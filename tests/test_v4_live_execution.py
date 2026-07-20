from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
import unittest

from recallpack.review_json import review_json_sha256


ROOT = Path(__file__).resolve().parents[1]
V3_MANIFEST = ROOT / "evaluation/evidence/execution-manifest.json"
PRIVATE_MANIFEST_SKIP_REASON = (
    "requires the private frozen execution manifest, which is intentionally "
    "excluded from the public submission bundle"
)


@unittest.skipUnless(V3_MANIFEST.is_file(), PRIVATE_MANIFEST_SKIP_REASON)
class FrozenLiveExecutionPlanTests(unittest.TestCase):
    def test_cycle_v3_derives_task_contracts_only_from_frozen_artifacts(self) -> None:
        from recallpack.v4_live_execution import build_frozen_live_execution_plan

        manifest = json.loads(V3_MANIFEST.read_text(encoding="utf-8"))
        plan = build_frozen_live_execution_plan(
            manifest,
            artifact_bytes=self._scenario_artifact_bytes(manifest),
        )

        self.assertEqual(review_json_sha256(manifest), plan.execution_manifest_sha256)
        self.assertEqual(
            [cell["slot_index"] for cell in manifest["execution_order"]],
            [cell.slot_index for cell in plan.cells],
        )
        self.assertEqual(
            [cell["slot_id"] for cell in manifest["execution_order"]],
            [cell.slot_id for cell in plan.cells],
        )
        contracts = {contract.scenario_slot: contract for contract in plan.scenario_contracts}
        self.assertEqual(
            "projectodyssey:turn-004",
            contracts["projectodyssey"].task_source_ref,
        )
        self.assertEqual(
            "Handoff task: update Mojo JIT crash handling without changing project dependencies.",
            contracts["projectodyssey"].goal,
        )
        self.assertEqual("ci_policy", contracts["projectodyssey"].component)
        self.assertEqual(
            ("pyproject.toml", "src/ci_policy.py"),
            contracts["projectodyssey"].allowed_edit_paths,
        )
        self.assertEqual("package_policy", contracts["deepagents"].component)
        self.assertEqual(
            ("pyproject.toml", "src/package_policy.py"),
            contracts["deepagents"].allowed_edit_paths,
        )

    def test_plan_rejects_missing_frozen_fixture_bytes(self) -> None:
        from recallpack.v4_live_execution import (
            FrozenLiveExecutionPlanError,
            build_frozen_live_execution_plan,
        )

        manifest = json.loads(V3_MANIFEST.read_text(encoding="utf-8"))
        artifact_bytes = self._scenario_artifact_bytes(manifest)
        del artifact_bytes["fixture_projectodyssey"]

        with self.assertRaisesRegex(
            FrozenLiveExecutionPlanError,
            r"missing_frozen_artifact_bytes: fixture_projectodyssey",
        ):
            build_frozen_live_execution_plan(manifest, artifact_bytes=artifact_bytes)

    def test_plan_rejects_no_scenario_specific_writable_path(self) -> None:
        from recallpack.v4_live_execution import (
            FrozenLiveExecutionPlanError,
            build_frozen_live_execution_plan,
        )

        manifest = json.loads(V3_MANIFEST.read_text(encoding="utf-8"))
        manifest = copy.deepcopy(manifest)
        manifest["comparison_contract"]["writable_paths"] = ["src/ci_policy.py"]

        with self.assertRaisesRegex(
            FrozenLiveExecutionPlanError,
            r"missing_scenario_writable_paths: deepagents",
        ):
            build_frozen_live_execution_plan(
                manifest,
                artifact_bytes=self._scenario_artifact_bytes(manifest),
            )

    def test_materializes_repository_from_frozen_bundle_without_gold_file(self) -> None:
        from recallpack.v4_live_execution import (
            build_frozen_live_execution_plan,
            materialize_frozen_repository,
        )

        manifest = json.loads(V3_MANIFEST.read_text(encoding="utf-8"))
        plan = build_frozen_live_execution_plan(
            manifest,
            artifact_bytes=self._scenario_artifact_bytes(manifest),
        )
        contract = next(
            item
            for item in plan.scenario_contracts
            if item.scenario_slot == "projectodyssey"
        )
        with tempfile.TemporaryDirectory() as temporary:
            repository_root = materialize_frozen_repository(
                contract,
                Path(temporary) / "repository",
            )

            self.assertEqual(
                "def handle_jit_crash(error_message):\n"
                "    return {\n"
                '        "action": "inspect",\n'
                '        "retry": False,\n'
                '        "retry_attempts": 0,\n'
                '        "continue_on_error": False,\n'
                '        "skip": False,\n'
                '        "minimal_reproducer_required": False,\n'
                "    }\n",
                (repository_root / "src/ci_policy.py").read_text(encoding="utf-8"),
            )
            self.assertFalse((repository_root / "gold.json").exists())

    def test_hidden_test_root_must_match_frozen_content_hash(self) -> None:
        from recallpack.v4_live_execution import (
            build_frozen_live_execution_plan,
            verify_frozen_hidden_test_root,
        )

        manifest = json.loads(V3_MANIFEST.read_text(encoding="utf-8"))
        plan = build_frozen_live_execution_plan(
            manifest,
            artifact_bytes=self._scenario_artifact_bytes(manifest),
        )
        contract = next(
            item
            for item in plan.scenario_contracts
            if item.scenario_slot == "projectodyssey"
        )

        verified_hash = verify_frozen_hidden_test_root(
            contract,
            ROOT / "evaluation/hidden-tests/projectodyssey",
        )

        self.assertEqual(contract.hidden_test_content_sha256, verified_hash)

    def test_prepares_patch_from_derived_contract_without_fixture_gold(self) -> None:
        from recallpack.v4_live_execution import (
            build_frozen_live_execution_plan,
            prepare_frozen_downstream_patch,
        )

        manifest = json.loads(V3_MANIFEST.read_text(encoding="utf-8"))
        plan = build_frozen_live_execution_plan(
            manifest,
            artifact_bytes=self._scenario_artifact_bytes(manifest),
        )
        contract = next(
            item
            for item in plan.scenario_contracts
            if item.scenario_slot == "projectodyssey"
        )
        provider = _RecordingPatchProvider(
            path="src/ci_policy.py",
            content=next(
                item.content.decode("utf-8")
                for item in contract.repository_files
                if item.path == "src/ci_policy.py"
            ).replace('"action": "inspect"', '"action": "fail_and_fix_forward"'),
        )

        prepared = prepare_frozen_downstream_patch(
            contract,
            selected_context=[
                {
                    "source_ref": "projectodyssey:turn-002",
                    "text": "Treat the JIT crash as a real bug and fix forward.",
                }
            ],
            variant_id="recallpack",
            patch_provider=provider,
        )

        self.assertTrue(prepared["accepted"])
        self.assertEqual(1, len(provider.calls))
        request = provider.calls[0]
        self.assertEqual(contract.goal, request.goal)
        self.assertEqual(list(contract.allowed_edit_paths), request.allowed_paths)
        self.assertEqual(
            ["pyproject.toml", "src/ci_policy.py"],
            [item["path"] for item in request.source_files],
        )
        self.assertNotIn("gold", "\n".join(request.source_files[0].values()))

    def test_semantic_selection_uses_frozen_events_embedding_then_rerank(self) -> None:
        from recallpack.v4_live_execution import (
            FrozenExecutionProviders,
            build_frozen_live_execution_plan,
            select_frozen_context,
        )

        manifest = json.loads(V3_MANIFEST.read_text(encoding="utf-8"))
        plan = build_frozen_live_execution_plan(
            manifest,
            artifact_bytes=self._scenario_artifact_bytes(manifest),
        )
        contract = next(
            item
            for item in plan.scenario_contracts
            if item.scenario_slot == "projectodyssey"
        )
        embedding = _SequencedEmbeddingProvider()
        rerank = _RecordingRerankProvider()

        selection = select_frozen_context(
            contract,
            variant_id="semantic_rerank",
            providers=FrozenExecutionProviders(
                embedding_provider_factory=lambda: embedding,
                rerank_provider_factory=lambda: rerank,
            ),
        )

        self.assertTrue(selection.budget_comparable)
        self.assertEqual(
            (
                "projectodyssey:turn-002",
                "projectodyssey:turn-001",
                "projectodyssey:turn-003",
            ),
            selection.selected_source_refs,
        )
        self.assertEqual(4, len(embedding.calls))
        self.assertEqual(1, len(rerank.calls))
        self.assertEqual(
            ["embedding", "embedding", "embedding", "embedding", "rerank"],
            [trace["role"] for trace in selection.provider_traces],
        )
        self.assertTrue(all("source_ref" not in item for item in selection.selected_context))

    def test_recallpack_selection_uses_observe_then_active_only_compile(self) -> None:
        from recallpack.v4_live_execution import (
            FrozenExecutionProviders,
            build_frozen_live_execution_plan,
            select_frozen_context,
        )

        manifest = json.loads(V3_MANIFEST.read_text(encoding="utf-8"))
        plan = build_frozen_live_execution_plan(
            manifest,
            artifact_bytes=self._scenario_artifact_bytes(manifest),
        )
        contract = next(
            item
            for item in plan.scenario_contracts
            if item.scenario_slot == "projectodyssey"
        )
        embedding = _SequencedEmbeddingProvider()
        rerank = _RecordingRerankProvider()
        memory = _SequencedMemoryDecisionProvider(
            [
                _write_decision(
                    "ci_policy",
                    "Treat the JIT crash as a compiler flake and retry.",
                    "ci_policy",
                ),
                _write_decision(
                    "ci_policy",
                    "Treat the JIT crash as a bug and fix forward.",
                    "ci_policy",
                    supersedes=[0],
                ),
                _write_preference(
                    "dependency_policy",
                    "Do not add new dependencies.",
                ),
            ]
        )

        selection = select_frozen_context(
            contract,
            variant_id="recallpack",
            providers=FrozenExecutionProviders(
                embedding_provider_factory=lambda: embedding,
                rerank_provider_factory=lambda: rerank,
                memory_provider_factory=lambda: memory,
            ),
        )

        self.assertTrue(selection.budget_comparable)
        self.assertEqual(
            ("projectodyssey:turn-002", "projectodyssey:turn-003"),
            selection.selected_source_refs,
        )
        self.assertNotIn("projectodyssey:turn-001", selection.selected_source_refs)
        self.assertEqual(3, len(memory.calls))
        self.assertEqual(1, len(rerank.calls))
        self.assertIn("persisted_write_time_lifecycle", selection.execution_trace["selection_source"])
        self.assertEqual(
            {"memory_decision", "embedding", "rerank"},
            {trace["role"] for trace in selection.provider_traces},
        )

    def test_recall_time_resolver_resolves_only_retrieved_raw_events(self) -> None:
        from recallpack.v4_live_execution import (
            FrozenExecutionProviders,
            build_frozen_live_execution_plan,
            select_frozen_context,
        )

        manifest = json.loads(V3_MANIFEST.read_text(encoding="utf-8"))
        plan = build_frozen_live_execution_plan(
            manifest,
            artifact_bytes=self._scenario_artifact_bytes(manifest),
        )
        contract = next(
            item
            for item in plan.scenario_contracts
            if item.scenario_slot == "projectodyssey"
        )
        embedding = _SequencedEmbeddingProvider()
        rerank = _RecordingRerankProvider()
        memory = _SequencedMemoryDecisionProvider(
            [
                _write_decision(
                    "ci_policy",
                    "Treat the JIT crash as a compiler flake and retry.",
                    "ci_policy",
                ),
                _write_decision(
                    "ci_policy",
                    "Treat the JIT crash as a bug and fix forward.",
                    "ci_policy",
                    supersedes=[0],
                ),
                _write_preference(
                    "dependency_policy",
                    "Do not add new dependencies.",
                ),
            ]
        )

        selection = select_frozen_context(
            contract,
            variant_id="recall_time_resolver",
            providers=FrozenExecutionProviders(
                embedding_provider_factory=lambda: embedding,
                rerank_provider_factory=lambda: rerank,
                memory_provider_factory=lambda: memory,
            ),
        )

        self.assertTrue(selection.budget_comparable)
        self.assertEqual(
            ("projectodyssey:turn-002", "projectodyssey:turn-003"),
            selection.selected_source_refs,
        )
        self.assertFalse(selection.execution_trace["persisted_lifecycle_used"])
        self.assertEqual(3, len(memory.calls))
        self.assertEqual(1, len(rerank.calls))

    def test_executes_one_registered_cell_and_retains_patch_trace_before_isolation(self) -> None:
        from recallpack.v4_live_execution import (
            FrozenExecutionProviders,
            build_frozen_live_execution_plan,
            execute_frozen_live_cell,
        )

        manifest = json.loads(V3_MANIFEST.read_text(encoding="utf-8"))
        plan = build_frozen_live_execution_plan(
            manifest,
            artifact_bytes=self._scenario_artifact_bytes(manifest),
        )
        cell = next(
            item
            for item in plan.cells
            if item.scenario_slot == "projectodyssey" and item.variant_id == "recallpack"
        )
        contract = next(
            item
            for item in plan.scenario_contracts
            if item.scenario_slot == "projectodyssey"
        )
        patch_provider = _RecordingPatchProvider(
            path="src/ci_policy.py",
            content=next(
                item.content.decode("utf-8")
                for item in contract.repository_files
                if item.path == "src/ci_policy.py"
            ).replace('"action": "inspect"', '"action": "fail_and_fix_forward"'),
        )
        result = execute_frozen_live_cell(
            plan,
            slot_index=cell.slot_index,
            providers=FrozenExecutionProviders(
                embedding_provider_factory=_SequencedEmbeddingProvider,
                rerank_provider_factory=_RecordingRerankProvider,
                memory_provider_factory=lambda: _SequencedMemoryDecisionProvider(
                    [
                        _write_decision(
                            "ci_policy",
                            "Treat the JIT crash as a compiler flake and retry.",
                            "ci_policy",
                        ),
                        _write_decision(
                            "ci_policy",
                            "Treat the JIT crash as a bug and fix forward.",
                            "ci_policy",
                            supersedes=[0],
                        ),
                        _write_preference(
                            "dependency_policy",
                            "Do not add new dependencies.",
                        ),
                    ]
                ),
                patch_provider_factory=lambda: patch_provider,
            ),
        )

        self.assertEqual(cell, result.cell)
        self.assertEqual(contract.scenario_slot, result.contract.scenario_slot)
        self.assertEqual(
            ("projectodyssey:turn-002", "projectodyssey:turn-003"),
            result.selection.selected_source_refs,
        )
        self.assertTrue(result.downstream["accepted"])
        self.assertEqual(["src/ci_policy.py"], [item["path"] for item in result.generated_files])
        self.assertEqual(
            {
                "status": "incomplete",
                "stage": "isolated_evaluation",
                "code": "not_run",
            },
            result.attempt_outcome,
        )
        self.assertEqual("not_run", result.execution_trace["isolated_evaluation"])
        self.assertEqual(1, len(patch_provider.calls))
        self.assertEqual(
            {"memory_decision", "embedding", "rerank", "patch_generation"},
            {trace["role"] for trace in result.provider_traces},
        )

    def test_authorized_execution_orders_provider_then_output_fixation(self) -> None:
        from recallpack.v4_live_execution import (
            FrozenExecutionProviders,
            build_frozen_live_execution_plan,
            execute_authorized_frozen_live_cell,
            frozen_model_output_sha256,
        )

        manifest = json.loads(V3_MANIFEST.read_text(encoding="utf-8"))
        plan = build_frozen_live_execution_plan(
            manifest,
            artifact_bytes=self._scenario_artifact_bytes(manifest),
        )
        cell = plan.cells[0]
        contract = next(
            item
            for item in plan.scenario_contracts
            if item.scenario_slot == cell.scenario_slot
        )
        authority = _RecordingFrozenExecutionAuthority()
        patch_provider = _RecordingPatchProvider(
            path="src/ci_policy.py",
            content=next(
                item.content.decode("utf-8")
                for item in contract.repository_files
                if item.path == "src/ci_policy.py"
            ).replace('"action": "inspect"', '"action": "retry_workaround"'),
        )

        authorized = execute_authorized_frozen_live_cell(
            plan,
            slot_index=cell.slot_index,
            providers=FrozenExecutionProviders(
                patch_provider_factory=lambda: patch_provider,
            ),
            authority=authority,
        )

        self.assertEqual(cell.slot_id, authorized.result.cell.slot_id)
        self.assertEqual(1, len(patch_provider.calls))
        self.assertEqual(
            [
                ("authorize", cell.slot_id, cell.repetition),
                (
                    "fix",
                    cell.slot_id,
                    cell.repetition,
                    frozen_model_output_sha256(authorized.result),
                    authorized.result.generated_files_sha256,
                ),
            ],
            authority.calls,
        )

    def test_authorized_execution_does_not_call_provider_when_authority_rejects(self) -> None:
        from recallpack.v4_live_execution import (
            FrozenExecutionProviders,
            FrozenLiveExecutionPlanError,
            build_frozen_live_execution_plan,
            execute_authorized_frozen_live_cell,
        )

        manifest = json.loads(V3_MANIFEST.read_text(encoding="utf-8"))
        plan = build_frozen_live_execution_plan(
            manifest,
            artifact_bytes=self._scenario_artifact_bytes(manifest),
        )
        patch_provider = _EmptyPatchProvider()

        with self.assertRaisesRegex(
            FrozenLiveExecutionPlanError,
            r"provider_action_not_authorized",
        ):
            execute_authorized_frozen_live_cell(
                plan,
                slot_index=0,
                providers=FrozenExecutionProviders(
                    patch_provider_factory=lambda: patch_provider,
                ),
                authority=_RejectingFrozenExecutionAuthority(),
            )
        self.assertEqual(0, len(patch_provider.calls))

    def test_authorized_execution_requires_output_fixation_authority_before_provider(self) -> None:
        from recallpack.v4_live_execution import (
            FrozenExecutionProviders,
            FrozenLiveExecutionPlanError,
            build_frozen_live_execution_plan,
            execute_authorized_frozen_live_cell,
        )

        manifest = json.loads(V3_MANIFEST.read_text(encoding="utf-8"))
        plan = build_frozen_live_execution_plan(
            manifest,
            artifact_bytes=self._scenario_artifact_bytes(manifest),
        )
        patch_provider = _EmptyPatchProvider()

        with self.assertRaisesRegex(
            FrozenLiveExecutionPlanError,
            r"invalid_frozen_execution_authority",
        ):
            execute_authorized_frozen_live_cell(
                plan,
                slot_index=0,
                providers=FrozenExecutionProviders(
                    patch_provider_factory=lambda: patch_provider,
                ),
                authority=_AuthorizeOnlyFrozenExecutionAuthority(),
            )
        self.assertEqual(0, len(patch_provider.calls))

    def test_production_isolation_requires_matching_authorized_output_fixation(self) -> None:
        from recallpack.isolation import ProductionExecutionIdentity
        from recallpack.v4_live_execution import (
            FrozenExecutionProviders,
            FrozenLiveExecutionPlanError,
            build_frozen_live_execution_plan,
            execute_authorized_frozen_live_cell,
            execute_frozen_live_cell,
            run_frozen_live_cell_isolated,
        )

        manifest = json.loads(V3_MANIFEST.read_text(encoding="utf-8"))
        plan = build_frozen_live_execution_plan(
            manifest,
            artifact_bytes=self._scenario_artifact_bytes(manifest),
        )
        cell = plan.cells[0]
        contract = next(
            item
            for item in plan.scenario_contracts
            if item.scenario_slot == cell.scenario_slot
        )
        source = next(
            item.content.decode("utf-8")
            for item in contract.repository_files
            if item.path == "src/ci_policy.py"
        )
        identity = ProductionExecutionIdentity(
            execution_manifest_sha256=plan.execution_manifest_sha256,
            scenario_id=cell.scenario_slot,
            slot_index=cell.slot_index,
            attempt_no=cell.repetition,
            repository_snapshot_sha256="1" * 64,
            hidden_test_tree_sha256=contract.hidden_test_content_sha256,
        )
        direct = execute_frozen_live_cell(
            plan,
            slot_index=cell.slot_index,
            providers=FrozenExecutionProviders(
                patch_provider_factory=lambda: _RecordingPatchProvider(
                    path="src/ci_policy.py",
                    content=source.replace('"action": "inspect"', '"action": "retry_workaround"'),
                ),
            ),
        )

        with self.assertRaisesRegex(
            FrozenLiveExecutionPlanError,
            r"production_output_fixation_required",
        ):
            run_frozen_live_cell_isolated(
                direct,
                hidden_test_root=ROOT / "missing-hidden-tests",
                evaluator_contract={},
                suite_runner=_CapturingFrozenIsolatedRunner(),
                production_execution_identity=identity,
            )

        authorized = execute_authorized_frozen_live_cell(
            plan,
            slot_index=cell.slot_index,
            providers=FrozenExecutionProviders(
                patch_provider_factory=lambda: _RecordingPatchProvider(
                    path="src/ci_policy.py",
                    content=source.replace('"action": "inspect"', '"action": "retry_workaround"'),
                ),
            ),
            authority=_RecordingFrozenExecutionAuthority(),
        )
        authorized.result.execution_trace["selected_context_token_count"] += 1
        with self.assertRaisesRegex(
            FrozenLiveExecutionPlanError,
            r"frozen_output_fixation_mismatch",
        ):
            run_frozen_live_cell_isolated(
                authorized.result,
                hidden_test_root=ROOT / "missing-hidden-tests",
                evaluator_contract={},
                suite_runner=_CapturingFrozenIsolatedRunner(),
                production_execution_identity=identity,
                output_fixation=authorized.output_fixation,
            )

    def test_test_only_isolation_cannot_append_to_production_runner_journal(self) -> None:
        from recallpack.evaluation_docker import build_runtime_evaluator_contract
        from recallpack.evidence_pipeline import ProductionRunnerOutputJournal
        from recallpack.v4_live_execution import (
            FrozenExecutionProviders,
            FrozenLiveExecutionPlanError,
            append_authorized_frozen_runner_output,
            build_frozen_live_execution_plan,
            build_frozen_production_execution_identity,
            execute_authorized_frozen_live_cell,
            run_frozen_live_cell_isolated,
        )

        manifest = json.loads(V3_MANIFEST.read_text(encoding="utf-8"))
        plan = build_frozen_live_execution_plan(
            manifest,
            artifact_bytes=self._scenario_artifact_bytes(manifest),
        )
        cell = plan.cells[0]
        contract = next(
            item
            for item in plan.scenario_contracts
            if item.scenario_slot == cell.scenario_slot
        )
        source = next(
            item.content.decode("utf-8")
            for item in contract.repository_files
            if item.path == "src/ci_policy.py"
        )
        authorized = execute_authorized_frozen_live_cell(
            plan,
            slot_index=cell.slot_index,
            providers=FrozenExecutionProviders(
                patch_provider_factory=lambda: _RecordingPatchProvider(
                    path="src/ci_policy.py",
                    content=source.replace(
                        '"action": "inspect"',
                        '"action": "retry_workaround"',
                    ),
                ),
            ),
            authority=_RecordingFrozenExecutionAuthority(),
        )
        evaluator_contract = build_runtime_evaluator_contract(
            platform="linux/arm64",
            image_digest="sha256:" + "1" * 64,
            base_image_digest="sha256:" + "2" * 64,
        )
        isolated = run_frozen_live_cell_isolated(
            authorized.result,
            hidden_test_root=ROOT / "evaluation/hidden-tests/projectodyssey",
            evaluator_contract=evaluator_contract,
            suite_runner=_CapturingFrozenIsolatedRunner(),
        )
        identity = build_frozen_production_execution_identity(authorized.result)
        journal = ProductionRunnerOutputJournal(plan.execution_manifest_sha256)

        with self.assertRaisesRegex(
            FrozenLiveExecutionPlanError,
            r"production_runner_output_rejected",
        ):
            append_authorized_frozen_runner_output(
                authorized,
                isolated_result=isolated,
                evaluator_contract=evaluator_contract,
                production_execution_identity=identity,
                runner_output_journal=journal,
            )

    def test_authorized_patch_rejection_is_sealed_without_hidden_test_access(self) -> None:
        from recallpack.evaluation_docker import build_runtime_evaluator_contract
        from recallpack.evidence_pipeline import ProductionRunnerOutputJournal
        from recallpack.isolation import has_valid_production_execution_receipt
        from recallpack.v4_live_execution import (
            FrozenExecutionProviders,
            append_authorized_frozen_runner_output,
            build_frozen_live_execution_plan,
            build_frozen_production_execution_identity,
            execute_authorized_frozen_live_cell,
            run_frozen_live_cell_isolated,
        )

        manifest = json.loads(V3_MANIFEST.read_text(encoding="utf-8"))
        plan = build_frozen_live_execution_plan(
            manifest,
            artifact_bytes=self._scenario_artifact_bytes(manifest),
        )
        authority = _RecordingFrozenExecutionAuthority()
        authorized = execute_authorized_frozen_live_cell(
            plan,
            slot_index=0,
            providers=FrozenExecutionProviders(
                patch_provider_factory=_EmptyPatchProvider,
            ),
            authority=authority,
        )
        self.assertEqual("adverse", authorized.result.attempt_outcome["status"])
        self.assertEqual("patch_generation", authorized.result.attempt_outcome["stage"])
        identity = build_frozen_production_execution_identity(authorized.result)
        evaluator_contract = build_runtime_evaluator_contract(
            platform="linux/arm64",
            image_digest="sha256:" + "1" * 64,
            base_image_digest="sha256:" + "2" * 64,
        )

        isolated = run_frozen_live_cell_isolated(
            authorized.result,
            hidden_test_root=ROOT / "missing-hidden-tests",
            evaluator_contract=evaluator_contract,
            production_execution_identity=identity,
            output_fixation=authorized.output_fixation,
        )

        self.assertTrue(isolated.blocked)
        self.assertEqual("empty_patch", isolated.failure_code)
        self.assertEqual("patch_not_executed", isolated.execution_binding.authority_mode)
        self.assertTrue(
            has_valid_production_execution_receipt(
                isolated,
                expected_identity=identity,
            )
        )
        journal = ProductionRunnerOutputJournal(plan.execution_manifest_sha256)
        output = append_authorized_frozen_runner_output(
            authorized,
            isolated_result=isolated,
            evaluator_contract=evaluator_contract,
            production_execution_identity=identity,
            runner_output_journal=journal,
        )
        self.assertEqual([], output["patched_files"])
        self.assertEqual(
            {"status": "adverse", "stage": "patch_generation", "code": "empty_patch"},
            output["attempt_outcome"],
        )
        finalized = journal.finalize()
        snapshot = finalized.load_finalized_runner_outputs(plan.execution_manifest_sha256)
        self.assertEqual(1, snapshot["entry_count"])

    def test_patch_rejection_is_retained_as_adverse_without_hidden_test_execution(self) -> None:
        from recallpack.v4_live_execution import (
            FrozenExecutionProviders,
            build_frozen_live_execution_plan,
            execute_frozen_live_cell,
        )

        manifest = json.loads(V3_MANIFEST.read_text(encoding="utf-8"))
        plan = build_frozen_live_execution_plan(
            manifest,
            artifact_bytes=self._scenario_artifact_bytes(manifest),
        )
        cell = next(
            item
            for item in plan.cells
            if item.scenario_slot == "projectodyssey"
            and item.variant_id == "raw_full_history"
        )
        provider = _EmptyPatchProvider()

        result = execute_frozen_live_cell(
            plan,
            slot_index=cell.slot_index,
            providers=FrozenExecutionProviders(
                patch_provider_factory=lambda: provider,
            ),
        )

        self.assertFalse(result.downstream["accepted"])
        self.assertEqual("empty_patch", result.downstream["error"])
        self.assertEqual(
            {
                "status": "adverse",
                "stage": "patch_generation",
                "code": "empty_patch",
            },
            result.attempt_outcome,
        )
        self.assertEqual("not_run", result.execution_trace["isolated_evaluation"])
        self.assertEqual(1, len(provider.calls))
        self.assertEqual(
            ["patch_generation"],
            [trace["role"] for trace in result.provider_traces],
        )

    def test_pre_isolation_journal_enforces_registered_slot_order_and_retains_results(self) -> None:
        from recallpack.v4_live_execution import (
            FrozenExecutionProviders,
            FrozenPreIsolationJournal,
            FrozenLiveExecutionPlanError,
            build_frozen_live_execution_plan,
        )

        manifest = json.loads(V3_MANIFEST.read_text(encoding="utf-8"))
        plan = build_frozen_live_execution_plan(
            manifest,
            artifact_bytes=self._scenario_artifact_bytes(manifest),
        )
        provider = _EmptyPatchProvider()
        providers = FrozenExecutionProviders(patch_provider_factory=lambda: provider)
        journal = FrozenPreIsolationJournal(plan)

        with self.assertRaisesRegex(
            FrozenLiveExecutionPlanError,
            r"expected_execution_slot_index: 0",
        ):
            journal.execute(slot_index=1, providers=providers)

        first = journal.execute(slot_index=0, providers=providers)
        self.assertEqual(0, first.cell.slot_index)
        self.assertEqual(1, journal.record_count)
        self.assertEqual((first,), journal.results())

        with self.assertRaisesRegex(
            FrozenLiveExecutionPlanError,
            r"expected_execution_slot_index: 1",
        ):
            journal.execute(slot_index=0, providers=providers)

        second = journal.execute(slot_index=1, providers=providers)
        self.assertEqual(1, second.cell.slot_index)
        self.assertEqual(2, journal.record_count)
        self.assertEqual((0, 1), tuple(item.cell.slot_index for item in journal.results()))
        self.assertEqual(2, len(provider.calls))

    def test_pre_isolation_journal_authorizes_fixed_output_in_manifest_order(self) -> None:
        from recallpack.v4_live_execution import (
            FrozenExecutionProviders,
            FrozenLiveExecutionPlanError,
            FrozenPreIsolationJournal,
            build_frozen_live_execution_plan,
        )

        manifest = json.loads(V3_MANIFEST.read_text(encoding="utf-8"))
        plan = build_frozen_live_execution_plan(
            manifest,
            artifact_bytes=self._scenario_artifact_bytes(manifest),
        )
        journal = FrozenPreIsolationJournal(plan)
        authority = _RecordingFrozenExecutionAuthority()
        provider = _EmptyPatchProvider()

        authorized = journal.execute_authorized(
            slot_index=0,
            providers=FrozenExecutionProviders(
                patch_provider_factory=lambda: provider,
            ),
            authority=authority,
        )

        self.assertEqual(0, authorized.result.cell.slot_index)
        self.assertEqual(1, journal.record_count)
        self.assertEqual(
            ["authorize", "fix"],
            [call[0] for call in authority.calls],
        )
        self.assertEqual(1, len(provider.calls))
        with self.assertRaisesRegex(
            FrozenLiveExecutionPlanError,
            r"expected_execution_slot_index: 1",
        ):
            journal.execute_authorized(
                slot_index=0,
                providers=FrozenExecutionProviders(
                    patch_provider_factory=lambda: provider,
                ),
                authority=authority,
            )

    def test_pre_isolation_journal_retries_only_a_manifest_technical_patch_failure(self) -> None:
        from recallpack.v4_live_execution import (
            FrozenExecutionProviders,
            FrozenLiveExecutionPlanError,
            FrozenPreIsolationJournal,
            build_frozen_live_execution_plan,
        )

        manifest = json.loads(V3_MANIFEST.read_text(encoding="utf-8"))
        plan = build_frozen_live_execution_plan(
            manifest,
            artifact_bytes=self._scenario_artifact_bytes(manifest),
        )
        self.assertIn("provider_timeout", plan.technical_failure_codes)
        provider = _RetryableThenPatchProvider()
        journal = FrozenPreIsolationJournal(plan)
        providers = FrozenExecutionProviders(patch_provider_factory=lambda: provider)

        first = journal.execute(slot_index=0, providers=providers)
        self.assertEqual(1, first.attempt_no)
        self.assertEqual(
            {
                "status": "invalidated",
                "stage": "patch_generation",
                "code": "provider_timeout",
            },
            first.attempt_outcome,
        )
        from recallpack.v4_live_execution import run_frozen_live_cell_isolated

        with self.assertRaisesRegex(
            FrozenLiveExecutionPlanError,
            r"technical_pre_isolation_attempt_requires_retry",
        ):
            run_frozen_live_cell_isolated(
                first,
                hidden_test_root=ROOT / "missing-hidden-tests",
                evaluator_contract={},
                suite_runner=_CapturingFrozenIsolatedRunner(),
            )
        with self.assertRaisesRegex(
            FrozenLiveExecutionPlanError,
            r"expected_execution_slot_index: 0",
        ):
            journal.execute(slot_index=1, providers=providers)

        replacement = journal.execute(slot_index=0, providers=providers)
        self.assertEqual(2, replacement.attempt_no)
        self.assertEqual("incomplete", replacement.attempt_outcome["status"])
        self.assertEqual(2, journal.record_count)
        self.assertEqual((1, 2), tuple(item.attempt_no for item in journal.results()))

    def test_selection_provider_technical_failure_is_retained_before_patch_or_hidden_reveal(self) -> None:
        from recallpack.v4_live_execution import (
            FrozenExecutionProviders,
            build_frozen_live_execution_plan,
            execute_frozen_live_cell,
            run_frozen_live_cell_isolated,
        )

        manifest = json.loads(V3_MANIFEST.read_text(encoding="utf-8"))
        plan = build_frozen_live_execution_plan(
            manifest,
            artifact_bytes=self._scenario_artifact_bytes(manifest),
        )
        cell = next(
            item
            for item in plan.cells
            if item.scenario_slot == "projectodyssey"
            and item.variant_id == "semantic_rerank"
        )
        patch_provider = _EmptyPatchProvider()

        result = execute_frozen_live_cell(
            plan,
            slot_index=cell.slot_index,
            providers=FrozenExecutionProviders(
                embedding_provider_factory=_RetryableAfterStoredEmbeddingProvider,
                rerank_provider_factory=_RecordingRerankProvider,
                patch_provider_factory=lambda: patch_provider,
            ),
        )

        self.assertEqual("invalidated", result.attempt_outcome["status"])
        self.assertEqual("selection", result.attempt_outcome["stage"])
        self.assertEqual("provider_timeout", result.attempt_outcome["code"])
        self.assertFalse(result.downstream["accepted"])
        self.assertEqual([], list(result.generated_files))
        self.assertEqual(0, len(patch_provider.calls))
        self.assertEqual(["embedding"], [trace["role"] for trace in result.provider_traces])
        from recallpack.v4_live_execution import serialize_frozen_pre_isolation_record

        record = serialize_frozen_pre_isolation_record(result)
        self.assertEqual("embedding", record["provider_traces"][0]["role"])
        self.assertEqual("provider_timeout", record["attempt_outcome"]["code"])
        with self.assertRaisesRegex(
            Exception,
            r"technical_pre_isolation_attempt_requires_retry",
        ):
            run_frozen_live_cell_isolated(
                result,
                hidden_test_root=ROOT / "missing-hidden-tests",
                evaluator_contract={},
                suite_runner=_CapturingFrozenIsolatedRunner(),
            )

    def test_rerank_provider_technical_failure_retains_prior_embedding_traces(self) -> None:
        from recallpack.v4_live_execution import (
            FrozenExecutionProviders,
            build_frozen_live_execution_plan,
            execute_frozen_live_cell,
        )

        manifest = json.loads(V3_MANIFEST.read_text(encoding="utf-8"))
        plan = build_frozen_live_execution_plan(
            manifest,
            artifact_bytes=self._scenario_artifact_bytes(manifest),
        )
        cell = next(
            item
            for item in plan.cells
            if item.scenario_slot == "projectodyssey"
            and item.variant_id == "semantic_rerank"
        )
        embedding = _SequencedEmbeddingProvider()
        patch_provider = _EmptyPatchProvider()

        result = execute_frozen_live_cell(
            plan,
            slot_index=cell.slot_index,
            providers=FrozenExecutionProviders(
                embedding_provider_factory=lambda: embedding,
                rerank_provider_factory=_RetryableRerankProvider,
                patch_provider_factory=lambda: patch_provider,
            ),
        )

        self.assertEqual(
            {
                "status": "invalidated",
                "stage": "selection",
                "code": "provider_timeout",
            },
            result.attempt_outcome,
        )
        self.assertEqual(
            ["embedding", "embedding", "embedding", "embedding", "rerank"],
            [trace["role"] for trace in result.provider_traces],
        )
        self.assertEqual(0, len(patch_provider.calls))

    def test_semantic_document_embedding_failure_retains_error_trace_before_patch(self) -> None:
        from recallpack.v4_live_execution import (
            FrozenExecutionProviders,
            build_frozen_live_execution_plan,
            execute_frozen_live_cell,
        )

        manifest = json.loads(V3_MANIFEST.read_text(encoding="utf-8"))
        plan = build_frozen_live_execution_plan(
            manifest,
            artifact_bytes=self._scenario_artifact_bytes(manifest),
        )
        cell = next(
            item
            for item in plan.cells
            if item.scenario_slot == "projectodyssey"
            and item.variant_id == "semantic_rerank"
        )
        patch_provider = _EmptyPatchProvider()

        result = execute_frozen_live_cell(
            plan,
            slot_index=cell.slot_index,
            providers=FrozenExecutionProviders(
                embedding_provider_factory=_RetryableDocumentEmbeddingProvider,
                rerank_provider_factory=_RecordingRerankProvider,
                patch_provider_factory=lambda: patch_provider,
            ),
        )

        self.assertEqual("invalidated", result.attempt_outcome["status"])
        self.assertEqual(
            [("embedding", 1), ("embedding", 0)],
            [
                (trace["role"], trace["output_item_count"])
                for trace in result.provider_traces
            ],
        )
        self.assertEqual(0, len(patch_provider.calls))

    def test_recallpack_observe_provider_failure_retains_memory_trace_before_patch(self) -> None:
        from recallpack.v4_live_execution import (
            FrozenExecutionProviders,
            build_frozen_live_execution_plan,
            execute_frozen_live_cell,
            serialize_frozen_pre_isolation_record,
        )

        manifest = json.loads(V3_MANIFEST.read_text(encoding="utf-8"))
        plan = build_frozen_live_execution_plan(
            manifest,
            artifact_bytes=self._scenario_artifact_bytes(manifest),
        )
        cell = next(
            item
            for item in plan.cells
            if item.scenario_slot == "projectodyssey" and item.variant_id == "recallpack"
        )
        memory_provider = _RetryableMemoryDecisionProvider()
        patch_provider = _EmptyPatchProvider()

        result = execute_frozen_live_cell(
            plan,
            slot_index=cell.slot_index,
            providers=FrozenExecutionProviders(
                embedding_provider_factory=_SequencedEmbeddingProvider,
                rerank_provider_factory=_RecordingRerankProvider,
                memory_provider_factory=lambda: memory_provider,
                patch_provider_factory=lambda: patch_provider,
            ),
        )

        self.assertEqual(
            {
                "status": "invalidated",
                "stage": "selection",
                "code": "provider_timeout",
            },
            result.attempt_outcome,
        )
        self.assertIn("memory_decision", [trace["role"] for trace in result.provider_traces])
        self.assertEqual(0, len(patch_provider.calls))
        record = serialize_frozen_pre_isolation_record(result)
        self.assertIn("memory_decision", [trace["role"] for trace in record["provider_traces"]])

    def test_recallpack_observe_embedding_failure_retains_embedding_trace_before_patch(self) -> None:
        from recallpack.v4_live_execution import (
            FrozenExecutionProviders,
            build_frozen_live_execution_plan,
            execute_frozen_live_cell,
        )

        manifest = json.loads(V3_MANIFEST.read_text(encoding="utf-8"))
        plan = build_frozen_live_execution_plan(
            manifest,
            artifact_bytes=self._scenario_artifact_bytes(manifest),
        )
        cell = next(
            item
            for item in plan.cells
            if item.scenario_slot == "projectodyssey" and item.variant_id == "recallpack"
        )
        memory_provider = _SequencedMemoryDecisionProvider(
            [
                _write_decision(
                    "ci_policy",
                    "Treat the JIT crash as a compiler flake and retry.",
                    "ci_policy",
                ),
            ]
        )
        patch_provider = _EmptyPatchProvider()

        result = execute_frozen_live_cell(
            plan,
            slot_index=cell.slot_index,
            providers=FrozenExecutionProviders(
                embedding_provider_factory=_RetryableAfterStoredEmbeddingProvider,
                rerank_provider_factory=_RecordingRerankProvider,
                memory_provider_factory=lambda: memory_provider,
                patch_provider_factory=lambda: patch_provider,
            ),
        )

        self.assertEqual(
            {
                "status": "invalidated",
                "stage": "selection",
                "code": "provider_timeout",
            },
            result.attempt_outcome,
        )
        self.assertIn(
            ("embedding", 0),
            [
                (trace["role"], trace["output_item_count"])
                for trace in result.provider_traces
            ],
        )
        self.assertEqual(0, len(patch_provider.calls))

    def test_terminal_selection_provider_error_is_adverse_not_repeatable(self) -> None:
        from recallpack.v4_live_execution import (
            FrozenExecutionProviders,
            build_frozen_live_execution_plan,
            execute_frozen_live_cell,
        )

        manifest = json.loads(V3_MANIFEST.read_text(encoding="utf-8"))
        plan = build_frozen_live_execution_plan(
            manifest,
            artifact_bytes=self._scenario_artifact_bytes(manifest),
        )
        cell = next(
            item
            for item in plan.cells
            if item.scenario_slot == "projectodyssey"
            and item.variant_id == "semantic_rerank"
        )
        patch_provider = _EmptyPatchProvider()
        terminal = execute_frozen_live_cell(
            plan,
            slot_index=cell.slot_index,
            providers=FrozenExecutionProviders(
                embedding_provider_factory=_TerminalEmbeddingProvider,
                rerank_provider_factory=_RecordingRerankProvider,
                patch_provider_factory=lambda: patch_provider,
            ),
        )
        self.assertEqual("adverse", terminal.attempt_outcome["status"])
        self.assertEqual("provider_operator_action_required", terminal.attempt_outcome["code"])
        self.assertEqual(0, len(patch_provider.calls))

    def test_frozen_adapter_rejects_non_tuple_allowlist_and_symlink_root_before_runner(self) -> None:
        from recallpack.evaluation_docker import run_frozen_isolated_variant

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with self.assertRaisesRegex(
                ValueError,
                r"explicit writable path contract is invalid",
            ):
                run_frozen_isolated_variant(
                    scenario_id="projectodyssey",
                    variant_id="raw_full_history",
                    repository_snapshot_root=root / "missing-repository",
                    hidden_test_root=root / "missing-hidden-tests",
                    generated_files=(),
                    downstream={},
                    allowed_paths=["src/ci_policy.py"],
                    evaluator_contract={},
                    suite_runner=_CapturingFrozenIsolatedRunner(),
                )

            repository = root / "repository"
            repository.mkdir()
            (repository / "src").mkdir()
            (repository / "src" / "ci_policy.py").write_text("VALUE = 1\n", encoding="utf-8")
            symlink = root / "repository-link"
            symlink.symlink_to(repository, target_is_directory=True)
            with self.assertRaisesRegex(
                ValueError,
                r"frozen repository root is unavailable",
            ):
                run_frozen_isolated_variant(
                    scenario_id="projectodyssey",
                    variant_id="raw_full_history",
                    repository_snapshot_root=symlink,
                    hidden_test_root=root / "missing-hidden-tests",
                    generated_files=(),
                    downstream={},
                    allowed_paths=("src/ci_policy.py",),
                    evaluator_contract={},
                    suite_runner=_CapturingFrozenIsolatedRunner(),
                )

    def test_pre_isolation_record_is_closed_and_rejects_secret_like_provider_metadata(self) -> None:
        from recallpack.v4_live_execution import (
            FrozenExecutionProviders,
            FrozenLiveExecutionPlanError,
            build_frozen_live_execution_plan,
            execute_frozen_live_cell,
            serialize_frozen_pre_isolation_record,
        )

        manifest = json.loads(V3_MANIFEST.read_text(encoding="utf-8"))
        plan = build_frozen_live_execution_plan(
            manifest,
            artifact_bytes=self._scenario_artifact_bytes(manifest),
        )
        cell = next(
            item
            for item in plan.cells
            if item.scenario_slot == "projectodyssey"
            and item.variant_id == "raw_full_history"
        )
        contract = next(
            item
            for item in plan.scenario_contracts
            if item.scenario_slot == "projectodyssey"
        )
        provider = _RecordingPatchProvider(
            path="src/ci_policy.py",
            content=next(
                item.content.decode("utf-8")
                for item in contract.repository_files
                if item.path == "src/ci_policy.py"
            ).replace('"action": "inspect"', '"action": "fail_and_fix_forward"'),
        )
        result = execute_frozen_live_cell(
            plan,
            slot_index=cell.slot_index,
            providers=FrozenExecutionProviders(
                patch_provider_factory=lambda: provider,
            ),
        )

        record = serialize_frozen_pre_isolation_record(result)
        serialized = json.dumps(record, sort_keys=True)
        self.assertEqual(
            {
                "attempt_outcome",
                "downstream",
                "execution",
                "provider_traces",
                "record_type",
                "selected_context",
            },
            set(record),
        )
        self.assertEqual("frozen_pre_isolation_attempt/v1", record["record_type"])
        self.assertNotIn("Treat the JIT crash", serialized)
        self.assertNotIn("fail_and_fix_forward", serialized)
        self.assertNotIn("patch_diff", serialized)
        self.assertNotIn("source_ref", serialized)
        self.assertEqual("not_run", record["downstream"]["isolated_evaluation"])
        self.assertTrue(record["downstream"]["accepted"])
        self.assertTrue(
            all(type(trace["latency_ms"]) is int and trace["latency_ms"] >= 0
                for trace in record["provider_traces"])
        )

        result.provider_traces[-1]["latency_ms"] = -1
        with self.assertRaisesRegex(
            FrozenLiveExecutionPlanError,
            r"unsafe_provider_trace_metadata",
        ):
            serialize_frozen_pre_isolation_record(result)

        result.provider_traces[-1]["latency_ms"] = 0
        result.provider_traces[-1]["model_name"] = "invalid provider name"
        with self.assertRaisesRegex(
            FrozenLiveExecutionPlanError,
            r"unsafe_provider_trace_metadata",
        ):
            serialize_frozen_pre_isolation_record(result)

    def test_isolated_runner_receives_only_frozen_contract_patch_without_gold_file(self) -> None:
        from recallpack.evaluation_docker import build_runtime_evaluator_contract
        from recallpack.v4_live_execution import (
            FrozenExecutionProviders,
            build_frozen_live_execution_plan,
            execute_frozen_live_cell,
            run_frozen_live_cell_isolated,
        )

        manifest = json.loads(V3_MANIFEST.read_text(encoding="utf-8"))
        plan = build_frozen_live_execution_plan(
            manifest,
            artifact_bytes=self._scenario_artifact_bytes(manifest),
        )
        cell = next(
            item
            for item in plan.cells
            if item.scenario_slot == "projectodyssey"
            and item.variant_id == "raw_full_history"
        )
        contract = next(
            item
            for item in plan.scenario_contracts
            if item.scenario_slot == "projectodyssey"
        )
        provider = _RecordingPatchProvider(
            path="src/ci_policy.py",
            content=next(
                item.content.decode("utf-8")
                for item in contract.repository_files
                if item.path == "src/ci_policy.py"
            ).replace('"action": "inspect"', '"action": "fail_and_fix_forward"'),
        )
        result = execute_frozen_live_cell(
            plan,
            slot_index=cell.slot_index,
            providers=FrozenExecutionProviders(
                patch_provider_factory=lambda: provider,
            ),
        )
        runner = _CapturingFrozenIsolatedRunner()

        isolated = run_frozen_live_cell_isolated(
            result,
            hidden_test_root=ROOT / "evaluation/hidden-tests/projectodyssey",
            evaluator_contract=build_runtime_evaluator_contract(
                platform="linux/arm64",
                image_digest="sha256:" + "1" * 64,
                base_image_digest="sha256:" + "2" * 64,
            ),
            suite_runner=runner,
        )

        self.assertEqual(1, len(runner.calls))
        call = runner.calls[0]
        self.assertFalse(call["gold_file_present"])
        self.assertIn("fail_and_fix_forward", call["ci_policy_source"])
        self.assertEqual("test_only_injected_runner", isolated.execution_binding.authority_mode)
        self.assertEqual(cell.variant_id, isolated.execution_binding.variant_id)
        self.assertFalse(Path(call["repository_root"]).exists())

        result.generated_files[0]["content"] = "tampered after patch fixation"
        with self.assertRaisesRegex(
            Exception,
            r"frozen_patch_digest_mismatch",
        ):
            run_frozen_live_cell_isolated(
                result,
                hidden_test_root=ROOT / "evaluation/hidden-tests/projectodyssey",
                evaluator_contract=build_runtime_evaluator_contract(
                    platform="linux/arm64",
                    image_digest="sha256:" + "1" * 64,
                    base_image_digest="sha256:" + "2" * 64,
                ),
                suite_runner=runner,
            )
        self.assertEqual(1, len(runner.calls))

    @staticmethod
    def _scenario_artifact_bytes(manifest: dict) -> dict[str, bytes]:
        artifact_ids = {
            scenario[field]
            for scenario in manifest["evidence_scenarios"]
            for field in (
                "fixture_artifact_id",
                "repository_snapshot_artifact_id",
                "hidden_test_hash_artifact_id",
            )
        }
        return {
            artifact_id: (ROOT / manifest["input_artifact_catalog"][artifact_id]["relative_path"]).read_bytes()
            for artifact_id in artifact_ids
        }
