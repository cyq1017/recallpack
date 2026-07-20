# Project H ProjectOdyssey JIT Provenance

This is a source-backed scenario fixture, not a copied open-source trace.

The scenario is inspired by a public ProjectOdyssey coding-agent instruction
evolution:

- Historical commit 47d9ddc:
  `https://github.com/HomericIntelligence/ProjectOdyssey/commit/47d9ddc`
- Current project instruction file:
  `https://github.com/HomericIntelligence/ProjectOdyssey/blob/main/CLAUDE.md`

RecallPack does not copy ProjectOdyssey code, docs, logs, tests, or raw text.
The fixture is authored synthetic data that captures the general stale-memory
shape:

- stale memory treats Mojo JIT CI crashes as flaky compiler behavior and allows
  retry or nonblocking workarounds;
- active memory says JIT crashes are real bugs and should not be hidden with
  retry loops, continue-on-error, or skip markers;
- active memory also keeps the no-new-dependencies preference for CI fixes.

This fixture is local behavior evidence only. It is not a production trace, not
a broad benchmark, and not proof that RecallPack fixed ProjectOdyssey.
