from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Any


SCRIPT_ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
if str(SCRIPT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT / "src"))
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))

from recallpack.submission_bundle import (  # noqa: E402
    JUDGE_FIRST_RUN_COMMANDS,
    PUBLIC_DIRECTORIES,
    PUBLIC_FILES,
    PUBLIC_LOCAL_ONLY_FILES,
    PUBLIC_LOCAL_ONLY_FILE_SUFFIXES,
    PUBLIC_SUBMISSION_DOC_EXCLUDES,
    scan_submission_bundle,
)

try:
    from devpost_preflight import build_preflight
except ModuleNotFoundError:
    from tools.devpost_preflight import build_preflight


JUDGE_COMMANDS = list(JUDGE_FIRST_RUN_COMMANDS)

BUNDLE_REFERENCE_PATTERN = re.compile(rb"dist/recallpack-submission-\d{8}-\d{6}")

MANUAL_NEXT_STEPS = [
    "create a public GitHub repository from the sanitized bundle contents",
    "confirm the MIT license is detected by GitHub",
    "add the public repository URL to Devpost",
    "run the judge commands from the public repository root",
    "submit Devpost only after final user approval",
]


def build_public_repo_preflight(root: Path) -> dict[str, Any]:
    root = root.resolve()
    preflight = build_preflight(root)
    public_surface = _public_surface_root(root, preflight)
    checks = _checks(root, public_surface)
    ready = all(check["status"] == "passed" for check in checks)
    source_kind = "sanitized_bundle" if (public_surface / "SUBMISSION_MANIFEST.md").is_file() else "unknown"
    public_repo_url = preflight.get("public_repo_url")
    repo_url_recorded = bool(public_repo_url)

    return {
        "status": (
            "ready_for_public_repo_sync"
            if ready and repo_url_recorded
            else "ready_for_manual_public_repo_creation"
            if ready
            else "blocked_public_repo_preflight"
        ),
        "ready": ready,
        "root": root.as_posix(),
        "publish_source": public_surface.as_posix(),
        "source_kind": source_kind,
        "must_publish_bundle_not_raw_workspace": True,
        "public_repo_url": public_repo_url,
        "remote_sync_verified": False,
        "remote_sync_note": (
            "Public repository URL is recorded, but this local-only preflight "
            "does not prove the latest sanitized bundle has been pushed to the "
            "remote GitHub repository."
            if repo_url_recorded
            else "No public repository URL is recorded."
        ),
        "checks": checks,
        "judge_commands": JUDGE_COMMANDS,
        "manual_next_steps": (
            [
                "run the judge commands from the public repository root",
                "submit Devpost only after final user approval",
            ]
            if repo_url_recorded
            else MANUAL_NEXT_STEPS
        ),
        "manual_blockers": preflight["missing_required_manual_items"],
        "no_public_action_performed": True,
        "requires_credentials": False,
        "network_calls_made": False,
    }


def _public_surface_root(root: Path, preflight: dict[str, Any]) -> Path:
    bundle = str(preflight["sanitized_bundle"])
    if bundle == ".":
        return root
    return (root / bundle).resolve()


def _checks(root: Path, public_surface: Path) -> list[dict[str, Any]]:
    return [
        _source_bundle_parity_check(root, public_surface),
        _mit_license_check(public_surface),
        _readme_check(public_surface),
        _manifest_check(public_surface),
        _forbidden_paths_check(public_surface),
        _scan_check(public_surface),
        _verification_commands_check(public_surface),
    ]


def _source_bundle_parity_check(root: Path, public_surface: Path) -> dict[str, Any]:
    if root.resolve() == public_surface.resolve():
        return {
            "id": "source_bundle_parity",
            "status": "passed",
            "skipped": True,
            "summary": "running against sanitized bundle root",
            "mismatched": [],
            "missing": [],
        }

    checked: list[str] = []
    mismatched: list[str] = []
    missing: list[str] = []
    for relative in _source_bundle_parity_files(root):
        source_path = root / relative
        bundle_path = public_surface / relative
        if not source_path.is_file() or not bundle_path.is_file():
            missing.append(relative)
            continue
        checked.append(relative)
        if _normalized_public_bytes(source_path) != _normalized_public_bytes(bundle_path):
            mismatched.append(relative)

    return {
        "id": "source_bundle_parity",
        "status": "passed" if not mismatched and not missing else "failed",
        "skipped": False,
        "summary": "raw workspace judge-facing files match latest sanitized bundle",
        "checked_count": len(checked),
        "mismatched": mismatched,
        "missing": missing,
    }


def _source_bundle_parity_files(root: Path) -> list[str]:
    files = set(PUBLIC_FILES)
    for relative_dir in PUBLIC_DIRECTORIES:
        directory = root / relative_dir
        if not directory.is_dir():
            continue
        for path in directory.rglob("*"):
            relative = path.relative_to(root).as_posix()
            if not path.is_file() or _is_generated_or_local(path, relative):
                continue
            files.add(relative)
    return sorted(files)


