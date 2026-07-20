from __future__ import annotations

import ast
import copy
import difflib
import json
import importlib.util
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol
import tomllib

from recallpack.providers import (
    ProviderError,
    ProviderTrace,
    QwenCloudHTTPClient,
    TEXT_MODEL,
    post_qwen_json_with_latency,
)
from recallpack.downstream_contract import (
    PatchContractError,
    build_patch_model_payload,
    validate_patch_generation_request,
    validate_patch_generation_result,
)


PATCH_GENERATION_SYSTEM_MESSAGE = (
    "Use the generate_patch tool exactly once. Generate only files needed for "
    "the coding task, limited to allowed paths."
)
PATCH_GENERATION_MAX_TOKENS = 2048


@dataclass(frozen=True)
class DownstreamValidationResult:
    accepted: bool
    error: str | None = None


@dataclass(frozen=True)
class PatchGenerationRequest:
    goal: str
    selected_context: list[dict[str, Any]]
    allowed_paths: list[str]
    source_files: list[dict[str, str]] = field(default_factory=list)


@dataclass(frozen=True)
class PatchGenerationResult:
    files: list[dict[str, str]]
    trace: ProviderTrace
    used_gold_patch_variants: bool = False


@dataclass(frozen=True)
class PreparedDownstreamPatch:
    """Internal patch preparation result with the trace retained for evidence."""

    payload: dict[str, Any]
    provider_trace: ProviderTrace | None
    generated_files: tuple[dict[str, str], ...]
    provider_failure_code: str | None
    provider_failure_retryable: bool


class PatchGenerationProvider(Protocol):
    def generate_patch(self, request: PatchGenerationRequest) -> PatchGenerationResult:
        ...


class DeterministicContextPatchProvider:
    def __init__(self, provider_name: str = "fake-qwen-patch-generator") -> None:
        self._provider_name = provider_name
        self.calls: list[PatchGenerationRequest] = []
        self.results: list[PatchGenerationResult] = []

    def generate_patch(self, request: PatchGenerationRequest) -> PatchGenerationResult:
        self.calls.append(request)
        files = _generate_patch_from_context(request)
        result = PatchGenerationResult(
            files=files,
            trace=ProviderTrace(
                provider_name=self._provider_name,
                model_id=TEXT_MODEL,
                provider_role="patch_generation",
                request_purpose="generate_patch_from_goal_and_selected_context",
                input_item_count=1 + len(request.selected_context),
                input_token_estimate=_patch_input_token_estimate(request),
                output_item_count=len(files),
                request_id=f"fake-patch-{len(self.calls)}",
                usage={
                    "context_count": len(request.selected_context),
                    "allowed_path_count": len(request.allowed_paths),
                    "source_file_paths": [
                        file.get("path", "") for file in request.source_files
                    ],
                    "local_provider_mode": "deterministic_context_fake",
                },
            ),
            used_gold_patch_variants=False,
        )
        self.results.append(result)
        return result


class DeterministicPolicyPatchProvider:
    """Diagnostic AST transformer driven by explicit policy text and source shape."""

    def __init__(self, provider_name: str = "deterministic-policy-transform") -> None:
        self._provider_name = provider_name
        self.calls: list[PatchGenerationRequest] = []
        self.results: list[PatchGenerationResult] = []

    def generate_patch(self, request: PatchGenerationRequest) -> PatchGenerationResult:
        self.calls.append(request)
        files = _generate_policy_patch_from_context(request)
        result = PatchGenerationResult(
            files=files,
            trace=ProviderTrace(
                provider_name=self._provider_name,
                model_id="deterministic-ast-policy-transform",
                provider_role="patch_generation",
                request_purpose="generate_patch_from_goal_and_selected_context",
                input_item_count=1 + len(request.selected_context),
                input_token_estimate=_patch_input_token_estimate(request),
                output_item_count=len(files),
                request_id=f"diagnostic-policy-patch-{len(self.calls)}",
                usage={
                    "context_count": len(request.selected_context),
                    "allowed_path_count": len(request.allowed_paths),
                    "source_file_paths": [
                        file.get("path", "") for file in request.source_files
                    ],
                    "generation_mode": "deterministic_ast_policy_transform",
                },
            ),
            used_gold_patch_variants=False,
        )
        self.results.append(result)
        return result


class QwenPatchGenerationProvider:
    def __init__(
        self,
        client: QwenCloudHTTPClient,
        compatible_base_url: str,
        model_id: str = TEXT_MODEL,
    ) -> None:
        self._client = client
        self._compatible_base_url = compatible_base_url.rstrip("/")
        self._model_id = model_id
        self.traces: list[ProviderTrace] = []

    def generate_patch(self, request: PatchGenerationRequest) -> PatchGenerationResult:
        prompt = _patch_generation_prompt(request)
        tool = _patch_generation_tool()
        body, headers, latency_ms = post_qwen_json_with_latency(
            self._client,
            url=f"{self._compatible_base_url}/chat/completions",
            payload={
                "model": self._model_id,
                "messages": [
                    {
                        "role": "system",
                        "content": PATCH_GENERATION_SYSTEM_MESSAGE,
                    },
                    {"role": "user", "content": prompt},
                ],
                "tools": [tool],
                "tool_choice": {
                    "type": "function",
                    "function": {"name": "generate_patch"},
                },
                "enable_thinking": False,
                "temperature": 0,
                "max_tokens": PATCH_GENERATION_MAX_TOKENS,
            },
            model_id=self._model_id,
        )
        files = _parse_patch_generation_response(body, self._model_id)
        usage = _usage_from_body(body)
        usage["source_file_paths"] = [
            file.get("path", "") for file in request.source_files
        ]
        trace = ProviderTrace(
            provider_name="qwen-cloud",
            model_id=str(body.get("model", self._model_id)),
            provider_role="patch_generation",
            request_purpose="generate_patch_from_goal_and_selected_context",
            input_item_count=1 + len(request.selected_context),
            input_token_estimate=_patch_input_token_estimate(request),
            output_item_count=len(files),
            latency_ms=latency_ms,
            is_live=True,
            deterministic_fallback_status="live_qwen",
            request_id=_request_id_from_body_or_headers(body, headers),
            usage=usage,
        )
        self.traces.append(trace)
        return PatchGenerationResult(
            files=files,
            trace=trace,
            used_gold_patch_variants=False,
        )


def validate_downstream_files(
    files: list[dict[str, str]],
    allowed_paths: list[str],
) -> DownstreamValidationResult:
    seen: set[str] = set()
    for file in files:
        if type(file) is not dict or set(file) != {"path", "content"}:
            return DownstreamValidationResult(False, "invalid_patch_files")
        path = file["path"]
        content = file["content"]
        if not isinstance(path, str) or not isinstance(content, str):
            return DownstreamValidationResult(False, "invalid_patch_files")
        if path in seen:
            return DownstreamValidationResult(False, "duplicate_path")
        seen.add(path)
        if not isinstance(path, str) or not _safe_repo_relative_path(path):
            return DownstreamValidationResult(False, "path_not_allowed")
        if path not in allowed_paths:
            return DownstreamValidationResult(False, "path_not_allowed")
        if path.endswith(".py") and not _safe_generated_python(content):
            return DownstreamValidationResult(False, "unsafe_python_content")
    if len(files) > len(allowed_paths):
        return DownstreamValidationResult(False, "too_many_files")
    return DownstreamValidationResult(True)


def _safe_generated_python(content: str) -> bool:
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return False
    disallowed_import_roots = {
        "builtins",
        "importlib",
        "os",
        "pathlib",
        "requests",
        "shutil",
        "socket",
        "subprocess",
        "sys",
        "urllib",
    }
    disallowed_calls = {
        "__import__",
        "compile",
        "eval",
        "exec",
        "globals",
        "input",
        "locals",
        "open",
        "vars",
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(
                alias.name.split(".", 1)[0] in disallowed_import_roots
                for alias in node.names
            ):
                return False
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".", 1)[0]
            if root in disallowed_import_roots:
                return False
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in disallowed_calls:
                return False
    return True


