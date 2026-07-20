# RecallPack Local Readiness Report

Status: local package green; M45 first-run handoff simulator implemented; M48
credential-free live E2E preflight generated; M50 external benchmark and winner
polish complete; M51 final architecture diagram complete; M53 demo media
package complete; M54 public release gate complete; M55 local screenshot
gallery complete; M56 reproducible screenshot capture complete; M57 Devpost
preflight complete; M58 Devpost materials export complete; M59 submission
evidence index complete; M60 final submission gate complete; M61 public repo
preflight complete; M62 external-review remediation complete; M63 fair
baseline and patch-generation provider proof complete; M64 live Qwen
patch-generation preflight complete; M65 live Qwen E2E complete; M104
latest-bundle Docker/ECS proof complete; M66 winner narrative polish: complete. Live Qwen E2E
was rerun with approval and produced a sanitized passing trace. M67 final judge
rehearsal: complete. M68 video production packet: complete. M69 recording
rehearsal gate: complete. M71 one-click stale-memory failure replay: complete.
M72 current screenshot gallery refresh: complete. M73 live Qwen trace explorer:
complete. M74 external-review remediation: complete. M75 current-model live
Qwen evidence reconciliation: complete. M76 real embedding baseline preflight:
complete. M77 non-isomorphic pagination fixture: complete. M78 submission wording consistency gate: complete. M79 README verification command sync: complete. M80 current release-candidate wording sync: complete. M81 bundle self-reference consistency gate: complete. M82 current evidence snapshot refresh: complete. M83 latest verification label cleanup: complete. M84 public readiness date sync: complete. M85 deadline runway plan: complete. M86 recording release-candidate sync: complete. M87 public copy generation source sync: complete. M88 winner-grade audit refresh: complete. M89 release-candidate wording refresh: complete. M90 current-day deadline runway refresh: complete. M91 recording package wording sync: complete. M92 submission media copy consistency gate: complete. M93 judge first-run command contract: complete. M94 public release gate command contract: complete. M95 current-day release readiness refresh: complete. M96 current-package wording guardrail: complete. M97 source-to-bundle parity preflight: complete. M98 adversarial review remediation: complete. M99 current evidence wording sync: complete. M106 current deadline and remote-sync boundary refresh: complete. M107 submission readiness loop: complete. M109 first-principles positioning remediation: complete; the headline is now write-time lifecycle exclusion, local 1/3 vs 3/3 is labeled as an authored deterministic replay, and stored live baseline traces are disclosed as selecting the active retry decision. M114 consent-first real trace intake: complete. M115 trace sanitizer hardening: complete. M116 ProjectOdyssey dry-run: complete. M117 ProjectOdyssey eight-fixture surface: complete. M118 judge-facing surface reset: complete. M119 ProjectOdyssey live-Qwen preflight path: complete. M120 ProjectOdyssey live Qwen run: complete as passing source-backed fixture evidence; live Qwen selected required active sources, excluded stale policy, and RecallPack live patch generation passed 3/3 ProjectOdyssey fixture tests. The separate M98 retry-policy rerun remains failed evidence.

Date: 2026-07-09

## Verified Local Package

- Static demo data was regenerated with `tools/build_demo_data.py`.
- First-screen demo data now separates standalone Qwen API smoke status from
  live observe/compile E2E status.
- First-screen demo now includes a one-click stale-memory failure replay that
  steps through stale context, the wrong retry patch, fixture tests 1/3, the
  active memory pack, and fixture tests 3/3.
- Review packet was regenerated with `tools/build_review_packet.py`.
- README, MIT license, demo runbook, review packet, skeptical judge Q&A,
  M50 external benchmark and winner polish doc, M71 one-click replay payload,
  3-minute demo video script,
  M66 blog post draft, M67 final judge rehearsal, M68 video production packet,
  M69 recording rehearsal report, architecture diagram, demo media package, submission
  checklist, public repo readiness report, public release gate, Devpost
  preflight, Devpost materials export, submission evidence index, final
  submission gate, public repo preflight, local screenshot gallery, gated
  action approval matrix, gated action runbook, deployment proof, static UI,
  and Docker target are present.
- Hero downstream patch/test proof, M23/M77/M110/M113/M117 eight curated lifecycle fixtures, judge
  first-screen summary, M21 quality hardening audit, micro-suite
  behavior-contract fixture evaluator, first-run handoff simulator, one-click
  stale-memory failure replay, Qwen provider
  integration trace payload, live Qwen contract writer, gated live Qwen E2E runner,
  M73 live Qwen trace explorer,
  credential-free live E2E preflight,
  Devpost preflight,
  Devpost materials export,
  submission evidence index,
  final submission gate,
  public repo preflight,
  fair computed baselines,
  skeptical judge Q&A, demo server, submission packet, submission docs, public
  repo readiness docs, and sanitized submission bundle are covered by tests.
- M114 adds a consent-first real trace intake validator and format dry run for
  future sanitized traces; no real trace is promoted to submission evidence by
  default.
- M115 adds `--sanitize --sanitized-out` so raw local candidates can be redacted
  before validation and review.
