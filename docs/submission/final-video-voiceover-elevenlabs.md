# RecallPack Final Video Voiceover

Status: voiceover draft for ElevenLabs or manual narration. Do not upload or
submit from this file.

Target duration: about 2 minutes 30 seconds.

Suggested voice style: calm technical founder, medium pace, clear pauses.

## Voiceover Text

When a fresh coding agent takes over, something has already decided what it
gets to see. If that selection keeps a decision the project later reversed, the
agent may confidently write last week's code.

RecallPack is a MemoryAgent project for coding-agent handoffs. It moves the
staleness decision earlier: judge supersession at write time, when old and
reversing decisions are visible together before handoff budget selection.

Here is the project repo. It is a cleaned public submission bundle, with a
credential-free demo and judge commands that can run from a fresh clone.

Now I will show the failure RecallPack is designed to prevent. This is a
deterministic local replay, not a claim that every live retriever must fail.
The stored live raw-history embedding and rerank baseline selected the active
retry decision on this small fixture, so the live claim is lifecycle filtering,
not a measured baseline failure rate.

In this demo, an earlier session recorded an old retry strategy. Later, the
project replaced that strategy with a new one. A raw-history retrieval path can
still pull the old decision, because it is semantically similar to the current
task.

In the replay, that stale context leads a fresh coding agent to write the
wrong retry patch. The fixture tests show the result: the local deterministic
baseline passes only one out of three tests.

RecallPack treats this as a memory lifecycle problem, not just a retrieval
problem.

On observe, it turns ordered session events into durable memories. It remembers
project decisions and preferences. When a newer decision replaces an older one,
the older memory is marked superseded instead of staying equally valid.

On compile, RecallPack only retrieves active memories for the current goal. It
uses embedding top-N retrieval, rerank, and then a fixed budget selector to
produce a small handoff pack with provenance.

Here, the active pack includes the current retry decision and the project
preference to avoid new dependencies. The old retry policy is still preserved
as history, but it is no longer eligible for the handoff.

With that active memory pack, the local replay writes the correct patch. The
same fixture tests now pass three out of three.

The Qwen Cloud boundary is explicit.

The Qwen text model is used for memory decisions, type classification,
duplicate detection, and supersession judgment. `text-embedding-v4` retrieves
candidate memories, and `qwen3-rerank` improves precision before deterministic
code assembles the final budgeted pack.

The public demo remains credential-free. It uses deterministic local providers
for replay, and it displays sanitized trace evidence for the live Qwen path.
One stored live Qwen provider-path trace completed successfully once. This is
integration evidence, not statistical validation of live downstream
performance. A newer M98 live rerun is also checked in as failed evidence:
lifecycle filtering held, but the downstream patch-test delta did not
reproduce. No API keys or raw prompts are checked into the repo.

The important claim is not that RecallPack stores more context.

The claim is that it helps a coding agent remember which project memories are
still active, and avoid acting on decisions that have already been replaced.

That is the MemoryAgent value: stale-aware memory lifecycle, budgeted recall,
and a local downstream replay that makes the risk visible while the live traces
prove the lifecycle boundary.
