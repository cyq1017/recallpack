# Evaluation Review Seed Contract

Status: T067 approved v5; T068 implementation authority  
Contract version: `review-seed/4.1`

## 1. Purpose And Threat Boundary

`EvaluationReviewSeed` closes the ordering gap between technical freeze and
external authorship. It is created before an external reviewer authors headline
labels or a blind holdout. A later claim-bearing `ExecutionManifest` may add
only the externally supplied hashes required by this contract. Every other
execution input is seed-frozen.

The protocol must prevent all of these paths:

1. the seed author omits an inconvenient externally authored artifact;
2. a post-review value changes while a permissive projection still passes;
3. one seed/attestation pair mints multiple manifests and resets the first-three
   attempt window;
4. a digest is treated as verified content before its sealed bytes are revealed;
5. legacy `4.0` claim-bearing records bypass the `4.1` review protocol.

The seed is not an `ExecutionManifest`, cannot authorize provider or sandbox
work, and cannot enable a claim.

## 2. Canonical Bytes And Digests

All protocol JSON records and JSON external artifacts use RFC 8785 JSON
Canonicalization Scheme (JCS) over I-JSON values. Parsers reject duplicate
object keys, invalid UTF-8, lone surrogates, and non-finite numbers before
canonicalization. No Unicode normalization is applied. UTC timestamps use only
`YYYY-MM-DDTHH:MM:SSZ`.

`sha256` means lowercase hexadecimal SHA-256 of the RFC 8785 UTF-8 bytes. Every
attested external artifact uses `canonicalization=rfc8785_json` and records its
JCS byte length. Binary fixture/test files exist only as base64 values inside the
closed deterministic file-bundle JSON envelope.

Every protocol timestamp must both match the lexical form above, use a year in
`0001..9999`, and parse as a valid proleptic-Gregorian UTC instant. Validation
rejects year `0000`, normalization, day
zero, impossible month/day combinations, leap-day errors, and leap seconds,
then requires round-trip serialization to equal the input string.

T068 must provide cross-language golden vectors covering Unicode, nested key
order, integer/decimal serialization, negative zero, and timestamp spelling,
plus rejection vectors for duplicate keys, invalid UTF-8, lone surrogates, and
non-finite numbers. Python and Node verification must produce identical bytes
and hashes for every valid vector.

## 3. EvaluationReviewSeed

The normative JSON Schema definitions for `EvaluationReviewSeed`,
`ExternalReviewAttestation`, and `ExecutionManifest41` must be added to
`evaluation.schema.json` by T068. Until that integration lands, this section is
the closed field contract: every object is `additionalProperties=false`, every
listed field is required, and no field is nullable unless stated.

The seed has exactly these top-level fields:

| Field | Closed contract |
| --- | --- |
| `record_type` | Constant `evaluation_review_seed` |
| `review_seed_version` | Constant `review-seed/4.1` |
| `semantic_rules_version` | Constant `4.1` |
| `created_at` | Exact UTC timestamp form from section 2; copied to the final manifest |
| `target_rung` | `Full`, `R1`, or `R2` |
| `code_hashes` | Closed code-hash object below |
| `scenario_plan` | Ordered, rung-closed scenario records below |
| `variants` | Exact five-variant order from the current execution schema |
| `provider_settings` | Existing closed `providerSettings`; live Qwen and fallback false |
| `comparison_contract` | New closed `comparisonContract41`; scenario-specific snapshot IDs are forbidden here |
| `evaluator_contract` | Existing closed `evaluatorContract` |
| `technical_failure_codes` | Existing closed, unique failure-code array |
| `execution_order` | Existing closed execution-slot records; complete rung grid |
| `claim_declarations` | Existing closed claim declarations; rung-eligible only |
| `evaluator_image_digest` | Platform-qualified immutable image digest |
| `frozen_input_artifact_catalog` | Closed seed-frozen artifact records below |
| `external_artifact_slots` | Exact validator-derived matrix from section 4 |

### 3.1 Closed code hashes

`code_hashes` has exactly four required SHA-256 fields:

- `runtime_tree_sha256`: all regular `*.py` files below `src/recallpack/`;
- `evaluator_tree_sha256`: `evaluation/Dockerfile`,
  `evaluation/.dockerignore`, and all regular `*.py` files below
  `evaluation/runner/`;