- M116/M117 add the source-backed ProjectOdyssey JIT policy fixture as an
  authored synthetic scenario, not production trace evidence. Project-h uses
  an unrigged deterministic keyword-provider baseline with no fixture-authored
  baseline embedding terms or downrank phrases.
- M118 resets judge-facing openings: README, Devpost copy, demo video opening,
  demo payload wording, and UI labels now lead with the MemoryAgent product
  problem and ProjectOdyssey evidence instead of internal milestone labels.
- M119 adds a credential-free ProjectOdyssey live-Qwen E2E preflight over the
  source-backed JIT fixture. It proves the provider-contract path can observe,
  compile, run raw-history embedding+rerank, and request patch generation for
  `ci_policy` without reading credentials or making network calls.
- M120 ran the ProjectOdyssey live Qwen path against the China DashScope
  endpoints. The sanitized trace is
  `docs/submission/projectodyssey-live-qwen-e2e-trace.json` with
  `live_e2e_passed`: required_sources_selected=True,
  stale_sources_excluded=True, selected_sources=`session-h-current:turn-006`
  and `session-h-history:turn-004`, provider_trace_count=32, downstream patch
  generation baseline 1/3 and RecallPack 3/3, and token usage memory=21722,
  embedding=727, rerank=474, patch_generation=1963. This is source-backed
  fixture integration evidence, not a broad live benchmark.
- Latest generated local bundle:
  `dist/recallpack-submission-20260720-231611/`.
- Latest deployed ECS runtime:
  M104 `recallpack-demo:m104-20260704-123846` image built from
  `dist/recallpack-submission-20260704-123846/`, tagged as
  `recallpack-demo:cloud`, and loaded to ECS over SSH without pushing an image
  registry.
- The approved ECS endpoint still reflects the M104 7/4 bundle and passed
  public judge smoke at `http://101.133.224.223/`; do not claim the latest 7/7
  local bundle is deployed without another redeploy and judge smoke run.
- M67 freezes the judge-facing local surface, M71 refreshes that surface with
  the one-click replay: publish the sanitized bundle, not the raw workspace;
  keep required Devpost file uploads, video upload, Devpost submit, live Qwen
  rerun, Docker image push, and any further ECS replacement as manual gates.
- M85 adds internal deadline runway control and does not add a new
  judge-facing product claim.
- M104 keeps the recording packet and video rehearsal gate honest about the
  current evidence snapshot and latest-bundle ECS runtime.
- M87 syncs README and review-packet generation source so judge-facing copy no
  longer regresses from manually corrected M85/M86 wording back to stale M81
  release-candidate text.
- M88 refreshes the winner-grade benchmark audit so old M42 P0 findings do not
  contradict the current passing live Qwen E2E trace, approved ECS proof, and
  one-click replay evidence.
- M98 adversarial review remediation: local tests now disclose fixture-authored
  baseline scoring terms, the live E2E preflight exercises an unrigged
  raw-history embedding/rerank baseline path, and public bundles exclude
  internal audit/research notes.
- M104 current evidence wording sync: README, review packet, final judge
  rehearsal, video production packet, recording gate, public repo readiness,
  and local readiness now name M98 as the current evidence snapshot while
  preserving M104 as the public ECS runtime boundary.
- M102 refreshes current-package wording so README, review packet, final judge
  rehearsal, video packet, recording gate, and public repo readiness
  consistently name M98 as the current local evidence snapshot while preserving
  M104 as the public ECS runtime boundary.
- M90 refreshes the current-day deadline runway and local readiness dates to
  2026-07-04 without adding a new judge-facing product claim.
- M106 refreshes the current-day deadline runway and release-readiness dates to
  2026-07-07, about 2 days 18 hours 17 minutes before the working deadline,
  without adding a new judge-facing product claim.
- M91 recording package wording sync: complete.
- M104 updated recording copy after the M104 prior verified ECS deployment
  while preserving M98 as the current evidence snapshot.
- M68 freezes the recording-day flow: one-take run of show, retake triggers,
  on-screen no-go list, upload package, and final self-check.
- M69 checks the recording packet, screenshots, manual upload gates, public ECS
  wording, and latest local bundle reference before recording.
- M71 upgrades the first screen from a static summary to a click-through replay
  while keeping the evidence source as the existing downstream temp-repo
  patch/test execution.
- M73 adds `qwen_load_bearing.trace_explorer` to `/api/demo` and the Evaluate
  view. It summarizes the checked-in sanitized live E2E trace with
  `role_summary`, stage flow, selected/excluded sources, and a safety boundary.
- M73 trace explorer is sanitized trace only: no credentials, prompts redacted,
  no raw memory text, and the local demo makes no live Qwen calls.
- M74 external-review remediation adds explicit truthfulness labels after
  adversarial review: local proof uses a deterministic context-keyed patch
  provider, the local raw-history baseline is a keyword-scored fake-embedding
  baseline, the micro-suite is a behavior contract fixture suite, and Qwen live
  evidence is a stored sanitized one-run trace.
- M75 reconciles Qwen model evidence after adversarial review: the current
  shipped model evidence is `docs/submission/live-qwen-e2e-trace.json` with
  `qwen3.7-plus-2026-05-26`; the older standalone `live-qwen-trace.json` is
  only a historical API contract smoke.
