# Review Seed Generation Command Contract

Status: T069 accepted implementation contract
Version: `review-seed-generation/4.1`

## Purpose

`tools/generate_review_seed.py` freezes an operator-authored seed draft into one
validated RFC 8785 `EvaluationReviewSeed` export. It is credential-free,
network-free, and cannot create an attestation, receipt, final
`ExecutionManifest`, run, aggregate, or claim.

T069 implements and tests this command with temporary synthetic contract
fixtures only. It MUST NOT generate the production T052 seed.

## Inputs

The command requires exactly:

- `--seed-draft`: a canonical repository-relative POSIX path to a regular I-JSON
  file with the complete final seed shape. The command ignores and replaces
  only `code_hashes` and `external_artifact_slots`; every other value is
  operator-frozen input;
- `--repository-root`: the clean frozen repository root used both for code-hash
  computation and seed-frozen artifact resolution; and
- `--output-dir`: a canonical repository-relative POSIX target directory whose
  parent already exists and whose final component does not already exist.

The command does not accept an external-content root, credential, endpoint,
attestation, receipt, label, holdout, or final-manifest argument. It does not
read environment variables to obtain any of those values.

## Derivation And Validation

The command MUST:

1. open the repository root once as the read/write authority, then parse the
   draft with the 4.1 duplicate-key and I-JSON parser;
2. require an object with a closed `frozen_input_artifact_catalog`;
3. replace `code_hashes` with `compute_frozen_code_hashes(repository_root)`;
4. replace `external_artifact_slots` with
   `derive_external_artifact_slots(seed)`;
5. load every seed-frozen artifact from the catalog record's exact
   `relative_path` beneath `repository_root`;
6. reject absolute, empty, dot, dot-dot, repeated-slash, backslash, non-ASCII,
   NUL, symlinked, hardlinked, non-regular, missing, or root-escaping paths;
7. validate the complete seed, artifact bytes, public scenario semantics, grid,
   models, claims, image binding, and recomputed repository code hashes through
   `validate_evaluation_review_seed`; and
8. canonicalize only after validation.

The supplied repository root must be an absolute canonical non-symlink
directory. The command opens it once and resolves the draft, every catalog
artifact, every directory and file consumed by
`compute_frozen_code_hashes`, and the output parent component-by-component
beneath that same root file descriptor. `compute_frozen_code_hashes` itself must
be hardened to use this descriptor-anchored authority; its current path-walk and
`Path.read_bytes` implementation is not conforming and must be replaced in
T069. Every component uses `O_NOFOLLOW`; intermediate components also use
`O_DIRECTORY`. Each input final descriptor must be a regular file with
`st_nlink=1`. The loader records `st_dev`, `st_ino`, `st_size`, and
`st_mtime_ns`, reads exactly the recorded byte length plus one EOF probe, then
requires a second `fstat` to match all recorded values. Code-tree enumeration
uses opened directory descriptors, rejects a changed entry type or identity,
and hashes only bytes returned by this stable reader. Any mismatch rejects. No
check-then-path-open flow is conforming anywhere in seed generation or code-hash
computation.

Catalog `sha256` and `bytes` values are not repaired or regenerated. A mismatch
means the operator has not frozen the declared input and the command fails
closed. There is no partial output, repair, fallback, or placeholder mode.

`__pycache__` or `*.pyc` in a frozen code root remains a terminal code-hash
error. Operators use a clean fresh clone or sanitized bundle; the command must
not delete or ignore those files.

## Output Package

Successful generation atomically publishes one new directory containing
exactly:

- `evaluation-review-seed.json`: canonical RFC 8785 seed bytes, no trailing
  newline;
- `evaluation-review-seed.sha256`: lowercase seed SHA-256 plus one LF;
- `external-artifact-slots.json`: canonical RFC 8785 derived slot array, no
  trailing newline; and
- `review-seed-generation-report.json`: canonical closed report, no trailing
  newline.

The report has exactly:

- `record_type=review_seed_generation_report`;
- `report_version=review-seed-generation/4.1`;
- fixed output filenames;
- seed and slot-list SHA-256 plus byte lengths;
- `external_artifact_slot_count`;
- `contains_external_content=false`;
- `credentials_read=false`;
- `network_calls_made=false`;
- `authorizes_execution=false`; and
- `next_gate=external_review_and_attestation`.

The report and stdout contain no absolute path, repository path, username,
credential name/value, or external artifact body. The seed remains a technical
freeze artifact, not evidence that external content exists.

Publication uses the already opened output-parent descriptor, a nonce-owned
sibling temporary directory created with `mkdirat`, exclusive descriptor-based
file creation, file and directory `fsync`, and one same-parent `renameat`.
Target existence is checked through that same parent descriptor and the rename
must not replace an existing entry. On failure, no final target exists; cleanup
unlinks only the four fixed filenames from the still-open owned temporary
directory descriptor and then removes that exact temporary directory through
the parent descriptor.

## T052-T054 Boundary

- T052 may run the command only after T069 closes, using the selected rung and
  final frozen inputs. The canonical seed bytes/hash are then immutable.
- T053 sends only the four-file export and a separately frozen review package
  to the external reviewer. Before authoring any label, leakage review, blind
  holdout, or attestation, the reviewer must first validate the seed bytes/hash,
  issue and externally retain the sequence-1 seed receipt, and record its
  `received_at`. Only then may the reviewer author and retain sealed labels,
  leakage review, optional blind holdout, and attestation outside the
  implementation workspace.
- T054 may import only the closed attestation at
  `evaluation/evidence/protocol/external-review-attestation.json`; no alternate
  in-workspace import path is allowed. External hash-reference records and
  their IDs, paths, wrapper bytes, and digests are generated locally by the
  deterministic assembler from canonical seed plus attestation bytes; no
  reviewer-supplied hash-reference file is accepted. The seed
  receipt may be read from external custody for binding but is not copied into
  the implementation workspace. Sealed external content stays outside until
  its declared reveal phase. Deterministic assembly and unique registration
  must succeed before provider or sandbox work.

No command in T069 performs T052, T053, or T054 on production artifacts.
