from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

try:
    from devpost_preflight import build_preflight
except ModuleNotFoundError:
    from tools.devpost_preflight import build_preflight


SCRIPT_ROOT = Path(__file__).resolve().parents[1]

RUN_OF_SHOW_ANCHORS = (
    "0:00-0:20",
    "0:20-0:40",
    "0:40-1:15",
    "1:15-1:30",
    "1:30-2:05",
    "2:05-2:35",
    "2:35-2:45",
)

PACKET_REQUIRED_SNIPPETS = (
    "Recording lock: 2:20-2:45",
    "One-Take Run Of Show",
    "Deterministic stale-memory failure replay",
    "When a fresh coding agent takes over",
    "Write-time lifecycle claim is the headline",
    "Stored live raw-history embedding+rerank baseline traces selected",
    "authored deterministic replay",
    "RecallPack active memory passes 3/3 fixture tests",
    "stored live Qwen provider-path trace completed successfully once",
    "Do not imply the public demo endpoint performs live Qwen calls",
    "the narration implies the local replay is a fresh live Qwen run",
    "Do not imply live raw-history retrieval selected stale memory",
    "Keep public ECS credential-free; do not imply live Qwen runs there",
    "Public ECS is described as the M104 credential-free runtime",
    "latest bundle is described as the current local package",
    "M98 remains the current evidence snapshot",
)

PACKET_FORBIDDEN_SNIPPETS = (
    "M85 is described as the latest local release candidate",
    "M81 is described as the latest local release candidate",
    "M68 is described as the latest local release candidate",
    "M67 is described as the latest local release candidate",
    "Keep M85 local bundle versus M65 ECS boundary honest",
    "Keep M81 local bundle versus M65 ECS boundary honest",
    "Keep M88 local bundle versus M65 ECS boundary honest",
    "Do not claim the M85 local bundle is deployed to ECS",
    "Do not claim the M81 local bundle is deployed to ECS",
    "M88 is described as the latest local evidence snapshot",
    "M88 remains the product evidence snapshot",
    "M88 product evidence snapshot",
    "Do not claim M66 or M67 is deployed to ECS",
    "Keep latest local package versus M65 ECS boundary honest",
    "Public ECS is described as the M65 credential-free runtime",
)

PUBLIC_ECS_REQUIRED_SNIPPETS = (
    "Current public ECS deployment: M104 credential-free runtime",
    "Public ECS judge smoke passed after the M104 redeploy",
)

SUBMISSION_COPY_FORBIDDEN_SNIPPETS = (
    "Current public ECS deployment: M65 credential-free runtime; it is not the latest local package.",
    "Public ECS judge smoke applies to the M65 deployment, not to the latest local package.",
    "latest local package versus M65 ECS",
)


def build_video_rehearsal_gate(root: Path) -> dict[str, Any]:
    root = root.resolve()
    failures: list[str] = []
    checks: list[dict[str, Any]] = []

    preflight = build_preflight(root)
    packet_text = _read_required(
        root / "docs" / "submission" / "video-production-packet.md",
        "video production packet",
        failures,
    )
    readme_text = _read_required(root / "README.md", "README", failures)
    media_text = _read_required(
        root / "docs" / "submission" / "demo-media-package.md",
        "demo media package",
        failures,
    )
    script_text = _read_required(
        root / "docs" / "submission" / "demo-video-script.md",
        "demo video script",
        failures,
    )
    review_packet_text = _read_required(
        root / "docs" / "submission" / "review-packet.md",
        "review packet",
        failures,
    )
    public_report_text = _read_required(
        root / "docs" / "submission" / "public-repo-readiness-report.md",
        "public repo readiness report",
        failures,
    )
    readiness_text = _read_required(
        root / "docs" / "submission" / "local-readiness-report.md",
        "local readiness report",
        failures,
    )
    blog_text = _read_required(
        root / "docs" / "submission" / "blog-post-draft.md",
        "blog post draft",
        failures,
    )
    devpost_text = _read_required(
        root / "docs" / "submission" / "devpost-final-copy.md",
        "Devpost final copy",
        failures,
    )
    fields_text = _read_required(
        root / "docs" / "submission" / "hackathon-fields.md",
        "hackathon fields",
        failures,
    )

    checks.append(_check_run_of_show(packet_text, failures))
    checks.append(_check_recording_claims(packet_text, script_text, failures))
    checks.append(_check_readme_and_media(readme_text, media_text, failures))
    checks.append(_check_screenshots(preflight, failures))
    checks.append(_check_manual_gates(preflight, failures))
    checks.append(_check_public_ecs_boundary(packet_text, failures))
    checks.append(
        _check_submission_copy_consistency(
            packet_text=packet_text,
            review_packet_text=review_packet_text,
            public_report_text=public_report_text,
            readiness_text=readiness_text,
            blog_text=blog_text,
            devpost_text=devpost_text,
            fields_text=fields_text,
            failures=failures,
        )
    )

    if not preflight["ready_local_materials"]:
        failures.extend(preflight["local_failures"])
    if preflight["live_qwen_e2e_status"] != "live_e2e_passed":
        failures.append(
            "live_qwen_e2e_status must be live_e2e_passed before recording"
        )

    recording_ready = not failures
    return {
        "status": (
            "ready_for_recording_gated_upload"
            if recording_ready
            else "failed_recording_rehearsal_gate"
        ),
        "recording_ready": recording_ready,
        "checks": checks,
        "local_failures": failures,
        "sanitized_bundle": preflight["sanitized_bundle"],
        "public_repo_url": preflight["public_repo_url"],
        "live_qwen_e2e_status": preflight["live_qwen_e2e_status"],
        "fresh_m98_live_rerun_status": preflight["fresh_m98_live_rerun_status"],
        "video_candidate": preflight.get("video_candidate", {"status": "missing"}),
        "manual_blockers": preflight["missing_required_manual_items"],
        "gated_actions": preflight["gated_actions"],
        "no_public_action_performed": True,
        "requires_credentials": False,
        "network_calls_made": False,
    }


