from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime
from fnmatch import fnmatchcase
import hashlib
import os
from pathlib import Path
import re
import stat
from typing import Any, Mapping

from recallpack.downstream import (
    PATCH_GENERATION_MAX_TOKENS,
    PATCH_GENERATION_SYSTEM_MESSAGE,
    build_patch_generation_tool_contract,
)
from recallpack.evaluation_docker import (
    BUILD_CONTEXT_EXCLUSIONS,
    build_runtime_evaluator_contract,
)
from recallpack.evaluation_v4 import V4_VARIANTS
from recallpack.evidence_review_protocol import (
    _expected_v41_writable_paths,
    derive_external_artifact_slots,
)
from recallpack.review_json import (
    canonicalize_review_json,
    parse_review_json,
    review_json_sha256,
)
from recallpack.secure_files import canonical_relative_parts


_DIGEST_PATTERN = re.compile(r"^sha256:[a-f0-9]{64}$")
_BUNDLE_PATH_PATTERN = re.compile(
    r"^[A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)*$"
)
_SCENARIOS = (
    (
        "projectodyssey",
        "evaluation/scenarios/projectodyssey",
        "fixtures/project-h-projectodyssey-jit/repo_snapshot",
        "evaluation/hidden-tests/projectodyssey",
    ),
    (
        "deepagents",
        "evaluation/scenarios/deepagents",
        "fixtures/project-i-deepagents-package/repo_snapshot",
        "evaluation/hidden-tests/deepagents",
    ),
)
_TECHNICAL_FAILURE_CODES = (
    "provider_timeout",
    "provider_rate_limit",
    "provider_server_error",
    "provider_network_error",
    "provider_http_response_unparseable",
    "model_output_unparseable_after_repair",
    "provider_operator_action_required",
    "sqlite_busy",
    "sqlite_io_error",
    "sandbox_unavailable",
    "sandbox_timeout",
)


@dataclass(frozen=True)
class ReviewSeedDraftResult:
    seed_draft_path: Path
    artifact_count: int
    execution_slot_count: int


