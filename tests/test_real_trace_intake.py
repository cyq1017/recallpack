import json
import tempfile
import unittest
from pathlib import Path

from recallpack.trace_intake import (
    sanitize_trace_payload,
    validate_trace_file,
    validate_trace_payload,
)


ROOT = Path(__file__).resolve().parents[1]


class RealTraceIntakeTests(unittest.TestCase):
    def test_sample_consent_trace_is_internal_review_only(self):
        trace_path = ROOT / "fixtures" / "trace-intake" / "sample-consent-trace.json"

        report = validate_trace_file(trace_path)

        self.assertEqual(report["status"], "accepted_for_internal_review")
        self.assertFalse(report["promoted_to_submission_evidence"])
        self.assertEqual(report["consent"]["status"], "consented")
        self.assertEqual(report["event_count"], 6)
        self.assertEqual(report["privacy"]["secret_hits"], [])
        self.assertEqual(report["privacy"]["local_path_hits"], [])
        self.assertIn("not_submission_evidence", report["evidence_boundary"])

    def test_trace_intake_blocks_missing_consent_and_private_text(self):
        payload = {
            "trace_id": "bad-trace",
            "project_id": "private-project",
            "promoted_to_submission_evidence": False,
            "events": [
                {
                    "session_id": "s1",
                    "sequence_no": 1,
                    "actor": "user",
                    "text": (
                        "Use "
                        + "sk-"
                        + "12345678901234567890 from /"
                        + "Users/example/.env"
                    ),
                    "observed_at": "2026-07-08T09:00:00Z",
                }
            ],
        }

        report = validate_trace_payload(payload)

        self.assertEqual(report["status"], "blocked")
        self.assertIn("missing_consent", report["blockers"])
        self.assertIn("secret_like_value", report["blockers"])
        self.assertIn("local_path", report["blockers"])

    def test_sanitizer_redacts_secret_like_values_and_local_paths(self):
        payload = {
            "trace_id": "raw-trace",
            "project_id": "project-real-candidate",
            "source_kind": "raw_consent_trace",
            "promoted_to_submission_evidence": False,
            "consent": {
                "status": "consented",
                "scope": "sanitized_recallpack_trace_review",
                "allows_public_release": False,
                "participant_label": "developer-a",
            },
            "events": [
                {
                    "session_id": "s1",
                    "sequence_no": 1,
                    "actor": "user",
                    "text": (
                        "The local env at /"
                        + "Users/example/private/.env contains "
                        + "sk-"
                        + "12345678901234567890 but the retry policy changed."
                    ),
                    "observed_at": "2026-07-08T09:00:00Z",
                }
            ],
        }

        sanitized = sanitize_trace_payload(payload)
        serialized = json.dumps(sanitized, sort_keys=True)
        report = validate_trace_payload(sanitized)

        self.assertEqual("sanitized_trace_candidate", sanitized["source_kind"])
        self.assertNotIn("12345678901234567890", serialized)
        self.assertNotIn("/" + "Users/example", serialized)
        self.assertIn("[redacted-secret]", serialized)
        self.assertIn("[redacted-local-path]", serialized)
        self.assertEqual("accepted_for_internal_review", report["status"])
        self.assertEqual([], report["privacy"]["secret_hits"])
        self.assertEqual([], report["privacy"]["local_path_hits"])

    def test_trace_intake_requires_ordered_unique_events(self):
        payload = {
            "trace_id": "ordering-trace",
            "project_id": "project-real-candidate",
            "promoted_to_submission_evidence": False,
            "consent": {
                "status": "consented",
                "scope": "sanitized_recallpack_trace_review",
                "allows_public_release": False,
                "participant_label": "developer-a",
            },
            "events": [
                {
                    "session_id": "s1",
                    "sequence_no": 1,
                    "actor": "user",
                    "text": "Initial provider auth policy is Authorization.",
                    "observed_at": "2026-07-08T09:00:00Z",
                },
                {
                    "session_id": "s1",
                    "sequence_no": 1,
                    "actor": "assistant",
                    "text": "Duplicate sequence should be rejected.",
                    "observed_at": "2026-07-08T09:01:00Z",
                },
                {
                    "session_id": "s1",
                    "sequence_no": 3,
                    "actor": "user",
                    "text": "Missing sequence two should be rejected.",
                    "observed_at": "2026-07-08T09:02:00Z",
                },
            ],
        }

        report = validate_trace_payload(payload)

        self.assertEqual(report["status"], "blocked")
        self.assertIn("duplicate_sequence", report["blockers"])
        self.assertIn("non_contiguous_sequence", report["blockers"])

    def test_trace_intake_tool_outputs_review_safe_json(self):
        valid_trace = ROOT / "fixtures" / "trace-intake" / "sample-consent-trace.json"
        with tempfile.TemporaryDirectory() as temp_dir:
            report_path = Path(temp_dir) / "report.json"
            import subprocess
            import sys

            result = subprocess.run(
                [
                    sys.executable,
                    "tools/validate_real_trace_intake.py",
                    "--trace",
                    str(valid_trace),
                    "--json-out",
                    str(report_path),
                ],
                cwd=ROOT,
                check=True,
                capture_output=True,
                text=True,
            )

            self.assertIn("status=accepted_for_internal_review", result.stdout)
            report = json.loads(report_path.read_text())
            self.assertFalse(report["promoted_to_submission_evidence"])
            self.assertEqual(report["privacy"]["secret_hits"], [])

    def test_trace_intake_tool_can_write_sanitized_trace_before_validation(self):
        raw_trace = {
            "trace_id": "raw-cli-trace",
            "project_id": "project-real-candidate",
            "source_kind": "raw_consent_trace",
            "promoted_to_submission_evidence": False,
            "consent": {
                "status": "consented",
                "scope": "sanitized_recallpack_trace_review",
                "allows_public_release": False,
                "participant_label": "developer-a",
            },
            "events": [
                {
                    "session_id": "s1",
                    "sequence_no": 1,
                    "actor": "user",
                    "text": (
                        "Read /"
                        + "Users/example/private/config and remove "
                        + "sk-"
                        + "12345678901234567890 from the trace."
                    ),
                    "observed_at": "2026-07-08T09:00:00Z",
                }
            ],
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            raw_path = temp_root / "raw.json"
            sanitized_path = temp_root / "sanitized.json"
            report_path = temp_root / "report.json"
            raw_path.write_text(json.dumps(raw_trace))

            import subprocess
            import sys

            result = subprocess.run(
                [
                    sys.executable,
                    "tools/validate_real_trace_intake.py",
                    "--trace",
                    str(raw_path),
                    "--sanitize",
                    "--sanitized-out",
                    str(sanitized_path),
                    "--json-out",
                    str(report_path),
                ],
                cwd=ROOT,
                check=True,
                capture_output=True,
                text=True,
            )

            sanitized_text = sanitized_path.read_text()
            report = json.loads(report_path.read_text())
            self.assertIn("status=accepted_for_internal_review", result.stdout)
            self.assertNotIn("12345678901234567890", sanitized_text)
            self.assertNotIn("/" + "Users/example", sanitized_text)
            self.assertEqual("accepted_for_internal_review", report["status"])

    def test_real_trace_intake_plan_states_boundaries(self):
        plan_path = ROOT / "docs" / "research" / "real-trace-intake-plan.md"
        if plan_path.exists():
            plan = plan_path.read_text()
        else:
            plan = (
                (ROOT / "README.md").read_text()
                + "\n"
                + (ROOT / "docs" / "submission" / "review-packet.md").read_text()
            )

        self.assertIn("consent-first", plan)
        self.assertIn("not submission evidence until promoted", plan)
        if plan_path.exists():
            self.assertIn("must not contain credentials", plan)
            self.assertIn("source-backed fixture", plan)
        else:
            self.assertIn("not a production trace claim", plan)


if __name__ == "__main__":
    unittest.main()