def render_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# RecallPack M69 Recording Rehearsal Report",
        "",
        f"Status: {payload['status']}",
        f"Recording ready: {str(payload['recording_ready']).lower()}",
        f"Sanitized bundle: {payload['sanitized_bundle']}",
        f"Public repository URL: {payload['public_repo_url'] or 'not recorded'}",
        f"Live Qwen E2E status: {payload['live_qwen_e2e_status']}",
        f"Fresh M98 live rerun status: {payload['fresh_m98_live_rerun_status']}",
        f"Local video candidate: {payload['video_candidate'].get('path', 'not built')}",
        f"Local video candidate upload performed: {str(payload['video_candidate'].get('upload_performed', False)).lower()}",
        "",
        "No public action was performed. This report does not upload video, "
        "create a repository, submit Devpost, read credentials, or call Qwen.",
        "",
        "## Checks",
        "",
    ]
    for check in payload["checks"]:
        lines.append(
            f"- {check['id']}: {check['status']} ({check['summary']})"
        )
    lines.extend(["", "## Manual Blockers", ""])
    lines.extend(f"- {item}" for item in payload["manual_blockers"])
    lines.append("")
    return "\n".join(lines)


def _read_required(path: Path, label: str, failures: list[str]) -> str:
    if not path.is_file():
        failures.append(f"missing {label}: {_display_path(path)}")
        return ""
    return path.read_text(encoding="utf-8")


