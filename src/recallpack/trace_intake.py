from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any


SECRET_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9_-]{12,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
)
LOCAL_PATH_PATTERNS = (
    re.compile("/" + r"Users/[^\s\"']+"),
    re.compile(r"/home/[^\s\"']+"),
)
REQUIRED_EVENT_FIELDS = (
    "session_id",
    "sequence_no",
    "actor",
    "text",
    "observed_at",
)


def validate_trace_file(path: str | Path) -> dict[str, Any]:
    trace_path = Path(path)
    payload = json.loads(trace_path.read_text())
    report = validate_trace_payload(payload)
    report["trace_file"] = trace_path.name
    return report


def sanitize_trace_file(path: str | Path) -> dict[str, Any]:
    trace_path = Path(path)
    payload = json.loads(trace_path.read_text())
    return sanitize_trace_payload(payload)


def sanitize_trace_payload(payload: dict[str, Any]) -> dict[str, Any]:
    sanitized = _sanitize_value(payload)
    if not isinstance(sanitized, dict):
        return {}
    sanitized["source_kind"] = "sanitized_trace_candidate"
    sanitized["promoted_to_submission_evidence"] = False
    return sanitized


def validate_trace_payload(payload: dict[str, Any]) -> dict[str, Any]:
    blockers: list[str] = []
    consent_report = _validate_consent(payload, blockers)
    event_report = _validate_events(payload, blockers)
    privacy_report = _scan_privacy(payload, blockers)

    promoted = bool(payload.get("promoted_to_submission_evidence", False))
    if promoted and not consent_report["allows_public_release"]:
        _add_blocker(blockers, "public_release_without_consent")

    status = "blocked" if blockers else "accepted_for_internal_review"
    return {
        "status": status,
        "trace_id": str(payload.get("trace_id", "")),
        "project_id": str(payload.get("project_id", "")),
        "promoted_to_submission_evidence": promoted,
        "evidence_boundary": (
            "not_submission_evidence_until_explicit_promotion"
            if not promoted
            else "candidate_submission_evidence_requires_manual_review"
        ),
        "consent": consent_report,
        "event_count": event_report["event_count"],
        "session_count": event_report["session_count"],
        "privacy": privacy_report,
        "blockers": blockers,
    }


def _validate_consent(payload: dict[str, Any], blockers: list[str]) -> dict[str, Any]:
    consent = payload.get("consent")
    if not isinstance(consent, dict):
        _add_blocker(blockers, "missing_consent")
        return {
            "status": "missing",
            "scope": "",
            "allows_public_release": False,
            "participant_label": "",
        }

    status = str(consent.get("status", ""))
    scope = str(consent.get("scope", ""))
    if status != "consented":
        _add_blocker(blockers, "missing_consent")
    if scope != "sanitized_recallpack_trace_review":
        _add_blocker(blockers, "invalid_consent_scope")
    return {
        "status": status,
        "scope": scope,
        "allows_public_release": bool(consent.get("allows_public_release", False)),
        "participant_label": str(consent.get("participant_label", "")),
    }


def _validate_events(payload: dict[str, Any], blockers: list[str]) -> dict[str, int]:
    events = payload.get("events")
    if not isinstance(events, list) or not events:
        _add_blocker(blockers, "missing_events")
        return {"event_count": 0, "session_count": 0}

    session_sequences: dict[str, list[int]] = defaultdict(list)
    for event in events:
        if not isinstance(event, dict):
            _add_blocker(blockers, "invalid_event")
            continue
        for field in REQUIRED_EVENT_FIELDS:
            if field not in event:
                _add_blocker(blockers, f"missing_event_{field}")
        session_id = str(event.get("session_id", ""))
        sequence_no = event.get("sequence_no")
        if not session_id:
            _add_blocker(blockers, "missing_event_session_id")
        if isinstance(sequence_no, int):
            session_sequences[session_id].append(sequence_no)
        else:
            _add_blocker(blockers, "invalid_sequence")

    for sequence_numbers in session_sequences.values():
        if len(sequence_numbers) != len(set(sequence_numbers)):
            _add_blocker(blockers, "duplicate_sequence")
        expected = list(range(1, len(sequence_numbers) + 1))
        if sorted(sequence_numbers) != expected:
            _add_blocker(blockers, "non_contiguous_sequence")

    return {"event_count": len(events), "session_count": len(session_sequences)}


def _scan_privacy(payload: dict[str, Any], blockers: list[str]) -> dict[str, list[str]]:
    serialized = json.dumps(payload, sort_keys=True)
    secret_hits = _scan_patterns(serialized, SECRET_PATTERNS)
    local_path_hits = _scan_patterns(serialized, LOCAL_PATH_PATTERNS)
    if secret_hits:
        _add_blocker(blockers, "secret_like_value")
    if local_path_hits:
        _add_blocker(blockers, "local_path")
    return {
        "secret_hits": secret_hits,
        "local_path_hits": local_path_hits,
    }


def _scan_patterns(text: str, patterns: tuple[re.Pattern[str], ...]) -> list[str]:
    hits: list[str] = []
    for pattern in patterns:
        for match in pattern.finditer(text):
            hits.append(_redact_hit(match.group(0)))
    return sorted(set(hits))


def _sanitize_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _sanitize_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_sanitize_value(item) for item in value]
    if isinstance(value, str):
        return _sanitize_text(value)
    return value


def _sanitize_text(text: str) -> str:
    sanitized = text
    for pattern in SECRET_PATTERNS:
        sanitized = pattern.sub("[redacted-secret]", sanitized)
    for pattern in LOCAL_PATH_PATTERNS:
        sanitized = pattern.sub("[redacted-local-path]", sanitized)
    return sanitized


def _redact_hit(value: str) -> str:
    if len(value) <= 8:
        return "[redacted]"
    return f"{value[:4]}...[redacted]"


def _add_blocker(blockers: list[str], blocker: str) -> None:
    if blocker not in blockers:
        blockers.append(blocker)
