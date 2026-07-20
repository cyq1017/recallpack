from __future__ import annotations

import json
from pathlib import Path

from recallpack.demo import build_demo_payload, discover_secondary_hero_fixture_roots
from recallpack.submission_bundle import JUDGE_FIRST_RUN_COMMANDS


def build_review_packet(
    project_root: str | Path,
    live_qwen_trace_path: str | Path | None = None,
    live_qwen_e2e_trace_path: str | Path | None = None,
    fresh_m98_live_rerun_trace_path: str | Path | None = None,
) -> str:
    root = Path(project_root)
    if live_qwen_trace_path is None:
        default_live_trace_path = (
            root / "docs" / "submission" / "live-qwen-trace.json"
        )
        live_qwen_trace_path = (
            default_live_trace_path if default_live_trace_path.is_file() else None
        )
    if live_qwen_e2e_trace_path is None:
        default_live_e2e_trace_path = (
            root / "docs" / "submission" / "live-qwen-e2e-trace.json"
        )
        live_qwen_e2e_trace_path = (
            default_live_e2e_trace_path
            if default_live_e2e_trace_path.is_file()
            else None
        )
    fresh_m98_trace_path = (
        Path(fresh_m98_live_rerun_trace_path)
        if fresh_m98_live_rerun_trace_path is not None
        else root / "docs" / "submission" / "live-qwen-m98-rerun-trace.json"
    )
    payload = build_demo_payload(
        root / "fixtures" / "project-a",
        root / "fixtures" / "micro-suite",
        live_qwen_trace_path=live_qwen_trace_path,
        live_qwen_e2e_trace_path=live_qwen_e2e_trace_path,
        fresh_m98_live_rerun_trace_path=(
            fresh_m98_trace_path if fresh_m98_trace_path.is_file() else None
        ),
        secondary_fixture_roots=discover_secondary_hero_fixture_roots(root),
    )
    suite = payload["evaluate"]["micro_suite"]
    recall_variants = {variant["id"]: variant for variant in payload["recall"]["variants"]}
    recallpack = recall_variants["recallpack"]
    baseline = recall_variants["embedding_top_k_rag"]
    raw_full_history = recall_variants["raw_full_history"]
    counts = suite["raw_counts"]
    edge_counts = suite["edge_counts"]
    metrics = suite["metrics"]
    evidence = suite["prediction_evidence"]
    baseline_downstream = baseline["downstream"]
    recallpack_downstream = recallpack["downstream"]
    qwen = payload["qwen_load_bearing"]
    boundary = payload["evidence_boundary"]
    story = payload["hero_story"]
    simulator = payload["handoff_simulator"]
    generalization = payload["evaluate"]["generalization_fixtures"]
    generalization_fixtures = list(generalization["fixtures"])
    traces = qwen["provider_traces"]
    usage = qwen.get("actual_qwen_token_usage", {})
    live_e2e = _load_live_e2e_trace(root / "docs" / "submission" / "live-qwen-e2e-trace.json")
    fresh_m98_live_rerun = _load_live_e2e_trace(fresh_m98_trace_path)
    live_e2e_preflight = _load_live_e2e_preflight(
        root / "docs" / "submission" / "live-qwen-e2e-preflight.json"
    )
    projectodyssey_live_e2e_preflight = _load_live_e2e_preflight(
        root / "docs" / "submission" / "projectodyssey-live-qwen-e2e-preflight.json"
    )
    projectodyssey_live_e2e = _load_live_e2e_trace(
        root / "docs" / "submission" / "projectodyssey-live-qwen-e2e-trace.json"
    )
    live_embedding_baseline_preflight = _load_live_e2e_preflight(
        root / "docs" / "submission" / "live-qwen-embedding-baseline-preflight.json"
    )
    live_embedding_baseline_traces = [
        trace
        for trace in (
            _load_live_e2e_trace(
                root / "docs" / "submission" / "live-qwen-embedding-baseline-trace.json"
            ),
            _load_live_e2e_trace(
                root
                / "docs"
                / "submission"
                / "live-qwen-m98-embedding-baseline-trace.json"
            ),
        )
        if trace is not None
    ]
    trace_lines = [
        (
            f"- {trace['provider_role']} -> {trace['model_name']} "
            f"({trace['request_purpose']}, live={trace['is_live']})"
        )
        for trace in traces
    ]
    live_trace_lines = _qwen_live_trace_lines(qwen, usage)
    live_e2e_lines = _qwen_live_e2e_lines(live_e2e)
    fresh_m98_live_rerun_lines = _qwen_fresh_m98_live_rerun_lines(
        fresh_m98_live_rerun
    )
    live_e2e_preflight_lines = _qwen_live_e2e_preflight_lines(live_e2e_preflight)
    projectodyssey_live_e2e_preflight_lines = _qwen_live_e2e_preflight_lines(
        projectodyssey_live_e2e_preflight,
        label="ProjectOdyssey live Qwen E2E preflight",
        selected_prefix="ProjectOdyssey preflight",
    )
    projectodyssey_live_e2e_lines = _qwen_projectodyssey_live_e2e_lines(
        projectodyssey_live_e2e
    )
    live_embedding_baseline_preflight_lines = (
        _qwen_live_embedding_baseline_preflight_lines(
            live_embedding_baseline_preflight
        )
    )
    trace_explorer_lines = _qwen_trace_explorer_lines(qwen)
    safety_lines = _safety_boundary_lines(qwen)
    return "\n".join(
        [
            "# RecallPack Review Packet",
            "",
            "## Positioning",
            "",
            (
                "RecallPack is a Qwen Cloud Hackathon MemoryAgent project for "
                "cross-session memory lifecycle and stale-aware coding-agent "
                "handoffs."
            ),
            "",
            "Core claim: RecallPack observes session events, writes durable memories, "
            "supersedes stale decisions, and compiles only active task-relevant "
            "memory into an estimated fixed-budget handoff pack.",
            "",
            "Post-GPT Pro review status: M37 fixes the disconnected HTTP runtime "
            "path by making `POST /observe` and `POST /compile` share the same "
            "SQLite store, and fixes cross-session supersession by assigning "
            "project-scoped event sequence numbers. M38 replaces the HTTP demo "
            "event-id memory decider with a provider-backed fake memory "
            "decision path that emits the same sanitized `memory_decision` trace "
            "schema used by live Qwen adapters. M41 upgrades the local HTTP "
            "`/compile` path from zero-vector and identity-rerank smoke to "
            "deterministic keyword fake embedding/rerank providers under the "
            "same provider contract, while the evaluation remains local fixture "
            "evidence. M43 adds a gated live Qwen E2E observe/compile runner. "
            "M46 exposed the first live E2E failure, then M47/M64 hardened and "
            "preflighted the same provider path. M65 reran live Qwen E2E with "
            "approved credentials and records a sanitized `live_e2e_passed` "
            "trace for observe, compile, embedding, rerank, and downstream "
            "patch generation. The local demo remains credential-free and uses "
            "deterministic fake providers unless an explicit live run is "
            "approved. M45 adds a first-run handoff simulator so the first "
            "screen reads as a coding-agent handoff product moment, not only "
            "an evidence dashboard. M71 adds a one-click stale-memory failure "
            "replay on the first screen; it reuses the existing downstream "
            "temp-repo patch/test evidence and does not add a new live-Qwen "
            "claim.",
            "",
            "M74 external-review remediation adds explicit truthfulness labels "
            "after adversarial review: local downstream proof uses a local "
            "deterministic context-keyed patch provider; the local raw-history "
            "baseline uses a keyword-scored fake-embedding baseline; the "
            "micro-suite is a behavior contract fixture suite; and the Qwen "
            "section displays a Stored Live Qwen Trace from a checked-in "
            "sanitized one-run trace rather than making live calls.",
            "",
            "M75 reconciles current shipped Qwen model evidence: the current "
            "live E2E trace is the primary current-model evidence, while the "
            "legacy standalone live smoke is preserved only as a historical "
            "contract smoke. M76 adds a real text-embedding-v4 raw-history "
            "baseline preflight so the next approved live run can test the "
            "baseline with Qwen embeddings instead of only the local keyword "
            "fake embedding.",
            "",
            "M98 responds to adversarial review by changing the gated live E2E "
            "contract: the live runner now derives the raw-history baseline "
            "from embedding top-N plus qwen3-rerank instead of hardcoding the "
            "stale context, and baseline failure is reported rather than used "
            "as a pass requirement. The fresh M98 live rerun is checked in as "
            "`live_e2e_failed`: lifecycle filtering held, but the downstream "
            "3/3 delta did not reproduce. The stored `live_e2e_passed` trace "
            "demonstrates provider-path integration. The M98 rerun demonstrates "
            "that downstream live reproducibility remains an open empirical "
            "question.",
            "",
            "M109 responds to first-principles adversarial review by moving the "
            "headline from local 1/3-vs-3/3 replay numbers to the structural "
            "write-time lifecycle claim. The stored live raw-history "
            "embedding+rerank baseline traces selected the active retry decision "
            "and did not reproduce the local stale-context failure, so the local "
            "replay is labeled as an authored deterministic failure-class "
            "illustration rather than live failure-rate evidence.",
            "",
            "M114 adds a consent-first real trace intake kit for future "
            "evaluation hardening. It validates candidate traces for explicit "
            "consent, ordered events, secret-like values, and local filesystem "
            "paths, and the CLI can write a sanitized copy with `--sanitize` "
            "and `--sanitized-out`. This is not a production trace claim and "
            "not submission evidence until a trace is explicitly promoted after "
            "privacy review.",
            "",
            "M117 adds the ProjectOdyssey JIT policy fixture as a source-backed "
            "synthetic stale-memory scenario. It uses an unrigged deterministic "
            "keyword-provider baseline without fixture-authored baseline "
            "embedding terms or downrank phrases; the raw-history baseline "
            "naturally selects the stale retry/skip policy and passes 1/3 "
            "hidden tests, while RecallPack selects the active fail-fast "
            "fix-forward policy plus the dependency preference and passes 3/3.",
            "",
            "M118 resets the judge-facing opening surface: README, Devpost copy, "
            "the demo video opening, and first-screen UI labels now lead with "
            "the MemoryAgent product problem and ProjectOdyssey evidence rather "
            "than internal milestone labels. Detailed milestone history stays in "
            "internal execution docs and review appendices.",
            "",
            "## Qwen Provider Integration Evidence",
            "",
            "- text-embedding-v4 retrieves candidate memories.",
            "- qwen3-rerank improves precision over embedding top-N.",
            "- Qwen text model is used for memory extraction and supersession "
            "judgment in the gated/provider path.",
            "- The current memory-decision adapter sends an OpenAI-compatible "
            "tools/tool_choice request and defaults to qwen3.7-plus-2026-05-26.",
            "- The current live E2E trace is the primary current-model evidence.",
            "- The legacy standalone live smoke is preserved only as a historical "
            "contract smoke and must not be presented as the current shipped "
            "model E2E proof.",
            "- M43 adds a gated live Qwen E2E observe/compile runner.",
            "- M47 hardens the memory-decision contract with structured event "
            "metadata, must-write policy, and descriptive tool schema.",
            "- M64 extends the credential-free live E2E preflight to include "
            "downstream patch generation.",
            "- M65 stores one sanitized live Qwen provider-path integration "
            "trace that completed successfully once; it is not statistical "
            "validation of live downstream performance.",
            "- M75 reconciles current shipped Qwen model evidence.",
            "- M76 adds a real text-embedding-v4 raw-history baseline preflight.",
            "- M120 runs the ProjectOdyssey source-backed scenario through live "
            "Qwen observe, embedding, rerank, and patch-generation; the stored "
            "trace records a passing ProjectOdyssey live E2E while preserving "
            "the separate failed M98 rerun as non-passing evidence.",
            "- M45 adds a first-run handoff simulator.",
            *live_e2e_lines,
            *fresh_m98_live_rerun_lines,
            *live_e2e_preflight_lines,
            *projectodyssey_live_e2e_preflight_lines,
            *projectodyssey_live_e2e_lines,
            *live_embedding_baseline_preflight_lines,
            *_qwen_live_embedding_baseline_trace_lines(live_embedding_baseline_traces),
            "- Deterministic code handles event ordering, leases, budget selection, "
            "and pack assembly.",
            "",
            "Qwen provider trace evidence:",
            "",
            *live_trace_lines,
            *trace_lines,
            "- /compile local retrieval: deterministic keyword fake embedding top-N + qwen3-rerank-shaped fake rerank",
            "- /compile local HTTP path uses deterministic keyword fake embedding/rerank",
            "- this is not zero-vector or identity-rerank smoke",
            "- local fake-embedding top-N candidates are passed into fake rerank before budget selection",
            "- local HTTP smoke uses fake providers unless a separate live Qwen "
            "contract run is explicitly approved",
            *trace_explorer_lines,
            "- Stored Live Qwen Trace: checked-in sanitized one-run trace; "
            "the local demo makes no live Qwen calls.",
            "",
            "## Evidence Boundary",
            "",
            f"{boundary['summary']}",
            "",
            *_evidence_boundary_lines(boundary),
            "",
            "What we do not claim:",
            "",
            *[f"- {item}" for item in boundary["do_not_claim"]],
            "",
            "## Local Demo Surface",
            "",
            "- GET /api/health exposes compact readiness: MemoryAgent track, "
            "live trace status, Qwen provider roles, curated fixture count, "
            "and local deterministic replay baseline 1/3 versus RecallPack 3/3.",
            "- POST /observe is exposed by the demo backend and runs the "
            "existing ObserveRuntime over SQLite with provider-backed fake "
            "memory decisions, not event-id fixture mapping.",
            "- POST /compile is exposed by the demo backend and reads the same "
            "runtime SQLite store used by POST /observe.",
            "- Judge smoke verifies GET /, GET /api/demo first-screen story, "
            "first-run handoff simulator, Qwen provider roles, POST /observe, "
            "and POST /compile.",
            "- Judge smoke now seeds the compile proof through POST /observe "
            "instead of relying on hidden fixture replay when "
            "RECALLPACK_SQLITE_PATH is configured.",
            "- Judge smoke asserts POST /observe returns a sanitized "
            "memory_decision provider trace from the fake provider path.",
            "- Judge smoke asserts POST /compile reports "
            "`local_provider_mode=deterministic_keyword_fake`.",
            "- Learn view shows the ordered 12-event session.",
            "- Learn view starts with a deterministic stale-memory failure replay: "
            "local stale context selected -> wrong retry patch -> fixture tests "
            "1/3 -> active memory pack -> fixture tests 3/3.",
            "- Learn view includes the first-run handoff simulator.",
            "- Recall view compares raw full-history reference, keyword-scored "
            "fake-embedding + rerank raw-history baseline, and RecallPack.",
            "- M74 local baseline wording: this local comparison uses a "
            "keyword-scored fake-embedding baseline over raw event text; "
            "`text-embedding-v4` evidence is reserved for the stored live E2E "
            "trace and provider contract.",
            "- Evaluate view shows the 32-event behavior contract fixture suite.",
            "- M74 micro-suite wording: behavior contract fixture suite, not a "
            "broad benchmark or live model evaluation.",
            "- A sanitized local submission bundle excludes internal execution "
            "notes, generated caches, and machine-local paths.",
            "- SUBMISSION_MANIFEST.md includes judge quick checks, local "
            "credential-free smoke commands, and the primary API surface.",
            "- Public repo readiness: publish the sanitized bundle boundary; "
            "do not push the raw workspace.",
            "- Docker runtime proof: passed.",
            "- Latest Docker proof: M104 image from the prior verified "
            "sanitized bundle passed local judge smoke on 127.0.0.1.",
            "- Docker image: recallpack-demo:cloud.",
            "- Docker container binding: 127.0.0.1:8814->8789.",
            "- Docker daemon blocker resolved by starting Docker Desktop.",
            "- Current public ECS deployment: M104 credential-free runtime from "
            "the prior verified 7/4 sanitized bundle.",
            "- Latest public ECS image tags: "
            "timestamped M104 local image and recallpack-demo:cloud.",
            "- Public ECS judge smoke passed after the M104 redeploy; do not "
            "claim the latest 7/7 local bundle is deployed without another "
            "redeploy and judge smoke run.",
            "- Fresh-clone rehearsal: passed.",
            "- Fresh-clone public surface gate checks required public files and "
            "manifest judge quick checks before running server smoke.",
            "- Static demo parity gate compares web/demo-data.js with the "
            "current fixture-backed demo payload, allowing only dynamic memory "
            "IDs to differ.",
            "- Full fresh-clone rehearsal: available with --full; it runs full "
            "unittest discovery in the temp copy with recursive smoke tests "
            "skipped.",
            "- Public repo root self-smoke command: PYTHONPATH=src python3 "
            "tools/fresh_clone_smoke.py --source .",
            "- Fresh-clone command: PYTHONPATH=src python3 "
            'tools/fresh_clone_smoke.py --source "$bundle_target".',
            (
                "- Raw full-history reference selected "
                f"{len(raw_full_history['selected_context'])} events and is marked "
                "not budget-comparable."
            ),
            "- Keyword-scored fake-embedding + rerank raw-history baseline is "
            "computed from raw event text and reranked before top-k selection, "
            "not from fixture-selected source IDs. Its deterministic local "
            "scoring terms are still fixture-authored, so treat it as demo "
            "replay evidence rather than an independent embedding evaluation.",
            "- M63 downstream proof generates patches through a local "
            "deterministic context-keyed patch provider from goal plus selected "
            "context and allowed edit paths; it does not read gold "
            "patch_variants.",
            "- M74 local downstream wording: local deterministic context-keyed "
            "patch provider; live Qwen patch generation is evidenced only by "
            "the stored sanitized E2E trace.",
            "- The same deterministic context-keyed local patch provider is used "
            "for the raw-history baseline and RecallPack before executing fixture "
            "tests against a temp repo.",
            (
                "- First-screen story: keyword-scored fake-embedding + rerank "
                "raw-history "
                "handoff fails "
                f"{story['baseline']['test_summary']['passed']}/"
                f"{story['baseline']['test_summary']['total']}"
            ),
            (
                "- RecallPack active memory handoff passes "
                f"{story['recallpack']['test_summary']['passed']}/"
                f"{story['recallpack']['test_summary']['total']}"
            ),
            (
                "- First-run handoff simulator: baseline "
                f"{simulator['baseline']['hidden_tests']}, RecallPack "
                f"{simulator['recallpack']['hidden_tests']}"
            ),
            "- Deterministic handoff replay: local baseline context includes "
            "session-a:turn-001, RecallPack active pack includes "
            "session-a:turn-005 and session-a:turn-003.",
            "- M73 live Qwen trace explorer: `/api/demo` exposes "
            "`qwen_load_bearing.trace_explorer` with `role_summary`, stage "
            "flow, selected/excluded sources, and safety boundary.",
            "- M73 live Qwen trace explorer safety: sanitized trace only; "
            "local demo makes no live Qwen calls.",
            (
                "- first-screen retrieval path: "
                f"{_display_retrieval_path(story['retrieval_path'])}"
            ),
            "- M72 current screenshot gallery: non-destructive M71 replay "
            "screenshots generated under docs/submission/media/m71-replay/.",
            "- M72 screenshot assets: 01-one-click-stale-memory-replay.png, "
            "02-recallpack-active-memory-pack.png, and "
            "03-qwen-provider-evidence.png.",
            (
                "- recorded Qwen trace status: standalone live API smoke passed "
                f"(stored status value: {story['live_qwen_status']})"
            ),
            "- Quality hardening audit: local P0/P1 wording and evidence risks "
            "reviewed.",
            "- M109 positioning remediation: local 1/3 vs 3/3 is an authored "
            "deterministic replay, while stored live evidence supports lifecycle "
            "filtering rather than a live baseline failure-rate claim.",
            "- Skeptical judge Q&A: docs/submission/skeptical-judge-qa.md maps "
            "claim-to-evidence links, bounded limits, and review commands.",
            (
                "- Eight curated lifecycle fixtures: retry, config, cache, "
                "serializer, pagination, realistic API-client auth, "
                "source-backed provider-auth, and source-backed ProjectOdyssey "
                "JIT scenario fixtures "
                "all show stale baseline failure and RecallPack success across "
                f"{generalization['fixture_count']} local fixtures."
            ),
            "- Remaining credibility note: eight local fixtures, including one "
            "non-isomorphic multi-session pagination fixture, one realistic "
            "repo-style API-client fixture, one source-backed provider-auth "
            "fixture, and one source-backed ProjectOdyssey JIT scenario with "
            "an unrigged keyword-provider baseline, are stronger than a single "
            "hero fixture, but still not a broad benchmark.",
            "- Real trace boundary: a consent-first real trace intake kit exists "
            "for future sanitized traces; it is not a production trace claim "
            "and no candidate trace is promoted to submission evidence by "
            "default. Raw local candidates must go through "
            "`tools/validate_real_trace_intake.py --sanitize` before review.",
            "",
            "## M50 external benchmark and winner polish",
            "",
            "- Internal M50 external benchmark notes record judging signals and "
            "reference patterns for the team, but internal research/audit notes "
            "are excluded from the sanitized public bundle.",
            "- docs/submission/demo-video-script.md provides a 2:20-2:45 demo "
            "script that opens with a deterministic local stale-context replay "
            "failing 1/3 fixture tests and RecallPack active memory passing 3/3 "
            "fixture tests.",
            "- Devpost Discussions and Qwen Cloud Discord are the current "
            "official community monitoring channels.",
            "- Project gallery is not yet published, so M50 records reference "
            "patterns without claiming direct competitor analysis.",
            "- One checked-in approved live Qwen E2E trace records "
            "live_e2e_passed; the fresh M98 rerun is checked in as "
            "live_e2e_failed and must not be presented as passing.",
            "- Skills and prior-art projects are recorded as references only; "
            "they are not installed or copied by default.",
            "- M51 architecture diagram: "
            "docs/submission/architecture-diagram.md.",
            "- Architecture summary: Browser demo -> Python demo backend -> SQLite "
            "event and memory store.",
            "- Qwen model summary: Qwen text model -> text-embedding-v4 -> "
            "qwen3-rerank.",
            "- M53 demo media package: docs/submission/demo-media-package.md.",
            "- M53 recording target 2:20-2:45; first frame should show the "
            "deterministic stale-memory failure replay with local baseline "
            "1/3 and RecallPack 3/3.",
            "- A local MP4 demo video candidate is checked in under "
            "docs/submission/media/video-candidate/, but no Devpost video URL "
            "or upload is recorded.",
            "- A six-slide presentation deck is built at "
            "docs/submission/media/recallpack-judge-deck.pptx, but it is a "
            "built-but-not-uploaded presentation PPT and remains a manual "
            "Devpost gate.",
            "- M54 public release gate: docs/submission/public-release-gate.md.",
            "- M54 publish rule: publish the sanitized bundle, not the raw workspace.",
            "- M54/M102 public repository boundary: the repository URL is "
            "recorded at https://github.com/cyq1017/recallpack; local preflight "
            "validates the sanitized bundle but does not prove remote synchronization. "
            "Devpost submission, image push, any future ECS replacement, and any further live Qwen "
            "rerun remain gated; approval-only actions remain blocked until the "
            "user performs or explicitly re-approves each external submission step.",
            "- M55 local screenshot gallery: generated 1280x720 Devpost "
            "candidates under docs/submission/media/.",
            "- M55 screenshot assets: 01-first-run-handoff-simulator.png, "
            "02-recallpack-active-memory-pack.png, and "
            "03-qwen-provider-evidence.png.",
            "- M72 current screenshot gallery: generated 1280x720 M71 replay "
            "candidates under docs/submission/media/m71-replay/.",
            "- M56 reproducible screenshot capture: "
            "tools/capture_demo_screenshots.py can list or regenerate the "
            "local Devpost screenshot gallery without live Qwen or media upload; "
            "capture mode accepts only local demo URLs.",
            "- M57 Devpost preflight: tools/devpost_preflight.py reports local "
            "material readiness and manual gated actions as JSON without "
            "credentials, network calls, media upload, public repo creation, or "
            "Devpost submission.",
            "- Current M57 preflight status should be blocked_gated_actions: "
            "local materials and public repo URL are ready, but required "
            "Devpost architecture/Alibaba Cloud proof file upload, the "
            "built-but-not-uploaded presentation PPT, final video URL/upload, "
            "final media order confirmation, and final Devpost approval remain "
            "manual gates.",
            "- M58 Devpost materials export: tools/export_devpost_materials.py "
            "turns the checked-in Devpost copy, hackathon fields, media assets, "
            "verification evidence, and M57 blockers into local JSON/Markdown "
            "for manual copy/paste without credentials, network calls, upload, "
            "public repo creation, or submission.",
            "- M59 submission evidence index: tools/export_evidence_index.py "
            "maps MemoryAgent positioning, downstream stale handoff proof, Qwen "
            "provider integration, live Qwen E2E boundary, public repo boundary, "
            "and Devpost media readiness to evidence files, commands, risk "
            "levels, and gated boundaries.",
            "- M60 final submission gate: tools/final_submission_gate.py "
            "aggregates Devpost preflight, evidence index, public bundle scan, "
            "and full fresh-clone rehearsal into one local JSON report while "
            "recording the published public repo URL and leaving media upload "
            "and Devpost submission gated.",
            "- M61 public repo preflight: tools/public_repo_preflight.py "
            "checks the sanitized publish surface, MIT license, README judge "
            "entry, submission manifest, forbidden paths, bundle scan, and "
            "judge commands before or after public GitHub repository creation.",
            "- M107 submission readiness loop: "
            "tools/submission_readiness_loop.py aggregates Devpost preflight, "
            "video rehearsal, public repo preflight, and optional full final "
            "submission gate into one local-only JSON loop without push, "
            "deploy, upload, submit, credential reads, or live Qwen calls.",
            "- M66 winner narrative polish: docs/submission/demo-video-script.md "
            "opens with stale project memory causing a wrong patch, "
            "docs/submission/demo-media-package.md adds 15/45/90 second "
            "recording gates, docs/submission/skeptical-judge-qa.md adds "
            "recording-day answers, and docs/submission/blog-post-draft.md "
            "prepares the Blog Post Award narrative.",
            "- M67 final judge rehearsal / M85 deadline runway / M99/M102 wording refresh: "
            "docs/submission/final-judge-rehearsal.md tracks the latest local "
            "package, the M98 evidence snapshot, the M104 public ECS runtime "
            "boundary, final judge commands, manual gates, and claim guardrails "
            "before public repo or Devpost work. M85 is internal deadline runway "
            "control and does not add a new judge-facing product claim.",
            "- M68 video production packet: "
            "docs/submission/video-production-packet.md turns the script into "
            "a recording-day run of show with retake triggers, on-screen "
            "no-go items, upload package, and final self-check.",
            "- M69 recording rehearsal gate / M86 recording release-candidate sync: "
            "tools/video_rehearsal_gate.py "
            "checks the recording packet, screenshots, manual upload gates, "
            "public ECS wording, and latest local bundle reference before "
            "recording; docs/submission/recording-rehearsal-report.md stores "
            "the latest local-only report. M102 keeps the packet aligned with "
            "the M104 public ECS boundary while preserving M98 as the current "
            "evidence snapshot.",
            "- M98 adversarial review remediation: the local evidence remains "
            "green, but the current winner-grade audit now treats a fresh live "
            "Qwen sweep/rerun for the unrigged baseline path as the remaining "
            "P0 prize-credibility gate.",
            "- M99 current-package wording sync: README, final judge "
            "rehearsal, video production packet, recording gate, and public "
            "repo readiness now use version-neutral latest local package wording while "
            "preserving M98 as the current evidence snapshot and M102 as the "
            "public ECS boundary.",
            "- M92/M99 submission media copy consistency gate: recording and "
            "submission copy now keep the latest local package, M98 "
            "evidence snapshot, and M104 public ECS runtime boundaries aligned; "
            "public ECS judge smoke is scoped to the M104 deployment.",
            "- M93 judge first-run command contract: SUBMISSION_MANIFEST.md, "
            "public repo preflight, README, and review packet copy-ready "
            "commands now share the same JUDGE_FIRST_RUN_COMMANDS list so "
            "judge setup instructions do not drift across public surfaces.",
            "- M94 public release gate command contract: the manual public "
            "release gate now includes every command from "
            "JUDGE_FIRST_RUN_COMMANDS, including the video rehearsal gate, so "
            "the last pre-publication checklist matches the judge quickstart.",
            "- M106 current-day release readiness refresh: local readiness, "
            "public repo readiness, and the internal deadline runway now use "
            "2026-07-07 with about 2 days 18 hours 17 minutes remaining; "
            "this is date/readiness maintenance, not a new product claim.",
            "- M96 current-package wording guardrail: judge-facing recording, "
            "review, public-repo, and generated packet surfaces now use "
            "version-neutral latest local package wording instead of calling "
            "M90 the current package.",
            "- M97 source-to-bundle parity preflight: raw-workspace public "
            "repo preflight now compares all public-bundle source files with "
            "the latest sanitized bundle and fails if docs or code changed "
            "after the bundle was built.",
            "- Next polish slices: manual video recording/upload, optional broader "
            "benchmark fixtures, and Devpost submission after explicit approval.",
            "",
            "## Evidence Snapshot",
            "",
            f"- 32-event behavior contract fixture suite positioning: {suite['positioning']}",
            (
                "- micro-suite prediction source: "
                f"{evidence['prediction_source']} behavior contract fixture evaluator"
            ),
            "- deprecated fixture prediction fields are ignored by regression tests",
            (
                f"- behavior-contract runtime counts, not model-quality metrics: "
                f"TP={counts['tp']} FP={counts['fp']} FN={counts['fn']} "
                f"TN={counts['tn']}"
            ),
            (
                "- behavior-contract supersession edges, oracle-backed runtime "
                f"check: {edge_counts['correct']}/{edge_counts['gold']} correct"
            ),
            f"- behavior-contract edge F1: {metrics['edge_f1']}",
            f"- behavior-contract memory type accuracy: {metrics['memory_type_accuracy']}",
            "- runtime pack-selection contract, not live model recall metric: "
            f"required memory recall at estimated 512 is {metrics['required_memory_recall_at_512']}",
            f"- stale selected items: {metrics['stale_selected_items']}",
            (
                "- baseline source-recall score: "
                f"{baseline['metrics']['hidden_test_pass_count']}/3"
            ),
            (
                "- RecallPack fixture tests: "
                f"{recallpack['metrics']['hidden_test_pass_count']}/3"
            ),
            (
                "- baseline downstream fixture tests: "
                f"{baseline_downstream['summary']['passed']}/3"
            ),
            (
                "- RecallPack downstream fixture tests: "
                f"{recallpack_downstream['summary']['passed']}/3"
            ),
            "- keyword-scored fake-embedding + rerank raw-history baseline stale context produces a wrong "
            "retry patch; RecallPack active memory produces the passing retry "
            "patch",
            *_generalization_fixture_lines(generalization_fixtures),
            "",
            "## Copy-Ready Commands",
            "",
            "```bash",
            "PYTHONPATH=src python3 tools/build_demo_data.py",
            "PYTHONPATH=src python3 tools/build_live_qwen_e2e_preflight.py",
            "PYTHONPATH=src python3 tools/build_live_qwen_embedding_baseline_preflight.py",
            "PYTHONPATH=src python3 tools/build_review_packet.py",
            "python3 tools/capture_demo_screenshots.py --list",
            *JUDGE_FIRST_RUN_COMMANDS,
            'bundle_target="dist/recallpack-submission-$(date +%Y%m%d-%H%M%S)"',
            'PYTHONPATH=src python3 tools/build_submission_bundle.py --target "$bundle_target"',
            'PYTHONPATH=src python3 tools/fresh_clone_smoke.py --source "$bundle_target"',
            'PYTHONPATH=src python3 tools/fresh_clone_smoke.py --source "$bundle_target" --full',
            "PYTHONPATH=src python3 -m recallpack.demo_server --host 127.0.0.1 --port 8789",
            "python3 tools/judge_smoke.py --url http://127.0.0.1:8789",
            "curl http://127.0.0.1:8789/api/health",
            "curl http://127.0.0.1:8789/api/demo",
            "curl -X POST http://127.0.0.1:8789/observe \\",
            "  -H 'content-type: application/json' \\",
            "  -d '{\"project_id\":\"project-a\",\"session_id\":\"session-a\",\"event_id\":\"turn-001\",\"sequence_no\":1,\"actor\":\"user\",\"kind\":\"message\",\"observed_at\":\"2026-06-24T00:00:00Z\",\"text\":\"Use three attempts with a fixed 100 ms delay in the retry helper.\"}'",
            "curl -X POST http://127.0.0.1:8789/compile \\",
            "  -H 'content-type: application/json' \\",
            "  -d '{\"project_id\":\"project-a\",\"goal\":\"Update the retry helper to the current project policy.\",\"component\":\"retry\",\"budget_tokens\":512}'",
            "```",
            "",
            "## Safety Boundary",
            "",
            "This packet does not create cloud resources by itself. An approved "
            "Alibaba Cloud ECS deployment is available at http://101.133.224.223/ "
            "and passed judge smoke.",
            *safety_lines,
            "",
            "## Reviewer Focus",
            "",
            "- Does the demo prove memory lifecycle rather than generic RAG?",
            "- Does Qwen provider integration evidence cover retrieval, rerank, "
            "and memory-operation judgment?",
            "- Is the curated deterministic baseline comparison labeled honestly?",
            "- Are the remaining live/deployment gates explicit?",
            "",
        ]
)


