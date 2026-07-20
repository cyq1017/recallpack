# RecallPack Skeptical Judge Q&A

This document is for judge review. It maps likely hard questions to concrete
local evidence and avoids claims the project has not proven.

## Recording-Day Judge Answers

Use these short answers in the demo video, Devpost comments, or live judging.

### Is this just RAG?

No. RAG ranks similar text. RecallPack first writes lifecycle state from
session events, marks stale memories as superseded, and only then recalls active
memories under a budget.

### Does the public demo run live Qwen?

No. The public demo is credential-free and uses deterministic fake providers
through the same trace contract. The repo includes a sanitized approved live
Qwen E2E trace with `live_e2e_passed`. The fresh M98 unrigged-baseline rerun is
stored separately with `live_e2e_failed`, so we do not call the fresh M98 run
passing live E2E evidence.

### Is the downstream patch hardcoded?

The local proof uses a deterministic context-keyed patch provider for
credential-free reproducibility. It is not live Qwen inference. The important
local claim is narrower: baseline and RecallPack use the same provider
contract, selected context, allowed edit paths, temp repo, and fixture tests. The
live Qwen patch-generation claim comes only from the stored sanitized E2E trace.

### Why only eight fixtures?

They are curated lifecycle fixtures, not a broad benchmark. The claim is
mechanistic: across retry, config, cache, serializer, pagination, API-client
auth, source-backed AI provider auth-header, and source-backed ProjectOdyssey
JIT policy patterns, stale raw history fails while active lifecycle memory
passes. Project-e also breaks the original single-session turn-id structure.
Project-h uses public ProjectOdyssey artifacts only as inspiration for an
authored scenario; it is not a production trace and does not claim RecallPack
fixed ProjectOdyssey.

### Why is this MemoryAgent?

The core operations are remember, supersede, and recall. The project is not a
generic agent platform; it is a stale-aware memory runtime for coding-agent
handoffs.

## Is This Actually A MemoryAgent Project?

Yes, within the local MVP boundary. RecallPack is not a generic RAG wrapper: it
has a write path and a recall path.

Evidence:

- HTTP `POST /observe` processes ordered session events through
  `ObserveRuntime` and writes durable memory records.
- `/compile` recalls active task-relevant memories under an estimated 512-token
  serialized-memory budget.
- Superseded memory is excluded before embedding retrieval and rerank.
- Tests: `tests/test_observe_lifecycle.py`, `tests/test_sqlite_event_store.py`,
  `tests/test_compile.py`, and `tests/test_hero_evaluation.py`.

Limit:

- RecallPack is an advisory memory runtime. It does not enforce policy, approve
  actions, or replace a coding-agent framework.

## Qwen Provider Integration Evidence

Qwen provider integration evidence is defined at the provider boundary:

- Qwen text model: memory extraction, classification, duplicate detection, and
  supersession judgment.
- Current Qwen text adapter: OpenAI-compatible `tools/tool_choice` request with
  default model `qwen3.7-plus-2026-05-26`.
- `text-embedding-v4`: candidate memory retrieval.
- `qwen3-rerank`: precision rerank over embedding top-N candidates.

Evidence:

- Provider adapters and fake-provider contract tests live in
  `src/recallpack/providers.py` and `tests/test_providers.py`.
- The sanitized live trace is stored in
  `docs/submission/live-qwen-e2e-trace.json` for the current E2E proof.
- The older standalone API smoke is stored in
  `docs/submission/live-qwen-trace.json`; keep it as a historical contract
  smoke with stored status `live_contract_passed`, not as the current shipped
  model E2E proof.
- Local HTTP `/compile` uses deterministic keyword fake embedding/rerank
  providers, so the public smoke path exercises retrieval ordering without
  reading credentials.
- M43 adds `tools/run_live_qwen_e2e.py`, a gated runner that can execute the
  hero observe/compile lifecycle through live Qwen providers after separate
  approval.
- One stored provider-path integration trace wrote
  `docs/submission/live-qwen-e2e-trace.json`; the stored status is
  `live_e2e_passed` with active retry memory selected and stale retry memory
  excluded. Treat it as one successful intended live path, not statistical
  validation of downstream live performance.
- A fresh M98 rerun is also checked in as `live_e2e_failed`; lifecycle
  filtering held, but the downstream pass-rate delta did not reproduce. Treat
  that as support for the structural lifecycle claim, not as a passing fresh
  E2E result.
- M76 adds `tools/build_live_qwen_embedding_baseline_preflight.py`, a
  credential-free no-network preflight for the real `text-embedding-v4` raw
  history baseline path. It verifies 13 embedding requests plus one
  `qwen3-rerank` request shape before any approved live baseline run.

Limit:

- Unit tests do not require live credentials. They use fake providers with the
  same sanitized trace schema. Do not read this as a claim that every local
  test makes a live Qwen call.
- The deterministic keyword fake providers are not a substitute for continuous
  live Qwen serving.
- The checked-in live E2E trace is a single provider-path integration trace,
  not a claim that the public demo endpoint performs live Qwen calls.

## Is The Baseline Fair?

The budget-comparable local baseline is a keyword-scored fake-embedding +
rerank raw-history baseline over raw session events. It is not source-picked
from `gold.json` selected-source IDs. For the first seven fixtures, the local
scoring geometry still uses fixture-authored scoring terms:
`baseline_embedding_terms` and `baseline_downrank_phrases` replay the intended
stale-retrieval failure. Project-h is stricter: it uses the deterministic
keyword-provider path without those fixture-authored baseline scoring fields.
Treat the full suite as deterministic demo replay evidence, not proof that
every embedder would fail the same way. Live embedding evidence is represented
by the gated live baseline path and must be rerun before being used as the
headline baseline result.

