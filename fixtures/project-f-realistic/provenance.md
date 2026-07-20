# Project F Realistic Scenario Fixture Provenance

This is a realistic scenario fixture for RecallPack evaluation.

It is not a live production trace, customer log, copied repository history, or
private incident record. The event stream, repository snapshot, and hidden tests
are authored synthetic data.

The scenario is inspired by public maintenance patterns common in API client
projects: authentication header migrations, timeout policy changes, dependency
restraints, and noisy follow-up sessions where older decisions can remain
semantically attractive to retrieval.

The fixture exists to test whether RecallPack's lifecycle state prevents a
fresh coding agent from acting on a superseded API-client decision under a
limited handoff budget.