def _evidence_boundary_lines(boundary: dict[str, object]) -> list[str]:
    sections = boundary.get("sections", [])
    if not isinstance(sections, list):
        return []
    lines: list[str] = []
    for section in sections:
        if not isinstance(section, dict):
            continue
        label = str(section.get("label", "Evidence"))
        lines.append(f"- {label}:")
        items = section.get("items", [])
        if not isinstance(items, list):
            continue
        for item in items:
            lines.append(f"  - {item}")
    return lines


def _generalization_fixture_lines(fixtures: list[dict[str, object]]) -> list[str]:
    if len(fixtures) == 8:
        count_label = "Eight"
    else:
        count_label = str(len(fixtures))
    lines = [f"- {count_label} curated lifecycle fixture details:"]
    for fixture in fixtures:
        lines.append(
            "  - "
            f"{fixture['project_id']} {fixture['component']}: baseline "
            f"{fixture['baseline_downstream_tests']}, RecallPack "
            f"{fixture['recallpack_downstream_tests']}, baseline sources "
            f"{', '.join(fixture['baseline_selected_sources'])}, RecallPack sources "
            f"{', '.join(fixture['recallpack_selected_sources'])}"
        )
        rejection_code = fixture.get("baseline_rejection_code")
        if rejection_code:
            lines.append(
                "  - "
                f"{fixture['project_id']} {fixture['component']}: baseline "
                f"rejection={rejection_code}; causal reason="
                f"{fixture['baseline_causal_reason']}"
            )
    return lines