class _RecordingPatchProvider:
    def __init__(self, *, path: str, content: str) -> None:
        self._path = path
        self._content = content
        self.calls = []

    def generate_patch(self, request):
        from recallpack.downstream import PatchGenerationResult
        from recallpack.providers import ProviderTrace

        self.calls.append(request)
        return PatchGenerationResult(
            files=[{"path": self._path, "content": self._content}],
            trace=ProviderTrace(
                provider_name="recording-fake",
                model_id="fake-patch",
                provider_role="patch_generation",
                request_purpose="generate_patch_from_goal_and_selected_context",
                input_item_count=1 + len(request.selected_context),
                input_token_estimate=1,
                output_item_count=1,
            ),
        )


class _RecordingFrozenExecutionAuthority:
    def __init__(self) -> None:
        self.calls = []

    def authorize_provider_action(self, slot_id, attempt_no, *, extraction_root=None):
        self.calls.append(("authorize", slot_id, attempt_no))
        self.assert_no_extraction_root(extraction_root)

    def fix_model_output(self, slot_id, attempt_no, *, output_sha256, patch_sha256):
        self.calls.append(("fix", slot_id, attempt_no, output_sha256, patch_sha256))

    @staticmethod
    def assert_no_extraction_root(extraction_root):
        if extraction_root is not None:
            raise AssertionError("provider authorization unexpectedly received an extraction root")


