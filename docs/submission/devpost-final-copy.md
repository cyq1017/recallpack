# RecallPack Devpost Final Copy

This file is copy-ready submission text. It does not authorize public repo
push, public deployment, live Qwen reruns, or hackathon submission.

## Elevator Pitch

RecallPack is a MemoryAgent project that keeps coding-agent handoffs from
acting on stale project memory. In stored live runs, Qwen judged supersession at
write time, when old and new decisions were both visible; the credential-free
local demo replays deterministic provider-compatible deciders. `/compile` then
packs only active task-relevant memories for a fresh coding agent.

## Tagline

Stale-aware memory lifecycle for coding-agent handoffs.

## Project Story

### Inspiration

More context can make a coding agent worse when old decisions are stale.
Coding agents can reason over conflicts when both sides of the conflict are in
context. The handoff problem is earlier: under a budget, retrieval chooses what
the next agent receives. If the newer decision that reversed an old policy is
omitted, the stale instruction just looks like project policy.

RecallPack was built to make memory lifecycle first-class: remember useful
project decisions, supersede stale ones while the evidence is still visible in
the session stream, and recall only active memories that fit the current goal
and budget.

The project is intentionally narrow: it is not a generic agent platform or a
generic RAG layer. It focuses on one MemoryAgent problem for coding-agent
handoffs: preventing agents from acting on superseded project memory.

### Why coding agents still need RecallPack

Modern coding agents are good at resolving contradictions after both sides are
in context. The failure RecallPack targets happens before that reasoning step:
under a handoff budget, retrieval has already decided what the fresh agent sees.
If the active reversal is omitted, the stale decision looks authoritative.

RecallPack makes that pre-reasoning selection safer by storing lifecycle state
at write time. The next agent receives an active memory pack instead of raw
history with stale decisions mixed in.

### What It Does

RecallPack has two runtime paths:

- `/observe` ingests ordered session events and writes durable memory records
  such as decisions, preferences, and lessons.
- `/compile` retrieves active memory candidates for a goal, applies embedding
  top-N retrieval, reranks candidates, and selects a bounded handoff pack with
  provenance.

The demo shows three variants side by side:

- raw full-history reference: all 12 events, not budget-comparable;
- keyword-scored fake-embedding + rerank raw-history baseline: selected from
  raw event text and reranked before top-k selection; it is not source-picked
  from gold selected-source IDs, but its deterministic scoring terms are
  fixture-authored for local replay;
- RecallPack: active lifecycle-aware memory recall.

The first screen starts with the evidence boundary and a deterministic
stale-memory failure replay: stale context is selected, the scripted local
baseline writes the wrong retry patch, fixture tests show 1/3, RecallPack
compiles the active memory pack, and the corrected patch passes 3/3. A
first-run handoff simulator below it summarizes the same fresh-agent handoff.
The replay is credential-free local evidence of a failure class, not a claim
that live retrieval always picks the stale item.

In the hero proof, the local keyword-scored fake-embedding + rerank
raw-history baseline recalls a superseded retry decision and produces the wrong
retry patch. It passes 1/3 fixture downstream tests. RecallPack filters the
stale decision, includes the active retry decision plus the dependency-free
preference, and passes 3/3 fixture downstream tests. The live Qwen evidence is
reported separately and disclosed first: two stored live raw-history
embedding+rerank baseline runs selected the active retry decision and did not
select the stale retry decision; stored live RecallPack runs held lifecycle
filtering; and the downstream live patch-generation delta has one historical
pass, one failed retry-policy rerun, and one passing ProjectOdyssey live run. In
the latest ProjectOdyssey live trace, Qwen selected the required active sources,
excluded the stale policy, and the RecallPack live-generated patch passed 3/3
fixture tests while the live raw-history baseline passed 1/3. This is
source-backed fixture integration evidence, not statistical validation of live
downstream performance.

