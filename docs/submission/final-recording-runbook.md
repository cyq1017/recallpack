# RecallPack Final Recording Runbook

Status: recording guide only. Do not upload or submit from this file.

Target length: 2:20-2:45.

Recommended format: browser-window screen recording plus separately generated
natural voiceover.

## Recording Setup

- Record only the browser window.
- Hide bookmarks, extensions, desktop, menu bar, terminal history, and Finder.
- Do not open cloud consoles, API key pages, local file paths, or private notes.
- Use 1280x720 or 1920x1080.
- Keep zoom at 100% unless text is hard to read.
- Use the public repo and the credential-free demo only:
  - `https://github.com/cyq1017/recallpack`
  - `http://101.133.224.223/` or a local `127.0.0.1` demo

## Run Of Show

| Time | Screen | Action | What must be visible |
| --- | --- | --- | --- |
| 0:00-0:12 | GitHub README | Start at the repo top. Pause on title and first paragraph. | RecallPack, MemoryAgent, GitHub URL. |
| 0:12-0:25 | GitHub README | Scroll slightly to show judge quickstart or proof summary. | Fresh-clone / no credentials message. |
| 0:25-0:40 | Demo Learn tab | Switch to the demo first screen. | Deterministic stale-memory failure replay. |
| 0:40-0:58 | Demo Learn tab | Focus on local replay baseline card. | Local baseline stale context, wrong retry patch, `1/3`. |
| 0:58-1:18 | Demo Recall tab | Click Recall. Pause on lifecycle pipeline. | observe, remember, supersede, embedding top-N, rerank, budget. |
| 1:18-1:40 | Demo Recall tab | Scroll or focus on active pack. | Superseded vs active memory, active retry decision, no-dependency preference. |
| 1:40-1:58 | Demo Recall tab | Show downstream comparison. | Local replay baseline `1/3`, RecallPack `3/3`. |
| 1:58-2:18 | Demo Evaluate tab | Click Evaluate. Pause on Qwen evidence. | memory_decision, embedding, rerank roles. |
| 2:18-2:35 | Demo Evaluate or README | Show local/fresh-clone proof. | Credential-free demo and judge-run proof. |
| 2:35-2:45 | Demo first screen | End on hero proof. | Deterministic stale-context risk and RecallPack lifecycle success. |

## Retake Triggers

Retake if any of these happen:

- A personal email, phone number, local filesystem path, API key, SSH key path,
  terminal command history, or cloud console appears.
- The video implies the public demo performs live Qwen calls.
- The video implies the eight fixtures are a broad benchmark.
- The video implies the deterministic replay is a fresh live Qwen outcome.
- Baseline `1/3` is not visible in the first minute.
- RecallPack `3/3` is not visible by 1:55.
- Qwen roles are not visible by 2:20.
- The video runs longer than 2:45.

## Upload Boundary

Before upload, inspect the final video once without audio and once with audio.

Upload only after:

- no private data appears on screen;
- the voiceover does not overclaim live Qwen;
- the GitHub URL is the cleaned public repo;
- the project story still matches the video.