class _RejectingFrozenExecutionAuthority:
    def authorize_provider_action(self, slot_id, attempt_no, *, extraction_root=None):
        del slot_id, attempt_no, extraction_root
        from recallpack.v4_live_execution import FrozenLiveExecutionPlanError

        raise FrozenLiveExecutionPlanError("provider_action_not_authorized")

    def fix_model_output(self, slot_id, attempt_no, *, output_sha256, patch_sha256):
        del slot_id, attempt_no, output_sha256, patch_sha256


class _AuthorizeOnlyFrozenExecutionAuthority:
    def authorize_provider_action(self, slot_id, attempt_no, *, extraction_root=None):
        del slot_id, attempt_no, extraction_root


class _EmptyPatchProvider:
    def __init__(self) -> None:
        self.calls = []

    def generate_patch(self, request):
        from recallpack.downstream import PatchGenerationResult
        from recallpack.providers import ProviderTrace

        self.calls.append(request)
        return PatchGenerationResult(
            files=[],
            trace=ProviderTrace(
                provider_name="empty-fake",
                model_id="fake-patch",
                provider_role="patch_generation",
                request_purpose="generate_patch_from_goal_and_selected_context",
                input_item_count=1 + len(request.selected_context),
                input_token_estimate=1,
                output_item_count=0,
            ),
        )