def _display_retrieval_path(path_steps: list[str]) -> str:
    return " -> ".join(
        "estimated 512-token serialized-memory budget selector"
        if step == "512-token budget selector"
        else step
        for step in path_steps
    )


def _qwen_live_trace_lines(
    qwen_payload: dict[str, object],
    usage: dict[str, object],
) -> list[str]:
    if qwen_payload.get("live_qwen_run"):
        return [
            "- standalone live API smoke passed: yes, sanitized contract trace recorded",
            (
                "- actual Qwen token usage: "
                f"memory={usage.get('memory_decision_total_tokens', 0)} "
                f"embedding={usage.get('embedding_total_tokens', 0)} "
                f"rerank={usage.get('rerank_total_tokens', 0)}"
            ),
        ]
    return [
        "- live Qwen run: no, gated",
        "- fake-provider traces match the live-provider schema",
    ]


def _qwen_trace_explorer_lines(qwen_payload: dict[str, object]) -> list[str]:
    explorer = qwen_payload.get("trace_explorer")
    if not isinstance(explorer, dict):
        return [
            "- M73 live Qwen trace explorer: not available in this payload; "
            "do not claim trace-explorer evidence without the live E2E trace file."
        ]
    role_summary = explorer.get("role_summary")
    if not isinstance(role_summary, list):
        role_summary = []
    roles = [
        str(row.get("provider_role"))
        for row in role_summary
        if isinstance(row, dict) and row.get("provider_role")
    ]
    stages = explorer.get("stages")
    if not isinstance(stages, list):
        stages = []
    stage_ids = [
        str(stage.get("id"))
        for stage in stages
        if isinstance(stage, dict) and stage.get("id")
    ]
    boundary = explorer.get("safety_boundary")
    if not isinstance(boundary, dict):
        boundary = {}
    return [
        "- M73 live Qwen trace explorer: checked-in sanitized live E2E trace "
        "is visible in `/api/demo` without rerunning Qwen.",
        (
            "- Stored Live Qwen Trace display mode: "
            f"{explorer.get('display_title', 'Stored Live Qwen Trace')}; "
            f"source_kind={explorer.get('source_kind', 'unknown')}."
        ),
        (
            "- trace_explorer status/source: "
            f"{explorer.get('status', 'unknown')} from "
            f"{explorer.get('source', 'unknown')}."
        ),
        (
            "- role_summary covers: "
            f"{', '.join(roles) if roles else 'none recorded'}."
        ),
        (
            "- trace_explorer stages: "
            f"{', '.join(stage_ids) if stage_ids else 'none recorded'}."
        ),
        (
            "- trace_explorer selected_sources="
            f"{explorer.get('selected_sources', [])}; excluded_sources_checked="
            f"{explorer.get('excluded_sources_checked', [])}."
        ),
        (
            "- trace_explorer downstream summary: "
            f"{explorer.get('downstream_summary', 'not recorded')}."
        ),
        (
            "- trace_explorer safety boundary: sanitized trace only="
            f"{bool(boundary.get('sanitized_trace_only'))}; no credentials="
            f"{bool(boundary.get('no_credentials'))}; prompts redacted="
            f"{bool(boundary.get('prompts_redacted'))}; local demo makes no "
            f"live Qwen calls={bool(boundary.get('local_demo_no_live_calls'))}."
        ),
    ]


