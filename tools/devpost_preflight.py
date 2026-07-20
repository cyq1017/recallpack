from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import struct
import sys
from typing import Any
import zipfile


SCREENSHOTS = (
    "m71-replay/01-one-click-stale-memory-replay.png",
    "m71-replay/02-recallpack-active-memory-pack.png",
    "m71-replay/03-qwen-provider-evidence.png",
)
REQUIRED_UPLOAD_CANDIDATES = (
    "architecture-diagram.png",
    "alibaba-cloud-deployment-proof-redacted.png",
)
DEVPOST_UPLOAD_STATE = "docs/submission/devpost-upload-state.json"
VIDEO_CANDIDATE_MANIFEST = "docs/submission/media/video-candidate/manifest.json"
VIDEO_CANDIDATE_MP4 = "docs/submission/media/video-candidate/recallpack-demo-candidate.mp4"
PRESENTATION_DECK_PPTX = "docs/submission/media/recallpack-judge-deck.pptx"

REQUIRED_FILES = (
    "README.md",
    "LICENSE",
    ".gitignore",
    "docs/submission/devpost-final-copy.md",
    "docs/submission/demo-media-package.md",
    "docs/submission/demo-video-script.md",
    "docs/submission/video-production-packet.md",
    PRESENTATION_DECK_PPTX,
    "docs/submission/recording-rehearsal-report.md",
    "docs/submission/final-judge-rehearsal.md",
    "docs/submission/public-release-gate.md",
    "docs/submission/public-repo-readiness-report.md",
    DEVPOST_UPLOAD_STATE,
    "docs/submission/review-packet.md",
    "docs/submission/local-readiness-report.md",
    "docs/submission/live-qwen-e2e-trace.json",
    "docs/submission/live-qwen-m98-rerun-trace.json",
    "deploy/alibaba-cloud/Dockerfile",
)

PUBLIC_REPO_MANUAL_ITEM = "public GitHub repository URL"
FRESH_M98_MANUAL_ITEM = "fresh M98 live Qwen rerun approval/result"
REQUIRED_UPLOAD_MANUAL_ITEM = (
    "required Devpost architecture and Alibaba Cloud proof file upload"
)

BASE_MANUAL_ITEMS = (
    "final presentation PPT upload or link",
    "final video URL or upload",
    "final Devpost submit approval",
    "final media order confirmation",
)

BASE_GATED_ACTIONS = (
    "presentation_upload",
    "devpost_submission",
    "video_upload",
)

BUNDLE_PATTERN = re.compile(r"dist/recallpack-submission-[0-9]{8}-[0-9]{6}/?")