class _CapturingFrozenIsolatedRunner:
    def __init__(self) -> None:
        self.calls = []

    def __call__(self, **kwargs):
        from recallpack.isolation import IsolatedSuiteResult

        repository_root = Path(kwargs["repository_root"])
        call = dict(kwargs)
        call["gold_file_present"] = (repository_root / "gold.json").exists()
        call["ci_policy_source"] = (repository_root / "src/ci_policy.py").read_text(
            encoding="utf-8"
        )
        self.calls.append(call)
        payload = {
            "tests": [
                {
                    "name": "network_probe",
                    "status": "passed",
                    "duration_ms": 1,
                    "evidence_artifact_id": "runner_result_json",
                },
                {
                    "name": "test_policy",
                    "status": "passed",
                    "duration_ms": 1,
                    "evidence_artifact_id": "runner_result_json",
                },
            ],
            "full_suite_passed": True,
            "passed": 2,
            "failed": 0,
            "exit_code": 0,
            "timed_out": False,
        }
        return IsolatedSuiteResult(
            exit_code=0,
            stdout=json.dumps(payload, sort_keys=True, separators=(",", ":")),
            stderr="",
            json_result=payload,
            blocked=False,
            timed_out=False,
            failure_code=None,
            host_fallback_used=False,
        )


