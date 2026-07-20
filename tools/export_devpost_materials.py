from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
from typing import Any

try:
    from devpost_preflight import build_preflight
except ModuleNotFoundError:
    from tools.devpost_preflight import build_preflight


def build_materials(root: Path) -> dict[str, Any]:
    root = root.resolve()
    devpost = _read(root, "docs/submission/devpost-final-copy.md")
    fields = _read(root, "docs/submission/hackathon-fields.md")
    readiness = _read(root, "docs/submission/local-readiness-report.md")
    preflight = build_preflight(root)

    project_name = _field(fields, "Project name")
    track = _field(fields, "Track")
    tagline = _field(fields, "Tagline")
    built_with = _bullet_list(_section(devpost, "Built With"))

    return {
        "status": preflight["status"],
        "project_name": project_name,
        "track": track,
        "tagline": tagline,
        "short_description": _section(fields, "Short Description"),
        "elevator_pitch": _section(devpost, "Elevator Pitch"),
        "project_story": _section(devpost, "Project Story"),
        "built_with": built_with,
        "ai_tools_used": _section(devpost, "Which AI tools Have You Leveraged?"),
        "media_assets": preflight["media_assets"],
        "required_upload_candidates": preflight["required_upload_candidates"],
        "presentation_deck": preflight["presentation_deck"],
        "devpost_upload_state": preflight["devpost_upload_state"],
        "video_candidate": preflight["video_candidate"],
        "manual_blockers": preflight["missing_required_manual_items"],
        "gated_actions": preflight["gated_actions"],
        "repository_url": preflight["public_repo_url"],
        "repository_url_required": not bool(preflight["public_repo_url"]),
        "video_url_required": "final video URL or upload"
        in preflight["missing_required_manual_items"],
        "live_qwen_e2e_status": preflight["live_qwen_e2e_status"],
        "fresh_m98_live_rerun_status": preflight["fresh_m98_live_rerun_status"],
        "verification": {
            "unit_tests": _unit_test_count(readiness),
            "sanitized_bundle": preflight["sanitized_bundle"],
            "preflight_status": preflight["status"],
        },
        "copy_sources": {
            "elevator_pitch": "docs/submission/devpost-final-copy.md#elevator-pitch",
            "project_story": "docs/submission/devpost-final-copy.md#project-story",
            "built_with": "docs/submission/devpost-final-copy.md#built-with",
            "ai_tools_used": (
                "docs/submission/devpost-final-copy.md#which-ai-tools-have-you-leveraged"
            ),
            "short_description": "docs/submission/hackathon-fields.md#short-description",
            "local_evidence": "docs/submission/hackathon-fields.md#local-evidence",
        },
        "no_public_action_performed": preflight["no_public_action_performed"],
        "requires_credentials": preflight["requires_credentials"],
        "network_calls_made": preflight["network_calls_made"],
    }


