# M116 ProjectOdyssey Unrigged Scenario Dry-Run

Date: 2026-07-09

Status: GO for M117 fixture implementation, with live Qwen still gated.

This document is internal submission planning evidence. It does not add a new
judge-facing claim by itself and does not claim RecallPack evaluated a
production ProjectOdyssey trace.

## Source Boundary

ProjectOdyssey is useful because the stale-memory pattern is a coding-agent
instruction evolution, not a generic API migration:

- Public source pair:
  - `https://github.com/HomericIntelligence/ProjectOdyssey/commit/47d9ddc`
  - `https://github.com/HomericIntelligence/ProjectOdyssey/blob/main/CLAUDE.md`
- Use only authored summaries of the public evolution.
- Do not copy repository text, code, logs, or docs into RecallPack fixtures.
- Label the fixture as a source-backed scenario, not a production trace.
- Do not state that RecallPack fixed ProjectOdyssey.

## Current Baseline Risk

The current project-a hero remains too authored to be the award headline.

Inspection result:

- `src/recallpack/evaluation.py:335` builds the raw-history embedding baseline.
- `src/recallpack/evaluation.py:341` uses `FakeEmbeddingProvider` with vectors
  from `_hero_baseline_embedding_vectors`.
- `src/recallpack/evaluation.py:442` reads `baseline_embedding_terms` from
  fixture gold metadata.
- `src/recallpack/evaluation.py:443` reads `baseline_downrank_phrases`.

That means the current local baseline is useful as a deterministic failure
replay, but it should not remain the headline proof that a naive retriever
naturally fails. The repository already discloses this boundary, but the next
quality step should replace the headline with an unrigged source-backed
scenario.

## Dry-Run Design

The dry-run tests whether a realistic ProjectOdyssey-style raw-history
candidate pool can make stale memory naturally dominate under a small handoff
budget without using fixture-authored embedding terms or downrank phrases.

### Candidate Events

All event texts below are authored summaries, not copied source text.

| Candidate | Lifecycle Role | Summary |
| --- | --- | --- |
| `stale_workaround` | stale decision | An older project note treats Mojo JIT crashes in CI as flaky compiler behavior and suggests retry loops, workflow continue-on-error, or skip markers as temporary workarounds. |
| `active_policy` | active decision | A newer project instruction says the JIT is stable now; do not hide crashes with retry, continue-on-error, or skips; treat crashes as real bugs and fix forward. |
| `crash_log` | current evidence | CI output reports a Mojo JIT crash while running tests. |
| `task_event` | current task | The fresh handoff task asks the agent to fix a Mojo JIT CI crash. |
| `dependency_pref` | preference | Do not add dependencies for CI or test-runner fixes. |

### Realistic Goals Tested

The best dry-run goal shape was:

```text
Fix the flaky Mojo JIT CI crash by updating retry handling.
```

This is realistic because the stale source is retry-heavy, while the active
source is a later instruction that reverses the workaround. It should not be
rewritten into an artificial phrase that only exists to force stale selection.

## Local Dry-Run Result

Provider used:

- `DeterministicKeywordEmbeddingProvider`
- `DeterministicKeywordRerankProvider`
- no `baseline_embedding_terms`
- no `baseline_downrank_phrases`
- no live Qwen
- no credentials

Representative result:

| Rank Stage | Ordering |
| --- | --- |
| Embedding order | `task_event`, `stale_workaround`, `crash_log`, `dependency_pref`, `active_policy` |
| Rerank order over top-N | `stale_workaround`, `task_event`, `crash_log`, `dependency_pref` |
| Selected top-2 | `stale_workaround`, `task_event` |

Interpretation:

- The stale workaround is naturally selected.
- The active policy is excluded from the selected top-2 budget.
- The selected top-2 also includes a real current task event, so the baseline
  can plausibly write a retry-oriented workaround without seeing the reversal.
- This passes the local M116 dry-run bar for implementing a formal fixture.

Important limitation:

- This is still a deterministic local dry-run. It is not a live
  `text-embedding-v4` plus `qwen3-rerank` result.
- M117 should add a credential-free preflight for the same scenario.
- A live Qwen rerun can be done later only after explicit approval.

## Acceptance Criteria For M117

M117 should implement the ProjectOdyssey source-backed fixture only if these
conditions stay true:

1. The fixture has no `baseline_embedding_terms`.
2. The fixture has no `baseline_downrank_phrases`.
3. The raw-history baseline uses the provider contract, not a source-id oracle.
4. Baseline selected context includes the stale workaround.
5. Baseline selected context excludes the active reversal under the configured
   budget.
6. RecallPack selected context includes the active reversal.
7. RecallPack selected context excludes the stale workaround before rerank and
   budget selection.
8. The downstream proof runs against a temp repo and hidden tests.
9. The provenance file says source-backed scenario, not production trace.
10. The docs do not claim live Qwen success unless a live run actually passes.

## Suggested M117 Fixture Shape

Fixture name:

```text
fixtures/project-h-projectodyssey-jit/
```

Repo snapshot:

```text
repo_snapshot/
  pyproject.toml
  src/ci_policy.py
```

Patch target:

```text
src/ci_policy.py
```

Possible behavior:

- Stale patch adds retry/continue-on-error/skip-style behavior around a JIT
  crash.
- Active patch treats the crash as a real failure, keeps tests strict, and
  returns a minimal reproduction/fix-forward path.
- Dependency preference blocks adding new CI helper packages.

Hidden tests:

1. The CI policy does not add retry behavior for JIT crashes.
2. The CI policy does not mark JIT crashes as skippable or non-blocking.
3. The patch keeps dependencies unchanged.

Expected variants:

- Raw full-history reference: contains both stale and active events; not
  budget-comparable.
- Unrigged raw-history baseline: selected from raw event text with provider
  embeddings/rerank, includes stale workaround, excludes active reversal,
  fails hidden tests.
- RecallPack: active memory selected, stale memory filtered by lifecycle state,
  passes hidden tests.

## GO / NO-GO

GO for M117 implementation.

Reason:

- ProjectOdyssey is a strong source-backed MemoryAgent scenario.
- The local dry-run shows stale can be selected naturally without fixture
  downrank fields.
- The fixture would directly repair the current central evidence gap: the
  project-a failure remains authored, while project-h can demonstrate the same
  failure shape under an unrigged candidate pool.

NO-GO conditions:

- If the formal fixture needs `baseline_embedding_terms` or
  `baseline_downrank_phrases`, do not ship it as the new hero.
- If active policy is selected alongside stale under the same budget, keep it
  as a regression fixture, not the headline proof.
- If live Qwen later selects the active policy, disclose it and keep the live
  result as structural lifecycle evidence, not a live baseline-failure claim.

## P0 / P1 / P2 Decisions

P0:

- Build M117 only as an unrigged fixture.
- Replace the award headline with project-h only if it passes the acceptance
  criteria above.
- Keep project-a language downgraded as deterministic replay.

P1:

- Add a no-network ProjectOdyssey live-baseline preflight.
- After M117 passes locally, request approval for one live Qwen embedding/rerank
  run on project-h.
- Update skeptical judge Q&A with the exact answer to "did you rig the
  baseline?"

P2:

- Keep urllib3 as a one-line analogy only if needed.
- Do not spend fixture-building time on generic API deprecation scenarios.
