# RecallPack V4 Review-Seed Operator Runbook

Status: T069 independently reviewed command and custody procedure

This runbook is for T052-T054 evidence operations.
T069 does not generate the production T052 seed. T069 uses only temporary
synthetic contract fixtures to verify the command.

## T052: Freeze And Export The Seed

Work from a clean fresh clone or sanitized bundle. Frozen code roots must not
contain `__pycache__`, `*.pyc`, symlinks, or hardlinks. The T052 production
scope is `R2`, with `projectodyssey` and `deepagents` in that order.

Build the complete seed draft and all seed-frozen catalog files under their
declared repository-relative paths. The draft builder is deterministic and
must receive the already-built evaluator image digest and platform explicitly.
It does not build or run an image, use providers, or authorize execution.

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 \
  tools/build_review_seed_draft.py \
  --repository-root "$(pwd -P)" \
  --output-dir evaluation/evidence/review-seed \
  --created-at <UTC_TIMESTAMP> \
  --evaluator-image-digest <SHA256_DIGEST> \
  --platform linux/arm64
```

Before export, copy the repository to a new clean staging root while excluding
`.venv`, `dist`, `.ruff_cache`, `.DS_Store`, `__pycache__`, and `*.pyc`.
Run the exporter from that clean root. This staging step preserves the
fail-closed source-tree check without deleting developer caches from the
workspace.

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 tools/generate_review_seed.py \
  --repository-root "$(pwd -P)" \
  --seed-draft evaluation/evidence/review-seed/seed-draft.json \
  --output-dir evaluation/evidence/review-seed/export
```

Both draft and export targets must not exist before their respective commands.
The draft's `code_hashes` and `external_artifact_slots` are non-authoritative
inputs; the exporter replaces both from the frozen repository. A successful
export contains exactly four files. Verify the seed hash file against
`evaluation-review-seed.json`, retain the entire export unchanged, and stop.
The seed does not authorize execution.

## T053: External Receipt, Authorship, And Custody

Create the reviewer custody root outside the RecallPack workspace. Do not put
that directory under the repository, sanitized bundle, Git worktree, `dist/`,
or any path copied by submission packaging.

Send the four-file export plus the separately frozen reviewer package. The
external reviewer must validate the canonical seed bytes/hash and issue the
sequence-1 `seed_receipt` before authoring any external artifact. The receipt is
retained outside the RecallPack workspace and records `received_at` before any
label, leakage review, optional blind holdout, or attestation authorship begins.

The reviewer then authors the exact derived slot set and the closed attestation.
Do not copy sealed external content into the workspace. Required-memory labels,
relation labels, leakage review bodies, optional blind fixture/source/snapshot,
and hidden tests remain in reviewer or user custody until their declared reveal
phase.

At the end of the replacement T053 cycle, the workspace may receive only a
sanitized attestation copy at
`evaluation/evidence/review-seed-cycles/cycle-v3/protocol/external-review-attestation.json`.
The manifest's internal protocol path remains unchanged. The seed receipt,
semantic report, custody report, custody anchor, labels, and leakage bodies
remain external.

## T054: Assemble And Register

Import only the cycle-v3 sanitized attestation source named above.
Reviewer-supplied hash-reference files are forbidden: all hash-reference records are derived locally by the deterministic assembler from canonical seed plus attestation bytes.

T054 must:

1. reopen and validate the canonical seed export;
2. read the sequence-1 receipt directly from external custody;
3. compare the external custody report to the independently retained expected
   JCS hash and byte length before parsing;
4. validate the semantic report, closed custody report, all leakage bodies,
   attestation, receipt chronology, exact slots, and content digests;
5. call `assemble_eligible_execution_manifest_41` with repository-bound code
   hashes;
6. atomically register only that eligible capability through
   `SqliteManifestRegistry`;
7. externally retain the sequence-2 manifest registration receipt; and
8. revalidate the eligible registered manifest before continuing.

No provider or sandbox action may begin before unique registration succeeds and
the sequence-2 receipt is retained. Sealed artifacts are read only at the exact
reveal phase through the registered manifest's custody authority.

## Stop Conditions

Stop without repair or fallback if any hash, byte length, path, schema,
chronology, slot, receipt, custody, registration, or code-root check fails. A
change to any frozen input requires a new T052 seed and a new external
authorship cycle.