class _RetryableThenPatchProvider:
    def __init__(self) -> None:
        self.calls = []

    def generate_patch(self, request):
        from recallpack.downstream import PatchGenerationResult
        from recallpack.providers import ProviderError, ProviderTrace

        self.calls.append(request)
        if len(self.calls) == 1:
            raise ProviderError.retryable(
                provider_name="recording-fake",
                model_id="fake-patch",
                message="transient patch provider timeout",
                code="provider_timeout",
            )
        source = next(
            item["content"]
            for item in request.source_files
            if item["path"] == "src/ci_policy.py"
        )
        return PatchGenerationResult(
            files=[
                {
                    "path": "src/ci_policy.py",
                    "content": source.replace(
                        '"action": "inspect"',
                        '"action": "retry_workaround"',
                    ),
                }
            ],
            trace=ProviderTrace(
                provider_name="recording-fake",
                model_id="fake-patch",
                provider_role="patch_generation",
                request_purpose="generate_patch_from_goal_and_selected_context",
                input_item_count=1 + len(request.selected_context),
                input_token_estimate=1,
                output_item_count=1,
            ),
        )


class _RetryableEmbeddingProvider:
    def embed_query(self, text):
        from recallpack.providers import ProviderError

        del text
        raise ProviderError.retryable(
            provider_name="recording-fake",
            model_id="fake-embedding",
            message="transient embedding timeout",
            code="provider_timeout",
        )

    def embed_document(self, text):
        raise AssertionError(f"unexpected document embedding after query failure: {text}")


