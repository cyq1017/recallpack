from __future__ import annotations

import json
from pathlib import Path

from recallpack.demo import build_demo_payload, discover_secondary_hero_fixture_roots


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    live_trace_path = ROOT / "docs" / "submission" / "live-qwen-trace.json"
    live_e2e_trace_path = ROOT / "docs" / "submission" / "live-qwen-e2e-trace.json"
    fresh_m98_trace_path = ROOT / "docs" / "submission" / "live-qwen-m98-rerun-trace.json"
    projectodyssey_trace_path = (
        ROOT / "docs" / "submission" / "projectodyssey-live-qwen-e2e-trace.json"
    )
    payload = build_demo_payload(
        ROOT / "fixtures" / "project-a",
        ROOT / "fixtures" / "micro-suite",
        live_qwen_trace_path=live_trace_path if live_trace_path.is_file() else None,
        live_qwen_e2e_trace_path=(
            live_e2e_trace_path if live_e2e_trace_path.is_file() else None
        ),
        fresh_m98_live_rerun_trace_path=(
            fresh_m98_trace_path if fresh_m98_trace_path.is_file() else None
        ),
        projectodyssey_live_qwen_e2e_trace_path=(
            projectodyssey_trace_path if projectodyssey_trace_path.is_file() else None
        ),
        secondary_fixture_roots=discover_secondary_hero_fixture_roots(ROOT),
    )
    target = ROOT / "web" / "demo-data.js"
    target.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    target.write_text(f"window.RECALLPACK_DEMO_DATA = {encoded};\n")


if __name__ == "__main__":
    main()
