from __future__ import annotations

import argparse
from pathlib import Path
import sys

from recallpack.review_seed_generation import generate_review_seed_package
from recallpack.secure_files import SecureFileError


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate one credential-free canonical RecallPack review seed export."
    )
    parser.add_argument("--repository-root", required=True)
    parser.add_argument("--seed-draft", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()

    try:
        result = generate_review_seed_package(
            repository_root=Path(args.repository_root),
            seed_draft=args.seed_draft,
            output_dir=args.output_dir,
        )
    except (FileExistsError, OSError, ValueError) as exc:
        print(
            f"status=review_seed_generation_failed error={_error_code(exc)}",
            file=sys.stderr,
        )
        return 1

    print("status=review_seed_generated")
    print(f"review_seed_sha256={result.review_seed_sha256}")
    print(f"external_artifact_slot_count={result.slot_count}")
    print("credentials_read=false")
    print("network_calls_made=false")
    print("authorizes_execution=false")
    return 0


def _error_code(exc: BaseException) -> str:
    if isinstance(exc, FileExistsError):
        return "output_target_exists"
    if isinstance(exc, SecureFileError):
        return "invalid_seed_generation_path"
    if isinstance(exc, ValueError):
        return "invalid_review_seed"
    return "seed_generation_io_failed"


if __name__ == "__main__":
    sys.exit(main())