def _display_path(path: Path) -> str:
    try:
        return path.relative_to(SCRIPT_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def _check_run_of_show(text: str, failures: list[str]) -> dict[str, Any]:
    missing = [anchor for anchor in RUN_OF_SHOW_ANCHORS if anchor not in text]
    if missing:
        failures.append(f"missing run-of-show anchors: {', '.join(missing)}")
    return {
        "id": "run_of_show_anchors",
        "status": "failed" if missing else "passed",
        "summary": "2:20-2:45 timeline anchors present",
    }


def _check_recording_claims(
    packet_text: str, script_text: str, failures: list[str]
) -> dict[str, Any]:
    missing = [
        snippet for snippet in PACKET_REQUIRED_SNIPPETS if snippet not in packet_text
    ]
    forbidden = [
        snippet for snippet in PACKET_FORBIDDEN_SNIPPETS if snippet in packet_text
    ]
    if "wrong patch" not in script_text:
        missing.append("demo video script says wrong patch")
    if missing:
        failures.append(f"missing recording guardrails: {', '.join(missing)}")
    if forbidden:
        failures.append(f"stale recording guardrails present: {', '.join(forbidden)}")
    return {
        "id": "recording_claim_guardrails",
        "status": "failed" if missing or forbidden else "passed",
        "summary": "baseline 1/3, RecallPack 3/3, Qwen, and ECS wording guarded",
    }


def _check_readme_and_media(
    readme_text: str, media_text: str, failures: list[str]
) -> dict[str, Any]:
    required = (
        "tools/video_rehearsal_gate.py",
        "docs/submission/recording-rehearsal-report.md",
    )
    missing = [snippet for snippet in required if snippet not in readme_text]
    if "docs/submission/video-production-packet.md" not in media_text:
        missing.append("demo media package links video production packet")
    if missing:
        failures.append(f"missing rehearsal references: {', '.join(missing)}")
    return {
        "id": "readme_and_media_links",
        "status": "failed" if missing else "passed",
        "summary": "recording gate and packet are discoverable",
    }


def _check_screenshots(
    preflight: dict[str, Any], failures: list[str]
) -> dict[str, Any]:
    assets = preflight["media_assets"]
    if len(assets) != 3:
        failures.append("expected three screenshot assets for Devpost gallery")
    too_small = [
        asset["filename"]
        for asset in assets
        if asset["width"] < 1200 or asset["height"] < 700
    ]
    if too_small:
        failures.append(f"screenshot assets too small: {', '.join(too_small)}")
    return {
        "id": "screenshot_assets",
        "status": "failed" if len(assets) != 3 or too_small else "passed",
        "summary": "three 1280x720-class screenshots are staged",
    }


def _check_manual_gates(
    preflight: dict[str, Any], failures: list[str]
) -> dict[str, Any]:
    required = {
        "final video URL or upload",
        "final Devpost submit approval",
        "final media order confirmation",
    }
    if not preflight.get("public_repo_url"):
        required.add("public GitHub repository URL")
    blockers = set(preflight["missing_required_manual_items"])
    missing = sorted(required - blockers)
    if missing:
        failures.append(f"missing manual blocker labels: {', '.join(missing)}")
    return {
        "id": "manual_upload_gates",
        "status": "failed" if missing else "passed",
        "summary": "video upload, media order, and final submit remain gated",
    }


def _check_public_ecs_boundary(text: str, failures: list[str]) -> dict[str, Any]:
    required = (
        "Keep public ECS credential-free; do not imply live Qwen runs there",
        "Public ECS is described as the M104 credential-free runtime",
    )
    missing = [snippet for snippet in required if snippet not in text]
    if missing:
        failures.append(f"missing public ECS boundary wording: {', '.join(missing)}")
    return {
        "id": "public_ecs_boundary",
        "status": "failed" if missing else "passed",
        "summary": "recording keeps public ECS credential-free and M104 boundary verified",
    }


def _check_submission_copy_consistency(
    *,
    packet_text: str,
    review_packet_text: str,
    public_report_text: str,
    readiness_text: str,
    blog_text: str,
    devpost_text: str,
    fields_text: str,
    failures: list[str],
) -> dict[str, Any]:
    missing: list[str] = []
    forbidden: list[str] = []

    for label, text in {
        "review packet": review_packet_text,
        "public repo readiness report": public_report_text,
    }.items():
        normalized_text = _normalize_whitespace(text)
        for snippet in PUBLIC_ECS_REQUIRED_SNIPPETS:
            if _normalize_whitespace(snippet) not in normalized_text:
                missing.append(f"{label}: {snippet}")

    if "M92 submission media copy consistency gate: complete" not in readiness_text:
        missing.append(
            "local readiness report: M92 submission media copy consistency gate"
        )
    if "latest bundle is described as the current local package" not in packet_text:
        missing.append(
            "video production packet: latest local package wording guardrail"
        )
    if "M98 remains the current evidence snapshot" not in packet_text:
        missing.append("video production packet: M98 evidence snapshot guardrail")
    normalized_blog = _normalize_whitespace(blog_text)
    if (
        "retry policy, config loader behavior, cache policy, audit serialization, pagination policy, API-client auth migration, provider auth-header mode, and a source-backed ProjectOdyssey JIT policy scenario"
        not in normalized_blog
    ):
        missing.append("blog post draft: eight fixture categories including ProjectOdyssey JIT")

    for label, text in {
        "video production packet": packet_text,
        "review packet": review_packet_text,
        "public repo readiness report": public_report_text,
        "local readiness report": readiness_text,
        "Devpost final copy": devpost_text,
        "hackathon fields": fields_text,
    }.items():
        for snippet in SUBMISSION_COPY_FORBIDDEN_SNIPPETS:
            if snippet in text:
                forbidden.append(f"{label}: {snippet}")

    if missing:
        failures.append(f"missing submission copy consistency: {', '.join(missing)}")
    if forbidden:
        failures.append(f"stale public ECS submission copy present: {', '.join(forbidden)}")

    return {
        "id": "submission_copy_consistency",
        "status": "failed" if missing or forbidden else "passed",
        "summary": "submission/video copy keeps latest local package, M98 snapshot, and M104 ECS boundaries aligned",
    }


def _normalize_whitespace(text: str) -> str:
    return " ".join(text.split())


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the local-only RecallPack recording rehearsal gate."
    )
    parser.add_argument(
        "--root",
        default=str(SCRIPT_ROOT),
        help="Repository or sanitized bundle root to inspect.",
    )
    parser.add_argument("--json-out", help="Optional path to write JSON report.")
    parser.add_argument(
        "--markdown-out", help="Optional path to write Markdown report."
    )
    args = parser.parse_args()

    payload = build_video_rehearsal_gate(Path(args.root))
    output = json.dumps(payload, indent=2, sort_keys=True)
    if args.json_out:
        Path(args.json_out).write_text(output + "\n", encoding="utf-8")
    if args.markdown_out:
        Path(args.markdown_out).write_text(
            render_markdown(payload), encoding="utf-8"
        )
    print(output)
    return 0 if payload["recording_ready"] else 1


if __name__ == "__main__":
    sys.exit(main())
