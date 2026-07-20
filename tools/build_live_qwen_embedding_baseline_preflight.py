from __future__ import annotations

import os
from pathlib import Path

from recallpack.live_qwen_contract import (
    DEFAULT_COMPATIBLE_BASE_URL,
    derive_rerank_base_url,
)
from recallpack.live_qwen_embedding_baseline import (
    write_live_qwen_embedding_baseline_preflight_report,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TARGET = ROOT / "docs" / "submission" / "live-qwen-embedding-baseline-preflight.json"
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
    target = Path(
        os.environ.get(
            "RECALLPACK_LIVE_QWEN_EMBEDDING_BASELINE_PREFLIGHT_PATH",
            DEFAULT_TARGET,
        )
    )
    fixture_root = Path(
        os.environ.get(
            "RECALLPACK_LIVE_QWEN_EMBEDDING_BASELINE_FIXTURE",
            DEFAULT_FIXTURE_ROOT,
        )
    )

    report = write_live_qwen_embedding_baseline_preflight_report(
        target=target,
        fixture_root=fixture_root,
        compatible_base_url=compatible_base_url,
        rerank_base_url=rerank_base_url,
    )
    counts = report["request_role_counts"]
    print(f"preflight_status={report['preflight_status']}")
    print(f"trace_path={target}")
    print(f"expected_selected_sources={','.join(report['expected_selected_sources'])}")
    print(
        "request_role_counts="
        f"embedding={counts['embedding']} "
        f"rerank={counts['rerank']}"
    )
    print("network_calls_made=false")


if __name__ == "__main__":
    main()
