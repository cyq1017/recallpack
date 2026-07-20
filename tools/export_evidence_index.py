from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

try:
    from export_devpost_materials import build_materials
except ModuleNotFoundError:
    from tools.export_devpost_materials import build_materials


def build_evidence_index(root: Path) -> dict[str, Any]:
    materials = build_materials(root)
    return {
        "status": "local_evidence_ready_gated_submission",
        "project_name": materials["project_name"],
        "track": materials["track"],
        "claims": _claims(
            materials["live_qwen_e2e_status"],
            materials["fresh_m98_live_rerun_status"],
            materials["repository_url"],
            materials.get("devpost_upload_state", {}),
        ),
        "manual_blockers": materials["manual_blockers"],
        "gated_actions": materials["gated_actions"],
        "public_repo_url": materials["repository_url"],
        "live_qwen_e2e_status": materials["live_qwen_e2e_status"],
        "fresh_m98_live_rerun_status": materials["fresh_m98_live_rerun_status"],
        "verification": materials["verification"],
        "no_public_action_performed": materials["no_public_action_performed"],
        "requires_credentials": materials["requires_credentials"],
        "network_calls_made": materials["network_calls_made"],
    }


def render_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# RecallPack Submission Evidence Index",
        "",
        "Claim-To-Evidence Index for local review and external audit.",
        "This export performs no public action; it records checked-in evidence.",
        "",
        f"Status: {payload['status']}",
        f"Live Qwen E2E status: {payload['live_qwen_e2e_status']}",
        f"Fresh M98 live rerun status: {payload['fresh_m98_live_rerun_status']}",
        f"Public repository URL: {payload['public_repo_url'] or 'not recorded'}",
        "",
        "## Claim-To-Evidence Index",
        "",
    ]
    for claim in payload["claims"]:
        lines.extend(
            [
                f"### {claim['id']}",
                "",
                f"Claim: {claim['claim']}",
                f"Status: {claim['claim_status']}",
                f"Risk level: {claim['risk_level']}",
                f"Evidence summary: {claim['evidence_summary']}",
                "",
                "Evidence files:",
                "",
            ]
        )
        lines.extend(f"- `{path}`" for path in claim["evidence_files"])
        lines.extend(["", "Verification commands:", ""])
        lines.extend(f"- `{command}`" for command in claim["verification_commands"])
        lines.append("")
    lines.extend(["## Remaining Manual Blockers", ""])
    lines.extend(f"- {item}" for item in payload["manual_blockers"])
    lines.append("")
    return "\n".join(lines)