- M76 adds a credential-free real `text-embedding-v4` raw-history baseline
  preflight at `docs/submission/live-qwen-embedding-baseline-preflight.json`.
  It records `preflight_status=ready_for_live_embedding_baseline_rerun`,
  `request_role_counts=embedding=13 rerank=1`, expected selected sources
  `session-a:turn-001, session-a:turn-003`, and `network_calls_made=false`.
- M79 syncs README and demo-runbook verification commands with the current
  public test/tool surface, including the live embedding baseline test,
  embedding baseline preflight/runner, and video rehearsal gate.
- M80 syncs final rehearsal, video production packet, video rehearsal gate, and
  review packet wording so the local release candidate wording no longer
  points at older M66/M68/M71 packages.
- M81 makes the bundle builder rewrite timestamped bundle self-references inside
  copied public docs to the target bundle path, preventing stale report paths
  when a fresh bundle is produced. The rewrite intentionally excludes Python
  source files so bundled self-tests keep their original assertions.
- M82 refreshes the current evidence snapshot after M81 so final rehearsal,
  video rehearsal, review packet, README, and local readiness wording identify
  M81 as the current local release candidate while preserving M65 as the public
  ECS boundary.
- M83 cleans up stale "latest" verification labels so current fresh-clone,
  final submission gate, and public repo preflight evidence point at M82/M83
  verification, not older M48/M60/M71 milestone labels.
- M84 syncs the public repository readiness report date to the current
  2026-07-01 evidence snapshot so the report date matches the current bundle
  and M82/M83 gate evidence.
- The latest local bundle includes M55 local screenshot gallery, M54 public release gate, M53 demo media package, M51 final
  architecture diagram, M50 external benchmark and winner polish,
  M66 winner narrative polish, `docs/submission/blog-post-draft.md`,
  `docs/submission/demo-video-script.md`, M64 credential-free live E2E
  patch-generation preflight, M48 credential-free live E2E preflight, M45 first-run handoff
  simulator, M43 gated live Qwen E2E runner
  for hero observe/compile lifecycle,
  M41 deterministic keyword fake provider path for local HTTP
  `/compile`, M40 Qwen memory decision tool-calling contract, M38
  provider-backed fake memory decision path for HTTP observe,
  M37 shared HTTP runtime and cross-session sequence fix, M36 static
  demo parity gate, M35 fresh-clone public surface
  completeness gate, M34 judge quick checks in `SUBMISSION_MANIFEST.md`, M33
  compact health readiness endpoint, M32 full fresh-clone rehearsal mode, M31
  stronger judge smoke assertions, M30 public repo root self-smoke, M29
  fresh-clone rehearsal and latest-bundle Docker runtime proof, M28 prior
  final-bundle Docker runtime proof, M27 browser visual QA, M26 HTTP observe
  endpoint proof, M25 skeptical judge Q&A, M24 judge smoke, M23 multi-fixture plus M77/M110/M113/M117 eight-fixture
  fixture proof, M21 quality hardening audit, M20 fresh-clone rehearsal, M19 fair
  computed baselines, M18 Docker proof, M17 public repo readiness, M16 live
  trace proof, M15 narrative polish, and M14 retrieval proof. The raw working
  directory is not the submission artifact.

## Verification Snapshot

- Python compile command: passed.
- Unit test suite: 203 tests passed in M119 verification.
- Final M119 full gate passed:
  `python3 tools/submission_readiness_loop.py --full`.
- Latest M119 full fresh-clone smoke passed:
  `PYTHONPATH=src python3 tools/fresh_clone_smoke.py --source dist/recallpack-submission-20260720-231611 --full`.
- focused M65 tests remain recorded for truthful Qwen status, terminal provider
  failure handling, threaded demo server, and judge smoke.
- focused M66 submission-doc tests passed for winner narrative polish, Docker
  proof wording, and final submission gate.
- JavaScript syntax check: passed.
- Judge smoke script: passed against the local demo server.
- Sanitized submission bundle build: passed.
- Latest existing bundle target: `dist/recallpack-submission-20260720-231611/`.
- Post-M25 fresh bundle rebuild: passed.
- Sanitized submission bundle scan: zero local path, secret, generated artifact,
  and internal path hits.
- M72 current screenshot gallery: complete.
- M72 generated non-destructive M71 replay screenshots under
  `docs/submission/media/m71-replay/`; the older M55 root-level PNGs are
  retained as historical assets.
- M73 live Qwen trace explorer: complete.
- M73 role_summary covers memory_decision, embedding, rerank, and
  patch_generation from the sanitized live E2E trace.
- M73 safety boundary records sanitized trace only and local demo makes no live
  Qwen calls.
- M74 external-review remediation: complete.
- M74 provider-mode labels are present in `/api/demo`, `/api/health`, UI copy,
  review packet, and the submission manifest.
- M75/M76 evidence labels are present in the README, review packet,
  skeptical judge Q&A, demo runbook, and submission manifest.
- M76 preflight command: `PYTHONPATH=src python3 tools/build_live_qwen_embedding_baseline_preflight.py`.
- M45 browser QA: First-Run Handoff Simulator started inside the desktop and
  mobile first viewport, showed baseline 1/3 and RecallPack 3/3, and had zero
  horizontal overflow at that time.