def _load_live_e2e_trace(path: Path) -> dict[str, object] | None:
    if not path.exists():
        return None
    try:
        parsed = json.loads(path.read_text())
    except json.JSONDecodeError:
        return {"live_status": "unreadable_trace"}
    return parsed if isinstance(parsed, dict) else {"live_status": "unreadable_trace"}


def _load_live_e2e_preflight(path: Path) -> dict[str, object] | None:
    if not path.exists():
        return None
    try:
        parsed = json.loads(path.read_text())
    except json.JSONDecodeError:
        return {"preflight_status": "unreadable_preflight"}
    return parsed if isinstance(parsed, dict) else {"preflight_status": "unreadable_preflight"}


def _qwen_live_e2e_lines(trace: dict[str, object] | None) -> list[str]:
    if trace is None:
        return ["- live Qwen E2E run: no, gated."]
    usage = trace.get("actual_qwen_token_usage")
    if not isinstance(usage, dict):
        usage = {}
    selected_sources = trace.get("selected_sources")
    if not isinstance(selected_sources, list):
        selected_sources = []
    provider_traces = trace.get("provider_traces")
    provider_trace_count = len(provider_traces) if isinstance(provider_traces, list) else 0
    text_models = _provider_models_for_roles(
        provider_traces,
        {"memory_decision", "patch_generation"},
    )
    lines = [
        (
            "- live Qwen provider-path integration trace: "
            f"{trace.get('live_status', 'unknown')}."
        ),
        (
            "- live Qwen E2E current-model trace: "
            f"{', '.join(text_models) if text_models else 'not recorded'}."
        ),
        (
            "- live Qwen E2E selected_sources="
            f"{selected_sources}; provider_trace_count={provider_trace_count}; "
            f"actual token usage memory={usage.get('memory_decision_total_tokens', 0)} "
            f"embedding={usage.get('embedding_total_tokens', 0)} "
            f"rerank={usage.get('rerank_total_tokens', 0)}."
        ),
    ]
    if trace.get("live_status") == "live_e2e_passed":
        downstream = trace.get("downstream_patch_generation")
        if not isinstance(downstream, dict):
            downstream = {}
        baseline = downstream.get("baseline")
        recallpack = downstream.get("recallpack")
        baseline_summary = baseline.get("summary") if isinstance(baseline, dict) else {}
        recallpack_summary = (
            recallpack.get("summary") if isinstance(recallpack, dict) else {}
        )
        lines.append(
            "- live Qwen E2E one-run integration outcome: observe events completed, stale retry "
            "memory was excluded, active retry and project preference were "
            "selected, and the intended downstream patch path completed for RecallPack. "
            "This is not statistical validation of live downstream performance."
        )
        if "session-a:turn-004" in selected_sources:
            lines.append(
                "- live Qwen E2E note: `session-a:turn-004` is supporting "
                "retry-failure evidence from the tool result; the required "
                "active decision and preference remain `session-a:turn-005` "
                "and `session-a:turn-003`."
            )
        lines.append(
            "- live Qwen E2E one-run downstream result, not a headline metric: baseline "
            f"{baseline_summary.get('passed', 0)}/"
            f"{baseline_summary.get('passed', 0) + baseline_summary.get('failed', 0)}; "
            "RecallPack "
            f"{recallpack_summary.get('passed', 0)}/"
            f"{recallpack_summary.get('passed', 0) + recallpack_summary.get('failed', 0)}; "
            "the fresh M98 rerun did not reproduce this downstream delta."
        )
        return lines
    failure_kind = trace.get("failure_kind")
    failure_summary = trace.get("failure_summary")
    if failure_kind:
        lines.append(
            "- live Qwen E2E failure_kind="
            f"{failure_kind}; failure_summary={failure_summary or 'not recorded'}."
        )
        lines.append(
            "- live Qwen E2E current blocker: live provider request failed before "
            "the observe/compile lifecycle completed; the failure trace is "
            "sanitized and records no credentials."
        )
        return lines
    lines.append(
        (
            "- live Qwen E2E did not record an explicit failure kind, but the "
            "stored status is not passing; do not claim a passing live E2E "
            "without rerunning the gated command."
        )
    )
    return lines


