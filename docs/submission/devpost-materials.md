# RecallPack Devpost Materials Export

Local-only export for manual Devpost copy/paste.
This export does not perform public actions; it records any known prior manual uploads.

Status: blocked_gated_actions
Project name: RecallPack
Track: MemoryAgent
Tagline: Stale-aware memory lifecycle for coding-agent handoffs.

## Elevator Pitch

RecallPack is a MemoryAgent project that keeps coding-agent handoffs from
acting on stale project memory. In stored live runs, Qwen judged supersession at
write time, when old and new decisions were both visible; the credential-free
local demo replays deterministic provider-compatible deciders. `/compile` then
packs only active task-relevant memories for a fresh coding agent.

## Short Description

RecallPack helps a coding agent carry useful project memory across sessions
without leaking stale decisions into the next handoff. It observes ordered
session events, writes durable project memories, marks older memories as
superseded through lifecycle edges, and compiles only active task-relevant
memory into an estimated 512-token serialized-memory pack.

## Built With

- Python 3 standard library
- SQLite
- JavaScript, HTML, CSS
- Docker
- Alibaba Cloud ECS target design
- Qwen text model
- text-embedding-v4
- qwen3-rerank

## Which AI Tools

AI tools were used for strategy review, coding assistance, test planning,
documentation drafting, and local verification support. The project itself uses
Qwen Cloud capabilities in the memory decision, embedding retrieval, and rerank
provider path, with sanitized trace evidence checked into the repo.

## Media Assets

- 01-one-click-stale-memory-replay.png (1280x720, 99388 bytes) - docs/submission/media/m71-replay/01-one-click-stale-memory-replay.png
- 02-recallpack-active-memory-pack.png (1280x720, 78909 bytes) - docs/submission/media/m71-replay/02-recallpack-active-memory-pack.png
- 03-qwen-provider-evidence.png (1280x720, 72774 bytes) - docs/submission/media/m71-replay/03-qwen-provider-evidence.png

## Required Devpost File Upload Candidates

- architecture-diagram.png (1280x720, 107290 bytes, upload_performed=true, privacy_checked=true) - docs/submission/media/architecture-diagram.png
- alibaba-cloud-deployment-proof-redacted.png (1280x720, 111486 bytes, upload_performed=true, privacy_checked=true) - docs/submission/media/alibaba-cloud-deployment-proof-redacted.png

## Known Devpost Upload State

- Status: additional_info_media_uploaded
- Final submit performed: false
- Uploaded: architecture-diagram.png -> Architecture Diagram (privacy_checked=true, redacted=false)
- Uploaded: alibaba-cloud-deployment-proof-redacted.png -> Screenshot showing proof of Alibaba Cloud Deployment (privacy_checked=true, redacted=true)
- Not uploaded: recallpack-judge-deck.pptx -> Presentation PPT (privacy_checked=true, redacted=false)

## Local Video Candidate

- Status: built
- Path: docs/submission/media/video-candidate/recallpack-demo-candidate.mp4
- Duration seconds: 156.0
- Upload performed: false
- Devpost video URL: not recorded

## Presentation PPT

- Status: built
- Path: docs/submission/media/recallpack-judge-deck.pptx
- Slides: 6
- Upload performed: false
- Privacy checked: true

## Remaining Manual Items

- final presentation PPT upload or link
- final video URL or upload
- final Devpost submit approval
- final media order confirmation

## Repository URL

https://github.com/cyq1017/recallpack

## Verification

- Unit tests recorded in readiness report: 585
- Sanitized bundle: dist/recallpack-submission-20260720-231611
- Live Qwen E2E status: live_e2e_passed
- Fresh M98 live rerun status: live_e2e_failed
- Requires credentials: false
- Network calls made: false