Evidence:

- `tests/test_hero_evaluation.py` mutates fixture selected-source fields and
  proves the keyword-scored fake-embedding + rerank baseline still behaves
  from raw event text.
- `src/recallpack/evaluation.py` intentionally reads
  `baseline_embedding_terms` and `baseline_downrank_phrases` from most fixture
  gold metadata for local deterministic baseline replay, and also supports the
  stricter `deterministic_keyword_provider` baseline mode used by project-h.
- M63 also routes both baseline and RecallPack downstream patches through the
  same deterministic context-keyed local patch provider.
- The raw full-history variant is shown only as a coverage reference and is
  marked not budget-comparable.
- The review packet states this explicitly in
  `docs/submission/review-packet.md`.
- `tests/test_qwen_live_embedding_baseline.py` and
  `tools/build_live_qwen_embedding_baseline_preflight.py` prove the real
  embedding baseline path will call Qwen embeddings for the goal plus all raw
  session events and then pass top-N to `qwen3-rerank`.

Limit:

- This is a local hackathon evidence baseline, not a broad benchmark,
  published benchmark, or live embedding benchmark.
- The real embedding baseline currently has a no-network preflight artifact;
  do not claim a passing live baseline trace until the gated live runner is
  explicitly approved and succeeds.
- The hero fixture uses a gold-oracle HeroFixtureDecider for behavior-contract
  replay, and the micro-suite uses a gold-echoing micro-suite behavior-contract decider.
  Those are useful for regression contracts, not independent model-quality
  measurements.

## Could The Eight Fixtures Be Overfit?

Yes, they are still local fixtures. The claim is narrower: eight local fixtures
show that the same lifecycle mechanism handles different stale-memory patterns,
with project-e intentionally breaking the original single-session turn-id shape
and project-h adding a source-backed ProjectOdyssey JIT policy scenario.

Evidence:

- project-a retry helper: stale fixed-delay retry is superseded.
- project-b config loader: stale missing-key `None` behavior is superseded.
- project-c cache policy: stale user-only key and 300 second TTL are
  superseded.
- project-d audit serializer: stale raw email serialization is superseded.
- project-e pagination policy: stale offset pagination is superseded by cursor
  tokens with a clamped limit.
- project-f API-client policy: stale Authorization plus short-timeout behavior
  is superseded by `X-Api-Key` and timeout=10.
- project-g provider-auth policy: stale forwarding of caller `Authorization`
  with `X-Api-Key` is superseded by mode-specific upstream auth headers.
- project-h CI policy: stale JIT retry/skip/continue-on-error workarounds are
  superseded by fail-fast fix-forward handling with a minimal reproducer.
- In all eight local fixtures, keyword-scored fake-embedding + rerank baseline
  passes 1/3 temp repo fixture tests, while RecallPack passes 3/3.

Limit:

- This is eight local fixtures, including one non-isomorphic multi-session
  sparse-event fixture and two source-backed pattern fixtures, not a broad
  benchmark.

## Does The Downstream Proof Execute Real Code?

Yes for the local proof. The evaluator generates patch files through the same
deterministic context-keyed local patch provider for baseline and RecallPack,
using only the goal, selected context, and allowed edit paths before applying
them to a temporary copy of each fixture repository and running temp repo hidden
tests.

Evidence:

- `src/recallpack/downstream.py` applies files under allowed paths.
- `tests/test_hero_evaluation.py` verifies downstream behavior for retry,
  config, cache, and serializer fixtures.
- The docs refer to this as temp repo fixture tests, not a source-id selection
  score.

Limit:

- Patch generation is deterministic for the hackathon proof. It is not a full
  autonomous coding model.

## What Is The /observe Concurrency Boundary?

The local proof is intentionally single-process and SQLite-backed.

Evidence:

- Event ordering, idempotency, retryable failure, pending duplicate replay, and
  lease-token/attempt fencing are tested in
  `tests/test_observe_idempotency.py` and `tests/test_sqlite_event_store.py`.
- The deployment proof fixes `deployment_replicas = 1` and `application_workers
  = 1`.

Limit:

- `/observe concurrency boundary` is not claimed to support multi-worker
  scale-out. Public deployment must keep a single worker unless database-backed
  cross-process locking is added.

## How Should A Judge Verify The Local Package?

Run the normal suite, start the server, then run the smoke script.

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
PYTHONPATH=src python3 -m recallpack.demo_server --host 127.0.0.1 --port 8789
python3 tools/judge_smoke.py --url http://127.0.0.1:8789
```

Evidence:

- `tests/test_judge_smoke.py` runs the smoke script against a real local
  `HTTPServer`.
- `tools/judge_smoke.py` verifies `GET /`, `GET /api/demo`, `POST /observe`,
  and `POST /compile`.

## What Remains Gated?

These actions require explicit approval:

- any additional live Qwen credential access or live contract rerun;
- any further public repository push or visibility change after the current
  sanitized public repo at https://github.com/cyq1017/recallpack;
- Docker image push;
- replacing the current approved public Alibaba Cloud ECS deployment or exposing
  any new public endpoint;
- hackathon submission.