def _is_generated_or_local(path: Path, relative: str) -> bool:
    parts = set(path.parts)
    is_excluded_submission_doc = (
        path.name in PUBLIC_SUBMISSION_DOC_EXCLUDES
        and len(path.parts) >= 3
        and path.parts[-2] == "submission"
        and path.parts[-3] == "docs"
    )
    return (
        "__pycache__" in parts
        or "dist" in parts
        or relative in PUBLIC_LOCAL_ONLY_FILES
        or path.name.endswith(PUBLIC_LOCAL_ONLY_FILE_SUFFIXES)
        or is_excluded_submission_doc
        or path.name == ".DS_Store"
        or path.suffix == ".pyc"
    )


def _normalized_public_bytes(path: Path) -> bytes:
    data = path.read_bytes()
    return BUNDLE_REFERENCE_PATTERN.sub(b"dist/recallpack-submission-<bundle>", data)


def _mit_license_check(public_surface: Path) -> dict[str, Any]:
    path = public_surface / "LICENSE"
    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    return {
        "id": "mit_license",
        "status": "passed" if "MIT License" in text else "failed",
        "file": "LICENSE",
    }


def _readme_check(public_surface: Path) -> dict[str, Any]:
    path = public_surface / "README.md"
    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    required = [
        "Start Here For Judges",
        "MemoryAgent",
        "Fresh Clone Quickstart",
        "python3 tools/final_submission_gate.py",
    ]
    missing = [snippet for snippet in required if snippet not in text]
    return {
        "id": "readme_judge_start",
        "status": "passed" if not missing else "failed",
        "missing": missing,
    }


def _manifest_check(public_surface: Path) -> dict[str, Any]:
    path = public_surface / "SUBMISSION_MANIFEST.md"
    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    required = [
        "## Judge Quick Checks",
        "python3 tools/final_submission_gate.py",
        "python3 tools/public_repo_preflight.py",
        "POST /observe",
        "POST /compile",
    ]
    missing = [snippet for snippet in required if snippet not in text]
    return {
        "id": "submission_manifest",
        "status": "passed" if not missing else "failed",
        "missing": missing,
    }


def _forbidden_paths_check(public_surface: Path) -> dict[str, Any]:
    forbidden = [
        public_surface / "AGENTS.md",
        public_surface / "docs" / "execution",
        public_surface / "dist",
        public_surface / ".env",
    ]
    present = [
        path.relative_to(public_surface).as_posix()
        for path in forbidden
        if path.exists()
    ]
    return {
        "id": "forbidden_paths_absent",
        "status": "passed" if not present else "failed",
        "present": present,
    }


def _scan_check(public_surface: Path) -> dict[str, Any]:
    scan = _scan_public_surface(public_surface)
    return {
        "id": "bundle_scan_clean",
        "status": "failed" if any(scan.values()) else "passed",
        "findings": scan,
    }


def _scan_public_surface(public_surface: Path) -> dict[str, list[str]]:
    tracked_files = _git_tracked_files(public_surface)
    if tracked_files is None:
        return scan_submission_bundle(public_surface)

    with tempfile.TemporaryDirectory() as tmp:
        scan_root = Path(tmp) / "tracked-public-surface"
        scan_root.mkdir()
        for relative in tracked_files:
            source = public_surface / relative
            if not source.is_file():
                continue
            destination = scan_root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
        return scan_submission_bundle(scan_root)


def _git_tracked_files(public_surface: Path) -> list[str] | None:
    if not (public_surface / ".git").exists():
        return None
    try:
        result = subprocess.run(
            ["git", "-C", public_surface.as_posix(), "ls-files", "-z"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=10,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None
    files = [
        item.decode("utf-8")
        for item in result.stdout.split(b"\0")
        if item
    ]
    return sorted(files)


def _verification_commands_check(public_surface: Path) -> dict[str, Any]:
    text_parts = []
    for relative in ["README.md", "SUBMISSION_MANIFEST.md"]:
        path = public_surface / relative
        if path.is_file():
            text_parts.append(path.read_text(encoding="utf-8"))
    text = "\n".join(text_parts)
    missing = [command for command in JUDGE_COMMANDS if command not in text]
    return {
        "id": "verification_commands_present",
        "status": "passed" if not missing else "failed",
        "missing": missing,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run local-only checks before manually creating the public judging repo."
    )
    parser.add_argument(
        "--root",
        default=str(SCRIPT_ROOT),
        help="Private workspace root or sanitized public bundle root.",
    )
    args = parser.parse_args()

    payload = build_public_repo_preflight(Path(args.root))
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if payload["ready"] else 1


if __name__ == "__main__":
    sys.exit(main())