def build_r2_review_seed_draft(
    *,
    repository_root: Path,
    output_dir: str,
    created_at: str,
    evaluator_image_digest: str,
    platform: str,
) -> ReviewSeedDraftResult:
    root = _canonical_root(repository_root)
    _validate_timestamp(created_at)
    if _DIGEST_PATTERN.fullmatch(evaluator_image_digest) is None:
        raise ValueError("invalid evaluator image digest")
    if platform not in {"linux/amd64", "linux/arm64"}:
        raise ValueError("invalid evaluator platform")
    output_parts = canonical_relative_parts(output_dir)
    output = root.joinpath(*output_parts)
    if output.exists():
        raise FileExistsError("review seed draft target already exists")

    artifact_payloads: dict[str, bytes] = {}
    artifact_paths: dict[str, str] = {}
    artifact_kinds: dict[str, str] = {}
    scenarios: list[dict[str, Any]] = []
    for slot, source_relative, repository_relative, hidden_relative in _SCENARIOS:
        scenario, payloads = _build_scenario(
            root,
            output_dir="/".join(output_parts),
            slot=slot,
            source_root=root / source_relative,
            repository_root=root / repository_relative,
            hidden_test_root=root / hidden_relative,
        )
        scenarios.append(scenario)
        for artifact_id, (kind, relative_path, payload) in payloads.items():
            artifact_kinds[artifact_id] = kind
            artifact_paths[artifact_id] = relative_path
            artifact_payloads[artifact_id] = payload

    dockerfile_path = "evaluation/Dockerfile"
    runner_path = "evaluation/runner/run_tests.py"
    dockerfile = (root / dockerfile_path).read_bytes()
    runner = (root / runner_path).read_bytes()
    base_image_digest = _dockerfile_base_digest(dockerfile)
    evaluator = build_runtime_evaluator_contract(
        platform=platform,
        image_digest=evaluator_image_digest,
        base_image_digest=base_image_digest,
    )
    common = _build_common_artifacts(
        output_dir="/".join(output_parts),
        evaluator=evaluator,
        dockerfile=dockerfile,
        runner=runner,
        dockerfile_path=dockerfile_path,
        runner_path=runner_path,
        build_context_sha256=compute_evaluator_build_context_sha256(
            root / "evaluation"
        ),
    )
    for artifact_id, (kind, relative_path, payload) in common.items():
        artifact_kinds[artifact_id] = kind
        artifact_paths[artifact_id] = relative_path
        artifact_payloads[artifact_id] = payload

    catalog = {
        artifact_id: _artifact_record(
            artifact_kinds[artifact_id],
            artifact_paths[artifact_id],
            payload,
        )
        for artifact_id, payload in artifact_payloads.items()
    }
    comparison = _comparison_contract(scenarios)
    execution_order = _execution_order(scenarios)
    seed: dict[str, Any] = {
        "record_type": "evaluation_review_seed",
        "review_seed_version": "review-seed/4.1",
        "semantic_rules_version": "4.1",
        "created_at": created_at,
        "target_rung": "R2",
        "code_hashes": {
            field: hashlib.sha256(f"generator-replaces:{field}".encode()).hexdigest()
            for field in (
                "runtime_tree_sha256",
                "evaluator_tree_sha256",
                "evaluation_schema_sha256",
                "dependency_lock_sha256",
            )
        },
        "scenario_plan": scenarios,
        "variants": list(V4_VARIANTS),
        "provider_settings": {
            "mode": "live",
            "provider_family": "qwen_cloud",
            "deterministic_fallback": False,
            "models": {
                "memory_decision": "qwen3.7-plus-2026-05-26",
                "embedding": "text-embedding-v4",
                "rerank": "qwen3-rerank",
                "patch_generation": "qwen3.7-plus-2026-05-26",
            },
            "temperature": 0,
            "seed": 7,
            "endpoint_region": "cn-beijing",
        },
        "comparison_contract": comparison,
        "evaluator_contract": evaluator,
        "technical_failure_codes": list(_TECHNICAL_FAILURE_CODES),
        "execution_order": execution_order,
        "claim_declarations": [
            {
                "claim_id": "claim_structural_runtime",
                "claim_type": "structural_runtime",
                "activation_rule_id": "structural_runtime_gate",
                "eligible_rungs": ["Full", "R1", "R2", "Floor"],
                "statement": (
                    "The frozen RecallPack runtime, provider-role contract, and "
                    "isolated evaluator executed under the registered R2 manifest."
                ),
                "rerunnable_command": (
                    "PYTHONPATH=src python3 -m unittest discover -s tests -v"
                ),
                "limitations": [
                    "R2 has no blind holdout.",
                    "The structural claim does not establish downstream superiority.",
                    "The public scenarios are source-backed synthetic events, not production traces.",
                ],
            }
        ],
        "evaluator_image_digest": evaluator_image_digest,
        "frozen_input_artifact_catalog": catalog,
        "external_artifact_slots": [],
    }
    seed["external_artifact_slots"] = derive_external_artifact_slots(seed)

    output.mkdir(parents=True, exist_ok=False)
    for artifact_id, payload in artifact_payloads.items():
        target = root / artifact_paths[artifact_id]
        if target in {root / dockerfile_path, root / runner_path}:
            continue
        _write_new_file(target, payload)
    draft_path = output / "seed-draft.json"
    _write_new_file(draft_path, canonicalize_review_json(seed))
    return ReviewSeedDraftResult(
        seed_draft_path=draft_path,
        artifact_count=len(catalog),
        execution_slot_count=len(execution_order),
    )


