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
    from export_evidence_index import build_evidence_index
    from fresh_clone_smoke import run_fresh_clone_smoke
    from public_repo_preflight import _scan_public_surface
except ModuleNotFoundError:
    from tools.devpost_preflight import build_preflight
    from tools.export_evidence_index import build_evidence_index
    from tools.fresh_clone_smoke import run_fresh_clone_smoke
    from tools.public_repo_preflight import _scan_public_surface


def build_final_gate(root: Path, timeout: int = 90) -> dict[str, Any]:
    root = root.resolve()
    preflight = build_preflight(root)
    public_surface = _public_surface_root(root, preflight)
    evidence = build_evidence_index(public_surface)
    scan = _scan_public_surface(public_surface)
    fresh_clone = _run_fresh_clone_gate(public_surface, timeout=timeout)

    gates = [
        _preflight_gate(preflight),
        _evidence_gate(evidence),
        _scan_gate(scan),
        fresh_clone,
    ]
    local_ready = all(gate["status"] == "passed" for gate in gates)

    return {
        "status": (
            "ready_local_evidence_gated_manual_submission"
            if local_ready
            else "failed_local_submission_gate"
        ),
        "local_ready": local_ready,
        "root": root.as_posix(),
        "public_surface_root": public_surface.as_posix(),
        "local_gates": gates,
        "manual_blockers": evidence["manual_blockers"],
        "gated_actions": evidence["gated_actions"],
        "public_repo_url": evidence["public_repo_url"],
        "live_qwen_e2e_status": evidence["live_qwen_e2e_status"],
        "fresh_m98_live_rerun_status": evidence["fresh_m98_live_rerun_status"],
        "no_public_action_performed": True,
        "requires_credentials": False,
        "network_calls_made": False,
        "local_http_smoke_performed": fresh_clone["status"] == "passed",
        "recommended_commands": [
            "python3 tools/final_submission_gate.py",
            "python3 tools/devpost_preflight.py",
            "python3 tools/export_evidence_index.py",
            "python3 tools/video_rehearsal_gate.py",
            "PYTHONPATH=src python3 tools/fresh_clone_smoke.py --source . --full",
        ],
    }


def _public_surface_root(root: Path, preflight: dict[str, Any]) -> Path:
    bundle = str(preflight["sanitized_bundle"])
    if bundle == ".":
        return root
    return (root / bundle).resolve()


def _preflight_gate(preflight: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": "devpost_preflight",
        "status": "passed" if preflight["ready_local_materials"] else "failed",
        "preflight_status": preflight["status"],
        "checked_file_count": len(preflight["checked_files"]),
        "local_failures": preflight["local_failures"],
        "manual_blocker_count": len(preflight["missing_required_manual_items"]),
    }


def _evidence_gate(evidence: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": "evidence_index",
        "status": (
            "passed"
            if evidence["status"] == "local_evidence_ready_gated_submission"
            else "failed"
        ),
        "claim_count": len(evidence["claims"]),
        "live_qwen_e2e_status": evidence["live_qwen_e2e_status"],
        "claim_statuses": sorted(
            {claim["claim_status"] for claim in evidence["claims"]}
        ),
    }


def _scan_gate(scan: dict[str, list[str]]) -> dict[str, Any]:
    has_findings = any(scan.values())
    return {
        "id": "public_bundle_scan",
        "status": "failed" if has_findings else "passed",
        "findings": scan,
    }


def _run_fresh_clone_gate(public_surface: Path, timeout: int) -> dict[str, Any]:
    try:
        smoke = run_fresh_clone_smoke(public_surface, timeout=timeout, full=True)
    except Exception as exc:
        return {
            "id": "fresh_clone_full",
            "status": "failed",
            "error": str(exc),
        }
    return {
        "id": "fresh_clone_full",
        "status": "passed" if smoke["status"] == "passed" else "failed",
        "unit_mode": smoke["unit_mode"],
        "judge_smoke": smoke["judge_smoke"],
        "checks": smoke["checks"],
        "copied_to_temp": smoke["copied_to_temp"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the local-only final RecallPack submission evidence gate."
    )
    parser.add_argument(
        "--root",
        default=str(SCRIPT_ROOT),
        help="Private workspace root or sanitized public bundle root.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=90,
        help="Timeout in seconds for each fresh-clone child command.",
    )
    args = parser.parse_args()

    payload = build_final_gate(Path(args.root), timeout=args.timeout)
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if payload["local_ready"] else 1


if __name__ == "__main__":
    sys.exit(main())
