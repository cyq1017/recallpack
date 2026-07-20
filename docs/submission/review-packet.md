# RecallPack Review Packet

## Positioning

RecallPack is a Qwen Cloud Hackathon MemoryAgent project for cross-session memory lifecycle and stale-aware coding-agent handoffs.

Core claim: RecallPack observes session events, writes durable memories, supersedes stale decisions, and compiles only active task-relevant memory into an estimated fixed-budget handoff pack.

Post-GPT Pro review status: M37 fixes the disconnected HTTP runtime path by making `POST /observe` and `POST /compile` share the same SQLite store, and fixes cross-session supersession by assigning project-scoped event sequence numbers. M38 replaces the HTTP demo event-id memory decider with a provider-backed fake memory decision path that emits the same sanitized `memory_decision` trace schema used by live Qwen adapters. M41 upgrades the local HTTP `/compile` path from zero-vector and identity-rerank smoke to deterministic keyword fake embedding/rerank providers under the same provider contract, while the evaluation remains local fixture evidence. M43 adds a gated live Qwen E2E observe/compile runner. M46 exposed the first live E2E failure, then M47/M64 hardened and preflighted the same provider path. M65 reran live Qwen E2E with approved credentials and records a sanitized `live_e2e_passed` trace for observe, compile, embedding, rerank, and downstream patch generation. The local demo remains credential-free and uses deterministic fake providers unless an explicit live run is approved. M45 adds a first-run handoff simulator so the first screen reads as a coding-agent handoff product moment, not only an evidence dashboard. M71 adds a one-click stale-memory failure replay on the first screen; it reuses the existing downstream temp-repo patch/test evidence and does not add a new live-Qwen claim.

M74 external-review remediation adds explicit truthfulness labels after adversarial review: local downstream proof uses a local deterministic context-keyed patch provider; the local raw-history baseline uses a keyword-scored fake-embedding baseline; the micro-suite is a behavior contract fixture suite; and the Qwen section displays a Stored Live Qwen Trace from a checked-in sanitized one-run trace rather than making live calls.

M75 reconciles current shipped Qwen model evidence: the current live E2E trace is the primary current-model evidence, while the legacy standalone live smoke is preserved only as a historical contract smoke. M76 adds a real text-embedding-v4 raw-history baseline preflight so the next approved live run can test the baseline with Qwen embeddings instead of only the local keyword fake embedding.

M98 responds to adversarial review by changing the gated live E2E contract: the live runner now derives the raw-history baseline from embedding top-N plus qwen3-rerank instead of hardcoding the stale context, and baseline failure is reported rather than used as a pass requirement. The fresh M98 live rerun is checked in as `live_e2e_failed`: lifecycle filtering held, but the downstream 3/3 delta did not reproduce. The stored `live_e2e_passed` trace demonstrates provider-path integration. The M98 rerun demonstrates that downstream live reproducibility remains an open empirical question.

M109 responds to first-principles adversarial review by moving the headline from local 1/3-vs-3/3 replay numbers to the structural write-time lifecycle claim. The stored live raw-history embedding+rerank baseline traces selected the active retry decision and did not reproduce the local stale-context failure, so the local replay is labeled as an authored deterministic failure-class illustration rather than live failure-rate evidence.

M114 adds a consent-first real trace intake kit for future evaluation hardening. It validates candidate traces for explicit consent, ordered events, secret-like values, and local filesystem paths, and the CLI can write a sanitized copy with `--sanitize` and `--sanitized-out`. This is not a production trace claim and not submission evidence until a trace is explicitly promoted after privacy review.

M117 adds the ProjectOdyssey JIT policy fixture as a source-backed synthetic stale-memory scenario. It uses an unrigged deterministic keyword-provider baseline without fixture-authored baseline embedding terms or downrank phrases; the raw-history baseline naturally selects the stale retry/skip policy and passes 1/3 hidden tests, while RecallPack selects the active fail-fast fix-forward policy plus the dependency preference and passes 3/3.