class _TerminalEmbeddingProvider:
    def embed_query(self, text):
        from recallpack.providers import ProviderError

        del text
        raise ProviderError.terminal(
            provider_name="recording-fake",
            model_id="fake-embedding",
            message="provider configuration rejected the request",
            code="provider_operator_action_required",
        )

    def embed_document(self, text):
        raise AssertionError(f"unexpected document embedding after query failure: {text}")


class _RetryableRerankProvider:
    def rerank(self, goal, documents, instruct):
        from recallpack.providers import ProviderError

        del goal, documents, instruct
        raise ProviderError.retryable(
            provider_name="recording-fake",
            model_id="fake-rerank",
            message="transient rerank timeout",
            code="provider_timeout",
        )


class _RetryableAfterStoredEmbeddingProvider:
    def __init__(self) -> None:
        self.calls = []

    def embed_query(self, text):
        from recallpack.providers import ProviderError

        self.calls.append(("query", text))
        raise ProviderError.retryable(
            provider_name="recording-fake",
            model_id="fake-embedding",
            message="transient embedding timeout",
            code="provider_timeout",
        )

    def embed_document(self, text):
        from recallpack.providers import EmbeddingResult, ProviderTrace

        self.calls.append(("document", text))
        return EmbeddingResult(
            embedding=_unit_vector(0),
            text_type="document",
            trace=ProviderTrace(
                provider_name="recording-fake",
                model_id="text-embedding-v4",
                provider_role="embedding",
                request_purpose="candidate_memory_retrieval_document",
                input_item_count=1,
                input_token_estimate=1,
                output_item_count=1,
            ),
        )