- `evaluation_schema_sha256`: exact bytes of
  `specs/001-recallpack-v4/contracts/evaluation.schema.json` after T068; and
- `dependency_lock_sha256`: exact bytes of `requirements-v4.txt`.

Symlinks, missing roots, duplicate normalized paths, `__pycache__`, `*.pyc`,
and files outside these roots reject. A tree hash is:

1. normalize each included path to its repository-relative POSIX UTF-8 path;
2. compute lowercase SHA-256 of each exact file byte sequence;
3. sort entries by the UTF-8 bytes of the normalized path;
4. encode each leaf as `<path> NUL <file_sha256> LF`; and
5. SHA-256 the concatenation of all leaf encodings.

No ignore file or caller-provided include list can alter those roots.

### 3.2 Closed comparison contract

Semantic rules `4.1` use `comparisonContract41`, not the legacy
`comparisonContract`. It contains the same fixed budget, tokenizer, patch
provider, prompt, runner, writable-path, hidden-test-boundary, variant
comparability, and provider-role fields, but it MUST NOT contain
`repository_snapshot_artifact_id` or `model_visible_snapshot_artifact_id`.
Those two scenario-specific inputs resolve only from the current
`evidenceScenario41`. A manifest, seed, runner, or validator that supplies or
consults a second scenario-input authority rejects `invalid_review_seed`.

The writable-path array is the ASCII-sorted union of the selected public
scenario registry paths. `projectodyssey` contributes `src/ci_policy.py` and
`pyproject.toml`; `deepagents` contributes `src/package_policy.py` and
`pyproject.toml`; `graphiti` contributes `src/backend_policy.py` and
`pyproject.toml`. A rung containing a blind holdout also includes the frozen
blind-authoring path set `src/retry.py`, `src/retry_policy.py`, `src/auth.py`,
`src/config_loader.py`, and `pyproject.toml`. This list is identical across
variants, but is no longer the stale demo-only list for an R2 public-scenario
run. Any missing, extra, reordered, or unregistered path rejects
`unequal_comparison_contract` through seed validation.

### 3.3 Closed scenario plan

Every scenario record has `scenario_slot` matching
`^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$` and one of two closed shapes:

- `source_backed_synthetic`: requires `scenario_slot`, `evidence_class`, and
  these artifact-ID/digest pairs: `fixture`, `source_ledger`,
  `repository_snapshot`, `model_visible_snapshot`, `hidden_test_hash`, and
  `provenance`. Every paired digest except the hidden-test content digest equals
  the referenced catalog record SHA-256. `hidden_test_content_sha256` is the literal
  64-character payload of the referenced 64-byte `hidden_test_hash` artifact;
  the catalog record SHA-256 separately hashes that wrapper payload;
- `blind_holdout`: requires only `scenario_slot` and
  `evidence_class=blind_holdout`. Its identity is opaque before external
  authorship; no content, label, expected value, test name, provenance, or hash
  surrogate may appear elsewhere in the seed.

The public pair field names are exactly `fixture_artifact_id`/`fixture_sha256`,
`source_ledger_artifact_id`/`source_ledger_sha256`,
`repository_snapshot_artifact_id`/`repository_snapshot_sha256`,
`model_visible_snapshot_artifact_id`/`model_visible_snapshot_sha256`,
`hidden_test_hash_artifact_id`/`hidden_test_content_sha256`, and
`provenance_artifact_id`/`provenance_sha256`.

The rung matrix is exact:

| Rung | Ordered scenario classes |
| --- | --- |
| `Full` | Three `source_backed_synthetic`, then one `blind_holdout` |
| `R1` | Two `source_backed_synthetic`, then one `blind_holdout` |
| `R2` | Exactly two `source_backed_synthetic`; no holdout |

The approved public-scenario registry is closed:

| Scenario ID | Repository identity | License |
| --- | --- | --- |
| `projectodyssey` | `https://github.com/HomericIntelligence/Odyssey` | `BSD-3-Clause` |
| `deepagents` | `https://github.com/langchain-ai/deepagents` | `MIT` |
| `graphiti` | `https://github.com/getzep/graphiti` | `Apache-2.0` |

