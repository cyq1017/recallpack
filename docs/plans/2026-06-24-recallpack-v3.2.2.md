# RecallPack V3.2.2 Final Redline

## Summary

V3.2.2 is a minimal engineering redline over
`docs/plans/2026-06-23-recallpack-v3.2.1.md`. It preserves the V3.2.1 product
shape and closes the final five P0 contract gaps before freezing migrations,
`/observe`, the hero fixture, and the evaluator.

If a V3.2.1 detail conflicts with this file, V3.2.2 wins.

## Fixed Runtime Parameters

```text
write_candidate_k = 8
read_embedding_k = 20
memory_budget_tokens = 512
tokenizer_encoding = o200k_base
embedding_model = text-embedding-v4
embedding_dimension = 1024
text_model = qwen3.7-plus-2026-05-26
deployment_replicas = 1
application_workers = 1
```

Any deployment with more than one ECS replica or more than one application
worker is non-compliant for the MVP. Use a single-process app server, for
example `uvicorn ... --workers 1`; do not run Gunicorn/Uvicorn multi-worker
mode. The in-process project lock is valid only under this single-worker
constraint.

## Ordered Event Stream Contract

V3.2.2 supports only online, ordered session event streams.

Add a per-project/session cursor:

```yaml
SessionCursor:
  project_id: string
  session_id: string
  next_expected_sequence_no: integer
```

Required constraints:

```text
UNIQUE(project_id, session_id, external_event_id)
UNIQUE(project_id, session_id, sequence_no)
```

Before creating or taking over an event lease, `/observe` must check the stream
cursor:

- `sequence_no < next_expected_sequence_no`: return `409 sequence_conflict`;
- `sequence_no > next_expected_sequence_no`: return `409 out_of_order`;
- previous event pending or failed/retryable: return `409 prior_event_incomplete`;
- only `sequence_no == next_expected_sequence_no` may be claimed.

`next_expected_sequence_no` advances by exactly one in the same final SQLite
transaction that commits `processing_state=completed` and `final_result_json`.
Terminal semantic no-op counts as completed and advances the cursor. Retryable
technical failure does not advance the cursor.

## Idempotency Preflight Before Lock

Duplicate requests must not wait behind the project application lock just to
discover that an event is already pending.

`POST /observe` order:

1. Run an idempotency preflight in a short SQLite transaction.
2. If same key + same hash + completed, return `200 final_result_json`.
3. If same key + different hash, return `409 idempotency_conflict`.
4. If same key + same hash + pending + unexpired lease, return `202 pending`.
5. If same key + same hash + pending + expired lease, atomically take over the
   lease and increment `attempt_count`.
6. If same key + same hash + failed/retryable, atomically create a new attempt.
7. Only after a request owns a valid lease may it wait for the project
   application lock and make Qwen/embedding calls.

This makes repeated requests return real `202 pending` while a first attempt is
running.

## Lease Fencing And CAS

Lease takeover requires fencing. Each processing attempt has:

```text
lease_token
attempt_no
```

The final SQLite transaction must commit memory, relation edges, observe run,
`processing_state=completed`, and `final_result_json` only if the event still
belongs to the current attempt:

```sql
UPDATE session_events
SET processing_state = 'completed',
    final_result_json = :result,
    lease_token = NULL,
    lease_expires_at = NULL
WHERE internal_id = :event_internal_id
  AND processing_state = 'pending'
  AND lease_token = :lease_token
  AND attempt_count = :attempt_no;
```

If this update affects zero rows, the attempt lost its lease. Roll back all
memory and relation writes from that transaction and return `409 lease_lost`.
An older attempt must never be able to commit after a newer attempt has taken
over an expired lease.

The same lease-token and attempt-number check applies when marking
`failed/retryable`.

## Token Budget Contract

`json.dumps(...)` defines the canonical byte sequence, but token counting is
defined by `tokenizer_encoding=o200k_base`.

Canonical serialization:

```python
json.dumps(
    pack,
    ensure_ascii=False,
    sort_keys=True,
    separators=(",", ":"),
)
```

Token estimate:

```text
len(o200k_base.encode(canonical_json))
```

The selector and evaluator must call the same shared token-counting function.
If `o200k_base` is unavailable in a runtime, evaluation must fail closed rather
than silently switching encodings.

The budget object remains the full downstream JSON object:

```json
{"memories":[...]}
```

Official evaluation uses `budget_tokens=512`. The API may accept
`1 <= budget_tokens <= 512`.

## Write Candidate Contract

Write-candidate retrieval is frozen as:

```text
same project
computed active
all scope levels and components
exact cosine similarity in application code
top write_candidate_k=8
```

Do not component-filter write candidates, because the incoming event's normalized
component is unknown until Qwen decides.

Tie-break candidates deterministically:

```text
cosine_score DESC
source_project_event_seq DESC
memory_id ASC
```

Every candidate sent to Qwen must include at least:

```json
{
  "candidate_index": 0,
  "memory_id": "mem_...",
  "type": "decision",
  "subject": "retry_policy",
  "text": "Use three attempts with a fixed 100 ms delay in the retry helper.",
  "scope_level": "component",
  "component": "retry",
  "source_actor": "user",
  "source_ref": {
    "session_id": "session-a",
    "event_id": "turn-001"
  },
  "source_project_event_seq": 1,
  "similarity": 0.83
}
```

`source_actor`, `scope_level`, `component`, and `source_project_event_seq` are
required so the service can enforce authority and relation hard constraints
after Qwen returns tool arguments.

Qwen may refer only to `candidate_index`, never arbitrary memory IDs. All
indexes are validated against the current allowlist.

Diagnostic metric:

```text
supersession-prior candidate recall@8
```

## Observe Tool Contract

Use the V3.2.1 strict discriminated union unchanged, with these clarifications:

- `operation=no_op`: terminal semantic no-op or non-memory event;
- `operation=duplicate`: semantic duplicate of one allowlisted candidate;
- `operation=write`: insert one memory, optionally with supersession edges;
- one event still creates at most one memory;
- cross-type multi-memory extraction remains out of scope.

## Final Build Gate

V3.2.2 is build-ready only if these redlines are preserved:

1. Ordered stream state includes `next_expected_sequence_no`.
2. `UNIQUE(project_id, session_id, sequence_no)` is enforced.
3. `/observe` rejects old, skipped, or blocked-by-prior events before claiming
   a new event.
4. Idempotency preflight happens before waiting on the project application lock.
5. Pending with unexpired lease always returns `202 pending`.
6. Lease takeover increments attempts and assigns a new lease token.
7. Final commit uses lease-token and attempt-number CAS/fencing.
8. Lost-lease attempts cannot write memories, edges, observe runs, or final
   results.
9. ECS replicas and application workers are both fixed at 1.
10. Token counting is fixed to `o200k_base` over canonical downstream JSON.
11. Selector and evaluator use the same token-counting function.
12. Write candidates are same-project, active, all-scope exact cosine top 8.
13. Candidate payload includes type, scope, component, source actor, source ref,
   source project sequence, and similarity.
14. Qwen relations refer only to candidate indexes from the allowlist.
15. `supersession-prior candidate recall@8` is tracked as a diagnostic metric.
