import hashlib
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from recallpack.compile import CompileRequest, CompileService
from recallpack.observe import ObserveRequest, ObserveRuntime
from recallpack.providers import (
    FakeEmbeddingProvider,
    FakeRerankProvider,
    ProviderError,
    ProviderRanker,
    ProviderTrace,
    document_for_candidate,
)
from recallpack.storage import SqliteEventStore


class QueueDecider:
    def __init__(self, *operations):
        self._operations = list(operations)

    def decide_memory_operation(self, request, candidates):
        if not self._operations:
            raise AssertionError("decider called more times than expected")
        return self._operations.pop(0)


class IdentityRanker:
    def rank(self, goal, candidates):
        return candidates


class RecordingRanker:
    def __init__(self):
        self.calls = []
        self.traces = []
        self.last_relevance_scores = {}

    def rank(self, goal, candidates):
        self.calls.append({"goal": goal, "candidates": list(candidates)})
        self.last_relevance_scores = {
            candidate.id: float(len(candidates) - index)
            for index, candidate in enumerate(candidates)
        }
        if candidates:
            self.traces.append(
                ProviderTrace(
                    provider_name="test-ranker",
                    model_id="qwen3-rerank",
                    provider_role="rerank",
                    request_purpose="precision_rerank_active_memory_candidates",
                    input_item_count=len(candidates),
                    input_token_estimate=1,
                    output_item_count=len(candidates),
                )
            )
        return candidates


class Utf8Tokenizer:
    def count(self, text):
        return len(text.encode("utf-8"))


class ContentAwareTokenizer:
    def count(self, text):
        if "mem_huge" in text:
            return 513
        if "mem_small" in text:
            return 100
        return 1


class QueryOnlyEmbeddingProvider:
    def __init__(self, vector):
        self._vector = list(vector)
        self.calls = []

    def embed_query(self, text):
        self.calls.append(("query", text))
        return FakeEmbeddingProvider(
            vectors={f"query:{text}": list(self._vector)}
        ).embed_query(text)

    def embed_document(self, text):
        self.calls.append(("document", text))
        raise AssertionError("compile must use stored document vectors")


class ActiveMemoryStore:
    def __init__(self, memories):
        self._memories = list(memories)

    def active_memories(self, project_id):
        return [memory for memory in self._memories if memory.project_id == project_id]


def stored_memory(memory_id, score, sequence, *, text=None, component="retry"):
    vector = [0.0] * 1024
    vector[0] = score
    vector[1] = max(0.0, 1.0 - score * score) ** 0.5
    memory = SimpleNamespace(
        id=memory_id,
        project_id="project-a",
        type="decision",
        subject=f"subject_{memory_id}",
        text=text or f"Memory {memory_id}",
        scope_level="component",
        component=component,
        source_actor="user",
        source_ref=SimpleNamespace(session_id="session-a", event_id=f"turn-{sequence}"),
        source_project_event_seq=sequence,
        embedding=vector,
        embedding_model="text-embedding-v4",
        embedding_dimension=1024,
        embedding_document_hash=None,
        record_schema_version=4,
    )
    memory.embedding_document_hash = hashlib.sha256(
        document_for_candidate(memory).encode("utf-8")
    ).hexdigest()
    return memory


def observe_request(event_id: str, sequence_no: int, text: str) -> ObserveRequest:
    return ObserveRequest(
        project_id="project-a",
        session_id="session-a",
        event_id=event_id,
        sequence_no=sequence_no,
        actor="user",
        kind="message",
        observed_at="2026-06-24T00:00:00Z",
        text=text,
    )


def write_operation(memory_type, subject, text, scope_level, component):
    return {
        "operation": "write",
        "memory": {
            "type": memory_type,
            "subject": subject,
            "text": text,
            "scope_level": scope_level,
            "component": component,
        },
        "duplicate_of_candidate_index": None,
        "supersedes_candidate_indexes": [],
        "reason": "new_memory",
    }


def document_key(memory_type, scope_level, component, subject, text):
    scope = "project" if scope_level == "project" else f"{scope_level}:{component}"
    document = f"type={memory_type}\nscope={scope}\nsubject={subject}\nmemory={text}"
    return f"document:{document}"


class CompileServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "recallpack.sqlite3"
        self.store = SqliteEventStore(self.db_path, lease_seconds=30)
        self.tokenizer_patch = patch(
            "recallpack.budget.default_tokenizer",
            return_value=Utf8Tokenizer(),
        )
        self.tokenizer_patch.start()

    def tearDown(self):
        self.tokenizer_patch.stop()
        self.tmpdir.cleanup()

    def write_memory(self, event_id, sequence_no, operation, embedding_provider=None):
        runtime_kwargs = {
            "store": self.store,
            "decider": QueueDecider(operation),
        }
        if embedding_provider is not None:
            runtime_kwargs["embedding_provider"] = embedding_provider
        runtime = ObserveRuntime(**runtime_kwargs)
        return runtime.observe(
            observe_request(event_id, sequence_no, operation["memory"]["text"]),
            now=100 + sequence_no,
        )

    def test_compile_includes_only_active_scope_overlapping_memories(self):
        self.write_memory(
            "turn-001",
            1,
            write_operation(
                "decision",
                "retry_policy",
                "Use three attempts with a fixed 100 ms delay.",
                "component",
                "retry",
            ),
        )
        old_retry = self.store.active_memories("project-a")[0]
        replacement = {
            "operation": "write",
            "memory": {
                "type": "decision",
                "subject": "retry_policy",
                "text": "Use five attempts with exponential backoff.",
                "scope_level": "component",
                "component": "retry",
            },
            "duplicate_of_candidate_index": None,
            "supersedes_candidate_indexes": [0],
            "reason": "updated_retry_policy",
        }
        ObserveRuntime(store=self.store, decider=QueueDecider(replacement)).observe(
            observe_request("turn-002", 2, replacement["memory"]["text"]),
            now=102,
        )
        self.write_memory(
            "turn-003",
            3,
            write_operation(
                "preference",
                "dependency_policy",
                "Do not add new dependencies.",
                "project",
                None,
            ),
        )
        self.write_memory(
            "turn-004",
            4,
            write_operation(
                "decision",
                "auth_policy",
                "Use bearer token validation in auth.",
                "component",
                "auth",
            ),
        )
        service = CompileService(store=self.store, ranker=RecordingRanker())

        result = service.compile(
            CompileRequest(
                project_id="project-a",
                goal="Modify retry behavior",
                component="retry",
                budget_tokens=512,
            )
        )

        ids = [memory["id"] for memory in result.pack.memories]
        scopes = [memory["scope"] for memory in result.pack.memories]
        texts = [memory["text"] for memory in result.pack.memories]
        self.assertEqual(result.status_code, 200)
        self.assertNotIn(old_retry.id, ids)
        self.assertIn("component:retry", scopes)
        self.assertIn("project", scopes)
        self.assertIn("Use five attempts with exponential backoff.", texts)
        self.assertIn("Do not add new dependencies.", texts)
        self.assertNotIn("Use bearer token validation in auth.", texts)
        self.assertEqual(result.trace["candidate_count"], 2)
        self.assertEqual(result.trace["selected_count"], 2)

    def test_compile_fails_closed_when_nonempty_rerank_has_no_scores_or_trace(self):
        self.write_memory(
            "turn-001",
            1,
            write_operation(
                "decision",
                "retry_policy",
                "Use five attempts with exponential backoff.",
                "component",
                "retry",
            ),
        )

        result = CompileService(store=self.store, ranker=IdentityRanker()).compile(
            CompileRequest(
                project_id="project-a",
                goal="Modify retry behavior",
                component="retry",
                budget_tokens=512,
            )
        )

        self.assertEqual(result.status_code, 503)
        self.assertEqual(result.error, "rerank_failure")
        self.assertEqual(result.pack.memories, [])
        self.assertFalse(result.trace["artifacts_published"])

    def test_compile_uses_stored_embedding_top_twenty_before_rerank(self):
        retry_text = "Use five attempts with exponential backoff."
        dependency_text = "Do not add new dependencies."
        unrelated_text = "Use weekly status report headings."
        retry_vector = [0.95, 0.05] + [0.0] * 1022
        dependency_vector = [0.80, 0.20] + [0.0] * 1022
        unrelated_vector = [0.0, 1.0] + [0.0] * 1022
        stored_embeddings = FakeEmbeddingProvider(
            vectors={
                f"query:{dependency_text}": dependency_vector,
                f"query:{unrelated_text}": unrelated_vector,
                document_key("decision", "component", "retry", "retry_policy", retry_text): retry_vector,
                document_key(
                    "preference",
                    "project",
                    None,
                    "dependency_policy",
                    dependency_text,
                ): dependency_vector,
                document_key(
                    "preference",
                    "project",
                    None,
                    "reporting_policy",
                    unrelated_text,
                ): unrelated_vector,
            }
        )
        self.write_memory(
            "turn-001",
            1,
            write_operation("decision", "retry_policy", retry_text, "component", "retry"),
            stored_embeddings,
        )
        self.write_memory(
            "turn-002",
            2,
            write_operation("preference", "dependency_policy", dependency_text, "project", None),
            stored_embeddings,
        )
        self.write_memory(
            "turn-003",
            3,
            write_operation("preference", "reporting_policy", unrelated_text, "project", None),
            stored_embeddings,
        )
        ranker = RecordingRanker()
        embeddings = FakeEmbeddingProvider(
            vectors={
                "query:Modify retry behavior": [1.0] + [0.0] * 1023,
            }
        )
        service = CompileService(
            store=self.store,
            ranker=ranker,
            embedding_provider=embeddings,
            retrieval_top_n=20,
        )

        with patch(
            "recallpack.budget.default_tokenizer",
            return_value=SimpleNamespace(count=lambda _text: 1),
        ):
            result = service.compile(
                CompileRequest(
                    project_id="project-a",
                    goal="Modify retry behavior",
                    component="retry",
                    budget_tokens=512,
                )
            )

        texts = [memory["text"] for memory in result.pack.memories]
        reranked_texts = [memory.text for memory in ranker.calls[0]["candidates"]]
        self.assertEqual(result.status_code, 200)
        self.assertEqual(texts, [retry_text, dependency_text, unrelated_text])
        self.assertEqual(reranked_texts, [retry_text, dependency_text, unrelated_text])
        self.assertEqual(result.trace["candidate_count"], 3)
        self.assertEqual(result.trace["embedding_top_n_count"], 3)
        self.assertEqual(result.trace.get("embedding_top_n"), 20)
        self.assertEqual(result.trace["retrieval_mode"], "embedding_top_n")
        self.assertEqual(len(result.trace["omitted_by_embedding_memory_ids"]), 0)
        self.assertNotIn("omitted_by_embedding_texts", result.trace)
        self.assertEqual(
            [call["operation"] for call in embeddings.calls],
            ["embed_query"],
        )

    def test_compile_does_not_call_rerank_when_no_active_candidates(self):
        ranker = RecordingRanker()
        embeddings = FakeEmbeddingProvider()
        service = CompileService(
            store=self.store,
            ranker=ranker,
            embedding_provider=embeddings,
            retrieval_top_n=8,
        )

        result = service.compile(
            CompileRequest(
                project_id="project-a",
                goal="Modify retry behavior",
                component="retry",
                budget_tokens=512,
            )
        )

        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.pack.memories, [])
        self.assertEqual(ranker.calls, [])
        self.assertEqual(embeddings.calls, [])
        self.assertEqual(result.trace["candidate_count"], 0)
        self.assertEqual(result.trace["embedding_top_n_count"], 0)
        self.assertEqual(result.trace["selected_count"], 0)
        self.assertEqual(result.trace["retrieval_mode"], "embedding_top_n")
        self.assertEqual(result.trace["provider_traces"], [])

    def test_compile_never_embeds_or_recalls_superseded_memory_even_if_vector_similar(self):
        old_text = "Use three attempts with a fixed 100 ms delay."
        current_text = "Use five attempts with exponential backoff."
        self.write_memory(
            "turn-001",
            1,
            write_operation("decision", "retry_policy", old_text, "component", "retry"),
        )
        replacement = {
            "operation": "write",
            "memory": {
                "type": "decision",
                "subject": "retry_policy",
                "text": current_text,
                "scope_level": "component",
                "component": "retry",
            },
            "duplicate_of_candidate_index": None,
            "supersedes_candidate_indexes": [0],
            "reason": "updated_retry_policy",
        }
        ObserveRuntime(store=self.store, decider=QueueDecider(replacement)).observe(
            observe_request("turn-002", 2, current_text),
            now=102,
        )
        ranker = RecordingRanker()
        embeddings = FakeEmbeddingProvider(
            vectors={
                "query:Modify retry behavior": [1.0, 0.0] + [0.0] * 1022,
                document_key("decision", "component", "retry", "retry_policy", old_text): [1.0, 0.0]
                + [0.0] * 1022,
                document_key("decision", "component", "retry", "retry_policy", current_text): [
                    0.9,
                    0.1,
                ]
                + [0.0] * 1022,
            }
        )
        service = CompileService(
            store=self.store,
            ranker=ranker,
            embedding_provider=embeddings,
            retrieval_top_n=4,
        )

        result = service.compile(
            CompileRequest(
                project_id="project-a",
                goal="Modify retry behavior",
                component="retry",
                budget_tokens=512,
            )
        )

        embedded_texts = [call["text"] for call in embeddings.calls if call["operation"] == "embed_document"]
        packed_texts = [memory["text"] for memory in result.pack.memories]
        self.assertEqual(packed_texts, [current_text])
        self.assertEqual(embedded_texts, [])
        self.assertNotIn(old_text, "\n".join(embedded_texts))
        self.assertNotIn(old_text, "\n".join(packed_texts))

    def test_compile_returns_empty_pack_when_nothing_is_eligible(self):
        service = CompileService(store=self.store, ranker=IdentityRanker())

        result = service.compile(
            CompileRequest(
                project_id="project-a",
                goal="Modify cache behavior",
                component="cache",
                budget_tokens=512,
            )
        )

        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.pack.to_canonical_json(), '{"memories":[]}')
        self.assertEqual(result.trace["candidate_count"], 0)

    def test_compile_rejects_unknown_component(self):
        service = CompileService(store=self.store, ranker=IdentityRanker())

        result = service.compile(
            CompileRequest(
                project_id="project-a",
                goal="Modify billing behavior",
                component="billing",
                budget_tokens=512,
            )
        )

        self.assertEqual(result.status_code, 422)
        self.assertEqual(result.error, "invalid_component")