M118 resets the judge-facing opening surface: README, Devpost copy, the demo video opening, and first-screen UI labels now lead with the MemoryAgent product problem and ProjectOdyssey evidence rather than internal milestone labels. Detailed milestone history stays in internal execution docs and review appendices.

## Qwen Provider Integration Evidence

- text-embedding-v4 retrieves candidate memories.
- qwen3-rerank improves precision over embedding top-N.
- Qwen text model is used for memory extraction and supersession judgment in the gated/provider path.
- The current memory-decision adapter sends an OpenAI-compatible tools/tool_choice request and defaults to qwen3.7-plus-2026-05-26.
- The current live E2E trace is the primary current-model evidence.
- The legacy standalone live smoke is preserved only as a historical contract smoke and must not be presented as the current shipped model E2E proof.
- M43 adds a gated live Qwen E2E observe/compile runner.
- M47 hardens the memory-decision contract with structured event metadata, must-write policy, and descriptive tool schema.
- M64 extends the credential-free live E2E preflight to include downstream patch generation.
- M65 stores one sanitized live Qwen provider-path integration trace that completed successfully once; it is not statistical validation of live downstream performance.
- M75 reconciles current shipped Qwen model evidence.
- M76 adds a real text-embedding-v4 raw-history baseline preflight.
- M120 runs the ProjectOdyssey source-backed scenario through live Qwen observe, embedding, rerank, and patch-generation; the stored trace records a passing ProjectOdyssey live E2E while preserving the separate failed M98 rerun as non-passing evidence.
- M45 adds a first-run handoff simulator.
- live Qwen provider-path integration trace: live_e2e_passed.
- live Qwen E2E current-model trace: qwen3.7-plus-2026-05-26.
- live Qwen E2E selected_sources=['session-a:turn-005', 'session-a:turn-004', 'session-a:turn-003']; provider_trace_count=19; actual token usage memory=22297 embedding=108 rerank=205.
- live Qwen E2E one-run integration outcome: observe events completed, stale retry memory was excluded, active retry and project preference were selected, and the intended downstream patch path completed for RecallPack. This is not statistical validation of live downstream performance.
- live Qwen E2E note: `session-a:turn-004` is supporting retry-failure evidence from the tool result; the required active decision and preference remain `session-a:turn-005` and `session-a:turn-003`.
- live Qwen E2E one-run downstream result, not a headline metric: baseline 1/3; RecallPack 3/3; the fresh M98 rerun did not reproduce this downstream delta.
- fresh M98 live Qwen rerun status: live_e2e_failed.
- fresh M98 live Qwen rerun selected_sources=['session-a:turn-005', 'session-a:turn-003', 'session-a:turn-004'].
- fresh M98 live Qwen rerun downstream: baseline 2/3; RecallPack 2/3.
- fresh M98 live Qwen rerun is stored as failed evidence; do not claim the fresh M98 live rerun passed.
- live Qwen E2E preflight: generated without credentials or network calls.
- preflight_status: ready_for_live_e2e_rerun.
- network_calls_made=false.
- request_role_counts: memory_decision=12 embedding=16 rerank=2 patch_generation=2.
- preflight expected selected sources: ['session-a:turn-005', 'session-a:turn-003']; future live reruns remain gated.
- preflight memory-decision contract checks: structured_event_metadata=True, descriptive_tool_schema=True, tool_choice_function=True.
- ProjectOdyssey live Qwen E2E preflight: generated without credentials or network calls.
- preflight_status: ready_for_live_e2e_rerun.
- network_calls_made=false.
- request_role_counts: memory_decision=12 embedding=16 rerank=2 patch_generation=2.
- ProjectOdyssey preflight expected selected sources: ['session-h-current:turn-006', 'session-h-history:turn-004']; future live reruns remain gated.
- ProjectOdyssey preflight memory-decision contract checks: structured_event_metadata=True, descriptive_tool_schema=True, tool_choice_function=True.
- ProjectOdyssey live Qwen E2E run: live_e2e_passed.
- ProjectOdyssey live selected_sources=['session-h-current:turn-006', 'session-h-history:turn-004']; provider_trace_count=32; required_sources_selected=True; stale_sources_excluded=True.
- ProjectOdyssey live downstream result: baseline 1/3; RecallPack 3/3.
- ProjectOdyssey live token usage: memory=21722 embedding=727 rerank=474 patch_generation=1963.
- ProjectOdyssey live boundary: Qwen selected the active decision and dependency preference while excluding the stale policy, and the RecallPack live-generated patch passed 3/3 downstream fixture tests. The separate fresh M98 rerun remains failed, so this is source-backed fixture integration evidence, not a broad live benchmark claim.
- real embedding baseline preflight: ready_for_live_embedding_baseline_rerun.
- real embedding baseline request_role_counts: embedding=13 rerank=1.
- real embedding baseline expected selected_sources=['session-a:turn-001', 'session-a:turn-003']; expected downstream fixture tests 1/3.
- real embedding baseline checks: stale_retry_selected_by_real_embedding_path=True; active_retry_not_selected_by_baseline=True.
- real embedding baseline live run remains gated; preflight records provider contract shape without credentials or network calls.
- live raw-history embedding+rerank baseline traces: 2 stored runs; active retry selected in 2/2; stale retry selected in 0/2.
- live baseline disclosure: stored plain retrieval runs selected active retry memory and did not reproduce the local stale-baseline failure. Therefore local 1/3 versus 3/3 is an authored deterministic failure-class illustration, not live frequency evidence.
- live baseline trace summaries: live_embedding_baseline_failed: selected_sources=['session-a:turn-005', 'session-a:turn-007']; live_embedding_baseline_failed: selected_sources=['session-a:turn-005', 'session-a:turn-007'].
- Deterministic code handles event ordering, leases, budget selection, and pack assembly.