Full uses exactly `projectodyssey`, `deepagents`, `graphiti` in that order. R1
uses exactly `projectodyssey`, `deepagents` in that order. R2 selects two
distinct IDs from this registry in registry order. The blind slot matches
`^blind_[A-Za-z0-9._-]{1,57}$`, is not a public registry ID, and occurs only at
the final rung position.

Scenario IDs are unique. The provenance artifact for each public scenario must
contain exactly its registered repository identity and its own matching
scenario ID. Every artifact ID named by a public scenario resolves
exactly once in `frozen_input_artifact_catalog` with the expected kind and
`origin=seed_frozen`. The fixture, source ledger, repository snapshot,
model-visible snapshot, hidden-test bundle, provenance, common prompt, runner,
patch contract, Dockerfile, evaluator runner, image build record, and every
other non-external execution input are frozen before review.

Across public scenarios, all six artifact IDs and all six semantic content
digests are pairwise distinct by category. Reusing one scenario under another
slot, aliasing an artifact ID, or duplicating a fixture, source ledger,
repository snapshot, model-visible snapshot, hidden-test content, or provenance
digest across public slots rejects `invalid_scenario_identity`.

Every public `source_provenance` artifact is RFC 8785 JSON matching the closed
`sourceProvenance41` schema. It contains exactly `record_type=source_provenance`,
the matching registry `scenario_slot`,
`evidence_class=source_backed_synthetic`, `production_trace=false`,
`copied_source_text=false`, `authored_summaries=true`, the registry-exact
`repository_url`, one or more unique full 40-character lowercase Git commit
hashes in `commit_refs`, the registry-fixed `license_id`, and
`authored_summary_sha256`. The authored-summary digest is SHA-256 of the JCS
array, in model-visible snapshot order, of closed
`{"source_ref": ..., "summary": ...}` objects for every event with
`authored_summary=true`. Its canonical body hash must equal both the scenario
plan `provenance_sha256` and the catalog record SHA-256. Missing, extra,
wrong-repository, wrong-license, cross-scenario, non-commit-addressable, or
authored-summary-mismatched content rejects `invalid_scenario_identity`.

### 3.4 Seed-frozen catalog

Every catalog record retains the existing path, digest, byte-length,
sanitization, and content-policy fields and adds
`origin=seed_frozen`. `origin` is a schema enum, not caller-defined text.
Only artifacts referenced by seed fields or required by their closed nested
contracts may appear. Output kinds, protocol records, external hash references,
externally required content, and hash surrogates reject with
`invalid_review_seed`.

Seed-frozen artifact IDs must not equal `evaluation_review_seed` or
`external_review_attestation` and must not start with `external__`. Their
normalized paths must not equal or descend from `protocol/`. Artifact IDs,
normalized paths, and content paths are unique. Reserved-name, reserved-path,
or union collision rejects `invalid_review_seed` before final assembly.

The catalog is a map keyed by artifact ID and therefore has no independent
ordering. Every record's bytes and hash are validated before the seed hash is
computed.

A public `hidden_test_hash` artifact payload is exactly 64 lowercase ASCII
hexadecimal characters with no newline and `bytes=64`. Its catalog `sha256`
hashes those wrapper bytes; its scenario-plan `hidden_test_content_sha256`
equals the wrapper payload. The two digest layers are never substituted.

## 4. Validator-Derived External Artifact Matrix

The validator derives the required slot keys from `target_rung` and
`scenario_plan`; it never trusts the seed author to choose the set.

For every `source_backed_synthetic` and `blind_holdout` scenario, exactly these
three slots are required:

| Kind | Canonicalization | Reveal phase |
| --- | --- | --- |
| `required_memory_label_ledger` | `rfc8785_json` | `post_outputs_fixed` |
| `relation_label_ledger` | `rfc8785_json` | `post_outputs_fixed` |
| `leakage_review` | `rfc8785_json` | `pre_run_eligibility_check` |

Every `blind_holdout` scenario additionally requires exactly:

| Kind | Canonicalization | Reveal phase |
| --- | --- | --- |
| `fixture` | `rfc8785_json` | `before_scenario_execution` |
| `source_ledger` | `rfc8785_json` | `before_scenario_execution` |
| `model_visible_snapshot` | `rfc8785_json` | `before_scenario_execution` |
| `hidden_test_bundle` | `rfc8785_json` | `after_model_output_fixed` |

