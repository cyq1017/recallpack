from __future__ import annotations

import hashlib
import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_ROOT = ROOT / "specs" / "001-recallpack-v4" / "contracts"
V4_VARIANTS = [
    "raw_full_history",
    "semantic_rerank",
    "recency_aware",
    "recall_time_resolver",
    "recallpack",
]
ENV_ALLOWLIST = [
    "HOME",
    "HOSTNAME",
    "LANG",
    "LC_ALL",
    "PATH",
    "PYTHONHASHSEED",
    "PYTHONDONTWRITEBYTECODE",
]
BUILD_CONTEXT_EXCLUSIONS = [
    ".git",
    ".git/**",
    ".env",
    ".env.*",
    "**/*.pem",
    "**/*.key",
    "**/*credential*",
    "**/*secret*",
    "dist",
    "docs/execution",
    "docs/submission",
    "fixtures",
    "**/__pycache__",
    "**/*.pyc",
    "**/.DS_Store",
    "hidden-tests",
    "scenarios",
    "evidence",
]
DEFAULT_WRITABLE_PATHS = [
    "src/retry.py",
    "src/retry_policy.py",
    "src/auth.py",
    "src/config_loader.py",
    "pyproject.toml",
]
DEFAULT_MODEL_VISIBLE_SNAPSHOT_TEXT = (
    "Sanitized model-visible snapshot. Summaries only, no hidden labels, IDs, "
    "or predicates."
)
DEFAULT_PROMPT_TEMPLATE_TEXT = (
    "Generate a patch from the selected context only. Hidden tests appear only "
    "after model output is fixed."
)
DEFAULT_CONTEXT_TEXT = (
    "Selected memory summary for patch generation only. No hidden test names, "
    "content, predicates, or gold labels."
)
DEFAULT_LEAKAGE_REVIEW_TEXT = (
    "Independent leakage review confirmed no hidden labels or predicates were "
    "model-visible under the frozen fixture hash."
)
EXECUTION_MANIFEST_SHA256 = "3" * 64


def load_schema() -> dict:
    return json.loads((CONTRACT_ROOT / "evaluation.schema.json").read_text())


def definition_validator(name: str) -> Draft202012Validator:
    schema = load_schema()
    return Draft202012Validator(
        {
            "$schema": schema["$schema"],
            "$defs": schema["$defs"],
            "$ref": f"#/$defs/{name}",
        },
        format_checker=FormatChecker(),
    )


def sha(char: str) -> str:
    return char * 64


def digest(char: str) -> str:
    return f"sha256:{char * 64}"


def canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def sha256_hex_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def canonical_sha256(value: object) -> str:
    return sha256_hex_bytes(canonical_json_bytes(value))


def artifact(kind: str, relative_path: str, payload: bytes) -> dict[str, object]:
    return {
        "kind": kind,
        "relative_path": relative_path,
        "sha256": sha256_hex_bytes(payload),
        "bytes": len(payload),
        "sanitized": True,
        "content_policy": "sanitized_bounded",
    }