def render_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# RecallPack Devpost Materials Export",
        "",
        "Local-only export for manual Devpost copy/paste.",
        "This export does not perform public actions; it records any known prior manual uploads.",
        "",
        f"Status: {payload['status']}",
        f"Project name: {payload['project_name']}",
        f"Track: {payload['track']}",
        f"Tagline: {payload['tagline']}",
        "",
        "## Elevator Pitch",
        "",
        payload["elevator_pitch"],
        "",
        "## Short Description",
        "",
        payload["short_description"],
        "",
        "## Built With",
        "",
    ]
    lines.extend(f"- {item}" for item in payload["built_with"])
    lines.extend(
        [
            "",
            "## Which AI Tools",
            "",
            payload["ai_tools_used"],
            "",
            "## Media Assets",
            "",
        ]
    )
    lines.extend(
        (
            f"- {asset['filename']} ({asset['width']}x{asset['height']}, "
            f"{asset['bytes']} bytes) - {asset['path']}"
        )
        for asset in payload["media_assets"]
    )
    lines.extend(
        [
            "",
            "## Required Devpost File Upload Candidates",
            "",
        ]
    )
    lines.extend(
        (
            f"- {asset['filename']} ({asset['width']}x{asset['height']}, "
            f"{asset['bytes']} bytes, upload_performed="
            f"{str(asset.get('upload_performed')).lower()}, privacy_checked="
            f"{str(asset.get('privacy_checked')).lower()}) - {asset['path']}"
        )
        for asset in payload["required_upload_candidates"]
    )
    upload_state = payload.get("devpost_upload_state", {})
    lines.extend(
        [
            "",
            "## Known Devpost Upload State",
            "",
            f"- Status: {upload_state.get('status', 'unknown')}",
            f"- Final submit performed: {str(upload_state.get('final_submit_performed')).lower()}",
        ]
    )
    for item in upload_state.get("uploads", []):
        if not isinstance(item, dict):
            continue
        upload_label = "Uploaded" if item.get("upload_performed") else "Not uploaded"
        lines.append(
            f"- {upload_label}: {item.get('filename')} -> {item.get('field')} "
            f"(privacy_checked={str(item.get('privacy_checked')).lower()}, "
            f"redacted={str(item.get('redacted', False)).lower()})"
        )
    candidate = payload["video_candidate"]
    lines.extend(
        [
            "",
            "## Local Video Candidate",
            "",
            f"- Status: {candidate['status']}",
            f"- Path: {candidate['path']}",
            f"- Duration seconds: {candidate.get('duration_seconds', 'unknown')}",
            f"- Upload performed: {str(candidate.get('upload_performed')).lower()}",
            f"- Devpost video URL: {candidate.get('devpost_video_url') or 'not recorded'}",
        ]
    )
    deck = payload["presentation_deck"]
    lines.extend(
        [
            "",
            "## Presentation PPT",
            "",
            f"- Status: {deck['status']}",
            f"- Path: {deck['path']}",
            f"- Slides: {deck.get('slide_count', 'unknown')}",
            f"- Upload performed: {str(deck.get('upload_performed')).lower()}",
            f"- Privacy checked: {str(deck.get('privacy_checked')).lower()}",
        ]
    )
    lines.extend(
        [
            "",
            "## Remaining Manual Items",
            "",
        ]
    )
    lines.extend(f"- {item}" for item in payload["manual_blockers"])
    lines.extend(
        [
            "",
            "## Repository URL",
            "",
            payload["repository_url"] or "not recorded",
            "",
            "## Verification",
            "",
            f"- Unit tests recorded in readiness report: {payload['verification']['unit_tests']}",
            f"- Sanitized bundle: {payload['verification']['sanitized_bundle']}",
            f"- Live Qwen E2E status: {payload['live_qwen_e2e_status']}",
            f"- Fresh M98 live rerun status: {payload['fresh_m98_live_rerun_status']}",
            f"- Requires credentials: {str(payload['requires_credentials']).lower()}",
            f"- Network calls made: {str(payload['network_calls_made']).lower()}",
            "",
        ]
    )
    return "\n".join(lines)


def _read(root: Path, relative: str) -> str:
    return (root / relative).read_text(encoding="utf-8")


def _field(text: str, name: str) -> str:
    match = re.search(rf"^{re.escape(name)}:\s*(.+)$", text, re.MULTILINE)
    if not match:
        raise ValueError(f"Missing field: {name}")
    return match.group(1).strip()


def _section(text: str, heading: str) -> str:
    pattern = re.compile(
        rf"^## {re.escape(heading)}\s*$\n(?P<body>.*?)(?=^## |\Z)",
        re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(text)
    if not match:
        raise ValueError(f"Missing section: {heading}")
    return match.group("body").strip()


def _bullet_list(text: str) -> list[str]:
    return [
        line.removeprefix("- ").strip().replace("`", "")
        for line in text.splitlines()
        if line.startswith("- ")
    ]


def _unit_test_count(text: str) -> int:
    matches = re.findall(r"Unit test suite:\s*([0-9]+) tests", text)
    if not matches:
        return 0
    return int(matches[-1])


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Export local-only RecallPack Devpost copy/paste materials."
    )
    parser.add_argument(
        "--root",
        default=str(Path(__file__).resolve().parents[1]),
        help="Repository or sanitized bundle root to inspect.",
    )
    parser.add_argument("--json-out", help="Optional path to write JSON export.")
    parser.add_argument("--markdown-out", help="Optional path to write Markdown export.")
    args = parser.parse_args()

    payload = build_materials(Path(args.root))
    output = json.dumps(payload, indent=2, sort_keys=True)
    if args.json_out:
        Path(args.json_out).write_text(output + "\n", encoding="utf-8")
    if args.markdown_out:
        Path(args.markdown_out).write_text(render_markdown(payload), encoding="utf-8")
    print(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