def run_downstream_proof(
    fixture: Any,
    selected_context: list[dict[str, Any]],
    variant_id: str,
    patch_provider: PatchGenerationProvider | None = None,
) -> dict[str, Any]:
    provider = patch_provider or DeterministicContextPatchProvider()
    with tempfile.TemporaryDirectory() as tmpdir:
        repo_root = Path(tmpdir) / "repo"
        shutil.copytree(fixture.root / "repo_snapshot", repo_root)
        request = PatchGenerationRequest(
            goal=str(fixture.gold["goal"]),
            selected_context=selected_context,
            allowed_paths=[str(path) for path in fixture.gold["allowed_edit_paths"]],
            source_files=_allowed_source_files(
                repo_root,
                [str(path) for path in fixture.gold["allowed_edit_paths"]],
            ),
        )
        validate_patch_generation_request(request)
        provider_request = copy.deepcopy(request)
        try:
            patch_result = provider.generate_patch(provider_request)
        except ProviderError as exc:
            return _rejected_downstream_result(
                variant_id,
                DownstreamValidationResult(False, exc.code),
                fixture,
                patch_result=_provider_error_patch_result(exc, request),
                selected_context=selected_context,
                generated_files=[],
            )
        except Exception:
            return _rejected_downstream_result(
                variant_id,
                DownstreamValidationResult(False, "provider_exception"),
                fixture,
                patch_result=_unexpected_provider_error_result(provider, request),
                selected_context=selected_context,
                generated_files=[],
            )
        generated_files = getattr(patch_result, "files", None)
        try:
            validate_patch_generation_result(patch_result, request)
        except PatchContractError as exc:
            return _rejected_downstream_result(
                variant_id,
                DownstreamValidationResult(False, exc.code),
                fixture,
                patch_result=patch_result,
                selected_context=selected_context,
                generated_files=(
                    generated_files if isinstance(generated_files, list) else []
                ),
            )
        validation = validate_downstream_files(
            generated_files,
            allowed_paths=fixture.gold["allowed_edit_paths"],
        )
        if not validation.accepted:
            return _rejected_downstream_result(
                variant_id,
                validation,
                fixture,
                patch_result=patch_result,
                selected_context=selected_context,
                generated_files=generated_files,
            )
        patch_diff = _apply_generated_files(repo_root, generated_files)
        tests = _run_hidden_tests_safely(repo_root, fixture.gold["hidden_tests"], fixture.gold)
    passed = sum(1 for test in tests if test["passed"])
    failed = len(tests) - passed
    return {
        "execution_mode": "temp_repo_hidden_tests",
        "variant_id": variant_id,
        "accepted": True,
        "patch_diff": patch_diff,
        "tests": tests,
        "summary": {"passed": passed, "failed": failed},
        "causal_reason": _downstream_causal_reason(selected_context, passed, failed),
        "patch_generation": _patch_generation_payload(
            patch_result,
            selected_context=selected_context,
            generated_files=generated_files,
        ),
    }


def prepare_downstream_patch(
    fixture: Any,
    selected_context: list[dict[str, Any]],
    variant_id: str,
    patch_provider: PatchGenerationProvider | None = None,
) -> dict[str, Any]:
    """Generate and validate a patch without executing repository code on the host."""
    return prepare_downstream_patch_from_contract(
        repository_root=Path(fixture.root) / "repo_snapshot",
        goal=str(fixture.gold["goal"]),
        allowed_paths=[str(path) for path in fixture.gold["allowed_edit_paths"]],
        selected_context=selected_context,
        variant_id=variant_id,
        patch_provider=patch_provider,
    )


def prepare_downstream_patch_from_contract(
    *,
    repository_root: str | Path,
    goal: str,
    allowed_paths: list[str],
    selected_context: list[dict[str, Any]],
    variant_id: str,
    patch_provider: PatchGenerationProvider | None = None,
) -> dict[str, Any]:
    """Generate and validate a patch from explicit, already-frozen task inputs."""
    return prepare_downstream_patch_result_from_contract(
        repository_root=repository_root,
        goal=goal,
        allowed_paths=allowed_paths,
        selected_context=selected_context,
        variant_id=variant_id,
        patch_provider=patch_provider,
    ).payload


def prepare_downstream_patch_result_from_contract(
    *,
    repository_root: str | Path,
    goal: str,
    allowed_paths: list[str],
    selected_context: list[dict[str, Any]],
    variant_id: str,
    patch_provider: PatchGenerationProvider | None = None,
) -> PreparedDownstreamPatch:
    """Prepare a patch while retaining only its typed provider trace internally."""
    provider = patch_provider or DeterministicContextPatchProvider()
    repo_root = Path(repository_root)
    request = PatchGenerationRequest(
        goal=goal,
        selected_context=selected_context,
        allowed_paths=list(allowed_paths),
        source_files=_allowed_source_files(
            repo_root,
            list(allowed_paths),
        ),
    )
    validate_patch_generation_request(request)
    provider_request = copy.deepcopy(request)
    try:
        patch_result = provider.generate_patch(provider_request)
    except ProviderError as exc:
        patch_result = _provider_error_patch_result(exc, request)
        return _prepared_downstream_patch(
            _rejected_patch_preparation_result(
                variant_id,
                exc.code,
                patch_result,
                selected_context,
                [],
            ),
            patch_result,
            provider_error=exc,
        )
    except Exception:
        patch_result = _unexpected_provider_error_result(provider, request)
        return _prepared_downstream_patch(
            _rejected_patch_preparation_result(
                variant_id,
                "provider_exception",
                patch_result,
                selected_context,
                [],
            ),
            patch_result,
        )

    generated_files = getattr(patch_result, "files", None)
    try:
        validate_patch_generation_result(patch_result, request)
    except PatchContractError as exc:
        return _prepared_downstream_patch(
            _rejected_patch_preparation_result(
                variant_id,
                exc.code,
                patch_result,
                selected_context,
                generated_files if isinstance(generated_files, list) else [],
            ),
            patch_result,
        )
    validation = validate_downstream_files(
        generated_files,
        allowed_paths=allowed_paths,
    )
    if not validation.accepted:
        return _prepared_downstream_patch(
            _rejected_patch_preparation_result(
                variant_id,
                str(validation.error),
                patch_result,
                selected_context,
                generated_files,
            ),
            patch_result,
        )
    return _prepared_downstream_patch(
        {
            "execution_mode": "patch_generation_only",
            "variant_id": variant_id,
            "accepted": True,
            "patch_diff": _preview_generated_files(repo_root, generated_files),
            "test_status": "pending_isolated_runner",
            "causal_reason": "patch validated; isolated hidden-test execution pending",
            "patch_generation": _patch_generation_payload(
                patch_result,
                selected_context=selected_context,
                generated_files=generated_files,
            ),
        },
        patch_result,
    )


def _prepared_downstream_patch(
    payload: dict[str, Any],
    patch_result: Any,
    *,
    provider_error: ProviderError | None = None,
) -> PreparedDownstreamPatch:
    trace = _safe_attribute(patch_result, "trace", None)
    generated_files = _safe_attribute(patch_result, "files", None)
    if payload.get("accepted") is True:
        if (
            not isinstance(generated_files, list)
            or not all(
                type(item) is dict
                and set(item) == {"path", "content"}
                and isinstance(item["path"], str)
                and isinstance(item["content"], str)
                for item in generated_files
            )
        ):
            raise RuntimeError("accepted patch result lost its validated files")
        frozen_generated_files = tuple(copy.deepcopy(generated_files))
    else:
        frozen_generated_files = ()
    return PreparedDownstreamPatch(
        payload=payload,
        provider_trace=trace if isinstance(trace, ProviderTrace) else None,
        generated_files=frozen_generated_files,
        provider_failure_code=(provider_error.code if provider_error is not None else None),
        provider_failure_retryable=(
            provider_error.retryable if provider_error is not None else False
        ),
    )


def _rejected_patch_preparation_result(
    variant_id: str,
    error: str,
    patch_result: Any,
    selected_context: list[dict[str, Any]],
    generated_files: list[dict[str, str]],
) -> dict[str, Any]:
    return {
        "execution_mode": "patch_generation_only",
        "variant_id": variant_id,
        "accepted": False,
        "error": error,
        "patch_diff": "",
        "test_status": "not_run_patch_rejected",
        "causal_reason": f"patch rejected before isolated execution: {error}",
        "patch_generation": _patch_generation_payload(
            patch_result,
            selected_context=selected_context,
            generated_files=generated_files,
        ),
    }


