from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any


SCRIPT_ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
if str(SCRIPT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT / "src"))
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))

try:
    from devpost_preflight import build_preflight
    from final_submission_gate import build_final_gate
    from public_repo_preflight import build_public_repo_preflight
    from video_rehearsal_gate import build_video_rehearsal_gate
except ModuleNotFoundError:
    from tools.devpost_preflight import build_preflight
    from tools.final_submission_gate import build_final_gate
    from tools.public_repo_preflight import build_public_repo_preflight
    from tools.video_rehearsal_gate import build_video_rehearsal_gate


FULL_LOOP_COMMAND = "python3 tools/submission_readiness_loop.py --full"


def build_submission_readiness_loop(
    root: Path,
    *,
    include_final_gate: bool = False,
    timeout: int = 90,
) -> dict[str, Any]:
    root = root.resolve()
    devpost = build_preflight(root)
    video = build_video_rehearsal_gate(root)
    public_repo = build_public_repo_preflight(root)
    final_gate = build_final_gate(root, timeout=timeout) if include_final_gate else None

    checks = [
        _devpost_check(devpost),
        _video_check(video),
        _public_repo_check(public_repo),
        _final_gate_check(final_gate),
    ]
    local_ready_without_final = all(
        check["status"] == "passed"
        for check in checks
        if check["id"] != "final_submission_gate"
    )
    full_final_passed = (
        bool(final_gate)
        and final_gate.get("status") == "ready_local_evidence_gated_manual_submission"
    )
    failed_checks = [
        check for check in checks if check["status"] not in {"passed", "skipped"}
    ]
    manual_blockers = _unique(
        list(devpost.get("missing_required_manual_items", []))
        + list((final_gate or {}).get("manual_blockers", []))
    )
    gated_actions = _unique(
        list(devpost.get("gated_actions", []))
        + list((final_gate or {}).get("gated_actions", []))
    )

    if failed_checks:
        status = "blocked_submission_readiness_loop"
        next_command = _next_fix(failed_checks)
    elif include_final_gate and full_final_passed:
        status = "ready_local_evidence_gated_manual_submission"
        next_command = "complete manual gated actions only after final approval"
    elif include_final_gate:
        status = "blocked_submission_readiness_loop"
        next_command = "fix final submission gate failure and rerun loop"
    else:
        status = "ready_for_full_loop_verification"
        next_command = FULL_LOOP_COMMAND

    return {
        "status": status,
        "root": root.as_posix(),
        "local_ready_without_final_gate": local_ready_without_final,
        "full_final_gate_run": include_final_gate,
        "full_final_gate_passed": full_final_passed,
        "checks": checks,
        "manual_blockers": manual_blockers,
        "gated_actions": gated_actions,
        "public_repo_url": devpost.get("public_repo_url"),
        "publish_source": public_repo.get("publish_source"),
        "remote_sync_verified": bool(public_repo.get("remote_sync_verified")),
        "remote_sync_note": public_repo.get("remote_sync_note"),
        "live_qwen_e2e_status": devpost.get("live_qwen_e2e_status"),
        "fresh_m98_live_rerun_status": devpost.get("fresh_m98_live_rerun_status"),
        "no_public_action_performed": True,
        "requires_credentials": False,
        "network_calls_made": False,
        "next_recommended_command": next_command,
        "loop_policy": (
            "Fix failed local checks, rebuild the sanitized bundle, rerun this "
            "loop with --full, and stop before push/deploy/video/upload/submit "
            "unless those external actions are explicitly approved."
        ),
    }


def _devpost_check(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": "devpost_preflight",
        "status": "passed" if payload.get("ready_local_materials") else "failed",
        "preflight_status": payload.get("status"),
        "local_failures": payload.get("local_failures", []),
        "manual_blockers": payload.get("missing_required_manual_items", []),
    }


def _video_check(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": "video_rehearsal_gate",
        "status": "passed" if payload.get("recording_ready") else "failed",
        "recording_status": payload.get("status"),
        "manual_blockers": payload.get("manual_blockers", []),
    }


def _public_repo_check(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": "public_repo_preflight",
        "status": "passed" if payload.get("ready") else "failed",
        "preflight_status": payload.get("status"),
        "publish_source": payload.get("publish_source"),
        "remote_sync_verified": bool(payload.get("remote_sync_verified")),
        "remote_sync_note": payload.get("remote_sync_note"),
    }


def _final_gate_check(payload: dict[str, Any] | None) -> dict[str, Any]:
    if payload is None:
        return {
            "id": "final_submission_gate",
            "status": "skipped",
            "recommended_command": FULL_LOOP_COMMAND,
        }
    return {
        "id": "final_submission_gate",
        "status": "passed"
        if payload.get("status") == "ready_local_evidence_gated_manual_submission"
        else "failed",
        "final_status": payload.get("status"),
        "public_surface_root": payload.get("public_surface_root"),
        "manual_blockers": payload.get("manual_blockers", []),
    }


def _next_fix(failed_checks: list[dict[str, Any]]) -> str:
    first = failed_checks[0]
    return f"fix {first['id']} and rerun {FULL_LOOP_COMMAND}"


def _unique(items: list[Any]) -> list[Any]:
    seen = set()
    result = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the local-only RecallPack submission readiness loop."
    )
    parser.add_argument(
        "--root",
        default=str(SCRIPT_ROOT),
        help="Private workspace root or sanitized public bundle root.",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="Include the full final submission gate and fresh-clone rehearsal.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=90,
        help="Timeout in seconds for child commands used by the final gate.",
    )
    args = parser.parse_args()

    payload = build_submission_readiness_loop(
        Path(args.root),
        include_final_gate=args.full,
        timeout=args.timeout,
    )
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if payload["status"].startswith("ready_") else 1


if __name__ == "__main__":
    sys.exit(main())
