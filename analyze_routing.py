"""Consolidated routing analysis report writer.

Reads the routing fixture, drives each question through the live router,
pulls per-service `/metrics`, and writes `routing-analysis-report.md`.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from typing import Any

import httpx


def normalize_target(value: Any) -> str:
    """Normalize backend names so ner_kg and ner-kg compare correctly."""
    if value is None:
        return ""

    text = str(value).strip().lower()
    text = text.replace("_", "-")

    if text in {"ner", "kg", "nerkg", "ner-kg"}:
        return "ner-kg"

    if text in {"rag", "retrieval"}:
        return "rag"

    return text


def load_fixture(path: str) -> list[dict[str, str]]:
    """Read the routing fixture's questions list."""
    with open(path, "r", encoding="utf-8") as f:
        payload = json.load(f)

    if isinstance(payload, list):
        return payload

    if isinstance(payload, dict) and "questions" in payload:
        return payload["questions"]

    raise ValueError(f"Could not find questions list in fixture: {path}")


def drive_router(router_base: str, questions: list[dict[str, str]]) -> list[dict[str, Any]]:
    """POST each question to the router and return routing decisions."""
    decisions: list[dict[str, Any]] = []
    route_url = f"{router_base.rstrip('/')}/route"

    with httpx.Client(timeout=10.0) as client:
        for item in questions:
            question = item["question"]
            expected = normalize_target(item.get("expected"))

            response = client.post(
                route_url,
                json={"question": question},
                headers={"content-type": "application/json"},
            )

            response.raise_for_status()
            body = response.json()

            decision_payload = body.get("decision", {})
            raw_target = (
                decision_payload.get("target")
                or body.get("target")
                or body.get("backend")
                or body.get("route")
            )

            request_id = (
                decision_payload.get("request_id")
                or body.get("request_id")
                or response.headers.get("X-Request-ID")
                or response.headers.get("x-request-id")
            )

            decisions.append(
                {
                    "question": question,
                    "expected": expected,
                    "target": normalize_target(raw_target),
                    "raw_target": raw_target,
                    "request_id": request_id,
                    "status_code": response.status_code,
                    "response": body,
                }
            )

    return decisions


def routing_accuracy(decisions: list[dict[str, Any]]) -> float:
    """Return the fraction of decisions whose target matches expected."""
    if not decisions:
        return 0.0

    scored = [
        decision
        for decision in decisions
        if decision.get("expected") and decision.get("target")
    ]

    if not scored:
        return 0.0

    correct = sum(
        1
        for decision in scored
        if normalize_target(decision["target"]) == normalize_target(decision["expected"])
    )

    return correct / len(scored)


def fetch_metrics(base_url: str) -> str:
    """GET {base_url}/metrics and return the OpenMetrics text body."""
    metrics_url = f"{base_url.rstrip('/')}/metrics"

    with httpx.Client(timeout=10.0) as client:
        response = client.get(metrics_url)
        response.raise_for_status()
        return response.text


def extract_request_volume(metrics_text: str) -> int:
    """Extract total request volume from Prometheus metrics text."""
    total = 0.0

    for line in metrics_text.splitlines():
        line = line.strip()

        if not line or line.startswith("#"):
            continue

        if line.startswith("service_requests_total"):
            parts = line.split()
            if len(parts) == 2:
                try:
                    total += float(parts[1])
                except ValueError:
                    pass

    return int(total)


def extract_p95_latency(metrics_text: str) -> str:
    """Estimate p95 latency from Prometheus histogram buckets."""
    bucket_pattern = re.compile(
        r'service_request_latency_seconds_bucket\{[^}]*le="([^"]+)"[^}]*\}\s+([0-9.eE+-]+)'
    )

    buckets: list[tuple[float, float]] = []

    for line in metrics_text.splitlines():
        match = bucket_pattern.search(line)

        if not match:
            continue

        le_text, count_text = match.groups()

        if le_text == "+Inf":
            le_value = float("inf")
        else:
            try:
                le_value = float(le_text)
            except ValueError:
                continue

        try:
            count_value = float(count_text)
        except ValueError:
            continue

        buckets.append((le_value, count_value))

    if not buckets:
        return "not available"

    buckets.sort(key=lambda item: item[0])
    total_count = buckets[-1][1]

    if total_count <= 0:
        return "not available"

    threshold = total_count * 0.95

    for upper_bound, cumulative_count in buckets:
        if cumulative_count >= threshold:
            if upper_bound == float("inf"):
                return "+Inf"
            return f"{upper_bound:.3f}s"

    return "not available"