def _run_hidden_tests_safely(
    repo_root: Path,
    test_names: list[str],
    gold: dict[str, Any],
) -> list[dict[str, Any]]:
    try:
        return _run_hidden_tests(repo_root, test_names, gold)
    except Exception as exc:
        detail = f"{type(exc).__name__}: {exc}"
        return [
            {"name": test_name, "passed": False, "detail": detail}
            for test_name in test_names
        ]


def _rejected_downstream_result(
    variant_id: str,
    validation: DownstreamValidationResult,
    fixture: Any,
    *,
    patch_result: Any,
    selected_context: list[dict[str, Any]],
    generated_files: list[dict[str, str]],
) -> dict[str, Any]:
    return {
        "execution_mode": "temp_repo_hidden_tests",
        "variant_id": variant_id,
        "accepted": False,
        "error": validation.error,
        "patch_diff": "",
        "tests": [],
        "summary": {"passed": 0, "failed": len(fixture.gold["hidden_tests"])},
        "causal_reason": (
            "patch rejected by downstream path validator: "
            f"{validation.error}"
        ),
        "patch_generation": _patch_generation_payload(
            patch_result,
            selected_context=selected_context,
            generated_files=generated_files,
        ),
    }


def _provider_error_patch_result(
    error: ProviderError,
    request: PatchGenerationRequest,
) -> PatchGenerationResult:
    return PatchGenerationResult(
        files=[],
        trace=ProviderTrace(
            provider_name=error.provider_name,
            model_id=error.model_id,
            provider_role="patch_generation",
            request_purpose="generate_patch_from_goal_and_selected_context",
            input_item_count=1 + len(request.selected_context),
            input_token_estimate=_patch_input_token_estimate(request),
            output_item_count=0,
            is_live=error.provider_name == "qwen-cloud",
            deterministic_fallback_status=error.code,
            request_id=error.request_id,
            usage=error.usage,
        ),
        used_gold_patch_variants=False,
    )


def _unexpected_provider_error_result(
    provider: PatchGenerationProvider,
    request: PatchGenerationRequest,
) -> PatchGenerationResult:
    return PatchGenerationResult(
        files=[],
        trace=ProviderTrace(
            provider_name=type(provider).__name__,
            model_id="unknown",
            provider_role="patch_generation",
            request_purpose="generate_patch_from_goal_and_selected_context",
            input_item_count=1 + len(request.selected_context),
            input_token_estimate=_patch_input_token_estimate(request),
            output_item_count=0,
            deterministic_fallback_status="provider_exception",
        ),
        used_gold_patch_variants=False,
    )


def _generate_patch_from_context(
    request: PatchGenerationRequest,
) -> list[dict[str, str]]:
    target_path = _primary_edit_path(request.allowed_paths)
    if target_path == "src/retry.py":
        source = (
            _current_retry_source()
            if _context_contains_current_retry_policy(request.selected_context)
            else _stale_retry_source()
        )
        return [{"path": target_path, "content": source}]
    if target_path == "src/config_loader.py":
        source = (
            _current_config_loader_source()
            if _selected_context_mentions(
                request.selected_context,
                ["configerror", "missing key"],
            )
            else _stale_config_loader_source()
        )
        return [{"path": target_path, "content": source}]
    if target_path == "src/cache_policy.py":
        source = (
            _current_cache_policy_source()
            if _selected_context_mentions(request.selected_context, ["tenant", "60"])
            else _stale_cache_policy_source()
        )
        return [{"path": target_path, "content": source}]
    if target_path == "src/audit_serializer.py":
        source = (
            _current_audit_serializer_source()
            if _selected_context_mentions(
                request.selected_context,
                ["redact", "[redacted]"],
            )
            else _stale_audit_serializer_source()
        )
        return [{"path": target_path, "content": source}]
    if target_path == "src/pagination.py":
        source = (
            _current_pagination_source()
            if _selected_context_mentions(
                request.selected_context,
                ["cursor", "100"],
            )
            else _stale_pagination_source()
        )
        return [{"path": target_path, "content": source}]
    if target_path == "src/api_client.py":
        source = (
            _current_api_client_source()
            if _selected_context_mentions(
                request.selected_context,
                ["x-api-key", "timeout=10"],
            )
            else _stale_api_client_source()
        )
        return [{"path": target_path, "content": source}]
    if target_path == "src/provider_auth.py":
        source = (
            _current_provider_auth_source()
            if _selected_context_mentions(
                request.selected_context,
                ["x-api-key", "strip caller authorization", "oauth code mode", "bearer"],
            )
            else _stale_provider_auth_source()
        )
        return [{"path": target_path, "content": source}]
    if target_path == "src/ci_policy.py":
        source = (
            _current_ci_policy_source()
            if _selected_context_mentions(
                request.selected_context,
                ["minimal reproducer", "fix forward"],
            )
            else _stale_ci_policy_source()
        )
        return [{"path": target_path, "content": source}]
    return []


def _generate_policy_patch_from_context(
    request: PatchGenerationRequest,
) -> list[dict[str, str]]:
    target_path = _primary_edit_path(request.allowed_paths)
    source = next(
        (
            file.get("content")
            for file in request.source_files
            if file.get("path") == target_path
        ),
        None,
    )
    if not isinstance(source, str):
        return []
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    policy_contract = _policy_contract(target_path, request.selected_context)
    if policy_contract is None:
        return []
    function_name, updates = policy_contract
    changed = _update_function_policy_dict(tree, function_name, updates)
    if not changed:
        return []
    ast.fix_missing_locations(tree)
    return [{"path": target_path, "content": ast.unparse(tree) + "\n"}]


def _policy_contract(
    target_path: str,
    selected_context: list[dict[str, Any]],
) -> tuple[str, dict[str, Any]] | None:
    if target_path == "src/ci_policy.py":
        policy = _infer_ci_retry_policy(selected_context)
        if policy is None:
            return None
        updates = (
            {
                "action": "fail_and_fix_forward",
                "retry": False,
                "retry_attempts": 0,
                "continue_on_error": False,
                "skip": False,
                "minimal_reproducer_required": True,
            }
            if policy == "current"
            else {
                "action": "retry_workaround",
                "retry": True,
                "retry_attempts": 3,
                "continue_on_error": True,
                "skip": True,
                "minimal_reproducer_required": False,
            }
        )
        return "handle_jit_crash", updates
    if target_path == "src/package_policy.py":
        policy = _infer_interactive_package_policy(selected_context)
        if policy is None:
            return None
        interactive_package = "code" if policy == "current" else "cli"
        return (
            "package_for_feature",
            {
                "context_command": interactive_package,
                "startup_tip": interactive_package,
                "deployment_command": "cli",
            },
        )
    if target_path == "src/backend_policy.py":
        policy = _infer_backend_policy(selected_context)
        if policy is None:
            return None
        return (
            "backend_for_example",
            {
                "new_example": "neo4j" if policy == "current" else "kuzu",
                "legacy_compatibility": "kuzu",
            },
        )
    return None


def _update_function_policy_dict(
    tree: ast.Module,
    function_name: str,
    updates: dict[str, Any],
) -> bool:
    function = next(
        (
            node
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == function_name
        ),
        None,
    )
    if function is None:
        return False
    candidates = _returned_policy_dicts(function)
    matching: list[ast.Dict] = []
    for node in candidates:
        keys = [
            key.value
            if isinstance(key, ast.Constant) and isinstance(key.value, str)
            else None
            for key in node.keys
        ]
        if not set(updates).issubset({key for key in keys if key is not None}):
            continue
        matching.append(node)
    if len(matching) != 1:
        return False
    target = matching[0]
    keys = [
        key.value
        if isinstance(key, ast.Constant) and isinstance(key.value, str)
        else None
        for key in target.keys
    ]
    target.values = [
        ast.Constant(updates[key]) if key in updates else value
        for key, value in zip(keys, target.values)
    ]
    return True


def _returned_policy_dicts(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
) -> list[ast.Dict]:
    assignments: dict[str, list[ast.Dict]] = {}
    returned: list[ast.Dict] = []
    for statement in function.body:
        if (
            isinstance(statement, ast.Assign)
            and len(statement.targets) == 1
            and isinstance(statement.targets[0], ast.Name)
            and isinstance(statement.value, ast.Dict)
        ):
            assignments.setdefault(statement.targets[0].id, []).append(statement.value)
            continue
        if not isinstance(statement, ast.Return):
            continue
        value = statement.value
        if isinstance(value, ast.Dict):
            returned.append(value)
            continue
        name = None
        if isinstance(value, ast.Name):
            name = value.id
        elif isinstance(value, ast.Subscript) and isinstance(value.value, ast.Name):
            name = value.value.id
        if name is not None and len(assignments.get(name, [])) == 1:
            returned.extend(assignments[name])
    return list({id(node): node for node in returned}.values())


