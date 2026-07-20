from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from recallpack.providers import (
    QwenCloudHTTPClient,
    QwenEmbeddingProvider,
    QwenMemoryDecisionProvider,
    QwenRerankProvider,
    ProviderTrace,
    TEXT_MODEL,
    sanitized_provider_trace_records,
)


DEFAULT_COMPATIBLE_BASE_URL = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
DEFAULT_RERANK_BASE_URL = "https://dashscope-intl.aliyuncs.com/compatible-api/v1"
DEFAULT_TEXT_MODEL = TEXT_MODEL


def derive_rerank_base_url(compatible_base_url: str) -> str:
    stripped = compatible_base_url.rstrip("/")
    if stripped.endswith("/compatible-mode/v1"):
        return stripped[: -len("/compatible-mode/v1")] + "/compatible-api/v1"
    return stripped


def build_live_qwen_contract_report(
    api_key: str,
    compatible_base_url: str = DEFAULT_COMPATIBLE_BASE_URL,
    rerank_base_url: str = DEFAULT_RERANK_BASE_URL,
    text_model: str = DEFAULT_TEXT_MODEL,
    opener: Any | None = None,
) -> dict[str, Any]:
    client = QwenCloudHTTPClient(api_key=api_key, opener=opener)

    memory_provider = QwenMemoryDecisionProvider(
        client=client,
        compatible_base_url=compatible_base_url,
        model_id=text_model,
    )
    memory_decision = memory_provider.decide_memory_operation(
        event_text=json.dumps(
            {
                "project_id": "project-a",
                "session_id": "contract-smoke",
                "event_id": "turn-002",
                "source_ref": "contract-smoke:turn-002",
                "sequence_no": 2,
                "actor": "user",
                "kind": "message",
                "observed_at": "2026-06-24T00:04:00Z",
                "text": (
                    "After rate-limit failures, use five attempts with "
                    "exponential backoff in the retry helper."
                ),
            },
            sort_keys=True,
        ),
        candidate_payloads=[
            {
                "type": "decision",
                "scope": "component:retry",
                "subject": "retry_policy",
                "source_ref": "session-a:turn-001",
                "text": "Use three attempts with a fixed delay.",
            }
        ],
        tool_schema={"name": "decide_memory_operation"},
    )

    embedding_provider = QwenEmbeddingProvider(
        client=client,
        compatible_base_url=compatible_base_url,
    )
    query_embedding = embedding_provider.embed_query(
        "Update the retry helper to the current project policy."
    )
    document_embedding = embedding_provider.embed_document(
        "Use five attempts with exponential backoff."
    )

    rerank_provider = QwenRerankProvider(
        client=client,
        rerank_base_url=rerank_base_url,
    )
    rerank = rerank_provider.rerank(
        goal="Update the retry helper to the current project policy.",
        documents=["Use five attempts with exponential backoff."],
        instruct="Rank active project memories for a coding-agent handoff.",
    )

    traces = [
        memory_decision.trace,
        query_embedding.trace,
        document_embedding.trace,
        rerank.trace,
    ]
    return {
        "live_qwen_run": True,
        "live_status": "live_contract_passed",
        "region_base_url": compatible_base_url.rstrip("/"),
        "rerank_base_url": rerank_base_url.rstrip("/"),
        "provider_traces": sanitized_provider_trace_records(traces),
        "actual_qwen_token_usage": _actual_qwen_token_usage(traces),
        "contract_summary": [
            "memory_decision live trace captured",
            "text-embedding-v4 live trace captured",
            "qwen3-rerank live trace captured",
        ],
        "qwen_model_work": [
            "memory extraction, type classification, and supersession judgment",
            "candidate memory retrieval with text-embedding-v4",
            "precision reranking with qwen3-rerank",
        ],
        "deterministic_runtime_work": [
            "event ordering and lease fencing",
            "schema validation and failure handling",
            "active/superseded lifecycle filtering",
            "512-token budget selection",
            "PACK.md and recallpack.json assembly",
        ],
    }


def write_live_qwen_contract_report(
    target: str | Path,
    api_key: str,
    compatible_base_url: str = DEFAULT_COMPATIBLE_BASE_URL,
    rerank_base_url: str = DEFAULT_RERANK_BASE_URL,
    text_model: str = DEFAULT_TEXT_MODEL,
    opener: Any | None = None,
) -> dict[str, Any]:
    report = build_live_qwen_contract_report(
        api_key=api_key,
        compatible_base_url=compatible_base_url,
        rerank_base_url=rerank_base_url,
        text_model=text_model,
        opener=opener,
    )
    target_path = Path(target)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    )
    return report


def _actual_qwen_token_usage(traces: list[ProviderTrace]) -> dict[str, int]:
    memory_total = 0
    embedding_total = 0
    rerank_total = 0
    for trace in traces:
        total_tokens = int(trace.usage.get("total_tokens", 0) or 0)
        if trace.provider_role == "memory_decision":
            memory_total += total_tokens
        elif trace.provider_role == "embedding":
            embedding_total += total_tokens
        elif trace.provider_role == "rerank":
            rerank_total += total_tokens
    return {
        "memory_decision_total_tokens": memory_total,
        "embedding_total_tokens": embedding_total,
        "rerank_total_tokens": rerank_total,
    }