Qwen provider trace evidence:

- standalone live API smoke passed: yes, sanitized contract trace recorded
- actual Qwen token usage: memory=301 embedding=20 rerank=29
- memory_decision -> qwen-plus (extract_classify_and_judge_memory_lifecycle, live=True)
- embedding -> text-embedding-v4 (candidate_memory_retrieval_query, live=True)
- embedding -> text-embedding-v4 (candidate_memory_retrieval_document, live=True)
- rerank -> qwen3-rerank (precision_rerank_active_memory_candidates, live=True)
- /compile local retrieval: deterministic keyword fake embedding top-N + qwen3-rerank-shaped fake rerank
- /compile local HTTP path uses deterministic keyword fake embedding/rerank
- this is not zero-vector or identity-rerank smoke
- local fake-embedding top-N candidates are passed into fake rerank before budget selection
- local HTTP smoke uses fake providers unless a separate live Qwen contract run is explicitly approved
- M73 live Qwen trace explorer: checked-in sanitized live E2E trace is visible in `/api/demo` without rerunning Qwen.
- Stored Live Qwen Trace display mode: Stored Live Qwen Trace; source_kind=checked_in_sanitized_trace.
- trace_explorer status/source: live_e2e_passed from docs/submission/live-qwen-e2e-trace.json.
- role_summary covers: memory_decision, embedding, rerank, patch_generation.
- trace_explorer stages: observe_memory_decisions, compile_embedding_retrieval, compile_rerank, downstream_patch_generation.
- trace_explorer selected_sources=['session-a:turn-005', 'session-a:turn-004', 'session-a:turn-003']; excluded_sources_checked=['session-a:turn-001'].
- trace_explorer downstream summary: baseline 1/3; RecallPack 3/3.
- trace_explorer safety boundary: sanitized trace only=True; no credentials=True; prompts redacted=True; local demo makes no live Qwen calls=True.
- Stored Live Qwen Trace: checked-in sanitized one-run trace; the local demo makes no live Qwen calls.

## Evidence Boundary

Memory lifecycle proof first; Qwen evidence is provider-path integration evidence, not broad live downstream validation.

- Live Qwen:
  - provider-path integration evidence: lifecycle filtering held in stored live RecallPack runs
  - live raw-history embedding+rerank selected the active retry decision in stored baseline runs
  - downstream live delta is one pass and one failed rerun, not a headline metric
