from __future__ import annotations

import json
import os
from pathlib import Path
import re

from recallpack.live_qwen_contract import (
    DEFAULT_COMPATIBLE_BASE_URL,
    derive_rerank_base_url,
)
from recallpack.live_qwen_embedding_baseline import (
    write_live_qwen_embedding_baseline_report,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TARGET = ROOT / "docs" / "submission" / "live-qwen-embedding-baseline-trace.json"
DEFAULT_FIXTURE_ROOT = ROOT / "fixtures" / "project-a"


def main() -> None:
    if os.environ.get("RECALLPACK_ENABLE_LIVE_QWEN") != "1":
        raise SystemExit("Set RECALLPACK_ENABLE_LIVE_QWEN=1 to run live Qwen.")
    if os.environ.get("RECALLPACK_LIVE_QWEN_EMBEDDING_BASELINE_APPROVED") != "1":
        raise SystemExit(
            "Set RECALLPACK_LIVE_QWEN_EMBEDDING_BASELINE_APPROVED=1 after explicit approval."
        )

    api_key = os.environ.get("DASHSCOPE_API_KEY", "")
    if not api_key:
        raise SystemExit("DASHSCOPE_API_KEY is required for live Qwen embedding baseline.")

    compatible_base_url = os.environ.get(
        "RECALLPACK_QWEN_BASE_URL",
        DEFAULT_COMPATIBLE_BASE_URL,
    )
    rerank_base_url = os.environ.get(
        "RECALLPACK_QWEN_RERANK_BASE_URL",
        derive_rerank_base_url(compatible_base_url),
    )
    target = Path(
        os.environ.get("RECALLPACK_LIVE_QWEN_EMBEDDING_BASELINE_TRACE_PATH", DEFAULT_TARGET)
    )
    fixture_root = Path(
        os.environ.get(
            "RECALLPACK_LIVE_QWEN_EMBEDDING_BASELINE_FIXTURE",
            DEFAULT_FIXTURE_ROOT,
        )
    )

    try:
        report = write_live_qwen_embedding_baseline_report(
            target=target,
            fixture_root=fixture_root,
            api_key=api_key,
            compatible_base_url=compatible_base_url,
            rerank_base_url=rerank_base_url,
        )
    except Exception as exc:
        report = _failed_report(
            exc=exc,
            target=target,
            fixture_root=fixture_root,
            api_key=api_key,
            compatible_base_url=compatible_base_url,
            rerank_base_url=rerank_base_url,
        )
        _write_json(target, report)
        print(f"live_status={report['live_status']}")
        print(f"trace_path={target}")
        print(f"failure_kind={report['failure_kind']}")
        raise SystemExit(1) from exc

    usage = report["actual_qwen_token_usage"]
    print(f"live_status={report['live_status']}")
    print(f"trace_path={target}")
    print(f"selected_sources={','.join(report['selected_sources'])}")
    print(
        "actual_qwen_token_usage="
        f"embedding={usage['embedding_total_tokens']} "
        f"rerank={usage['rerank_total_tokens']}"
    )
    print(f"provider_trace_count={len(report['provider_traces'])}")


def _failed_report(
    *,
    exc: Exception,
    target: Path,
    fixture_root: Path,
    api_key: str,
    compatible_base_url: str,
    rerank_base_url: str,
) -> dict[str, object]:
    return {
        "live_qwen_run": True,
        "live_status": "live_embedding_baseline_failed",
        "scenario": "hero_real_embedding_raw_history_baseline",
        "project_id": "project-a",
        "fixture_root_name": fixture_root.name,
        "region_base_url": compatible_base_url.rstrip("/"),
        "rerank_base_url": rerank_base_url.rstrip("/"),
        "trace_artifact": target.name,
        "selected_sources": [],
        "checks": {
            "stale_retry_selected": False,
            "active_retry_selected": False,
            "project_preference_selected": False,
            "downstream_baseline_fails": False,
        },
        "provider_traces": [],
        "actual_qwen_token_usage": {
            "embedding_total_tokens": 0,
            "rerank_total_tokens": 0,
        },
        "failure_kind": type(exc).__name__,
        "failure_summary": _sanitize_failure_summary(str(exc), api_key),
        "credentials_recorded": False,
        "failure_trace_is_sanitized": True,
    }


def _sanitize_failure_summary(text: str, api_key: str) -> str:
    sanitized = text.replace(api_key, "[redacted]") if api_key else text
    sanitized = re.sub(r"sk-[A-Za-z0-9_-]{8,}", "sk-[redacted]", sanitized)
    return sanitized[:1000]


def _write_json(target: Path, payload: dict[str, object]) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