def build_preflight(root: Path) -> dict[str, Any]:
    root = root.resolve()
    local_failures: list[str] = []
    checked_files: list[str] = []

    for relative in REQUIRED_FILES:
        path = root / relative
        if path.is_file():
            checked_files.append(relative)
        else:
            local_failures.append(f"missing required file: {relative}")

    media_assets = _media_assets(root, local_failures)
    upload_state = _devpost_upload_state(root, local_failures)
    upload_candidates = _required_upload_candidates(root, local_failures, upload_state)
    presentation_deck = _presentation_deck(root, upload_state, local_failures)
    video_candidate = _video_candidate(root, local_failures)
    if video_candidate["status"] == "built":
        checked_files.extend([VIDEO_CANDIDATE_MANIFEST, VIDEO_CANDIDATE_MP4])
    checked_files.extend(candidate["path"] for candidate in upload_candidates)
    bundle_path = _bundle_path(root)
    bundle_label = _display_bundle_path(root, bundle_path)
    if not _bundle_is_available(root, bundle_path):
        local_failures.append(f"missing sanitized bundle: {bundle_label}")
    elif bundle_label != ".":
        checked_files.append(f"{bundle_label.rstrip('/')}/SUBMISSION_MANIFEST.md")
    else:
        checked_files.append("SUBMISSION_MANIFEST.md")

    live_status = _live_qwen_e2e_status(root / "docs" / "submission" / "live-qwen-e2e-trace.json")
    fresh_m98_status = _live_qwen_e2e_status(
        root / "docs" / "submission" / "live-qwen-m98-rerun-trace.json"
    )
    public_repo_url = _public_repo_url(root)
    manual_items = list(BASE_MANUAL_ITEMS)
    gated_actions = list(BASE_GATED_ACTIONS)
    if any(not candidate.get("upload_performed") for candidate in upload_candidates):
        manual_items.insert(0, REQUIRED_UPLOAD_MANUAL_ITEM)
        gated_actions.insert(0, "required_file_upload")
    if not public_repo_url:
        manual_items.insert(0, PUBLIC_REPO_MANUAL_ITEM)
        gated_actions.insert(0, "public_repo_push")
    if fresh_m98_status in {"not_found", "invalid_json", "unknown"}:
        manual_items.insert(1, FRESH_M98_MANUAL_ITEM)
        gated_actions.insert(1, "live_qwen_e2e_rerun")
    ready_local_materials = not local_failures
    status = "blocked_gated_actions" if ready_local_materials else "local_materials_incomplete"

    return {
        "status": status,
        "ready_local_materials": ready_local_materials,
        "checked_files": sorted(set(checked_files)),
        "media_assets": media_assets,
        "required_upload_candidates": upload_candidates,
        "presentation_deck": presentation_deck,
        "devpost_upload_state": upload_state,
        "video_candidate": video_candidate,
        "missing_required_manual_items": manual_items,
        "gated_actions": gated_actions,
        "live_qwen_e2e_status": live_status,
        "fresh_m98_live_rerun_status": fresh_m98_status,
        "public_repo_url": public_repo_url,
        "sanitized_bundle": bundle_label,
        "no_public_action_performed": True,
        "requires_credentials": False,
        "network_calls_made": False,
        "local_failures": local_failures,
    }


def _media_assets(root: Path, local_failures: list[str]) -> list[dict[str, Any]]:
    assets: list[dict[str, Any]] = []
    media_root = root / "docs" / "submission" / "media"
    for relative in SCREENSHOTS:
        path = media_root / relative
        filename = path.name
        asset_path = f"docs/submission/media/{relative}"
        if not path.is_file():
            local_failures.append(f"missing media asset: {asset_path}")
            continue
        try:
            width, height = _png_size(path)
        except ValueError as exc:
            local_failures.append(str(exc))
            continue
        size = path.stat().st_size
        if width < 1200 or height < 700:
            local_failures.append(
                f"media asset too small: {filename} is {width}x{height}"
            )
        if size <= 20_000:
            local_failures.append(f"media asset too small on disk: {filename}")
        assets.append(
            {
                "filename": filename,
                "path": asset_path,
                "width": width,
                "height": height,
                "bytes": size,
            }
        )
    return assets


def _required_upload_candidates(
    root: Path,
    local_failures: list[str],
    upload_state: dict[str, Any],
) -> list[dict[str, Any]]:
    assets: list[dict[str, Any]] = []
    media_root = root / "docs" / "submission" / "media"
    uploaded_by_path = {
        str(item.get("path")): item
        for item in upload_state.get("uploads", [])
        if isinstance(item, dict)
    }
    for relative in REQUIRED_UPLOAD_CANDIDATES:
        path = media_root / relative
        asset_path = f"docs/submission/media/{relative}"
        if not path.is_file():
            local_failures.append(f"missing required Devpost upload candidate: {asset_path}")
            continue
        try:
            width, height = _png_size(path)
        except ValueError as exc:
            local_failures.append(str(exc))
            continue
        size = path.stat().st_size
        if width < 1200 or height < 700:
            local_failures.append(
                f"required Devpost upload candidate too small: {relative} is {width}x{height}"
            )
        if size <= 20_000:
            local_failures.append(f"required Devpost upload candidate too small on disk: {relative}")
        uploaded = uploaded_by_path.get(asset_path, {})
        upload_performed = bool(uploaded.get("upload_performed"))
        privacy_checked = bool(uploaded.get("privacy_checked"))
        if upload_performed and not privacy_checked:
            local_failures.append(f"uploaded Devpost file lacks privacy check: {asset_path}")
        assets.append(
            {
                "filename": relative,
                "path": asset_path,
                "width": width,
                "height": height,
                "bytes": size,
                "upload_performed": upload_performed,
                "privacy_checked": privacy_checked,
                "redacted": bool(uploaded.get("redacted")),
                "privacy_check_summary": uploaded.get("privacy_check_summary"),
            }
        )
    return assets


