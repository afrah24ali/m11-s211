"""router service — classifies a question and forwards to the right backend.

Exposes:
- POST /route      — classify + forward; returns the backend's response plus the routing decision
- GET  /metrics    — Prometheus text format
- GET  /decisions  — recent routing decisions
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from collections import deque
from typing import Literal

import httpx
from fastapi import FastAPI, Request
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from pydantic import BaseModel
from starlette.responses import Response

SERVICE = os.environ.get("SERVICE_NAME", "router")

# These defaults work inside Docker Compose if the services listen on port 8000.
# In docker-compose-stretch.yml you can override them with:
# NER_KG_URL=http://ner-kg:8101
# RAG_URL=http://rag:8102
NER_KG_URL = (
    os.environ.get("NER_KG_URL")
    or os.environ.get("NER_KG_BASE")
    or "http://localhost:8101"
)

RAG_URL = (
    os.environ.get("RAG_URL")
    or os.environ.get("RAG_BASE")
    or "http://localhost:8102"
)

app = FastAPI()

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(SERVICE)

REQUESTS = Counter(
    "service_requests_total",
    "Requests per endpoint",
    ["service", "endpoint", "status"],
)

LATENCY = Histogram(
    "service_request_latency_seconds",
    "Request latency by endpoint",
    ["service", "endpoint"],
)

ROUTING_DECISIONS = Counter(
    "router_decisions_total",
    "Routing decisions by target backend",
    ["target"],
)

_DECISIONS: deque[dict] = deque(maxlen=1000)


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or request.headers.get("x-request-id") or str(uuid.uuid4())
    request.state.request_id = request_id

    start = time.perf_counter()
    response = await call_next(request)
    elapsed = time.perf_counter() - start

    LATENCY.labels(SERVICE, request.url.path).observe(elapsed)
    REQUESTS.labels(SERVICE, request.url.path, str(response.status_code)).inc()

    response.headers["X-Request-ID"] = request_id

    return response


class RouteIn(BaseModel):
    question: str


Target = Literal["ner-kg", "rag"]


def classify_question(question: str) -> Target:
    """Classify a question as either ner-kg or rag."""

    q = question.lower().strip()

    ner_kg_keywords = [
        "entity",
        "entities",
        "extract",
        "ner",
        "named entity",
        "knowledge graph",
        "kg",
        "cypher",
        "relationship",
        "relations",
        "connected",
        "link",
        "node",
        "edge",
        "graph",
        "who is the ceo",
        "ceo of",
        "founder",
        "founded",
        "located in",
        "headquartered",
        "capital of",
        "person",
        "organization",
        "company",
    ]

    rag_keywords = [
        "summarize",
        "summary",
        "explain",
        "describe",
        "why",
        "how",
        "compare",
        "contrast",
        "advantages",
        "disadvantages",
        "trade-off",
        "tradeoff",
        "document",
        "article",
        "passage",
        "context",
        "according to",
        "based on",
        "source",
        "sources",
        "retrieval",
        "rag",
        "grounded",
        "answer from",
    ]

    ner_kg_score = sum(1 for keyword in ner_kg_keywords if keyword in q)
    rag_score = sum(1 for keyword in rag_keywords if keyword in q)

    # Strong KG patterns.
    if q.startswith("extract") or "extract entities" in q:
        return "ner-kg"

    if "cypher" in q or "knowledge graph" in q or " kg " in f" {q} ":
        return "ner-kg"

    if "who is the ceo" in q or "ceo of" in q:
        return "ner-kg"

    if "founder" in q or "founded" in q:
        return "ner-kg"

    # Strong RAG patterns.
    if q.startswith("summarize") or q.startswith("explain") or q.startswith("compare"):
        return "rag"

    if "according to" in q or "based on the document" in q or "based on this document" in q:
        return "rag"

    if rag_score > ner_kg_score:
        return "rag"

    if ner_kg_score > rag_score:
        return "ner-kg"

    # Default: open-ended questions usually belong to RAG.
    return "rag"


def is_extraction_question(question: str) -> bool:
    q = question.lower()
    return (
        "extract" in q
        or "entities" in q
        or "entity" in q
        or "named entity" in q
        or "ner" in q
    )


async def forward_to_backend(target: Target, question: str, request_id: str) -> dict:
    """Forward the question to the chosen backend and return its JSON response."""

    headers = {
        "X-Request-ID": request_id,
        "content-type": "application/json",
    }

    timeout = httpx.Timeout(10.0)

    async with httpx.AsyncClient(timeout=timeout) as client:
        if target == "ner-kg":
            if is_extraction_question(question):
                url = f"{NER_KG_URL.rstrip('/')}/extract"
                payload = {"text": question}
            else:
                url = f"{NER_KG_URL.rstrip('/')}/kg/query"
                payload = {
                    "cypher": question,
                    "question": question,
                }

        else:
            url = f"{RAG_URL.rstrip('/')}/rag/answer"
            payload = {"question": question}

        try:
            response = await client.post(url, headers=headers, json=payload)

            try:
                response_json = response.json()
            except Exception:
               response_json = {
            "error": "Backend did not return JSON",
            "text": response.text,
        }

            return {
        "backend_url": url,
        "status_code": response.status_code,
        "response": response_json,
    }

        except httpx.RequestError as exc:
            return {
        "backend_url": url,
        "status_code": 503,
        "response": {
            "error": "Backend unavailable",
            "detail": str(exc),
        },
    }


@app.post("/route")
async def route(payload: RouteIn, request: Request) -> dict:
    request_id = request.state.request_id
    target = classify_question(payload.question)

    ROUTING_DECISIONS.labels(target).inc()

    backend_response = await forward_to_backend(
        target=target,
        question=payload.question,
        request_id=request_id,
    )

    decision = {
        "request_id": request_id,
        "question": payload.question,
        "target": target,
        "backend_status_code": backend_response.get("status_code"),
        "ts": time.time(),
    }

    _DECISIONS.append(decision)

    logger.info(
        json.dumps(
            {
                "service": SERVICE,
                "event": "routing_decision",
                "request_id": request_id,
                "question": payload.question,
                "target": target,
                "backend_status_code": backend_response.get("status_code"),
            }
        )
    )

    return {
        "decision": decision,
        "target": target,
        "request_id": request_id,
        "backend_response": backend_response,
    }


@app.get("/decisions")
def decisions(limit: int = 1000) -> dict:
    return {"decisions": list(_DECISIONS)[-limit:]}


@app.get("/metrics")
def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)