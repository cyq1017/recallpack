# RecallPack Media Assets

This folder is the staging location for Devpost screenshots and local video
candidates.

Local video candidate:

- `video-candidate/recallpack-demo-candidate.mp4` - 156-second local MP4
  candidate generated from current screenshots, captions, and macOS `say`
  voiceover.
- `video-candidate/manifest.json` - records duration, source scenes,
  `upload_performed=false`, and no Devpost video URL.

This candidate is not proof of upload and is not a Devpost video URL.

Local presentation deck:

- `recallpack-judge-deck.pptx` - six judge-facing slides covering the handoff
  risk, lifecycle mechanism, bounded evaluation evidence, Qwen Cloud boundary,
  and judge replay path. It passed a rendered-slide and OOXML privacy scan, but
  `upload_performed=false`.

Current M72 screenshot candidates:

- `m71-replay/01-one-click-stale-memory-replay.png` - One-click stale-memory
  failure replay with baseline stale context visible.
- `m71-replay/02-recallpack-active-memory-pack.png` - Recall view with the
  pipeline, baseline comparison, and PACK.md memory segment.
- `m71-replay/03-qwen-provider-evidence.png` - Evaluate view with Qwen provider
  evidence, live smoke status, token usage, and provider roles.
- `architecture-diagram.png` - 1280x720 Devpost architecture diagram upload
  candidate.
- `alibaba-cloud-deployment-proof-redacted.png` - 1280x720 Devpost Alibaba
  Cloud deployment proof upload candidate generated from the verified ECS smoke
  evidence with public endpoint and repo owner text redacted.
- `alibaba-cloud-deployment-proof.png` - source proof image retained only in the
  private workspace for local evidence; do not upload this unredacted file.
  Sanitized public bundles exclude it and keep only the redacted copy.

Known Devpost upload state:

- `architecture-diagram.png` and
  `alibaba-cloud-deployment-proof-redacted.png` were manually uploaded after
  local privacy checks.
- `docs/submission/devpost-upload-state.json` records that Devpost final submit
  was not performed. It also records the privacy-checked presentation PPT as
  not yet uploaded or linked.

Historical M55 screenshot candidates:

- `01-first-run-handoff-simulator.png` - First-screen handoff simulator with
  baseline 1/3 and RecallPack 3/3 visible.
- `02-recallpack-active-memory-pack.png` - Recall view with the pipeline,
  baseline comparison, and PACK.md memory segment.
- `03-qwen-provider-evidence.png` - Evaluate view with Qwen provider evidence,
  live smoke status, token usage, and provider roles.

Use `docs/submission/demo-media-package.md` as the capture plan before adding
or uploading media files. Any future media file should be checked for:

- no credentials or API keys;
- no personal names, account IDs, public IPs, or private repo/user identifiers
  unless intentionally redacted;
- no private local filesystem paths;
- no terminal history with secrets;
- no unredacted cloud console, billing, access-key, or dashboard screenshots;
- no claim that live Qwen E2E passed unless the gated rerun actually passes.

Recommended additional future filenames:

- `05-ecs-judge-smoke-proof.png`
