import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
import struct


ROOT = Path(__file__).resolve().parents[1]


def read_png_size(path):
    data = path.read_bytes()
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise AssertionError(f"{path} is not a PNG file")
    return struct.unpack(">II", data[16:24])


class SubmissionDocsTests(unittest.TestCase):
    def test_judge_facing_docs_do_not_use_stale_four_fixture_wording(self):
        stale_phrases = [
            "four downstream lifecycle fixtures",
            "four curated lifecycle fixtures",
            "four curated",
            "four fixtures are described",
            "four fixtures are useful",
            "four independent",
            "four structural copies",
            "four-fixture lifecycle",
            "four-fixture wording",
            "beyond four fixtures",
            "all four fixtures",
            "m23 four-fixture",
        ]
        paths = [
            ROOT / "README.md",
            ROOT / "docs" / "submission",
            ROOT / "docs" / "execution",
        ]
        offenders = []
        for path in paths:
            files = [path] if path.is_file() else sorted(path.rglob("*.md"))
            for file_path in files:
                text = file_path.read_text().lower()
                for phrase in stale_phrases:
                    if phrase in text:
                        offenders.append(f"{file_path.relative_to(ROOT)}: {phrase}")

        self.assertEqual([], offenders)

    def test_submission_checklist_marks_local_readiness_done_and_gates_unchecked(self):
        checklist = (ROOT / "docs" / "submission" / "submission-checklist.md").read_text()

        self.assertIn("- [x] `PYTHONPATH=src python3 tools/build_demo_data.py` rerun.", checklist)
        self.assertIn('bundle_target="dist/recallpack-submission-$(date +%Y%m%d-%H%M%S)"', checklist)
        self.assertIn('tools/build_submission_bundle.py --target "$bundle_target"', checklist)
        self.assertIn("Sanitized bundle scan reports zero local path", checklist)
        self.assertIn("MIT `LICENSE` is present.", checklist)
        self.assertIn("public-repo-readiness-report.md", checklist)
        self.assertIn("Local Docker build/run proof passed on `127.0.0.1`.", checklist)
        self.assertIn("- [x] `/api/demo` returns a 32-event micro-suite.", checklist)
        self.assertIn("- [x] `/compile` excludes stale `session-a:turn-001`.", checklist)
        self.assertIn(
            "Evaluate view records mixed adverse baseline outcomes: 1/3 where a stale patch is produced and 0/3 with `empty_patch` where strict validation rejects a no-op.",
            checklist,
        )
        self.assertIn("- [x] `docs/submission/review-packet.md`", checklist)
        self.assertIn("- [x] `docs/submission/devpost-final-copy.md`", checklist)
        self.assertIn("- [x] `docs/submission/demo-video-script.md`", checklist)
        self.assertIn("- [x] `docs/submission/demo-media-package.md`", checklist)
        self.assertIn("- [x] `docs/submission/architecture-diagram.md`", checklist)
        self.assertIn("- [x] `docs/submission/skeptical-judge-qa.md`", checklist)
        self.assertIn("- [x] `docs/submission/evidence-index.md`", checklist)
        self.assertIn("- [x] `docs/submission/devpost-materials.md`", checklist)
        self.assertIn("- [x] `docs/submission/public-release-gate.md`", checklist)
        self.assertIn("- [x] `LICENSE`", checklist)
        self.assertIn("- [x] `.gitignore`", checklist)
        self.assertIn("- [x] `docs/submission/local-readiness-report.md`", checklist)
        self.assertIn("- [x] `docs/submission/gated-action-approval-matrix.md`", checklist)
        self.assertIn("- [x] `docs/submission/gated-action-runbook.md`", checklist)
        self.assertIn("- [x] Fresh timestamped `dist/recallpack-submission-*/SUBMISSION_MANIFEST.md`", checklist)
        self.assertIn("- [x] One-time Live Qwen credential access", checklist)
        self.assertIn("- [x] One-time Live Qwen contract execution.", checklist)
        self.assertIn("- [ ] Any additional Live Qwen credential access", checklist)
        self.assertIn("- [x] One-time local Docker build/run proof.", checklist)
        self.assertIn("- [ ] Any further Docker run", checklist)
        self.assertIn("- [x] Approved ECS resource creation.", checklist)
        self.assertIn("- [x] Approved public endpoint exposure.", checklist)
        self.assertIn("- [ ] Hackathon submission.", checklist)

    def test_local_readiness_report_records_verification_and_remaining_gates(self):
        report = (ROOT / "docs" / "submission" / "local-readiness-report.md").read_text()
        runbook = (ROOT / "docs" / "submission" / "demo-runbook.md").read_text()

        self.assertIn("# RecallPack Local Readiness Report", report)
        self.assertIn(
            "Status: local package green; M45 first-run handoff simulator implemented",
            report,
        )
        self.assertIn("M62 external-review remediation complete", report)
        self.assertIn("focused M65 tests", report)
        self.assertIn("M15 first-screen narrative polish: complete", report)
        self.assertIn("M16 live Qwen contract trace: complete", report)
        self.assertIn("M17 public repository readiness: complete", report)
        self.assertIn("M18 local Docker runtime proof: complete", report)
        self.assertIn("M19 fair computed baselines: complete", report)
        self.assertIn("M20 fresh-clone rehearsal and public surface polish: complete", report)
        self.assertIn("M21 judge-grade quality hardening audit: complete", report)
        self.assertIn("M22 second independent fixture proof: complete", report)
        self.assertIn("M23/M77/M110/M113/M117 eight curated lifecycle fixtures: complete", report)
        self.assertIn("M24 judge smoke script and final bundle rehearsal: complete", report)
        self.assertIn("M25 skeptical judge Q&A: complete", report)
        self.assertIn("M26 HTTP observe endpoint and judge smoke write-path proof: complete", report)
        self.assertIn("M27 browser visual QA: complete", report)
        self.assertIn("M28 final-bundle Docker runtime proof: complete", report)
        self.assertIn("M29 fresh-clone rehearsal and latest-bundle Docker proof: complete", report)
        self.assertIn("M31 stronger judge smoke assertions and live-status hard gate: complete", report)
        self.assertIn("M32 full fresh-clone rehearsal mode: complete", report)
        self.assertIn("M33 compact health readiness endpoint: complete", report)
        self.assertIn("M35 fresh-clone public surface completeness gate: complete", report)
        self.assertIn("M36 static demo data parity gate: complete", report)
        self.assertIn("M37 shared HTTP runtime and cross-session sequence fix: complete", report)
        self.assertIn("Raw full-history reference: 12 events", report)
        self.assertIn("not budget-comparable", report)
        self.assertIn("Keyword-scored fake-embedding + rerank baseline", report)
        self.assertIn("not fixture-selected source IDs", report)
        self.assertIn(
            "First-screen story: keyword-scored fake-embedding + rerank raw-history handoff fails 1/3",
            report,
        )
        self.assertIn("RecallPack active memory handoff passes 3/3", report)
        self.assertIn(
            "First-screen retrieval path: deterministic keyword fake embedding top-N -> qwen3-rerank-shaped fake rerank -> estimated 512-token serialized-memory budget selector",
            report,
        )
        self.assertIn("behavior-contract fixture evaluator", report)
        self.assertIn("fixture prediction fields are ignored", report)
        self.assertIn("Keyword-scored fake-embedding baseline source-recall score: 0/3", report)
        self.assertIn("Downstream computed embedding baseline fixture tests: 1/3", report)
        self.assertIn("Downstream RecallPack fixture tests: 3/3", report)
        self.assertIn("Project-b config loader baseline fixture tests: 1/3", report)
        self.assertIn("Project-b config loader RecallPack fixture tests: 3/3", report)
        self.assertIn("Project-c cache policy baseline fixture tests: 0/3", report)
        self.assertIn("Project-c baseline rejection: `empty_patch`", report)
        self.assertIn("Project-c cache policy RecallPack fixture tests: 3/3", report)
        self.assertIn("Project-d audit serializer baseline fixture tests: 0/3", report)
        self.assertIn("Project-d baseline rejection: `empty_patch`", report)
        self.assertIn("Project-d audit serializer RecallPack fixture tests: 3/3", report)
        self.assertIn("Project-e pagination baseline fixture tests: 0/3", report)
        self.assertIn("Project-e baseline rejection: `empty_patch`", report)
        self.assertIn("Project-e pagination RecallPack fixture tests: 3/3", report)
        self.assertIn("Downstream proof mode: temp repo patch plus fixture tests", report)
        self.assertIn("Qwen provider integration trace: live-provider schema present", report)
        self.assertIn("Live Qwen trace: `live_contract_passed`", report)
        self.assertIn("Actual Qwen token usage: memory=301 embedding=20 rerank=29", report)
        self.assertIn("memory_decision, embedding, and rerank traces", report)
        self.assertIn("M73 live Qwen trace explorer: complete", report)
        self.assertIn("role_summary", report)
        self.assertIn("sanitized trace only", report)
        self.assertIn("/compile retrieval path: embedding top-N + rerank", report)
        self.assertIn("Fake rerank receives fake-embedding top-N candidates before budget selection", report)
        self.assertIn("Sanitized submission bundle build: passed.", report)
        self.assertIn("Post-M25 fresh bundle rebuild: passed.", report)
        self.assertRegex(report, r"dist/recallpack-submission-[0-9]{8}-[0-9]{6}")
        self.assertIn("M83 latest verification label cleanup: complete", report)
        self.assertIn("Latest M106 fresh-clone smoke passed", report)
        self.assertIn("Latest M106 final submission gate passed", report)
        self.assertIn("Latest M106 public repo preflight passed", report)
        self.assertNotIn("Latest M48 full fresh-clone rehearsal passed", report)
        self.assertNotIn("dist/recallpack-submission-20260626-212300", report)
        self.assertIn("SUBMISSION_MANIFEST.md` includes judge quick checks", report)
        self.assertIn("M34 judge quick check manifest: complete", report)
        self.assertIn("Fresh-clone public surface gate checks required public files", report)
        self.assertIn("Static demo parity gate compares `web/demo-data.js`", report)
        self.assertIn("M72 current screenshot gallery: complete", report)
        self.assertIn("docs/submission/media/m71-replay", report)
        self.assertIn("older M55 root-level PNGs are", report)
        self.assertIn("M78 submission wording consistency gate: complete", report)
        self.assertIn("M79 README verification command sync: complete", report)
        self.assertIn("M80 current release-candidate wording sync: complete", report)
        self.assertIn("M81 bundle self-reference consistency gate: complete", report)
        self.assertIn("M82 current evidence snapshot refresh: complete", report)
        self.assertIn("M85 deadline runway plan: complete", report)
        self.assertIn("Unit test suite: 212 tests passed in M121 verification.", report)
        self.assertIn("Sanitized submission bundle scan: zero local path", report)
        self.assertIn("Public repository boundary: publish the sanitized bundle contents", report)
        self.assertIn("License: MIT `LICENSE` present.", report)
        self.assertIn("Last completed local Docker runtime proof: passed", report)
        self.assertIn("Last completed Docker image: `recallpack-demo:cloud`", report)
        self.assertIn("Last completed Docker container binding: `127.0.0.1:8817->8789`", report)
        self.assertIn("Docker daemon blocker: resolved by starting Docker Desktop", report)
        self.assertIn("Judge smoke verifies standalone `live_contract_passed`", report)
        self.assertIn("live_qwen_e2e_status=live_e2e_passed", report)
        self.assertIn("GET /api/health returns compact readiness", report)
        self.assertIn("POST /observe wrote auth decision memory", report)
        self.assertIn("Shared-store regression proof", report)
        self.assertIn("runtime_store=shared_sqlite", report)
        self.assertIn("POST /compile selected active retry memory", report)
        self.assertIn("Remaining gated actions", report)
        self.assertIn("P0 gaps remaining for prize-grade credibility", report)
        self.assertIn("provider-backed fake memory decision path", report)
        self.assertIn("M39 conservative public evidence wording: complete", report)
        self.assertIn("M40 Qwen memory decision tool-calling contract: complete", report)
        self.assertIn("M41 deterministic keyword fake /compile providers: complete", report)
        self.assertIn("M43 live Qwen E2E runner: implemented and gated", report)
        self.assertIn("M47 live memory-decision contract hardening: complete", report)
        self.assertIn("M48 credential-free live E2E preflight: complete", report)
        self.assertIn("M45 first-run handoff simulator: complete", report)
        self.assertIn("First-run handoff simulator shows baseline 1/3 and RecallPack 3/3", report)
        self.assertIn("M71 one-click stale-memory failure replay: complete", report)
        self.assertIn("one-click stale-memory failure replay", report)
        self.assertIn("live Qwen E2E attempted once with approval", report)
        self.assertIn("stored status `live_e2e_passed`", report)
        self.assertIn("selected_sources=`session-a:turn-005, session-a:turn-004, session-a:turn-003`", report)
        self.assertIn("structured event metadata", report)
        self.assertIn("descriptive tool schema", report)
        self.assertIn("preflight_status `ready_for_live_e2e_rerun`", report)
        self.assertIn("network_calls_made=false", report)
        self.assertIn("local HTTP /compile uses deterministic keyword fake embedding/rerank", report)
        self.assertIn("fake rule path", report)
        self.assertIn("Fresh-clone rehearsal copied the sanitized bundle into a temp directory", report)
        self.assertIn("Fresh-clone full mode runs full public-test discovery", report)
        self.assertIn("custody-bound frozen-executor suite skip explicitly", report)
        self.assertIn("M30 public repo root self-smoke: complete", report)
        self.assertIn("P2 gaps: final submission", report)
        self.assertIn("latest public repo", report)
        self.assertIn("ECS redeploy after M121", report)
        self.assertIn("final video recording/upload", report)
        self.assertIn("final media order confirmation", report)
        self.assertIn("Approved public Alibaba Cloud ECS deployment", report)
        self.assertIn("gated-action-approval-matrix.md", report)
        self.assertIn("gated-action-runbook.md", report)
        self.assertIn("tests/test_submission_docs.py", runbook)
        self.assertIn("skeptical-judge-qa.md", runbook)
        self.assertIn("Open the first screen on Learn and start with the Evidence Boundary", runbook)
        self.assertIn("Then use the one-click stale-memory failure replay", runbook)
        self.assertIn("wrong retry patch -> active memory", runbook)
        self.assertIn("baseline fixture tests 1/3", runbook)
        self.assertIn("Show the First-Run Handoff Simulator as the compact summary", runbook)
        self.assertIn("baseline retrieves stale raw history", runbook)
        self.assertIn("keyword-scored fake-embedding + rerank raw-history baseline: fixture tests 1/3", runbook)
        self.assertIn("raw full-history reference", runbook)
        self.assertIn("RecallPack active memory: fixture tests 3/3", runbook)
        self.assertIn("eight curated lifecycle fixtures", runbook)
        self.assertIn("live_contract_passed", runbook)
        self.assertIn("live-provider contract with", runbook)
        self.assertIn("tools/run_live_qwen_e2e.py", runbook)
        self.assertIn("RECALLPACK_LIVE_QWEN_E2E_APPROVED=1", runbook)
        self.assertIn("tests/test_submission_bundle.py", runbook)
        self.assertIn('bundle_target="dist/recallpack-submission-$(date +%Y%m%d-%H%M%S)"', runbook)
        self.assertIn('tools/build_submission_bundle.py --target "$bundle_target"', runbook)
        self.assertIn("python3 tools/judge_smoke.py --url http://127.0.0.1:8789", runbook)
        self.assertIn("curl http://127.0.0.1:8789/api/health", runbook)
        self.assertIn("Judge smoke script: passed against the local demo server", report)

    def test_m114_real_trace_intake_is_recorded_without_overclaiming(self):
        readme = (ROOT / "README.md").read_text()
        report = (ROOT / "docs" / "submission" / "local-readiness-report.md").read_text()
        packet = (ROOT / "docs" / "submission" / "review-packet.md").read_text()
        handoff_path = ROOT / "docs" / "execution" / "HANDOFF.md"
        plan_path = ROOT / "docs" / "research" / "real-trace-intake-plan.md"

        self.assertIn("consent-first real trace intake kit", readme)
        self.assertIn("not submission evidence until promoted", readme)
        self.assertIn("--sanitize", readme)
        self.assertIn("M114 consent-first real trace intake: complete", report)
        self.assertIn("consent-first real trace intake kit", packet)
        self.assertIn("not a production trace claim", packet)
        if handoff_path.exists():
            self.assertIn("M114", handoff_path.read_text())
        if plan_path.exists():
            self.assertIn("accepted_for_internal_review", plan_path.read_text())
        else:
            self.assertTrue((ROOT / "fixtures" / "trace-intake" / "sample-consent-trace.json").is_file())

    def test_public_repo_readiness_report_and_readme_are_judge_ready(self):
        readme = (ROOT / "README.md").read_text()
        license_text = (ROOT / "LICENSE").read_text()
        report = (ROOT / "docs" / "submission" / "public-repo-readiness-report.md").read_text()
        gitignore = (ROOT / ".gitignore").read_text()

        self.assertIn("MIT License", license_text)
        self.assertIn("Fresh Clone Quickstart", readme)
        self.assertIn("Start Here For Judges", readme)
        self.assertIn("Run this first", readme)
        self.assertIn("deterministic, fixture-backed demonstration", readme)
        self.assertIn("first-run handoff simulator", readme)
        self.assertIn("deterministic keyword fake embedding/rerank", readme)
        self.assertIn("not zero-vector or identity-rerank smoke", readme)
        self.assertIn("Qwen Cloud adapters", readme)
        self.assertIn("OpenAI-compatible tool-calling request", readme)
        self.assertIn("qwen3.7-plus-2026-05-26", readme)
        self.assertIn("sanitized standalone live API contract trace", readme)
        self.assertIn("gated live Qwen E2E runner", readme)
        self.assertIn("memory-decision contract hardening", readme)
        self.assertIn("credential-free live E2E preflight", readme)
        self.assertIn("tools/build_live_qwen_e2e_preflight.py", readme)
        self.assertIn("RECALLPACK_LIVE_QWEN_E2E_APPROVED=1", readme)
        self.assertIn("does not require Qwen credentials", readme)
        self.assertIn("Skeptical judge Q&A", readme)
        self.assertIn("docs/submission/skeptical-judge-qa.md", readme)
        self.assertIn("Curated deterministic baseline comparison", readme)
        self.assertIn("raw full-history reference", readme)
        self.assertIn("keyword-scored fake-embedding + rerank raw-history baseline", readme)
        self.assertNotIn("Qwen Cloud is load-bearing", readme)
        self.assertIn("recallpack-demo:local", readme)
        self.assertIn("python3 -m py_compile", readme)
        verification_files = [
            "tests/test_qwen_live_embedding_baseline.py",
            "tools/build_live_qwen_embedding_baseline_preflight.py",
            "tools/run_live_qwen_embedding_baseline.py",
            "tools/video_rehearsal_gate.py",
        ]
        verification_docs = [
            ROOT / "README.md",
            ROOT / "docs" / "submission" / "demo-runbook.md",
            ROOT / "docs" / "submission" / "gated-action-runbook.md",
            ROOT / "docs" / "submission" / "public-release-gate.md",
            ROOT / "docs" / "submission" / "public-repo-readiness-report.md",
        ]
        for verification_doc in verification_docs:
            text = verification_doc.read_text()
            for verification_file in verification_files:
                self.assertIn(verification_file, text)
        self.assertIn("PYTHONPATH=src python3 -m unittest discover -s tests -v", readme)
        self.assertIn("node --check web/app.js", readme)
        self.assertIn("PYTHONPATH=src python3 tools/fresh_clone_smoke.py --source .", readme)
        self.assertIn("PYTHONPATH=src python3 tools/fresh_clone_smoke.py --source . --full", readme)
        self.assertIn("python3 tools/judge_smoke.py --url http://127.0.0.1:8789", readme)
        self.assertIn("curl http://127.0.0.1:8789/api/health", readme)
        self.assertIn("tools/fresh_clone_smoke.py", readme)
        self.assertIn("curl -X POST http://127.0.0.1:8789/observe", readme)
        self.assertIn(
            "Public repo readiness status: latest sanitized bundle is ready for public repo sync",
            report,
        )
        self.assertIn("Date: 2026-07-09", report)
        self.assertNotIn("Date: 2026-06-29", report)
        self.assertIn("License status: MIT License present", report)
        self.assertIn("Do not push the raw workspace as the judging repository", report)
        self.assertIn("docs/execution/", report)
        self.assertIn("AGENTS.md", report)
        self.assertIn("dist/", report)
        self.assertIn("Safe to publish", report)
        self.assertIn("Files to exclude", report)
        self.assertIn("skeptical-judge-qa.md", report)
        self.assertIn("Judge smoke commands", report)
        self.assertIn(
            "M104 Docker proof: passed from the prior verified public ECS bundle",
            report,
        )
        self.assertIn("Full fresh-clone rehearsal command", report)
        self.assertIn("M35 public surface completeness gate: passed", report)
        self.assertIn("required judge-facing files are missing", report)
        self.assertIn("M36 static demo parity gate: passed", report)
        self.assertIn("rejects stale `web/demo-data.js`", report)
        self.assertIn("tools/fresh_clone_smoke.py --source . --full", report)
        self.assertIn("M29 fresh-clone rehearsal: passed", report)
        self.assertIn("M30 public repo root self-smoke: passed", report)
        self.assertIn("Latest M121 final submission gate: passed", report)
        self.assertIn("Latest M121 public repo preflight: passed", report)
        self.assertNotIn("Latest M60 final submission gate", report)
        self.assertNotIn("Latest M61 public repo preflight", report)
        self.assertIn("PYTHONPATH=src python3 tools/fresh_clone_smoke.py --source .", report)
        self.assertIn("POST /observe writes an auth decision memory", report)
        self.assertIn("compile proof is seeded through HTTP observe events", report)
        self.assertIn("GET /api/health exposes compact readiness", report)
        self.assertIn("No Qwen credentials are required for local tests", report)
        self.assertIn(".env", gitignore)
        self.assertIn("*.sqlite3", gitignore)

    def test_hackathon_fields_are_ready_to_copy(self):
        fields = (ROOT / "docs" / "submission" / "hackathon-fields.md").read_text()
        devpost = (ROOT / "docs" / "submission" / "devpost-final-copy.md").read_text()

        self.assertIn("# RecallPack Hackathon Fields", fields)
        self.assertIn("Project name: RecallPack", fields)
        self.assertIn("Track: MemoryAgent", fields)
        self.assertIn("Tagline:", fields)
        self.assertIn("text-embedding-v4", fields)
        self.assertIn("qwen3-rerank", fields)
        self.assertIn("Qwen text model", fields)
        self.assertIn("tools/tool_choice", fields)
        self.assertIn("qwen3.7-plus-2026-05-26", fields)
        self.assertIn("standalone live API smoke passed", fields)
        self.assertIn("memory=301, embedding=20, rerank=29", fields)
        self.assertIn("PYTHONPATH=src python3 -m recallpack.demo_server", fields)
        self.assertIn("Credential-free Alibaba Cloud ECS runtime proof is running", fields)
        self.assertIn("http://101.133.224.223/", fields)
        self.assertIn("# RecallPack Devpost Final Copy", devpost)
        self.assertIn("Elevator Pitch", devpost)
        self.assertIn("Project Story", devpost)
        self.assertIn("Built With", devpost)
        self.assertIn("Video Demo Script", devpost)
        self.assertIn("Which AI tools", devpost)
        self.assertIn("MemoryAgent", devpost)
        self.assertIn("keyword-scored fake-embedding + rerank raw-history baseline", devpost)
        self.assertIn("standalone live API smoke passed", devpost)
        self.assertIn("patch-generation provider", devpost)
        self.assertIn("does not read gold patch variants", devpost)
        self.assertNotIn("open loops", devpost)
        self.assertIn("Credential-free Alibaba Cloud ECS runtime proof is running", devpost)
        self.assertIn("http://101.133.224.223/", devpost)

    def test_quality_hardening_audit_is_judge_grade_and_candid(self):
        audit_path = ROOT / "docs" / "submission" / "quality-hardening-audit.md"
        if not audit_path.exists():
            self.skipTest("internal quality-hardening audit is excluded from sanitized bundles")
        audit = audit_path.read_text()
        report = (ROOT / "docs" / "submission" / "local-readiness-report.md").read_text()
        review_packet = (ROOT / "docs" / "submission" / "review-packet.md").read_text()
        deployment = (ROOT / "docs" / "deployment" / "alibaba-cloud-proof.md").read_text()

        self.assertIn("# RecallPack M21 Quality Hardening Audit", audit)
        self.assertIn("Claim-To-Evidence Matrix", audit)
        self.assertIn("Evaluation Fairness Audit", audit)
        self.assertIn("Architecture Defensibility Audit", audit)
        self.assertIn("Demo Quality Audit", audit)
        self.assertIn("P0 gaps still remaining after M38", audit)
        self.assertIn("POST /observe` and `POST /compile` now share", audit)
        self.assertIn("P1 fixes applied", audit)
        self.assertIn("P2 remaining credibility risks", audit)
        self.assertIn("Next evidence recommendation: add broader external", audit)
        self.assertIn("M22 update: second independent project fixture added", audit)
        self.assertIn("M23 update: project-c cache policy and project-d audit serializer", audit)
        self.assertIn("eight-fixture local proof", audit)
        self.assertIn("project-b config loader", audit)
        self.assertIn("project-c cache", audit)
        self.assertIn("project-d audit serializer", audit)
        self.assertIn(
            "project-c, project-d, and project-e baselines are rejected as `empty_patch` and score 0/3",
            audit,
        )
        self.assertIn("not a broad benchmark", audit)
        self.assertIn("sanitized trace evidence", audit)
        self.assertIn("M21 judge-grade quality hardening audit: complete", report)
        self.assertIn("Quality hardening audit", review_packet)
        self.assertIn("Eight curated lifecycle fixtures", review_packet)
        self.assertIn("Skeptical judge Q&A", review_packet)
        self.assertIn("project-b config", review_packet)
        self.assertIn("project-c cache", review_packet)
        self.assertIn("project-d serializer", review_packet)
        self.assertIn("project-e pagination", review_packet)
        self.assertIn(
            "Recall view compares raw full-history reference, keyword-scored fake-embedding + rerank raw-history baseline, and RecallPack.",
            review_packet,
        )
        self.assertIn("M72 current screenshot gallery", review_packet)
        self.assertIn("docs/submission/media/m71-replay", review_packet)
        banned_two_way_claim = "Recall view compares raw-history RAG with " + "RecallPack."
        banned_deployment_phrase = "compare raw-history RAG with " + "RecallPack"
        self.assertNotIn(banned_two_way_claim, review_packet)
        self.assertNotIn(banned_deployment_phrase, deployment)

    def test_gated_action_docs_are_approval_ready(self):
        matrix = (ROOT / "docs" / "submission" / "gated-action-approval-matrix.md").read_text()
        runbook = (ROOT / "docs" / "submission" / "gated-action-runbook.md").read_text()
        dockerfile = (ROOT / "deploy" / "alibaba-cloud" / "Dockerfile").read_text()

        self.assertIn("# RecallPack Gated Action Approval Matrix", matrix)
        self.assertIn("Live Qwen contract", matrix)
        self.assertIn("Docker build/run proof", matrix)
        self.assertIn("Alibaba Cloud ECS deployment", matrix)
        self.assertIn("Hackathon submission", matrix)
        self.assertIn("explicit approval required", matrix)
        self.assertIn("completed once; blocked for rerun", matrix)
        self.assertIn("No credentials are stored in repo files.", matrix)
        self.assertIn("completed locally and on ECS; blocked for scope change", matrix)
        self.assertIn(
            "completed; latest M104 redeploy passed; blocked for replacement or scale change",
            matrix,
        )
        self.assertIn("completed once at `http://101.133.224.223/`", matrix)
        self.assertIn("One approved local Docker image was built and run", matrix)
        self.assertIn("One approved ECS Docker container is running", matrix)

        self.assertIn("# RecallPack Gated Action Runbook", runbook)
        self.assertIn("RECALLPACK_ENABLE_LIVE_QWEN=1", runbook)
        self.assertIn("tools/run_live_qwen_contract.py", runbook)
        self.assertIn("docker build -f deploy/alibaba-cloud/Dockerfile", runbook)
        self.assertIn("deployment_replicas = 1", runbook)
        self.assertIn("application_workers = 1", runbook)
        self.assertIn("rollback", runbook)
        self.assertIn("Stop before", runbook)

        self.assertIn("EXPOSE 8789", dockerfile)
        self.assertIn("recallpack.demo_server", dockerfile)
        self.assertIn("COPY docs/submission /app/docs/submission", dockerfile)

    def test_skeptical_judge_qa_maps_claims_to_evidence(self):
        qa = (ROOT / "docs" / "submission" / "skeptical-judge-qa.md").read_text()

        self.assertIn("# RecallPack Skeptical Judge Q&A", qa)
        self.assertIn("Qwen Provider Integration Evidence", qa)
        self.assertIn("tools/tool_choice", qa)
        self.assertIn("qwen3.7-plus-2026-05-26", qa)
        self.assertIn("text-embedding-v4", qa)
        self.assertIn("qwen3-rerank", qa)
        self.assertIn("live_contract_passed", qa)
        self.assertIn("keyword-scored fake-embedding + rerank", qa)
        self.assertIn("not source-picked", qa)
        self.assertIn("fixture-authored scoring terms", qa)
        self.assertIn("baseline_embedding_terms", qa)
        self.assertIn("baseline_downrank_phrases", qa)
        self.assertIn("gold-oracle HeroFixtureDecider", qa)
        self.assertIn("gold-echoing micro-suite behavior-contract decider", qa)
        self.assertIn("eight local fixtures", qa)
        self.assertIn("not a broad benchmark", qa)
        self.assertIn("temp repo fixture tests", qa)
        self.assertIn("/observe concurrency boundary", qa)
        self.assertIn("single worker", qa)
        self.assertIn("docs/submission/live-qwen-trace.json", qa)
        self.assertIn("tests/test_judge_smoke.py", qa)

    def test_public_ui_uses_conservative_evidence_labels(self):
        app_js = (ROOT / "web" / "app.js").read_text()

        self.assertIn("MemoryAgent fixture demo", app_js)
        self.assertIn("First-Run Handoff Simulator", app_js)
        self.assertIn("local replay stale raw history", app_js)
        self.assertIn("active memory lifecycle pack", app_js)
        self.assertIn("Curated Lifecycle Fixtures", app_js)
        self.assertIn("generalization.fixture_count", app_js)
        self.assertNotIn("Four Curated Lifecycle Fixtures", app_js)
        self.assertIn("Qwen Provider Integration Evidence", app_js)
        self.assertIn("standalone live API smoke", app_js)
        self.assertNotIn("Qwen Load-Bearing", app_js)
        self.assertNotIn("Multi-Fixture Lifecycle Benchmark", app_js)

    def test_public_ui_exposes_one_click_handoff_replay_hooks(self):
        app_js = (ROOT / "web" / "app.js").read_text()
        styles = (ROOT / "web" / "styles.css").read_text()

        self.assertIn("renderHandoffReplay", app_js)
        self.assertIn("handoff_replay", app_js)
        self.assertIn("Replay handoff", app_js)
        self.assertIn("data-replay-step", app_js)
        self.assertIn("setActiveReplayStep", app_js)
        self.assertIn("wrong retry patch", app_js)
        self.assertIn("active memory pack", app_js)
        self.assertIn(".handoff-replay", styles)
        self.assertIn(".replay-controls", styles)
        self.assertIn(".replay-step[aria-selected=\"true\"]", styles)

    def test_public_ui_exposes_live_qwen_trace_explorer_hooks(self):
        app_js = (ROOT / "web" / "app.js").read_text()
        styles = (ROOT / "web" / "styles.css").read_text()

        self.assertIn("renderQwenTraceExplorer", app_js)
        self.assertIn("trace_explorer", app_js)
        self.assertIn("explorer.role_summary || []", app_js)
        self.assertIn("explorer.safety_boundary || {}", app_js)
        self.assertIn("Stored Live Qwen Trace", app_js)
        self.assertIn("checked-in file, no live call", app_js)
        self.assertIn("sanitized trace only", app_js)
        self.assertIn("local demo makes no live Qwen calls", app_js)
        self.assertIn("downstream patch generation", app_js)
        self.assertIn("local deterministic context-keyed patch provider", app_js)
        self.assertIn(".trace-explorer", styles)
        self.assertIn(".trace-stage-grid", styles)

    def test_m74_external_review_remediation_is_recorded(self):
        report = (ROOT / "docs" / "submission" / "local-readiness-report.md").read_text()
        packet = (ROOT / "docs" / "submission" / "review-packet.md").read_text()
        root_manifest = ROOT / "SUBMISSION_MANIFEST.md"
        manifest = (
            root_manifest
            if root_manifest.exists()
            else ROOT / "dist" / "recallpack-submission-20260704-001615" / "SUBMISSION_MANIFEST.md"
        ).read_text()

        self.assertIn("M74 external-review remediation: complete", report)
        self.assertIn("deterministic context-keyed patch provider", report)
        self.assertIn("keyword-scored fake-embedding baseline", report)
        self.assertIn("behavior contract fixture suite", report)
        self.assertIn("stored sanitized one-run trace", report)
        self.assertIn("Stored Live Qwen Trace", packet)
        self.assertIn("local deterministic context-keyed patch provider", packet)
        self.assertIn("keyword-scored fake-embedding", packet)
        self.assertIn("behavior contract fixture suite", packet)
        self.assertIn("local Docker is the canonical credential-free demo surface", manifest)

    def test_public_ui_supports_direct_view_links_for_media_capture(self):
        app_js = (ROOT / "web" / "app.js").read_text()

        self.assertIn("initialViewFromUrl", app_js)
        self.assertIn("URLSearchParams", app_js)
        self.assertIn('searchParams.get("view")', app_js)
        self.assertIn("validViewIds.has(view)", app_js)
        self.assertIn('searchParams.set("view", viewId)', app_js)
        self.assertIn("scrollToRequestedSection", app_js)
        self.assertIn("qwen-provider-evidence", app_js)

    def test_docker_runtime_proof_is_recorded(self):
        dockerfile = (ROOT / "deploy" / "alibaba-cloud" / "Dockerfile").read_text()
        self.assertIn("COPY requirements-v4.txt", dockerfile)
        self.assertIn("pip install --no-cache-dir -r requirements-v4.txt", dockerfile)
        cache_env = "ENV TIKTOKEN_CACHE_DIR=/app/.cache/tiktoken"
        cache_warmup = (
            'RUN python -c "import tiktoken; '
            "tiktoken.get_encoding('o200k_base')\""
        )
        self.assertIn(cache_env, dockerfile)
        self.assertIn(cache_warmup, dockerfile)
        self.assertLess(dockerfile.index(cache_env), dockerfile.index(cache_warmup))
        self.assertLess(
            dockerfile.index("pip install --no-cache-dir -r requirements-v4.txt"),
            dockerfile.index(cache_warmup),
        )
        self.assertIn(
            "COPY specs/001-recallpack-v4/contracts "
            "/app/specs/001-recallpack-v4/contracts",
            dockerfile,
        )
        readme = (ROOT / "README.md").read_text()
        deployment = (ROOT / "docs" / "deployment" / "alibaba-cloud-proof.md").read_text()
        readiness = (ROOT / "docs" / "submission" / "local-readiness-report.md").read_text()
        public_report = (
            ROOT / "docs" / "submission" / "public-repo-readiness-report.md"
        ).read_text()
        review_packet = (ROOT / "docs" / "submission" / "review-packet.md").read_text()

        self.assertIn("Docker Quickstart", readme)
        self.assertIn("127.0.0.1:8789:8789", readme)
        self.assertIn("M18 local Docker runtime proof: complete", readiness)
        self.assertIn("M28 final-bundle Docker runtime proof: complete", readiness)
        self.assertIn("Docker proof status: passed", deployment)
        self.assertIn("Build context: sanitized public bundle", deployment)
        self.assertIn("recallpack-demo:m104-20260704-123846", deployment)
        self.assertIn("ThreadingHTTPServer", deployment)
        self.assertIn("Docker daemon blocker resolved by starting Docker Desktop", deployment)
        self.assertIn("live_qwen_e2e_status=live_e2e_passed", deployment)
        self.assertIn("POST /observe -> writes memory through the HTTP observe path", deployment)
        self.assertIn("POST /compile -> includes session-a:turn-005", deployment)
        self.assertIn("excludes stale session-a:turn-001", deployment)
        self.assertIn("Docker proof: local 127.0.0.1 runtime passed", public_report)
        self.assertIn("M104 Docker proof: passed from the prior verified public ECS bundle", public_report)
        self.assertIn("hard-gates `live_contract_passed`", public_report)
        self.assertIn("first-screen", public_report)
        self.assertIn("Qwen provider roles", public_report)
        self.assertIn("Docker runtime proof: passed", review_packet)
        self.assertIn("Fresh-clone rehearsal: passed", review_packet)
        self.assertIn("recallpack-demo:cloud", review_packet)
        self.assertIn(
            "Current public ECS deployment: M104 credential-free runtime from the prior verified 7/4 sanitized bundle.",
            review_packet,
        )
        self.assertIn("python3 tools/judge_smoke.py --url http://127.0.0.1:8789", review_packet)

    def test_m50_external_benchmark_and_winner_polish_are_recorded(self):
        m50_path = ROOT / "docs" / "submission" / "m50-external-benchmark-winner-polish.md"
        if not m50_path.exists():
            self.skipTest("internal M50 inspiration doc is excluded from sanitized bundles")
        m50 = m50_path.read_text()
        script = (ROOT / "docs" / "submission" / "demo-video-script.md").read_text()
        readiness = (ROOT / "docs" / "submission" / "local-readiness-report.md").read_text()
        review_packet = (ROOT / "docs" / "submission" / "review-packet.md").read_text()
        handoff_path = ROOT / "docs" / "execution" / "HANDOFF.md"
        long_task_path = ROOT / "docs" / "execution" / "long-task-plan.md"

        self.assertIn("# RecallPack M50 External Benchmark And Winner Polish", m50)
        self.assertIn("Official Hackathon Signals", m50)
        self.assertIn("Innovation & AI Creativity 30%", m50)
        self.assertIn("Technical Depth & Engineering 30%", m50)
        self.assertIn("Problem Value & Impact 25%", m50)
        self.assertIn("Presentation & Documentation 15%", m50)
        self.assertIn("Devpost Discussions", m50)
        self.assertIn("Project gallery is not yet published", m50)
        self.assertIn("Qwen Cloud Discord", m50)
        self.assertIn("Reference Bank", m50)
        self.assertIn("Skills to consider", m50)
        self.assertIn("hackathon-demo-script", m50)
        self.assertIn("hackathon-submission-prep", m50)
        self.assertIn("demo-video", m50)
        self.assertIn("Do not install by default", m50)
        self.assertIn("Prior-art memory systems", m50)
        self.assertIn("mem0ai/mem0", m50)
        self.assertIn("getzep/graphiti", m50)
        self.assertIn("GitHub Copilot agentic memory", m50)
        self.assertIn("Borrow-When-Stuck Map", m50)
        self.assertIn("Live Qwen E2E proof", m50)
        self.assertIn("live_e2e_passed", m50)
        self.assertIn("Winner Polish Backlog", m50)
        self.assertIn("M51", m50)
        self.assertIn("M52", m50)

        self.assertIn("# RecallPack 3-Minute Demo Video Script", script)
        self.assertIn("Target length: 2:20-2:45", script)
        self.assertIn("0:00", script)
        self.assertIn("baseline stale context", script)
        self.assertIn("1/3 fixture tests", script)
        self.assertIn("RecallPack active memory", script)
        self.assertIn("3/3 fixture tests", script)
        self.assertIn("Qwen text model", script)
        self.assertIn("text-embedding-v4", script)
        self.assertIn("qwen3-rerank", script)
        self.assertIn("Alibaba Cloud ECS", script)
        self.assertIn("stored sanitized live Qwen provider-path trace", script)
        self.assertIn("Do not imply the public demo endpoint performs live Qwen calls", script)
        self.assertIn("turn-004` as supporting", script)

        self.assertIn("M50 external benchmark and winner polish: complete", readiness)
        self.assertIn("M50 external benchmark and winner polish", review_packet)
        self.assertIn("demo-video-script.md", review_packet)

        if handoff_path.exists():
            handoff = handoff_path.read_text()
            self.assertIn("M50 external benchmark and winner polish", handoff)
        if long_task_path.exists():
            long_task = long_task_path.read_text()
            self.assertIn("### M50: External Benchmark And Winner Polish", long_task)

    def test_m88_winner_grade_benchmark_audit_reflects_current_evidence(self):
        audit_path = ROOT / "docs" / "submission" / "winner-grade-benchmark-audit.md"
        if not audit_path.exists():
            self.skipTest("internal winner-grade audit is excluded from sanitized bundles")
        audit = audit_path.read_text()
        readiness = (ROOT / "docs" / "submission" / "local-readiness-report.md").read_text()
        handoff_path = ROOT / "docs" / "execution" / "HANDOFF.md"
        long_task_path = ROOT / "docs" / "execution" / "long-task-plan.md"

        self.assertIn("Status: refreshed after the M98 adversarial review remediation", audit)
        self.assertIn("P0 gaps remaining in local evidence", audit)
        self.assertIn("fresh M98 live rerun", audit)
        self.assertIn("live_e2e_passed", audit)
        self.assertIn("credential-free ECS runtime proof", audit)
        self.assertIn("one-click stale-memory failure replay", audit)
        self.assertIn("181 local tests", audit)
        self.assertIn("M88 winner-grade audit refresh: complete", readiness)
        self.assertIn("M98 unrigged raw-history baseline path", audit)
        self.assertNotIn("not yet winner-grade", audit)
        self.assertNotIn("still lacks\nthree winner-grade signals", audit)
        self.assertNotIn("does not close live/cloud P0s", audit)

        if handoff_path.exists() and long_task_path.exists():
            self.assertIn("## M88 Winner-Grade Audit Refresh", handoff_path.read_text())
            self.assertIn("### M88: Winner-Grade Audit Refresh", long_task_path.read_text())

    def test_m89_recording_and_public_copy_use_current_m88_snapshot(self):
        from tools import video_rehearsal_gate

        readme = (ROOT / "README.md").read_text()
        review_packet = (
            ROOT / "docs" / "submission" / "review-packet.md"
        ).read_text()
        public_report = (
            ROOT / "docs" / "submission" / "public-repo-readiness-report.md"
        ).read_text()
        rehearsal = (
            ROOT / "docs" / "submission" / "final-judge-rehearsal.md"
        ).read_text()
        packet = (
            ROOT / "docs" / "submission" / "video-production-packet.md"
        ).read_text()
        gate = (ROOT / "tools" / "video_rehearsal_gate.py").read_text()
        report = (
            ROOT / "docs" / "submission" / "recording-rehearsal-report.md"
        ).read_text()
        readiness = (
            ROOT / "docs" / "submission" / "local-readiness-report.md"
        ).read_text()
        handoff_path = ROOT / "docs" / "execution" / "HANDOFF.md"
        long_task_path = ROOT / "docs" / "execution" / "long-task-plan.md"

        self.assertIn("latest local package", readme)
        self.assertIn("M98 evidence snapshot", readme)
        self.assertIn("latest local package", review_packet)
        self.assertIn("M98 evidence snapshot", review_packet)
        self.assertIn("M104 prior verified ECS deployment", public_report)
        self.assertIn("latest local package and M98 evidence snapshot", rehearsal)
        self.assertIn("Keep public ECS credential-free; do not imply live Qwen runs there", packet)
        self.assertIn("latest bundle is described as the current local package", packet)
        self.assertIn("M98 remains the current evidence snapshot", packet)
        self.assertIn("Keep public ECS credential-free; do not imply live Qwen runs there", gate)
        self.assertIn("latest bundle is described as the current local package", gate)
        self.assertIn("M98 remains the current evidence snapshot", gate)
        self.assertIn(
            "latest bundle is described as the current local package",
            video_rehearsal_gate.PACKET_REQUIRED_SNIPPETS,
        )
        self.assertRegex(report, r"Sanitized bundle: dist/recallpack-submission-[0-9]{8}-[0-9]{6}")
        self.assertIn("M89 release-candidate wording refresh: complete", readiness)

        public_surfaces = "\n".join(
            [readme, review_packet, public_report, rehearsal, packet, report]
        )
        self.assertNotIn("current M85 local release candidate", public_surfaces)
        self.assertNotIn("M88 product evidence snapshot", public_surfaces)
        self.assertNotIn("M85 is described as the latest local release candidate", public_surfaces)
        self.assertNotIn("latest local package deployed to ECS", public_surfaces)
        self.assertNotIn("Keep M85 local bundle versus M65 ECS boundary honest", public_surfaces)
        if handoff_path.exists() and long_task_path.exists():
            self.assertIn("## M89 Release-Candidate Wording Refresh", handoff_path.read_text())
            self.assertIn("### M89: Release-Candidate Wording Refresh", long_task_path.read_text())

    def test_m51_architecture_diagram_is_judge_ready(self):
        diagram = (ROOT / "docs" / "submission" / "architecture-diagram.md").read_text()
        readme = (ROOT / "README.md").read_text()
        readiness = (ROOT / "docs" / "submission" / "local-readiness-report.md").read_text()
        review_packet = (ROOT / "docs" / "submission" / "review-packet.md").read_text()

        self.assertIn("# RecallPack Architecture Diagram", diagram)
        self.assertIn("```mermaid", diagram)
        self.assertIn("Browser demo", diagram)
        self.assertIn("Python demo backend", diagram)
        self.assertIn("POST /observe", diagram)
        self.assertIn("POST /compile", diagram)
        self.assertIn("SQLite event and memory store", diagram)
        self.assertIn("Qwen text model", diagram)
        self.assertIn("text-embedding-v4", diagram)
        self.assertIn("qwen3-rerank", diagram)
        self.assertIn("Budget selector", diagram)
        self.assertIn("Downstream evaluator", diagram)
        self.assertIn("Alibaba Cloud ECS", diagram)
        self.assertIn("Live-gated Qwen path", diagram)
        self.assertIn("Deterministic local proof path", diagram)
        self.assertIn("One stored live Qwen provider-path trace records `live_e2e_passed`", diagram)

        self.assertIn("Architecture Diagram", readme)
        self.assertIn("docs/submission/architecture-diagram.md", readme)
        self.assertIn("M51 final architecture diagram: complete", readiness)
        self.assertIn("M51 architecture diagram", review_packet)
        self.assertIn("docs/submission/architecture-diagram.md", review_packet)

    def test_m53_demo_media_package_is_recording_ready(self):
        media = (ROOT / "docs" / "submission" / "demo-media-package.md").read_text()
        media_readme = (ROOT / "docs" / "submission" / "media" / "README.md").read_text()
        readme = (ROOT / "README.md").read_text()
        readiness = (ROOT / "docs" / "submission" / "local-readiness-report.md").read_text()
        review_packet = (ROOT / "docs" / "submission" / "review-packet.md").read_text()
        devpost = (ROOT / "docs" / "submission" / "devpost-final-copy.md").read_text()

        self.assertIn("# RecallPack M53 Demo Media Package", media)
        self.assertIn("Recording target: 2:20-2:45", media)
        self.assertIn("Shot List", media)
        self.assertIn("Opening frame", media)
        self.assertIn("deterministic stale-memory failure replay", media)
        self.assertIn("local baseline stale context", media)
        self.assertIn("1/3` fixture tests", media)
        self.assertIn("RecallPack active memory", media)
        self.assertIn("3/3`", media)
        self.assertIn("Qwen Provider Integration Evidence", media)
        self.assertIn("Architecture Diagram", media)
        self.assertIn("Alibaba Cloud ECS", media)
        self.assertIn("Image Gallery Candidates", media)
        self.assertIn("Local Video Candidate Boundary", media)
        self.assertIn("no video upload was performed", media)
        self.assertIn("recallpack-demo-candidate.mp4", media)
        self.assertIn("one stored live Qwen provider-path trace completed", media)
        self.assertIn("Do not imply the public demo endpoint performs live Qwen calls", media)
        self.assertIn("Acceptance Checklist", media)

        self.assertIn("# RecallPack Media Assets", media_readme)
        self.assertIn("demo-media-package.md", media_readme)
        self.assertIn("Local video candidate", media_readme)
        self.assertIn("recallpack-demo-candidate.mp4", media_readme)
        self.assertIn("not proof of upload", media_readme)
        self.assertIn("architecture-diagram.png", media_readme)
        self.assertIn("alibaba-cloud-deployment-proof-redacted.png", media_readme)
        self.assertIn("alibaba-cloud-deployment-proof.png", media_readme)
        self.assertIn("do not upload this unredacted file", media_readme)
        self.assertIn("Sanitized public bundles exclude it", media_readme)
        self.assertIn("devpost-upload-state.json", media_readme)
        self.assertTrue(
            (
                ROOT
                / "docs"
                / "submission"
                / "media"
                / "alibaba-cloud-deployment-proof-redacted.png"
            ).is_file()
        )
        original_proof = ROOT / "docs" / "submission" / "media" / "alibaba-cloud-deployment-proof.png"
        if (ROOT / "SUBMISSION_MANIFEST.md").is_file():
            self.assertFalse(original_proof.exists())
        else:
            self.assertTrue(original_proof.is_file())

        self.assertIn("Demo Video And Media Package", readme)
        self.assertIn("docs/submission/demo-media-package.md", readme)
        self.assertIn("M53 demo media package: complete", readiness)
        self.assertIn("M53 demo media package", review_packet)
        self.assertIn("docs/submission/demo-media-package.md", review_packet)
        self.assertIn("Demo Media Package", devpost)

    def test_m66_winner_narrative_polish_is_recording_ready(self):
        script = (ROOT / "docs" / "submission" / "demo-video-script.md").read_text()
        devpost = (ROOT / "docs" / "submission" / "devpost-final-copy.md").read_text()
        media = (ROOT / "docs" / "submission" / "demo-media-package.md").read_text()
        qa = (ROOT / "docs" / "submission" / "skeptical-judge-qa.md").read_text()
        blog = (ROOT / "docs" / "submission" / "blog-post-draft.md").read_text()
        review_packet = (
            ROOT / "docs" / "submission" / "review-packet.md"
        ).read_text()
        readiness = (
            ROOT / "docs" / "submission" / "local-readiness-report.md"
        ).read_text()

        self.assertIn("M66 Winner Narrative Polish", media)
        self.assertIn("20 seconds", media)
        self.assertIn("40 seconds", media)
        self.assertIn("75 seconds", media)
        self.assertIn("90 seconds", media)
        self.assertIn("Recording-Day Checklist", media)

        self.assertIn("When a fresh coding agent takes over", script)
        self.assertIn(
            "RecallPack moves the decision",
            script,
        )
        self.assertIn("RecallPack prevents coding agents from acting on superseded project memory", script)
        self.assertIn("not better RAG", script)

        self.assertIn(
            "More context can make a coding agent worse when old decisions are stale.",
            devpost,
        )
        self.assertIn("not a generic agent platform", devpost)

        self.assertIn("Recording-Day Judge Answers", qa)
        self.assertIn("Is this just RAG?", qa)
        self.assertIn("Does the public demo run live Qwen?", qa)
        self.assertIn("Why only eight fixtures?", qa)

        self.assertIn("# Why Coding Agents Need Memory Lifecycle, Not More Context", blog)
        self.assertIn("More context can make coding agents worse", blog)
        self.assertIn("remember, supersede, and recall", blog)
        self.assertIn("text-embedding-v4", blog)
        self.assertIn("qwen3-rerank", blog)
        self.assertIn("not a broad benchmark", blog)
        self.assertIn("Blog Post Award", blog)

        self.assertIn("M66 winner narrative polish", review_packet)
        self.assertIn("docs/submission/blog-post-draft.md", review_packet)
        self.assertIn("M66 winner narrative polish: complete", readiness)

    def test_m67_final_judge_rehearsal_freezes_submission_surface(self):
        rehearsal = (
            ROOT / "docs" / "submission" / "final-judge-rehearsal.md"
        ).read_text()
        readme = (ROOT / "README.md").read_text()
        gate = (ROOT / "docs" / "submission" / "public-release-gate.md").read_text()
        readiness = (
            ROOT / "docs" / "submission" / "local-readiness-report.md"
        ).read_text()
        review_packet = (
            ROOT / "docs" / "submission" / "review-packet.md"
        ).read_text()

        self.assertIn("# RecallPack M67 Final Judge Rehearsal", rehearsal)
        self.assertIn("Submission Surface Freeze", rehearsal)
        self.assertIn("No new product features", rehearsal)
        self.assertIn("publish the sanitized bundle, not the raw workspace", rehearsal)
        self.assertIn("M98 evidence snapshot", rehearsal)
        self.assertIn("without adding new judge-facing product claims", rehearsal)
        self.assertNotIn("M71 local release candidate", rehearsal)
        self.assertIn("M104 public ECS runtime", rehearsal)
        self.assertRegex(rehearsal, r"dist/recallpack-submission-[0-9]{8}-[0-9]{6}")
        self.assertIn("http://101.133.224.223/", rehearsal)
        self.assertIn("https://github.com/cyq1017/recallpack", rehearsal)
        self.assertNotIn("- public GitHub repository URL;", rehearsal)
        self.assertIn("final video URL or upload", rehearsal)
        self.assertIn("final Devpost submit approval", rehearsal)
        self.assertIn("PYTHONPATH=src python3 tools/fresh_clone_smoke.py --source . --full", rehearsal)
        self.assertIn("python3 tools/final_submission_gate.py", rehearsal)
        self.assertIn("python3 tools/public_repo_preflight.py", rehearsal)
        self.assertIn("PYTHONPATH=src python3 tools/judge_smoke.py --url http://101.133.224.223 --timeout 15", rehearsal)
        self.assertIn("The approved ECS endpoint still reflects the M104", rehearsal)
        self.assertIn("do not claim the 7/7", rehearsal)
        self.assertNotIn("Do not claim M66 is deployed to ECS", rehearsal)
        self.assertIn("Do not rerun live Qwen without approval", rehearsal)

        self.assertIn("Final Judge Rehearsal", readme)
        self.assertIn("docs/submission/final-judge-rehearsal.md", readme)
        self.assertIn("latest local package", readme)
        self.assertIn("M98 evidence snapshot", readme)
        self.assertNotIn("current M85 local release candidate", readme)
        self.assertNotIn("current M81 local release candidate", readme)
        self.assertIn("final-judge-rehearsal.md", gate)
        self.assertIn("M67 final judge rehearsal: complete", readiness)
        self.assertIn("M67 final judge rehearsal", review_packet)

    def test_public_repo_copy_does_not_overstate_unverified_remote_freshness(self):
        documents = {
            "final rehearsal": ROOT / "docs" / "submission" / "final-judge-rehearsal.md",
            "public readiness": ROOT / "docs" / "submission" / "public-repo-readiness-report.md",
            "Devpost copy": ROOT / "docs" / "submission" / "devpost-final-copy.md",
            "review packet": ROOT / "docs" / "submission" / "review-packet.md",
            "evidence index": ROOT / "docs" / "submission" / "evidence-index.md",
        }

        for label, path in documents.items():
            with self.subTest(document=label):
                text = path.read_text()
                self.assertIn("does not prove", text)
                self.assertNotIn("was synced from the sanitized", text)
                self.assertNotIn("has been published at https://github.com", text)
                self.assertNotIn("has been created from the sanitized", text)

    def test_m68_video_production_packet_is_recording_executable(self):
        packet = (
            ROOT / "docs" / "submission" / "video-production-packet.md"
        ).read_text()
        readme = (ROOT / "README.md").read_text()
        media = (ROOT / "docs" / "submission" / "demo-media-package.md").read_text()
        readiness = (
            ROOT / "docs" / "submission" / "local-readiness-report.md"
        ).read_text()
        review_packet = (
            ROOT / "docs" / "submission" / "review-packet.md"
        ).read_text()
        gate = (ROOT / "docs" / "submission" / "public-release-gate.md").read_text()

        self.assertIn("# RecallPack M68 Video Production Packet", packet)
        self.assertIn("Recording lock: 2:20-2:45", packet)
        self.assertIn("One-Take Run Of Show", packet)
        self.assertIn("0:00-0:20", packet)
        self.assertIn("0:20-0:40", packet)
        self.assertIn("0:40-1:15", packet)
        self.assertIn("1:15-1:30", packet)
        self.assertIn("1:30-2:05", packet)
        self.assertIn("2:05-2:35", packet)
        self.assertIn("Retake Triggers", packet)
        self.assertIn("On-Screen No-Go List", packet)
        self.assertIn("Upload Package", packet)
        self.assertIn("Do not upload from this repo", packet)
        self.assertIn("Write-time lifecycle claim is the headline", packet)
        self.assertIn("authored deterministic replay", packet)
        self.assertIn("Local deterministic replay baseline stale context passes 1/3 fixture tests", packet)
        self.assertIn("RecallPack active memory passes 3/3 fixture tests", packet)
        self.assertIn("Deterministic stale-memory failure replay", packet)
        self.assertIn("Current gallery: `docs/submission/media/m71-replay/`", packet)
        self.assertIn("Do not imply the public demo endpoint performs live Qwen calls", packet)
        self.assertIn("PYTHONPATH=src python3 tools/judge_smoke.py --url http://101.133.224.223 --timeout 15", packet)

        self.assertIn("Video Production Packet", readme)
        self.assertIn("docs/submission/video-production-packet.md", readme)
        self.assertIn("docs/submission/video-production-packet.md", media)
        self.assertIn("docs/submission/video-production-packet.md", gate)
        self.assertIn("M68 video production packet: complete", readiness)
        self.assertIn("M68 video production packet", review_packet)

    def test_m69_video_rehearsal_gate_is_recording_ready_and_local_only(self):
        from tools.video_rehearsal_gate import build_video_rehearsal_gate

        payload = build_video_rehearsal_gate(ROOT)
        packet = (
            ROOT / "docs" / "submission" / "video-production-packet.md"
        ).read_text()
        report = (
            ROOT / "docs" / "submission" / "recording-rehearsal-report.md"
        ).read_text()
        readiness = (
            ROOT / "docs" / "submission" / "local-readiness-report.md"
        ).read_text()
        review_packet = (
            ROOT / "docs" / "submission" / "review-packet.md"
        ).read_text()
        readme = (ROOT / "README.md").read_text()

        self.assertEqual("ready_for_recording_gated_upload", payload["status"])
        self.assertTrue(payload["recording_ready"])
        self.assertEqual([], payload["local_failures"])
        self.assertEqual("live_e2e_passed", payload["live_qwen_e2e_status"])
        self.assertFalse(payload["requires_credentials"])
        self.assertFalse(payload["network_calls_made"])
        self.assertTrue(payload["no_public_action_performed"])
        self.assertNotIn("required_file_upload", payload["gated_actions"])
        self.assertIn("video_upload", payload["gated_actions"])
        self.assertIn("final video URL or upload", payload["manual_blockers"])
        self.assertNotIn(
            "required Devpost architecture and Alibaba Cloud proof file upload",
            payload["manual_blockers"],
        )
        self.assertEqual("built", payload["video_candidate"]["status"])
        self.assertEqual(
            "docs/submission/media/video-candidate/recallpack-demo-candidate.mp4",
            payload["video_candidate"]["path"],
        )
        self.assertFalse(payload["video_candidate"]["upload_performed"])
        if (ROOT / "SUBMISSION_MANIFEST.md").is_file():
            self.assertEqual(".", payload["sanitized_bundle"])
        else:
            self.assertRegex(
                payload["sanitized_bundle"],
                r"^dist/recallpack-submission-[0-9]{8}-[0-9]{6}$",
            )

        check_ids = {check["id"] for check in payload["checks"]}
        self.assertIn("run_of_show_anchors", check_ids)
        self.assertIn("recording_claim_guardrails", check_ids)
        self.assertIn("screenshot_assets", check_ids)
        self.assertIn("manual_upload_gates", check_ids)
        self.assertIn("public_ecs_boundary", check_ids)
        manual_gate = {
            check["id"]: check for check in payload["checks"]
        }["manual_upload_gates"]
        self.assertIn("video upload, media order, and final submit", manual_gate["summary"])

        self.assertIn("latest bundle is described as the current local package", packet)
        self.assertIn("M98 remains the current evidence snapshot", packet)
        self.assertIn("Fresh M98 live rerun is stored as failed evidence", packet)
        self.assertNotIn("Fresh M98 live rerun remains gated/not run", packet)
        self.assertNotIn("M85 is described as the latest local release candidate", packet)
        self.assertNotIn("M81 is described as the latest local release candidate", packet)
        self.assertNotIn("M80 is described as the latest local release candidate", packet)
        self.assertNotIn("M68 is described as the latest local release candidate", packet)
        self.assertNotIn("M67 is described as the latest local release candidate", packet)
        self.assertNotIn("M88 is described as the latest local evidence snapshot", packet)
        self.assertNotIn("M88 remains the product evidence snapshot", packet)
        self.assertIn("# RecallPack M69 Recording Rehearsal Report", report)
        self.assertIn("ready_for_recording_gated_upload", report)
        self.assertIn("recallpack-demo-candidate.mp4", report)
        self.assertIn("Local video candidate upload performed: false", report)
        self.assertIn("No public action was performed", report)
        self.assertIn("M69 recording rehearsal gate: complete", readiness)
        self.assertIn("M69 recording rehearsal gate", review_packet)
        self.assertIn("tools/video_rehearsal_gate.py", readme)
        self.assertIn("docs/submission/recording-rehearsal-report.md", readme)

        with tempfile.TemporaryDirectory() as tmp_dir:
            json_out = Path(tmp_dir) / "rehearsal.json"
            markdown_out = Path(tmp_dir) / "rehearsal.md"
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "tools" / "video_rehearsal_gate.py"),
                    "--json-out",
                    str(json_out),
                    "--markdown-out",
                    str(markdown_out),
                ],
                cwd=ROOT,
                check=True,
                capture_output=True,
                text=True,
            )
            cli_payload = json.loads(result.stdout)
            self.assertEqual("ready_for_recording_gated_upload", cli_payload["status"])
            self.assertEqual("ready_for_recording_gated_upload", json.loads(json_out.read_text())["status"])
            self.assertIn("Recording Rehearsal Report", markdown_out.read_text())

    def test_m86_recording_gate_tracks_current_release_candidate(self):
        from tools import video_rehearsal_gate

        packet = (
            ROOT / "docs" / "submission" / "video-production-packet.md"
        ).read_text()
        gate = (ROOT / "tools" / "video_rehearsal_gate.py").read_text()
        report = (
            ROOT / "docs" / "submission" / "recording-rehearsal-report.md"
        ).read_text()
        readiness = (
            ROOT / "docs" / "submission" / "local-readiness-report.md"
        ).read_text()
        review_packet = (
            ROOT / "docs" / "submission" / "review-packet.md"
        ).read_text()
        handoff_path = ROOT / "docs" / "execution" / "HANDOFF.md"
        long_task_path = ROOT / "docs" / "execution" / "long-task-plan.md"

        self.assertIn("Keep public ECS credential-free; do not imply live Qwen runs there", packet)
        self.assertIn("Do not imply the public ECS endpoint performs live Qwen calls", packet)
        self.assertIn("latest bundle is described as the current local package", packet)
        self.assertIn("M98 remains the current evidence snapshot", packet)
        self.assertNotIn("Keep M85 local bundle versus M65 ECS boundary honest", packet)
        self.assertNotIn("Do not claim the M85 local bundle is deployed to ECS", packet)
        self.assertNotIn("M85 is described as the latest local release candidate", packet)
        self.assertNotIn("Keep M81 local bundle versus M65 ECS boundary honest", packet)
        self.assertNotIn("Do not claim the M81 local bundle is deployed to ECS", packet)
        self.assertNotIn("M81 is described as the latest local release candidate", packet)

        self.assertIn("Keep public ECS credential-free; do not imply live Qwen runs there", gate)
        self.assertIn("latest bundle is described as the current local package", gate)
        self.assertIn(
            "latest bundle is described as the current local package",
            video_rehearsal_gate.PACKET_REQUIRED_SNIPPETS,
        )
        self.assertIn(
            "M98 remains the current evidence snapshot",
            video_rehearsal_gate.PACKET_REQUIRED_SNIPPETS,
        )
        self.assertIn(
            "M85 is described as the latest local release candidate",
            video_rehearsal_gate.PACKET_FORBIDDEN_SNIPPETS,
        )
        self.assertIn(
            "M81 is described as the latest local release candidate",
            video_rehearsal_gate.PACKET_FORBIDDEN_SNIPPETS,
        )

        self.assertIn("M86 recording release-candidate sync: complete", readiness)
        self.assertIn("M86 recording release-candidate sync", review_packet)
        self.assertRegex(report, r"Sanitized bundle: dist/recallpack-submission-[0-9]{8}-[0-9]{6}")

        if handoff_path.exists() and long_task_path.exists():
            self.assertIn("## M86 Recording Release-Candidate Sync", handoff_path.read_text())
            self.assertIn("### M86: Recording Release-Candidate Sync", long_task_path.read_text())

    def test_m87_public_copy_generation_source_is_current(self):
        readme = (ROOT / "README.md").read_text()
        review_packet = (
            ROOT / "docs" / "submission" / "review-packet.md"
        ).read_text()
        readiness = (
            ROOT / "docs" / "submission" / "local-readiness-report.md"
        ).read_text()
        public_report = (
            ROOT / "docs" / "submission" / "public-repo-readiness-report.md"
        ).read_text()
        handoff_path = ROOT / "docs" / "execution" / "HANDOFF.md"
        long_task_path = ROOT / "docs" / "execution" / "long-task-plan.md"

        self.assertIn("latest local package", readme)
        self.assertIn("M98 evidence snapshot", readme)
        self.assertNotIn("current M85 local release candidate", readme)
        self.assertNotIn("current M81 local release candidate", readme)
        self.assertIn("M104 keeps this packet honest", readme)

        self.assertIn("latest local package", review_packet)
        self.assertIn("M98 evidence snapshot", review_packet)
        self.assertIn("M86 recording release-candidate sync", review_packet)
        self.assertIn("M99 current-package wording sync", review_packet)
        self.assertNotIn("current M85 local release candidate", review_packet)
        self.assertNotIn("current M81 local release candidate", review_packet)

        self.assertIn("M87 public copy generation source sync: complete", readiness)
        self.assertIn("M99 keeps the current-package wording", public_report)
        self.assertIn("M98 is the current evidence snapshot", public_report)
        if handoff_path.exists() and long_task_path.exists():
            self.assertIn("## M87 Public Copy Generation Source Sync", handoff_path.read_text())
            self.assertIn("### M87: Public Copy Generation Source Sync", long_task_path.read_text())

    def test_m69_video_rehearsal_gate_reports_missing_external_root(self):
        from tools.video_rehearsal_gate import build_video_rehearsal_gate

        with tempfile.TemporaryDirectory() as tmp_dir:
            payload = build_video_rehearsal_gate(Path(tmp_dir))

        self.assertEqual("failed_recording_rehearsal_gate", payload["status"])
        self.assertFalse(payload["recording_ready"])
        self.assertTrue(payload["local_failures"])
        self.assertIn("missing video production packet", payload["local_failures"][0])

    def test_m54_public_release_gate_is_approval_ready(self):
        gate = (ROOT / "docs" / "submission" / "public-release-gate.md").read_text()
        readme = (ROOT / "README.md").read_text()
        readiness = (ROOT / "docs" / "submission" / "local-readiness-report.md").read_text()
        review_packet = (ROOT / "docs" / "submission" / "review-packet.md").read_text()
        public_report = (
            ROOT / "docs" / "submission" / "public-repo-readiness-report.md"
        ).read_text()

        self.assertIn("# RecallPack M54 Public Release Gate", gate)
        self.assertIn("Status: approval-ready local gate", gate)
        self.assertIn("No push, publish, public repo creation, image push, or Devpost submission was performed", gate)
        self.assertIn("Release Candidate Source", gate)
        self.assertIn("Sanitized bundle only", gate)
        self.assertIn("Do not publish the raw workspace", gate)
        self.assertIn("docs/execution/", gate)
        self.assertIn("AGENTS.md", gate)
        self.assertIn("dist/", gate)
        self.assertIn("Required Public Files", gate)
        self.assertIn("LICENSE", gate)
        self.assertIn("README.md", gate)
        self.assertIn("docs/submission/public-release-gate.md", gate)
        self.assertIn("Approval-Only Actions", gate)
        self.assertIn("public GitHub repository", gate)
        self.assertIn("Devpost submission", gate)
        self.assertIn("Final Judge Commands", gate)
        self.assertIn("tools/fresh_clone_smoke.py --source . --full", gate)
        self.assertIn("python3 tools/judge_smoke.py --url", gate)
        self.assertIn("No-Go Conditions", gate)
        self.assertIn("live Qwen E2E passed", gate)

        self.assertIn("Public Release Gate", readme)
        self.assertIn("docs/submission/public-release-gate.md", readme)
        self.assertIn("M54 public release gate: complete", readiness)
        self.assertIn("M54 public release gate", review_packet)
        self.assertIn("docs/submission/public-release-gate.md", review_packet)
        self.assertIn("public-release-gate.md", public_report)

    def test_m55_demo_gallery_screenshots_are_packaged(self):
        media = (ROOT / "docs" / "submission" / "demo-media-package.md").read_text()
        media_readme = (ROOT / "docs" / "submission" / "media" / "README.md").read_text()
        readiness = (ROOT / "docs" / "submission" / "local-readiness-report.md").read_text()
        review_packet = (ROOT / "docs" / "submission" / "review-packet.md").read_text()
        gate = (ROOT / "docs" / "submission" / "public-release-gate.md").read_text()
        public_report = (
            ROOT / "docs" / "submission" / "public-repo-readiness-report.md"
        ).read_text()

        expected = {
            "01-one-click-stale-memory-replay.png": "One-click stale-memory failure replay",
            "02-recallpack-active-memory-pack.png": "RecallPack active memory pack",
            "03-qwen-provider-evidence.png": "Qwen provider evidence",
        }
        for filename, label in expected.items():
            path = ROOT / "docs" / "submission" / "media" / "m71-replay" / filename
            self.assertTrue(path.is_file(), filename)
            self.assertGreater(path.stat().st_size, 20_000, filename)
            width, height = read_png_size(path)
            self.assertGreaterEqual(width, 1200, filename)
            self.assertGreaterEqual(height, 700, filename)
            self.assertIn(filename, media)
            self.assertIn(filename, media_readme)
            self.assertIn(label, media)

        self.assertIn("M55 local screenshot gallery: complete", readiness)
        self.assertIn("M72 current screenshot gallery: complete", readiness)
        self.assertIn("M55 local screenshot gallery", review_packet)
        self.assertIn("M72 current screenshot gallery", review_packet)
        self.assertIn("video-candidate/recallpack-demo-candidate.mp4", media_readme)
        self.assertIn("no video upload was performed", media)
        self.assertIn("docs/submission/media/m71-replay/*.png", gate)
        self.assertIn("Devpost screenshot gallery", public_report)

    def test_m56_screenshot_capture_tool_is_reproducible_without_live_services(self):
        script = ROOT / "tools" / "capture_demo_screenshots.py"
        readme = (ROOT / "README.md").read_text()
        media = (ROOT / "docs" / "submission" / "demo-media-package.md").read_text()
        readiness = (ROOT / "docs" / "submission" / "local-readiness-report.md").read_text()
        review_packet = (ROOT / "docs" / "submission" / "review-packet.md").read_text()
        public_report = (
            ROOT / "docs" / "submission" / "public-repo-readiness-report.md"
        ).read_text()

        result = subprocess.run(
            [sys.executable, str(script), "--list"],
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=10,
        )

        self.assertEqual(0, result.returncode, msg=result.stderr)
        payload = json.loads(result.stdout)
        self.assertFalse(payload["requires_live_qwen"])
        self.assertFalse(payload["uploads_media"])
        self.assertEqual("1280x720", payload["viewport"])
        self.assertEqual(
            [
                "01-one-click-stale-memory-replay.png",
                "02-recallpack-active-memory-pack.png",
                "03-qwen-provider-evidence.png",
            ],
            [item["filename"] for item in payload["shots"]],
        )
        self.assertIn("?view=recall", payload["shots"][1]["url"])
        self.assertIn("?view=evaluate", payload["shots"][2]["url"])

        command = "python3 tools/capture_demo_screenshots.py --url http://127.0.0.1:8789"
        self.assertIn(command, readme)
        self.assertIn(command, media)
        self.assertIn("M56 reproducible screenshot capture: complete", readiness)
        self.assertIn("M56 reproducible screenshot capture", review_packet)
        self.assertIn("tools/capture_demo_screenshots.py", public_report)

    def test_m56_screenshot_capture_tool_rejects_non_local_urls(self):
        script = ROOT / "tools" / "capture_demo_screenshots.py"

        result = subprocess.run(
            [sys.executable, str(script), "--url", "https://example.com"],
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=10,
        )

        self.assertEqual(2, result.returncode)
        self.assertIn("Only local demo URLs are supported", result.stderr)

    def test_m57_devpost_preflight_reports_local_materials_and_gated_actions(self):
        script = ROOT / "tools" / "devpost_preflight.py"
        readme = (ROOT / "README.md").read_text()
        gate = (ROOT / "docs" / "submission" / "public-release-gate.md").read_text()
        readiness = (ROOT / "docs" / "submission" / "local-readiness-report.md").read_text()
        review_packet = (ROOT / "docs" / "submission" / "review-packet.md").read_text()
        public_report = (
            ROOT / "docs" / "submission" / "public-repo-readiness-report.md"
        ).read_text()
        handoff_path = ROOT / "docs" / "execution" / "HANDOFF.md"
        long_task_path = ROOT / "docs" / "execution" / "long-task-plan.md"

        result = subprocess.run(
            [sys.executable, str(script)],
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=10,
        )

        self.assertEqual(0, result.returncode, msg=result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual("blocked_gated_actions", payload["status"])
        self.assertTrue(payload["ready_local_materials"])
        self.assertTrue(payload["no_public_action_performed"])
        self.assertFalse(payload["requires_credentials"])
        self.assertEqual("live_e2e_passed", payload["live_qwen_e2e_status"])
        self.assertEqual("live_e2e_failed", payload["fresh_m98_live_rerun_status"])
        self.assertEqual(
            "https://github.com/cyq1017/recallpack",
            payload["public_repo_url"],
        )
        self.assertNotIn("public GitHub repository URL", payload["missing_required_manual_items"])
        self.assertNotIn("fresh M98 live Qwen rerun approval/result", payload["missing_required_manual_items"])
        self.assertIn("final video URL or upload", payload["missing_required_manual_items"])
        self.assertIn(
            "final presentation PPT upload or link",
            payload["missing_required_manual_items"],
        )
        self.assertIn("final Devpost submit approval", payload["missing_required_manual_items"])
        self.assertIn("final media order confirmation", payload["missing_required_manual_items"])
        self.assertNotIn(
            "required Devpost architecture and Alibaba Cloud proof file upload",
            payload["missing_required_manual_items"],
        )
        self.assertNotIn("public ECS URL availability confirmation", payload["missing_required_manual_items"])
        self.assertEqual(
            "additional_info_media_uploaded",
            payload["devpost_upload_state"]["status"],
        )
        self.assertFalse(payload["devpost_upload_state"]["final_submit_performed"])
        self.assertEqual("built", payload["presentation_deck"]["status"])
        self.assertEqual(
            "docs/submission/media/recallpack-judge-deck.pptx",
            payload["presentation_deck"]["path"],
        )
        self.assertFalse(payload["presentation_deck"]["upload_performed"])
        self.assertNotIn("public_repo_push", payload["gated_actions"])
        self.assertNotIn("required_file_upload", payload["gated_actions"])
        self.assertIn("devpost_submission", payload["gated_actions"])
        self.assertIn("video_upload", payload["gated_actions"])
        self.assertIn("presentation_upload", payload["gated_actions"])
        self.assertNotIn("live_qwen_e2e_rerun", payload["gated_actions"])
        self.assertNotIn("ecs_redeploy_latest_bundle", payload["gated_actions"])
        if (ROOT / "SUBMISSION_MANIFEST.md").is_file():
            self.assertEqual(".", payload["sanitized_bundle"])
        else:
            self.assertRegex(
                payload["sanitized_bundle"],
                r"^dist/recallpack-submission-[0-9]{8}-[0-9]{6}$",
            )
        self.assertIn("README.md", payload["checked_files"])
        self.assertIn("LICENSE", payload["checked_files"])
        self.assertIn("docs/submission/devpost-final-copy.md", payload["checked_files"])
        self.assertIn("docs/submission/video-production-packet.md", payload["checked_files"])
        self.assertIn(
            "docs/submission/media/recallpack-judge-deck.pptx",
            payload["checked_files"],
        )
        self.assertIn("docs/submission/recording-rehearsal-report.md", payload["checked_files"])
        self.assertIn("docs/submission/public-release-gate.md", payload["checked_files"])
        self.assertIn("docs/submission/final-judge-rehearsal.md", payload["checked_files"])
        self.assertIn("docs/submission/review-packet.md", payload["checked_files"])

        screenshot_names = [asset["filename"] for asset in payload["media_assets"]]
        self.assertEqual(
            [
                "01-one-click-stale-memory-replay.png",
                "02-recallpack-active-memory-pack.png",
                "03-qwen-provider-evidence.png",
            ],
            screenshot_names,
        )
        screenshot_paths = [asset["path"] for asset in payload["media_assets"]]
        self.assertEqual(
            [
                "docs/submission/media/m71-replay/01-one-click-stale-memory-replay.png",
                "docs/submission/media/m71-replay/02-recallpack-active-memory-pack.png",
                "docs/submission/media/m71-replay/03-qwen-provider-evidence.png",
            ],
            screenshot_paths,
        )
        for asset in payload["media_assets"]:
            self.assertGreaterEqual(asset["width"], 1200, asset)
            self.assertGreaterEqual(asset["height"], 700, asset)
            self.assertGreater(asset["bytes"], 20_000, asset)

        from recallpack.submission_bundle import build_submission_bundle
        from tools.devpost_preflight import build_preflight

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "recallpack-submission"
            build_submission_bundle(ROOT, target)
            state_path = target / "docs" / "submission" / "devpost-upload-state.json"
            state_payload = json.loads(state_path.read_text())
            state_payload["uploads"][0]["upload_performed"] = False
            state_path.write_text(json.dumps(state_payload, indent=2) + "\n")

            stale_upload_payload = build_preflight(target)

        self.assertIn(
            "required Devpost architecture and Alibaba Cloud proof file upload",
            stale_upload_payload["missing_required_manual_items"],
        )
        self.assertIn("required_file_upload", stale_upload_payload["gated_actions"])

        command = "python3 tools/devpost_preflight.py"
        self.assertIn(command, readme)
        self.assertIn(command, gate)
        self.assertIn("M57 Devpost preflight: complete", readiness)
        self.assertIn("M57 Devpost preflight", review_packet)
        self.assertIn("Devpost preflight", public_report)
        if handoff_path.exists():
            self.assertIn("M57 Devpost preflight", handoff_path.read_text())
        if long_task_path.exists():
            self.assertIn("### M57: Devpost Preflight", long_task_path.read_text())

    def test_m58_devpost_materials_export_is_copy_ready_and_local_only(self):
        script = ROOT / "tools" / "export_devpost_materials.py"
        readme = (ROOT / "README.md").read_text()
        readiness = (ROOT / "docs" / "submission" / "local-readiness-report.md").read_text()
        review_packet = (ROOT / "docs" / "submission" / "review-packet.md").read_text()
        public_report = (
            ROOT / "docs" / "submission" / "public-repo-readiness-report.md"
        ).read_text()
        handoff_path = ROOT / "docs" / "execution" / "HANDOFF.md"
        long_task_path = ROOT / "docs" / "execution" / "long-task-plan.md"

        with tempfile.TemporaryDirectory() as tmp:
            json_out = Path(tmp) / "devpost-materials.json"
            markdown_out = Path(tmp) / "devpost-materials.md"

            result = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "--json-out",
                    str(json_out),
                    "--markdown-out",
                    str(markdown_out),
                ],
                cwd=ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=10,
            )

            self.assertEqual(0, result.returncode, msg=result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload, json.loads(json_out.read_text()))
            markdown = markdown_out.read_text()

        self.assertEqual("blocked_gated_actions", payload["status"])
        self.assertEqual("RecallPack", payload["project_name"])
        self.assertEqual("MemoryAgent", payload["track"])
        self.assertEqual(
            "Stale-aware memory lifecycle for coding-agent handoffs.",
            payload["tagline"],
        )
        self.assertIn("MemoryAgent project", payload["elevator_pitch"])
        self.assertIn("Python 3 standard library", payload["built_with"])
        self.assertIn("text-embedding-v4", payload["built_with"])
        self.assertIn("qwen3-rerank", payload["built_with"])
        self.assertIn("strategy review", payload["ai_tools_used"])
        self.assertFalse(payload["repository_url_required"])
        self.assertEqual("https://github.com/cyq1017/recallpack", payload["repository_url"])
        self.assertTrue(payload["video_url_required"])
        self.assertEqual("built", payload["video_candidate"]["status"])
        self.assertEqual(
            "docs/submission/media/video-candidate/recallpack-demo-candidate.mp4",
            payload["video_candidate"]["path"],
        )
        self.assertEqual(156.0, payload["video_candidate"]["duration_seconds"])
        self.assertFalse(payload["video_candidate"]["upload_performed"])
        self.assertIsNone(payload["video_candidate"]["devpost_video_url"])
        self.assertEqual("built", payload["presentation_deck"]["status"])
        self.assertEqual(
            "docs/submission/media/recallpack-judge-deck.pptx",
            payload["presentation_deck"]["path"],
        )
        self.assertFalse(payload["presentation_deck"]["upload_performed"])
        self.assertTrue(payload["no_public_action_performed"])
        self.assertFalse(payload["requires_credentials"])
        self.assertFalse(payload["network_calls_made"])
        self.assertEqual("live_e2e_passed", payload["live_qwen_e2e_status"])
        self.assertEqual("live_e2e_failed", payload["fresh_m98_live_rerun_status"])
        self.assertNotIn("public GitHub repository URL", payload["manual_blockers"])
        self.assertNotIn("fresh M98 live Qwen rerun approval/result", payload["manual_blockers"])
        self.assertIn("final video URL or upload", payload["manual_blockers"])
        self.assertIn("devpost-final-copy.md", payload["copy_sources"]["project_story"])
        self.assertIn("hackathon-fields.md", payload["copy_sources"]["short_description"])
        self.assertEqual(
            [
                "01-one-click-stale-memory-replay.png",
                "02-recallpack-active-memory-pack.png",
                "03-qwen-provider-evidence.png",
            ],
            [asset["filename"] for asset in payload["media_assets"]],
        )
        self.assertEqual(
            "docs/submission/media/m71-replay/01-one-click-stale-memory-replay.png",
            payload["media_assets"][0]["path"],
        )
        self.assertEqual(
            ["architecture-diagram.png", "alibaba-cloud-deployment-proof-redacted.png"],
            [asset["filename"] for asset in payload["required_upload_candidates"]],
        )
        self.assertTrue(payload["required_upload_candidates"][0]["upload_performed"])
        self.assertTrue(payload["required_upload_candidates"][0]["privacy_checked"])
        self.assertTrue(payload["required_upload_candidates"][1]["upload_performed"])
        self.assertTrue(payload["required_upload_candidates"][1]["privacy_checked"])
        self.assertTrue(payload["required_upload_candidates"][1]["redacted"])
        self.assertEqual(
            "additional_info_media_uploaded",
            payload["devpost_upload_state"]["status"],
        )
        self.assertFalse(payload["devpost_upload_state"]["final_submit_performed"])
        self.assertIn("Required Devpost File Upload Candidates", markdown)
        self.assertIn("## Presentation PPT", markdown)
        self.assertIn("recallpack-judge-deck.pptx", markdown)
        self.assertIn(
            "Not uploaded: recallpack-judge-deck.pptx -> Presentation PPT",
            markdown,
        )
        self.assertIn("alibaba-cloud-deployment-proof-redacted.png", markdown)
        self.assertIn("Known Devpost Upload State", markdown)
        self.assertGreaterEqual(payload["verification"]["unit_tests"], 125)
        self.assertRegex(
            payload["verification"]["sanitized_bundle"],
            r"^dist/recallpack-submission-[0-9]{8}-[0-9]{6}$|\.$",
        )

        self.assertIn("# RecallPack Devpost Materials Export", markdown)
        self.assertIn("Project name: RecallPack", markdown)
        self.assertIn("Track: MemoryAgent", markdown)
        self.assertIn("Status: blocked_gated_actions", markdown)
        self.assertIn("This export does not perform public actions", markdown)
        self.assertIn("01-one-click-stale-memory-replay.png", markdown)
        self.assertIn("docs/submission/media/m71-replay", markdown)
        self.assertIn("https://github.com/cyq1017/recallpack", markdown)
        self.assertIn("final video URL or upload", markdown)

        command = "python3 tools/export_devpost_materials.py"
        self.assertIn(command, readme)
        self.assertIn("M58 Devpost materials export: complete", readiness)
        self.assertIn("M58 Devpost materials export", review_packet)
        self.assertIn("Devpost materials export", public_report)
        if handoff_path.exists():
            self.assertIn("M58 Devpost materials export", handoff_path.read_text())
        if long_task_path.exists():
            self.assertIn("### M58: Devpost Materials Export", long_task_path.read_text())

    def test_m58_devpost_materials_export_module_is_importable_for_reuse(self):
        from tools.export_devpost_materials import build_materials, render_markdown

        payload = build_materials(ROOT)
        markdown = render_markdown(payload)

        self.assertEqual("RecallPack", payload["project_name"])
        self.assertEqual("blocked_gated_actions", payload["status"])
        self.assertIn("This export does not perform public actions", markdown)

    def test_m59_submission_evidence_index_maps_claims_to_files_and_commands(self):
        script = ROOT / "tools" / "export_evidence_index.py"
        readme = (ROOT / "README.md").read_text()
        readiness = (ROOT / "docs" / "submission" / "local-readiness-report.md").read_text()
        review_packet = (ROOT / "docs" / "submission" / "review-packet.md").read_text()
        public_report = (
            ROOT / "docs" / "submission" / "public-repo-readiness-report.md"
        ).read_text()
        handoff_path = ROOT / "docs" / "execution" / "HANDOFF.md"
        long_task_path = ROOT / "docs" / "execution" / "long-task-plan.md"

        with tempfile.TemporaryDirectory() as tmp:
            json_out = Path(tmp) / "evidence-index.json"
            markdown_out = Path(tmp) / "evidence-index.md"
            result = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "--json-out",
                    str(json_out),
                    "--markdown-out",
                    str(markdown_out),
                ],
                cwd=ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=10,
            )

            self.assertEqual(0, result.returncode, msg=result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload, json.loads(json_out.read_text()))
            markdown = markdown_out.read_text()

        self.assertEqual("local_evidence_ready_gated_submission", payload["status"])
        self.assertTrue(payload["no_public_action_performed"])
        self.assertFalse(payload["requires_credentials"])
        self.assertFalse(payload["network_calls_made"])
        self.assertEqual("live_e2e_passed", payload["live_qwen_e2e_status"])
        self.assertEqual("live_e2e_failed", payload["fresh_m98_live_rerun_status"])
        self.assertEqual("https://github.com/cyq1017/recallpack", payload["public_repo_url"])
        self.assertNotIn("public GitHub repository URL", payload["manual_blockers"])

        claims = {claim["id"]: claim for claim in payload["claims"]}
        for claim_id in [
            "memoryagent_positioning",
            "downstream_stale_handoff_proof",
            "qwen_provider_integration",
            "live_qwen_e2e_boundary",
            "public_repo_boundary",
            "devpost_media_readiness",
        ]:
            self.assertIn(claim_id, claims)
            self.assertTrue(claims[claim_id]["evidence_files"], claim_id)
            self.assertTrue(claims[claim_id]["verification_commands"], claim_id)
            self.assertIn(claims[claim_id]["claim_status"], {"local_proven", "gated_boundary"})

        self.assertIn("1/3", claims["downstream_stale_handoff_proof"]["evidence_summary"])
        self.assertIn(
            "project-c/d/e baselines are rejected as empty_patch and score 0/3",
            claims["downstream_stale_handoff_proof"]["evidence_summary"],
        )
        self.assertIn("3/3", claims["downstream_stale_handoff_proof"]["evidence_summary"])
        self.assertIn("patch-generation", claims["qwen_provider_integration"]["claim"])
        self.assertIn(
            "patch_generation=2",
            claims["qwen_provider_integration"]["evidence_summary"],
        )
        self.assertIn(
            "docs/submission/live-qwen-e2e-preflight.json",
            claims["qwen_provider_integration"]["evidence_files"],
        )
        self.assertIn(
            "docs/submission/projectodyssey-live-qwen-e2e-preflight.json",
            claims["qwen_provider_integration"]["evidence_files"],
        )
        self.assertIn(
            "docs/submission/projectodyssey-live-qwen-e2e-trace.json",
            claims["qwen_provider_integration"]["evidence_files"],
        )
        self.assertIn(
            "RecallPack downstream patch generation passing 3/3",
            claims["qwen_provider_integration"]["evidence_summary"],
        )
        self.assertIn(
            "ProjectOdyssey",
            claims["qwen_provider_integration"]["evidence_summary"],
        )
        self.assertIn(
            "RECALLPACK_LIVE_QWEN_E2E_FIXTURE=fixtures/project-h-projectodyssey-jit",
            " ".join(claims["qwen_provider_integration"]["verification_commands"]),
        )
        self.assertIn(
            "docs/submission/live-qwen-e2e-trace.json",
            claims["live_qwen_e2e_boundary"]["evidence_files"],
        )
        self.assertIn(
            "docs/submission/projectodyssey-live-qwen-e2e-trace.json",
            claims["live_qwen_e2e_boundary"]["evidence_files"],
        )
        self.assertIn(
            "passing ProjectOdyssey live run",
            claims["live_qwen_e2e_boundary"]["claim"],
        )
        self.assertIn(
            "ProjectOdyssey live Qwen selected required active sources",
            claims["live_qwen_e2e_boundary"]["evidence_summary"],
        )
        self.assertIn(
            "RecallPack live-generated patch generation passed 3/3",
            claims["live_qwen_e2e_boundary"]["evidence_summary"],
        )
        self.assertEqual("gated_boundary", claims["live_qwen_e2e_boundary"]["claim_status"])
        self.assertEqual("local_proven", claims["public_repo_boundary"]["claim_status"])
        self.assertIn("https://github.com/cyq1017/recallpack", claims["public_repo_boundary"]["evidence_summary"])
        self.assertIn(
            "does not prove the remote repository contains the latest bundle",
            claims["public_repo_boundary"]["evidence_summary"],
        )
        self.assertNotIn(
            "synced the public repository",
            claims["public_repo_boundary"]["evidence_summary"],
        )
        self.assertIn(
            "fresh_clone_smoke.py --source . --full",
            claims["public_repo_boundary"]["evidence_summary"],
        )
        self.assertIn("one historical pass", claims["live_qwen_e2e_boundary"]["evidence_summary"])
        self.assertIn("one passing ProjectOdyssey run", claims["live_qwen_e2e_boundary"]["evidence_summary"])
        self.assertIn("Lifecycle checks held", claims["live_qwen_e2e_boundary"]["evidence_summary"])
        self.assertIn("structural stale exclusion", claims["live_qwen_e2e_boundary"]["evidence_summary"])
        self.assertNotIn(
            "required Devpost architecture and Alibaba Cloud proof file upload",
            payload["manual_blockers"],
        )
        self.assertIn(
            "docs/submission/media/architecture-diagram.png",
            claims["devpost_media_readiness"]["evidence_files"],
        )
        self.assertIn(
            "docs/submission/media/alibaba-cloud-deployment-proof-redacted.png",
            claims["devpost_media_readiness"]["evidence_files"],
        )
        self.assertIn(
            "Required Devpost image uploads are recorded as complete",
            claims["devpost_media_readiness"]["evidence_summary"],
        )
        self.assertNotIn("fresh M98 live Qwen rerun approval/result", payload["manual_blockers"])

        self.assertIn("# RecallPack Submission Evidence Index", markdown)
        self.assertIn("Claim-To-Evidence Index", markdown)
        self.assertIn("downstream_stale_handoff_proof", markdown)
        self.assertIn("one passing ProjectOdyssey run", markdown)
        self.assertIn("This export performs no public action", markdown)
        self.assertIn("PYTHONPATH=src python3 -m unittest discover -s tests -v", markdown)

        command = "python3 tools/export_evidence_index.py"
        self.assertIn(command, readme)
        self.assertIn("M59 submission evidence index: complete", readiness)
        self.assertIn("M59 submission evidence index", review_packet)
        self.assertIn("Submission evidence index", public_report)
        if handoff_path.exists():
            self.assertIn("M59 submission evidence index", handoff_path.read_text())
        if long_task_path.exists():
            self.assertIn("### M59: Submission Evidence Index", long_task_path.read_text())

    def test_m60_final_submission_gate_runs_public_bundle_and_records_manual_gates(self):
        if os.environ.get("RECALLPACK_FRESH_CLONE_CHILD") == "1":
            self.skipTest("fresh-clone child run skips recursive final gate tests")

        from recallpack.submission_bundle import build_submission_bundle

        readme = (ROOT / "README.md").read_text()
        readiness = (ROOT / "docs" / "submission" / "local-readiness-report.md").read_text()
        review_packet = (ROOT / "docs" / "submission" / "review-packet.md").read_text()
        public_report = (
            ROOT / "docs" / "submission" / "public-repo-readiness-report.md"
        ).read_text()
        handoff_path = ROOT / "docs" / "execution" / "HANDOFF.md"
        long_task_path = ROOT / "docs" / "execution" / "long-task-plan.md"

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "recallpack-submission"
            build_submission_bundle(ROOT, target)
            result = subprocess.run(
                [sys.executable, "tools/final_submission_gate.py", "--root", "."],
                cwd=target,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=90,
            )

        self.assertEqual(0, result.returncode, msg=result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual("ready_local_evidence_gated_manual_submission", payload["status"])
        self.assertTrue(payload["local_ready"])
        self.assertTrue(payload["no_public_action_performed"])
        self.assertFalse(payload["requires_credentials"])
        self.assertFalse(payload["network_calls_made"])
        self.assertEqual("live_e2e_passed", payload["live_qwen_e2e_status"])
        self.assertEqual("live_e2e_failed", payload["fresh_m98_live_rerun_status"])
        self.assertEqual("https://github.com/cyq1017/recallpack", payload["public_repo_url"])
        self.assertNotIn("public GitHub repository URL", payload["manual_blockers"])
        self.assertNotIn("required_file_upload", payload["gated_actions"])
        self.assertIn("devpost_submission", payload["gated_actions"])

        gates = {gate["id"]: gate for gate in payload["local_gates"]}
        for gate_id in [
            "devpost_preflight",
            "evidence_index",
            "public_bundle_scan",
            "fresh_clone_full",
        ]:
            self.assertEqual("passed", gates[gate_id]["status"], gate_id)
        self.assertEqual(6, gates["evidence_index"]["claim_count"])
        self.assertEqual("full", gates["fresh_clone_full"]["unit_mode"])
        self.assertEqual("passed", gates["fresh_clone_full"]["judge_smoke"])
        self.assertEqual([], gates["public_bundle_scan"]["findings"]["secret_hits"])
        self.assertEqual([], gates["public_bundle_scan"]["findings"]["local_path_hits"])
        self.assertIn("python3 tools/final_submission_gate.py", payload["recommended_commands"])

        command = "python3 tools/final_submission_gate.py"
        self.assertIn(command, readme)
        self.assertIn("M60 final submission gate: complete", readiness)
        self.assertIn("M60 final submission gate", review_packet)
        self.assertIn("Final submission gate", public_report)
        if handoff_path.exists():
            self.assertIn("M60 final submission gate", handoff_path.read_text())
        if long_task_path.exists():
            self.assertIn("### M60: Final Submission Gate", long_task_path.read_text())

    def test_m61_public_repo_preflight_validates_publish_surface_without_pushing(self):
        from recallpack.submission_bundle import build_submission_bundle

        readme = (ROOT / "README.md").read_text()
        readiness = (ROOT / "docs" / "submission" / "local-readiness-report.md").read_text()
        review_packet = (ROOT / "docs" / "submission" / "review-packet.md").read_text()
        public_report = (
            ROOT / "docs" / "submission" / "public-repo-readiness-report.md"
        ).read_text()
        release_gate = (ROOT / "docs" / "submission" / "public-release-gate.md").read_text()
        handoff_path = ROOT / "docs" / "execution" / "HANDOFF.md"
        long_task_path = ROOT / "docs" / "execution" / "long-task-plan.md"

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "recallpack-submission"
            build_submission_bundle(ROOT, target)
            result = subprocess.run(
                [sys.executable, "tools/public_repo_preflight.py", "--root", "."],
                cwd=target,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=15,
            )

        self.assertEqual(0, result.returncode, msg=result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual("ready_for_public_repo_sync", payload["status"])
        self.assertTrue(payload["ready"])
        self.assertEqual("sanitized_bundle", payload["source_kind"])
        self.assertTrue(payload["must_publish_bundle_not_raw_workspace"])
        self.assertEqual("https://github.com/cyq1017/recallpack", payload["public_repo_url"])
        self.assertFalse(payload["remote_sync_verified"])
        self.assertIn("does not prove the latest sanitized bundle", payload["remote_sync_note"])
        self.assertTrue(payload["no_public_action_performed"])
        self.assertFalse(payload["requires_credentials"])
        self.assertFalse(payload["network_calls_made"])
        self.assertNotIn("public GitHub repository URL", payload["manual_blockers"])
        self.assertNotIn("add the public repository URL to Devpost", payload["manual_next_steps"])
        self.assertEqual(
            "run the judge commands from the public repository root",
            payload["manual_next_steps"][0],
        )

        checks = {check["id"]: check for check in payload["checks"]}
        for check_id in [
            "source_bundle_parity",
            "mit_license",
            "readme_judge_start",
            "submission_manifest",
            "forbidden_paths_absent",
            "bundle_scan_clean",
            "verification_commands_present",
        ]:
            self.assertEqual("passed", checks[check_id]["status"], check_id)
        self.assertEqual([], checks["bundle_scan_clean"]["findings"]["secret_hits"])
        self.assertEqual([], checks["bundle_scan_clean"]["findings"]["local_path_hits"])
        self.assertIn("PYTHONPATH=src python3 -m unittest discover -s tests -v", payload["judge_commands"])
        self.assertIn("python3 tools/final_submission_gate.py", payload["judge_commands"])

        command = "python3 tools/public_repo_preflight.py"
        self.assertIn(command, readme)
        self.assertIn("M61 public repo preflight: complete", readiness)
        self.assertIn("M61 public repo preflight", review_packet)
        self.assertIn("Deterministic handoff replay", review_packet)
        self.assertIn("does not add a new live-Qwen claim", review_packet)
        self.assertIn("Public repo preflight", public_report)
        self.assertIn(command, release_gate)
        if handoff_path.exists():
            self.assertIn("M61 public repo preflight", handoff_path.read_text())
        if long_task_path.exists():
            self.assertIn("### M61: Public Repo Preflight", long_task_path.read_text())

    def test_submission_readiness_loop_aggregates_local_gates_without_external_actions(self):
        from tools.submission_readiness_loop import build_submission_readiness_loop

        readme = (ROOT / "README.md").read_text()
        readiness = (ROOT / "docs" / "submission" / "local-readiness-report.md").read_text()
        review_packet = (ROOT / "docs" / "submission" / "review-packet.md").read_text()
        release_gate = (ROOT / "docs" / "submission" / "public-release-gate.md").read_text()

        payload = build_submission_readiness_loop(ROOT, include_final_gate=False)

        self.assertEqual("ready_for_full_loop_verification", payload["status"])
        self.assertTrue(payload["local_ready_without_final_gate"])
        self.assertFalse(payload["full_final_gate_run"])
        self.assertTrue(payload["no_public_action_performed"])
        self.assertFalse(payload["requires_credentials"])
        self.assertFalse(payload["network_calls_made"])
        self.assertEqual("https://github.com/cyq1017/recallpack", payload["public_repo_url"])
        self.assertFalse(payload["remote_sync_verified"])
        self.assertIn("does not prove the latest sanitized bundle", payload["remote_sync_note"])
        self.assertIn("final video URL or upload", payload["manual_blockers"])
        self.assertIn("final presentation PPT upload or link", payload["manual_blockers"])
        self.assertIn("final Devpost submit approval", payload["manual_blockers"])
        self.assertNotIn("public GitHub repository URL", payload["manual_blockers"])
        self.assertIn("devpost_submission", payload["gated_actions"])
        self.assertIn("presentation_upload", payload["gated_actions"])
        self.assertIn("video_upload", payload["gated_actions"])

        checks = {check["id"]: check for check in payload["checks"]}
        self.assertEqual("passed", checks["devpost_preflight"]["status"])
        self.assertEqual("passed", checks["video_rehearsal_gate"]["status"])
        self.assertEqual("passed", checks["public_repo_preflight"]["status"])
        self.assertEqual("skipped", checks["final_submission_gate"]["status"])
        self.assertEqual(
            "python3 tools/submission_readiness_loop.py --full",
            payload["next_recommended_command"],
        )

        command = "python3 tools/submission_readiness_loop.py --full"
        self.assertIn(command, readme)
        self.assertIn(command, release_gate)
        self.assertIn("submission readiness loop", readiness)
        self.assertIn("submission readiness loop", review_packet)

    def test_m97_public_repo_preflight_rejects_stale_bundle_when_source_docs_changed(self):
        from recallpack.submission_bundle import build_submission_bundle
        from tools.public_repo_preflight import build_public_repo_preflight

        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            shutil.copytree(
                ROOT,
                workspace,
                ignore=shutil.ignore_patterns(
                    ".git",
                    "dist",
                    "__pycache__",
                    "*.pyc",
                    ".DS_Store",
                ),
            )
            manifest_path = workspace / "SUBMISSION_MANIFEST.md"
            if manifest_path.exists():
                manifest_path.unlink()
            release_gate = (
                workspace / "docs" / "submission" / "public-release-gate.md"
            ).read_text()
            match = re.search(r"dist/recallpack-submission-\d{8}-\d{6}", release_gate)
            self.assertIsNotNone(match)
            build_submission_bundle(workspace, workspace / match.group(0))

            readme_path = workspace / "README.md"
            readme_path.write_text(
                readme_path.read_text()
                + "\n\nM97 source-to-bundle drift marker.\n"
            )

            payload = build_public_repo_preflight(workspace)

        checks = {check["id"]: check for check in payload["checks"]}
        self.assertFalse(payload["ready"])
        self.assertEqual("blocked_public_repo_preflight", payload["status"])
        self.assertIn("source_bundle_parity", checks)
        self.assertEqual("failed", checks["source_bundle_parity"]["status"])
        self.assertIn("README.md", checks["source_bundle_parity"]["mismatched"])

        readiness = (
            ROOT / "docs" / "submission" / "local-readiness-report.md"
        ).read_text()
        public_report = (
            ROOT / "docs" / "submission" / "public-repo-readiness-report.md"
        ).read_text()
        review_packet = (
            ROOT / "docs" / "submission" / "review-packet.md"
        ).read_text()
        handoff_path = ROOT / "docs" / "execution" / "HANDOFF.md"
        long_task_path = ROOT / "docs" / "execution" / "long-task-plan.md"

        self.assertIn("M97 source-to-bundle parity preflight: complete", readiness)
        self.assertIn("M97 source-to-bundle parity preflight", public_report)
        self.assertIn("M97 source-to-bundle parity preflight", review_packet)
        if handoff_path.exists() and long_task_path.exists():
            self.assertIn("## M97 Source-To-Bundle Parity Preflight", handoff_path.read_text())
            self.assertIn("### M97: Source-To-Bundle Parity Preflight", long_task_path.read_text())

    def test_public_repo_preflight_scans_tracked_files_after_judge_commands(self):
        from recallpack.submission_bundle import build_submission_bundle
        from tools.public_repo_preflight import build_public_repo_preflight

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "recallpack-public"
            build_submission_bundle(ROOT, target)
            subprocess.run(["git", "init"], cwd=target, check=True, stdout=subprocess.PIPE)
            subprocess.run(["git", "add", "."], cwd=target, check=True, stdout=subprocess.PIPE)
            cache_path = target / "tests" / "__pycache__" / "generated.pyc"
            cache_path.parent.mkdir(parents=True)
            cache_payload = "compiled-local-cache-" + "sk-" + "abcdefghijklmnopqrstuvwxyz"
            cache_path.write_bytes(cache_payload.encode("utf-8"))

            payload = build_public_repo_preflight(target)

        checks = {check["id"]: check for check in payload["checks"]}
        self.assertTrue(payload["ready"])
        self.assertEqual("passed", checks["bundle_scan_clean"]["status"])
        self.assertEqual([], checks["bundle_scan_clean"]["findings"]["secret_hits"])
        self.assertEqual([], checks["bundle_scan_clean"]["findings"]["generated_artifact_hits"])

    def test_public_repo_preflight_ignores_intentionally_excluded_submission_docs(self):
        from recallpack.submission_bundle import (
            PUBLIC_LOCAL_ONLY_FILES,
            PUBLIC_SUBMISSION_DOC_EXCLUDES,
            build_submission_bundle,
        )
        from tools.public_repo_preflight import build_public_repo_preflight

        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            shutil.copytree(
                ROOT,
                workspace,
                ignore=shutil.ignore_patterns(
                    ".git",
                    "dist",
                    "__pycache__",
                    "*.pyc",
                    ".DS_Store",
                ),
            )
            release_gate = (
                workspace / "docs" / "submission" / "public-release-gate.md"
            ).read_text()
            match = re.search(r"dist/recallpack-submission-\d{8}-\d{6}", release_gate)
            self.assertIsNotNone(match)
            build_submission_bundle(workspace, workspace / match.group(0))

            payload = build_public_repo_preflight(workspace)

        checks = {check["id"]: check for check in payload["checks"]}
        parity = checks["source_bundle_parity"]
        excluded_paths = {
            f"docs/submission/{name}" for name in PUBLIC_SUBMISSION_DOC_EXCLUDES
        }
        self.assertEqual("passed", parity["status"])
        self.assertTrue(excluded_paths)
        self.assertFalse(excluded_paths.intersection(parity["missing"]))
        self.assertFalse(PUBLIC_LOCAL_ONLY_FILES.intersection(parity["missing"]))

    def test_m71_replay_milestone_is_recorded_in_internal_execution_docs(self):
        handoff_path = ROOT / "docs" / "execution" / "HANDOFF.md"
        long_task_path = ROOT / "docs" / "execution" / "long-task-plan.md"
        if not handoff_path.exists() or not long_task_path.exists():
            self.skipTest("internal execution docs are excluded from sanitized bundles")

        handoff = handoff_path.read_text()
        long_task = long_task_path.read_text()

        self.assertIn("## M71 One-Click Stale-Memory Failure Replay", handoff)
        self.assertIn("baseline fixture tests 1/3", handoff)
        self.assertIn("adds no new", handoff)
        self.assertIn("### M71: One-Click Stale-Memory Failure Replay", long_task)
        self.assertIn("renderHandoffReplay", long_task)
        self.assertIn("does not add a new live-Qwen", long_task)
        self.assertIn("claim", long_task)
        self.assertIn("## M72 Current Screenshot Gallery Refresh", handoff)
        self.assertIn("docs/submission/media/m71-replay", handoff)
        self.assertIn("### M72: Current Screenshot Gallery Refresh", long_task)
        self.assertIn("01-one-click-stale-memory-replay.png", long_task)
        self.assertIn("## M73 Live Qwen Trace Explorer", handoff)
        self.assertIn("trace_explorer", handoff)
        self.assertIn("### M73: Live Qwen Trace Explorer", long_task)
        self.assertIn("renderQwenTraceExplorer", long_task)

    def test_m85_deadline_runway_is_recorded_as_internal_planning_only(self):
        runway_path = ROOT / "docs" / "execution" / "deadline-runway-plan.md"
        handoff_path = ROOT / "docs" / "execution" / "HANDOFF.md"
        long_task_path = ROOT / "docs" / "execution" / "long-task-plan.md"
        if not handoff_path.exists() or not long_task_path.exists():
            self.skipTest("internal execution docs are excluded from sanitized bundles")

        runway = runway_path.read_text()
        handoff = handoff_path.read_text()
        long_task = long_task_path.read_text()

        self.assertIn("# RecallPack M85 Deadline Runway Plan", runway)
        self.assertIn("2026-07-09 14:00 PDT", runway)
        self.assertIn("2026-07-10 05:00 CST", runway)
        self.assertIn("2026-07-07 10:43 CST", runway)
        self.assertIn("about 2 days 18 hours 17 minutes", runway)
        self.assertIn("T-7 to T-5", runway)
        self.assertIn("T-5 to T-3", runway)
        self.assertIn("T-3 to T-1", runway)
        self.assertIn("T-1 to deadline", runway)
        self.assertIn("Internal planning only", runway)
        self.assertIn("not judge-facing evidence", runway)
        self.assertIn("public repo push", runway)
        self.assertIn("Devpost submit", runway)
        self.assertIn("latest-bundle ECS redeploy", runway)

        self.assertIn("## M85 Deadline Runway Plan", handoff)
        self.assertIn("M0 through M96 are locally complete", handoff)
        self.assertIn("### M85: Deadline Runway Plan", long_task)
        self.assertIn("freeze product-quality work before T-3", long_task)

    def test_m90_current_day_deadline_runway_refresh_is_recorded(self):
        runway_path = ROOT / "docs" / "execution" / "deadline-runway-plan.md"
        handoff_path = ROOT / "docs" / "execution" / "HANDOFF.md"
        long_task_path = ROOT / "docs" / "execution" / "long-task-plan.md"
        if not handoff_path.exists() or not long_task_path.exists():
            self.skipTest("internal execution docs are excluded from sanitized bundles")

        public_report = (
            ROOT / "docs" / "submission" / "public-repo-readiness-report.md"
        ).read_text()
        readiness = (
            ROOT / "docs" / "submission" / "local-readiness-report.md"
        ).read_text()
        runway = runway_path.read_text()
        handoff = handoff_path.read_text()
        long_task = long_task_path.read_text()

        self.assertIn("Date: 2026-07-07", public_report)
        self.assertIn("Date: 2026-07-09", readiness)
        self.assertNotIn("Date: 2026-07-02", public_report)
        self.assertIn("Sources rechecked on 2026-07-07", runway)
        self.assertIn("Local check: `2026-07-07 10:43 CST`", runway)
        self.assertIn("Remaining time at that check: about 2 days 18 hours 17 minutes", runway)
        self.assertIn("M90 current-day deadline runway refresh: complete", readiness)
        self.assertIn("## M90 Current-Day Deadline Runway Refresh", handoff)
        self.assertIn("M0 through M96 are locally complete", handoff)
        self.assertIn("### M90: Current-Day Deadline Runway Refresh", long_task)

    def test_m91_recording_copy_tracks_m90_package_without_overstating_m88(self):
        from tools.video_rehearsal_gate import build_video_rehearsal_gate

        packet = (
            ROOT / "docs" / "submission" / "video-production-packet.md"
        ).read_text()
        readme = (ROOT / "README.md").read_text()
        review_packet = (
            ROOT / "docs" / "submission" / "review-packet.md"
        ).read_text()
        readiness = (
            ROOT / "docs" / "submission" / "local-readiness-report.md"
        ).read_text()
        public_report = (
            ROOT / "docs" / "submission" / "public-repo-readiness-report.md"
        ).read_text()
        report = (
            ROOT / "docs" / "submission" / "recording-rehearsal-report.md"
        ).read_text()
        handoff_path = ROOT / "docs" / "execution" / "HANDOFF.md"
        long_task_path = ROOT / "docs" / "execution" / "long-task-plan.md"

        payload = build_video_rehearsal_gate(ROOT)
        self.assertEqual("ready_for_recording_gated_upload", payload["status"])

        self.assertIn("Keep public ECS credential-free; do not imply live Qwen runs there", packet)
        self.assertIn("latest bundle is described as the current local package", packet)
        self.assertIn("M98 remains the current evidence snapshot", packet)
        self.assertNotIn("M88 is described as the latest local evidence snapshot", packet)
        self.assertNotIn("M88 remains the product evidence snapshot", packet)
        self.assertNotIn("Keep M88 local bundle versus M65 ECS boundary honest", packet)

        self.assertIn("latest local package", readme)
        self.assertIn("M98 evidence snapshot", readme)
        self.assertIn("M91 recording package wording sync: complete", readiness)
        self.assertIn("M99 current-package wording sync", review_packet)
        self.assertIn("M99 keeps the current-package wording", public_report)
        self.assertIn("M104 prior verified ECS deployment", public_report)
        self.assertIn("recording keeps public ECS credential-free and M104 boundary verified", report)

        if handoff_path.exists() and long_task_path.exists():
            self.assertIn("## M91 Recording Package Wording Sync", handoff_path.read_text())
            self.assertIn("### M91: Recording Package Wording Sync", long_task_path.read_text())

    def test_m92_submission_media_copy_keeps_public_ecs_and_fixture_scope_honest(self):
        from tools.video_rehearsal_gate import build_video_rehearsal_gate

        review_packet = (
            ROOT / "docs" / "submission" / "review-packet.md"
        ).read_text()
        public_report = (
            ROOT / "docs" / "submission" / "public-repo-readiness-report.md"
        ).read_text()
        readiness = (
            ROOT / "docs" / "submission" / "local-readiness-report.md"
        ).read_text()
        video_packet = (
            ROOT / "docs" / "submission" / "video-production-packet.md"
        ).read_text()
        devpost = (
            ROOT / "docs" / "submission" / "devpost-final-copy.md"
        ).read_text()
        fields = (
            ROOT / "docs" / "submission" / "hackathon-fields.md"
        ).read_text()
        blog = (ROOT / "docs" / "submission" / "blog-post-draft.md").read_text()
        handoff_path = ROOT / "docs" / "execution" / "HANDOFF.md"
        long_task_path = ROOT / "docs" / "execution" / "long-task-plan.md"
        payload = build_video_rehearsal_gate(ROOT)

        check_ids = {check["id"] for check in payload["checks"]}
        self.assertIn("submission_copy_consistency", check_ids)
        self.assertEqual("ready_for_recording_gated_upload", payload["status"])

        required_public_ecs_phrases = [
            "Current public ECS deployment: M104 credential-free runtime",
            "Public ECS judge smoke passed after the M104 redeploy",
        ]
        for phrase in required_public_ecs_phrases:
            self.assertIn(phrase, review_packet)
            self.assertIn(phrase, public_report)

        for surface in [review_packet, public_report, readiness, video_packet, devpost, fields]:
            self.assertNotIn(
                "M65 threaded demo runtime from the latest sanitized bundle",
                surface,
            )
            self.assertNotIn(
                "Public ECS judge smoke status matches the latest deployed sanitized bundle",
                surface,
            )

        self.assertIn(
            "retry policy, config loader behavior, cache policy, audit serialization, pagination policy, API-client auth migration, provider auth-header mode, and a source-backed ProjectOdyssey JIT policy scenario",
            " ".join(blog.split()),
        )
        self.assertIn("M92 submission media copy consistency gate: complete", readiness)
        if handoff_path.exists() and long_task_path.exists():
            self.assertIn("## M92 Submission Media Copy Consistency Gate", handoff_path.read_text())
            self.assertIn("### M92: Submission Media Copy Consistency Gate", long_task_path.read_text())

    def test_m93_judge_first_run_command_contract_is_recorded(self):
        review_packet = (
            ROOT / "docs" / "submission" / "review-packet.md"
        ).read_text()
        public_report = (
            ROOT / "docs" / "submission" / "public-repo-readiness-report.md"
        ).read_text()
        readiness = (
            ROOT / "docs" / "submission" / "local-readiness-report.md"
        ).read_text()
        handoff_path = ROOT / "docs" / "execution" / "HANDOFF.md"
        long_task_path = ROOT / "docs" / "execution" / "long-task-plan.md"

        self.assertIn("M93 judge first-run command contract", review_packet)
        self.assertIn("M93 judge first-run command contract: complete", readiness)
        self.assertIn("JUDGE_FIRST_RUN_COMMANDS", readiness)
        self.assertIn("M93 judge first-run command contract", public_report)
        self.assertIn("JUDGE_FIRST_RUN_COMMANDS", public_report)

        if handoff_path.exists() and long_task_path.exists():
            self.assertIn("## M93 Judge First-Run Command Contract", handoff_path.read_text())
            self.assertIn("### M93: Judge First-Run Command Contract", long_task_path.read_text())

    def test_m94_public_release_gate_uses_judge_first_run_command_contract(self):
        from recallpack.submission_bundle import JUDGE_FIRST_RUN_COMMANDS

        release_gate = (
            ROOT / "docs" / "submission" / "public-release-gate.md"
        ).read_text()
        readiness = (
            ROOT / "docs" / "submission" / "local-readiness-report.md"
        ).read_text()
        public_report = (
            ROOT / "docs" / "submission" / "public-repo-readiness-report.md"
        ).read_text()
        review_packet = (
            ROOT / "docs" / "submission" / "review-packet.md"
        ).read_text()
        handoff_path = ROOT / "docs" / "execution" / "HANDOFF.md"
        long_task_path = ROOT / "docs" / "execution" / "long-task-plan.md"

        for command in JUDGE_FIRST_RUN_COMMANDS:
            self.assertIn(command, release_gate)

        self.assertIn("M94 public release gate command contract: complete", readiness)
        self.assertIn("M94 public release gate command contract", public_report)
        self.assertIn("M94 public release gate command contract", review_packet)

        if handoff_path.exists() and long_task_path.exists():
            self.assertIn("## M94 Public Release Gate Command Contract", handoff_path.read_text())
            self.assertIn("### M94: Public Release Gate Command Contract", long_task_path.read_text())

    def test_m95_current_day_release_readiness_refresh_is_recorded(self):
        runway_path = ROOT / "docs" / "execution" / "deadline-runway-plan.md"
        handoff_path = ROOT / "docs" / "execution" / "HANDOFF.md"
        long_task_path = ROOT / "docs" / "execution" / "long-task-plan.md"
        if not handoff_path.exists() or not long_task_path.exists():
            self.skipTest("internal execution docs are excluded from sanitized bundles")

        public_report = (
            ROOT / "docs" / "submission" / "public-repo-readiness-report.md"
        ).read_text()
        readiness = (
            ROOT / "docs" / "submission" / "local-readiness-report.md"
        ).read_text()
        runway = runway_path.read_text()
        handoff = handoff_path.read_text()
        long_task = long_task_path.read_text()

        self.assertIn("Date: 2026-07-07", public_report)
        self.assertIn("Date: 2026-07-09", readiness)
        self.assertNotIn("Date: 2026-07-03", public_report)
        self.assertIn("Sources rechecked on 2026-07-07", runway)
        self.assertIn("Local check: `2026-07-07 10:43 CST`", runway)
        self.assertIn("Remaining time at that check: about 2 days 18 hours 17 minutes", runway)
        self.assertIn("M106 current deadline and remote-sync boundary refresh: complete", readiness)
        self.assertIn("M0 through M96 are locally complete", handoff)
        self.assertIn("## M95 Current-Day Release Readiness Refresh", handoff)
        self.assertIn("### M95: Current-Day Release Readiness Refresh", long_task)

    def test_m96_judge_surfaces_do_not_call_m90_the_current_package(self):
        judge_surface_paths = [
            ROOT / "README.md",
            ROOT / "src" / "recallpack" / "submission_packet.py",
            ROOT / "tools" / "video_rehearsal_gate.py",
            ROOT / "docs" / "submission",
        ]
        stale_current_package_phrases = [
            "current M90 local package",
            "current M90 local",
            "not to the current M90",
            "M90 local package versus M65 ECS",
            "M90 is described as the current local package",
            "Keep M90 local package versus M65 ECS boundary honest",
            "Do not claim the M90 local package is deployed to ECS",
        ]
        offenders = []

        for path in judge_surface_paths:
            files = [path] if path.is_file() else sorted(path.rglob("*.md"))
            for file_path in files:
                text = file_path.read_text()
                for phrase in stale_current_package_phrases:
                    if phrase in text:
                        offenders.append(f"{file_path.relative_to(ROOT)}: {phrase}")

        self.assertEqual([], offenders)

        packet = (
            ROOT / "docs" / "submission" / "video-production-packet.md"
        ).read_text()
        review_packet = (
            ROOT / "docs" / "submission" / "review-packet.md"
        ).read_text()
        readiness = (
            ROOT / "docs" / "submission" / "local-readiness-report.md"
        ).read_text()
        handoff_path = ROOT / "docs" / "execution" / "HANDOFF.md"
        long_task_path = ROOT / "docs" / "execution" / "long-task-plan.md"
        self.assertIn("latest local package", packet)
        self.assertIn("latest local package", review_packet)
        self.assertIn("M96 current-package wording guardrail: complete", readiness)
        if handoff_path.exists() and long_task_path.exists():
            self.assertIn("## M96 Current-Package Wording Guardrail", handoff_path.read_text())
            self.assertIn("### M96: Current-Package Wording Guardrail", long_task_path.read_text())

    def test_m118_judge_surface_opening_uses_product_language_not_milestones(self):
        readme = (ROOT / "README.md").read_text()
        devpost = (
            ROOT / "docs" / "submission" / "devpost-final-copy.md"
        ).read_text()
        script = (
            ROOT / "docs" / "submission" / "demo-video-script.md"
        ).read_text()
        app_js = (ROOT / "web" / "app.js").read_text()
        demo_source = (ROOT / "src" / "recallpack" / "demo.py").read_text()

        readme_opening = readme.split("## Evidence At A Glance", 1)[0]
        self.assertIn("MemoryAgent runtime for coding-agent handoffs", readme_opening)
        self.assertIn("selection happens before the agent reasons", readme_opening)
        self.assertIn("Run the judge smoke", readme_opening)
        self.assertIn("## Limits", readme)
        self.assertNotIn("## What We Do Not Claim", readme)

        devpost_opening = devpost.split("### Challenges", 1)[0]
        self.assertIn("Why coding agents still need RecallPack", devpost_opening)
        self.assertIn("source-backed ProjectOdyssey JIT fixture", devpost_opening)

        script_opening = script.split("## Script", 1)[0]
        self.assertIn("first 20 seconds must show the product problem", script_opening)

        for label, text in [
            ("README opening", readme_opening),
            ("Devpost opening", devpost_opening),
            ("video opening", script_opening),
        ]:
            self.assertIsNone(re.search(r"\bM\d{2,3}\b", text), label)
            self.assertNotIn("live_e2e", text, label)

        self.assertNotIn("M98 rerun", app_js)
        self.assertIn("Fresh live rerun", app_js)
        self.assertNotIn("M117 covers", demo_source)


if __name__ == "__main__":
    unittest.main()
