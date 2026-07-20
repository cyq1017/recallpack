# Why Coding Agents Need Memory Lifecycle, Not More Context

Draft status: ready for manual blog/social editing. This file does not publish
anything and does not authorize Devpost submission.

Target prize: Qwen Cloud Hackathon Blog Post Award.

## Thesis

More context can make coding agents worse when the context contains stale
project decisions. A coding agent can resolve stale context if the reversing
decision is selected too. The fragile step is earlier: budgeted handoff
selection decides what the agent gets before it reasons. A coding agent does
not only need memory that retrieves similar text. It needs memory that knows
whether a decision is still active.

RecallPack is a MemoryAgent project built around that claim. It gives project
memory a lifecycle: remember, supersede, and recall. The goal is narrow:
prevent a fresh coding agent from acting on superseded project memory during a
handoff.

## The Failure Mode

Imagine a project where an early session says:

- use three retry attempts with a fixed 100 ms delay.

Later, tests show that this policy is too short for rate limits, and the user
replaces it:

- use five attempts with exponential backoff.

A normal retrieval system may still pull the old policy because it is
semantically similar to the current task, especially in a constrained handoff
pack. In RecallPack's deterministic hero replay, that stale-context baseline
passes only 1/3 fixture downstream tests.

The issue is not missing context. The issue is context without lifecycle state.

## What RecallPack Does

RecallPack has two runtime paths:

- `/observe` processes ordered session events and writes durable memories.
- `/compile` recalls only active task-relevant memories under a fixed handoff
  budget.

Each memory carries provenance, scope, status, and lifecycle state. When a
newer decision replaces an older one, the old memory becomes superseded before
recall. That means stale memory is filtered before embedding retrieval and
rerank.

The local replay result in the hero demo is simple:

- stale raw-history baseline: 1/3 fixture tests;
- RecallPack active memory pack: 3/3 fixture tests.

The project includes eight curated lifecycle fixtures: retry policy, config
loader behavior, cache policy, audit serialization, pagination policy,
API-client auth migration, provider auth-header mode, and a source-backed
ProjectOdyssey JIT policy scenario. This is not a broad benchmark. It is local
evidence for the same mechanism across several stale memory patterns.

## How Qwen Is Load-Bearing

RecallPack uses Qwen Cloud for model work and keeps deterministic runtime work
in normal code.

- Qwen text model: memory extraction, classification, duplicate detection, and
  supersession judgment.
- `text-embedding-v4`: retrieval over active memory candidates.
- `qwen3-rerank`: precision ranking before budget selection.

The runtime handles ordered event processing, SQLite lifecycle writes, budget
selection, pack assembly, and reproducible local evaluation.

The public demo is credential-free. It uses deterministic fake providers
through the same trace contract so judges can run it locally or on the public
ECS endpoint without secrets. The repository also includes a sanitized approved
live Qwen E2E trace with `live_e2e_passed`. That trace records memory decision,
embedding, rerank, and patch-generation evidence without credentials, raw
prompts, raw memories, or tool arguments.

A fresh M98 live rerun is also checked in as failed evidence: lifecycle
filtering held, but the downstream 3/3 delta did not reproduce. That is why the
strongest claim is structural stale-decision exclusion, not that every live
retriever will fail the same way as the deterministic replay.

## What We Learned

For coding agents, memory quality is not just retrieval quality. The agent
needs to know whether a remembered decision is current, superseded, scoped to
the task, and backed by evidence.

That is why RecallPack is not better RAG. It is a memory lifecycle layer for
coding-agent handoffs.

## Next

The next useful step is not adding more demo features. It is testing the same
lifecycle contract against broader external project histories and real coding
agent handoff logs.

Until then, RecallPack makes a narrower hackathon claim: when stale project
memory is the failure mode, lifecycle-aware recall can stop a coding agent from
acting on an obsolete decision.