- Public repository boundary: publish the sanitized bundle contents, not the raw
  workspace.
- License: MIT `LICENSE` present.
- Local server smoke: passed.
- Fresh-clone rehearsal copied the sanitized bundle into a temp directory and
  passed py_compile, focused unittest, JS syntax, and judge smoke checks.
- Fresh-clone full mode runs full public-test discovery. Recursive smoke tests
  and the custody-bound frozen-executor suite skip explicitly when the private
  frozen execution manifest is absent from the public bundle:
  `PYTHONPATH=src python3 tools/fresh_clone_smoke.py --source . --full`.
- Latest M106 fresh-clone smoke passed for
  `dist/recallpack-submission-20260720-231611/` with py_compile, unit subset,
  JS syntax, local server smoke, and judge smoke all passed.
- Latest M106 final submission gate passed for
  `dist/recallpack-submission-20260720-231611/` with Devpost preflight,
  evidence index, public bundle scan, and full fresh-clone rehearsal all
  passed.
- Latest M106 public repo preflight passed for the current sanitized bundle with
  MIT license, README judge entry, manifest, forbidden paths, bundle scan, and
  judge commands all passed. It records the public repo URL but does not prove
  the latest sanitized bundle has been pushed to GitHub.
- M93 judge first-run command contract: `SUBMISSION_MANIFEST.md`,
  `tools/public_repo_preflight.py`, README, and review packet copy-ready
  commands share `JUDGE_FIRST_RUN_COMMANDS`.
- M94 public release gate command contract: `docs/submission/public-release-gate.md`
  now includes every command from `JUDGE_FIRST_RUN_COMMANDS`, including
  `python3 tools/video_rehearsal_gate.py`.
- M95 historical release readiness refresh recorded local readiness and public
  repo readiness dates as `2026-07-04`, with the internal deadline runway
  reference at `2026-07-04 00:01 CST`.
- M106 current-day release readiness refresh: current local readiness and
  public repo readiness dates are `2026-07-07`, and the internal deadline
  runway reference is `2026-07-07 10:43 CST` with about 2 days 18 hours 17
  minutes remaining.
- M107 submission readiness loop: `python3 tools/submission_readiness_loop.py --full`
  aggregates Devpost preflight, video rehearsal, public repo preflight, and
  final submission gate into one local-only loop while keeping push, deploy,
  upload, submit, credentials, and live Qwen actions gated.
- M96 current-package wording guardrail: judge-facing recording, review,
  public-repo, and generated packet surfaces now use version-neutral latest
  local package wording instead of calling M90 the current package.
- M97 source-to-bundle parity preflight: raw-workspace public repo preflight
  now compares all public-bundle source files with the latest sanitized bundle
  and fails if source docs/code changed after the bundle was built.
- Historical M48 full fresh-clone rehearsal remains superseded by the current
  M82/M83 fresh-clone and final submission gate evidence above.
- Public repo root self-smoke command is documented and covered:
  `PYTHONPATH=src python3 tools/fresh_clone_smoke.py --source .`.
- `SUBMISSION_MANIFEST.md` includes judge quick checks, local credential-free
  smoke commands, and the primary API surface.
- Fresh-clone public surface gate checks required public files and manifest
  judge quick checks before running compile, tests, JS syntax, and server smoke.
- Static demo parity gate compares `web/demo-data.js` with the current
  fixture-backed demo payload and allows only dynamic memory IDs to differ.
- Downstream generated Python safety validation rejects dangerous imports and
  calls before fixture tests import model-generated code.
- Last completed local Docker runtime proof: passed from
  `dist/recallpack-submission-20260704-123846/`.
- Last completed Docker image: `recallpack-demo:cloud`.
- Last completed Docker container binding: `127.0.0.1:8817->8789`.
- Docker daemon blocker: resolved by starting Docker Desktop.
- `GET /api/demo` returned the 32-event behavior-contract fixture suite.
- `GET /api/demo` returned M23/M77/M110/M113/M117 eight curated lifecycle fixtures.
- `GET /api/demo` returned M16 `hero_story` with baseline 1/3, RecallPack 3/3,
  retrieval path, standalone live API smoke passed status, and
  `live_qwen_e2e_status=live_e2e_passed`.
- `GET /api/demo` returned M45 `handoff_simulator` with baseline 1/3,
  RecallPack 3/3, stale source visibility, and active-memory source visibility.
- `GET /api/health returns compact readiness` with MemoryAgent track,
  `live_contract_passed`, `live_qwen_e2e_status=live_e2e_passed`, Qwen provider
  roles, eight-fixture count, baseline 1/3, RecallPack 3/3, and local
  credential-free status.
- Judge smoke verifies standalone `live_contract_passed`, live E2E passed
  status, first-screen baseline 1/3,
  RecallPack 3/3, first-run simulator baseline 1/3 and RecallPack 3/3,
  retrieval path, Qwen provider roles, compact health, shared runtime SQLite,
  deterministic keyword compile provider mode, and no hidden fixture replay
  under `RECALLPACK_SQLITE_PATH`.
- Approved public Alibaba Cloud ECS deployment: passed at
  `http://101.133.224.223/` after M104 redeployed the 7/4 sanitized bundle.
