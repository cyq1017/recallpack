from __future__ import annotations

import json
from pathlib import PurePosixPath
from typing import Any
import unicodedata


PATCH_CONTRACT_VERSION = "1.0"
MAX_GOAL_BYTES = 32_768
MAX_CONTEXT_ITEMS = 64
MAX_ALLOWED_PATHS = 32
MAX_MODEL_INPUT_BYTES = 2_097_152
MAX_MODEL_OUTPUT_BYTES = 2_097_152

_REQUEST_FIELDS = frozenset(
    {"goal", "selected_context", "allowed_paths", "source_files"}
)
_RESULT_FIELDS = frozenset({"files", "trace", "used_gold_patch_variants"})
_MISSING = object()

_CONTEXT_FIELDS = frozenset(
    {"id", "type", "subject", "scope", "source_ref", "text", "actor", "kind"}
)
_MODEL_CONTEXT_FIELDS = ("type", "subject", "scope", "text")
_EDIT_POLICY = (
    "Return complete replacement content only for allowed_edit_paths.",
    "For code behavior changes, output exactly one file at primary_source_path unless selected_context explicitly requires another allowed path.",
    "Preserve existing public function names and module-level API from source_files.",
    "Do not edit README or other unlisted documentation files.",
    "Do not edit dependency files such as pyproject.toml unless selected_context explicitly requires a dependency change.",
    "If selected_context says do not add new dependencies, do not add imports or dependency declarations.",
)


class PatchContractError(ValueError):
    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"patch-contract/{PATCH_CONTRACT_VERSION} {code} / {detail}")


def validate_patch_generation_request(request: Any) -> None:
    if not _has_exact_instance_fields(request, _REQUEST_FIELDS):
        _fail(
            "forbidden_model_input",
            "patch request must be a closed goal/context/path/source object",
        )
    goal = getattr(request, "goal", None)
    selected_context = getattr(request, "selected_context", None)
    allowed_paths = getattr(request, "allowed_paths", None)
    source_files = getattr(request, "source_files", None)

    if not _bounded_text(goal, MAX_GOAL_BYTES):
        _fail("invalid_goal", "goal must be non-empty bounded UTF-8 text")
    if _contains_forbidden_evaluation_marker(goal):
        _fail("forbidden_model_input", "goal contains hidden-test or gold-answer markers")
    if (
        not isinstance(selected_context, list)
        or len(selected_context) > MAX_CONTEXT_ITEMS
    ):
        _fail("invalid_selected_context", "selected_context must be a bounded list")
    for item in selected_context:
        if type(item) is not dict:
            _fail("invalid_selected_context", "context items must be objects")
        if not set(item).issubset(_CONTEXT_FIELDS):
            _fail(
                "forbidden_model_input",
                "context contains gold, hidden-test, artifact, or unknown fields",
            )
        if not _bounded_text(item.get("text"), MAX_MODEL_INPUT_BYTES):
            _fail("invalid_selected_context", "context text must be bounded UTF-8 text")
        if any(
            field in item and not isinstance(item[field], str)
            for field in _CONTEXT_FIELDS
        ):
            _fail("invalid_selected_context", "context fields must be strings")
        if any(
            _contains_forbidden_evaluation_marker(item.get(field, ""))
            for field in _MODEL_CONTEXT_FIELDS
        ):
            _fail(
                "forbidden_model_input",
                "context contains hidden-test or gold-answer markers",
            )

    _validate_allowed_paths(allowed_paths)
    _validate_source_files(source_files, allowed_paths)
    if _canonical_json_size(_unchecked_model_payload(request)) > MAX_MODEL_INPUT_BYTES:
        _fail("model_input_too_large", "model-visible patch input exceeds the limit")


def build_patch_model_payload(request: Any) -> dict[str, Any]:
    validate_patch_generation_request(request)
    return _unchecked_model_payload(request)


def _unchecked_model_payload(request: Any) -> dict[str, Any]:
    primary_source_path = _primary_edit_path(request.allowed_paths)
    return {
        "task": "Generate a minimal patch for the coding-agent handoff.",
        "goal": request.goal,
        "selected_context": [
            {field: item.get(field, "") for field in _MODEL_CONTEXT_FIELDS}
            for item in request.selected_context
        ],
        "allowed_edit_paths": list(request.allowed_paths),
        "primary_source_path": primary_source_path,
        "source_files": [dict(file) for file in request.source_files],
        "edit_policy": list(_EDIT_POLICY),
        "output_contract": {
            "files": [
                {
                    "path": "one allowed path",
                    "content": "complete replacement file content",
                }
            ]
        },
    }


