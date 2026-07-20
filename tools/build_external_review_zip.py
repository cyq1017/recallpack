from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import zipfile
from typing import Any


SCRIPT_ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
if str(SCRIPT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT / "src"))

from recallpack.submission_bundle import scan_submission_bundle  # noqa: E402


def build_external_review_zip(source: Path, archive: Path) -> dict[str, Any]:
    source = source.resolve()
    archive = archive.resolve()
    _assert_sanitized_bundle(source)
    if archive.exists():
        raise FileExistsError(f"External review archive already exists: {archive}")

    scan = scan_submission_bundle(source)
    if any(scan.values()):
        raise ValueError(f"Source bundle scan is not clean: {scan}")

    files = _bundle_files(source)
    prompt = _external_review_prompt()
    manifest = {
        "title": "RecallPack external review archive",
        "source_kind": "sanitized_bundle",
        "bundle_root": source.name,
        "bundle_file_count": len(files),
        "extra_files": [
            "EXTERNAL_REVIEW_PROMPT.md",
            "EXTERNAL_REVIEW_MANIFEST.json",
        ],
        "source_scan_clean": True,
        "source_scan": scan,
        "requires_credentials": False,
        "network_calls_made": False,
        "no_public_action_performed": True,
        "upload_performed": False,
        "claim_boundary": (
            "Historical sanitized live Qwen E2E evidence is included; "
            "fresh M98 live Qwen rerun is included as failed evidence where "
            "lifecycle filtering held but downstream 3/3 did not reproduce."
        ),
    }

    archive.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive, mode="w", compression=zipfile.ZIP_DEFLATED) as zip_file:
        zip_file.writestr("EXTERNAL_REVIEW_PROMPT.md", prompt)
        zip_file.writestr(
            "EXTERNAL_REVIEW_MANIFEST.json",
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        )
        for path in files:
            relative = path.relative_to(source)
            zip_file.write(path, f"{source.name}/{relative.as_posix()}")

    return {
        "status": "ready_for_external_review_upload",
        "archive": archive,
        "source": source,
        "bundle_root": source.name,
        "bundle_file_count": len(files),
        "source_scan_clean": True,
        "requires_credentials": False,
        "network_calls_made": False,
        "no_public_action_performed": True,
        "upload_performed": False,
    }


def _assert_sanitized_bundle(source: Path) -> None:
    if not source.is_dir():
        raise FileNotFoundError(f"Source bundle does not exist: {source}")
    if not (source / "SUBMISSION_MANIFEST.md").is_file():
        raise ValueError(
            "External review archives must be built from a sanitized submission "
            "bundle containing SUBMISSION_MANIFEST.md, not the raw workspace."
        )


def _bundle_files(source: Path) -> list[Path]:
    files: list[Path] = []
    for path in source.rglob("*"):
        if path.is_symlink():
            relative = path.relative_to(source).as_posix()
            raise ValueError(f"Symlink is not allowed in external review archive: {relative}")
        if not path.is_file():
            continue
        relative = path.relative_to(source).as_posix()
        if _is_forbidden(relative):
            raise ValueError(f"Forbidden path in sanitized bundle: {relative}")
        files.append(path)
    return sorted(files)


def _is_forbidden(relative: str) -> bool:
    parts = relative.split("/")
    if "__pycache__" in parts or ".git" in parts:
        return True
    if relative == "AGENTS.md":
        return True
    if relative.startswith("docs/execution/"):
        return True
    if relative.startswith("dist/"):
        return True
    if relative.endswith(".pyc"):
        return True
    return False


def _external_review_prompt() -> str:
    return """# RecallPack External Review Prompt

You are reviewing RecallPack as an adversarial hackathon judge and senior
AI-agent systems engineer.

Review the attached sanitized bundle, not the private raw workspace. Focus on:

- whether the MemoryAgent positioning is obvious and differentiated;
- whether stale-aware memory lifecycle is actually implemented, not only
  described;
- whether `/observe` and `/compile` are technically defensible;
- whether the Qwen text, embedding, and rerank provider path is load-bearing
  without overstating local fake-provider execution;
- whether the downstream patch/test proof is fair and non-circular;
- whether the eight curated lifecycle regression fixtures are persuasive while
  not being claimed as a broad benchmark;
- whether README, demo copy, Devpost copy, and review packet have any overclaim;
- whether the public repository surface is fresh-clone runnable by a judge.

Important truthfulness boundaries:

- local tests and demo are credential-free and use deterministic fake providers;
- a historical sanitized live Qwen E2E trace is included;
- fresh M98 live Qwen rerun is included as `live_e2e_failed`; treat it as
  lifecycle-filtering evidence, not a passing downstream headline;
- the public ECS endpoint is an M104 credential-free runtime proof unless a
  newer redeploy is explicitly documented;
- raw full history is a reference, not a budget-comparable baseline;
- the local keyword-scored fake-embedding baseline is deterministic fixture
  evidence, not a broad benchmark.

Please return:

1. P0/P1/P2 issues blocking prize-grade submission quality.
2. Any wording that overclaims Qwen, benchmark breadth, live execution, or ECS.
3. Whether the core MemoryAgent contribution is clear in the first 60 seconds.
4. The smallest set of changes that would most improve winning odds.
5. Any parts that are strong enough to keep unchanged.
"""


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build a local-only RecallPack external review zip from a sanitized bundle."
    )
    parser.add_argument(
        "--source",
        required=True,
        help="Sanitized submission bundle root containing SUBMISSION_MANIFEST.md.",
    )
    parser.add_argument(
        "--target",
        required=True,
        help="Output .zip path. Must not already exist.",
    )
    args = parser.parse_args()

    payload = build_external_review_zip(Path(args.source), Path(args.target))
    printable = dict(payload)
    printable["archive"] = printable["archive"].as_posix()
    printable["source"] = printable["source"].as_posix()
    print(json.dumps(printable, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