def _qwen_fresh_m98_live_rerun_lines(trace: dict[str, object] | None) -> list[str]:
    if trace is None:
        return ["- fresh M98 live Qwen rerun: not recorded."]
    status = trace.get("live_status", "unknown")
    selected_sources = trace.get("selected_sources")
    if not isinstance(selected_sources, list):
        selected_sources = []
    downstream = trace.get("downstream_patch_generation")
    if not isinstance(downstream, dict):
        downstream = {}
    baseline = downstream.get("baseline")
    recallpack = downstream.get("recallpack")
    baseline_summary = baseline.get("summary") if isinstance(baseline, dict) else {}
    recallpack_summary = (
        recallpack.get("summary") if isinstance(recallpack, dict) else {}
    )
    lines = [
        f"- fresh M98 live Qwen rerun status: {status}.",
        (
            "- fresh M98 live Qwen rerun selected_sources="
            f"{selected_sources}."
        ),
        (
            "- fresh M98 live Qwen rerun downstream: baseline "
            f"{baseline_summary.get('passed', 0)}/"
            f"{baseline_summary.get('passed', 0) + baseline_summary.get('failed', 0)}; "
            "RecallPack "
            f"{recallpack_summary.get('passed', 0)}/"
            f"{recallpack_summary.get('passed', 0) + recallpack_summary.get('failed', 0)}."
        ),
    ]
    if status != "live_e2e_passed":
        lines.append(
            "- fresh M98 live Qwen rerun is stored as failed evidence; do not "
            "claim the fresh M98 live rerun passed."
        )
    return lines


