from __future__ import annotations

import json
import os
from pathlib import Path
import re
from datetime import datetime, timezone

from recallpack.live_qwen_contract import (
    DEFAULT_COMPATIBLE_BASE_URL,
    DEFAULT_TEXT_MODEL,
    derive_rerank_base_url,
)
from recallpack.evaluation import load_hero_fixture
from recallpack.live_qwen_e2e import _scenario_base, write_live_qwen_e2e_report


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TARGET = ROOT / "docs" / "submission" / "live-qwen-e2e-trace.json"
DEFAULT_FIXTURE_ROOT = ROOT / "fixtures" / "project-a"


def main() -> None:
    if os.environ.get("RECALLPACK_ENABLE_LIVE_QWEN") != "1":
        raise SystemExit("Set RECALLPACK_ENABLE_LIVE_QWEN=1 to run live Qwen.")
    if os.environ.get("RECALLPACK_LIVE_QWEN_E2E_APPROVED") != "1":
        raise SystemExit(
            "Set RECALLPACK_LIVE_QWEN_E2E_APPROVED=1 after explicit E2E approval."
        )

    api_key = os.environ.get("DASHSCOPE_API_KEY", "")
    if not api_key:
        raise SystemExit("DASHSCOPE_API_KEY is required for live Qwen E2E.")

    compatible_base_url = os.environ.get(
        "RECALLPACK_QWEN_BASE_URL",
        DEFAULT_COMPATIBLE_BASE_URL,
    )
    rerank_base_url = os.environ.get(
        "RECALLPACK_QWEN_RERANK_BASE_URL",
        derive_rerank_base_url(compatible_base_url),
    )
    text_model = os.environ.get("RECALLPACK_QWEN_TEXT_MODEL", DEFAULT_TEXT_MODEL)
    target = Path(os.environ.get("RECALLPACK_LIVE_QWEN_E2E_TRACE_PATH", DEFAULT_TARGET))
    fixture_root = Path(os.environ.get("RECALLPACK_LIVE_QWEN_E2E_FIXTURE", DEFAULT_FIXTURE_ROOT))

    try:
        report = write_live_qwen_e2e_report(
            target=target,
            fixture_root=fixture_root,
            api_key=api_key,
            compatible_base_url=compatible_base_url,
            rerank_base_url=rerank_base_url,
            text_model=text_model,
        )
    except Exception as exc:
        report = _failed_report(
            exc=exc,
            target=target,
            fixture_root=fixture_root,
            api_key=api_key,
            compatible_base_url=compatible_base_url,
            rerank_base_url=rerank_base_url,
            text_model=text_model,
        )
        _write_json(target, report)
        print(f"live_status={report['live_status']}")
        print(f"trace_path={target}")
        print(f"selected_sources={','.join(report['selected_sources'])}")
        print(f"failure_kind={report['failure_kind']}")
        raise SystemExit(1) from exc

    usage = report["actual_qwen_token_usage"]
    print(f"live_status={report['live_status']}")
    print(f"trace_path={target}")
    print(f"selected_sources={','.join(report['selected_sources'])}")
    print(
        "actual_qwen_token_usage="
        f"memory={usage['memory_decision_total_tokens']} "
        f"embedding={usage['embedding_total_tokens']} "
        f"rerank={usage['rerank_total_tokens']} "
        f"patch_generation={usage['patch_generation_total_tokens']}"
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
    text_model: str,
) -> dict[str, object]:
    fixture = _load_failure_fixture(fixture_root)
    project_id = (
        fixture.gold.get("project_id", "project-a") if fixture is not None else "project-a"
    )
    stale_sources = (
        list(fixture.gold.get("stale_sources", ["session-a:turn-001"]))
        if fixture is not None
        else ["session-a:turn-001"]
    )
    required_sources = (
        list(fixture.gold.get("required_sources", [])) if fixture is not None else []
    )
    scenario = _scenario_base(fixture) if fixture is not None else "hero_observe_compile"
    return {
        "live_qwen_run": True,
        "live_status": "live_e2e_failed",
        "run_completed_at": _utc_timestamp(),
        "scenario": scenario,
        "project_id": project_id,
        "fixture_root_name": fixture_root.name,
        "region_base_url": compatible_base_url.rstrip("/"),
        "rerank_base_url": rerank_base_url.rstrip("/"),
        "model_name": text_model,
        "trace_artifact": target.name,
        "observed_event_count": 0,
        "observe_status_counts": {},
        "selected_sources": [],
        "excluded_sources_checked": stale_sources,
        "checks": {
            "all_observe_events_completed": False,
            "required_sources_selected": False,
            "stale_sources_excluded": False,
            "active_retry_selected": False,
            "project_preference_selected": False,
            "stale_retry_excluded": False,
            "compile_status_ok": False,
            "baseline_downstream_fails": False,
            "baseline_downstream_reported": False,
            "recallpack_downstream_passes": False,
        },
        "expected_required_sources": required_sources,
        "live_status_required_checks": [
            "all_observe_events_completed",
            "required_sources_selected",
            "stale_sources_excluded",
            "compile_status_ok",
            "baseline_downstream_reported",
            "recallpack_downstream_passes",
        ],
        "baseline_selection": {
            "context_source": "live_embedding_top_n_rerank_raw_history",
            "selected_sources": [],
        },
        "downstream_patch_generation": {
            "baseline": {"summary": {"passed": 0, "failed": 0}},
            "recallpack": {"summary": {"passed": 0, "failed": 0}},
            "same_provider_contract": False,
            "used_gold_patch_variants": False,
        },
        "provider_traces": [],
        "actual_qwen_token_usage": {
            "memory_decision_total_tokens": 0,
            "embedding_total_tokens": 0,
            "rerank_total_tokens": 0,
            "patch_generation_total_tokens": 0,
        },
        "failure_kind": type(exc).__name__,
        "failure_summary": _sanitize_failure_summary(str(exc), api_key),
        "credentials_recorded": False,
        "failure_trace_is_sanitized": True,
    }


def _load_failure_fixture(fixture_root: Path):
    try:
        return load_hero_fixture(fixture_root)
    except Exception:
        return None


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


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


if __name__ == "__main__":
    main()
