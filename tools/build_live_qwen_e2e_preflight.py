from __future__ import annotations

import os
from pathlib import Path

from recallpack.live_qwen_contract import (
    DEFAULT_COMPATIBLE_BASE_URL,
    DEFAULT_TEXT_MODEL,
    derive_rerank_base_url,
)
from recallpack.live_qwen_e2e import write_live_qwen_e2e_preflight_report


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TARGET = ROOT / "docs" / "submission" / "live-qwen-e2e-preflight.json"
DEFAULT_FIXTURE_ROOT = ROOT / "fixtures" / "project-a"


def main() -> None:
    compatible_base_url = os.environ.get(
        "RECALLPACK_QWEN_BASE_URL",
        DEFAULT_COMPATIBLE_BASE_URL,
    )
    rerank_base_url = os.environ.get(
        "RECALLPACK_QWEN_RERANK_BASE_URL",
        derive_rerank_base_url(compatible_base_url),
    )
    text_model = os.environ.get("RECALLPACK_QWEN_TEXT_MODEL", DEFAULT_TEXT_MODEL)
    target = Path(os.environ.get("RECALLPACK_LIVE_QWEN_E2E_PREFLIGHT_PATH", DEFAULT_TARGET))
    fixture_root = Path(
        os.environ.get("RECALLPACK_LIVE_QWEN_E2E_FIXTURE", DEFAULT_FIXTURE_ROOT)
    )

    report = write_live_qwen_e2e_preflight_report(
        target=target,
        fixture_root=fixture_root,
        compatible_base_url=compatible_base_url,
        rerank_base_url=rerank_base_url,
        text_model=text_model,
    )
    counts = report["request_role_counts"]
    print(f"preflight_status={report['preflight_status']}")
    print(f"trace_path={target}")
    print(f"expected_selected_sources={','.join(report['expected_selected_sources'])}")
    print(
        "request_role_counts="
        f"memory_decision={counts['memory_decision']} "
        f"embedding={counts['embedding']} "
        f"rerank={counts['rerank']} "
        f"patch_generation={counts['patch_generation']}"
    )
    print("network_calls_made=false")


if __name__ == "__main__":
    main()
