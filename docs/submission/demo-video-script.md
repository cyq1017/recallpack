# RecallPack 3-Minute Demo Video Script

Target length: 2:20-2:45.

Recording truth boundary: the first 20 seconds must show the product problem,
not the internal evidence history. Start with stale project memory reaching a
fresh coding agent, then show RecallPack's write-time lifecycle fix. The local
demo remains credential-free and uses deterministic fake providers through the
same trace contract. Stored live Qwen traces are integration evidence, not
statistical validation of downstream live performance.

## Recording Setup

- Open the deployed or local demo first screen.
- Keep the first viewport on the Evidence Boundary plus deterministic replay.
- Have the Recall and Evaluate tabs ready.
- Have `docs/submission/review-packet.md` open only if a quick evidence cutaway
  is needed.

## Script

### 0:00-0:20 - Problem And Write-Time Advantage

Voiceover:

When a fresh coding agent takes over, something has already decided what it
gets to see. If selection keeps a decision the project later reversed, the
agent may confidently write last week's code. Retrieval can recover only when
the reversing decision also survives the budget. RecallPack moves the decision
earlier: it judges supersession at write time, when both the old decision and
the reversal are visible together, then stores that lifecycle state.

Screen:

- Show the Evidence Boundary.
- Point at active versus superseded memory.

### 0:20-0:40 - Stored Live Evidence Boundary

Voiceover:

The stored live Qwen evidence supports that lifecycle boundary. In stored live
RecallPack runs, stale retry memory was excluded and active retry memory was
selected. The stored raw-history embedding plus rerank baseline actually picked
the active decision on this tiny fixture, so the live claim is not "retrieval
always fails." The claim is that stale exclusion becomes an auditable memory
property.

Screen:

- Show Qwen status lines and Evidence Boundary.
- Mention one stored pass and one failed fresh rerun if visible.

### 0:40-1:15 - Authored Local Failure-Class Replay

Voiceover:

This local replay is an authored deterministic illustration of the failure
class. The raw-history fake-embedding baseline keeps the old retry policy,
writes the wrong patch, and the fixture tests pass only 1/3. RecallPack filters
that superseded memory, keeps the active retry decision and no-new-dependencies
preference, and the same fixture tests pass 3/3.

Screen:

- Show deterministic stale-memory failure replay.
- Show `1/3 fixture tests` and `3/3 fixture tests`.
- Say source IDs: stale `session-a:turn-001`, active `session-a:turn-005`, and
  preference `session-a:turn-003`.

### 1:15-1:35 - RecallPack Memory Lifecycle

Voiceover:

RecallPack observes ordered session events as lifecycle operations. It
remembers decisions and preferences, supersedes the old retry policy, and
keeps active memory separate from stale history before `/compile` ranks and
budgets the final pack.

Screen:

- Show RecallPack patch/test card.
- Show active vs superseded memory states.
- Show the eight-fixture summary if visible.

### 1:35-2:05 - Qwen And Deterministic Runtime Boundary

Voiceover:

The intended Qwen Cloud path has three model roles. In stored live runs, the
Qwen text model handled memory decisions and supersession judgments.
text-embedding-v4 retrieved memory candidates. qwen3-rerank improved precision
before deterministic code assembled the budgeted pack.

The local demo stays credential-free, so it uses deterministic fake providers
through the same provider trace contract. The repository also includes a
stored sanitized live Qwen provider-path trace showing the intended model path
completed successfully once. A newer live rerun is also checked in as failed
evidence: lifecycle filtering still held, but the downstream 3/3 delta did not
reproduce. That is why the headline is structural stale exclusion, not
guaranteed live downstream performance.

Screen:

- Show Qwen Provider Integration Evidence.
- Show model work vs deterministic runtime work.
- Show `text-embedding-v4`, `qwen3-rerank`, and `Qwen text model`.

### 2:05-2:30 - Deployment And Judge Run Path

Voiceover:

RecallPack also includes judge-run evidence: a credential-free Alibaba Cloud
ECS runtime proof, fresh-clone smoke, Docker proof, and a public-repo-ready
sanitized bundle. A judge can run the repo without credentials and reproduce the local
MemoryAgent proof.

Screen:

- Show Alibaba Cloud ECS deployment status or review packet line.
- Show `python3 tools/judge_smoke.py --url ...` if there is time.
- Mention public repo and video links will be on Devpost.

### 2:30-2:45 - Close

Voiceover:

RecallPack makes stale-decision exclusion a structural property of project
memory. It turns raw history into an active, stale-aware handoff pack. The
result is not better RAG; it prevents a fresh coding agent from receiving a
decision the project already reversed.

Screen:

- End on active versus superseded memory and the local replay scores.

## Must-Say Lines

- "MemoryAgent, not generic RAG."
- "A coding agent can resolve stale context only if the reversing decision is also selected."
- "RecallPack judges supersession at write time, while both decisions are visible."
- "Stored live Qwen runs support lifecycle filtering, not a live failure-rate claim."
- "RecallPack prevents coding agents from acting on superseded project memory."
- "RecallPack is not better RAG; it prevents agents from acting on superseded memory."
- "Local deterministic replay baseline stale context passes 1/3 fixture tests."
- "RecallPack active memory passes 3/3 fixture tests."
- "Qwen text model, text-embedding-v4, and qwen3-rerank are the intended model
  roles."
- "The local demo is credential-free and uses deterministic fake providers."
- "One stored live Qwen provider-path trace completed successfully once; the
  public demo is still a credential-free deterministic runtime."
- "The fresh live rerun is failed evidence: lifecycle held, downstream
  delta did not reproduce."

## Avoid

- Do not start with architecture.
- Do not spend more than 20 seconds on tests before showing the wrong patch.
- Do not imply the public demo endpoint performs live Qwen calls.
- Do not imply raw full history is the fair budget baseline.
- Do not imply the local replay is a fresh live-Qwen result.
- Do not imply live raw-history retrieval selected stale memory on this fixture.
- Do not claim broad benchmark coverage beyond eight curated lifecycle fixtures.
- Do not imply the public ECS endpoint performs live Qwen calls.
- Do not show exact live source IDs unless you explain `turn-004` as supporting
  failure evidence.
