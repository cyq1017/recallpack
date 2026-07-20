from __future__ import annotations

from pathlib import Path

from recallpack.submission_packet import build_review_packet


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    live_trace_path = ROOT / "docs" / "submission" / "live-qwen-trace.json"
    live_e2e_trace_path = ROOT / "docs" / "submission" / "live-qwen-e2e-trace.json"
    target = ROOT / "docs" / "submission" / "review-packet.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        build_review_packet(
            ROOT,
            live_qwen_trace_path=live_trace_path if live_trace_path.is_file() else None,
            live_qwen_e2e_trace_path=(
                live_e2e_trace_path if live_e2e_trace_path.is_file() else None
            ),
        )
    )


if __name__ == "__main__":
    main()