def build_deterministic_file_bundle(
    root: Path,
    *,
    scenario_slot: str,
    purpose: str,
) -> dict[str, Any]:
    canonical_root = _canonical_root(root)
    if purpose not in {"fixture", "hidden_tests"}:
        raise ValueError("invalid deterministic bundle purpose")
    files: list[dict[str, Any]] = []
    aggregate_bytes = 0
    for path in sorted(
        canonical_root.rglob("*"),
        key=lambda item: item.relative_to(canonical_root).as_posix().encode("ascii"),
    ):
        relative = path.relative_to(canonical_root).as_posix()
        if path.is_symlink():
            raise ValueError("deterministic bundle cannot contain symlinks")
        if any(part == "__pycache__" for part in path.relative_to(canonical_root).parts):
            continue
        if path.is_dir():
            continue
        if path.name == ".DS_Store" or path.suffix == ".pyc":
            continue
        metadata = path.stat(follow_symlinks=False)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
            raise ValueError("deterministic bundle requires unique regular files")
        if _BUNDLE_PATH_PATTERN.fullmatch(relative) is None:
            raise ValueError("deterministic bundle path is not canonical ASCII")
        payload = path.read_bytes()
        if len(payload) > 1_048_576:
            raise ValueError("deterministic bundle file exceeds size limit")
        aggregate_bytes += len(payload)
        if aggregate_bytes > 16_777_216:
            raise ValueError("deterministic bundle exceeds aggregate size limit")
        files.append(
            {
                "path": relative,
                "sha256": hashlib.sha256(payload).hexdigest(),
                "bytes": len(payload),
                "content_base64": base64.b64encode(payload).decode("ascii"),
            }
        )
    if not files:
        raise ValueError("deterministic bundle cannot be empty")
    return {
        "record_type": "deterministic_file_bundle",
        "bundle_version": "deterministic-file-bundle/4.1",
        "scenario_slot": scenario_slot,
        "purpose": purpose,
        "files": files,
    }


def compute_evaluator_build_context_sha256(evaluation_root: Path) -> str:
    root = _canonical_root(evaluation_root)
    patterns = tuple(
        line.strip()
        for line in (root / ".dockerignore").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    )
    if patterns != BUILD_CONTEXT_EXCLUSIONS:
        raise ValueError("Docker ignore file differs from evaluator contract")
    leaves: list[tuple[bytes, bytes]] = []
    for path in root.rglob("*"):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            raise ValueError("evaluator build context cannot contain symlinks")
        if _docker_ignored(relative, patterns):
            continue
        if path.is_dir():
            continue
        metadata = path.stat(follow_symlinks=False)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
            raise ValueError("evaluator build context requires unique regular files")
        payload_hash = hashlib.sha256(path.read_bytes()).hexdigest().encode("ascii")
        path_bytes = relative.encode("utf-8")
        leaves.append((path_bytes, path_bytes + b"\0" + payload_hash + b"\n"))
    if not leaves:
        raise ValueError("evaluator build context is empty")
    return hashlib.sha256(b"".join(leaf for _, leaf in sorted(leaves))).hexdigest()


