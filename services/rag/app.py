"""rag service — answers questions over a small grounded corpus.

Exposes:
- POST /rag/answer — RAG answer endpoint
- GET  /metrics    — Prometheus text format

Honors Track — TODO implementations required.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
import uuid

from fastapi import FastAPI, Request
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from pydantic import BaseModel
from starlette.responses import Response

SERVICE = os.environ.get("SERVICE_NAME", "rag")
app = FastAPI()

# Structured logger -- emits one JSON line per request that includes the
# X-Request-ID so cross-service logs can be joined by id (Task 4 in the
# learner guide).
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


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or request.headers.get("x-request-id") or str(uuid.uuid4())

    start = time.perf_counter()
    response = await call_next(request)
    elapsed_ms = (time.perf_counter() - start) * 1000.0

    LATENCY.labels(SERVICE, request.url.path).observe(elapsed_ms / 1000.0)
    REQUESTS.labels(SERVICE, request.url.path, str(response.status_code)).inc()

    response.headers["X-Request-ID"] = request_id

    logger.info(
        json.dumps(
            {
                "service": SERVICE,
                "request_id": request_id,
                "path": request.url.path,
                "status": response.status_code,
                "latency_ms": round(elapsed_ms, 3),
            }
        )
    )

    return response


class AnswerIn(BaseModel):
    question: str


DECLINE = "I do not have enough grounded information to answer that question."


CORPUS = [
    {
        "id": "rag-overview",
        "title": "Retrieval-Augmented Generation",
        "text": (
            "Retrieval-Augmented Generation, or RAG, combines retrieval with text generation. "
            "A retriever first finds relevant documents, then a generator answers using those documents. "
            "This helps keep answers grounded in provided sources."
        ),
    },
    {
        "id": "observability",
        "title": "Service Observability",
        "text": (
            "Observability helps operators understand whether a service is working. "
            "Useful signals include request counts, latency, error rates, healthchecks, and structured logs."
        ),
    },
    {
        "id": "microservices",
        "title": "Microservices Trade-Offs",
        "text": (
            "Microservices split a system into independent services. "
            "This improves separation of responsibilities and independent scaling, but it adds network calls, "
            "deployment complexity, and cross-service debugging problems."
        ),
    },
    {
        "id": "routing",
        "title": "Question Routing",
        "text": (
            "A router receives an inbound question, classifies it, generates a request ID, "
            "and forwards the request to the selected backend. The request ID should be forwarded "
            "with the X-Request-ID header so logs can be correlated across services."
        ),
    },
    {
        "id": "knowledge-graph",
        "title": "Knowledge Graph Service",
        "text": (
            "A knowledge graph service is useful for entity-focused questions. "
            "It can extract entities, represent relationships, and answer structured lookup questions."
        ),
    },
]


STOPWORDS = {
    "a",
    "an",
    "the",
    "is",
    "are",
    "was",
    "were",
    "to",
    "of",
    "in",
    "on",
    "for",
    "and",
    "or",
    "what",
    "who",
    "why",
    "how",
    "when",
    "where",
    "does",
    "do",
    "it",
    "this",
    "that",
    "with",
    "using",
    "use",
}


def tokenize(text: str) -> set[str]:
    tokens = re.findall(r"[a-zA-Z0-9]+", text.lower())
    return {token for token in tokens if token not in STOPWORDS}


def retrieve(question: str, k: int = 2) -> list[dict]:
    question_tokens = tokenize(question)

    scored_docs = []
    for doc in CORPUS:
        doc_tokens = tokenize(doc["title"] + " " + doc["text"])
        score = len(question_tokens & doc_tokens)

        if score > 0:
            scored_docs.append((score, doc))

    scored_docs.sort(key=lambda item: item[0], reverse=True)

    return [doc for _, doc in scored_docs[:k]]


def generate_grounded_answer(question: str, docs: list[dict]) -> str:
    q = question.lower()

    if not docs:
        return DECLINE

    if "rag" in q or "retrieval" in q:
        return (
            "RAG combines document retrieval with answer generation. "
            "The retriever finds relevant sources, and the answer is generated from those sources."
        )

    if "observability" in q or "metrics" in q or "latency" in q or "error" in q:
        return (
            "Observability shows whether a service is working by exposing signals such as "
            "request counts, latency, error rates, healthchecks, and structured logs."
        )

    if "microservice" in q or "monolith" in q or "architecture" in q:
        return (
            "Microservices improve separation of responsibilities and independent scaling, "
            "but they add network, deployment, and debugging complexity."
        )

    if "router" in q or "route" in q or "request id" in q or "x-request-id" in q:
        return (
            "The router classifies each question, generates a request ID, forwards the request "
            "to the selected backend, and uses X-Request-ID for cross-service log correlation."
        )

    if "knowledge graph" in q or "kg" in q or "entity" in q:
        return (
            "A knowledge graph service is useful for entity-focused questions because it can "
            "extract entities and answer structured relationship queries."
        )

    # Safe fallback: answer only from the top retrieved document.
    top_doc = docs[0]
    return top_doc["text"]


@app.post("/rag/answer")
def answer(payload: AnswerIn) -> dict:
    docs = retrieve(payload.question)
    answer_text = generate_grounded_answer(payload.question, docs)

    sources = [
        {
            "id": doc["id"],
            "title": doc["title"],
        }
        for doc in docs
    ]

    return {
        "answer": answer_text,
        "sources": sources,
    }


@app.get("/metrics")
def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)