class CompileV4ContractTests(unittest.TestCase):
    def setUp(self):
        self.tokenizer_patch = patch(
            "recallpack.budget.default_tokenizer",
            return_value=Utf8Tokenizer(),
        )
        self.tokenizer_patch.start()

    def tearDown(self):
        self.tokenizer_patch.stop()

    def compile_or_fail(self, service, request, contract):
        try:
            return service.compile(request)
        except (AssertionError, ProviderError, ValueError) as exc:
            self.fail(f"{contract}: compile raised instead of returning the V4 result: {exc}")

    def request(self, budget=512):
        return CompileRequest(
            project_id="project-a",
            goal="Update retry behavior",
            component="retry",
            budget_tokens=budget,
        )

    def test_active_stored_vector_scan_sends_exact_top_twenty_to_rerank(self):
        memories = [
            stored_memory(f"mem_{index:02d}", 1.0 - index * 0.02, index + 1)
            for index in range(21)
        ]
        ranker = RecordingRanker()
        provider = QueryOnlyEmbeddingProvider([1.0] + [0.0] * 1023)
        service = CompileService(
            store=ActiveMemoryStore(memories),
            ranker=ranker,
            embedding_provider=provider,
        )

        result = self.compile_or_fail(
            service,
            self.request(),
            "stored-vector active-only top-20 retrieval",
        )

        self.assertEqual(result.status_code, 200)
        self.assertEqual(len(ranker.calls), 1)
        self.assertEqual(len(ranker.calls[0]["candidates"]), 20)
        self.assertEqual([item.id for item in ranker.calls[0]["candidates"]], [
            f"mem_{index:02d}" for index in range(20)
        ])
        self.assertEqual(provider.calls, [("query", "Update retry behavior")])

    def test_incomplete_rerank_permutation_returns_503_without_partial_pack(self):
        memory = stored_memory("mem_retry", 1.0, 1)
        query_vector = [1.0] + [0.0] * 1023
        embeddings = FakeEmbeddingProvider(
            vectors={
                "query:Update retry behavior": query_vector,
                f"document:{document_for_candidate(memory)}": query_vector,
            }
        )
        service = CompileService(
            store=ActiveMemoryStore([memory]),
            ranker=ProviderRanker(FakeRerankProvider(ranked_indexes=[])),
            embedding_provider=embeddings,
            retrieval_top_n=20,
        )

        result = self.compile_or_fail(
            service,
            self.request(),
            "strict rerank permutation",
        )

        self.assertEqual(result.status_code, 503)
        self.assertEqual(result.error, "rerank_failure")
        self.assertEqual(result.pack.memories, [])
        self.assertFalse(result.trace.get("artifacts_published", False))

    def test_short_or_zero_query_embedding_fails_closed_before_rerank(self):
        memory = stored_memory("mem_retry", 1.0, 1)
        for vector in ([1.0, 0.0], [0.0] * 1024):
            with self.subTest(vector_length=len(vector), nonzero=any(vector)):
                ranker = RecordingRanker()
                service = CompileService(
                    store=ActiveMemoryStore([memory]),
                    ranker=ranker,
                    embedding_provider=QueryOnlyEmbeddingProvider(vector),
                )

                result = self.compile_or_fail(
                    service,
                    self.request(),
                    "query embedding dimension and norm validation",
                )

                self.assertEqual(result.status_code, 503)
                self.assertEqual(result.error, "embedding_failure")
                self.assertEqual(result.pack.memories, [])
                self.assertEqual(ranker.calls, [])
                self.assertFalse(result.trace.get("artifacts_published", False))

    def test_rerank_ties_use_source_sequence_then_memory_id(self):
        memories = [
            stored_memory("mem_b", 0.8, 7),
            stored_memory("mem_a", 0.8, 7),
            stored_memory("mem_newer", 0.8, 8),
        ]
        query_vector = [1.0] + [0.0] * 1023
        vectors = {"query:Update retry behavior": query_vector}
        vectors.update(
            {f"document:{document_for_candidate(memory)}": query_vector for memory in memories}
        )
        service = CompileService(
            store=ActiveMemoryStore(memories),
            ranker=ProviderRanker(
                FakeRerankProvider(
                    ranked_indexes=[1, 0, 2],
                    relevance_scores=[0.5, 0.5, 0.5],
                )
            ),
            embedding_provider=FakeEmbeddingProvider(vectors=vectors),
            retrieval_top_n=20,
        )

        result = self.compile_or_fail(service, self.request(), "rerank tie-break")

        self.assertEqual(
            [memory["id"] for memory in result.pack.memories],
            ["mem_newer", "mem_a", "mem_b"],
        )
        self.assertEqual(
            result.trace.get("reranked_memory_ids"),
            ["mem_newer", "mem_a", "mem_b"],
        )
        candidate_scores = result.trace.get("candidate_scores", [])
        self.assertEqual(len(candidate_scores), 3)
        self.assertEqual(
            [score["candidate_index"] for score in candidate_scores],
            [0, 1, 2],
        )
        self.assertTrue(
            all(score["rerank_score"] == 0.5 for score in candidate_scores)
        )
        self.assertTrue(
            all(isinstance(score["embedding_cosine"], float) for score in candidate_scores)
        )
        artifact_traces = result.trace.get("artifact_provider_traces", [])
        self.assertEqual(
            [trace["role"] for trace in artifact_traces],
            ["embedding", "rerank"],
        )
        self.assertEqual(
            [trace["request_purpose"] for trace in artifact_traces],
            [
                "candidate_memory_retrieval_query",
                "precision_rerank_active_memory_candidates",
            ],
        )

    def test_budget_skips_overflow_and_continues_to_later_fitting_memory(self):
        huge = stored_memory("mem_huge", 1.0, 2, text="retry " * 400)
        small = stored_memory("mem_small", 0.9, 1, text="Keep retry dependency-free.")
        service = CompileService(
            store=ActiveMemoryStore([huge, small]),
            ranker=RecordingRanker(),
            embedding_provider=QueryOnlyEmbeddingProvider([1.0] + [0.0] * 1023),
            retrieval_top_n=20,
        )

        with patch(
            "recallpack.budget.default_tokenizer",
            return_value=ContentAwareTokenizer(),
        ):
            result = self.compile_or_fail(
                service,
                self.request(),
                "skip-and-continue exact budget selection",
            )

        self.assertEqual([memory["id"] for memory in result.pack.memories], ["mem_small"])
        self.assertEqual(
            result.trace.get("omissions"),
            [{"memory_id": "mem_huge", "stage": "budget", "reason": "budget_overflow"}],
        )

    def test_budget_smaller_than_empty_envelope_returns_422(self):
        service = CompileService(store=ActiveMemoryStore([]), ranker=IdentityRanker())

        with patch(
            "recallpack.budget.default_tokenizer",
            return_value=SimpleNamespace(count=lambda _text: 2),
        ):
            result = self.compile_or_fail(
                service,
                self.request(budget=1),
                "empty-envelope budget_too_small mapping",
            )

        self.assertEqual(result.status_code, 422)
        self.assertEqual(result.error, "budget_too_small")
        self.assertEqual(result.pack.memories, [])

    def test_empty_envelope_succeeds_when_no_active_memory_is_eligible(self):
        ranker = RecordingRanker()
        service = CompileService(store=ActiveMemoryStore([]), ranker=ranker)

        result = self.compile_or_fail(service, self.request(), "empty compile envelope")

        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.pack.to_canonical_json(), '{"memories":[]}')
        self.assertEqual(ranker.calls, [])
        self.assertEqual(result.trace.get("rerank_input_count"), 0)
        self.assertEqual(result.trace.get("selected_count"), 0)
        self.assertEqual(result.trace.get("provider_traces"), [])


if __name__ == "__main__":
    unittest.main()
