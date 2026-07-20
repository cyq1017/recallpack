from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from recallpack.trace_intake import sanitize_trace_file, validate_trace_file, validate_trace_payload


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate a consent-first sanitized RecallPack real-trace candidate."
    )
    parser.add_argument("--trace", required=True, help="Path to the sanitized trace JSON.")
    parser.add_argument(
        "--sanitize",
        action="store_true",
        help="Sanitize the input trace before validation.",
    )
    parser.add_argument(
        "--sanitized-out",
        help="Optional path to write the sanitized trace when --sanitize is used.",
    )
    parser.add_argument("--json-out", help="Optional path to write the validation report.")
    args = parser.parse_args()

    if args.sanitize:
        payload = sanitize_trace_file(args.trace)
        if args.sanitized_out:
            sanitized_output = Path(args.sanitized_out)
            sanitized_output.parent.mkdir(parents=True, exist_ok=True)
            sanitized_output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
        report = validate_trace_payload(payload)
        report["trace_file"] = Path(args.trace).name
        report["sanitized_input"] = True
    else:
        report = validate_trace_file(args.trace)
        report["sanitized_input"] = False
    if args.json_out:
        output = Path(args.json_out)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")

    print(f"status={report['status']}")
    print(f"event_count={report['event_count']}")
    print(f"session_count={report['session_count']}")
    print(f"promoted_to_submission_evidence={str(report['promoted_to_submission_evidence']).lower()}")
    if report["blockers"]:
        print("blockers=" + ",".join(report["blockers"]))
    return 1 if report["status"] == "blocked" else 0


if __name__ == "__main__":
    sys.exit(main())
