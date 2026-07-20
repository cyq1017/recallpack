from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
import shutil
import stat
from typing import Iterable


PUBLIC_DIRECTORIES = (
    "src/recallpack",
    "tests",
    "fixtures",
    "web",
    "tools",
    "evaluation/hidden-tests",
    "evaluation/runner",
    "evaluation/scenarios",
    "docs/submission",
)

PUBLIC_FILES = (
    ".gitignore",
    "LICENSE",
    "README.md",
    "requirements-v4.txt",
    "evaluation/.dockerignore",
    "evaluation/Dockerfile",
    "specs/001-recallpack-v4/contracts/artifacts.schema.json",
    "specs/001-recallpack-v4/contracts/compile.openapi.yaml",
    "specs/001-recallpack-v4/contracts/evaluation.schema.json",
    "specs/001-recallpack-v4/contracts/review-seed.schema.json",
    "specs/001-recallpack-v4/contracts/review-seed-contract.md",
    "specs/001-recallpack-v4/contracts/review-seed-generation-command.md",
    "specs/001-recallpack-v4/contracts/review-json-golden-vectors.json",
    "specs/001-recallpack-v4/contracts/observe.openapi.yaml",
    "specs/001-recallpack-v4/reviews/t053-external-review-phase2-prompt-v4.md",
    "specs/001-recallpack-v4/reviews/t053-semantic-adjudication-vectors-v4.json",
    "specs/001-recallpack-v4/reviews/t053-semantic-adjudication-report.schema.v4.json",
    "specs/001-recallpack-v4/reviews/t053-phase2-custody-report.schema.v4.json",
    "specs/001-recallpack-v4/reviews/t053-proposed-events-v3.json",
    "specs/001-recallpack-v4/reviews/t053-review-source-inventory-v3.json",
    "specs/001-recallpack-v4/review-seed-operator-runbook.md",
    "docs/plans/2026-06-24-recallpack-v3.2.2.md",
    "docs/deployment/alibaba-cloud-proof.md",
    "deploy/alibaba-cloud/Dockerfile",
)

EXCLUDED_PATHS = (
    "AGENTS.md",
    "docs/execution/",
    "docs/research/",
    "docs/submission/internal-audits-and-milestone-notes",
    "docs/submission/media/alibaba-cloud-deployment-proof.png",
    "dist/",
    "__pycache__/",
    "*.pyc",
    ".DS_Store",
    "*.inspect.ndjson",
)

PUBLIC_SUBMISSION_DOC_EXCLUDES = {
    "m50-external-benchmark-winner-polish.md",
    "m62-external-review-remediation.md",
    "m63-fair-baseline-model-patch-proof.md",
    "quality-hardening-audit.md",
    "winner-grade-benchmark-audit.md",
}

PUBLIC_LOCAL_ONLY_FILES = {
    "docs/submission/media/alibaba-cloud-deployment-proof.png",
}

# Presentation tooling emits these inspect logs beside the rendered deck. They
# are local verification artifacts, not judge-facing submission material.
PUBLIC_LOCAL_ONLY_FILE_SUFFIXES = (".inspect.ndjson",)

JUDGE_FIRST_RUN_COMMANDS = (
    "python3 -m venv .venv",
    ". .venv/bin/activate",
    "python3 -m pip install -r requirements-v4.txt",
    "PYTHONPATH=src python3 tools/fresh_clone_smoke.py --source .",
    "PYTHONPATH=src python3 tools/fresh_clone_smoke.py --source . --full",
    "PYTHONPATH=src python3 -m unittest discover -s tests -v",
    "node --check web/app.js",
    "python3 tools/devpost_preflight.py",
    "python3 tools/export_devpost_materials.py",
    "python3 tools/export_evidence_index.py",
    "python3 tools/video_rehearsal_gate.py",
    "python3 tools/final_submission_gate.py",
    "python3 tools/public_repo_preflight.py",
    "python3 tools/submission_readiness_loop.py --full",
)