class _RetryableDocumentEmbeddingProvider:
    def embed_query(self, text):
        from recallpack.providers import EmbeddingResult, ProviderTrace

        del text
        return EmbeddingResult(
            embedding=_unit_vector(0),
            text_type="query",
            trace=ProviderTrace(
                provider_name="recording-fake",
                model_id="fake-embedding",
                provider_role="embedding",
                request_purpose="candidate_memory_retrieval_query",
                input_item_count=1,
                input_token_estimate=1,
                output_item_count=1,
            ),
        )

    def embed_document(self, text):
        from recallpack.providers import ProviderError

        del text
        raise ProviderError.retryable(
            provider_name="recording-fake",
            model_id="fake-embedding",
            message="transient embedding timeout",
            code="provider_timeout",
        )


class _RetryableMemoryDecisionProvider:
    def __init__(self) -> None:
        self.calls = []

    def decide_memory_operation(self, event_text, candidate_payloads, tool_schema):
        from recallpack.providers import ProviderError

        self.calls.append((event_text, candidate_payloads, tool_schema))
        raise ProviderError.retryable(
            provider_name="recording-fake",
            model_id="fake-memory",
            message="transient memory decision timeout",
            code="provider_timeout",
        )


class _SequencedEmbeddingProvider:
    def __init__(self) -> None:
        self.calls = []

    def embed_query(self, text):
        from recallpack.providers import EmbeddingResult, ProviderTrace

        self.calls.append(("query", text))
        return EmbeddingResult(
            embedding=_unit_vector(0),
            text_type="query",
            trace=ProviderTrace(
                provider_name="sequenced-fake",
                model_id="text-embedding-v4",
                provider_role="embedding",
                request_purpose="candidate_memory_retrieval_query",
                input_item_count=1,
                input_token_estimate=1,
                output_item_count=1,
            ),
        )

    def embed_document(self, text):
        from recallpack.providers import EmbeddingResult, ProviderTrace

        self.calls.append(("document", text))
        document_index = sum(1 for kind, _ in self.calls if kind == "document")
        vector_index = 0 if document_index == 2 else document_index
        return EmbeddingResult(
            embedding=_unit_vector(vector_index),
            text_type="document",
            trace=ProviderTrace(
                provider_name="sequenced-fake",
                model_id="text-embedding-v4",
                provider_role="embedding",
                request_purpose="candidate_memory_retrieval_document",
                input_item_count=1,
                input_token_estimate=1,
                output_item_count=1,
            ),
        )