- Current public ECS deployment: M104 credential-free runtime from
  `dist/recallpack-submission-20260704-123846/`.
- Public ECS judge smoke passed after the M104 redeploy; do not claim the 7/7
  local bundle is deployed without another redeploy and judge smoke run.
- Public ECS image tags: `recallpack-demo:m104-20260704-123846` and
  `recallpack-demo:cloud`.
- Public ECS judge smoke:
  `PYTHONPATH=src python3 tools/judge_smoke.py --url http://101.133.224.223 --timeout 20`
  returned `status=passed`.
- Public ECS `POST /compile` selected `session-a:turn-005` and
  `session-a:turn-003`, used `retrieval_mode=embedding_top_n`, and returned
  `fixture_replayed=false`.
- Judge smoke seeds the compile proof through HTTP `POST /observe` events before
  calling `POST /compile`.
- Judge smoke verifies `POST /observe` returns a sanitized memory_decision
  provider trace from the provider-backed fake path.
- `POST /observe wrote auth decision memory` from a fresh `judge-smoke-*`
  session without polluting the retry compile proof.
- Shared-store regression proof: an env-backed `POST /observe` write from
  `shared-session-a:turn-001` is selected by the following `POST /compile`, with
  `runtime_store=shared_sqlite` and `fixture_replayed=false`.
- `POST /compile selected active retry memory` from `session-a:turn-005`.
- `POST /compile` selected project preference memory from `session-a:turn-003`.
- `POST /compile` excluded stale retry memory from `session-a:turn-001`.

## Evidence Metrics

- Hero fixture: 12 ordered session events.
- M15 first-screen narrative polish: complete.
- M16 live Qwen contract trace: complete.
- M75 current shipped Qwen model evidence reconciliation: complete.
- M76 real embedding baseline preflight: complete.
- M17 public repository readiness: complete.
- M18 local Docker runtime proof: complete.
- M19 fair computed baselines: complete.
- M20 fresh-clone rehearsal and public surface polish: complete.
- M21 judge-grade quality hardening audit: complete.
- M22 second independent fixture proof: complete.
- M23/M77/M110/M113/M117 eight curated lifecycle fixtures: complete.
- M24 judge smoke script and final bundle rehearsal: complete.
- M25 skeptical judge Q&A: complete.
- M26 HTTP observe endpoint and judge smoke write-path proof: complete.
- M27 browser visual QA: complete.
- M28 final-bundle Docker runtime proof: complete.
- M29 fresh-clone rehearsal and latest-bundle Docker proof: complete.
- M30 public repo root self-smoke: complete.
- M31 stronger judge smoke assertions and live-status hard gate: complete.
- M32 full fresh-clone rehearsal mode: complete.
- M33 compact health readiness endpoint: complete.
- M34 judge quick check manifest: complete.
- M35 fresh-clone public surface completeness gate: complete.
- M36 static demo data parity gate: complete.
- M37 shared HTTP runtime and cross-session sequence fix: complete.
- M38 provider-backed fake memory decision path for HTTP observe: complete.
- M39 conservative public evidence wording: complete.
- M40 Qwen memory decision tool-calling contract: complete.
- M41 deterministic keyword fake /compile providers: complete.
- M43 live Qwen E2E runner: implemented and gated.
- M46 live Qwen E2E attempted once with approval and wrote
  `docs/submission/live-qwen-e2e-trace.json`.
- Live Qwen E2E stored status `live_e2e_passed` with
  selected_sources=`session-a:turn-005, session-a:turn-004, session-a:turn-003`.
  The latest approved rerun selected active retry memory and project preference,
  excluded stale retry memory, and RecallPack downstream fixture tests passed 3/3.
- M47 live memory-decision contract hardening: complete.
- M47 adds structured event metadata, explicit must-write/must-supersede
  policy, and descriptive tool schema fields for Qwen memory decisions.
- M48 credential-free live E2E preflight: complete.
- M48 preflight artifact:
  `docs/submission/live-qwen-e2e-preflight.json`.
- M48 preflight_status `ready_for_live_e2e_rerun`.
- M48 network_calls_made=false; the preflight does not read Qwen credentials
  and does not call Qwen.
- M98 live E2E preflight request_role_counts: memory_decision=12 embedding=16 rerank=2 patch_generation=2.
- M48 expected selected sources: `session-a:turn-005` and
  `session-a:turn-003`; stale `session-a:turn-001` remains excluded in the
  fake-response E2E rehearsal.
- Stored live Qwen E2E evidence records `live_e2e_passed`; a fresh M98 live
  rerun is now stored at `docs/submission/live-qwen-m98-rerun-trace.json` with
  `live_e2e_failed` because the live patch-generation proof did not pass 3/3
  for RecallPack. Do not present the fresh M98 rerun as passing.
- M50 external benchmark and winner polish: complete.
- M50 records official Devpost judging signals, Devpost Discussions, Qwen Cloud
  Discord, the not-yet-published project gallery, borrow-when-stuck references,
  and prior-art memory systems for later comparison without copying.
- M50 adds `docs/submission/demo-video-script.md`, a 2:20-2:45 script that
  starts from baseline stale context failing 1/3 fixture tests and RecallPack
  active memory passing 3/3.