HIGH_CONFIDENCE_SECRET_PATTERNS = (
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
)
SECRET_LITERAL_PATTERN = re.compile(
    r"\b(?:api[_-]?key|secret)\b\s*[:=]\s*['\"]([^'\"]{8,})['\"]",
    re.IGNORECASE,
)
BUNDLE_REFERENCE_PATTERN = re.compile(r"dist/recallpack-submission-\d{8}-\d{6}")
BUNDLE_TARGET_NAME_PATTERN = re.compile(r"recallpack-submission-\d{8}-\d{6}")
PRESERVED_HISTORICAL_BUNDLE_REFERENCES = {
    "dist/recallpack-submission-20260704-123846",
}
TEXT_FILE_SUFFIXES = {
    ".css",
    ".html",
    ".js",
    ".json",
    ".md",
    ".txt",
}
PLACEHOLDER_SECRET_VALUES = {
    "...",
    "example",
    "placeholder",
    "unit-secret",
    "test-secret",
    "[redacted]",
}

LOCAL_TEXT_MARKERS = (
    "/" + "Users/",
    "cao" + "yuqi",
    "." + "codex",
)


@dataclass(frozen=True)
class SubmissionBundleResult:
    target: Path
    files: list[str]
    scan: dict[str, list[str]]


def build_submission_bundle(project_root: str | Path, target_dir: str | Path) -> SubmissionBundleResult:
    root = Path(project_root).resolve()
    target = Path(target_dir)
    if target.exists():
        raise FileExistsError(f"Submission bundle target already exists: {target}")

    target.mkdir(parents=True)
    for relative_dir in PUBLIC_DIRECTORIES:
        _copy_public_directory(root, target, relative_dir)
    for relative_file in PUBLIC_FILES:
        _copy_public_file(root, target, relative_file)
    _rewrite_bundle_references(target)

    files = _list_bundle_files(target)
    _write_manifest(target, files)
    files = _list_bundle_files(target)
    return SubmissionBundleResult(target=target, files=files, scan=scan_submission_bundle(target))


def scan_submission_bundle(target_dir: str | Path) -> dict[str, list[str]]:
    target = Path(target_dir)
    findings: dict[str, list[str]] = {
        "local_path_hits": [],
        "secret_hits": [],
        "generated_artifact_hits": [],
        "internal_path_hits": [],
    }

    for path in target.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(target).as_posix()
        _scan_path(relative, findings)
        _scan_text(path, relative, findings)

    for key in findings:
        findings[key].sort()
    return findings


def _copy_public_directory(root: Path, target: Path, relative_dir: str) -> None:
    source = root / relative_dir
    destination = target / relative_dir
    if not source.is_dir():
        raise FileNotFoundError(f"Required submission directory is missing: {source}")
    _assert_public_source_tree_safe(root, source)
    shutil.copytree(
        source,
        destination,
        ignore=_ignore_generated_files,
        symlinks=True,
    )
    _assert_public_source_tree_safe(target, destination)