- Local Demo:
  - credential-free deterministic replay
  - authored local 1/3 vs 3/3 failure-class illustration
  - no live Qwen calls are made by the public demo runtime
- Behavior Contract:
  - eight curated lifecycle regression fixtures
  - tests stale-memory handling behaviors, not a broad benchmark
  - raw full history is reference-only and not budget-comparable

What we do not claim:

- broad coding benchmark improvement
- universal retrieval superiority
- guaranteed live Qwen downstream success
- replacement for agent reasoning

## Local Demo Surface

- GET /api/health exposes compact readiness: MemoryAgent track, live trace status, Qwen provider roles, curated fixture count, and local deterministic replay baseline 1/3 versus RecallPack 3/3.
- POST /observe is exposed by the demo backend and runs the existing ObserveRuntime over SQLite with provider-backed fake memory decisions, not event-id fixture mapping.
- POST /compile is exposed by the demo backend and reads the same runtime SQLite store used by POST /observe.
- Judge smoke verifies GET /, GET /api/demo first-screen story, first-run handoff simulator, Qwen provider roles, POST /observe, and POST /compile.
- Judge smoke now seeds the compile proof through POST /observe instead of relying on hidden fixture replay when RECALLPACK_SQLITE_PATH is configured.
- Judge smoke asserts POST /observe returns a sanitized memory_decision provider trace from the fake provider path.
- Judge smoke asserts POST /compile reports `local_provider_mode=deterministic_keyword_fake`.
- Learn view shows the ordered 12-event session.
- Learn view starts with a deterministic stale-memory failure replay: local stale context selected -> wrong retry patch -> fixture tests 1/3 -> active memory pack -> fixture tests 3/3.
- Learn view includes the first-run handoff simulator.
- Recall view compares raw full-history reference, keyword-scored fake-embedding + rerank raw-history baseline, and RecallPack.
- M74 local baseline wording: this local comparison uses a keyword-scored fake-embedding baseline over raw event text; `text-embedding-v4` evidence is reserved for the stored live E2E trace and provider contract.
- Evaluate view shows the 32-event behavior contract fixture suite.
- M74 micro-suite wording: behavior contract fixture suite, not a broad benchmark or live model evaluation.
- A sanitized local submission bundle excludes internal execution notes, generated caches, and machine-local paths.
- SUBMISSION_MANIFEST.md includes judge quick checks, local credential-free smoke commands, and the primary API surface.
- Public repo readiness: publish the sanitized bundle boundary; do not push the raw workspace.
- Docker runtime proof: passed.
- Latest Docker proof: M104 image from the prior verified sanitized bundle passed local judge smoke on 127.0.0.1.
- Docker image: recallpack-demo:cloud.
- Docker container binding: 127.0.0.1:8814->8789.
- Docker daemon blocker resolved by starting Docker Desktop.
- Current public ECS deployment: M104 credential-free runtime from the prior verified 7/4 sanitized bundle.
- Latest public ECS image tags: timestamped M104 local image and recallpack-demo:cloud.
- Public ECS judge smoke passed after the M104 redeploy; do not claim the latest 7/7 local bundle is deployed without another redeploy and judge smoke run.
- Fresh-clone rehearsal: passed.
- Fresh-clone public surface gate checks required public files and manifest judge quick checks before running server smoke.
- Static demo parity gate compares web/demo-data.js with the current fixture-backed demo payload, allowing only dynamic memory IDs to differ.
- Full fresh-clone rehearsal: available with --full; it runs full unittest discovery in the temp copy with recursive smoke tests skipped.
- Public repo root self-smoke command: PYTHONPATH=src python3 tools/fresh_clone_smoke.py --source .
- Fresh-clone command: PYTHONPATH=src python3 tools/fresh_clone_smoke.py --source "$bundle_target".
- Raw full-history reference selected 12 events and is marked not budget-comparable.
- Keyword-scored fake-embedding + rerank raw-history baseline is computed from raw event text and reranked before top-k selection, not from fixture-selected source IDs. Its deterministic local scoring terms are still fixture-authored, so treat it as demo replay evidence rather than an independent embedding evaluation.
- M63 downstream proof generates patches through a local deterministic context-keyed patch provider from goal plus selected context and allowed edit paths; it does not read gold patch_variants.
- M74 local downstream wording: local deterministic context-keyed patch provider; live Qwen patch generation is evidenced only by the stored sanitized E2E trace.
- The same deterministic context-keyed local patch provider is used for the raw-history baseline and RecallPack before executing fixture tests against a temp repo.
- First-screen story: keyword-scored fake-embedding + rerank raw-history handoff fails 1/3
- RecallPack active memory handoff passes 3/3
- First-run handoff simulator: baseline 1/3, RecallPack 3/3
- Deterministic handoff replay: local baseline context includes session-a:turn-001, RecallPack active pack includes session-a:turn-005 and session-a:turn-003.
- M73 live Qwen trace explorer: `/api/demo` exposes `qwen_load_bearing.trace_explorer` with `role_summary`, stage flow, selected/excluded sources, and safety boundary.
- M73 live Qwen trace explorer safety: sanitized trace only; local demo makes no live Qwen calls.
- first-screen retrieval path: embedding top-N -> qwen3-rerank -> estimated 512-token serialized-memory budget selector
- M72 current screenshot gallery: non-destructive M71 replay screenshots generated under docs/submission/media/m71-replay/.
- M72 screenshot assets: 01-one-click-stale-memory-replay.png, 02-recallpack-active-memory-pack.png, and 03-qwen-provider-evidence.png.
- recorded Qwen trace status: standalone live API smoke passed (stored status value: live_contract_passed)
- Quality hardening audit: local P0/P1 wording and evidence risks reviewed.
- M109 positioning remediation: local 1/3 vs 3/3 is an authored deterministic replay, while stored live evidence supports lifecycle filtering rather than a live baseline failure-rate claim.
- Skeptical judge Q&A: docs/submission/skeptical-judge-qa.md maps claim-to-evidence links, bounded limits, and review commands.
- Eight curated lifecycle fixtures: retry, config, cache, serializer, pagination, realistic API-client auth, source-backed provider-auth, and source-backed ProjectOdyssey JIT scenario fixtures all show stale baseline failure and RecallPack success across 8 local fixtures.
- Remaining credibility note: eight local fixtures, including one non-isomorphic multi-session pagination fixture, one realistic repo-style API-client fixture, one source-backed provider-auth fixture, and one source-backed ProjectOdyssey JIT scenario with an unrigged keyword-provider baseline, are stronger than a single hero fixture, but still not a broad benchmark.
- Real trace boundary: a consent-first real trace intake kit exists for future sanitized traces; it is not a production trace claim and no candidate trace is promoted to submission evidence by default. Raw local candidates must go through `tools/validate_real_trace_intake.py --sanitize` before review.

