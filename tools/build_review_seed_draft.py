from __future__ import annotations

import argparse
from pathlib import Path
import sys

from recallpack.review_seed_draft import build_r2_review_seed_draft


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build the credential-free R2 production review-seed draft."
    )
    parser.add_argument("--repository-root", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--created-at", required=True)
    parser.add_argument("--evaluator-image-digest", required=True)
    parser.add_argument(
        "--platform",
        required=True,
        choices=("linux/amd64", "linux/arm64"),
    )
    args = parser.parse_args()
    try:
        result = build_r2_review_seed_draft(
            repository_root=Path(args.repository_root),
            output_dir=args.output_dir,
            created_at=args.created_at,
            evaluator_image_digest=args.evaluator_image_digest,
            platform=args.platform,
        )
    except (FileExistsError, OSError, ValueError) as exc:
        print(f"status=review_seed_draft_failed error={type(exc).__name__}", file=sys.stderr)
        return 1
    print("status=review_seed_draft_built")
    print(f"seed_draft={result.seed_draft_path}")
    print(f"artifact_count={result.artifact_count}")
    print(f"execution_slot_count={result.execution_slot_count}")
    print("credentials_read=false")
    print("network_calls_made=false")
    print("authorizes_execution=false")
    return 0


if __name__ == "__main__":
    sys.exit(main())