def _copy_public_file(root: Path, target: Path, relative_file: str) -> None:
    source = root / relative_file
    destination = target / relative_file
    if not source.is_file():
        raise FileNotFoundError(f"Required submission file is missing: {source}")
    _assert_public_source_file_safe(root, source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    _assert_public_source_file_safe(target, destination)


def _assert_public_source_tree_safe(root: Path, source: Path) -> None:
    _assert_path_components_not_symlinks(root, source)
    for directory, names, filenames in os.walk(source, followlinks=False):
        directory_path = Path(directory)
        for name in (*names, *filenames):
            candidate = directory_path / name
            metadata = os.lstat(candidate)
            if stat.S_ISLNK(metadata.st_mode):
                raise ValueError("Unsafe public bundle source: symlink is forbidden")
            if stat.S_ISREG(metadata.st_mode):
                if metadata.st_nlink != 1:
                    raise ValueError(
                        "Unsafe public bundle source: hardlinked file is forbidden"
                    )
            elif not stat.S_ISDIR(metadata.st_mode):
                raise ValueError(
                    "Unsafe public bundle source: special filesystem entry is forbidden"
                )


def _assert_public_source_file_safe(root: Path, source: Path) -> None:
    _assert_path_components_not_symlinks(root, source)
    metadata = os.lstat(source)
    if not stat.S_ISREG(metadata.st_mode):
        raise ValueError("Unsafe public bundle source: regular file required")
    if metadata.st_nlink != 1:
        raise ValueError("Unsafe public bundle source: hardlinked file is forbidden")


def _assert_path_components_not_symlinks(root: Path, source: Path) -> None:
    try:
        relative = source.relative_to(root)
    except ValueError as exc:
        raise ValueError("Unsafe public bundle source: path escapes root") from exc
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("Unsafe public bundle source: symlink is forbidden")


def _rewrite_bundle_references(target: Path) -> None:
    replacement = _bundle_reference(target)
    if replacement is None:
        return
    for path in target.rglob("*"):
        if not path.is_file() or path.suffix not in TEXT_FILE_SUFFIXES:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        rewritten = BUNDLE_REFERENCE_PATTERN.sub(
            lambda match: (
                match.group(0)
                if match.group(0) in PRESERVED_HISTORICAL_BUNDLE_REFERENCES
                else replacement
            ),
            text,
        )
        if rewritten != text:
            path.write_text(rewritten, encoding="utf-8")


def _bundle_reference(target: Path) -> str | None:
    if not BUNDLE_TARGET_NAME_PATTERN.fullmatch(target.name):
        return None
    if target.parent.name == "dist":
        return f"dist/{target.name}"
    return target.name


def _ignore_generated_files(directory: str, names: list[str]) -> set[str]:
    ignored = set()
    normalized_directory = directory.replace("\\", "/")
    for name in names:
        if name in {".DS_Store", "__pycache__", "dist"}:
            ignored.add(name)
        elif name.endswith(".pyc"):
            ignored.add(name)
        elif name.endswith(PUBLIC_LOCAL_ONLY_FILE_SUFFIXES):
            ignored.add(name)
        elif normalized_directory.endswith("/docs/submission") and (
            name in PUBLIC_SUBMISSION_DOC_EXCLUDES
        ):
            ignored.add(name)
        elif _relative_ignore_candidate(normalized_directory, name) in PUBLIC_LOCAL_ONLY_FILES:
            ignored.add(name)
    return ignored


def _relative_ignore_candidate(normalized_directory: str, name: str) -> str:
    marker = "/docs/submission/media"
    if normalized_directory.endswith(marker):
        return f"docs/submission/media/{name}"
    return f"{normalized_directory}/{name}"


def _list_bundle_files(target: Path) -> list[str]:
    return sorted(path.relative_to(target).as_posix() for path in target.rglob("*") if path.is_file())


def _write_manifest(target: Path, files: Iterable[str]) -> None:
    lines = [
        "# RecallPack Submission Bundle Manifest",
        "",
        "Generated locally for hackathon review/submission packaging.",
        "This bundle is intentionally narrower than the working directory.",
        "",
        "## Included Files",
        "",
    ]
    lines.extend(f"- `{path}`" for path in files)
    lines.extend(
        [
            "",
            "## Excluded From Bundle",
            "",
        ]
    )
    lines.extend(f"- `{path}`" for path in EXCLUDED_PATHS)
    lines.extend(
        [
            "",
            "## Judge Quick Checks",
            "",
            "RecallPack is a MemoryAgent submission. The local review path proves stale-aware",
            "memory lifecycle, budgeted recall, downstream patch/test behavior, and the",
            "Qwen load-bearing boundary without requiring live credentials.",
            "",
            "No credentials are required for local checks.",
            "",
            "Truthfulness boundary: local hidden-test proof uses a local",
            "deterministic context-keyed patch provider; local raw-history",
            "baseline retrieval uses keyword-scored fake embeddings/rerank;",
            "the 32-event micro-suite is a behavior contract fixture suite;",
            "and live Qwen evidence is a stored sanitized one-run trace.",
            "The local Docker is the canonical credential-free demo surface.",
            "The public ECS endpoint is an approved deployment proof",
            "and may be revalidated separately, but local Docker is the",
            "canonical credential-free demo surface for judging.",
            "The full fresh-clone rehearsal runs public-test discovery.",
            "Custody-bound frozen-executor tests explicitly skip because their",
            "private frozen execution manifest is intentionally excluded from",
            "this public bundle; the private workspace runs that custody suite.",
            "",
            "From this bundle root:",
            "",
            "```bash",
            "PYTHONPATH=src python3 tools/build_live_qwen_e2e_preflight.py",
            "PYTHONPATH=src python3 tools/build_live_qwen_embedding_baseline_preflight.py",
            *JUDGE_FIRST_RUN_COMMANDS,
            "```",
            "",
            "The live E2E preflight is credential-free and records no-network",
            "readiness for the next explicitly approved live Qwen rerun.",
            "The real embedding baseline preflight is also credential-free and",
            "verifies the text-embedding-v4 plus qwen3-rerank raw-history",
            "baseline request path before any approved live baseline run.",
            "The Devpost preflight is also credential-free and reports local",
            "material readiness versus manual gated submission actions.",
            "The Devpost materials export is local-only and turns checked-in",
            "submission copy, media assets, and preflight blockers into JSON",
            "and Markdown for manual copy/paste.",
            "The evidence index maps judge-facing claims to files and commands",
            "without making network calls or public changes.",
            "The final submission gate aggregates preflight, evidence index,",
            "bundle scan, and full fresh-clone rehearsal into one local report.",
            "The public repo preflight checks the sanitized publish surface,",
            "license, README, manifest, forbidden paths, and judge commands",
            "before or after public GitHub repository creation.",
            "",
            "When the local demo server is running on `127.0.0.1:8789`:",
            "",
            "```bash",
            "curl http://127.0.0.1:8789/api/health",
            "python3 tools/judge_smoke.py --url http://127.0.0.1:8789",
            "```",
            "",
            "Primary API surface:",
            "",
            "- `GET /api/health` gives the compact judging readiness summary.",
            "- `GET /api/demo` returns the full demo/evaluation payload.",
            "- `POST /observe` records ordered memory lifecycle events.",
            "- `POST /compile` returns the active memory pack under budget.",
            "",
            "## Safety Notes",
            "",
            "- No live Qwen credentials are read or copied.",
            "- No public deployment or hackathon submission is performed by this builder.",
            "- Existing target directories are not overwritten by default.",
            "",
        ]
    )
    (target / "SUBMISSION_MANIFEST.md").write_text("\n".join(lines), encoding="utf-8")


def _scan_path(relative: str, findings: dict[str, list[str]]) -> None:
    parts = set(relative.split("/"))
    if (
        "__pycache__" in parts
        or relative.endswith(".pyc")
        or relative.endswith(".DS_Store")
        or relative.endswith(PUBLIC_LOCAL_ONLY_FILE_SUFFIXES)
    ):
        findings["generated_artifact_hits"].append(relative)
    if (
        relative == "AGENTS.md"
        or relative.startswith("docs/execution/")
        or relative.startswith("docs/research/")
        or relative.removeprefix("docs/submission/") in PUBLIC_SUBMISSION_DOC_EXCLUDES
    ):
        findings["internal_path_hits"].append(relative)


def _scan_text(path: Path, relative: str, findings: dict[str, list[str]]) -> None:
    text = path.read_text(encoding="utf-8", errors="ignore")
    if any(marker in text for marker in LOCAL_TEXT_MARKERS):
        findings["local_path_hits"].append(relative)
    for pattern in HIGH_CONFIDENCE_SECRET_PATTERNS:
        if pattern.search(text):
            findings["secret_hits"].append(f"{relative}:{pattern.pattern}")
    for match in SECRET_LITERAL_PATTERN.finditer(text):
        value = match.group(1)
        if value.lower() not in PLACEHOLDER_SECRET_VALUES:
            findings["secret_hits"].append(f"{relative}:{SECRET_LITERAL_PATTERN.pattern}")
