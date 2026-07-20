from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path
from types import SimpleNamespace

from recallpack.downstream import (
    PatchGenerationRequest,
    PatchGenerationResult,
    _parse_patch_generation_response,
    run_downstream_proof,
)
from recallpack.downstream_contract import (
    MAX_MODEL_INPUT_BYTES,
    PatchContractError,
    build_patch_model_payload,
    validate_patch_generation_request,
    validate_patch_generation_result,
)
from recallpack.evaluation import load_hero_fixture
from recallpack.providers import ProviderError, ProviderTrace, TEXT_MODEL


ROOT = Path(__file__).resolve().parents[1]


def _request() -> PatchGenerationRequest:
    return PatchGenerationRequest(
        goal="Update retry behavior from the active project policy.",
        selected_context=[
            {
                "id": "mem_active",
                "type": "decision",
                "subject": "retry_policy",
                "scope": "component:retry",
                "source_ref": "session-current:turn-005",
                "text": "Use five attempts with exponential backoff.",
            }
        ],
        allowed_paths=["src/retry.py", "pyproject.toml"],
        source_files=[
            {
                "path": "src/retry.py",
                "content": "def retry(operation):\n    return operation()\n",
            },
            {"path": "pyproject.toml", "content": "[project]\nname='demo'\n"},
        ],
    )


def _trace(*, output_item_count: int = 1) -> ProviderTrace:
    return ProviderTrace(
        provider_name="fake-qwen",
        model_id=TEXT_MODEL,
        provider_role="patch_generation",
        request_purpose="generate_patch_from_goal_and_selected_context",
        input_item_count=2,
        input_token_estimate=32,
        output_item_count=output_item_count,
        request_id="patch-contract-test",
    )


def _result(**overrides) -> PatchGenerationResult:
    values = {
        "files": [
            {
                "path": "src/retry.py",
                "content": "def retry(operation):\n    return operation()  # updated\n",
            }
        ],
        "trace": _trace(),
        "used_gold_patch_variants": False,
    }
    values.update(overrides)
    return PatchGenerationResult(**values)


class EmptyPatchProvider:
    def generate_patch(self, request):
        return PatchGenerationResult(files=[], trace=_trace(output_item_count=0))


class MalformedPatchProvider:
    def generate_patch(self, request):
        return PatchGenerationResult(files=[7], trace=_trace())


class MutatingAllowlistPatchProvider:
    def generate_patch(self, request):
        request.allowed_paths.append("README.md")
        return PatchGenerationResult(
            files=[{"path": "README.md", "content": "changed\n"}],
            trace=_trace(),
        )


class MissingResultPatchProvider:
    def generate_patch(self, request):
        return None


class TerminalFailurePatchProvider:
    def generate_patch(self, request):
        raise ProviderError.terminal(
            provider_name="qwen-cloud",
            model_id=TEXT_MODEL,
            message="malformed patch response",
            request_id="terminal-patch-request",
        )


class ExplodingTracePatchProvider:
    def generate_patch(self, request):
        class ExplodingTrace:
            provider_name = "broken-provider"
            usage = {}

            def to_sanitized_record(self):
                raise RuntimeError("trace serializer failed")

        return PatchGenerationResult(
            files=[{"path": "src/retry.py", "content": "changed\n"}],
            trace=ExplodingTrace(),
        )


class PoisonValidationTracePatchProvider:
    def generate_patch(self, request):
        class PoisonValidationTrace:
            @property
            def provider_role(self):
                raise RuntimeError("poison trace attribute")

        return PatchGenerationResult(
            files=[{"path": "src/retry.py", "content": "changed\n"}],
            trace=PoisonValidationTrace(),
        )