- M51 final architecture diagram: complete.
- M51 adds `docs/submission/architecture-diagram.md`, covering Browser demo,
  Python demo backend, SQLite event and memory store, `POST /observe`,
  `POST /compile`, Qwen text model, `text-embedding-v4`, `qwen3-rerank`, budget
  selector, downstream evaluator, and Alibaba Cloud ECS.
- M53 demo media package: complete.
- M53 adds `docs/submission/demo-media-package.md` and
  `docs/submission/media/README.md` with a 2:20-2:45 shot list, Devpost image
  gallery candidates, recording acceptance checklist, and manual recording
  boundary.
- M54 public release gate: complete.
- M54 adds `docs/submission/public-release-gate.md`, which requires publishing
  the sanitized bundle rather than the raw workspace and keeps public GitHub
  creation, Devpost submission, image push, ECS replacement, and live Qwen rerun
  blocked until explicit approval.
- M55 local screenshot gallery: complete.
- M55 adds three generated 1280x720 local Devpost screenshot candidates under
  `docs/submission/media/`: first-run handoff simulator, RecallPack active
  memory pack, and Qwen provider evidence. No final video file is checked in
  and no media upload was performed.
- M72 current screenshot gallery: complete.
- M72 adds three generated 1280x720 local Devpost screenshot candidates under
  `docs/submission/media/m71-replay/`: one-click stale-memory failure replay,
  RecallPack active memory pack, and Qwen provider evidence. No upload was
  performed.
- M102 local video candidate: complete.
- M102 adds `docs/submission/media/video-candidate/recallpack-demo-candidate.mp4`,
  a 156-second local MP4 candidate with generated voiceover and captions. It is
  not a Devpost video URL and no video upload was performed.
- M56 reproducible screenshot capture: complete.
- M67 final judge rehearsal: complete.
- M68 video production packet: complete.
- M69 recording rehearsal gate: complete.
- M62 external-review remediation: complete.
- M62 fixes first-screen Qwen wording so standalone live API smoke passed is
  not presented as passing live observe/compile E2E.
- M62 adds terminal provider failure handling so non-retryable provider errors
  dead-letter the event and advance the session cursor instead of stalling the
  session.
- M62 restores the approved public ECS endpoint by replacing the blocked
  single-threaded stdlib server with a `ThreadingHTTPServer` runtime.
- M63 fair baseline and deterministic patch-provider proof: complete.
- M63 raw-history baseline uses keyword-scored fake-embedding plus rerank before
  top-k selection.
- M63 downstream proof uses the same deterministic context-keyed local patch
  provider for baseline and RecallPack.
- M63 patch-generation provider input is goal, selected context, and allowed
  edit paths; it does not read gold patch variants.
- M64 live Qwen preflight now exercises the same provider contract for
  downstream patch generation with two credential-free fake Qwen responses.
- M64 request role counts: memory_decision=12 embedding=16 rerank=2
  patch_generation=2.
- M56 adds `tools/capture_demo_screenshots.py`, which can list the screenshot
  plan without Chrome or a running server and can regenerate the three local
  Devpost screenshots from `http://127.0.0.1:8789`. It does not require live
  Qwen, rejects non-local capture URLs, and does not upload media.
- M57 Devpost preflight: complete.
- M57 adds `tools/devpost_preflight.py`, a local-only JSON preflight that
  checks README, license, release gate, Devpost copy, review packet, screenshot
  PNG dimensions, the latest sanitized bundle manifest, and the stored live
  Qwen E2E status without credentials, network calls, media upload, public repo
  creation, or Devpost submission.
- Current M57 status: `blocked_gated_actions` with local materials and public
  repository URL ready; remaining manual items are required Devpost
  architecture/Alibaba Cloud proof file upload, final video URL or upload,
  final Devpost submit approval, and final media order confirmation.
- M58 Devpost materials export: complete.
- M58 adds `tools/export_devpost_materials.py`, a local-only JSON/Markdown
  export that gathers copy-ready Devpost fields, built-with technologies,
  screenshot assets, verification evidence, and the M57 manual blockers for
  manual copy/paste. It does not read credentials, make network calls, upload
  media, create a public repository, or submit Devpost.
- M59 submission evidence index: complete.
- M59 adds `tools/export_evidence_index.py`, a local-only JSON/Markdown
  claim-to-evidence index mapping MemoryAgent positioning, downstream stale
  handoff proof, Qwen provider integration, live Qwen E2E boundary, public repo
  boundary, and Devpost media readiness to evidence files, verification
  commands, risk levels, and gated boundaries.
- M60 final submission gate: complete.
- M60 adds `tools/final_submission_gate.py`, a local-only JSON report that
  aggregates Devpost preflight, submission evidence index, sanitized public
  bundle scan, and full fresh-clone rehearsal. It does not read credentials,
  call live Qwen, upload media, create a public repository, or submit Devpost.
- M61 public repo preflight: complete.
- M61 adds `tools/public_repo_preflight.py`, a local-only JSON preflight that
  checks the sanitized publish surface, MIT license, README judge entry,
  submission manifest, forbidden paths, bundle scan, and judge commands before
  manual GitHub repository creation. It does not read credentials, call live
  Qwen, create a repository, push code, or change visibility.