## M50 external benchmark and winner polish

- Internal M50 external benchmark notes record judging signals and reference patterns for the team, but internal research/audit notes are excluded from the sanitized public bundle.
- docs/submission/demo-video-script.md provides a 2:20-2:45 demo script that opens with a deterministic local stale-context replay failing 1/3 fixture tests and RecallPack active memory passing 3/3 fixture tests.
- Devpost Discussions and Qwen Cloud Discord are the current official community monitoring channels.
- Project gallery is not yet published, so M50 records reference patterns without claiming direct competitor analysis.
- One checked-in approved live Qwen E2E trace records live_e2e_passed; the fresh M98 rerun is checked in as live_e2e_failed and must not be presented as passing.
- Skills and prior-art projects are recorded as references only; they are not installed or copied by default.
- M51 architecture diagram: docs/submission/architecture-diagram.md.
- Architecture summary: Browser demo -> Python demo backend -> SQLite event and memory store.
- Qwen model summary: Qwen text model -> text-embedding-v4 -> qwen3-rerank.
- M53 demo media package: docs/submission/demo-media-package.md.
- M53 recording target 2:20-2:45; first frame should show the deterministic stale-memory failure replay with local baseline 1/3 and RecallPack 3/3.
- A local MP4 demo video candidate is checked in under docs/submission/media/video-candidate/, but no Devpost video URL or upload is recorded.
- A six-slide presentation deck is built at docs/submission/media/recallpack-judge-deck.pptx, but it is a built-but-not-uploaded presentation PPT and remains a manual Devpost gate.
- M54 public release gate: docs/submission/public-release-gate.md.
- M54 publish rule: publish the sanitized bundle, not the raw workspace.
- M54/M102 public repository boundary: the repository URL is recorded at https://github.com/cyq1017/recallpack; local preflight validates the sanitized bundle but does not prove remote synchronization. Devpost submission, image push, any future ECS replacement, and any further live Qwen rerun remain gated; approval-only actions remain blocked until the user performs or explicitly re-approves each external submission step.
- M55 local screenshot gallery: generated 1280x720 Devpost candidates under docs/submission/media/.
- M55 screenshot assets: 01-first-run-handoff-simulator.png, 02-recallpack-active-memory-pack.png, and 03-qwen-provider-evidence.png.
- M72 current screenshot gallery: generated 1280x720 M71 replay candidates under docs/submission/media/m71-replay/.
- M56 reproducible screenshot capture: tools/capture_demo_screenshots.py can list or regenerate the local Devpost screenshot gallery without live Qwen or media upload; capture mode accepts only local demo URLs.
- M57 Devpost preflight: tools/devpost_preflight.py reports local material readiness and manual gated actions as JSON without credentials, network calls, media upload, public repo creation, or Devpost submission.
- Current M57 preflight status should be blocked_gated_actions: local materials and public repo URL are ready, but required Devpost architecture/Alibaba Cloud proof file upload, the built-but-not-uploaded presentation PPT, final video URL/upload, final media order confirmation, and final Devpost approval remain manual gates.
- M58 Devpost materials export: tools/export_devpost_materials.py turns the checked-in Devpost copy, hackathon fields, media assets, verification evidence, and M57 blockers into local JSON/Markdown for manual copy/paste without credentials, network calls, upload, public repo creation, or submission.
- M59 submission evidence index: tools/export_evidence_index.py maps MemoryAgent positioning, downstream stale handoff proof, Qwen provider integration, live Qwen E2E boundary, public repo boundary, and Devpost media readiness to evidence files, commands, risk levels, and gated boundaries.
- M60 final submission gate: tools/final_submission_gate.py aggregates Devpost preflight, evidence index, public bundle scan, and full fresh-clone rehearsal into one local JSON report while recording the published public repo URL and leaving media upload and Devpost submission gated.
- M61 public repo preflight: tools/public_repo_preflight.py checks the sanitized publish surface, MIT license, README judge entry, submission manifest, forbidden paths, bundle scan, and judge commands before or after public GitHub repository creation.
- M107 submission readiness loop: tools/submission_readiness_loop.py aggregates Devpost preflight, video rehearsal, public repo preflight, and optional full final submission gate into one local-only JSON loop without push, deploy, upload, submit, credential reads, or live Qwen calls.
- M66 winner narrative polish: docs/submission/demo-video-script.md opens with stale project memory causing a wrong patch, docs/submission/demo-media-package.md adds 15/45/90 second recording gates, docs/submission/skeptical-judge-qa.md adds recording-day answers, and docs/submission/blog-post-draft.md prepares the Blog Post Award narrative.
- M67 final judge rehearsal / M85 deadline runway / M99/M102 wording refresh: docs/submission/final-judge-rehearsal.md tracks the latest local package, the M98 evidence snapshot, the M104 public ECS runtime boundary, final judge commands, manual gates, and claim guardrails before public repo or Devpost work. M85 is internal deadline runway control and does not add a new judge-facing product claim.
- M68 video production packet: docs/submission/video-production-packet.md turns the script into a recording-day run of show with retake triggers, on-screen no-go items, upload package, and final self-check.
- M69 recording rehearsal gate / M86 recording release-candidate sync: tools/video_rehearsal_gate.py checks the recording packet, screenshots, manual upload gates, public ECS wording, and latest local bundle reference before recording; docs/submission/recording-rehearsal-report.md stores the latest local-only report. M102 keeps the packet aligned with the M104 public ECS boundary while preserving M98 as the current evidence snapshot.
- M98 adversarial review remediation: the local evidence remains green, but the current winner-grade audit now treats a fresh live Qwen sweep/rerun for the unrigged baseline path as the remaining P0 prize-credibility gate.
- M99 current-package wording sync: README, final judge rehearsal, video production packet, recording gate, and public repo readiness now use version-neutral latest local package wording while preserving M98 as the current evidence snapshot and M102 as the public ECS boundary.
- M92/M99 submission media copy consistency gate: recording and submission copy now keep the latest local package, M98 evidence snapshot, and M104 public ECS runtime boundaries aligned; public ECS judge smoke is scoped to the M104 deployment.
- M93 judge first-run command contract: SUBMISSION_MANIFEST.md, public repo preflight, README, and review packet copy-ready commands now share the same JUDGE_FIRST_RUN_COMMANDS list so judge setup instructions do not drift across public surfaces.
- M94 public release gate command contract: the manual public release gate now includes every command from JUDGE_FIRST_RUN_COMMANDS, including the video rehearsal gate, so the last pre-publication checklist matches the judge quickstart.
- M106 current-day release readiness refresh: local readiness, public repo readiness, and the internal deadline runway now use 2026-07-07 with about 2 days 18 hours 17 minutes remaining; this is date/readiness maintenance, not a new product claim.
- M96 current-package wording guardrail: judge-facing recording, review, public-repo, and generated packet surfaces now use version-neutral latest local package wording instead of calling M90 the current package.
- M97 source-to-bundle parity preflight: raw-workspace public repo preflight now compares all public-bundle source files with the latest sanitized bundle and fails if docs or code changed after the bundle was built.
- Next polish slices: manual video recording/upload, optional broader benchmark fixtures, and Devpost submission after explicit approval.