def _build_scenario(
    root: Path,
    *,
    output_dir: str,
    slot: str,
    source_root: Path,
    repository_root: Path,
    hidden_test_root: Path,
) -> tuple[dict[str, Any], dict[str, tuple[str, str, bytes]]]:
    events = _read_jsonl(source_root / "authored-events.jsonl")
    source_ledger = parse_review_json((source_root / "source-ledger.json").read_bytes())
    source_ledger_bytes = canonicalize_review_json(source_ledger)
    source_ledger_sha256 = review_json_sha256(source_ledger)
    expected_entries = source_ledger.get("entries") if isinstance(source_ledger, Mapping) else None
    if not isinstance(expected_entries, list) or len(expected_entries) != len(events):
        raise ValueError(f"{slot} source ledger does not cover authored events")
    for entry, event in zip(expected_entries, events, strict=True):
        if (
            entry.get("source_ref") != event.get("source_ref")
            or entry.get("model_visible") is not True
            or entry.get("event_sha256") != review_json_sha256(event)
        ):
            raise ValueError(f"{slot} source ledger event binding failed")

    fixture = {
        "record_type": "fixture",
        "scenario_slot": slot,
        "events": events,
    }
    snapshot = {
        "record_type": "model_visible_snapshot",
        "scenario_slot": slot,
        "source_ledger_sha256": source_ledger_sha256,
        "events": events,
    }
    diagnostic_provenance = parse_review_json((source_root / "provenance.json").read_bytes())
    summaries = [
        {"source_ref": event["source_ref"], "summary": event["summary"]}
        for event in events
    ]
    provenance = {
        "record_type": "source_provenance",
        "scenario_slot": slot,
        "evidence_class": "source_backed_synthetic",
        "production_trace": False,
        "copied_source_text": False,
        "authored_summaries": True,
        "repository_url": diagnostic_provenance["repository_url"],
        "commit_refs": diagnostic_provenance["commit_refs"],
        "license_id": diagnostic_provenance["license_id"],
        "authored_summary_sha256": review_json_sha256(summaries),
    }
    repository_bundle = build_deterministic_file_bundle(
        repository_root,
        scenario_slot=slot,
        purpose="fixture",
    )
    hidden_bundle = build_deterministic_file_bundle(
        hidden_test_root,
        scenario_slot=slot,
        purpose="hidden_tests",
    )
    hidden_content_sha256 = hashlib.sha256(
        canonicalize_review_json(hidden_bundle)
    ).hexdigest()
    payloads = {
        f"fixture_{slot}": (
            "fixture",
            f"{output_dir}/inputs/scenarios/{slot}/fixture.json",
            canonicalize_review_json(fixture),
        ),
        f"source_ledger_{slot}": (
            "source_ledger",
            f"{output_dir}/inputs/scenarios/{slot}/source-ledger.json",
            source_ledger_bytes,
        ),
        f"repository_snapshot_{slot}": (
            "repository_snapshot",
            f"{output_dir}/inputs/scenarios/{slot}/repository-snapshot.json",
            canonicalize_review_json(repository_bundle),
        ),
        f"model_visible_snapshot_{slot}": (
            "model_visible_snapshot",
            f"{output_dir}/inputs/scenarios/{slot}/model-visible-snapshot.json",
            canonicalize_review_json(snapshot),
        ),
        f"hidden_test_hash_{slot}": (
            "hidden_test_hash",
            f"{output_dir}/inputs/scenarios/{slot}/hidden-test-content.sha256",
            hidden_content_sha256.encode("ascii"),
        ),
        f"provenance_{slot}": (
            "source_provenance",
            f"{output_dir}/inputs/scenarios/{slot}/provenance.json",
            canonicalize_review_json(provenance),
        ),
    }
    scenario = {
        "scenario_slot": slot,
        "evidence_class": "source_backed_synthetic",
        "fixture_artifact_id": f"fixture_{slot}",
        "fixture_sha256": hashlib.sha256(payloads[f"fixture_{slot}"][2]).hexdigest(),
        "source_ledger_artifact_id": f"source_ledger_{slot}",
        "source_ledger_sha256": source_ledger_sha256,
        "repository_snapshot_artifact_id": f"repository_snapshot_{slot}",
        "repository_snapshot_sha256": hashlib.sha256(
            payloads[f"repository_snapshot_{slot}"][2]
        ).hexdigest(),
        "model_visible_snapshot_artifact_id": f"model_visible_snapshot_{slot}",
        "model_visible_snapshot_sha256": review_json_sha256(snapshot),
        "hidden_test_hash_artifact_id": f"hidden_test_hash_{slot}",
        "hidden_test_content_sha256": hidden_content_sha256,
        "provenance_artifact_id": f"provenance_{slot}",
        "provenance_sha256": review_json_sha256(provenance),
    }
    return scenario, payloads


