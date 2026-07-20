# RecallPack M53 Demo Media Package

Status: local video candidate generated; no video upload was performed and no
Devpost submission was made. One stored live Qwen provider-path trace records
`live_e2e_passed`; a fresh M98 rerun is checked in as `live_e2e_failed`, where
lifecycle filtering held but the downstream delta did not reproduce.

Recording target: 2:20-2:45.

Primary source script: `docs/submission/demo-video-script.md`.

Recording-day control packet: `docs/submission/video-production-packet.md`.
Recording rehearsal gate report: `docs/submission/recording-rehearsal-report.md`.
Local MP4 candidate: `docs/submission/media/video-candidate/recallpack-demo-candidate.mp4`.
Local presentation PPT: `docs/submission/media/recallpack-judge-deck.pptx`.
It contains six judge-facing slides and is not uploaded until the user confirms
the final Devpost field and media order.

## M66 Winner Narrative Polish

Recording goal: convert the local proof into a judge-visible story, not a
feature tour.

- By 20 seconds: state the write-time lifecycle advantage: old and reversing
  decisions are visible together before handoff budget selection.
- By 40 seconds: disclose the stored live boundary: lifecycle held, while live
  raw-history retrieval selected the active retry decision on this fixture.
- By 75 seconds: show baseline `1/3` fixture tests and RecallPack `3/3`
  fixture tests in the authored local replay.
- By 90 seconds: show active vs superseded memory and source IDs.
- Before the close: show Qwen model roles and the credential-free public demo
  boundary.
- Closing line: RecallPack prevents coding agents from acting on superseded
  project memory.

## Local Screenshot Gallery

Generated local Devpost screenshot candidates:

- `docs/submission/media/m71-replay/01-one-click-stale-memory-replay.png` - One-click stale-memory failure replay.
- `docs/submission/media/m71-replay/02-recallpack-active-memory-pack.png` - RecallPack active memory pack.
- `docs/submission/media/m71-replay/03-qwen-provider-evidence.png` - Qwen provider evidence.

The older M55 root-level PNGs are retained as historical assets. Use the
`m71-replay/` gallery for final Devpost image upload because it matches the
current first-screen product moment.

Capture details:

- source: local demo server at `http://127.0.0.1:8789/`;
- viewport: 1280x720;
- capture tool: local Chrome headless screenshot;
- status: screenshots generated locally; no media upload was performed.

Regenerate screenshots while the local demo server is running:

```bash
python3 tools/capture_demo_screenshots.py --url http://127.0.0.1:8789
```

The capture tool accepts only local demo hosts (`127.0.0.1`, `localhost`, or
`::1`) and does not upload media.

List the capture plan without requiring Chrome or a running server:

```bash
python3 tools/capture_demo_screenshots.py --list
```

## Opening Frame

Open on the Learn view with the deterministic stale-memory failure replay
visible.

The first visible message should be:

- local baseline stale context -> wrong retry patch -> 1/3 fixture tests;
- RecallPack active memory -> correct retry patch -> 3/3 fixture tests.

Do not start with architecture, test logs, or repository files.

## Shot List

| Time | Screen | Narration job | Must show |
| --- | --- | --- | --- |
| 0:00-0:20 | Evidence Boundary / lifecycle | State write-time information advantage. | write-time lifecycle state |
| 0:20-0:40 | Stored live boundary | Disclose lifecycle held and live raw-history retrieval selected active. | live baseline disclosure |
| 0:40-1:15 | Deterministic stale-memory failure replay | Show authored failure-class replay. | 1/3 and 3/3 fixture tests |
| 1:15-1:35 | Active/superseded memory | Explain remember, supersede, recall. | RecallPack active memory |
| 1:35-2:05 | Qwen Provider Integration Evidence | Separate model work from deterministic runtime. | Qwen text model, text-embedding-v4, qwen3-rerank |
| 2:05-2:25 | Architecture Diagram | Show system flow and boundaries. | Browser demo, SQLite, Qwen roles, Budget selector |
| 2:25-2:45 | ECS / judge commands | Close with runability and deployment proof. | Alibaba Cloud ECS, judge smoke command |