R2 contains no blind-holdout slots. Public fixture, source-ledger,
model-visible-snapshot, prompt, hidden-test, and provenance hashes remain
seed-frozen and must not be duplicated as external slots.

Each derived slot is the closed object:

- `artifact_id` equal to
  `external__<scenario_slot>__<kind>`;
- `scenario_slot`;
- `kind` from the exact tables above;
- `canonicalization` fixed by kind;
- `reveal_phase` fixed by kind; and
- `custody_state=sealed_external`.

`external_artifact_slots` must equal this derived array in scenario-plan order
and table order. Missing, extra, duplicate, catch-all, wrong-scenario,
wrong-kind, wrong-phase, or wrong-ID entries reject
`external_artifact_set_mismatch`.

Reveal authority is not global. The first three phases are instantiated once
per execution attempt and keyed by the registered execution-manifest SHA-256,
`slot_id`, and `attempt_no`. Advancing one attempt never advances another.
Blind fixture/source-ledger/model-visible bodies are exposed only through that
attempt's private loader handle. Hidden-test body parsing or materialization is
forbidden until the same attempt's model output and patch bytes are immutable;
its disposable extraction root is destroyed and made unreachable before any
later provider action. `post_outputs_fixed` is a separate scenario barrier: it
advances only after every predeclared claim-bearing output for that scenario,
across all variants and repetitions, is immutable. Only then may required-memory
or relation-label bodies be revealed to scorer-only code. No provider-facing
code can receive a label or another attempt's revealed handle in any phase.

The JSON external artifacts are also closed:

- `required_memory_label_ledger`: `record_type`, `scenario_slot`,
  `source_ledger_sha256`, and a non-empty unique lexicographically ordered
  `required_source_refs` array. Every ref resolves in that scenario's exact
  source ledger;
- `relation_label_ledger`: the existing closed ledger contract, with every
  `opportunity_id` in the disjoint `^opp_[A-Za-z0-9._-]+$` namespace so it
  cannot equal a valid colon-delimited `source_ref`;
- every public or blind `model_visible_snapshot` uses the same closed
  `modelVisibleSnapshot41` JCS envelope with `record_type`, `scenario_slot`,
  `source_ledger_sha256`, and a non-empty ordered `events` array. Each closed
  event contains `source_ref`, exact UTC `observed_at`, `actor` in
  `user|assistant|system`, `kind=message`, bounded non-empty `summary`,
  `model_visible=true`, and `authored_summary=true`; its source ref and canonical
  event hash must match that scenario's source ledger. Source refs are unique,
  array order exactly equals source-ledger entry order, and JSONL, a bare array,
  alternate wrappers, duplicate-key JSON, or parser normalization reject;
- `leakage_review`: `record_type`, `scenario_slot`, exact fields
  `fixture_sha256`, `source_ledger_sha256`,
  `model_visible_snapshot_sha256`, `prompt_template_sha256`,
  `relation_label_sha256`,
  `hidden_test_content_sha256`, and `evaluator_image_digest`, plus `verdict` in
  `pass|reject` and `reason_codes`. The pass set is exactly
  `no_copied_source_text`, `no_hidden_test_content_model_visible`,
  `no_gold_source_ids_model_visible`, `no_required_labels_model_visible`, and
  `no_relation_labels_model_visible`, in that order. A reject may add only
  `other_review_rejection`. `relation_label_sha256` binds the review to the
  exact externally authored relation ledger. The final reason code means the
  reviewer compared that ledger with the bound model-visible snapshot and
  prompt and found no opportunity IDs, relation-kind labels, endpoint-role or
  endpoint-pairing semantics, or complete/partial restatement in direct or
  paraphrased form; and
- blind `fixture` and `hidden_test_bundle`: the closed deterministic file-bundle
  envelope below, dispatched to purpose-specific schemas.

Only `verdict=pass` with the exact pass set is eligible. Every reviewed digest
must equal its seed-frozen or attested source. Unknown, missing, or mismatched
fields fail closed.