def _claims(
    live_qwen_e2e_status: str,
    fresh_m98_live_rerun_status: str,
    public_repo_url: str | None,
    devpost_upload_state: dict[str, Any],
) -> list[dict[str, Any]]:
    verify_all = "PYTHONPATH=src python3 -m unittest discover -s tests -v"
    live_e2e_passed = live_qwen_e2e_status == "live_e2e_passed"
    public_repo_published = bool(public_repo_url)
    required_uploads_done = (
        devpost_upload_state.get("status") == "additional_info_media_uploaded"
        and devpost_upload_state.get("final_submit_performed") is False
    )
    return [
        {
            "id": "memoryagent_positioning",
            "claim": "RecallPack is a MemoryAgent project for stale-aware coding-agent handoffs.",
            "claim_status": "local_proven",
            "risk_level": "low",
            "evidence_summary": "README, Devpost copy, and demo payload align on MemoryAgent positioning.",
            "evidence_files": [
                "README.md",
                "docs/submission/devpost-final-copy.md",
                "docs/submission/review-packet.md",
            ],
            "verification_commands": [verify_all, "python3 tools/export_devpost_materials.py"],
        },
        {
            "id": "downstream_stale_handoff_proof",
            "claim": "Deterministic local stale-context replay illustrates the stale-handoff failure class while RecallPack active memory passes fixture tests.",
            "claim_status": "local_proven",
            "risk_level": "medium",
            "evidence_summary": "Under one strict downstream contract, project-a/b/f/g/h baseline runs produce stale patches and score 1/3; project-c/d/e baselines are rejected as empty_patch and score 0/3; RecallPack scores 3/3 across all eight curated lifecycle regression fixtures. The suite includes one non-isomorphic pagination fixture, one realistic API-client auth migration fixture, one source-backed AI provider auth-header fixture, and one source-backed ProjectOdyssey JIT policy fixture with an unrigged keyword-provider baseline. This is an authored deterministic mechanism demonstration, not a broad benchmark, live embedding benchmark, or live failure-rate measurement.",
            "evidence_files": [
                "fixtures/project-a/",
                "fixtures/project-b/",
                "fixtures/project-c/",
                "fixtures/project-d/",
                "fixtures/project-e/",
                "fixtures/project-f-realistic/",
                "fixtures/project-g-auth-mode/",
                "fixtures/project-h-projectodyssey-jit/",
                "tests/test_hero_evaluation.py",
                "docs/submission/review-packet.md",
            ],
            "verification_commands": [verify_all, "python3 tools/judge_smoke.py --url http://127.0.0.1:8789"],
        },
        {
            "id": "qwen_provider_integration",
            "claim": (
                "Qwen text, embedding, rerank, and gated patch-generation "
                "contracts are represented and reviewable."
            ),
            "claim_status": "local_proven",
            "risk_level": "medium",
            "evidence_summary": (
                "Sanitized provider traces cover memory_decision, "
                "text-embedding-v4, and qwen3-rerank without credentials; "
                "one stored live provider-path trace reaches patch_generation=2. "
                "M98 credential-free preflight now covers the unrigged "
                "raw-history baseline path with request_role_counts "
                "memory_decision=12 embedding=16 rerank=2 patch_generation=2 "
                "and M119 adds a credential-free ProjectOdyssey live E2E "
                "preflight over the source-backed JIT scenario; M120 then runs "
                "the ProjectOdyssey live provider path and records a passing "
                "source-backed fixture E2E with required sources selected, stale "
                "sources excluded, and RecallPack downstream patch generation "
                "passing 3/3; "
                "the fresh M98 live rerun is recorded separately. "
                "The credential-free local demo still uses deterministic fake "
                "providers and a deterministic context-keyed patch provider."
            ),
            "evidence_files": [
                "src/recallpack/providers.py",
                "src/recallpack/downstream.py",
                "src/recallpack/live_qwen_embedding_baseline.py",
                "tests/test_providers.py",
                "tests/test_qwen_live_e2e.py",
                "tests/test_qwen_live_embedding_baseline.py",
                "docs/submission/live-qwen-trace.json",
                "docs/submission/live-qwen-e2e-preflight.json",
                "docs/submission/projectodyssey-live-qwen-e2e-preflight.json",
                "docs/submission/projectodyssey-live-qwen-e2e-trace.json",
                "docs/submission/live-qwen-m98-rerun-trace.json",
                "docs/submission/live-qwen-m98-embedding-baseline-trace.json",
                "docs/submission/live-qwen-embedding-baseline-preflight.json",
                "docs/submission/review-packet.md",
            ],
            "verification_commands": [
                verify_all,
                "PYTHONPATH=src python3 tools/build_live_qwen_e2e_preflight.py",
                "RECALLPACK_LIVE_QWEN_E2E_FIXTURE=fixtures/project-h-projectodyssey-jit RECALLPACK_LIVE_QWEN_E2E_PREFLIGHT_PATH=docs/submission/projectodyssey-live-qwen-e2e-preflight.json PYTHONPATH=src python3 tools/build_live_qwen_e2e_preflight.py",
                "PYTHONPATH=src python3 tools/build_live_qwen_embedding_baseline_preflight.py",
            ],
        },
        {
            "id": "live_qwen_e2e_boundary",
            "claim": (
                "Live Qwen observe/compile/patch-generation provider path has "
                "one stored sanitized integration pass, one failed M98 rerun, "
                "and one passing ProjectOdyssey live run; lifecycle filtering "
                "held in the live provider path while broad live failure-rate "
                "measurement remains out of scope."
            ),
            "claim_status": "gated_boundary",
            "risk_level": "medium" if live_e2e_passed else "high",
            "evidence_summary": (
                "Live E2E: one historical pass, one failed M98 rerun, and one "
                "passing ProjectOdyssey run. Lifecycle checks held in stored "
                "live runs, and ProjectOdyssey live Qwen selected required "
                "active sources while excluding the stale policy; RecallPack "
                "live-generated patch generation passed 3/3 ProjectOdyssey "
                "fixture tests. Stored live "
                "raw-history embedding+rerank baseline traces selected the "
                "active retry decision instead of the stale retry decision, so "
                "the project claim is structural stale exclusion rather than a "
                "measured live baseline failure rate."
                if live_e2e_passed
                else (
                    "Stored live observe/compile trace is not passing; do not "
                    "claim a passing live E2E without rerunning the gated command."
                )
            ),
            "evidence_files": [
                "tools/run_live_qwen_e2e.py",
                "docs/submission/live-qwen-e2e-trace.json",
                "docs/submission/live-qwen-m98-rerun-trace.json",
                "docs/submission/live-qwen-m98-embedding-baseline-trace.json",
                "docs/submission/projectodyssey-live-qwen-e2e-trace.json",
                "docs/submission/live-qwen-e2e-preflight.json",
                "docs/submission/gated-action-runbook.md",
            ],
            "verification_commands": [verify_all, "PYTHONPATH=src python3 tools/build_live_qwen_e2e_preflight.py"],
        },
        {
            "id": "public_repo_boundary",
            "claim": (
                "The public repository URL is recorded, and the judging surface is the sanitized bundle rather than the raw workspace."
                if public_repo_published
                else "The public repository should be created from the sanitized bundle, not the raw workspace."
            ),
            "claim_status": "local_proven" if public_repo_published else "gated_boundary",
            "risk_level": "medium" if public_repo_published else "medium",
            "evidence_summary": (
                f"Public repo URL is recorded: {public_repo_url}. Local preflight validates the current sanitized bundle and its fresh-clone commands, but does not prove the remote repository contains the latest bundle. Bundle scans report zero local path, secret, generated, or internal hits. Run `PYTHONPATH=src python3 tools/fresh_clone_smoke.py --source . --full` from a fresh public clone to verify the current remote HEAD."
                if public_repo_published
                else "Fresh-clone smoke validates the sanitized bundle and scan reports zero local path, secret, generated, or internal hits."
            ),
            "evidence_files": [
                "tools/build_submission_bundle.py",
                "tools/fresh_clone_smoke.py",
                "docs/submission/public-release-gate.md",
                "docs/submission/public-repo-readiness-report.md",
                "docs/submission/evidence-index.md",
            ],
            "verification_commands": [
                "PYTHONPATH=src python3 tools/fresh_clone_smoke.py --source .",
                "PYTHONPATH=src python3 tools/fresh_clone_smoke.py --source . --full",
            ],
        },
        {
            "id": "devpost_media_readiness",
            "claim": (
                "Devpost copy, screenshots, required file uploads, and a local "
                "video candidate are prepared; video URL/upload and final "
                "submission remain manual."
            ),
            "claim_status": "gated_boundary",
            "risk_level": "medium" if required_uploads_done else "high",
            "evidence_summary": (
                "Three current 1280x720 M71 replay screenshot candidates, the "
                "Devpost architecture diagram, the redacted Alibaba Cloud "
                "deployment proof PNG, and a 156-second local MP4 candidate are "
                "staged. Required Devpost image uploads are recorded as complete "
                "with privacy checks; final video URL/upload and final Devpost "
                "submit remain blockers."
                if required_uploads_done
                else (
                    "Three current 1280x720 M71 replay screenshot candidates, "
                    "the Devpost architecture diagram, the redacted Alibaba Cloud "
                    "deployment proof PNG, and a 156-second local MP4 candidate "
                    "are staged; required Devpost image upload status is not "
                    "recorded as complete."
                )
            ),
            "evidence_files": [
                "docs/submission/devpost-materials.json",
                "docs/submission/devpost-materials.md",
                "docs/submission/devpost-upload-state.json",
                "docs/submission/media/m71-replay/",
                "docs/submission/media/architecture-diagram.png",
                "docs/submission/media/alibaba-cloud-deployment-proof-redacted.png",
                "docs/submission/media/video-candidate/",
                "docs/submission/demo-media-package.md",
                "docs/submission/video-production-packet.md",
                "docs/submission/recording-rehearsal-report.md",
            ],
            "verification_commands": [
                "python3 tools/devpost_preflight.py",
                "python3 tools/export_devpost_materials.py",
                "python3 tools/video_rehearsal_gate.py",
            ],
        },
    ]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Export local-only RecallPack claim-to-evidence index."
    )
    parser.add_argument(
        "--root",
        default=str(Path(__file__).resolve().parents[1]),
        help="Repository or sanitized bundle root to inspect.",
    )
    parser.add_argument("--json-out", help="Optional path to write JSON export.")
    parser.add_argument("--markdown-out", help="Optional path to write Markdown export.")
    args = parser.parse_args()

    payload = build_evidence_index(Path(args.root))
    output = json.dumps(payload, indent=2, sort_keys=True)
    if args.json_out:
        Path(args.json_out).write_text(output + "\n", encoding="utf-8")
    if args.markdown_out:
        Path(args.markdown_out).write_text(render_markdown(payload), encoding="utf-8")
    print(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