def _infer_ci_retry_policy(
    selected_context: list[dict[str, Any]],
) -> str | None:
    recognized: list[tuple[int, str]] = []
    for index, item in enumerate(selected_context):
        text = str(item.get("text", "")).lower().replace("-", " ")
        relevant_crash = "crash" in text and any(
            marker in text for marker in ("jit", "compiler")
        )
        mentions_retry = any(
            word.startswith(("retr", "rerun")) for word in text.split()
        )
        retry_is_prohibited = mentions_retry and any(
            marker in text
            for marker in (
                "prohibit",
                "forbid",
                "disable",
                "do not",
                "must not",
                "without",
                "instead of",
            )
        )
        current = (
            relevant_crash
            and any(
                marker in text
                for marker in ("reproduc", "failing case", "crash case")
            )
            and (
                retry_is_prohibited
                or any(
                    marker in text
                    for marker in ("fix", "bug", "underlying issue")
                )
            )
        )
        stale = relevant_crash and (
            "flake" in text
            or "rerun" in text
            or (
                mentions_retry
                and any(
                    marker in text
                    for marker in (
                        "allow",
                        "enable",
                        "add retry",
                        "use retry",
                        "workaround",
                    )
                )
            )
        )
        policy = "current" if current else "stale" if stale else None
        if policy is not None:
            recognized.append((index, policy))
    if not recognized:
        return None
    return recognized[0][1]


def _infer_interactive_package_policy(
    selected_context: list[dict[str, Any]],
) -> str | None:
    for item in selected_context:
        text = str(item.get("text", "")).lower().replace("-", " ")
        if item.get("subject") == "deployment_package_policy" or text.startswith(
            "deployment command"
        ):
            continue
        if "interactive coding" not in text or "package" not in text:
            continue
        if "code package" in text:
            return "current"
        if "cli package" in text:
            return "stale"
    return None


def _infer_backend_policy(
    selected_context: list[dict[str, Any]],
) -> str | None:
    for item in selected_context:
        text = str(item.get("text", "")).lower().replace("-", " ")
        if item.get("subject") == "legacy_backend_compatibility" or text.startswith(
            "existing compatibility"
        ):
            continue
        if "kuzu" not in text or "backend" not in text:
            continue
        if "deprecat" in text and "neo4j" in text:
            return "current"
        if "supported" in text or "reasonable reference" in text:
            return "stale"
    return None


def _primary_edit_path(allowed_paths: list[str]) -> str:
    for path in allowed_paths:
        if path != "pyproject.toml":
            return path
    return allowed_paths[0] if allowed_paths else ""


def _patch_generation_payload(
    result: PatchGenerationResult,
    selected_context: list[dict[str, Any]],
    generated_files: list[dict[str, str]],
) -> dict[str, Any]:
    trace = _safe_attribute(result, "trace", None)
    payload = _safe_sanitized_patch_trace(trace, selected_context)
    usage = _safe_attribute(trace, "usage", {})
    if not isinstance(usage, dict):
        usage = {}
    output_paths = [
        file["path"]
        for file in generated_files
        if type(file) is dict and isinstance(file.get("path"), str)
    ]
    payload.update(
        {
            "provider_name": str(_safe_attribute(trace, "provider_name", "unknown")),
            "used_gold_patch_variants": _safe_attribute(
                result, "used_gold_patch_variants", None
            ),
            "input_fields": [
                "goal",
                "selected_context",
                "allowed_edit_paths",
                "source_files",
            ],
            "source_file_paths": list(
                usage.get("source_file_paths", [])
            )
            if isinstance(usage.get("source_file_paths"), list)
            else [],
            "selected_context_source_refs": [
                str(item.get("source_ref", "")) for item in selected_context
            ],
            "output_paths": output_paths,
            "generation_mode": str(usage.get("generation_mode", "unspecified")),
        }
    )
    return payload


def _safe_sanitized_patch_trace(
    trace: Any,
    selected_context: list[dict[str, Any]],
) -> dict[str, Any]:
    serializer = _safe_attribute(trace, "to_sanitized_record", None)
    if callable(serializer):
        try:
            record = serializer()
            if isinstance(record, dict):
                return dict(record)
        except Exception:
            pass
    return {
        "provider_role": "patch_generation",
        "model_name": "unknown",
        "request_purpose": "generate_patch_from_goal_and_selected_context",
        "input_item_count": 1 + len(selected_context),
        "input_token_estimate": 0,
        "output_item_count": 0,
        "is_live": False,
        "deterministic_fallback_status": "contract_rejected",
        "request_id_present": False,
        "request_id": None,
    }


def _safe_attribute(value: Any, name: str, default: Any) -> Any:
    try:
        return getattr(value, name, default)
    except Exception:
        return default


def _context_contains_current_policy(
    gold: dict[str, Any],
    selected_context: list[dict[str, Any]],
) -> bool:
    terms = gold.get("current_policy_terms")
    if not terms:
        return _context_contains_current_retry_policy(selected_context)
    joined = "\n".join(str(item.get("text", "")).lower() for item in selected_context)
    return all(str(term).lower() in joined for term in terms)


def _context_contains_current_retry_policy(selected_context: list[dict[str, Any]]) -> bool:
    joined = "\n".join(str(item.get("text", "")).lower() for item in selected_context)
    return "five attempts" in joined and "exponential" in joined


def _stale_retry_source() -> str:
    return (
        "import time\n\n\n"
        "def retry(operation, max_attempts=3, delay_seconds=0.1):\n"
        "    last_error = None\n"
        "    for attempt in range(max_attempts):\n"
        "        try:\n"
        "            return operation()\n"
        "        except Exception as exc:\n"
        "            last_error = exc\n"
        "            if attempt < max_attempts - 1:\n"
        "                time.sleep(delay_seconds)\n"
        "    raise last_error\n"
    )


def _current_retry_source() -> str:
    return (
        "import time\n\n\n"
        "def retry(operation, max_attempts=5, delay_seconds=0.1):\n"
        "    last_error = None\n"
        "    for attempt in range(max_attempts):\n"
        "        try:\n"
        "            return operation()\n"
        "        except Exception as exc:\n"
        "            last_error = exc\n"
        "            if attempt < max_attempts - 1:\n"
        "                time.sleep(delay_seconds * (2 ** attempt))\n"
        "    raise last_error\n"
    )


def _stale_config_loader_source() -> str:
    return "def get_required_config(config, key):\n    return config.get(key)\n"


def _current_config_loader_source() -> str:
    return (
        "class ConfigError(RuntimeError):\n"
        "    pass\n\n\n"
        "def get_required_config(config, key):\n"
        "    try:\n"
        "        return config[key]\n"
        "    except KeyError as exc:\n"
        "        raise ConfigError(f\"missing config key: {key}\") from exc\n"
    )


def _stale_cache_policy_source() -> str:
    return (
        "DEFAULT_TTL_SECONDS = 300\n\n\n"
        "def build_cache_key(tenant_id, user_id):\n"
        "    return f\"user:{user_id}\"\n"
    )


def _current_cache_policy_source() -> str:
    return (
        "DEFAULT_TTL_SECONDS = 60\n\n\n"
        "def build_cache_key(tenant_id, user_id):\n"
        "    return f\"tenant:{tenant_id}:user:{user_id}\"\n"
    )


def _stale_audit_serializer_source() -> str:
    return "def serialize_user_event(event):\n    return dict(event)\n"


def _current_audit_serializer_source() -> str:
    return (
        "def serialize_user_event(event):\n"
        "    payload = dict(event)\n"
        "    if \"email\" in payload:\n"
        "        payload[\"email\"] = '[redacted]'\n"
        "    return payload\n"
    )


def _stale_pagination_source() -> str:
    return (
        "def build_page_request(page, page_size):\n"
        "    return {\"offset\": page * page_size, \"limit\": page_size}\n"
    )


def _current_pagination_source() -> str:
    return (
        "def build_page_request(cursor, limit):\n"
        "    return {\"cursor\": cursor, \"limit\": min(limit, 100)}\n"
    )


