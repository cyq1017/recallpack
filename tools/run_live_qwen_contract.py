from __future__ import annotations

import os
from pathlib import Path

from recallpack.live_qwen_contract import (
    DEFAULT_COMPATIBLE_BASE_URL,
    DEFAULT_TEXT_MODEL,
    derive_rerank_base_url,
    write_live_qwen_contract_report,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TARGET = ROOT / "docs" / "submission" / "live-qwen-trace.json"


def main() -> None:
    if os.environ.get("RECALLPACK_ENABLE_LIVE_QWEN") != "1":
        raise SystemExit("Set RECALLPACK_ENABLE_LIVE_QWEN=1 to run live Qwen.")
    if os.environ.get("RECALLPACK_LIVE_QWEN_APPROVED") != "1":
        raise SystemExit("Set RECALLPACK_LIVE_QWEN_APPROVED=1 after explicit approval.")

    api_key = os.environ.get("DASHSCOPE_API_KEY", "")
    if not api_key:
        raise SystemExit("DASHSCOPE_API_KEY is required for live Qwen.")

    compatible_base_url = os.environ.get(
        "RECALLPACK_QWEN_BASE_URL",
        DEFAULT_COMPATIBLE_BASE_URL,
    )
    rerank_base_url = os.environ.get(
        "RECALLPACK_QWEN_RERANK_BASE_URL",
        derive_rerank_base_url(compatible_base_url),
    )
    text_model = os.environ.get("RECALLPACK_QWEN_TEXT_MODEL", DEFAULT_TEXT_MODEL)
    target = Path(os.environ.get("RECALLPACK_LIVE_QWEN_TRACE_PATH", DEFAULT_TARGET))

    report = write_live_qwen_contract_report(
        target=target,
        api_key=api_key,
        compatible_base_url=compatible_base_url,
        rerank_base_url=rerank_base_url,
        text_model=text_model,
    )
    usage = report["actual_qwen_token_usage"]
    print(f"live_status={report['live_status']}")
    print(f"trace_path={target}")
    print(
        "actual_qwen_token_usage="
        f"memory={usage['memory_decision_total_tokens']} "
        f"embedding={usage['embedding_total_tokens']} "
        f"rerank={usage['rerank_total_tokens']}"
    )
    print(f"provider_trace_count={len(report['provider_traces'])}")


if __name__ == "__main__":
    main()