`deterministic_file_bundle/4.1` is an RFC 8785 JSON object with exactly
`record_type=deterministic_file_bundle`,
`bundle_version=deterministic-file-bundle/4.1`, `scenario_slot`, `purpose` in
`fixture|hidden_tests`, and `files`. `files` contains 1..256 regular-file
records in ASCII bytewise path order. Each record contains an already-canonical
relative POSIX `path` made only of slash-separated non-empty
`[A-Za-z0-9._-]+` segments, with no segment exactly `.` or `..`, no leading or
trailing slash, and no repeated slash; lowercase SHA-256 of decoded content, decoded `bytes`, and
canonical padded RFC 4648 `content_base64`. Per-file decoded size is at most
1,048,576 bytes and aggregate decoded size at most 16,777,216 bytes. Duplicate
or ASCII-case-colliding paths, absolute paths, backslashes, NUL,
symlinks, hardlinks, devices, archives, compression, and unknown entry types are
unrepresentable or rejected. After outer JCS hash/length and every inner
hash/length are verified, materialization writes only into an evaluator-owned
disposable root with no symlink following. Collision keys are the entire path
mapped with ASCII `A-Z -> a-z`; locale and Unicode normalization are forbidden.
Host-workspace extraction is
forbidden. Hidden-test bundle parsing and materialization are unavailable until
`after_model_output_fixed`.

External-content dispatch binds slot kind to bundle purpose before entry
parsing: `kind=fixture` requires `fixtureBundle41` and `purpose=fixture`;
`kind=hidden_test_bundle` requires `hiddenTestBundle41` and
`purpose=hidden_tests`. Either inverse mapping rejects
`external_artifact_content_mismatch` at `/purpose` before any file is decoded or
materialized.

## 5. ExternalReviewAttestation

The reviewer receives the canonical seed bytes and hash before authorship and
returns one closed, content-addressed attestation with exactly:

- `record_type=external_review_attestation`;
- `attestation_version=review-attestation/4.1`;
- `review_seed_sha256`;
- `seed_receipt_id` and `seed_receipt_sha256`;
- opaque `reviewer_id` and `reviewer_role=external-reviewer`;
- `reviewed_at` in the exact timestamp form from section 2;
- `external_artifacts`, one entry for every derived slot in exact order;
- `authorship_scopes`, one entry for every derived
  `(scenario_slot, kind)` pair in exact order;
- `no_variant_output_access_before_authorship=true`; and
- `external_custody_until_reveal=true`.

Each `external_artifacts` entry is exactly:

- `artifact_id`, `scenario_slot`, and `kind`, equal to its derived slot;
- `content_sha256`, excluding exactly the 16 digests formed by repeating one
  lowercase hexadecimal character 64 times; every other syntactically valid
  digest remains `unverified_until_reveal`;
- `canonicalization`, equal to the derived slot;
- integer `byte_length >= 1`; and
- `reveal_phase`, equal to the derived slot.

The attestation contains no artifact body, label entry, holdout source,
hidden-test name, expected value, credential, private path, or personal contact
information. Swapped scenario/kind hashes and incomplete scopes reject
`invalid_review_attestation`.

Before its reveal phase an entry means only
`verification_state=unverified_until_reveal`. A syntactically valid random
digest is not proof that content exists. At reveal, the isolated loader must
validate the content schema or raw-byte contract, recompute `content_sha256`
and `byte_length`, and reject missing or mismatched content before it affects a
run, score, aggregate, or claim.

## 6. Deterministic ExecutionManifest41 Assembly

Final assembly is a deterministic pure function of canonical seed bytes and
canonical attestation bytes. No wall clock, random ID, caller-selected catalog
record, optional metadata, or caller-supplied projection is accepted.

Every final top-level field is classified here; unclassified fields reject:

| Final field | Class | Exact source or derivation |
| --- | --- | --- |
| `record_type` | schema constant | `execution_manifest` |
| `manifest_version` | schema constant | `execution-manifest/4.1` |
| `semantic_rules_version` | schema constant | `4.1` |
| `created_at` | seed-frozen | `/created_at` |
| `descope_rung` | seed-frozen | `/target_rung` |
| `code_hashes` | seed-frozen | `/code_hashes` |
| `scenario_slots` | deterministic | ordered `/scenario_plan/*/scenario_slot` |
| `evidence_scenarios` | deterministic | exact `evidenceScenario41` records below |
| `fixture_hashes` | deterministic | public fixture catalog content hashes; blind fixture attested content hashes |
| `label_hashes` | attested external | relation-label-ledger content hash per scenario |
| `hidden_test_hashes` | deterministic | public hidden-test catalog content hashes; blind hidden-test attested content hashes |
| `variants` | seed-frozen | `/variants` |
| `provider_settings` | seed-frozen | `/provider_settings` |
| `comparison_contract` | seed-frozen | `/comparison_contract` as `comparisonContract41` |
| `evaluator_contract` | seed-frozen | `/evaluator_contract` |
| `technical_failure_codes` | seed-frozen | `/technical_failure_codes` |
| `execution_order` | seed-frozen | `/execution_order` |
| `claim_declarations` | seed-frozen | `/claim_declarations` |
| `evaluator_image_digest` | seed-frozen | `/evaluator_image_digest` |
| `input_artifact_catalog` | deterministic | exact union defined below |
| `review` | deterministic | exact review object defined below |