def _qwen_live_e2e_preflight_lines(
    preflight: dict[str, object] | None,
    label: str = "live Qwen E2E preflight",
    selected_prefix: str = "preflight",
) -> list[str]:
    if preflight is None:
        return [f"- {label}: not generated."]
    role_counts = preflight.get("request_role_counts")
    if not isinstance(role_counts, dict):
        role_counts = {}
    selected_sources = preflight.get("expected_selected_sources")
    if not isinstance(selected_sources, list):
        selected_sources = []
    contract = preflight.get("memory_decision_request_contract")
    if not isinstance(contract, dict):
        contract = {}
    return [
        f"- {label}: generated without credentials or network calls.",
        f"- preflight_status: {preflight.get('preflight_status', 'unknown')}.",
        (
            "- network_calls_made="
            f"{str(bool(preflight.get('network_calls_made'))).lower()}."
        ),
        (
            "- request_role_counts: "
            f"memory_decision={role_counts.get('memory_decision', 0)} "
            f"embedding={role_counts.get('embedding', 0)} "
            f"rerank={role_counts.get('rerank', 0)} "
            f"patch_generation={role_counts.get('patch_generation', 0)}."
        ),
        (
            f"- {selected_prefix} expected selected sources: "
            f"{selected_sources}; future live reruns remain gated."
        ),
        (
            f"- {selected_prefix} memory-decision contract checks: "
            f"structured_event_metadata={contract.get('all_structured_event_metadata')}, "
            f"descriptive_tool_schema={contract.get('all_descriptive_tool_schema')}, "
            f"tool_choice_function={contract.get('all_tool_choice_function')}."
        ),
    ]


