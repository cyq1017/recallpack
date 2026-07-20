from __future__ import annotations

from typing import Any, Mapping

from recallpack.evidence_review_protocol import (
    EligibleRegistration41,
    InMemoryManifestRegistry,
    SqliteManifestRegistry,
    _eligibility_binding_for_manifest,
)


def test_only_eligible_registration(
    manifest: Mapping[str, Any],
) -> EligibleRegistration41:
    """Build downstream-test state; this does not exercise the production mint."""

    binding = _eligibility_binding_for_manifest(manifest)
    return EligibleRegistration41(
        review_seed_sha256=binding.review_seed_sha256,
        execution_manifest_sha256=binding.execution_manifest_sha256,
        review_attestation_sha256=binding.review_attestation_sha256,
        leakage_set_sha256=binding.leakage_set_sha256,
        eligibility_gate_version=binding.eligibility_gate_version,
    )


def seed_test_only_eligible_registration(
    registry: InMemoryManifestRegistry | SqliteManifestRegistry,
    manifest: Mapping[str, Any],
) -> EligibleRegistration41:
    registration = test_only_eligible_registration(manifest)
    if type(registry) is InMemoryManifestRegistry:
        with registry._lock:
            registry._eligible_registrations[
                registration.review_seed_sha256
            ] = registration
        return registration
    if type(registry) is SqliteManifestRegistry:
        registry._connection.execute(
            "INSERT INTO eligible_review_seed_registrations "
            "(review_seed_sha256, execution_manifest_sha256, "
            "review_attestation_sha256, leakage_set_sha256, "
            "eligibility_gate_version) VALUES (?, ?, ?, ?, ?)",
            (
                registration.review_seed_sha256,
                registration.execution_manifest_sha256,
                registration.review_attestation_sha256,
                registration.leakage_set_sha256,
                registration.eligibility_gate_version,
            ),
        )
        return registration
    raise TypeError("test helper accepts only built-in registries")