The proof includes eight curated lifecycle regression fixtures: retry policy,
config loader, cache policy, audit serializer, a non-isomorphic pagination
fixture, a realistic API-client auth migration fixture, a source-backed AI
provider auth-header fixture inspired by public gateway/provider header
failures, and a source-backed ProjectOdyssey JIT fixture. They are designed to
test stale-memory handling behaviors, not to act as a broad benchmark. In each
fixture, keyword-scored fake-embedding + rerank
raw-history context keeps a superseded decision and passes only 1/3 downstream
fixture tests in the local deterministic replay environment. RecallPack
selects active memory and passes 3/3 fixture tests with the same local
temp-repo evaluator contract.

### How It Uses Qwen Cloud

RecallPack includes Qwen Cloud provider integration evidence for the intended provider path:

- Qwen text model: memory extraction, type classification, duplicate
  detection, and supersession judgment.
- Current Qwen text adapter: OpenAI-compatible `tools/tool_choice` contract with
  default model `qwen3.7-plus-2026-05-26`.
- `text-embedding-v4`: candidate memory retrieval in the stored live E2E trace
  and provider contract.
- `qwen3-rerank`: precision improvement over embedding top-N candidates.
- Gated downstream patch generation uses the same Qwen text-provider
  `tools/tool_choice` contract; the checked-in sanitized traces record one
  historical provider-path run that completed successfully, one failed
  retry-policy rerun, and one passing ProjectOdyssey source-backed fixture run.
  Local tests remain credential-free.

Deterministic application code handles ordered event processing, lease/CAS
storage behavior, lifecycle state writes, token budgeting, pack assembly, and
fixture-backed local verification.

The local demo displays standalone live API smoke passed, meaning the repo
contains a sanitized approved trace for memory_decision, embedding, and rerank.
The checked-in demo and unit tests do not read credentials or make live Qwen
calls.

### How We Built It

RecallPack is a small Python standard-library backend with a static demo UI:

- SQLite-backed event and memory lifecycle storage.
- Provider adapters for fake/local testing and live Qwen contract checks.
- A deterministic lifecycle-regression fixture evaluator with a local context-keyed
  patch-generation provider. The provider receives goal, selected context, and
  allowed edit paths, then validates generated patches with fixture tests in a
  temporary repo. It does not read gold patch variants.
- A 32-event behavior contract fixture suite that checks memory-operation
  behavior and stale-selection risk.
- A sanitized public bundle builder that excludes internal execution notes,
  generated caches, local machine paths, and credentials.
- A Docker target for an Alibaba Cloud ECS-style runtime proof.

### Challenges

The hardest part was making the comparison honest. Raw full history is useful
as a coverage reference, but it is not budget-comparable. The local baseline is
a keyword-scored fake-embedding + rerank raw-history path over raw events, and
its deterministic scoring terms are fixture-authored so the demo replay is
reproducible. RecallPack uses active memory lifecycle state before rerank and
budget selection. Both the baseline and RecallPack route through the same
local context-keyed patch provider, so the downstream proof no longer reads
gold patch variants. The live `text-embedding-v4`, `qwen3-rerank`, and Qwen
patch-generation evidence is the stored sanitized E2E trace, the failed
retry-policy rerun, and the passing ProjectOdyssey source-backed fixture rerun.
The stored live raw-history embedding+rerank baseline traces selected
the active retry decision on this small fixture, so RecallPack does not claim a
measured live baseline failure rate. The retry-policy rerun is recorded separately as
`live-qwen-m98-rerun-trace.json`; it completed the live observe/compile path
but the live patch-generation proof did not pass 3/3 for RecallPack. The
ProjectOdyssey rerun is recorded as
`projectodyssey-live-qwen-e2e-trace.json`; it selected both required active
sources, excluded the stale JIT policy, and RecallPack live patch generation
passed 3/3 fixture tests. The failed retry-policy trace remains stored as failed evidence
and is not presented as a passing rerun.

Another challenge was making Qwen Cloud provider evidence visible without
making local tests fragile. The solution is a strict provider trace contract:
fake providers emit the same sanitized trace shape as live providers, and the
one approved live contract trace is stored without credentials, raw prompts,
raw memories, or tool arguments.