def _qwen_projectodyssey_live_e2e_lines(
    trace: dict[str, object] | None,
) -> list[str]:
    if trace is None:
        return ["- ProjectOdyssey live Qwen E2E run: not recorded."]
    selected_sources = trace.get("selected_sources")
    if not isinstance(selected_sources, list):
        selected_sources = []
    checks = trace.get("checks")
    if not isinstance(checks, dict):
        checks = {}
    downstream = trace.get("downstream_patch_generation")
    if not isinstance(downstream, dict):
        downstream = {}
    baseline = downstream.get("baseline")
    recallpack = downstream.get("recallpack")
    baseline_summary = baseline.get("summary") if isinstance(baseline, dict) else {}
    recallpack_summary = (
        recallpack.get("summary") if isinstance(recallpack, dict) else {}
    )
    usage = trace.get("actual_qwen_token_usage")
    if not isinstance(usage, dict):
        usage = {}
    provider_traces = trace.get("provider_traces")
    provider_trace_count = len(provider_traces) if isinstance(provider_traces, list) else 0
    status = str(trace.get("live_status", "unknown"))
    baseline_ratio = (
        f"{baseline_summary.get('passed', 0)}/"
        f"{baseline_summary.get('passed', 0) + baseline_summary.get('failed', 0)}"
    )
    recallpack_ratio = (
        f"{recallpack_summary.get('passed', 0)}/"
        f"{recallpack_summary.get('passed', 0) + recallpack_summary.get('failed', 0)}"
    )
    if status == "live_e2e_passed" and recallpack_ratio == "3/3":
        boundary = (
            "- ProjectOdyssey live boundary: Qwen selected the active decision "
            "and dependency preference while excluding the stale policy, and "
            "the RecallPack live-generated patch passed 3/3 downstream fixture "
            "tests. The separate fresh M98 rerun remains failed, so this is "
            "source-backed fixture integration evidence, not a broad live "
            "benchmark claim."
        )
    else:
        boundary = (
            "- ProjectOdyssey live boundary: Qwen selected the active decision "
            "and dependency preference while excluding the stale policy, but "
            "the live patch-generation outputs did not pass fixture tests; "
            "do not claim ProjectOdyssey live E2E passed."
        )
    return [
        (
            "- ProjectOdyssey live Qwen E2E run: "
            f"{status}."
        ),
        (
            "- ProjectOdyssey live selected_sources="
            f"{selected_sources}; provider_trace_count={provider_trace_count}; "
            "required_sources_selected="
            f"{checks.get('required_sources_selected')}; stale_sources_excluded="
            f"{checks.get('stale_sources_excluded')}."
        ),
        (
            "- ProjectOdyssey live downstream result: baseline "
            f"{baseline_ratio}; RecallPack {recallpack_ratio}."
        ),
        (
            "- ProjectOdyssey live token usage: memory="
            f"{usage.get('memory_decision_total_tokens', 0)} embedding="
            f"{usage.get('embedding_total_tokens', 0)} rerank="
            f"{usage.get('rerank_total_tokens', 0)} patch_generation="
            f"{usage.get('patch_generation_total_tokens', 0)}."
        ),
        boundary,
    ]