`evidenceScenario41` replaces the legacy `evidenceScenario`; no `4.1` manifest
uses the legacy embedded-provenance shape. It is closed and contains exactly:
`scenario_slot`, `evidence_class`, `custody_state`, `fixture_artifact_id`,
`source_ledger_artifact_id`, `repository_snapshot_artifact_id`,
`model_visible_snapshot_artifact_id`,
`hidden_test_hash_artifact_id`, `required_memory_label_hash_artifact_id`,
`relation_label_hash_artifact_id`, `leakage_review_hash_artifact_id`, and
`provenance_artifact_id`.

For a public scenario, IDs for fixture/source-ledger/repository/model-visible/
hidden-test/provenance copy the matching seed scenario pointers; the three review IDs are
the deterministic external slot IDs; `evidence_class` is
`source_backed_synthetic`; `custody_state=externally_reviewed_hashes_only`; and
`provenance_artifact_id` is the seed-frozen provenance ID. For a blind scenario,
fixture/source-ledger/model-visible/hidden-test plus the three review IDs are
their deterministic external slot IDs; `evidence_class=blind_holdout`;
`custody_state=sealed_external`; and `provenance_artifact_id=null`. No field
depends on an external artifact body.

For a blind scenario, `repository_snapshot_artifact_id` equals
`fixture_artifact_id`; the externally authored fixture bundle is the exact
repository tree materialized for that cell. There is no second blind repository
slot or lookup.

For each execution cell, the effective repository snapshot and model-visible
snapshot are resolved exclusively from that cell's matching
`evidenceScenario41`. The global `comparison_contract` cannot carry either ID.

The three top-level scenario maps have exactly the `scenario_slots` key set.
`fixture_hashes[slot]` is public `/scenario_plan/*/fixture_sha256` or blind
attested fixture **content** SHA-256. `label_hashes[slot]` is always the attested
relation-label-ledger **content** SHA-256. `hidden_test_hashes[slot]` is public
`/scenario_plan/*/hidden_test_content_sha256` or blind attested hidden-test-bundle
**content** SHA-256. None of these values is a catalog-wrapper SHA-256.

The final catalog is the exact union of:

1. every seed catalog record, unchanged and marked `origin=seed_frozen`;
2. one seed record and one attestation record, each marked
   `origin=protocol_record`, with deterministic artifact IDs
   `evaluation_review_seed` and `external_review_attestation`; and
3. one external hash-reference record per derived slot, marked
   `origin=attested_external_reference`.

The seed protocol record path is exactly
`protocol/evaluation-review-seed.json`; the attestation path is exactly
`protocol/external-review-attestation.json`. Their SHA-256 and bytes are derived
from their RFC 8785 bytes. Every external reference path is exactly
`protocol/external-hashes/<scenario_slot>/<kind>.sha256`. These namespaces,
IDs, paths, origin values, sanitization fields, and content policy are schema
constants or deterministic derivations. Any ID/path collision or path mutation
rejects before registration.

An external hash-reference record has deterministic artifact ID equal to its
slot ID, `kind=external_hash_reference`, its scenario/kind/canonicalization/
reveal metadata from the attestation, and `content_sha256`. Its referenced file
payload is exactly the 64 lowercase ASCII characters of `content_sha256` with
no newline. The catalog record's own `sha256` hashes those 64 wrapper bytes;
`bytes` is exactly 64. The wrapper digest and external content digest are never
interchangeable.

The final `review` object is exactly:

- `reviewer_role`, copied from the attestation;
- `review_seed_artifact_id=evaluation_review_seed`;
- `review_seed_sha256`;
- `review_attestation_artifact_id=external_review_attestation`;
- `review_attestation_sha256`; and
- `leakage_review_hashes`, the exact scenario-keyed map of attested
  `leakage_review` content hashes.

Semantic validation loads seed and attestation bytes from the final catalog,
recomputes both hashes, re-derives the required slot matrix, reassembles the
entire expected `ExecutionManifest41`, and requires RFC 8785 byte equality with
the supplied final manifest. This full reassembly is the seed projection; no
field-removal algorithm, caller projection, or projection hash exists.

## 7. Unique Registration And Descendant Binding

The registration authority stores an immutable mapping
`review_seed_sha256 -> execution_manifest_sha256`. Byte-identical registration
is idempotent. A second distinct final manifest hash for the same seed rejects
`review_seed_reuse`, even if the attestation is unchanged. Any change requiring
a different final manifest requires a new seed, external authorship cycle, and
attestation.

No provider or sandbox action may begin before unique registration succeeds.
Runs, aggregates, and EvidenceManifests bind only the registered final manifest
hash, never the seed hash. Every descendant's semantic-rules version equals the
bound final manifest's version.

## 8. Procedural Chronology And Honesty Boundary

Content addressing does not authenticate a human, chronology, custody, or
artifact existence. Claim-bearing operation therefore retains outside the
implementation workspace:

1. reviewer-controlled `seed_receipt`, monotonic sequence `1`, binding the seed
   hash and receipt time before authorship; and
2. reviewer- or user-controlled `manifest_registration_receipt`, monotonic
   sequence `2`, binding seed hash, attestation hash, unique final manifest
   hash, and registration time before provider or sandbox action.

`seed_receipt` is a closed RFC 8785 record with exactly
`record_type=seed_receipt`, `receipt_version=review-receipt/4.1`,
`sequence=1`, `receipt_id`, `review_seed_sha256`, `received_at`,
`receiver_role=external-reviewer`, and `assurance=procedural`.

`manifest_registration_receipt` is a closed RFC 8785 record with exactly
`record_type=manifest_registration_receipt`,
`receipt_version=review-receipt/4.1`, `sequence=2`, `receipt_id`,
`review_seed_sha256`, `review_attestation_sha256`,
`execution_manifest_sha256`, `registered_at`, `registrar_role` in
`external-reviewer|user-custodian`, and `assurance=procedural`.

The attestation binds the first receipt. The final EvidenceManifest catalogs
the second receipt after execution without creating a pre-run hash cycle.
Receipt content is sanitized and contains no personal contact information.

These records remain procedural assertions unless an independently controlled
signing/timestamp service is added. Public evidence must then state exactly
`reviewer_authentication=procedural` and
`chronology_assurance=procedural`; it must not say validator-authenticated,
cryptographically authenticated, independently timestamped, or proof of
artifact existence. Backfilled files can still satisfy content validation, so
custody and timing remain disclosed limitations.

## 9. Version And Migration

The manifest schema dispatcher is exactly two disjoint branches:

- `semantic_rules_version=4.0` and `descope_rung=Floor`, using the legacy Floor
  review shape; or
- `semantic_rules_version=4.1` and `descope_rung` in `Full|R1|R2`, using this
  seed/attestation shape.

There is no schema-valid claim-bearing `4.0` branch and no `4.1` Floor branch.
Historical `4.0` non-Floor records, if inspected, use a separately named
diagnostic-only parser that cannot register runs, aggregates,
EvidenceManifests, or claims.

Run, aggregate, and EvidenceManifest schema and semantic validation dispatch
from the bound final manifest's rules version. `4.0` descendants are accepted
only for a valid bound Floor manifest. `4.1` descendants are accepted only for
a valid uniquely registered Full/R1/R2 manifest. Cross-version descendants and
records bound to a seed hash reject.

## 10. Failure Semantics

All failures are terminal and occur before the affected artifact can influence
a claim-bearing action. Stable codes are:

- `invalid_review_seed`;
- `invalid_review_attestation`;
- `review_seed_hash_mismatch`;
- `review_seed_projection_mismatch`;
- `external_artifact_set_mismatch`;
- `external_artifact_content_mismatch`;
- `invalid_reveal_phase`;
- `invalid_custody_state`;
- `review_seed_reuse`; and
- existing catalog, path, privacy, schema, and secret errors where applicable.