def _build_common_artifacts(
    *,
    output_dir: str,
    evaluator: Mapping[str, Any],
    dockerfile: bytes,
    runner: bytes,
    dockerfile_path: str,
    runner_path: str,
    build_context_sha256: str,
) -> dict[str, tuple[str, str, bytes]]:
    tool = build_patch_generation_tool_contract()
    patch_contract = canonicalize_review_json(
        {
            "record_type": "patch_provider_contract",
            "contract_version": "4.1",
            "provider_role": "patch_generation",
            "request_fields": [
                "goal",
                "selected_context",
                "allowed_edit_paths",
                "source_files",
            ],
            "response_tool": tool,
            "complete_replacement_files": True,
            "path_allowlist_required": True,
            "hidden_test_visibility": "after_model_output_fixed",
            "deterministic_fallback": False,
        }
    )
    prompt_template = canonicalize_review_json(
        {
            "record_type": "patch_prompt_template",
            "template_version": "4.1",
            "system_message": PATCH_GENERATION_SYSTEM_MESSAGE,
            "user_message": "json.dumps(build_patch_model_payload(request), sort_keys=True)",
            "tool": tool,
            "tool_choice": {
                "type": "function",
                "function": {"name": "generate_patch"},
            },
            "enable_thinking": False,
            "temperature": 0,
            "max_tokens": PATCH_GENERATION_MAX_TOKENS,
        }
    )
    runner_contract = canonicalize_review_json(
        {
            "record_type": "runner_contract",
            "contract_version": "4.1",
            "entrypoint": "/runner/run_tests.py",
            "network": "none",
            "hidden_test_visibility": "after_model_output_fixed",
            "repository_mount_mode": "rw",
            "hidden_test_mount_mode": "ro",
            "result_format": "closed_json_per_test",
            "build_context_hash_algorithm": (
                "sha256(sorted(path_utf8 + NUL + file_sha256_ascii + LF))"
            ),
        }
    )
    image_build_record = canonicalize_review_json(
        {
            "record_type": "image_build_record",
            "builder": "docker_buildx",
            "platform": evaluator["platform"],
            "build_context_root": evaluator["build_context_root"],
            "build_context_sha256": build_context_sha256,
            "dockerfile_artifact_id": "evaluator_dockerfile",
            "dockerfile_sha256": hashlib.sha256(dockerfile).hexdigest(),
            "runner_artifact_id": "evaluator_runner",
            "runner_sha256": hashlib.sha256(runner).hexdigest(),
            "dockerfile_from_base_image_digest": evaluator["base_image_digest"],
            "output_image_digest": evaluator["image_digest"],
        }
    )
    return {
        "patch_provider_contract": (
            "patch_provider_contract",
            f"{output_dir}/inputs/common/patch-provider-contract.json",
            patch_contract,
        ),
        "prompt_template": (
            "prompt_template",
            f"{output_dir}/inputs/common/prompt-template.json",
            prompt_template,
        ),
        "runner_contract": (
            "runner_contract",
            f"{output_dir}/inputs/common/runner-contract.json",
            runner_contract,
        ),
        "evaluator_dockerfile": ("dockerfile", dockerfile_path, dockerfile),
        "evaluator_runner": ("evaluator_runner", runner_path, runner),
        "evaluator_image_build_record": (
            "image_build_record",
            f"{output_dir}/inputs/common/evaluator-image-build-record.json",
            image_build_record,
        ),
    }


def _comparison_contract(scenarios: list[Mapping[str, Any]]) -> dict[str, Any]:
    semantic_roles = {
        "required_roles": ["embedding", "rerank", "patch_generation"],
        "allowed_roles": ["embedding", "rerank", "patch_generation"],
        "repeatable_roles": ["embedding"],
        "singleton_roles": ["rerank", "patch_generation"],
    }
    lifecycle_roles = {
        "required_roles": [
            "memory_decision",
            "embedding",
            "rerank",
            "patch_generation",
        ],
        "allowed_roles": [
            "memory_decision",
            "embedding",
            "rerank",
            "patch_generation",
        ],
        "repeatable_roles": ["memory_decision", "embedding"],
        "singleton_roles": ["rerank", "patch_generation"],
    }
    return {
        "budget_tokens": 512,
        "tokenizer": {
            "encoding": "o200k_base",
            "package": "tiktoken",
            "package_version": "0.13.0",
            "exact": True,
        },
        "patch_provider_contract_artifact_id": "patch_provider_contract",
        "prompt_template_artifact_id": "prompt_template",
        "runner_contract_artifact_id": "runner_contract",
        "writable_paths": _expected_v41_writable_paths(scenarios),
        "hidden_test_visibility": "after_model_output_fixed",
        "budget_scope": "budget_comparable_variants_only",
        "variant_input_policy": "identical_across_budget_comparable_variants",
        "variant_comparability": {
            "raw_full_history": {
                "budget_comparable": False,
                "budget_policy": "unbounded_reference",
                "headline_comparator_eligible": False,
            },
            "semantic_rerank": {
                "budget_comparable": True,
                "budget_policy": "exact_512_max",
                "headline_comparator_eligible": True,
            },
            "recency_aware": {
                "budget_comparable": True,
                "budget_policy": "exact_512_max",
                "headline_comparator_eligible": True,
            },
            "recall_time_resolver": {
                "budget_comparable": True,
                "budget_policy": "exact_512_max",
                "headline_comparator_eligible": True,
            },
            "recallpack": {
                "budget_comparable": True,
                "budget_policy": "exact_512_max",
                "headline_comparator_eligible": False,
            },
        },
        "variant_provider_role_contract": {
            "raw_full_history": {
                "required_roles": ["patch_generation"],
                "allowed_roles": ["patch_generation"],
                "repeatable_roles": [],
                "singleton_roles": ["patch_generation"],
            },
            "semantic_rerank": dict(semantic_roles),
            "recency_aware": dict(semantic_roles),
            "recall_time_resolver": dict(lifecycle_roles),
            "recallpack": dict(lifecycle_roles),
        },
    }


