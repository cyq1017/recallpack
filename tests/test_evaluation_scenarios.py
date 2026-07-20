import hashlib
import json
import re
import unittest
from pathlib import Path

from recallpack.budget import canonical_json
from tests.v4_evidence_fixtures import definition_validator


ROOT = Path(__file__).resolve().parents[1]
SCENARIO_ROOT = ROOT / "evaluation" / "scenarios"
EXPECTED = {
    "projectodyssey": {
        "license_id": "BSD-3-Clause",
        "repository_url": "https://github.com/HomericIntelligence/Odyssey",
        "commit_refs": [
            "47d9ddc0e8cfdb102ffda04dc5f932e0c2351d15",
            "147b1517e47809a78bb63b242f8578b553cc577d",
        ],
    },
    "deepagents": {
        "license_id": "MIT",
        "repository_url": "https://github.com/langchain-ai/deepagents",
        "commit_refs": [
            "18bf86d5fcb9245af9aed1fefe5d80b2200f9cfc",
            "c7b311933da6245267f4bded050c36279973de1e",
        ],
    },
    "graphiti": {
        "license_id": "Apache-2.0",
        "repository_url": "https://github.com/getzep/graphiti",
        "commit_refs": [
            "c537ed49532f0a41019136f4470e24df1abc28e2",
            "57778eb5bff2231a53d6ccbc8dc6e386c47b1f11",
        ],
    },
}


class EvaluationScenarioEvidenceTests(unittest.TestCase):
    def test_source_backed_scenario_packets_are_closed_hash_bound_and_diagnostic(self):
        for scenario_id, expected in EXPECTED.items():
            with self.subTest(scenario_id=scenario_id):
                root = SCENARIO_ROOT / scenario_id
                events = [
                    json.loads(line)
                    for line in (root / "authored-events.jsonl").read_text().splitlines()
                    if line.strip()
                ]
                source_ledger = json.loads((root / "source-ledger.json").read_text())
                relation_ledger = json.loads(
                    (root / "relation-label-ledger.json").read_text()
                )
                provenance = json.loads((root / "provenance.json").read_text())
                leakage = json.loads((root / "leakage-review.json").read_text())

                self.assertEqual(len(events), 4)
                self.assertEqual(
                    {tuple(event) for event in events},
                    {
                        (
                            "source_ref",
                            "observed_at",
                            "actor",
                            "kind",
                            "summary",
                            "model_visible",
                            "authored_summary",
                        )
                    },
                )
                self.assertTrue(all(event["authored_summary"] for event in events))
                self.assertTrue(all(event["model_visible"] for event in events))
                self.assertTrue(all(event["actor"] == "user" for event in events))
                self.assertTrue(all(event["kind"] == "message" for event in events))
                self.assertIn("handoff task", events[-1]["summary"].lower())
                self.assertNotIn("lifecycle_role", canonical_json(events))
                self.assertTrue(all(len(event["summary"].split()) <= 55 for event in events))

                self.assertEqual(
                    [], list(definition_validator("sourceLedger").iter_errors(source_ledger))
                )
                self.assertEqual(source_ledger["scenario_slot"], scenario_id)
                self.assertEqual(
                    [entry["source_ref"] for entry in source_ledger["entries"]],
                    [event["source_ref"] for event in events],
                )
                for event, entry in zip(events, source_ledger["entries"]):
                    self.assertEqual(
                        entry["event_sha256"],
                        hashlib.sha256(
                            canonical_json(event).encode("utf-8")
                        ).hexdigest(),
                    )
                    self.assertEqual(entry["model_visible"], event["model_visible"])

                self.assertEqual(
                    [],
                    list(
                        definition_validator("relationLabelLedger").iter_errors(
                            relation_ledger
                        )
                    ),
                )
                self.assertEqual(
                    relation_ledger["source_ledger_sha256"],
                    hashlib.sha256(
                        canonical_json(source_ledger).encode("utf-8")
                    ).hexdigest(),
                )
                self.assertEqual(
                    [entry["relation_kind"] for entry in relation_ledger["entries"]],
                    ["true_supersession", "hard_negative"],
                )

                self.assertEqual(provenance["record_type"], "scenario_provenance")
                self.assertEqual(provenance["scenario_slot"], scenario_id)
                self.assertEqual(
                    provenance["evidence_class"], "source_backed_synthetic"
                )
                self.assertFalse(provenance["production_trace"])
                self.assertFalse(provenance["copied_source_text"])
                self.assertTrue(provenance["authored_summaries"])
                self.assertEqual(provenance["license_id"], expected["license_id"])
                self.assertEqual(
                    provenance["license_status"],
                    "verified_from_repository_license",
                )
                self.assertEqual(
                    provenance["repository_url"], expected["repository_url"]
                )
                self.assertEqual(provenance["commit_refs"], expected["commit_refs"])
                self.assertTrue(
                    all(
                        re.fullmatch(r"[a-f0-9]{40}", commit_ref)
                        for commit_ref in provenance["commit_refs"]
                    )
                )
                self.assertNotIn("/main/", canonical_json(provenance["source_urls"]))
                self.assertTrue(
                    all(
                        any(commit_ref in url for url in provenance["source_urls"])
                        for commit_ref in provenance["commit_refs"]
                    )
                )
                limitations = " ".join(provenance["limitations"]).lower()
                self.assertIn("policy transition", limitations)
                self.assertIn("authored evaluation", limitations)
                self.assertEqual(
                    provenance["review_status"],
                    "pending_independent_evidence_review",
                )
                self.assertTrue(all(url.startswith("https://github.com/") for url in provenance["source_urls"]))

                self.assertEqual(leakage["record_type"], "leakage_review")
                self.assertEqual(leakage["scenario_slot"], scenario_id)
                self.assertEqual(
                    leakage["review_status"], "pending_independent_evidence_review"
                )
                self.assertEqual(
                    leakage["verdict"], "diagnostic_only_until_external_review"
                )
                self.assertFalse(leakage["checks"]["copied_source_text"])
                self.assertFalse(leakage["checks"]["hidden_test_text_model_visible"])
                self.assertFalse(leakage["checks"]["gold_source_ids_model_visible"])
                self.assertFalse(leakage["checks"]["relation_labels_model_visible"])
                leakage_limits = " ".join(leakage["limitations"]).lower()
                self.assertIn("not a production trace", leakage_limits)
                self.assertIn("desired policy behavior is model-visible", leakage_limits)
                self.assertIn("ineligible for headline", leakage_limits)


if __name__ == "__main__":
    unittest.main()
