import copy
import json
import unittest
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator, FormatChecker


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_ROOT = ROOT / "specs" / "001-recallpack-v4" / "contracts"


def _load_json(name: str) -> dict:
    return json.loads((CONTRACT_ROOT / name).read_text())


def _load_openapi(name: str) -> dict:
    return yaml.safe_load((CONTRACT_ROOT / name).read_text())


def _local_refs(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "$ref" and isinstance(item, str) and item.startswith("#/"):
                yield item
            yield from _local_refs(item)
    elif isinstance(value, list):
        for item in value:
            yield from _local_refs(item)


def _resolve_pointer(document: dict, reference: str):
    current = document
    for part in reference[2:].split("/"):
        current = current[part.replace("~1", "/").replace("~0", "~")]
    return current


def _definition_validator(schema: dict, name: str) -> Draft202012Validator:
    return Draft202012Validator(
        {
            "$schema": schema["$schema"],
            "$defs": schema["$defs"],
            "$ref": f"#/$defs/{name}",
        },
        format_checker=FormatChecker(),
    )


class V4ContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not CONTRACT_ROOT.is_dir():
            raise unittest.SkipTest(
                "V4 design contracts are not included in the pre-V4 sanitized bundle"
            )

    def test_json_schemas_pass_draft_2020_12_metaschema(self):
        for name in ("artifacts.schema.json", "evaluation.schema.json"):
            with self.subTest(name=name):
                Draft202012Validator.check_schema(_load_json(name))

    def test_openapi_documents_are_31_and_have_no_unresolved_local_refs(self):
        for name in ("observe.openapi.yaml", "compile.openapi.yaml"):
            with self.subTest(name=name):
                document = _load_openapi(name)
                self.assertEqual(document["openapi"], "3.1.0")
                for reference in _local_refs(document):
                    _resolve_pointer(document, reference)

    def test_compile_503_requires_explicit_no_publication(self):
        document = _load_openapi("compile.openapi.yaml")
        schema = document["components"]["schemas"]["ServiceUnavailableResponse"]
        validator = Draft202012Validator(schema)
        valid = {
            "status_code": 503,
            "error": "artifact_validation_failed",
            "artifacts_published": False,
        }
        self.assertEqual([], list(validator.iter_errors(valid)))

        missing = dict(valid)
        missing.pop("artifacts_published")
        published = dict(valid, artifacts_published=True)
        self.assertTrue(list(validator.iter_errors(missing)))
        self.assertTrue(list(validator.iter_errors(published)))

    def test_observe_400_rejects_provider_failure_codes(self):
        document = _load_openapi("observe.openapi.yaml")
        schema = document["components"]["schemas"]["ErrorResponse"]
        validator = Draft202012Validator(schema)
        self.assertEqual(
            [],
            list(
                validator.iter_errors(
                    {"status_code": 400, "error": "invalid_timestamp"}
                )
            ),
        )
        self.assertTrue(
            list(
                validator.iter_errors(
                    {"status_code": 400, "error": "provider_timeout"}
                )
            )
        )

    def test_context_contract_rejects_513_and_swapped_budget_policies(self):
        schema = _load_json("evaluation.schema.json")
        context = {
            "artifact_id": "context_1",
            "sha256": "a" * 64,
            "exact_token_count": 512,
            "tokenizer": {
                "encoding": "o200k_base",
                "package": "tiktoken",
                "package_version": "0.13.0",
                "exact": True,
            },
            "budget_policy": "exact_512_max",
        }
        context_validator = _definition_validator(schema, "contextEvidence")
        self.assertEqual([], list(context_validator.iter_errors(context)))
        over_budget = dict(context, exact_token_count=513)
        self.assertTrue(list(context_validator.iter_errors(over_budget)))

        run_definition = schema["$defs"]["run"]
        policy_validator = Draft202012Validator(
            {
                "$schema": schema["$schema"],
                "$defs": schema["$defs"],
                "type": "object",
                "required": ["variant_id", "context_evidence"],
                "properties": {
                    "variant_id": run_definition["properties"]["variant_id"],
                    "context_evidence": run_definition["properties"][
                        "context_evidence"
                    ],
                },
                "allOf": [run_definition["allOf"][0]],
            },
            format_checker=FormatChecker(),
        )
        raw = {
            "variant_id": "raw_full_history",
            "context_evidence": dict(
                context,
                budget_policy="unbounded_reference",
                exact_token_count=900,
            ),
        }
        comparable = {
            "variant_id": "recallpack",
            "context_evidence": context,
        }
        self.assertEqual([], list(policy_validator.iter_errors(raw)))
        self.assertEqual([], list(policy_validator.iter_errors(comparable)))

        raw_wrong = copy.deepcopy(raw)
        raw_wrong["context_evidence"]["budget_policy"] = "exact_512_max"
        comparable_wrong = copy.deepcopy(comparable)
        comparable_wrong["context_evidence"][
            "budget_policy"
        ] = "unbounded_reference"
        self.assertTrue(list(policy_validator.iter_errors(raw_wrong)))
        self.assertTrue(list(policy_validator.iter_errors(comparable_wrong)))


if __name__ == "__main__":
    unittest.main()
