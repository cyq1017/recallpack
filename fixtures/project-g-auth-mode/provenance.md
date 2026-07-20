# Project G Auth Mode Provenance

This is a source-backed pattern fixture, not a copied open-source trace.

The scenario is inspired by public AI provider/gateway authentication header
issues:

- Higress issue 3954: a standard Claude provider path can forward client
  `Authorization` together with upstream `x-api-key`, causing upstream
  authentication failure.
- VSCode / VS Code issue 317810: custom endpoint BYOK auth header inference can choose
  the wrong header style for Azure-compatible gateways, and related comments
  describe `Authorization` plus `X-API-Key` conflicts.

RecallPack does not copy code, issue text, credentials, logs, or project data
from those repositories. The fixture is not copied; it is authored synthetic
data that captures
the general stale-decision shape:

- stale memory says to forward caller `Authorization` and attach `X-Api-Key`;
- active memory says standard provider-key mode must strip caller
  `Authorization` and send only `X-Api-Key`;
- active memory also preserves the separate OAuth/code-mode Bearer path.

This fixture is local behavior evidence only. It is not a real production
trace, not a broad benchmark, and not proof that RecallPack fixed either
public issue.