Validation is fail closed. There is no repair, fallback, partial import, or
placeholder mode. Pre-reveal hashes remain explicitly unverified.

## 11. Minimum T068 Adversarial Matrix

T068 must assert stable error code and JSON pointer for at least:

1. cross-language canonical golden and rejection vectors;
2. mutation of every seed-frozen scalar, nested value, list order, claim,
   provider setting, evaluator field, technical code, scenario identity, and
   catalog record;
3. missing code-hash keys, changed tree roots, symlinks, or unclassified seed
   artifacts;
4. missing, extra, duplicate, wrong-kind, catch-all, cross-scenario, or
   forbidden-rung external slots;
5. swapped artifact hashes, incomplete scopes, attestation replay, and altered
   slot metadata;
6. repeated-character sentinel digests and reveal bytes that mismatch an
   otherwise random valid digest;
7. two distinct final byte strings from one seed, including timestamp, version,
   path, catalog, or wrapper mutation;
8. early reveal, sealed content in seed/final/model-visible bytes, and missing
   reveal-time content;
9. 4.0 Floor, 4.0 Full/R1/R2, 4.1 Floor, and valid simulated 4.1 R2 and Full;
10. descendants bound to a seed hash, wrong final hash, or wrong rules version;
    and
11. a Full test packet whose simulated external reviewer marker remains
    non-droppable and outside public evidence artifacts.

It must additionally reject wrong/reordered/renamed public registry scenarios;
cross-scenario artifact or content aliases; mutation of every nested
`evidenceScenario41` field and every content-vs-wrapper map value; reserved
catalog IDs/paths and generated-path collisions; empty, unsorted, nonexistent,
duplicate, or cross-scenario required-memory refs; leakage-review field/hash/
reason/verdict mismatches; malformed or unsafe deterministic bundles; every
early reveal transition; malformed or cyclic receipts; impossible timestamps;
and any of the 16 repeated-character digest sentinels.

The matrix must include these named closure probes:

- `B13`: reject legacy global repository/model-visible snapshot pointers or any
  effective-input disagreement with `evidenceScenario41`;
- `B14`: reject cell A phase advancement authorizing cell B hidden tests, and
  reject reuse of A's extraction root by any later provider action;
- `B15`: reject scenario-label reveal while any predeclared claim-bearing output
  for that scenario remains mutable;
- `B16`: reject every wrong/missing/extra `sourceProvenance41` field, wrong
  registry URL/license, scenario mismatch, empty/non-full commit refs, or
  authored-summary digest mismatch;
- `B17`: reject `kind=fixture,purpose=hidden_tests` and the inverse at
  `/purpose` before bundle entry parsing;
- `B18`: reject a legacy nested `relation_label_ledger_sha256` in `4.1` or any
  mismatch among `label_hashes[slot]`, the relation-label artifact reference,
  and attested content digest; and
- `B19`: accept exact valid Gregorian UTC vectors in years `0001`, valid leap
  years, and `9999`, while rejecting year `0000` in both Python and Node.
- `B20`: reject a missing/altered repository pointer, any global/catalog/seed
  lookup at execution time, or a blind repository pointer unequal to its
  fixture pointer;
- `B21`: reject a public model-visible snapshot encoded as JSONL, bare array,
  alternate wrapper, duplicate-key JSON, reordered events, duplicate/missing
  refs, false/missing authored-summary flag, or mismatched event/projection hash;
  and
- `B22`: reject `.`, `..`, empty, repeated-slash, leading/trailing-slash,
  non-ASCII, and ASCII-case-alias bundle paths before decoding or writes.

## T053 V4 pre-registration eligibility

Diagnostic projection and execution eligibility are different types. Raw
manifest mappings and diagnostic projections cannot register. Production
assembly requires the exact V4 semantic report, closed phase-2 custody report,
all leakage bodies, and a separately retained expected custody-report JCS hash
and byte length, compared against a stable read before parsing. Only an opaque
`EligibleExecutionManifest41` may enter the new five-field eligible registry.
Legacy registration rows never resolve as eligible. Normative details are in
`reviews/t053-leakage-contract-remediation-v4.md` and
`reviews/t053-semantic-adjudication-contract-v4.md`.