def _stale_api_client_source() -> str:
    return (
        "def build_request(path, token, timeout=5):\n"
        "    return {\n"
        "        \"path\": path,\n"
        "        \"headers\": {\"Authorization\": f\"Bearer {token}\"},\n"
        "        \"timeout\": timeout,\n"
        "    }\n"
    )


def _current_api_client_source() -> str:
    return (
        "def build_request(path, api_key, timeout=10):\n"
        "    return {\n"
        "        \"path\": path,\n"
        "        \"headers\": {\"X-Api-Key\": api_key},\n"
        "        \"timeout\": timeout,\n"
        "    }\n"
    )


def _stale_provider_auth_source() -> str:
    return (
        "def build_upstream_headers(mode, inbound_headers, provider_token):\n"
        "    headers = dict(inbound_headers)\n"
        "    headers[\"Authorization\"] = inbound_headers.get(\"Authorization\", \"\")\n"
        "    headers[\"X-Api-Key\"] = provider_token\n"
        "    return headers\n"
    )


def _current_provider_auth_source() -> str:
    return (
        "def build_upstream_headers(mode, inbound_headers, provider_token):\n"
        "    headers = {\n"
        "        key: value\n"
        "        for key, value in inbound_headers.items()\n"
        "        if key.lower() != \"authorization\"\n"
        "    }\n"
        "    if mode == \"oauth_code\":\n"
        "        headers[\"Authorization\"] = f\"Bearer {provider_token}\"\n"
        "        headers.pop(\"X-Api-Key\", None)\n"
        "        return headers\n"
        "    headers[\"X-Api-Key\"] = provider_token\n"
        "    headers.pop(\"Authorization\", None)\n"
        "    return headers\n"
    )


def _stale_ci_policy_source() -> str:
    return (
        "def handle_jit_crash(error_message):\n"
        "    return {\n"
        "        \"action\": \"retry_workaround\",\n"
        "        \"retry\": True,\n"
        "        \"retry_attempts\": 3,\n"
        "        \"continue_on_error\": True,\n"
        "        \"skip\": True,\n"
        "        \"minimal_reproducer_required\": False,\n"
        "    }\n"
    )


def _current_ci_policy_source() -> str:
    return (
        "def handle_jit_crash(error_message):\n"
        "    return {\n"
        "        \"action\": \"fail_and_fix_forward\",\n"
        "        \"retry\": False,\n"
        "        \"retry_attempts\": 0,\n"
        "        \"continue_on_error\": False,\n"
        "        \"skip\": False,\n"
        "        \"minimal_reproducer_required\": True,\n"
        "    }\n"
    )


def _patch_input_token_estimate(request: PatchGenerationRequest) -> int:
    text = request.goal + "\n" + "\n".join(
        str(item.get("text", "")) for item in request.selected_context
    ) + "\n" + "\n".join(
        str(file.get("content", "")) for file in request.source_files
    )
    return max(1, len(text.split()))


def _patch_generation_prompt(request: PatchGenerationRequest) -> str:
    return json.dumps(build_patch_model_payload(request), sort_keys=True)


def _allowed_source_files(repo_root: Path, allowed_paths: list[str]) -> list[dict[str, str]]:
    source_files: list[dict[str, str]] = []
    resolved_root = repo_root.resolve()
    for relative in allowed_paths:
        if not _safe_repo_relative_path(relative):
            continue
        path = (repo_root / relative).resolve()
        try:
            path.relative_to(resolved_root)
        except ValueError:
            continue
        if path.is_file():
            source_files.append({"path": relative, "content": path.read_text()})
    return source_files


def _safe_repo_relative_path(relative: str) -> bool:
    if not relative:
        return False
    path = Path(relative)
    return not path.is_absolute() and ".." not in path.parts


def _patch_generation_tool() -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": "generate_patch",
            "description": (
                "Return complete replacement file contents for a coding task. "
                "Every file path must be one of the allowed_edit_paths."
            ),
            "parameters": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "files": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "path": {"type": "string"},
                                "content": {"type": "string"},
                            },
                            "required": ["path", "content"],
                        },
                    }
                },
                "required": ["files"],
            },
        },
    }


def build_patch_generation_tool_contract() -> dict[str, Any]:
    return copy.deepcopy(_patch_generation_tool())


def _parse_patch_generation_response(
    body: dict[str, Any],
    model_id: str,
) -> list[dict[str, str]]:
    if not isinstance(body, dict):
        _raise_patch_response_error(model_id, "response body was not an object")
    choices = body.get("choices")
    if not isinstance(choices, list) or len(choices) != 1:
        _raise_patch_response_error(model_id, "response must contain exactly one choice")
    choice = choices[0]
    if not isinstance(choice, dict) or not isinstance(choice.get("message"), dict):
        _raise_patch_response_error(model_id, "response choice did not contain a message")
    message = choice["message"]
    tool_calls = message.get("tool_calls")
    if tool_calls is not None:
        content = message.get("content")
        if content is not None and not (
            isinstance(content, str) and not content.strip()
        ):
            _raise_patch_response_error(
                model_id, "response contained conflicting tool and content channels"
            )
        if not isinstance(tool_calls, list) or len(tool_calls) != 1:
            _raise_patch_response_error(
                model_id, "response must contain exactly one patch tool call"
            )
        call = tool_calls[0]
        if not isinstance(call, dict) or not isinstance(call.get("function"), dict):
            _raise_patch_response_error(model_id, "patch tool call was malformed")
        function = call["function"]
        if function.get("name") != "generate_patch":
            _raise_patch_response_error(model_id, "response called the wrong tool")
        return _parse_patch_payload(function.get("arguments"), model_id)
    content = message.get("content")
    if isinstance(content, str) and content.strip():
        return _parse_patch_payload(content, model_id)
    _raise_patch_response_error(
        model_id, "response did not call generate_patch or return JSON content"
    )
    raise AssertionError("unreachable")


def _parse_patch_payload(value: Any, model_id: str) -> list[dict[str, str]]:
    if not isinstance(value, str):
        _raise_patch_response_error(model_id, "patch payload was not a JSON string")
    try:
        parsed = json.loads(value)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ProviderError.terminal(
            provider_name="qwen-cloud",
            model_id=model_id,
            message="Qwen patch-generation payload was not valid JSON.",
        ) from exc
    if type(parsed) is not dict or set(parsed) != {"files"}:
        _raise_patch_response_error(
            model_id, "patch payload was not a closed files object"
        )
    return _normalize_patch_files(parsed["files"], model_id)


def _raise_patch_response_error(model_id: str, detail: str) -> None:
    raise ProviderError.terminal(
        provider_name="qwen-cloud",
        model_id=model_id,
        message=f"Qwen patch-generation {detail}.",
    )


def _normalize_patch_files(files: Any, model_id: str) -> list[dict[str, str]]:
    if not isinstance(files, list):
        raise ProviderError.terminal(
            provider_name="qwen-cloud",
            model_id=model_id,
            message="Qwen patch-generation files value was not a list.",
        )
    normalized: list[dict[str, str]] = []
    for file in files:
        if not isinstance(file, dict):
            raise ProviderError.terminal(
                provider_name="qwen-cloud",
                model_id=model_id,
                message="Qwen patch-generation file item was not an object.",
            )
        if set(file) != {"path", "content"} or not all(
            isinstance(file.get(field), str) for field in ("path", "content")
        ):
            raise ProviderError.terminal(
                provider_name="qwen-cloud",
                model_id=model_id,
                message="Qwen patch-generation file fields were not closed strings.",
            )
        normalized.append(
            {
                "path": file["path"],
                "content": file["content"],
            }
        )
    return normalized


def _request_id_from_body_or_headers(
    body: dict[str, Any],
    headers: dict[str, Any],
) -> str | None:
    return (
        body.get("request_id")
        or body.get("id")
        or headers.get("x-request-id")
        or headers.get("X-Request-Id")
    )


def _usage_from_body(body: dict[str, Any]) -> dict[str, Any]:
    usage = body.get("usage")
    return dict(usage) if isinstance(usage, dict) else {}


