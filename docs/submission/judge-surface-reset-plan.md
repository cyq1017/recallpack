# M116 Judge Surface Reset Plan

Date: 2026-07-09

Status: M117/M118 local implementation complete. This document records the
decision boundary and remaining gates; it does not authorize push, deployment,
live Qwen reruns, video upload, or Devpost submission.

## Problem

RecallPack has strong local engineering evidence, but the judge-facing surface
is too hard to parse in five minutes.

Current issues:

- README starts with caveats before the product moment.
- Internal milestone names appear in README, Devpost copy, video script, review
  packet, and UI labels.
- The strongest caveat is correct but currently dominates the opening: the
  project-a local replay is authored and stored live raw-history baseline runs
  selected the active retry decision.
- The judge has to read too far before seeing the simple product claim:
  RecallPack prevents a fresh coding agent from receiving a project decision
  that has already been reversed.

## Reset Principle

Do not hide limits. Move them into one clear limits section after the judge
understands the product.

The first screen should answer four questions:

1. What breaks?
2. Why normal retrieval can fail before the agent reasons?
3. What does RecallPack do differently?
4. What evidence can I run now?

## New README Opening Shape

Target first screen:

````markdown
# RecallPack

RecallPack is a MemoryAgent runtime for coding-agent handoffs. It prevents a
fresh agent from acting on project memory that a later session already
superseded.

Ordinary retrieval ranks similar history; it does not know which decision is
still active. RecallPack observes session events, writes durable memory, marks
older decisions as superseded at write time, and compiles only active
task-relevant memory into a budgeted handoff pack.

In the local demo, stale raw-history context leads to the wrong patch and
failing fixture tests. RecallPack filters the superseded memory, keeps the
active decision, and the same temp-repo tests pass.

Run the judge smoke:

```bash
PYTHONPATH=src python3 tools/fresh_clone_smoke.py --source .
```

## Evidence At A Glance
...

## Limits
...
````

Notes:

- Remove all internal milestone labels from the public README opening.
- Keep Qwen model roles in one concise section.
- Keep live-run caveats in `Limits`, not in every paragraph.
- After M117, promote project-h only if it passes the unrigged scenario
  criteria. Until then, do not call project-a a natural retrieval failure.

## Devpost Pitch Reset

Target elevator pitch:

```text
RecallPack is a MemoryAgent runtime for coding-agent handoffs. It remembers
project decisions across sessions, marks superseded memory stale when newer
evidence arrives, and compiles only active task-relevant memory into a bounded
handoff pack. Qwen handles memory extraction, semantic retrieval, reranking,
and supersession judgment; deterministic runtime code enforces ordering,
lifecycle state, budget, provenance, and local verification.
```

Target "What it does" order:

1. One stale-memory failure story.
2. `/observe`: remember and supersede.
3. `/compile`: active-only retrieval under budget.
4. Qwen model roles.
5. Local evidence and limits.

Avoid:

- milestone names;
- "M98", "M104", "M113" in public narrative;
- long paragraphs explaining every historical remediation;
- claiming broad benchmark performance;
- saying live Qwen E2E passed unless the latest run being referenced actually
  passed.

## Video Opening Reset

Target first 30 seconds:

```text
This is the bug RecallPack targets: a coding agent can inherit an old project
decision that a later session already reversed. Retrieval can only reason over
the conflict if both sides fit in the handoff budget. RecallPack makes that
state explicit: observe events, remember decisions, mark older decisions
superseded, then compile only active memory for the next agent.
```

Screen order:

1. Baseline stale context card.
2. Active versus superseded memory timeline.
3. RecallPack pack showing only active decision.
4. Patch/test result.
5. Qwen model-role trace.

Do not start with:

- live-run caveats;
- public ECS status;
- bundle names;
- internal milestone names;
- every evidence boundary.

## Evidence Table Reset

Keep a compact table near the top:

| Claim | Evidence | Limit |
| --- | --- | --- |
| RecallPack stores memory lifecycle | `/observe`, SQLite lifecycle tests | MVP is single-process SQLite. |
| RecallPack excludes stale memory before recall | `/compile` tests and fixture evaluations | Local fixtures are not a broad benchmark. |
| Qwen is load-bearing in the intended path | adapters, sanitized trace, preflight | Public demo uses fake providers. |
| Downstream risk is testable | temp-repo patch/test evaluator | Local patch generation is deterministic. |
| ProjectOdyssey scenario is source-backed | public source pair and authored fixture | Not a production trace and not copied text. |

## P0 / P1 / P2 Surface Decisions

P0:

- Remove internal milestone labels from README, Devpost copy, and the video
  opening before final submission.
- Replace "project-a proves natural retriever failure" with "project-a is a
  deterministic failure replay".
- If M117 project-h passes, use project-h as the headline natural failure
  scenario.

P1:

- Put "Why coding agents cannot just solve this themselves" in the README and
  Devpost story:
  selection happens before the agent reasons, and stale exclusion should be
  auditable across sessions and agents.
- Keep Qwen load-bearing as model roles, not a vague badge:
  memory decision, embedding retrieval, rerank, supersession judgment.
- Add a one-paragraph "What to trust" section that separates local replay,
  source-backed scenario, and live provider-path evidence.

P2:

- Keep detailed milestone history in internal execution docs and the review
  packet appendix, not the public first screen.
- Keep blog polish after the project-h fixture and public-copy reset are done.

## M117/M118 Implementation Cut

M117 implemented the unrigged ProjectOdyssey fixture because the acceptance
criteria in `docs/submission/projectodyssey-dry-run.md` remained true.

M118 rewrote:

- `README.md`
- `docs/submission/devpost-final-copy.md`
- `docs/submission/demo-video-script.md`
- any UI label that exposes an internal milestone as the first thing a judge
  sees

M118 did not rewrite:

- internal execution history;
- detailed review packet appendices;
- stored trace artifacts.

## Remaining P0/P1 Risks

Closed locally:

- M117 gives the award headline an eight-fixture local surface with a
  source-backed ProjectOdyssey JIT scenario.
- M118 removes milestone-heavy wording from the public opening surface.

Remaining P1:

- Live Qwen baseline on the new ProjectOdyssey scenario remains gated and
  unrun.
- Deterministic downstream proof remains local, not a broad agent benchmark.
- Public repo synchronization and final video/Devpost submission remain manual
  gates.
