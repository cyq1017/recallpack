from __future__ import annotations

import argparse
from pathlib import Path
import sys

from recallpack.submission_bundle import build_submission_bundle


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the sanitized RecallPack submission bundle.")
    parser.add_argument(
        "--target",
        default="dist/recallpack-submission",
        help="Output directory. Must not already exist.",
    )
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parents[1]
    result = build_submission_bundle(project_root, project_root / args.target)
    print(f"Built submission bundle: {result.target}")
    print(f"Files: {len(result.files)}")
    for category, findings in result.scan.items():
        print(f"{category}: {len(findings)}")
        for finding in findings:
            print(f"  - {finding}")

    if any(result.scan.values()):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
