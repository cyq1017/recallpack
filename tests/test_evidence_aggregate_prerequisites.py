import copy
import importlib
import unittest

from tests.v4_evidence_fixtures import (
    TestOnlyTrustedRetainedAttemptLoader,
    build_aggregate_artifact_hashes,
    build_aggregate_report,
    build_evaluation_run,
    build_execution_input_artifact_bytes,
    build_test_only_simulated_cross_scenario_false_supersession_conflict_packet,
    build_test_only_simulated_false_supersession_scope_packet,
    build_test_only_simulated_retained_adverse_false_supersession_packet,
    build_full_execution_manifest,
    build_test_only_simulated_runtime_contract_retained_attempt_packet,
    build_test_only_simulated_runtime_contract_scope_packet,
    build_simulated_external_holdout_bundle,
    build_test_only_retained_attempt_authority,
    build_test_only_simulated_valid_manifest_red_packet,
    build_test_only_simulated_zero_denominator_false_supersession_packet,
    canonical_json_bytes,
    canonical_sha256,
    definition_validator,
)


def _import_evidence():
    return importlib.import_module("recallpack.evidence")


class AggregatePrerequisiteTests(unittest.TestCase):
    def _assert_semantic_reject_detail(
        self,
        fn,
        *args,
        code: str,
        pointer: str,
        detail: str,
        **kwargs,
    ):
        with self.assertRaises(ValueError) as excinfo:
            fn(*args, **kwargs)
        message = str(excinfo.exception)
        self.assertIn(code, message)
        self.assertIn(pointer, message)
        self.assertIn(detail, message)

    def _aggregate_validate_kwargs(self, packet):
        return {
            "execution_manifest": packet["manifest"],
            "retained_attempt_loader": packet["retained_attempt_loader"],
            "artifact_bytes": packet["artifact_bytes"],
            "source_ledgers": packet["all_source_ledgers"],
            "relation_label_ledgers": packet["all_relation_label_ledgers"],
        }

    def _run_validate_kwargs(self, packet, run):
        kwargs = {
            "artifact_bytes": packet["artifact_bytes"],
            "source_ledger": packet["all_source_ledgers"][run["scenario_id"]],
        }
        if run["variant_id"] == "recallpack" and run["designation"] == "headline":
            kwargs["relation_label_ledger"] = packet["all_relation_label_ledgers"][
                run["scenario_id"]
            ]
        return kwargs

    def _validate_runs(self, validate_run, packet, runs):
        for run in runs:
            validate_run(
                run, packet["manifest"], **self._run_validate_kwargs(packet, run)
            )

    def _assert_aggregate_missing_api(self, evidence_module, case_names):
        validate = getattr(
            evidence_module,
            "validate_legacy_aggregate_report_diagnostic",
            None,
        )
        if validate is None:
            joined = ",".join(case_names)
            raise AttributeError(
                "module 'recallpack.evidence' has no attribute "
                f"'validate_aggregate_report' [{joined}]"
            )
        return validate

    def _replace_contributor(self, packet, original_run_id, replacement_run):
        contributors = []
        for run in packet["contributors"]:
            if run["run_id"] == original_run_id:
                contributors.append(copy.deepcopy(replacement_run))
            else:
                contributors.append(copy.deepcopy(run))
        return contributors

    def _rebuild_runtime_aggregate(self, packet, contributors):
        metric = copy.deepcopy(packet["aggregate"]["metrics"][0])
        return build_aggregate_report(
            packet["manifest"],
            claim_id=packet["aggregate"]["claim_id"],
            claim_type=packet["aggregate"]["claim_type"],
            run_records=contributors,
            run_ids=[run["run_id"] for run in contributors],
            adverse_run_ids=[],
            scope=copy.deepcopy(packet["aggregate"]["scope"]),
            metrics=[metric],
        )

    def _metric_report(
        self,
        packet,
        *,
        metric_id,
        n,
        numerator,
        denominator,
        rate,
        claim_id="claim_structural_runtime",
        claim_type="structural_runtime",
    ):
        return build_aggregate_report(
            packet["manifest"],
            claim_id=claim_id,
            claim_type=claim_type,
            run_records=packet["contributors"],
            run_ids=[run["run_id"] for run in packet["contributors"]],
            adverse_run_ids=[
                run["run_id"]
                for run in packet["contributors"]
                if run["outcome"]["status"] == "adverse"
            ],
            scope=copy.deepcopy(packet["aggregate"]["scope"]),
            metrics=[
                {
                    "metric_id": metric_id,
                    "n": n,
                    "numerator": numerator,
                    "denominator": denominator,
                    "rate": rate,
                }
            ],
        )

    def test_full_manifest_helpers_require_explicit_simulated_external_holdout_and_mark_test_packets(
        self,
    ):
        with self.assertRaisesRegex(ValueError, "simulated_external_holdout"):
            build_full_execution_manifest()

        holdout = build_simulated_external_holdout_bundle()
        manifest = build_full_execution_manifest(simulated_external_holdout=holdout)
        with self.assertRaisesRegex(ValueError, "simulated_external_holdout"):
            build_execution_input_artifact_bytes(manifest)

        packets = {
            "runtime_scope": build_test_only_simulated_runtime_contract_scope_packet(),
            "false_supersession_scope": (
                build_test_only_simulated_false_supersession_scope_packet()
            ),
            "zero_denominator_scope": (
                build_test_only_simulated_zero_denominator_false_supersession_packet()
            ),
            "cross_scenario_scope": (
                build_test_only_simulated_cross_scenario_false_supersession_conflict_packet()
            ),
            "retained_attempt_scope": (
                build_test_only_simulated_runtime_contract_retained_attempt_packet()
            ),
            "retained_adverse_scope": (
                build_test_only_simulated_retained_adverse_false_supersession_packet()
            ),
            "manifest_red_packet": build_test_only_simulated_valid_manifest_red_packet(),
        }
        for name, packet in packets.items():
            with self.subTest(name=name):
                self.assertEqual(
                    "simulated_external_contract_test_only",
                    packet["test_only_simulation_marker"],
                )
                self.assertEqual(
                    "simulated_external_contract_test_only",
                    packet["simulated_external_holdout"]["custody_kind"],
                )

        runtime_packet = packets["runtime_scope"]
        self.assertEqual(
            "test_only_sealed_retained_attempt_authority",
            runtime_packet["retained_attempt_authority"]["simulation_marker"],
        )
        self.assertEqual(
            "test_only_trusted_retained_attempt_loader",
            runtime_packet["retained_attempt_loader"].simulation_marker,
        )

    def test_runtime_aggregate_positive_prerequisites_reach_future_api_through_trusted_loader(
        self,
    ):
        packet = build_test_only_simulated_runtime_contract_scope_packet()
        evidence_module = _import_evidence()
        validate_run = evidence_module.validate_legacy_evaluation_run_diagnostic

        self.assertEqual(60, len(packet["all_runs"]))
        self._validate_runs(validate_run, packet, packet["all_runs"])
        self.assertEqual(60, packet["retained_attempt_authority"]["entry_count"])
        self.assertEqual(
            packet["retained_attempt_authority"],
            packet["retained_attempt_loader"].load_finalized_population(
                canonical_sha256(packet["manifest"])
            ),
        )
        self.assertEqual(
            [], list(definition_validator("aggregate").iter_errors(packet["aggregate"]))
        )

        validate = self._assert_aggregate_missing_api(
            evidence_module, ["runtime_positive"]
        )
        validate(packet["aggregate"], **self._aggregate_validate_kwargs(packet))

    def test_false_supersession_and_zero_denominator_positive_prerequisites_reach_future_api(
        self,
    ):
        packet = build_test_only_simulated_false_supersession_scope_packet()
        zero_packet = (
            build_test_only_simulated_zero_denominator_false_supersession_packet()
        )
        evidence_module = _import_evidence()
        validate_run = evidence_module.validate_legacy_evaluation_run_diagnostic

        self._validate_runs(validate_run, packet, packet["all_runs"])
        self._validate_runs(validate_run, zero_packet, zero_packet["all_runs"])
        self.assertEqual(
            [], list(definition_validator("aggregate").iter_errors(packet["aggregate"]))
        )
        self.assertEqual(
            [],
            list(
                definition_validator("aggregate").iter_errors(zero_packet["aggregate"])
            ),
        )
        self.assertEqual(
            {
                "metric_id": "false_supersession_rate",
                "n": 2,
                "numerator": 1,
                "denominator": 2,
                "rate": 0.5,
            },
            packet["aggregate"]["metrics"][0],
        )
        self.assertEqual(
            {
                "metric_id": "false_supersession_rate",
                "n": 0,
                "numerator": 0,
                "denominator": 0,
                "rate": None,
            },
            zero_packet["aggregate"]["metrics"][0],
        )

        validate = self._assert_aggregate_missing_api(
            evidence_module,
            [
                "false_supersession_positive",
                "false_supersession_zero_denominator_positive",
            ],
        )
        validate(packet["aggregate"], **self._aggregate_validate_kwargs(packet))
        validate(
            zero_packet["aggregate"], **self._aggregate_validate_kwargs(zero_packet)
        )

    def test_retained_non_authoritative_false_supersession_repeat_poisoning_is_future_red(
        self,
    ):
        packet = build_test_only_simulated_retained_adverse_false_supersession_packet()
        evidence_module = _import_evidence()
        validate_run = evidence_module.validate_legacy_evaluation_run_diagnostic

        self._validate_runs(validate_run, packet, packet["retained_runs"])
        self.assertEqual(
            [],
            list(definition_validator("aggregate").iter_errors(packet["aggregate"])),
        )
        self.assertTrue(
            all(
                opportunity["outcome"] == "correct"
                for run in packet["contributors"]
                for opportunity in run["relation_opportunities"]
            )
        )
        adverse_entry = next(
            entry
            for entry in packet["retained_attempt_authority"]["entries"]
            if entry["run_id"] == packet["retained_adverse_run"]["run_id"]
        )
        self.assertEqual(
            "retained_non_authoritative", adverse_entry["finalization_state"]
        )
        self.assertEqual(
            {
                "metric_id": "false_supersession_rate",
                "n": 2,
                "numerator": 0,
                "denominator": 2,
                "rate": 0.0,
            },
            packet["aggregate"]["metrics"][0],
        )

        validate = self._assert_aggregate_missing_api(
            evidence_module,
            ["retained_non_authoritative_false_supersession_repeat"],
        )
        self._assert_semantic_reject_detail(
            validate,
            packet["aggregate"],
            code="invalid_aggregate",
            pointer="/metrics/0/numerator",
            detail=(
                "false_supersession_rate numerator must include adverse "
                "retained non-authoritative repeats"
            ),
            **self._aggregate_validate_kwargs(packet),
        )

    def test_retained_attempt_loader_future_red_cases_cover_omission_alternate_duplicate_cross_manifest_and_invalidated(
        self,
    ):
        packet = build_test_only_simulated_runtime_contract_retained_attempt_packet()
        evidence_module = _import_evidence()
        validate_run = evidence_module.validate_legacy_evaluation_run_diagnostic

        self._validate_runs(validate_run, packet, packet["all_runs"])
        self._validate_runs(
            validate_run,
            packet,
            [packet["alternate_same_slot_run"], packet["invalidated_same_slot_run"]],
        )
        self.assertEqual(
            [], list(definition_validator("aggregate").iter_errors(packet["aggregate"]))
        )

        foreign_manifest = copy.deepcopy(packet["manifest"])
        foreign_manifest["created_at"] = "2026-07-12T00:00:01Z"
        foreign_run = build_evaluation_run(
            foreign_manifest,
            run_id="eval_ForeignSemanticRerank1",
            scenario_id="projectodyssey",
            variant_id="semantic_rerank",
        )
        validate_run(
            foreign_run,
            foreign_manifest,
            artifact_bytes=packet["artifact_bytes"],
            source_ledger=packet["all_source_ledgers"]["projectodyssey"],
        )

        canonical_run = packet["canonical_same_slot_run"]
        alternate_run = packet["alternate_same_slot_run"]
        invalidated_run = packet["invalidated_same_slot_run"]
        finalization_states = {
            alternate_run["run_id"]: "retained_non_authoritative",
            invalidated_run["run_id"]: "invalidated_technical",
        }
        cases = []

        omitted_packet = copy.deepcopy(packet)
        omitted_packet["retained_attempt_authority"]["entries"] = [
            entry
            for entry in omitted_packet["retained_attempt_authority"]["entries"]
            if entry["run_id"] != alternate_run["run_id"]
        ]
        omitted_packet["retained_attempt_loader"] = (
            TestOnlyTrustedRetainedAttemptLoader(
                omitted_packet["retained_attempt_authority"]
            )
        )
        cases.append(
            {
                "name": "omitted_retained_record",
                "packet": omitted_packet,
                "aggregate": omitted_packet["aggregate"],
                "pointer": "/retained_attempt_authority/population_sha256",
                "detail": (
                    "retained_attempt_authority population_sha256 must match "
                    "the finalized retained entry set"
                ),
            }
        )

        alternate_packet = copy.deepcopy(packet)
        alternate_contributors = self._replace_contributor(
            alternate_packet,
            canonical_run["run_id"],
            alternate_packet["alternate_same_slot_run"],
        )
        alternate_packet["aggregate"] = self._rebuild_runtime_aggregate(
            alternate_packet, alternate_contributors
        )
        cases.append(
            {
                "name": "alternate_valid_same_slot_occupant",
                "packet": alternate_packet,
                "aggregate": alternate_packet["aggregate"],
                "pointer": "/run_ids/0",
                "detail": (
                    "run_ids must equal the accepted scope projection derived "
                    "from retained_attempt_authority"
                ),
            }
        )

        duplicate_packet = copy.deepcopy(packet)
        duplicate_retained_runs = [
            run
            for run in duplicate_packet["retained_runs"]
            if run["run_id"] != invalidated_run["run_id"]
        ]
        duplicate_packet["retained_attempt_authority"] = (
            build_test_only_retained_attempt_authority(
                duplicate_packet["manifest"],
                duplicate_retained_runs,
                finalization_states={
                    **finalization_states,
                    alternate_run["run_id"]: "accepted",
                },
            )
        )
        duplicate_packet["retained_attempt_loader"] = (
            TestOnlyTrustedRetainedAttemptLoader(
                duplicate_packet["retained_attempt_authority"]
            )
        )
        cases.append(
            {
                "name": "duplicate_accepted_occupancy",
                "packet": duplicate_packet,
                "aggregate": duplicate_packet["aggregate"],
                "pointer": "/retained_attempt_authority/entries",
                "detail": "exactly one accepted retained attempt must occupy each predeclared slot",
            }
        )

        cross_manifest_packet = copy.deepcopy(packet)
        cross_manifest_packet["retained_runs"].append(copy.deepcopy(foreign_run))
        cross_manifest_packet["artifact_bytes"][f"run_{foreign_run['run_id']}"] = (
            canonical_json_bytes(foreign_run)
        )
        cross_manifest_packet["retained_attempt_authority"] = (
            build_test_only_retained_attempt_authority(
                cross_manifest_packet["manifest"],
                cross_manifest_packet["retained_runs"],
                finalization_states={
                    **finalization_states,
                    foreign_run["run_id"]: "retained_non_authoritative",
                },
            )
        )
        cross_manifest_packet["retained_attempt_loader"] = (
            TestOnlyTrustedRetainedAttemptLoader(
                cross_manifest_packet["retained_attempt_authority"]
            )
        )
        cases.append(
            {
                "name": "cross_manifest_retained_record",
                "packet": cross_manifest_packet,
                "aggregate": cross_manifest_packet["aggregate"],
                "pointer": "/retained_attempt_authority/entries/62/execution_manifest_sha256",
                "detail": (
                    "retained attempts must bind the aggregate "
                    "execution_manifest_sha256"
                ),
            }
        )

        invalidated_packet = copy.deepcopy(packet)
        invalidated_contributors = self._replace_contributor(
            invalidated_packet,
            canonical_run["run_id"],
            invalidated_packet["invalidated_same_slot_run"],
        )
        invalidated_packet["aggregate"] = self._rebuild_runtime_aggregate(
            invalidated_packet, invalidated_contributors
        )
        invalidated_packet["retained_attempt_authority"] = (
            build_test_only_retained_attempt_authority(
                invalidated_packet["manifest"],
                invalidated_packet["retained_runs"],
                finalization_states={
                    **finalization_states,
                    canonical_run["run_id"]: "retained_non_authoritative",
                    invalidated_run["run_id"]: "accepted",
                },
            )
        )
        invalidated_packet["retained_attempt_loader"] = (
            TestOnlyTrustedRetainedAttemptLoader(
                invalidated_packet["retained_attempt_authority"]
            )
        )
        cases.append(
            {
                "name": "invalidated_attempt_admitted",
                "packet": invalidated_packet,
                "aggregate": invalidated_packet["aggregate"],
                "pointer": "/retained_attempt_authority/entries/59/finalization_state",
                "detail": "invalidated retained attempts cannot enter the accepted-run universe",
            }
        )

        for case in cases:
            with self.subTest(case=case["name"]):
                self.assertEqual(
                    [],
                    list(
                        definition_validator("aggregate").iter_errors(case["aggregate"])
                    ),
                )

        validate = self._assert_aggregate_missing_api(
            evidence_module, [case["name"] for case in cases]
        )
        for case in cases:
            with self.subTest(case=case["name"]):
                self._assert_semantic_reject_detail(
                    validate,
                    case["aggregate"],
                    code="invalid_aggregate",
                    pointer=case["pointer"],
                    detail=case["detail"],
                    **self._aggregate_validate_kwargs(case["packet"]),
                )

    def test_false_supersession_cross_scenario_reuse_is_the_only_aggregate_conflict_rule(
        self,
    ):
        evidence_module = _import_evidence()
        validate_run = evidence_module.validate_legacy_evaluation_run_diagnostic
        packet = build_test_only_simulated_cross_scenario_false_supersession_conflict_packet()
        self._validate_runs(validate_run, packet, packet["contributors"])
        self.assertEqual(
            [], list(definition_validator("aggregate").iter_errors(packet["aggregate"]))
        )
        self.assertEqual(
            {
                "metric_id": "false_supersession_rate",
                "n": 3,
                "numerator": 0,
                "denominator": 3,
                "rate": 0.0,
            },
            packet["aggregate"]["metrics"][0],
        )

        validate = self._assert_aggregate_missing_api(
            evidence_module, ["cross_scenario_reuse"]
        )
        self._assert_semantic_reject_detail(
            validate,
            packet["aggregate"],
            code="invalid_aggregate",
            pointer="/metrics/0",
            detail=(
                "false_supersession_rate must reject opportunity_id groups "
                "reused across scenarios"
            ),
            **self._aggregate_validate_kwargs(packet),
        )

    def test_retained_attempt_loader_must_be_a_capability_not_a_mapping(self):
        packet = build_test_only_simulated_runtime_contract_scope_packet()
        validate = self._assert_aggregate_missing_api(
            _import_evidence(), ["retained_loader_capability"]
        )
        invalid_loaders = {
            "mapping": packet["retained_attempt_authority"],
            "missing_method": object(),
            "non_callable_method": type(
                "NonCallableLoader", (), {"load_finalized_population": None}
            )(),
        }
        for name, loader in invalid_loaders.items():
            with self.subTest(loader=name):
                kwargs = self._aggregate_validate_kwargs(packet)
                kwargs["retained_attempt_loader"] = loader
                self._assert_semantic_reject_detail(
                    validate,
                    packet["aggregate"],
                    code="invalid_aggregate",
                    pointer="/retained_attempt_loader",
                    detail="retained_attempt_loader failed evaluator-owned capability check",
                    **kwargs,
                )

    def test_retained_authority_snapshot_finalization_count_hash_and_order_are_authenticated(
        self,
    ):
        packet = build_test_only_simulated_runtime_contract_scope_packet()
        validate = self._assert_aggregate_missing_api(
            _import_evidence(), ["retained_snapshot_integrity"]
        )
        cases = []

        not_finalized = copy.deepcopy(packet["retained_attempt_authority"])
        not_finalized["authority_state"] = "open"
        cases.append(
            (
                "state",
                not_finalized,
                "/retained_attempt_authority/authority_state",
                "retained attempt authority snapshot must be finalized",
            )
        )

        wrong_count = copy.deepcopy(packet["retained_attempt_authority"])
        wrong_count["entry_count"] += 1
        cases.append(
            (
                "count",
                wrong_count,
                "/retained_attempt_authority/entry_count",
                "entry_count must match the retained entry set",
            )
        )

        wrong_hash = copy.deepcopy(packet["retained_attempt_authority"])
        wrong_hash["population_sha256"] = "0" * 64
        cases.append(
            (
                "hash",
                wrong_hash,
                "/retained_attempt_authority/population_sha256",
                "population_sha256 must match the finalized retained entry set",
            )
        )

        duplicate_order = copy.deepcopy(packet["retained_attempt_authority"])
        duplicate_order["entries"][1]["registration_order"] = 0
        duplicate_order["population_sha256"] = canonical_sha256(
            duplicate_order["entries"]
        )
        cases.append(
            (
                "order",
                duplicate_order,
                "/retained_attempt_authority/entries",
                "registration_order must be unique and contiguous from 0",
            )
        )

        mismatched_state = copy.deepcopy(packet["retained_attempt_authority"])
        mismatched_state["entries"][0]["finalization_state"] = "invalidated_technical"
        mismatched_state["population_sha256"] = canonical_sha256(
            mismatched_state["entries"]
        )
        cases.append(
            (
                "state_designation",
                mismatched_state,
                "/retained_attempt_authority/entries/0/finalization_state",
                "finalization_state must match the retained run designation",
            )
        )

        for name, authority, pointer, detail in cases:
            with self.subTest(case=name):
                kwargs = self._aggregate_validate_kwargs(packet)
                kwargs["retained_attempt_loader"] = (
                    TestOnlyTrustedRetainedAttemptLoader(authority)
                )
                self._assert_semantic_reject_detail(
                    validate,
                    packet["aggregate"],
                    code="invalid_aggregate",
                    pointer=pointer,
                    detail=detail,
                    **kwargs,
                )

    def test_claim_id_type_binding_and_claim_metric_compatibility_are_literal(self):
        packet = build_test_only_simulated_runtime_contract_scope_packet()
        validate = self._assert_aggregate_missing_api(
            _import_evidence(), ["claim_binding_and_metric_compatibility"]
        )

        unknown_claim = copy.deepcopy(packet["aggregate"])
        unknown_claim["claim_id"] = "claim_unknown"
        self._assert_semantic_reject_detail(
            validate,
            unknown_claim,
            code="invalid_aggregate",
            pointer="/claim_id",
            detail="claim_id must resolve to exactly one manifest claim declaration",
            **self._aggregate_validate_kwargs(packet),
        )

        wrong_type = self._metric_report(
            packet,
            metric_id="downstream_full_suite_success",
            n=3,
            numerator=3,
            denominator=3,
            rate=1.0,
            claim_id="claim_structural_runtime",
            claim_type="downstream_superiority",
        )
        self._assert_semantic_reject_detail(
            validate,
            wrong_type,
            code="invalid_aggregate",
            pointer="/claim_type",
            detail="claim_type must equal the resolved manifest claim declaration",
            **self._aggregate_validate_kwargs(packet),
        )

        incompatible = copy.deepcopy(packet["aggregate"])
        incompatible["metrics"][0]["metric_id"] = "downstream_full_suite_success"
        self._assert_semantic_reject_detail(
            validate,
            incompatible,
            code="invalid_aggregate",
            pointer="/metrics/0/metric_id",
            detail="'downstream_full_suite_success' is not one of",
            **self._aggregate_validate_kwargs(packet),
        )

    def test_scope_projection_adverse_runs_and_artifact_hashes_must_be_exact(self):
        packet = build_test_only_simulated_runtime_contract_scope_packet()
        validate = self._assert_aggregate_missing_api(
            _import_evidence(), ["exact_scope_adverse_and_hash_projection"]
        )
        mutations = []

        omitted = copy.deepcopy(packet["aggregate"])
        omitted["run_ids"] = omitted["run_ids"][1:]
        omitted["artifact_hashes"] = build_aggregate_artifact_hashes(
            packet["manifest"], packet["contributors"][1:]
        )
        mutations.append(
            (omitted, "/run_ids", "run_ids must equal the accepted scope projection")
        )

        wrong_adverse = copy.deepcopy(packet["aggregate"])
        wrong_adverse["adverse_run_ids"] = [wrong_adverse["run_ids"][0]]
        mutations.append(
            (
                wrong_adverse,
                "/adverse_run_ids",
                "adverse_run_ids must equal the adverse contributing run subset",
            )
        )

        extra_hash = copy.deepcopy(packet["aggregate"])
        extra_hash["artifact_hashes"]["run:eval_Extra"] = "0" * 64
        mutations.append(
            (
                extra_hash,
                "/artifact_hashes",
                "artifact_hashes must contain exactly execution_manifest and contributing run hashes",
            )
        )

        wrong_hash = copy.deepcopy(packet["aggregate"])
        wrong_hash["artifact_hashes"][f"run:{wrong_hash['run_ids'][0]}"] = "0" * 64
        mutations.append(
            (
                wrong_hash,
                f"/artifact_hashes/run:{wrong_hash['run_ids'][0]}",
                "contributing run hash must equal the canonical retained run hash",
            )
        )

        unknown_scenario = copy.deepcopy(packet["aggregate"])
        unknown_scenario["scope"]["scenario_ids"].append("unknown-scenario")
        mutations.append(
            (
                unknown_scenario,
                "/scope/scenario_ids/1",
                "scope scenario_ids must resolve to manifest execution slots",
            )
        )

        for aggregate, pointer, detail in mutations:
            with self.subTest(pointer=pointer):
                self._assert_semantic_reject_detail(
                    validate,
                    aggregate,
                    code="invalid_aggregate",
                    pointer=pointer,
                    detail=detail,
                    **self._aggregate_validate_kwargs(packet),
                )


if __name__ == "__main__":
    unittest.main()