class DownstreamPatchContractTests(unittest.TestCase):
    def assert_contract_error(self, code: str, fn, *args, **kwargs):
        with self.assertRaises(PatchContractError) as raised:
            fn(*args, **kwargs)
        self.assertEqual(code, raised.exception.code)
        self.assertTrue(str(raised.exception).startswith(f"patch-contract/1.0 {code}"))

    def test_request_payload_is_closed_and_provenance_neutral(self):
        request = _request()
        validate_patch_generation_request(request)
        payload = build_patch_model_payload(request)

        self.assertEqual(
            set(payload),
            {
                "task",
                "goal",
                "selected_context",
                "allowed_edit_paths",
                "primary_source_path",
                "source_files",
                "edit_policy",
                "output_contract",
            },
        )
        self.assertEqual(
            set(payload["selected_context"][0]),
            {"type", "subject", "scope", "text"},
        )
        serialized = json.dumps(payload, sort_keys=True)
        self.assertNotIn("mem_active", serialized)
        self.assertNotIn("session-current:turn-005", serialized)
        edit_policy = "\n".join(payload["edit_policy"]).lower()
        self.assertNotIn("false/zero", edit_policy)
        self.assertNotIn("minimal reproducer", edit_policy)
        self.assertNotIn("continue-on-error", edit_policy)

        changed_provenance = copy.deepcopy(request)
        changed_provenance.selected_context[0]["id"] = "different-memory"
        changed_provenance.selected_context[0]["source_ref"] = "other:turn-999"
        self.assertEqual(payload, build_patch_model_payload(changed_provenance))

    def test_request_rejects_gold_hidden_and_unsafe_input_shapes(self):
        leaked_context = _request()
        leaked_context.selected_context[0]["hidden_test_predicate"] = "expect five"
        self.assert_contract_error(
            "forbidden_model_input",
            validate_patch_generation_request,
            leaked_context,
        )

        gold_context = _request()
        gold_context.selected_context[0]["gold_selected_source_ids"] = ["mem_active"]
        self.assert_contract_error(
            "forbidden_model_input",
            validate_patch_generation_request,
            gold_context,
        )

        duplicate_paths = _request()
        duplicate_paths.allowed_paths.append("src/retry.py")
        self.assert_contract_error(
            "invalid_allowed_paths",
            validate_patch_generation_request,
            duplicate_paths,
        )

        unsafe_source = _request()
        unsafe_source.source_files.append(
            {"path": "../private.txt", "content": "private"}
        )
        self.assert_contract_error(
            "invalid_source_files",
            validate_patch_generation_request,
            unsafe_source,
        )

        leaked_value = _request()
        leaked_value.selected_context[0]["text"] = (
            "Hidden test test_secret expects value=GOLD-42."
        )
        self.assert_contract_error(
            "forbidden_model_input",
            validate_patch_generation_request,
            leaked_value,
        )

        leaked_goal = _request()
        object.__setattr__(leaked_goal, "goal", "Implement the GOLD_ANSWER exactly.")
        self.assert_contract_error(
            "forbidden_model_input",
            validate_patch_generation_request,
            leaked_goal,
        )

        leaked_source = _request()
        leaked_source.source_files[0]["content"] = "# hidden_test predicate\n"
        self.assert_contract_error(
            "forbidden_model_input",
            validate_patch_generation_request,
            leaked_source,
        )

        for field in ("type", "subject", "scope"):
            with self.subTest(context_field=field):
                leaked_field = _request()
                leaked_field.selected_context[0][field] = "hiddenTestPredicate"
                self.assert_contract_error(
                    "forbidden_model_input",
                    validate_patch_generation_request,
                    leaked_field,
                )

        separated_markers = [
            ("goal", "Use GoldAnswer exactly."),
            ("path", "src/hiddenTests.py"),
            ("source", "def hiddenTestPredicate():\n    return 42\n"),
            ("goal", "Use gold.answer exactly."),
        ]
        for surface, marker in separated_markers:
            with self.subTest(surface=surface, marker=marker):
                leaked = _request()
                if surface == "goal":
                    object.__setattr__(leaked, "goal", marker)
                elif surface == "path":
                    leaked.allowed_paths[0] = marker
                    leaked.source_files.clear()
                else:
                    leaked.source_files[0]["content"] = marker
                self.assert_contract_error(
                    "forbidden_model_input" if surface != "path" else "invalid_allowed_paths",
                    validate_patch_generation_request,
                    leaked,
                )

        extra_request_field = SimpleNamespace(
            **vars(_request()),
            hidden_test_names=["test_secret"],
        )
        self.assert_contract_error(
            "forbidden_model_input",
            validate_patch_generation_request,
            extra_request_field,
        )

    def test_request_counts_the_complete_serialized_model_payload(self):
        request = _request()
        request.selected_context[0]["subject"] = "s" * MAX_MODEL_INPUT_BYTES

        self.assert_contract_error(
            "model_input_too_large",
            validate_patch_generation_request,
            request,
        )

    def test_request_rejects_filesystem_equivalent_paths(self):
        unicode_paths = _request()
        unicode_paths.allowed_paths[:] = ["src/café.py", "src/cafe\u0301.py"]
        unicode_paths.source_files.clear()
        self.assert_contract_error(
            "invalid_allowed_paths",
            validate_patch_generation_request,
            unicode_paths,
        )

        case_paths = _request()
        case_paths.allowed_paths[:] = ["src/Retry.py", "src/retry.py"]
        case_paths.source_files.clear()
        self.assert_contract_error(
            "invalid_allowed_paths",
            validate_patch_generation_request,
            case_paths,
        )

    def test_result_requires_closed_typed_files_and_matching_trace(self):
        request = _request()
        validate_patch_generation_result(_result(), request)

        self.assert_contract_error(
            "empty_patch",
            validate_patch_generation_result,
            _result(files=[], trace=_trace(output_item_count=0)),
            request,
        )
        self.assert_contract_error(
            "gold_aware_provider",
            validate_patch_generation_result,
            _result(used_gold_patch_variants=True),
            request,
        )
        self.assert_contract_error(
            "invalid_patch_files",
            validate_patch_generation_result,
            _result(files=[{"path": "src/retry.py", "content": 7}]),
            request,
        )
        self.assert_contract_error(
            "invalid_patch_files",
            validate_patch_generation_result,
            _result(
                files=[
                    {
                        "path": "src/retry.py",
                        "content": "pass\n",
                        "hidden_test_result": "passed",
                    }
                ]
            ),
            request,
        )
        self.assert_contract_error(
            "invalid_provider_trace",
            validate_patch_generation_result,
            _result(trace=_trace(output_item_count=2)),
            request,
        )

        extra_result_field = SimpleNamespace(
            **vars(_result()),
            hidden_test_result="passed",
        )
        self.assert_contract_error(
            "invalid_patch_result",
            validate_patch_generation_result,
            extra_result_field,
            request,
        )

    def test_result_rejects_total_oversize_noop_and_mapping_tricks(self):
        request = _request()
        request.allowed_paths[:] = ["src/a.txt", "src/b.txt"]
        request.source_files.clear()
        huge = "x" * (MAX_MODEL_INPUT_BYTES // 2)
        self.assert_contract_error(
            "patch_output_too_large",
            validate_patch_generation_result,
            _result(
                files=[
                    {"path": "src/a.txt", "content": huge},
                    {"path": "src/b.txt", "content": huge},
                ],
                trace=_trace(output_item_count=2),
            ),
            request,
        )

        self.assert_contract_error(
            "empty_patch",
            validate_patch_generation_result,
            _result(
                files=[
                    {
                        "path": "src/retry.py",
                        "content": "def retry(operation):\n    return operation()\n",
                    }
                ]
            ),
            _request(),
        )

        class SplitMapping(dict):
            def get(self, key, default=None):
                if key == "content":
                    return "pass\n"
                return super().get(key, default)

        self.assert_contract_error(
            "invalid_patch_files",
            validate_patch_generation_result,
            _result(
                files=[
                    SplitMapping(
                        path="src/retry.py",
                        content="import os\n",
                    )
                ]
            ),
            _request(),
        )

    def test_qwen_response_rejects_non_string_patch_fields(self):
        body = {
            "choices": [
                {
                    "message": {
                        "tool_calls": [
                            {
                                "function": {
                                    "name": "generate_patch",
                                    "arguments": json.dumps(
                                        {
                                            "files": [
                                                {
                                                    "path": "src/retry.py",
                                                    "content": 7,
                                                }
                                            ]
                                        }
                                    ),
                                }
                            }
                        ]
                    }
                }
            ]
        }

        with self.assertRaises(ProviderError) as raised:
            _parse_patch_generation_response(body, TEXT_MODEL)
        self.assertFalse(raised.exception.retryable)

    def test_qwen_response_rejects_malformed_or_ambiguous_success_shapes(self):
        bodies = [
            {"choices": []},
            {
                "choices": [
                    {
                        "message": {
                            "tool_calls": [
                                {
                                    "function": {
                                        "name": "generate_patch",
                                        "arguments": "[]",
                                    }
                                }
                            ]
                        }
                    }
                ]
            },
            {
                "choices": [
                    {
                        "message": {
                            "tool_calls": [
                                {
                                    "function": {
                                        "name": "generate_patch",
                                        "arguments": json.dumps({"files": []}),
                                    }
                                },
                                {
                                    "function": {
                                        "name": "generate_patch",
                                        "arguments": json.dumps({"files": []}),
                                    }
                                },
                            ]
                        }
                    }
                ]
            },
            {
                "choices": [
                    {
                        "message": {
                            "tool_calls": [
                                {
                                    "function": {
                                        "name": "generate_patch",
                                        "arguments": json.dumps(
                                            {"files": [], "gold": "secret"}
                                        ),
                                    }
                                }
                            ]
                        }
                    }
                ]
            },
            {
                "choices": [
                    {
                        "message": {
                            "tool_calls": [
                                {
                                    "function": {
                                        "name": "generate_patch",
                                        "arguments": json.dumps({"files": []}),
                                    }
                                }
                            ],
                            "content": json.dumps(
                                {
                                    "files": [
                                        {
                                            "path": "src/retry.py",
                                            "content": "conflicting patch\n",
                                        }
                                    ]
                                }
                            ),
                        }
                    }
                ]
            },
        ]

        for body in bodies:
            with self.subTest(body=body):
                with self.assertRaises(ProviderError) as raised:
                    _parse_patch_generation_response(body, TEXT_MODEL)
                self.assertFalse(raised.exception.retryable)

    def test_empty_patch_is_adverse_and_hidden_tests_do_not_run(self):
        fixture = load_hero_fixture(ROOT / "fixtures" / "project-a")

        result = run_downstream_proof(
            fixture,
            selected_context=[],
            variant_id="empty_patch",
            patch_provider=EmptyPatchProvider(),
        )

        self.assertFalse(result["accepted"])
        self.assertEqual(result["error"], "empty_patch")
        self.assertEqual(result["tests"], [])
        self.assertEqual(result["summary"], {"passed": 0, "failed": 3})
        self.assertEqual(
            result["causal_reason"],
            "patch rejected by downstream path validator: empty_patch",
        )

    def test_malformed_patch_rejection_is_adverse_instead_of_crashing(self):
        fixture = load_hero_fixture(ROOT / "fixtures" / "project-a")

        result = run_downstream_proof(
            fixture,
            selected_context=[],
            variant_id="malformed_patch",
            patch_provider=MalformedPatchProvider(),
        )

        self.assertFalse(result["accepted"])
        self.assertEqual(result["error"], "invalid_patch_files")
        self.assertEqual(result["patch_generation"]["output_paths"], [])
        self.assertEqual(result["tests"], [])

    def test_provider_cannot_mutate_the_frozen_request_authority(self):
        fixture = load_hero_fixture(ROOT / "fixtures" / "project-a")

        result = run_downstream_proof(
            fixture,
            selected_context=[],
            variant_id="mutating_allowlist",
            patch_provider=MutatingAllowlistPatchProvider(),
        )

        self.assertFalse(result["accepted"])
        self.assertEqual(result["error"], "path_not_allowed")
        self.assertEqual(result["tests"], [])

    def test_missing_or_terminal_provider_result_becomes_adverse_evidence(self):
        fixture = load_hero_fixture(ROOT / "fixtures" / "project-a")

        cases = [
            (MissingResultPatchProvider(), "invalid_patch_result", []),
            (TerminalFailurePatchProvider(), "provider_terminal_failure", []),
            (
                ExplodingTracePatchProvider(),
                "invalid_provider_trace",
                ["src/retry.py"],
            ),
            (
                PoisonValidationTracePatchProvider(),
                "invalid_provider_trace",
                ["src/retry.py"],
            ),
        ]
        for provider, expected_error, expected_paths in cases:
            with self.subTest(expected_error=expected_error):
                result = run_downstream_proof(
                    fixture,
                    selected_context=[],
                    variant_id="provider_failure",
                    patch_provider=provider,
                )

                self.assertFalse(result["accepted"])
                self.assertEqual(result["error"], expected_error)
                self.assertEqual(result["tests"], [])
                self.assertEqual(
                    result["patch_generation"]["output_paths"], expected_paths
                )


if __name__ == "__main__":
    unittest.main()
