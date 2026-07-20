from __future__ import annotations

import copy
import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass
from typing import Any, Mapping

from recallpack.budget import canonical_json


_PRODUCTION_RETAINED_AUTHORITY_KEY = secrets.token_bytes(32)


@dataclass(frozen=True)
class TestOnlyTrustedRetainedAttemptLoader:
    """Evaluator-owned capability for contract tests, never public evidence."""

    simulation_marker = "test_only_trusted_retained_attempt_loader"
    _snapshot_bytes: bytes

    def __init__(self, authority_snapshot: Mapping[str, Any]) -> None:
        object.__setattr__(
            self,
            "_snapshot_bytes",
            canonical_json(copy.deepcopy(dict(authority_snapshot))).encode("utf-8"),
        )

    def load_finalized_population(
        self,
        execution_manifest_sha256: str,
    ) -> dict[str, Any]:
        snapshot = json.loads(self._snapshot_bytes)
        if snapshot.get("execution_manifest_sha256") != execution_manifest_sha256:
            raise ValueError("retained-attempt loader manifest binding mismatch")
        return snapshot


@dataclass(frozen=True)
class _ProductionTrustedRetainedAttemptLoader:
    _snapshot_bytes: bytes
    _hmac_sha256: str

    def load_finalized_population(
        self,
        execution_manifest_sha256: str,
    ) -> dict[str, Any]:
        expected_hmac = hmac.new(
            _PRODUCTION_RETAINED_AUTHORITY_KEY,
            self._snapshot_bytes,
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(self._hmac_sha256, expected_hmac):
            raise ValueError("production retained-attempt authority authentication failed")
        snapshot = json.loads(self._snapshot_bytes)
        if snapshot.get("execution_manifest_sha256") != execution_manifest_sha256:
            raise ValueError("retained-attempt loader manifest binding mismatch")
        return snapshot


def _seal_production_retained_attempt_snapshot(
    authority_snapshot: Mapping[str, Any],
) -> _ProductionTrustedRetainedAttemptLoader:
    snapshot_bytes = canonical_json(copy.deepcopy(dict(authority_snapshot))).encode("utf-8")
    return _ProductionTrustedRetainedAttemptLoader(
        _snapshot_bytes=snapshot_bytes,
        _hmac_sha256=hmac.new(
            _PRODUCTION_RETAINED_AUTHORITY_KEY,
            snapshot_bytes,
            hashlib.sha256,
        ).hexdigest(),
    )


def load_finalized_attempt_snapshot(
    loader: Any,
    execution_manifest_sha256: str,
) -> Mapping[str, Any]:
    loader_type = type(loader)
    if loader_type not in {
        TestOnlyTrustedRetainedAttemptLoader,
        _ProductionTrustedRetainedAttemptLoader,
    }:
        raise TypeError("retained attempt loader is not an evaluator-owned capability")
    snapshot = loader.load_finalized_population(execution_manifest_sha256)
    if loader_type is TestOnlyTrustedRetainedAttemptLoader:
        if (
            snapshot.get("authority_kind")
            != "test_only_sealed_retained_attempt_authority"
            or snapshot.get("simulation_marker")
            != "test_only_sealed_retained_attempt_authority"
        ):
            raise TypeError("test-only capability cannot impersonate production authority")
    elif (
        snapshot.get("authority_kind") != "production_append_only_attempt_journal"
        or snapshot.get("simulation_marker") is not None
    ):
        raise TypeError("production capability authority header is invalid")
    return snapshot


def is_test_only_retained_attempt_loader(loader: Any) -> bool:
    return type(loader) is TestOnlyTrustedRetainedAttemptLoader