class _RecordingRerankProvider:
    def __init__(self) -> None:
        self.calls = []

    def rerank(self, goal, documents, instruct):
        from recallpack.providers import ProviderTrace, RerankResult

        self.calls.append((goal, list(documents), instruct))
        return RerankResult(
            ranked_indexes=list(range(len(documents))),
            relevance_scores={index: float(len(documents) - index) for index in range(len(documents))},
            trace=ProviderTrace(
                provider_name="recording-fake",
                model_id="qwen3-rerank",
                provider_role="rerank",
                request_purpose="precision_rerank_active_memory_candidates",
                input_item_count=len(documents),
                input_token_estimate=1,
                output_item_count=len(documents),
            ),
        )


class _SequencedMemoryDecisionProvider:
    def __init__(self, operations) -> None:
        self._operations = list(operations)
        self.calls = []

    def decide_memory_operation(self, event_text, candidate_payloads, tool_schema):
        from recallpack.providers import MemoryDecisionResult, ProviderTrace

        index = len(self.calls)
        self.calls.append((event_text, list(candidate_payloads), dict(tool_schema)))
        return MemoryDecisionResult(
            tool_arguments=dict(self._operations[index]),
            trace=ProviderTrace(
                provider_name="sequenced-fake",
                model_id="qwen3.7-plus-2026-05-26",
                provider_role="memory_decision",
                request_purpose="extract_classify_and_judge_memory_lifecycle",
                input_item_count=1 + len(candidate_payloads),
                input_token_estimate=1,
                output_item_count=1,
            ),
        )


def _unit_vector(index: int) -> list[float]:
    vector = [0.0] * 1024
    vector[index] = 1.0
    return vector


def _write_decision(subject, text, component, supersedes=None):
    return {
        "operation": "write",
        "memory": {
            "type": "decision",
            "subject": subject,
            "text": text,
            "scope_level": "component",
            "component": component,
        },
        "duplicate_of_candidate_index": None,
        "supersedes_candidate_indexes": list(supersedes or []),
        "reason": "test_decision",
    }


def _write_preference(subject, text):
    return {
        "operation": "write",
        "memory": {
            "type": "preference",
            "subject": subject,
            "text": text,
            "scope_level": "project",
            "component": None,
        },
        "duplicate_of_candidate_index": None,
        "supersedes_candidate_indexes": [],
        "reason": "test_preference",
    }


if __name__ == "__main__":
    unittest.main()