def _qwen_live_embedding_baseline_preflight_lines(
    preflight: dict[str, object] | None
) -> list[str]:
    if preflight is None:
        return ["- real embedding baseline preflight: not generated."]
    role_counts = preflight.get("request_role_counts")
    if not isinstance(role_counts, dict):
        role_counts = {}
    selected_sources = preflight.get("expected_selected_sources")
    if not isinstance(selected_sources, list):
        selected_sources = []
    checks = preflight.get("checks")
    if not isinstance(checks, dict):
        checks = {}
    return [
        (
            "- real embedding baseline preflight: "
            f"{preflight.get('preflight_status', 'unknown')}."
        ),
        (
            "- real embedding baseline request_role_counts: "
            f"embedding={role_counts.get('embedding', 0)} "
            f"rerank={role_counts.get('rerank', 0)}."
        ),
        (
            "- real embedding baseline expected selected_sources="
            f"{selected_sources}; expected downstream fixture tests "
            f"{preflight.get('expected_downstream_tests', 'not recorded')}."
        ),
        (
            "- real embedding baseline checks: "
            "stale_retry_selected_by_real_embedding_path="
            f"{checks.get('stale_retry_selected_by_real_embedding_path')}; "
            "active_retry_not_selected_by_baseline="
            f"{checks.get('active_retry_not_selected_by_baseline')}."
        ),
        "- real embedding baseline live run remains gated; preflight records "
        "provider contract shape without credentials or network calls.",
    ]


def _qwen_live_embedding_baseline_trace_lines(
    traces: list[dict[str, object]]
) -> list[str]:
    if not traces:
        return ["- live raw-history embedding+rerank baseline traces: not recorded."]
    active_hits = 0
    stale_hits = 0
    summaries: list[str] = []
    for trace in traces:
        selected_sources = trace.get("selected_sources")
        if not isinstance(selected_sources, list):
            selected_sources = []
        checks = trace.get("checks")
        if not isinstance(checks, dict):
            checks = {}
        if "session-a:turn-005" in selected_sources or checks.get("active_retry_selected"):
            active_hits += 1
        if "session-a:turn-001" in selected_sources or checks.get("stale_retry_selected"):
            stale_hits += 1
        status = trace.get("live_status", "unknown")
        summaries.append(f"{status}: selected_sources={selected_sources}")
    return [
        (
            "- live raw-history embedding+rerank baseline traces: "
            f"{len(traces)} stored runs; active retry selected in {active_hits}/"
            f"{len(traces)}; stale retry selected in {stale_hits}/{len(traces)}."
        ),
        (
            "- live baseline disclosure: stored plain retrieval runs selected "
            "active retry memory and did not reproduce the local stale-baseline "
            "failure. Therefore local 1/3 versus 3/3 is an authored deterministic "
            "failure-class illustration, not live frequency evidence."
        ),
        "- live baseline trace summaries: " + "; ".join(summaries) + ".",
    ]


def _provider_models_for_roles(
    provider_traces: object,
    roles: set[str],
) -> list[str]:
    if not isinstance(provider_traces, list):
        return []
    models: list[str] = []
    for trace in provider_traces:
        if not isinstance(trace, dict) or trace.get("provider_role") not in roles:
            continue
        model_name = trace.get("model_name")
        if isinstance(model_name, str) and model_name not in models:
            models.append(model_name)
    return models


def _safety_boundary_lines(qwen_payload: dict[str, object]) -> list[str]:
    if qwen_payload.get("live_qwen_run"):
        return [
            "Live Qwen contract was run once with explicit approval; this packet "
            "stores only sanitized trace records.",
            "No credentials, raw prompts, raw memory text, image push, public "
            "endpoint, or hackathon submission action is included.",
        ]
    return [
        "No credentials, live Qwen calls, image push, public endpoint, or "
        "hackathon submission action is included.",
    ]