## Evidence Snapshot

- 32-event behavior contract fixture suite positioning: RecallPack micro-suite is a hackathon evidence suite, not a broad benchmark.
- micro-suite prediction source: behavioral_runtime behavior contract fixture evaluator
- deprecated fixture prediction fields are ignored by regression tests
- behavior-contract runtime counts, not model-quality metrics: TP=20 FP=0 FN=0 TN=12
- behavior-contract supersession edges, oracle-backed runtime check: 10/10 correct
- behavior-contract edge F1: 1.0
- behavior-contract memory type accuracy: 1.0
- runtime pack-selection contract, not live model recall metric: required memory recall at estimated 512 is 1.0
- stale selected items: 0
- baseline source-recall score: 0/3
- RecallPack fixture tests: 3/3
- baseline downstream fixture tests: 1/3
- RecallPack downstream fixture tests: 3/3
- keyword-scored fake-embedding + rerank raw-history baseline stale context produces a wrong retry patch; RecallPack active memory produces the passing retry patch
- Eight curated lifecycle fixture details:
  - project-a retry: baseline 1/3, RecallPack 3/3, baseline sources session-a:turn-008, session-a:turn-001, RecallPack sources session-a:turn-005, session-a:turn-003
  - project-b config: baseline 1/3, RecallPack 3/3, baseline sources session-b:turn-001, session-b:turn-002, RecallPack sources session-b:turn-005, session-b:turn-003
  - project-c cache: baseline 0/3, RecallPack 3/3, baseline sources session-c:turn-001, session-c:turn-002, RecallPack sources session-c:turn-005, session-c:turn-003
  - project-c cache: baseline rejection=empty_patch; causal reason=patch rejected by downstream path validator: empty_patch
  - project-d serializer: baseline 0/3, RecallPack 3/3, baseline sources session-d:turn-008, session-d:turn-001, RecallPack sources session-d:turn-005, session-d:turn-003
  - project-d serializer: baseline rejection=empty_patch; causal reason=patch rejected by downstream path validator: empty_patch
  - project-e pagination: baseline 0/3, RecallPack 3/3, baseline sources session-e-alpha:note-002, session-e-beta:pref-003, RecallPack sources session-e-gamma:decision-001, session-e-beta:pref-002
  - project-e pagination: baseline rejection=empty_patch; causal reason=patch rejected by downstream path validator: empty_patch
  - project-f-realistic api_client: baseline 1/3, RecallPack 3/3, baseline sources session-f-setup:turn-002, session-f-setup:turn-004, RecallPack sources session-f-fix:turn-006, session-f-setup:turn-004
  - project-g-auth-mode provider_auth: baseline 1/3, RecallPack 3/3, baseline sources session-g-alpha:turn-002, session-g-alpha:turn-001, RecallPack sources session-g-alpha:turn-004, session-g-fix:turn-006
  - project-h-projectodyssey-jit ci_policy: baseline 1/3, RecallPack 3/3, baseline sources session-h-current:turn-004, session-h-history:turn-002, RecallPack sources session-h-current:turn-006, session-h-history:turn-004