def _devpost_upload_state(root: Path, local_failures: list[str]) -> dict[str, Any]:
    path = root / DEVPOST_UPLOAD_STATE
    if not path.is_file():
        local_failures.append(f"missing Devpost upload state: {DEVPOST_UPLOAD_STATE}")
        return {"status": "missing", "uploads": []}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        local_failures.append(f"invalid Devpost upload state: {DEVPOST_UPLOAD_STATE}")
        return {"status": "invalid_json", "uploads": []}
    uploads = payload.get("uploads")
    if not isinstance(uploads, list):
        local_failures.append(f"Devpost upload state uploads must be a list: {DEVPOST_UPLOAD_STATE}")
        payload["uploads"] = []
    if payload.get("final_submit_performed") is not False:
        local_failures.append("Devpost upload state must not claim final_submit_performed=true")
    return payload


def _video_candidate(root: Path, local_failures: list[str]) -> dict[str, Any]:
    manifest_path = root / VIDEO_CANDIDATE_MANIFEST
    video_path = root / VIDEO_CANDIDATE_MP4
    if not manifest_path.is_file():
        local_failures.append(f"missing video candidate manifest: {VIDEO_CANDIDATE_MANIFEST}")
        return {"status": "missing_manifest", "path": VIDEO_CANDIDATE_MP4}
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        local_failures.append(f"invalid video candidate manifest: {VIDEO_CANDIDATE_MANIFEST}")
        return {"status": "invalid_manifest", "path": VIDEO_CANDIDATE_MP4}
    manifest_video = str(manifest.get("video_path") or VIDEO_CANDIDATE_MP4)
    if manifest_video != VIDEO_CANDIDATE_MP4:
        local_failures.append(f"unexpected video candidate path: {manifest_video}")
    if not video_path.is_file():
        local_failures.append(f"missing video candidate file: {VIDEO_CANDIDATE_MP4}")
        return {"status": "missing_video", "path": VIDEO_CANDIDATE_MP4}
    size = video_path.stat().st_size
    duration = float(manifest.get("duration_seconds") or 0)
    if not (140 <= duration <= 165):
        local_failures.append(f"video candidate duration outside 2:20-2:45: {duration}")
    if size <= 1_000_000:
        local_failures.append(f"video candidate too small on disk: {VIDEO_CANDIDATE_MP4}")
    if manifest.get("upload_performed") is not False:
        local_failures.append("video candidate manifest must not claim upload_performed=true")
    if manifest.get("devpost_video_url"):
        local_failures.append("video candidate manifest must not claim a Devpost video URL")
    return {
        "status": "built",
        "path": VIDEO_CANDIDATE_MP4,
        "manifest_path": VIDEO_CANDIDATE_MANIFEST,
        "duration_seconds": duration,
        "bytes": size,
        "upload_performed": manifest.get("upload_performed"),
        "devpost_video_url": manifest.get("devpost_video_url"),
    }