def validate_patch_generation_result(result: Any, request: Any) -> None:
    validate_patch_generation_request(request)
    if not _has_exact_instance_fields(result, _RESULT_FIELDS):
        _fail(
            "invalid_patch_result",
            "patch result must be a closed files/trace/gold-awareness object",
        )
    if getattr(result, "used_gold_patch_variants", None) is not False:
        _fail("gold_aware_provider", "patch provider must not use gold variants")
    files = getattr(result, "files", None)
    if not isinstance(files, list):
        _fail("invalid_patch_files", "patch files must be a list")
    if not files:
        _fail("empty_patch", "patch provider returned no files")

    seen: set[str] = set()
    for file in files:
        if type(file) is not dict or set(file) != {"path", "content"}:
            _fail("invalid_patch_files", "patch files must be closed path/content objects")
        path = file["path"]
        content = file["content"]
        if (
            not isinstance(path, str)
            or not _safe_repo_relative_path(path)
            or path not in request.allowed_paths
        ):
            _fail("path_not_allowed", "patch path is outside the frozen allowlist")
        if path in seen:
            _fail("duplicate_path", "patch paths must be unique")
        if not isinstance(content, str):
            _fail("invalid_patch_files", "patch content must be a string")
        seen.add(path)

    if _canonical_json_size(files) > MAX_MODEL_OUTPUT_BYTES:
        _fail("patch_output_too_large", "complete patch output exceeds the limit")

    source_content = {file["path"]: file["content"] for file in request.source_files}
    if all(source_content.get(file["path"]) == file["content"] for file in files):
        _fail("empty_patch", "patch output does not change the repository snapshot")

    trace = getattr(result, "trace", None)
    if (
        trace is None
        or _safe_attribute(trace, "provider_role") != "patch_generation"
        or _safe_attribute(trace, "request_purpose")
        != "generate_patch_from_goal_and_selected_context"
        or _safe_attribute(trace, "input_item_count")
        != 1 + len(request.selected_context)
        or _safe_attribute(trace, "output_item_count") != len(files)
        or not _nonempty_text(_safe_attribute(trace, "provider_name"))
        or not _nonempty_text(_safe_attribute(trace, "model_id"))
        or not _nonnegative_int(_safe_attribute(trace, "input_token_estimate"))
    ):
        _fail("invalid_provider_trace", "patch provider trace does not match the request/result")


def _validate_allowed_paths(value: Any) -> None:
    canonical_paths = (
        [_canonical_path_key(path) for path in value]
        if isinstance(value, list) and all(isinstance(path, str) for path in value)
        else []
    )
    if (
        not isinstance(value, list)
        or not value
        or len(value) > MAX_ALLOWED_PATHS
        or any(not isinstance(path, str) or not _safe_repo_relative_path(path) for path in value)
        or any(_contains_forbidden_evaluation_marker(path) for path in value)
        or len(value) != len(set(canonical_paths))
    ):
        _fail("invalid_allowed_paths", "allowed paths must be unique safe repo paths")


def _validate_source_files(value: Any, allowed_paths: list[str]) -> None:
    if not isinstance(value, list) or len(value) > len(allowed_paths):
        _fail("invalid_source_files", "source_files must be bounded by allowed paths")
    seen: set[str] = set()
    for file in value:
        if type(file) is not dict or set(file) != {"path", "content"}:
            _fail("invalid_source_files", "source files must be closed path/content objects")
        path = file.get("path")
        content = file.get("content")
        if (
            not isinstance(path, str)
            or path not in allowed_paths
            or not _safe_repo_relative_path(path)
            or path in seen
            or not isinstance(content, str)
        ):
            _fail("invalid_source_files", "source path/content is invalid or duplicated")
        _encoded_size(content)
        if _contains_forbidden_evaluation_marker(content):
            _fail(
                "forbidden_model_input",
                "source files contain hidden-test or gold-answer markers",
            )
        seen.add(path)


def _safe_repo_relative_path(value: str) -> bool:
    if (
        not value
        or "\\" in value
        or "\x00" in value
        or value != value.strip()
        or value != unicodedata.normalize("NFC", value)
    ):
        return False
    path = PurePosixPath(value)
    return (
        not path.is_absolute()
        and "." not in path.parts
        and ".." not in path.parts
        and path.as_posix() == value
    )


def _primary_edit_path(allowed_paths: list[str]) -> str:
    return next(
        (path for path in allowed_paths if path != "pyproject.toml"),
        allowed_paths[0],
    )


def _bounded_text(value: Any, max_bytes: int) -> bool:
    return _nonempty_text(value) and _encoded_size(value) <= max_bytes


def _nonempty_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip()) and "\x00" not in value


def _nonnegative_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _encoded_size(value: str) -> int:
    try:
        return len(value.encode("utf-8"))
    except UnicodeEncodeError:
        _fail("invalid_utf8", "patch contract text must be valid UTF-8")
    raise AssertionError("unreachable")


def _canonical_json_size(value: Any) -> int:
    try:
        serialized = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        _fail("invalid_utf8", f"patch contract payload is not canonical JSON: {type(exc).__name__}")
    return _encoded_size(serialized)


def _canonical_path_key(value: str) -> str:
    return unicodedata.normalize("NFC", value).casefold()


def _has_exact_instance_fields(value: Any, expected: frozenset[str]) -> bool:
    try:
        return set(vars(value)) == expected
    except TypeError:
        return False


def _safe_attribute(value: Any, name: str) -> Any:
    try:
        return getattr(value, name, _MISSING)
    except Exception:
        return _MISSING


def _contains_forbidden_evaluation_marker(value: str) -> bool:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    collapsed = "".join(character for character in normalized if character.isalnum())
    return any(
        marker in collapsed
        for marker in (
            "goldselected",
            "goldanswer",
            "goldpatch",
            "hiddentest",
            "authoreddownrank",
        )
    )


def _fail(code: str, detail: str) -> None:
    raise PatchContractError(code, detail)