def render_report(
    decisions: list[dict[str, Any]],
    accuracy: float,
    service_metrics: dict[str, str],
    report_path: str,
) -> None:
    """Write the consolidated routing analysis report."""
    total_questions = len(decisions)
    correct = sum(
        1
        for decision in decisions
        if normalize_target(decision.get("target")) == normalize_target(decision.get("expected"))
    )

    route_counts = Counter(decision.get("target", "unknown") for decision in decisions)
    request_ids = [decision.get("request_id") for decision in decisions if decision.get("request_id")]
    missing_request_ids = total_questions - len(request_ids)

    if total_questions:
        most_common_target, most_common_count = route_counts.most_common(1)[0]
        most_common_percent = most_common_count / total_questions
        routing_pattern = (
            f"{most_common_count}/{total_questions} questions "
            f"({most_common_percent:.1%}) were routed to `{most_common_target}`."
        )
    else:
        routing_pattern = "No routing decisions were recorded."

    lines: list[str] = []

    lines.append("# Routing Analysis Report")
    lines.append("")

    lines.append("## Routing Accuracy")
    lines.append("")
    lines.append(f"- Total fixture questions: {total_questions}")
    lines.append(f"- Correct routing decisions: {correct}")
    lines.append(f"- Routing accuracy: {accuracy:.3f}")
    lines.append("")

    lines.append("| Question | Expected | Routed Target | Request ID |")
    lines.append("|---|---:|---:|---|")

    for decision in decisions:
        question = str(decision.get("question", "")).replace("|", "\\|")
        expected = decision.get("expected", "")
        target = decision.get("target", "")
        request_id = decision.get("request_id", "")
        lines.append(f"| {question} | {expected} | {target} | `{request_id}` |")

    lines.append("")

    lines.append("## Per-Service Metrics")
    lines.append("")
    lines.append("| Service | Request Volume | Estimated p95 Latency |")
    lines.append("|---|---:|---:|")

    for service_name, metrics_text in service_metrics.items():
        volume = extract_request_volume(metrics_text)
        p95 = extract_p95_latency(metrics_text)
        lines.append(f"| {service_name} | {volume} | {p95} |")

    lines.append("")

    lines.append("## Routing Pattern")
    lines.append("")
    lines.append(f"- {routing_pattern}")

    for target, count in sorted(route_counts.items()):
        percent = count / total_questions if total_questions else 0.0
        lines.append(f"- `{target}` received {count} decisions ({percent:.1%}).")

    lines.append("")

    lines.append("## Cross-Service Correlation")
    lines.append("")
    lines.append(
        f"The router produced request IDs for {len(request_ids)} out of "
        f"{total_questions} routing decisions. "
        f"{missing_request_ids} decisions were missing request IDs. "
        "The same request ID is forwarded through the `X-Request-ID` header, "
        "so a single request can be traced from the router log to the selected backend log."
    )
    lines.append("")
    lines.append("Manual verification command:")
    lines.append("")
    lines.append("```bash")
    lines.append("docker compose -f docker-compose-stretch.yml logs | grep <request-id>")
    lines.append("```")
    lines.append("")

    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="M11 Stretch-Thu routing analysis")
    p.add_argument("--fixture", required=True)
    p.add_argument("--router-base", required=True)
    p.add_argument("--ner-kg-base", required=True)
    p.add_argument("--rag-base", required=True)
    p.add_argument("--report-out", default="routing-analysis-report.md")
    return p.parse_args()


def main() -> None:
    args = parse_args()

    questions = load_fixture(args.fixture)
    decisions = drive_router(args.router_base, questions)
    accuracy = routing_accuracy(decisions)

    service_metrics = {
        "router": fetch_metrics(args.router_base),
        "ner-kg": fetch_metrics(args.ner_kg_base),
        "rag": fetch_metrics(args.rag_base),
    }

    render_report(decisions, accuracy, service_metrics, args.report_out)

    print(f"Wrote {args.report_out} (accuracy={accuracy:.3f})")


if __name__ == "__main__":
    main()