def _execution_order(scenarios: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for scenario in scenarios:
        for variant in V4_VARIANTS:
            for repetition in range(1, 4):
                index = len(result)
                result.append(
                    {
                        "slot_id": (
                            f"slot_{scenario['scenario_slot']}_{variant}_{repetition}"
                        ),
                        "slot_index": index,
                        "scenario_slot": scenario["scenario_slot"],
                        "variant_id": variant,
                        "repetition": repetition,
                        "planned_designation": "headline",
                    }
                )
    return result


def _artifact_record(kind: str, relative_path: str, payload: bytes) -> dict[str, Any]:
    return {
        "kind": kind,
        "origin": "seed_frozen",
        "relative_path": relative_path,
        "sha256": hashlib.sha256(payload).hexdigest(),
        "bytes": len(payload),
        "sanitized": True,
        "content_policy": "sanitized_bounded",
    }


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for line in path.read_bytes().splitlines():
        if not line.strip():
            continue
        value = parse_review_json(line)
        if not isinstance(value, dict):
            raise ValueError("authored event must be an object")
        events.append(value)
    if not events:
        raise ValueError("authored event stream cannot be empty")
    return events


def _dockerfile_base_digest(dockerfile: bytes) -> str:
    matches = re.findall(rb"^FROM\s+\S+@(sha256:[a-f0-9]{64})\s*$", dockerfile, re.MULTILINE)
    if len(matches) != 1:
        raise ValueError("Dockerfile must contain one pinned base image digest")
    return matches[0].decode("ascii")


def _docker_ignored(relative: str, patterns: tuple[str, ...]) -> bool:
    parts = relative.split("/")
    for pattern in patterns:
        if pattern.startswith("**/"):
            tail = pattern[3:]
            if any(fnmatchcase(part, tail) for part in parts):
                return True
        elif "/" not in pattern:
            if any(fnmatchcase(part, pattern) for part in parts):
                return True
        elif pattern.endswith("/**"):
            prefix = pattern[:-3].rstrip("/")
            if relative == prefix or relative.startswith(prefix + "/"):
                return True
        elif fnmatchcase(relative, pattern):
            return True
    return False


def _write_new_file(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        view = memoryview(payload)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise OSError("short write while creating review-seed draft")
            view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _canonical_root(path: Path) -> Path:
    if not path.is_absolute():
        raise ValueError("root path must be absolute")
    resolved = path.resolve(strict=True)
    if resolved != path or path.is_symlink() or not path.is_dir():
        raise ValueError("root path must be canonical and non-symlinked")
    return resolved


def _validate_timestamp(value: str) -> None:
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except (TypeError, ValueError) as exc:
        raise ValueError("created_at must be exact UTC") from exc
    if parsed.strftime("%Y-%m-%dT%H:%M:%SZ") != value:
        raise ValueError("created_at must be exact UTC")