For the public local backend, `/compile` uses deterministic keyword fake
embedding/rerank providers through that same contract. This keeps the demo
credential-free while avoiding zero-vector or identity-rerank smoke behavior.
We also added and ran a gated live Qwen E2E runner for the hero
observe/compile lifecycle. The stored live provider-path trace records
`live_e2e_passed`: Qwen handled memory decisions, `text-embedding-v4` handled
retrieval, `qwen3-rerank` handled precision ranking, and the intended live
patch-generation path completed successfully once. No credentials, raw prompts,
raw memories, or tool arguments are recorded in that trace. The live runner now
reports baseline failure instead of requiring it for pass status, and the
raw-history baseline context is derived from embedding/rerank retrieval. The
fresh retry-policy rerun result is `live_e2e_failed`: lifecycle filtering held, but the
downstream pass-rate delta did not reproduce. The latest ProjectOdyssey live
run is `live_e2e_passed`: live Qwen selected
`session-h-current:turn-006` and `session-h-history:turn-004`, excluded the
stale policy, and RecallPack live patch generation passed 3/3 ProjectOdyssey
fixture tests. The stored passing traces demonstrate provider-path integration;
the failed retry-policy rerun demonstrates that live downstream reproducibility still
needs careful fixture-by-fixture validation; and the live baseline traces show
retrieval can get the small retry fixture right without RecallPack.

### What We Learned

Memory quality is not just retrieval quality. For coding agents, memory needs a
lifecycle: active, superseded, and provenance-backed. A stale memory
can be more harmful than no memory when it drives code edits.

### Limits

- Broad coding benchmark improvement.
- Universal retrieval superiority.
- Guaranteed live Qwen downstream success.
- Replacement for coding-agent reasoning.

### What Is Next

The public repository URL is recorded as
`https://github.com/cyq1017/recallpack`. The local preflight validates the
sanitized bundle but does not prove the remote repository contains the latest
bundle, so the public clone should be rechecked before final submission. The
remaining gated steps are final presentation PPT upload/link, final demo
video/media upload, and final hackathon submission. A future live Qwen
benchmark should only be claimed after
additional independent scenarios pass, not from a single stored fixture run.

Credential-free Alibaba Cloud ECS runtime proof is running at
`http://101.133.224.223/` and passed the project judge smoke script.

## Built With

- Python 3 standard library
- SQLite
- JavaScript, HTML, CSS
- Docker
- Alibaba Cloud ECS target design
- Qwen text model
- `text-embedding-v4`
- `qwen3-rerank`

## Which AI tools Have You Leveraged?

AI tools were used for strategy review, coding assistance, test planning,
documentation drafting, and local verification support. The project itself uses
Qwen Cloud capabilities in the memory decision, embedding retrieval, and rerank
provider path, with sanitized trace evidence checked into the repo.

## Video Demo Script

See also: Demo Media Package in `docs/submission/demo-media-package.md`.

1. Open the local demo first screen.
2. State the MemoryAgent claim: stale-aware memory lifecycle for coding-agent
   handoffs.
3. Show the three first-screen cards: raw full-history reference,
   keyword-scored fake-embedding + rerank raw-history baseline, and RecallPack.
4. Show the local deterministic replay: stale context can lead to 1/3 fixture
   tests, while RecallPack active memory passes 3/3 in curated lifecycle
   scenarios.
5. Point to the `/compile` path: local fake embedding top-N -> fake
   qwen3-rerank-shaped rerank -> estimated 512-token serialized-memory budget
   selector; live model evidence is the stored E2E trace.
6. Open Evaluate and show Qwen Provider Integration Evidence plus the
   deterministic runtime work split.
7. End with the safety boundary: local and public demos use sanitized trace
   evidence, no credentials are required, and final video/submission remain
   gated.

## Recommended Project Media

- First image: screenshot of the first-screen hero proof with baseline 1/3 and
  RecallPack 3/3.
- Second image: screenshot of the Qwen Provider Integration Evidence section.
- Third image: screenshot of the downstream patch/test proof in the Recall tab.

## Judge Run Commands

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
PYTHONPATH=src python3 -m recallpack.demo_server --host 127.0.0.1 --port 8789
```

Open:

```text
http://127.0.0.1:8789/
```
