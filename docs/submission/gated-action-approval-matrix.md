# RecallPack Gated Action Approval Matrix

This matrix is the approval surface for work that remains outside the local
submission-ready package. Every row is explicit approval required before Codex
may execute it.

## Approval Rules

- do not read credentials unless the matching row is approved.
- Do not run live Qwen calls unless the matching row is approved.
- Do not run Docker build/run unless the matching row is approved.
- Do not push images, create ECS resources, expose public endpoints, or submit
  the hackathon project unless the matching row is approved.
- Approval must name the action, target, and allowed scope in the current task.

## Matrix

| Action | Status | Approval phrase | Inputs needed | Stop conditions |
| --- | --- | --- | --- | --- |
| Live Qwen credential access | completed once; blocked for rerun | "Approve reading Qwen credentials for RecallPack live contract only." | Exact credential source and allowed env var names. | Any unrelated secret, missing scope, or unclear account. |
| Live Qwen contract | completed once; blocked for rerun | "Approve running RecallPack live Qwen contract once." | Approved credentials, model/account region, cost ceiling. | Unexpected billing prompt, network/auth error loop, or non-contract call. |
| Live Qwen E2E observe/compile | completed once; latest trace records live_e2e_passed | "Approve rerunning RecallPack live Qwen E2E observe/compile after contract changes." | Approved credentials, model/account region, cost ceiling, fixture target, and green `tools/build_live_qwen_e2e_preflight.py` output. | Unexpected billing prompt, network/auth error loop, non-E2E call, raw prompt/memory leakage, failed preflight, or repeated no-active-memory result. |
| Docker build/run proof | completed locally and on ECS; blocked for scope change | "Approve local Docker build/run proof for RecallPack." | Permission to use local Docker daemon and port. | Docker daemon unhealthy, privileged prompt, image push request. |
| Image push | blocked | "Approve pushing the RecallPack demo image to TARGET registry." | Registry target, repository name, account, tag. | Missing registry target, private data in image, auth mismatch. |
| Alibaba Cloud ECS deployment | completed; latest M104 redeploy passed; blocked for replacement or scale change | "Approve creating or replacing the RecallPack ECS demo deployment in TARGET account/region." | Account, region, instance size, network policy, budget ceiling. | More than one replica, more than one app worker, public exposure ambiguity. |
| Public endpoint exposure | completed once at `http://101.133.224.223/`; blocked for URL/domain/policy change | "Approve exposing RecallPack demo at URL for hackathon judging." | URL/domain/IP, allowed duration, access policy. | Broad access without duration, missing rollback path, secrets in response. |
| Hackathon submission | blocked | "Approve submitting RecallPack hackathon materials." | Final form destination, exact fields, screenshots/video links. | Any missing required field, public repo ambiguity, unreviewed upload. |

## Current Local State

- Local demo package is ready.
- Approved public ECS deployment is running at `http://101.133.224.223/` and
  passed `python3 tools/judge_smoke.py --url http://101.133.224.223`.
- One approved live Qwen credential use happened for the contract trace.
- One approved live Qwen contract run completed and wrote
  `docs/submission/live-qwen-trace.json`.
- Live Qwen E2E observe/compile/patch-generation was rerun with approval and
  wrote `docs/submission/live-qwen-e2e-trace.json` with `live_e2e_passed`;
  selected_sources include `session-a:turn-005`, `session-a:turn-004`, and
  `session-a:turn-003`.
- M48 credential-free live E2E preflight is generated at
  `docs/submission/live-qwen-e2e-preflight.json` with
  `preflight_status=ready_for_live_e2e_rerun`, `network_calls_made=false`, and
  `request_role_counts=memory_decision=12 embedding=16 rerank=2 patch_generation=2`.
- No credentials are stored in repo files.
- One approved local Docker image was built and run on `127.0.0.1`.
- One approved ECS Docker container is running as `recallpack-cloud` with
  `0.0.0.0:80->8789/tcp`.
- No Docker image has been pushed.
- No hackathon submission has been performed.
