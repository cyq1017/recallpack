# RecallPack Hackathon Fields

Project name: RecallPack

Track: MemoryAgent

Tagline: Stale-aware memory lifecycle for coding-agent handoffs.

## Short Description

RecallPack helps a coding agent carry useful project memory across sessions
without leaking stale decisions into the next handoff. It observes ordered
session events, writes durable project memories, marks older memories as
superseded through lifecycle edges, and compiles only active task-relevant
memory into an estimated 512-token serialized-memory pack.

## Problem

Generic top-k RAG can retrieve old project decisions that were later replaced.
A coding agent can resolve the conflict if both the old decision and the newer
reversing decision are in context. The handoff failure happens earlier: budgeted
selection can keep the stale decision and drop the counterevidence.

## Solution

RecallPack separates runtime memory lifecycle from recall. `/observe` processes
session events and maintains active vs superseded memory state. `/compile`
retrieves active candidates for the current goal, applies ranking, and produces
a compact handoff pack with provenance.

## Qwen Usage

- `text-embedding-v4`: candidate memory retrieval.
- `qwen3-rerank`: precision improvement over embedding top-N.
- Qwen text model: memory extraction, type classification, duplicate detection,
  and supersession judgment.
- Current Qwen text adapter: OpenAI-compatible `tools/tool_choice` contract with
  default model `qwen3.7-plus-2026-05-26`.

Deterministic code handles event ordering, lease/CAS behavior, lifecycle writes,
token budgeting, and final pack assembly.

## Local Evidence

- Eight downstream lifecycle fixtures: project-a retry helper, project-b config
  loader, project-c cache policy, project-d audit serializer, project-e
  pagination policy, project-f realistic API-client auth migration, and
  project-g source-backed AI provider auth-header mode, plus project-h
  source-backed ProjectOdyssey JIT policy.
- 32-event behavior contract fixture suite. These counts are runtime regression
  checks for the lifecycle engine, not model-quality measurements.
- Deprecated fixture prediction fields are ignored by regression tests.
- Behavior-contract runtime counts: TP=20 FP=0 FN=0 TN=12.
- Behavior-contract supersession edges: 10/10 correct.
- Runtime pack-selection contract: required memory recall at estimated 512 is
  1.0 and stale selected items are 0.
- Raw full-history reference: all 12 events, not budget-comparable.
- Deterministic local replay: keyword-scored fake-embedding + rerank
  raw-history baseline fixture tests: 1/3; local scoring terms are
  fixture-authored for replay, not an independent embedding benchmark.
- Deterministic local replay: RecallPack fixture tests: 3/3.
- Downstream local deterministic context-keyed patch provider proof: stale-context retry patch
  passes 1/3 fixture tests.
- Downstream RecallPack proof: active-memory retry patch passes 3/3 fixture
  tests.
- Eight curated lifecycle fixtures: project-a retry, project-b config,
  project-c cache, project-d serializer, project-e pagination, and
  project-f realistic API-client auth, plus project-g source-backed provider
  auth-header and project-h source-backed ProjectOdyssey JIT stale contexts
  each pass 1/3 fixture tests; RecallPack active memory passes 3/3 fixture
  tests in each fixture.
- Qwen trace proof: sanitized live-provider traces cover memory_decision,
  embedding, and rerank with sanitized request-id presence and aggregate token
  usage.
- Live Qwen E2E: one stored provider-path integration trace stores
  `live_e2e_passed`; selected sources include active retry memory
  `session-a:turn-005`, retry lesson `session-a:turn-004`, and dependency
  preference `session-a:turn-003`; stale `session-a:turn-001` is excluded.
- Live raw-history embedding+rerank baseline: two stored live runs selected
  active retry `session-a:turn-005` and did not select stale
  `session-a:turn-001`; the local 1/3 vs 3/3 replay is an authored deterministic
  failure-class illustration, not a live failure-rate measurement.
- Fresh retry-policy live rerun: checked in as failed evidence. Lifecycle filtering held, but
  the downstream 3/3 delta did not reproduce; do not present it as a passing
  fresh live rerun.
- Deterministic stale-memory failure replay: first screen steps through stale
  context, wrong retry patch, baseline 1/3, active memory pack, and RecallPack
  3/3; the first-run handoff simulator remains as a compact summary.
- Compile proof: `/compile` uses local fake embedding top-N retrieval before
  fake qwen3-rerank-shaped rerank and estimated 512-token budget selection.
- Live model evidence: stored sanitized one-run E2E trace covers Qwen memory
  decisions, `text-embedding-v4`, `qwen3-rerank`, and Qwen patch generation.
- Local HTTP `/compile` proof uses deterministic keyword fake embedding/rerank,
  not zero-vector or identity-rerank smoke.
- Live Qwen status: standalone live API smoke passed; actual token usage recorded as
  memory=301, embedding=20, rerank=29.

## Demo Commands

```bash
PYTHONPATH=src python3 tools/build_demo_data.py
PYTHONPATH=src python3 tools/build_review_packet.py
PYTHONPATH=src python3 -m unittest discover -s tests -v
PYTHONPATH=src python3 -m recallpack.demo_server --host 127.0.0.1 --port 8789
```

Open:

```text
http://127.0.0.1:8789/
```

## Deployment Status

Credential-free Alibaba Cloud ECS runtime proof is running at:

```text
http://101.133.224.223/
```

It uses ECS + Docker + SQLite with fixed `deployment_replicas = 1` and
`application_workers = 1`. Judge smoke passed against the public URL.