def _presentation_deck(
    root: Path,
    upload_state: dict[str, Any],
    local_failures: list[str],
) -> dict[str, Any]:
    path = root / PRESENTATION_DECK_PPTX
    if not path.is_file():
        return {
            "status": "missing",
            "path": PRESENTATION_DECK_PPTX,
            "upload_performed": False,
            "privacy_checked": False,
        }

    try:
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())
    except zipfile.BadZipFile:
        local_failures.append(f"presentation deck is not a valid PPTX: {PRESENTATION_DECK_PPTX}")
        return {
            "status": "invalid_pptx",
            "path": PRESENTATION_DECK_PPTX,
            "upload_performed": False,
            "privacy_checked": False,
        }

    slide_count = sum(
        1
        for name in names
        if name.startswith("ppt/slides/slide") and name.endswith(".xml")
    )
    if "ppt/presentation.xml" not in names or slide_count < 3:
        local_failures.append(
            f"presentation deck is missing PowerPoint slide content: {PRESENTATION_DECK_PPTX}"
        )
        return {
            "status": "invalid_pptx",
            "path": PRESENTATION_DECK_PPTX,
            "slide_count": slide_count,
            "upload_performed": False,
            "privacy_checked": False,
        }

    upload_record = next(
        (
            item
            for item in upload_state.get("uploads", [])
            if isinstance(item, dict) and item.get("path") == PRESENTATION_DECK_PPTX
        ),
        {},
    )
    upload_performed = bool(upload_record.get("upload_performed"))
    privacy_checked = bool(upload_record.get("privacy_checked"))
    if upload_performed and not privacy_checked:
        local_failures.append("uploaded presentation PPT lacks privacy check")

    return {
        "status": "built",
        "path": PRESENTATION_DECK_PPTX,
        "bytes": path.stat().st_size,
        "slide_count": slide_count,
        "upload_performed": upload_performed,
        "privacy_checked": privacy_checked,
    }


def _png_size(path: Path) -> tuple[int, int]:
    data = path.read_bytes()
    if len(data) < 24 or not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError(f"media asset is not a PNG: {path.name}")
    return struct.unpack(">II", data[16:24])


def _bundle_path(root: Path) -> Path:
    if (root / "SUBMISSION_MANIFEST.md").is_file():
        return root
    latest_dist_bundle = _latest_dist_bundle(root)
    if latest_dist_bundle is not None:
        return latest_dist_bundle
    gate_path = root / "docs" / "submission" / "public-release-gate.md"
    if gate_path.is_file():
        match = BUNDLE_PATTERN.search(gate_path.read_text(encoding="utf-8"))
        if match:
            return root / match.group(0).rstrip("/")
    return root / "dist" / "recallpack-submission"


def _latest_dist_bundle(root: Path) -> Path | None:
    dist = root / "dist"
    if not dist.is_dir():
        return None
    candidates = [
        path
        for path in dist.glob("recallpack-submission-[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]-[0-9][0-9][0-9][0-9][0-9][0-9]")
        if (path / "SUBMISSION_MANIFEST.md").is_file()
    ]
    if not candidates:
        return None
    return sorted(candidates, key=lambda path: path.name)[-1]


def _display_bundle_path(root: Path, bundle_path: Path) -> str:
    if bundle_path.resolve() == root.resolve():
        return "."
    try:
        return bundle_path.relative_to(root).as_posix()
    except ValueError:
        return bundle_path.as_posix()


def _bundle_is_available(root: Path, bundle_path: Path) -> bool:
    if bundle_path.resolve() == root.resolve():
        return (root / "SUBMISSION_MANIFEST.md").is_file()
    return (bundle_path / "SUBMISSION_MANIFEST.md").is_file()


def _live_qwen_e2e_status(path: Path) -> str:
    if not path.is_file():
        return "not_found"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return "invalid_json"
    status = (
        payload.get("live_status")
        or payload.get("status")
        or payload.get("live_qwen_e2e_status")
        or payload.get("summary", {}).get("status")
    )
    return str(status or "unknown")


def _public_repo_url(root: Path) -> str | None:
    candidates = [
        root / "docs" / "submission" / "public-repo-readiness-report.md",
        root / "docs" / "submission" / "devpost-materials.md",
        root / "README.md",
    ]
    pattern = re.compile(r"https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
    for path in candidates:
        if not path.is_file():
            continue
        match = pattern.search(path.read_text(encoding="utf-8"))
        if match:
            return match.group(0).rstrip(".,)")
    return None


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the local-only RecallPack Devpost readiness preflight."
    )
    parser.add_argument(
        "--root",
        default=str(Path(__file__).resolve().parents[1]),
        help="Repository or sanitized bundle root to inspect.",
    )
    args = parser.parse_args()

    payload = build_preflight(Path(args.root))
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if payload["ready_local_materials"] else 1


if __name__ == "__main__":
    sys.exit(main())