## Image Gallery Candidates

Use these as Devpost gallery screenshots:

1. First-screen hero proof: deterministic stale-memory failure replay showing
   local baseline 1/3 and RecallPack 3/3.
2. Recall view: active vs superseded memory, selected source IDs, and pack
   provenance.
3. Qwen Provider Integration Evidence: Qwen text model, text-embedding-v4,
   qwen3-rerank, and deterministic runtime split.
4. Architecture Diagram: `docs/submission/architecture-diagram.md` rendered as
   a readable diagram, or `docs/submission/media/architecture-diagram.png` for
   the required Devpost architecture upload.
5. ECS proof: `docs/deployment/alibaba-cloud-proof.md` or running public URL
   with judge smoke result. The Devpost upload candidate is the privacy-checked
   redacted image
   `docs/submission/media/alibaba-cloud-deployment-proof-redacted.png`; keep
   the unredacted source PNG local-only.

## Local Video Candidate Boundary

The repository now includes a local MP4 candidate generated from the current
M71 screenshots, captions, and macOS `say` voiceover. It is useful for review
and upload preparation, but it is not a Devpost video URL and does not prove
that any video was uploaded.

Generation constraints:

- local file: `docs/submission/media/video-candidate/recallpack-demo-candidate.mp4`;
- duration: 156 seconds;
- resolution: 1280x720;
- audio: generated locally with macOS `say`;
- upload_performed: false.

Do not claim a final Devpost video link exists until the candidate is actually
uploaded to an accepted video host or Devpost-compatible link.
Do not imply the public demo endpoint performs live Qwen calls; it is a
credential-free deterministic runtime that displays the sanitized live trace
evidence.

## Capture Steps

1. Start the backend:

   ```bash
   PYTHONPATH=src python3 -m recallpack.demo_server --host 127.0.0.1 --port 8789
   ```

2. Run judge smoke:

   ```bash
   python3 tools/judge_smoke.py --url http://127.0.0.1:8789
   ```

3. Open:

   ```text
   http://127.0.0.1:8789/
   ```

4. Either review/upload the local MP4 candidate or record a replacement video
   using the shot list above.

5. Stop the backend after recording.

## Acceptance Checklist

- [ ] Video length is between 2:20 and 2:45.
- [ ] Opening frame shows the deterministic stale-memory failure replay.
- [ ] Local baseline stale context and 1/3 fixture tests appear in the first 40 seconds.
- [ ] RecallPack active memory and 3/3 fixture tests appear before 1:35.
- [ ] Qwen Provider Integration Evidence appears before 2:05.
- [ ] Architecture Diagram appears before the closing section.
- [ ] Alibaba Cloud ECS proof or judge smoke command appears before the close.
- [ ] The voiceover says "MemoryAgent, not generic RAG."
- [ ] The voiceover says the local demo is credential-free.
- [ ] The voiceover says one stored live Qwen provider-path trace completed
      successfully once, while the public/local demo remains credential-free
      and the fresh M98 rerun is not claimed as passing.
- [ ] No credentials, private paths, raw API key, or terminal secrets appear on screen.

## Recording-Day Checklist

Run these immediately before recording:

```bash
PYTHONPATH=src python3 tools/judge_smoke.py --url http://101.133.224.223 --timeout 15
```

Then confirm:

- the first viewport shows baseline `1/3` and RecallPack `3/3`;
- the video does not imply the public demo endpoint performs live Qwen calls;
- `session-a:turn-004`, if shown, is described as supporting retry-failure
  evidence rather than required memory;
- the eight fixtures are described as curated lifecycle fixtures, not a broad
  benchmark.

## Devpost Media Copy

Recommended caption for the first screenshot:

```text
RecallPack first-run handoff simulator: stale baseline context fails fixture
tests, while active lifecycle memory produces the passing patch.
```

Recommended caption for the architecture screenshot:

```text
RecallPack architecture: deterministic lifecycle runtime with live-gated Qwen
text, embedding, and rerank roles.
```
