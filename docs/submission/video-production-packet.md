# RecallPack M68 Video Production Packet

Status: local-only recording control packet. No video upload is performed by
this file.

Recording lock: 2:20-2:45.

Primary script: `docs/submission/demo-video-script.md`.

## Preflight

Run these before opening the recorder:

```bash
PYTHONPATH=src python3 tools/judge_smoke.py --url http://101.133.224.223 --timeout 15
python3 tools/devpost_preflight.py
python3 tools/final_submission_gate.py
```

Confirm the local package still reports:

- Write-time lifecycle claim is the headline; local 1/3 vs 3/3 is labeled as
  an authored deterministic replay.
- RecallPack active memory passes 3/3 fixture tests in the same local replay.
- Stored live Qwen provider-path trace has `live_qwen_e2e_status=live_e2e_passed`.
- Stored live raw-history embedding+rerank baseline traces selected the active
  retry decision and did not reproduce the local stale-context failure.
- Fresh M98 live rerun is stored as failed evidence: lifecycle filtering held,
  but the downstream delta did not reproduce. Do not present it as a passing run.
- No public action was performed by local tools.

## One-Take Run Of Show

| Time | Screen | Narration objective | Hard stop |
| --- | --- | --- | --- |
| 0:00-0:20 | Evidence Boundary / lifecycle | State write-time information advantage: old and reversing decisions are visible together before handoff budget selection. | Say "write time" and "lifecycle state" before 0:20. |
| 0:20-0:40 | Qwen/live boundary | Disclose stored live evidence: lifecycle held; live baseline did not fail on this fixture. | Do not imply live retrieval selected stale memory. |
| 0:40-1:15 | Deterministic stale-memory failure replay | Show the authored local failure-class replay: stale context 1/3, RecallPack 3/3. | Say "authored deterministic replay" and "fixture tests". |
| 1:15-1:30 | Active vs superseded memory | Explain remember, supersede, recall. | Say active `turn-005` and preference `turn-003`. |
| 1:30-2:05 | Qwen Provider Integration Evidence | Separate Qwen model work from deterministic runtime work. | Name Qwen text model, text-embedding-v4, qwen3-rerank. |
| 2:05-2:35 | Architecture / ECS / judge commands | Show runability and proof surface. | Keep public ECS credential-free; do not imply live Qwen runs there. |
| 2:35-2:45 | Closing first screen | Repeat lifecycle claim. | End on stale-decision exclusion, not live benchmark superiority. |

## Voiceover Anchors

- "MemoryAgent, not generic RAG."
- "When a fresh coding agent takes over, something has already decided what it
  gets to see."
- "RecallPack judges supersession at write time, while both decisions are
  visible together."
- "Stored live Qwen runs support lifecycle filtering; the local 1/3 versus 3/3
  replay is an authored mechanism demonstration."
- "If a coding agent receives an old project decision, it may confidently write
  the wrong patch."
- "Local deterministic replay baseline stale context passes 1/3 fixture tests."
- "RecallPack active memory passes 3/3 fixture tests."
- "The local demo is credential-free and uses deterministic fake providers."
- "The stored live Qwen provider-path trace completed successfully once, but
  the public demo endpoint remains credential-free."
- "The fresh M98 live rerun is checked in as failed evidence: lifecycle held,
  but the downstream delta did not reproduce."

## Retake Triggers

Retake the video if any of these happen:

- the first 15 seconds do not mention stale project memory causing a wrong
  patch or the write-time lifecycle advantage;
- the first 40 seconds imply live raw-history retrieval selected stale memory;
- RecallPack 3/3 appears after 1:35;
- Qwen model roles are skipped;
- the narration implies the public demo endpoint performs live Qwen calls;
- the narration implies the local replay is a fresh live Qwen run;
- the narration implies eight fixtures are a broad benchmark;
- local filesystem paths, credentials, API keys, private terminal history, or
  raw tokens appear on screen;
- the video exceeds 2:45.

## On-Screen No-Go List

- Do not show Qwen API keys, environment variables, SSH key paths, terminal
  history with secrets, or cloud console credentials.
- Do not imply the public demo endpoint performs live Qwen calls.
- Do not imply the public ECS endpoint performs live Qwen calls.
- Do not imply live raw-history retrieval selected stale memory.
- Do not show raw workspace paths as the public submission source.
- Do not call the eight curated fixtures a broad benchmark.

## Upload Package

Prepare these manually after recording:

- final video URL or upload;
- local MP4 candidate for review/upload:
  `docs/submission/media/video-candidate/recallpack-demo-candidate.mp4`;
- three image gallery screenshots from `docs/submission/media/m71-replay/`;
- public GitHub repository URL: https://github.com/cyq1017/recallpack;
- Devpost project story from `docs/submission/devpost-final-copy.md`;
- optional blog draft from `docs/submission/blog-post-draft.md`.

Do not upload from this repo. Upload is a manual Devpost action after the user
approves the final media order.

## Final Self-Check

Before putting the video URL into Devpost, answer yes to all:

- The first frame is the deterministic stale-memory failure replay.
- The local MP4 candidate, if used, has been reviewed for audio, captions, and
  no private paths before upload.
- Baseline 1/3 and RecallPack 3/3 are visible without deep scrolling.
- Qwen provider roles are visible and not overstated.
- Public ECS is described as the M104 credential-free runtime from the prior
  verified 7/4 sanitized bundle.
- Public ECS judge smoke is described as passing after the M104 redeploy; do
  not claim the latest 7/7 local bundle is deployed without another redeploy.
- latest local package is described as the current local package.
- latest bundle is described as the current local package.
- M98 remains the current evidence snapshot after adversarial review, not an
  older M88/M90 package label.
- Fresh M98 live rerun is stored as failed evidence; do not call it unrun,
  gated, or passing.
- The closing line is about memory lifecycle making stale exclusion structural.

Current gallery: `docs/submission/media/m71-replay/`.

M72 note: the current M71 replay screenshots were generated non-destructively
under `m71-replay/`; the older M55 root-level PNGs remain only as historical
assets.