## Copy-Ready Commands

```bash
PYTHONPATH=src python3 tools/build_demo_data.py
PYTHONPATH=src python3 tools/build_live_qwen_e2e_preflight.py
PYTHONPATH=src python3 tools/build_live_qwen_embedding_baseline_preflight.py
PYTHONPATH=src python3 tools/build_review_packet.py
python3 tools/capture_demo_screenshots.py --list
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install -r requirements-v4.txt
PYTHONPATH=src python3 tools/fresh_clone_smoke.py --source .
PYTHONPATH=src python3 tools/fresh_clone_smoke.py --source . --full
PYTHONPATH=src python3 -m unittest discover -s tests -v
node --check web/app.js
python3 tools/devpost_preflight.py
python3 tools/export_devpost_materials.py
python3 tools/export_evidence_index.py
python3 tools/video_rehearsal_gate.py
python3 tools/final_submission_gate.py
python3 tools/public_repo_preflight.py
python3 tools/submission_readiness_loop.py --full
bundle_target="dist/recallpack-submission-$(date +%Y%m%d-%H%M%S)"
PYTHONPATH=src python3 tools/build_submission_bundle.py --target "$bundle_target"
PYTHONPATH=src python3 tools/fresh_clone_smoke.py --source "$bundle_target"
PYTHONPATH=src python3 tools/fresh_clone_smoke.py --source "$bundle_target" --full
PYTHONPATH=src python3 -m recallpack.demo_server --host 127.0.0.1 --port 8789
python3 tools/judge_smoke.py --url http://127.0.0.1:8789
curl http://127.0.0.1:8789/api/health
curl http://127.0.0.1:8789/api/demo
curl -X POST http://127.0.0.1:8789/observe \
  -H 'content-type: application/json' \
  -d '{"project_id":"project-a","session_id":"session-a","event_id":"turn-001","sequence_no":1,"actor":"user","kind":"message","observed_at":"2026-06-24T00:00:00Z","text":"Use three attempts with a fixed 100 ms delay in the retry helper."}'
curl -X POST http://127.0.0.1:8789/compile \
  -H 'content-type: application/json' \
  -d '{"project_id":"project-a","goal":"Update the retry helper to the current project policy.","component":"retry","budget_tokens":512}'
```

## Safety Boundary

This packet does not create cloud resources by itself. An approved Alibaba Cloud ECS deployment is available at http://101.133.224.223/ and passed judge smoke.
Live Qwen contract was run once with explicit approval; this packet stores only sanitized trace records.
No credentials, raw prompts, raw memory text, image push, public endpoint, or hackathon submission action is included.

## Reviewer Focus

- Does the demo prove memory lifecycle rather than generic RAG?
- Does Qwen provider integration evidence cover retrieval, rerank, and memory-operation judgment?
- Is the curated deterministic baseline comparison labeled honestly?
- Are the remaining live/deployment gates explicit?