- M45 first-run handoff simulator: complete.
- First-run handoff simulator shows baseline 1/3 and RecallPack 3/3 before
  the detailed timeline.
- First-screen story: keyword-scored fake-embedding + rerank raw-history handoff fails 1/3.
- Raw full-history reference: 12 events, not budget-comparable.
- Keyword-scored fake-embedding + rerank baseline: selected from raw event text, reranked before top-k selection, and not fixture-selected source IDs.
- RecallPack active memory handoff passes 3/3.
- First-screen retrieval path: deterministic keyword fake embedding top-N -> qwen3-rerank-shaped fake rerank -> estimated 512-token serialized-memory budget selector.
- Micro-suite: 32 events.
- Micro-suite predictions are produced by the behavior-contract fixture evaluator.
- Deprecated fixture prediction fields are ignored by regression tests.
- Behavior-contract runtime counts, not model-quality metrics:
  TP=20 FP=0 FN=0 TN=12.
- Behavior-contract supersession edges, oracle-backed runtime check:
  10/10 correct.
- Runtime pack-selection contract, not live model recall metric:
  required memory recall at 512 is 1.0.
- Stale selected items: 0.
- Keyword-scored fake-embedding baseline source-recall score: 0/3.
- RecallPack fixture tests: 3/3.
- Downstream computed embedding baseline fixture tests: 1/3 from a temp repo
  stale retry patch.
- Downstream RecallPack fixture tests: 3/3 from a temp repo active retry patch.
- Project-b config loader baseline fixture tests: 1/3.
- Project-b config loader RecallPack fixture tests: 3/3.
- Project-b stale pattern: missing config key returns `None` is superseded
  by raising `ConfigError` with the missing key name.
- Project-c cache policy baseline fixture tests: 0/3.
- Project-c baseline rejection: `empty_patch`; strict downstream validation
  rejects the generated no-op before hidden tests run.
- Project-c cache policy RecallPack fixture tests: 3/3.
- Project-c stale pattern: user-only cache key and 300 second TTL is superseded
  by tenant-aware keys and a 60 second TTL.
- Project-d audit serializer baseline fixture tests: 0/3.
- Project-d baseline rejection: `empty_patch`; strict downstream validation
  rejects the generated no-op before hidden tests run.
- Project-d audit serializer RecallPack fixture tests: 3/3.
- Project-d stale pattern: raw email serialization is superseded by
  `[redacted]` email output.
- Project-e pagination baseline fixture tests: 0/3.
- Project-e baseline rejection: `empty_patch`; strict downstream validation
  rejects the generated no-op before hidden tests run.
- Project-e pagination RecallPack fixture tests: 3/3.
- Downstream proof mode: temp repo patch plus fixture tests.
- Downstream patch generation mode: local deterministic context-keyed patch
  provider; live Qwen patch generation is evidenced by the stored sanitized
  one-run trace.
- Local baseline retrieval mode: keyword-scored fake-embedding baseline, not
  `text-embedding-v4`.
- Micro-suite evidence mode: behavior contract fixture suite, not a broad
  benchmark.
- Qwen provider integration trace: live-provider schema present.
- Live Qwen trace: `live_contract_passed`.
- Actual Qwen token usage: memory=301 embedding=20 rerank=29.
- Provider evidence includes memory_decision, embedding, and rerank traces.
- M73 live Qwen trace explorer: complete.
- M73 `trace_explorer.role_summary` covers memory_decision, embedding, rerank,
  and patch_generation.
- M73 trace explorer safety: sanitized trace only; no credentials; prompts
  redacted; local demo makes no live Qwen calls.
- M74 truthfulness labels: deterministic context-keyed patch provider,
  keyword-scored fake-embedding baseline, behavior contract fixture suite, and
  stored sanitized one-run trace.
- M108 GPT Pro evidence-boundary remediation: first-screen Evidence Boundary
  card added; Qwen evidence now says stored live provider-path integration
  trace plus transparent M98 failed rerun; eight fixtures are described as
  curated lifecycle regression fixtures, not a broad benchmark; ECS is
  described as credential-free runtime proof.
- M108 latest sanitized bundle:
  `dist/recallpack-submission-20260720-231611/`.
- /compile retrieval path: embedding top-N + rerank.
- Fake rerank receives fake-embedding top-N candidates before budget selection.
- local HTTP /compile uses deterministic keyword fake embedding/rerank, so the
  public smoke path is not zero-vector or identity-rerank smoke.
- local HTTP /observe uses a provider-backed fake rule path so credential-free
  judge smoke does not read Qwen credentials.
- live Qwen E2E attempted once with approval; local tests still cover the E2E
  report path with fake HTTP responses and sanitized trace assertions.
- Quality hardening audit: GPT Pro review reopened credibility P0s; M37 fixes
  the disconnected HTTP runtime and cross-session sequence issue; M38 fixes the
  event-id fixture decider issue at the HTTP surface by routing observe through
  a fake provider contract. It does not claim end-to-end live Qwen autonomy,
  broader evaluation, or public deployment risks are closed.
- Skeptical judge Q&A maps core claims to code, test, demo, and documentation
  evidence plus explicit limits.