def _apply_generated_files(repo_root: Path, generated_files: list[dict[str, str]]) -> str:
    diffs: list[str] = []
    for generated in generated_files:
        relative_path = generated["path"]
        if not _safe_repo_relative_path(relative_path):
            raise ValueError(f"unsafe generated path: {relative_path}")
        path = repo_root / relative_path
        before = path.read_text() if path.exists() else ""
        after = generated["content"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(after)
        diffs.extend(
            difflib.unified_diff(
                before.splitlines(keepends=True),
                after.splitlines(keepends=True),
                fromfile=f"a/{relative_path}",
                tofile=f"b/{relative_path}",
            )
        )
    return "".join(diffs)


def _preview_generated_files(
    repo_root: Path,
    generated_files: list[dict[str, str]],
) -> str:
    diffs: list[str] = []
    for generated in generated_files:
        relative_path = generated["path"]
        if not _safe_repo_relative_path(relative_path):
            raise ValueError(f"unsafe generated path: {relative_path}")
        path = repo_root / relative_path
        before = path.read_text() if path.exists() else ""
        after = generated["content"]
        diffs.extend(
            difflib.unified_diff(
                before.splitlines(keepends=True),
                after.splitlines(keepends=True),
                fromfile=f"a/{relative_path}",
                tofile=f"b/{relative_path}",
            )
        )
    return "".join(diffs)


def _run_hidden_tests(
    repo_root: Path,
    test_names: list[str],
    gold: dict[str, Any],
) -> list[dict[str, Any]]:
    if gold.get("hidden_test_kind") == "config_loader":
        config_module = _load_module(
            repo_root / "src" / "config_loader.py",
            "config_loader",
        )
        runners = {
            "test_raises_config_error": _hidden_test_raises_config_error,
            "test_error_mentions_missing_key": _hidden_test_error_mentions_missing_key,
            "test_public_function_returns_existing_value": (
                _hidden_test_public_function_returns_existing_value
            ),
        }
        return [runners[test_name](repo_root, config_module) for test_name in test_names]
    if gold.get("hidden_test_kind") == "cache_policy":
        cache_module = _load_module(repo_root / "src" / "cache_policy.py", "cache_policy")
        runners = {
            "test_cache_key_includes_tenant": _hidden_test_cache_key_includes_tenant,
            "test_cache_ttl_is_current": _hidden_test_cache_ttl_is_current,
            "test_cache_key_function_is_stable": _hidden_test_cache_key_function_is_stable,
        }
        return [runners[test_name](repo_root, cache_module) for test_name in test_names]
    if gold.get("hidden_test_kind") == "serializer_redaction":
        serializer_module = _load_module(
            repo_root / "src" / "audit_serializer.py",
            "audit_serializer",
        )
        runners = {
            "test_redacts_email": _hidden_test_redacts_email,
            "test_removes_raw_email": _hidden_test_removes_raw_email,
            "test_preserves_event_type": _hidden_test_preserves_event_type,
        }
        return [runners[test_name](repo_root, serializer_module) for test_name in test_names]
    if gold.get("hidden_test_kind") == "pagination_policy":
        pagination_module = _load_module(
            repo_root / "src" / "pagination.py",
            "pagination",
        )
        runners = {
            "test_public_function_returns_mapping": (
                _hidden_test_public_function_returns_mapping
            ),
            "test_uses_cursor_token": _hidden_test_uses_cursor_token,
            "test_clamps_limit_to_100": _hidden_test_clamps_limit_to_100,
        }
        return [
            runners[test_name](repo_root, pagination_module)
            for test_name in test_names
        ]
    if gold.get("hidden_test_kind") == "api_client_policy":
        api_client_module = _load_module(
            repo_root / "src" / "api_client.py",
            "api_client",
        )
        runners = {
            "test_uses_x_api_key_header": _hidden_test_uses_x_api_key_header,
            "test_timeout_is_ten_seconds": _hidden_test_timeout_is_ten_seconds,
            "test_api_client_no_new_dependencies": (
                _hidden_test_api_client_no_new_dependencies
            ),
        }
        return [
            runners[test_name](repo_root, api_client_module)
            for test_name in test_names
        ]
    if gold.get("hidden_test_kind") == "provider_auth_policy":
        provider_auth_module = _load_module(
            repo_root / "src" / "provider_auth.py",
            "provider_auth",
        )
        runners = {
            "test_standard_mode_strips_authorization": (
                _hidden_test_standard_mode_strips_authorization
            ),
            "test_oauth_mode_uses_bearer_without_x_api_key": (
                _hidden_test_oauth_mode_uses_bearer_without_x_api_key
            ),
            "test_provider_auth_no_new_dependencies": (
                _hidden_test_provider_auth_no_new_dependencies
            ),
        }
        return [
            runners[test_name](repo_root, provider_auth_module)
            for test_name in test_names
        ]
    if gold.get("hidden_test_kind") == "ci_jit_policy":
        ci_policy_module = _load_module(
            repo_root / "src" / "ci_policy.py",
            "ci_policy",
        )
        runners = {
            "test_jit_crash_policy_disables_retry": (
                _hidden_test_jit_crash_policy_disables_retry
            ),
            "test_jit_crash_policy_blocks_nonblocking_workarounds": (
                _hidden_test_jit_crash_policy_blocks_nonblocking_workarounds
            ),
            "test_ci_policy_no_new_dependencies": (
                _hidden_test_ci_policy_no_new_dependencies
            ),
        }
        return [
            runners[test_name](repo_root, ci_policy_module)
            for test_name in test_names
        ]
    if gold.get("hidden_test_kind") == "package_relocation_policy":
        package_module = _load_module(
            repo_root / "src" / "package_policy.py",
            "package_policy",
        )
        runners = {
            "test_interactive_context_command_uses_code_package": (
                _hidden_test_interactive_context_command_uses_code_package
            ),
            "test_startup_tip_uses_code_package": (
                _hidden_test_startup_tip_uses_code_package
            ),
            "test_deployment_command_stays_in_cli_package": (
                _hidden_test_deployment_command_stays_in_cli_package
            ),
        }
        return [
            runners[test_name](repo_root, package_module)
            for test_name in test_names
        ]
    if gold.get("hidden_test_kind") == "backend_deprecation_policy":
        backend_module = _load_module(
            repo_root / "src" / "backend_policy.py",
            "backend_policy",
        )
        runners = {
            "test_new_example_uses_maintained_backend": (
                _hidden_test_new_example_uses_maintained_backend
            ),
            "test_legacy_compatibility_remains_kuzu": (
                _hidden_test_legacy_compatibility_remains_kuzu
            ),
            "test_backend_policy_no_new_dependencies": (
                _hidden_test_backend_policy_no_new_dependencies
            ),
        }
        return [
            runners[test_name](repo_root, backend_module)
            for test_name in test_names
        ]
    retry_module = _load_retry_module(repo_root / "src" / "retry.py")
    runners = {
        "test_uses_current_retry_count": _hidden_test_uses_current_retry_count,
        "test_uses_current_backoff_policy": _hidden_test_uses_current_backoff_policy,
        "test_does_not_modify_dependencies": _hidden_test_does_not_modify_dependencies,
    }
    return [runners[test_name](repo_root, retry_module) for test_name in test_names]


def _load_retry_module(path: Path) -> Any:
    return _load_module(path, "retry")


def _load_module(path: Path, module_prefix: str) -> Any:
    spec = importlib.util.spec_from_file_location(
        f"{module_prefix}_{abs(hash(path))}",
        path,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import module from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _hidden_test_uses_current_retry_count(repo_root: Path, retry_module: Any) -> dict[str, Any]:
    attempts = 0
    retry_module.time.sleep = lambda _seconds: None

    def operation() -> str:
        nonlocal attempts
        attempts += 1
        if attempts < 5:
            raise RuntimeError("transient failure")
        return "ok"

    try:
        result = retry_module.retry(operation)
        passed = result == "ok" and attempts == 5
        detail = f"attempts={attempts}"
    except Exception as exc:
        passed = False
        detail = f"{type(exc).__name__}: {exc}; attempts={attempts}"
    return {"name": "test_uses_current_retry_count", "passed": passed, "detail": detail}


def _hidden_test_uses_current_backoff_policy(repo_root: Path, retry_module: Any) -> dict[str, Any]:
    sleeps: list[float] = []
    retry_module.time.sleep = sleeps.append

    def operation() -> str:
        raise RuntimeError("always failing")

    try:
        retry_module.retry(operation)
    except RuntimeError:
        pass
    rounded = [round(value, 6) for value in sleeps]
    return {
        "name": "test_uses_current_backoff_policy",
        "passed": rounded == [0.1, 0.2, 0.4, 0.8],
        "detail": f"sleeps={rounded}",
    }


def _hidden_test_does_not_modify_dependencies(repo_root: Path, retry_module: Any) -> dict[str, Any]:
    pyproject = tomllib.loads((repo_root / "pyproject.toml").read_text())
    dependencies = pyproject.get("project", {}).get("dependencies")
    return {
        "name": "test_does_not_modify_dependencies",
        "passed": dependencies == [],
        "detail": f"dependencies={dependencies}",
    }


def _hidden_test_interactive_context_command_uses_code_package(
    repo_root: Path,
    package_module: Any,
) -> dict[str, Any]:
    value = package_module.package_for_feature("context_command")
    return {
        "name": "test_interactive_context_command_uses_code_package",
        "passed": value == "code",
        "detail": f"package={value!r}",
    }


def _hidden_test_startup_tip_uses_code_package(
    repo_root: Path,
    package_module: Any,
) -> dict[str, Any]:
    value = package_module.package_for_feature("startup_tip")
    return {
        "name": "test_startup_tip_uses_code_package",
        "passed": value == "code",
        "detail": f"package={value!r}",
    }


def _hidden_test_deployment_command_stays_in_cli_package(
    repo_root: Path,
    package_module: Any,
) -> dict[str, Any]:
    value = package_module.package_for_feature("deployment_command")
    return {
        "name": "test_deployment_command_stays_in_cli_package",
        "passed": value == "cli",
        "detail": f"package={value!r}",
    }


def _hidden_test_new_example_uses_maintained_backend(
    repo_root: Path,
    backend_module: Any,
) -> dict[str, Any]:
    value = backend_module.backend_for_example("new_example")
    return {
        "name": "test_new_example_uses_maintained_backend",
        "passed": value == "neo4j",
        "detail": f"backend={value!r}",
    }


def _hidden_test_legacy_compatibility_remains_kuzu(
    repo_root: Path,
    backend_module: Any,
) -> dict[str, Any]:
    value = backend_module.backend_for_example("legacy_compatibility")
    return {
        "name": "test_legacy_compatibility_remains_kuzu",
        "passed": value == "kuzu",
        "detail": f"backend={value!r}",
    }


def _hidden_test_backend_policy_no_new_dependencies(
    repo_root: Path,
    backend_module: Any,
) -> dict[str, Any]:
    pyproject = tomllib.loads((repo_root / "pyproject.toml").read_text())
    dependencies = pyproject.get("project", {}).get("dependencies")
    return {
        "name": "test_backend_policy_no_new_dependencies",
        "passed": dependencies == [],
        "detail": f"dependencies={dependencies}",
    }


def _hidden_test_raises_config_error(repo_root: Path, config_module: Any) -> dict[str, Any]:
    try:
        config_module.get_required_config({}, "DATABASE_URL")
    except Exception as exc:
        config_error = getattr(config_module, "ConfigError", None)
        passed = config_error is not None and isinstance(exc, config_error)
        detail = type(exc).__name__
    else:
        passed = False
        detail = "no exception"
    return {"name": "test_raises_config_error", "passed": passed, "detail": detail}


def _hidden_test_error_mentions_missing_key(repo_root: Path, config_module: Any) -> dict[str, Any]:
    try:
        config_module.get_required_config({}, "DATABASE_URL")
    except Exception as exc:
        detail = str(exc)
        passed = "DATABASE_URL" in detail
    else:
        passed = False
        detail = "no exception"
    return {
        "name": "test_error_mentions_missing_key",
        "passed": passed,
        "detail": detail,
    }


def _hidden_test_public_function_returns_existing_value(
    repo_root: Path,
    config_module: Any,
) -> dict[str, Any]:
    try:
        result = config_module.get_required_config({"DATABASE_URL": "postgres://local"}, "DATABASE_URL")
        passed = result == "postgres://local"
        detail = f"result={result!r}"
    except Exception as exc:
        passed = False
        detail = f"{type(exc).__name__}: {exc}"
    return {
        "name": "test_public_function_returns_existing_value",
        "passed": passed,
        "detail": detail,
    }


def _hidden_test_cache_key_includes_tenant(repo_root: Path, cache_module: Any) -> dict[str, Any]:
    try:
        key = cache_module.build_cache_key("tenant-a", "user-1")
        passed = "tenant-a" in key and "user-1" in key
        detail = f"key={key!r}"
    except Exception as exc:
        passed = False
        detail = f"{type(exc).__name__}: {exc}"
    return {"name": "test_cache_key_includes_tenant", "passed": passed, "detail": detail}


def _hidden_test_cache_ttl_is_current(repo_root: Path, cache_module: Any) -> dict[str, Any]:
    ttl = getattr(cache_module, "DEFAULT_TTL_SECONDS", None)
    return {
        "name": "test_cache_ttl_is_current",
        "passed": ttl == 60,
        "detail": f"DEFAULT_TTL_SECONDS={ttl!r}",
    }


def _hidden_test_cache_key_function_is_stable(repo_root: Path, cache_module: Any) -> dict[str, Any]:
    try:
        key = cache_module.build_cache_key("tenant-a", "user-1")
        passed = isinstance(key, str) and "user-1" in key
        detail = f"key={key!r}"
    except Exception as exc:
        passed = False
        detail = f"{type(exc).__name__}: {exc}"
    return {
        "name": "test_cache_key_function_is_stable",
        "passed": passed,
        "detail": detail,
    }


def _hidden_test_redacts_email(repo_root: Path, serializer_module: Any) -> dict[str, Any]:
    event = {"type": "login", "email": "ada@example.com", "user_id": "u-1"}
    try:
        payload = serializer_module.serialize_user_event(event)
        passed = payload.get("email") == "[redacted]"
        detail = f"email={payload.get('email')!r}"
    except Exception as exc:
        passed = False
        detail = f"{type(exc).__name__}: {exc}"
    return {"name": "test_redacts_email", "passed": passed, "detail": detail}


def _hidden_test_removes_raw_email(repo_root: Path, serializer_module: Any) -> dict[str, Any]:
    raw_email = "ada@example.com"
    event = {"type": "login", "email": raw_email, "user_id": "u-1"}
    try:
        payload = serializer_module.serialize_user_event(event)
        passed = raw_email not in str(payload)
        detail = f"payload={payload!r}"
    except Exception as exc:
        passed = False
        detail = f"{type(exc).__name__}: {exc}"
    return {"name": "test_removes_raw_email", "passed": passed, "detail": detail}


def _hidden_test_preserves_event_type(repo_root: Path, serializer_module: Any) -> dict[str, Any]:
    event = {"type": "login", "email": "ada@example.com", "user_id": "u-1"}
    try:
        payload = serializer_module.serialize_user_event(event)
        passed = payload.get("type") == "login"
        detail = f"type={payload.get('type')!r}"
    except Exception as exc:
        passed = False
        detail = f"{type(exc).__name__}: {exc}"
    return {"name": "test_preserves_event_type", "passed": passed, "detail": detail}


def _hidden_test_public_function_returns_mapping(
    repo_root: Path,
    pagination_module: Any,
) -> dict[str, Any]:
    try:
        payload = pagination_module.build_page_request(2, 50)
        passed = isinstance(payload, dict) and payload.get("limit") == 50
        detail = f"payload={payload!r}"
    except Exception as exc:
        passed = False
        detail = f"{type(exc).__name__}: {exc}"
    return {
        "name": "test_public_function_returns_mapping",
        "passed": passed,
        "detail": detail,
    }


def _hidden_test_uses_cursor_token(
    repo_root: Path,
    pagination_module: Any,
) -> dict[str, Any]:
    try:
        payload = pagination_module.build_page_request("cursor-7", 250)
        passed = payload.get("cursor") == "cursor-7" and "offset" not in payload
        detail = f"payload={payload!r}"
    except Exception as exc:
        passed = False
        detail = f"{type(exc).__name__}: {exc}"
    return {"name": "test_uses_cursor_token", "passed": passed, "detail": detail}


def _hidden_test_clamps_limit_to_100(
    repo_root: Path,
    pagination_module: Any,
) -> dict[str, Any]:
    try:
        payload = pagination_module.build_page_request("cursor-7", 250)
        passed = payload.get("limit") == 100
        detail = f"payload={payload!r}"
    except Exception as exc:
        passed = False
        detail = f"{type(exc).__name__}: {exc}"
    return {"name": "test_clamps_limit_to_100", "passed": passed, "detail": detail}


def _hidden_test_uses_x_api_key_header(
    repo_root: Path,
    api_client_module: Any,
) -> dict[str, Any]:
    try:
        payload = api_client_module.build_request("/v1/orders", "secret-key")
        headers = payload.get("headers", {})
        passed = headers.get("X-Api-Key") == "secret-key" and "Authorization" not in headers
        detail = f"headers={headers!r}"
    except Exception as exc:
        passed = False
        detail = f"{type(exc).__name__}: {exc}"
    return {"name": "test_uses_x_api_key_header", "passed": passed, "detail": detail}


def _hidden_test_timeout_is_ten_seconds(
    repo_root: Path,
    api_client_module: Any,
) -> dict[str, Any]:
    try:
        payload = api_client_module.build_request("/v1/orders", "secret-key")
        passed = payload.get("timeout") == 10
        detail = f"timeout={payload.get('timeout')!r}"
    except Exception as exc:
        passed = False
        detail = f"{type(exc).__name__}: {exc}"
    return {"name": "test_timeout_is_ten_seconds", "passed": passed, "detail": detail}


def _hidden_test_api_client_no_new_dependencies(
    repo_root: Path,
    api_client_module: Any,
) -> dict[str, Any]:
    pyproject = tomllib.loads((repo_root / "pyproject.toml").read_text())
    dependencies = pyproject.get("project", {}).get("dependencies")
    return {
        "name": "test_api_client_no_new_dependencies",
        "passed": dependencies == [],
        "detail": f"dependencies={dependencies}",
    }


def _hidden_test_standard_mode_strips_authorization(
    repo_root: Path,
    provider_auth_module: Any,
) -> dict[str, Any]:
    inbound = {"Authorization": "Bearer gateway-consumer", "Trace-Id": "trace-1"}
    try:
        headers = provider_auth_module.build_upstream_headers(
            "standard",
            inbound,
            "provider-token",
        )
        passed = (
            headers.get("X-Api-Key") == "provider-token"
            and "Authorization" not in headers
            and headers.get("Trace-Id") == "trace-1"
        )
        detail = f"headers={headers!r}"
    except Exception as exc:
        passed = False
        detail = f"{type(exc).__name__}: {exc}"
    return {
        "name": "test_standard_mode_strips_authorization",
        "passed": passed,
        "detail": detail,
    }


def _hidden_test_oauth_mode_uses_bearer_without_x_api_key(
    repo_root: Path,
    provider_auth_module: Any,
) -> dict[str, Any]:
    inbound = {"Authorization": "Bearer gateway-consumer", "X-Api-Key": "old-key"}
    try:
        headers = provider_auth_module.build_upstream_headers(
            "oauth_code",
            inbound,
            "oauth-token",
        )
        passed = (
            headers.get("Authorization") == "Bearer oauth-token"
            and "X-Api-Key" not in headers
        )
        detail = f"headers={headers!r}"
    except Exception as exc:
        passed = False
        detail = f"{type(exc).__name__}: {exc}"
    return {
        "name": "test_oauth_mode_uses_bearer_without_x_api_key",
        "passed": passed,
        "detail": detail,
    }


def _hidden_test_provider_auth_no_new_dependencies(
    repo_root: Path,
    provider_auth_module: Any,
) -> dict[str, Any]:
    pyproject = tomllib.loads((repo_root / "pyproject.toml").read_text())
    dependencies = pyproject.get("project", {}).get("dependencies")
    return {
        "name": "test_provider_auth_no_new_dependencies",
        "passed": dependencies == [],
        "detail": f"dependencies={dependencies}",
    }


def _hidden_test_jit_crash_policy_disables_retry(
    repo_root: Path,
    ci_policy_module: Any,
) -> dict[str, Any]:
    try:
        policy = ci_policy_module.handle_jit_crash("mojo jit crash")
        passed = policy.get("retry") is False and policy.get("retry_attempts") == 0
        detail = f"policy={policy!r}"
    except Exception as exc:
        passed = False
        detail = f"{type(exc).__name__}: {exc}"
    return {
        "name": "test_jit_crash_policy_disables_retry",
        "passed": passed,
        "detail": detail,
    }


def _hidden_test_jit_crash_policy_blocks_nonblocking_workarounds(
    repo_root: Path,
    ci_policy_module: Any,
) -> dict[str, Any]:
    try:
        policy = ci_policy_module.handle_jit_crash("mojo jit crash")
        passed = (
            policy.get("continue_on_error") is False
            and policy.get("skip") is False
            and policy.get("minimal_reproducer_required") is True
        )
        detail = f"policy={policy!r}"
    except Exception as exc:
        passed = False
        detail = f"{type(exc).__name__}: {exc}"
    return {
        "name": "test_jit_crash_policy_blocks_nonblocking_workarounds",
        "passed": passed,
        "detail": detail,
    }


def _hidden_test_ci_policy_no_new_dependencies(
    repo_root: Path,
    ci_policy_module: Any,
) -> dict[str, Any]:
    pyproject = tomllib.loads((repo_root / "pyproject.toml").read_text())
    dependencies = pyproject.get("project", {}).get("dependencies")
    return {
        "name": "test_ci_policy_no_new_dependencies",
        "passed": dependencies == [],
        "detail": f"dependencies={dependencies}",
    }


def _downstream_causal_reason(
    selected_context: list[dict[str, Any]],
    passed: int,
    failed: int,
) -> str:
    if failed == 0 and _selected_context_mentions(selected_context, ["configerror", "missing key"]):
        return "active config policy selected: raise ConfigError with the missing key name"
    if failed and _selected_context_mentions(selected_context, ["return none", "config"]):
        return "stale config policy selected: return None fails current config fixture tests"
    if failed == 0 and _selected_context_mentions(selected_context, ["tenant", "60"]):
        return "active cache policy selected: tenant-aware key with 60 second TTL"
    if failed and _selected_context_mentions(selected_context, ["user id", "300"]):
        return "stale cache policy selected: user-only key and 300 second TTL"
    if failed == 0 and _selected_context_mentions(selected_context, ["redact", "[redacted]"]):
        return "active serializer policy selected: redact email values"
    if failed and _selected_context_mentions(selected_context, ["raw email"]):
        return "stale serializer policy selected: raw email values leak"
    if failed == 0 and _selected_context_mentions(selected_context, ["cursor", "100"]):
        return "active pagination policy selected: cursor tokens with limit clamped to 100"
    if failed and _selected_context_mentions(selected_context, ["page numbers", "offset"]):
        return "stale pagination policy selected: offset requests fail current pagination fixture tests"
    if failed == 0 and _selected_context_mentions(selected_context, ["x-api-key", "timeout=10"]):
        return "active API client policy selected: X-Api-Key header with timeout=10"
    if failed and _selected_context_mentions(selected_context, ["authorization", "timeout=5"]):
        return "stale API client policy selected: Authorization header and timeout=5 fail current fixture tests"
    if failed == 0 and _selected_context_mentions(
        selected_context,
        ["x-api-key", "strip caller authorization", "oauth code mode", "bearer"],
    ):
        return "active provider auth policy selected: standard mode strips Authorization and OAuth mode keeps Bearer"
    if failed and _selected_context_mentions(
        selected_context,
        ["forward caller authorization", "x-api-key"],
    ):
        return "stale provider auth policy selected: forwarding both Authorization and X-Api-Key fails current fixture tests"
    if failed == 0 and _selected_context_mentions(
        selected_context,
        ["minimal reproducer", "fix forward"],
    ):
        return "active CI JIT policy selected: fail fast and fix forward with a minimal reproducer"
    if failed and _selected_context_mentions(
        selected_context,
        ["retry loops", "continue-on-error", "skip markers"],
    ):
        return "stale CI JIT policy selected: retry and nonblocking workarounds fail current fixture tests"
    if _context_contains_current_retry_policy(selected_context) and failed == 0:
        return "active retry policy selected: five attempts with exponential backoff and no dependency change"
    if failed:
        return "stale retry policy selected: three fixed-delay attempts fail current retry fixture tests"
    return "downstream fixture tests passed"


def _selected_context_mentions(
    selected_context: list[dict[str, Any]],
    terms: list[str],
) -> bool:
    joined = "\n".join(str(item.get("text", "")).lower() for item in selected_context)
    return all(term in joined for term in terms)