- M23, M77, M110, M113, and M117 expand the local proof to eight stale-memory patterns.
  Remaining credibility risk: eight local fixtures are still not a broad benchmark.
- M118 removes milestone-heavy wording from the public opening surface while
  preserving detailed milestone history in internal execution docs and review
  appendices.
- M119 extends the no-network live E2E preflight to the source-backed
  ProjectOdyssey JIT fixture and records
  `docs/submission/projectodyssey-live-qwen-e2e-preflight.json`.
- M120 runs ProjectOdyssey live Qwen and records
  `docs/submission/projectodyssey-live-qwen-e2e-trace.json` as
  `live_e2e_passed`: baseline 1/3, RecallPack 3/3. The separate M98 rerun
  remains `live_e2e_failed`, so do not claim broad live downstream reliability.
- M120 public repository sync was completed from a sanitized bundle boundary at
  `https://github.com/cyq1017/recallpack`; after the M121 path-hardening change,
  the public remote has not yet been refreshed with the latest bundle.
- M121 final path hardening closes patch-generation repo-root escape risk:
  unsafe allowed source-file paths are skipped, unsafe generated patch paths are
  rejected, and final patch application has a guard.
- Latest local sanitized bundle:
  `dist/recallpack-submission-20260720-231611/`.
- Unit test suite: 212 tests passed in M121 verification.

## Remaining gated actions

These are intentionally not performed in the local package:

- credential access beyond approved one-time contract and E2E attempts;
- final video recording/upload;
- final media order confirmation;
- image push;
- hackathon submission.

Approval materials:

- `docs/submission/gated-action-approval-matrix.md`;
- `docs/submission/gated-action-runbook.md`.

## Remaining P0/P1 gaps

- M63 local proof update: downstream patches are generated through the same
  deterministic context-keyed local patch provider for the raw-history baseline
  and RecallPack; provider input is goal plus selected context plus allowed edit
  paths, and it does not read gold patch variants.
- P0 gaps remaining for prize-grade credibility: local runtime and packaging
  checks are green, but a fresh approved live Qwen sweep/rerun is still needed
  before claiming the M98 unrigged baseline path as final live evidence.
- P1 gaps: local HTTP demo still uses deterministic fake providers for
  credential-free judge reproducibility, and evaluation remains eight curated
  local fixtures, including one non-isomorphic multi-session case, one
  realistic API-client auth case, and one source-backed provider-auth case,
  rather than a broad benchmark.
- P2 gaps: final submission, external reviewer run, actual video
  recording/upload, final Devpost image gallery assets, latest public repo
  update after another privacy scan, ECS redeploy after M121, and broader
  multi-project benchmarking remain gated or future work.

## Final Submission Material Audit

Date: 2026-07-20 CST

- A six-slide judge deck is present at
  `docs/submission/media/recallpack-judge-deck.pptx`. Its content covers the
  handoff problem, lifecycle mechanism, bounded evaluation evidence, Qwen
  provider boundary, and a local judge replay path.
- The deck was rendered and scanned locally for personal contact data,
  credentials, private local paths, raw API keys, public ECS endpoints, and
  repository-owner identifiers. None were found. The deck is marked
  `privacy_checked=true` and `upload_performed=false` in
  `docs/submission/devpost-upload-state.json`.
- Devpost preflight now treats the privacy-checked presentation deck as a
  separate manual action. It must not be described as uploaded until the user
  performs that action.
- The Devpost materials exporter labels this deck `Not uploaded`; it no longer
  conflates a prepared upload record with an actual upload.
- Presentation-tool inspection logs ending in `.inspect.ndjson` remain local
  generated artifacts and are excluded from the sanitized public bundle.
- The presentation was visually revised before upload: slide 2 now shows the
  stale-policy selection timeline instead of a repeated UI screenshot, slide 5
  uses a readable Qwen-to-deterministic-runtime path, and slide 6 records the
  current 585-test verification. All six final slides were rendered and
  visually reviewed; overflow and template-fidelity checks passed.
- No push, upload, cloud action, credential read, live Qwen call, or Devpost
  submission was performed during this audit.

### Local Verification

- Unit test suite: 585 tests passed in 96.929 seconds with the pinned local
  runtime, `TIKTOKEN_CACHE_DIR=/private/tmp/recallpack-tiktoken-cache`, and
  `PYTHONWARNINGS=always::ResourceWarning`.
- The regression includes the public-bundle exclusion for `.inspect.ndjson`,
  the presentation upload-state distinction, the review-packet delivery
  wording, and cleanup of fresh-clone server output pipes. No ResourceWarning
  was emitted by the workspace suite.
- Fresh-clone verification passed from
  `dist/recallpack-submission-20260720-231611/`: public surface, Python
  compilation, JavaScript syntax, full unit mode, localhost server smoke, and
  judge smoke all passed. The judge smoke confirmed that `/compile` includes
  the active decision and project preference while excluding the stale decision.
- Any bundle created after this report must repeat that same fresh-clone gate
  before an external action.
- The revised-deck bundle
  `dist/recallpack-submission-20260720-231611/` passed the full local readiness
  loop: public-surface checks, fresh-clone rehearsal, localhost smoke, and
  judge smoke all passed. The PPT remains built and privacy-checked, not
  uploaded.
