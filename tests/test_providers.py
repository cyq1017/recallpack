import json
import unittest
from io import BytesIO
from urllib.error import HTTPError, URLError

from recallpack.observe import RetryableObserveError, TerminalObserveError
from recallpack.providers import (
    DeterministicKeywordEmbeddingProvider,
    DeterministicKeywordRerankProvider,
    EMBEDDING_DIMENSION,
    RERANK_MODEL,
    TEXT_EMBEDDING_MODEL,
    TEXT_MODEL,
    FakeEmbeddingProvider,
    FakeMemoryDecisionProvider,
    FakeRuleBasedMemoryDecisionProvider,
    FakeRerankProvider,
    ProviderError,
    ProviderMemoryDecider,
    ProviderRanker,
    RerankResult,
    QwenCloudHTTPClient,
    QwenEmbeddingProvider,
    QwenMemoryDecisionProvider,
    QwenRerankProvider,
    sanitized_provider_trace_records,
)


class RaisingMemoryDecisionProvider:
    def __init__(self, error):
        self._error = error

    def decide_memory_operation(self, event_text, candidate_payloads, tool_schema):
        raise self._error


class FakeHTTPResponse:
    def __init__(self, body, headers=None):
        self._body = body.encode("utf-8")
        self.headers = headers or {}

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False


class RecordingOpener:
    def __init__(self, responses):
        self._responses = list(responses)
        self.requests = []

    def __call__(self, request, timeout):
        self.requests.append({"request": request, "timeout": timeout})
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def _dot(left, right):
    return sum(a * b for a, b in zip(left, right))


class ProviderContractTests(unittest.TestCase):
    def test_fake_provider_traces_match_sanitized_load_bearing_schema(self):
        decision_provider = FakeMemoryDecisionProvider(
            tool_arguments={
                "operation": "no_op",
                "memory": None,
                "duplicate_of_candidate_index": None,
                "supersedes_candidate_indexes": [],
                "reason": "non_memory_event",
            }
        )
        embedding_provider = FakeEmbeddingProvider()
        rerank_provider = FakeRerankProvider(ranked_indexes=[0])

        decision = decision_provider.decide_memory_operation(
            event_text="User says do not add dependencies.",
            candidate_payloads=[{"type": "preference", "text": "existing"}],
            tool_schema={"name": "decide_memory_operation"},
        )
        query = embedding_provider.embed_query("Update retry behavior")
        document = embedding_provider.embed_document("Use five attempts with exponential backoff.")
        rerank = rerank_provider.rerank(
            goal="Update retry behavior",
            documents=["retry decision"],
            instruct="rank active memories",
        )

        records = sanitized_provider_trace_records(
            [decision.trace, query.trace, document.trace, rerank.trace]
        )

        expected_keys = {
            "provider_role",
            "model_name",
            "request_purpose",
            "input_item_count",
            "input_token_estimate",
            "output_item_count",
            "latency_ms",
            "is_live",
            "deterministic_fallback_status",
            "request_id_present",
            "request_id",
        }
        self.assertEqual([record["provider_role"] for record in records], [
            "memory_decision",
            "embedding",
            "embedding",
            "rerank",
        ])
        for record in records:
            self.assertEqual(set(record), expected_keys)
            self.assertFalse(record["is_live"])
            self.assertEqual(record["latency_ms"], 0)
            self.assertEqual(record["deterministic_fallback_status"], "fake_provider_deterministic")
            self.assertNotIn("User says do not add dependencies.", str(record))
            self.assertNotIn("tool_arguments", str(record))
            self.assertNotIn("secret", str(record).lower())

    def test_fake_and_live_traces_share_the_v4_contract_shape(self):
        fake = FakeEmbeddingProvider().embed_query("retry goal").trace.to_v4_record()
        opener = RecordingOpener(
            [
                FakeHTTPResponse(
                    '{"id":"req-live","model":"text-embedding-v4",'
                    '"data":[{"embedding":[0.1]}],'
                    '"usage":{"prompt_tokens":7,"completion_tokens":0,"total_tokens":7}}'
                )
            ]
        )
        live = QwenEmbeddingProvider(
            client=QwenCloudHTTPClient(api_key="unit-secret", opener=opener),
            compatible_base_url="https://example.invalid/v1",
        ).embed_query("retry goal").trace.to_v4_record()

        expected_keys = {
            "role",
            "provider_family",
            "model_name",
            "request_purpose",
            "input_item_count",
            "input_token_estimate",
            "output_item_count",
            "latency_ms",
            "live",
            "deterministic_fallback",
            "request_id_present",
            "token_usage",
        }
        self.assertEqual(set(fake), expected_keys)
        self.assertEqual(set(live), expected_keys)
        self.assertEqual(fake["provider_family"], "deterministic_fake")
        self.assertEqual(live["provider_family"], "qwen_cloud")
        self.assertTrue(fake["deterministic_fallback"])
        self.assertFalse(live["deterministic_fallback"])
        self.assertEqual(fake["latency_ms"], 0)
        self.assertFalse(fake["token_usage"]["reported_by_provider"])
        self.assertEqual(
            live["token_usage"],
            {
                "input_tokens": 7,
                "output_tokens": 0,
                "total_tokens": 7,
                "reported_by_provider": True,
            },
        )
        self.assertNotIn("req-live", str(live))
        self.assertNotIn("unit-secret", str(live))

    def test_live_provider_trace_records_measured_request_latency(self):
        opener = RecordingOpener(
            [
                FakeHTTPResponse(
                    '{"id":"req-live","model":"text-embedding-v4",'
                    '"data":[{"embedding":[0.1]}],'
                    '"usage":{"prompt_tokens":7,"completion_tokens":0,"total_tokens":7}}'
                )
            ]
        )
        clock_values = iter((100.0, 100.125))
        provider = QwenEmbeddingProvider(
            client=QwenCloudHTTPClient(
                api_key="unit-secret",
                opener=opener,
                clock=lambda: next(clock_values),
            ),
            compatible_base_url="https://example.invalid/v1",
        )

        trace = provider.embed_query("retry goal").trace

        self.assertEqual(125, trace.latency_ms)
        self.assertEqual(125, trace.to_sanitized_record()["latency_ms"])
        self.assertEqual(125, trace.to_v4_record()["latency_ms"])
        self.assertNotIn("unit-secret", str(trace.to_sanitized_record()))

    def test_fake_embedding_provider_records_query_and_document_calls(self):
        provider = FakeEmbeddingProvider()

        query = provider.embed_query("retry policy")
        document = provider.embed_document("Use five attempts with exponential backoff.")

        self.assertEqual(query.trace.provider_name, "fake-qwen")
        self.assertEqual(query.trace.model_id, TEXT_EMBEDDING_MODEL)
        self.assertEqual(query.trace.provider_role, "embedding")
        self.assertEqual(query.trace.request_purpose, "candidate_memory_retrieval_query")
        self.assertEqual(query.trace.input_item_count, 1)
        self.assertEqual(query.trace.output_item_count, 1)
        self.assertEqual(query.text_type, "query")
        self.assertEqual(len(query.embedding), EMBEDDING_DIMENSION)
        self.assertEqual(document.text_type, "document")
        self.assertEqual(len(document.embedding), EMBEDDING_DIMENSION)
        self.assertEqual(
            [call["operation"] for call in provider.calls],
            ["embed_query", "embed_document"],
        )
        self.assertEqual(provider.calls[0]["text"], "retry policy")

    def test_fake_rerank_provider_returns_ranked_indexes_with_trace(self):
        provider = FakeRerankProvider(ranked_indexes=[2, 0, 1])

        result = provider.rerank(
            goal="Modify retry behavior",
            documents=["preference", "lesson", "decision"],
            instruct="rank memories",
        )

        self.assertEqual(result.ranked_indexes, [2, 0, 1])
        self.assertEqual(result.trace.provider_name, "fake-qwen")
        self.assertEqual(result.trace.model_id, RERANK_MODEL)
        self.assertEqual(result.trace.provider_role, "rerank")
        self.assertEqual(result.trace.request_purpose, "precision_rerank_active_memory_candidates")
        self.assertEqual(result.trace.input_item_count, 3)
        self.assertEqual(result.trace.output_item_count, 3)
        self.assertEqual(result.trace.usage["document_count"], 3)
        self.assertEqual(provider.calls[0]["goal"], "Modify retry behavior")

    def test_fake_rerank_requires_complete_unique_finite_permutation(self):
        invalid_cases = [
            ([0], [0.9], "missing"),
            ([0, 0], [0.9, 0.8], "duplicate"),
            ([0, 2], [0.9, 0.8], "foreign"),
            ([0, 1], [0.9, float("nan")], "non_finite"),
            ([0, 1], [0.9], "score_count"),
            ([0, 1], [0.9, 0.8, 0.7], "extra_score"),
        ]

        for indexes, scores, label in invalid_cases:
            with self.subTest(label=label):
                provider = FakeRerankProvider(
                    ranked_indexes=indexes,
                    relevance_scores=scores,
                )
                with self.assertRaisesRegex(ProviderError, "rerank_failure") as raised:
                    provider.rerank(
                        goal="retry goal",
                        documents=["old", "current"],
                        instruct="rank active memories",
                    )
                self.assertEqual(raised.exception.code, "rerank_failure")
                self.assertTrue(raised.exception.retryable)

    def test_live_rerank_validates_and_sorts_complete_results_by_score(self):
        opener = RecordingOpener(
            [
                FakeHTTPResponse(
                    '{"id":"rerank-req","model":"qwen3-rerank","results":['
                    '{"index":0,"relevance_score":0.2},'
                    '{"index":1,"relevance_score":0.9}]}'
                )
            ]
        )
        provider = QwenRerankProvider(
            client=QwenCloudHTTPClient(api_key="unit-secret", opener=opener),
            rerank_base_url="https://example.invalid/v1",
        )

        result = provider.rerank(
            goal="retry goal",
            documents=["old", "current"],
            instruct="rank active memories",
        )

        self.assertEqual(result.ranked_indexes, [1, 0])
        self.assertEqual(result.relevance_scores, {0: 0.2, 1: 0.9})

    def test_deterministic_keyword_providers_rank_by_goal_terms(self):
        embedding_provider = DeterministicKeywordEmbeddingProvider()
        query = embedding_provider.embed_query("Update retry helper to exponential backoff")
        retry_doc = embedding_provider.embed_document(
            "type=decision\nscope=component:retry\nsubject=retry_policy\n"
            "memory=Use five attempts with exponential backoff."
        )
        auth_doc = embedding_provider.embed_document(
            "type=decision\nscope=component:auth\nsubject=auth_policy\n"
            "memory=Use bearer token validation."
        )

        self.assertGreater(_dot(query.embedding, retry_doc.embedding), 0.0)
        self.assertGreater(
            _dot(query.embedding, retry_doc.embedding),
            _dot(query.embedding, auth_doc.embedding),
        )
        self.assertEqual(query.trace.provider_name, "fake-qwen-keyword")
        self.assertEqual(query.trace.model_id, TEXT_EMBEDDING_MODEL)
        self.assertEqual(
            query.trace.usage["local_provider_mode"],
            "deterministic_keyword_fake",
        )

        rerank_provider = DeterministicKeywordRerankProvider()
        result = rerank_provider.rerank(
            goal="Update retry helper to exponential backoff",
            documents=[
                "type=decision\nsubject=auth_policy\nmemory=Use bearer token validation.",
                "type=decision\nsubject=retry_policy\nmemory=Use exponential backoff.",
            ],
            instruct="rank active memories",
        )

        self.assertEqual(result.ranked_indexes, [1, 0])
        self.assertEqual(result.trace.provider_name, "fake-qwen-keyword")
        self.assertEqual(result.trace.model_id, RERANK_MODEL)
        self.assertEqual(
            result.trace.usage["local_provider_mode"],
            "deterministic_keyword_fake",
        )

    def test_fake_memory_decision_provider_returns_tool_arguments_and_trace(self):
        tool_arguments = {
            "operation": "no_op",
            "memory": None,
            "duplicate_of_candidate_index": None,
            "supersedes_candidate_indexes": [],
            "reason": "non_memory_event",
        }
        provider = FakeMemoryDecisionProvider(tool_arguments=tool_arguments)

        result = provider.decide_memory_operation(
            event_text="hello",
            candidate_payloads=[],
            tool_schema={"name": "decide_memory_operation"},
        )

        self.assertEqual(result.tool_arguments, tool_arguments)
        self.assertEqual(result.trace.provider_name, "fake-qwen")
        self.assertEqual(result.trace.model_id, TEXT_MODEL)
        self.assertEqual(result.trace.provider_role, "memory_decision")
        self.assertEqual(
            result.trace.request_purpose,
            "extract_classify_and_judge_memory_lifecycle",
        )
        self.assertEqual(result.trace.input_item_count, 1)
        self.assertEqual(result.trace.output_item_count, 1)
        self.assertEqual(result.trace.tool_arguments, tool_arguments)
        self.assertEqual(result.trace.usage["candidate_count"], 0)
        self.assertEqual(provider.calls[0]["tool_schema"]["name"], "decide_memory_operation")

    def test_rule_based_memory_decision_provider_uses_text_and_candidates(self):
        provider = FakeRuleBasedMemoryDecisionProvider()
        prior_candidate = {
            "index": 0,
            "id": "mem_old",
            "type": "decision",
            "subject": "retry_policy",
            "text": "Use three attempts with a fixed 100 ms delay.",
            "scope": {"level": "component", "component": "retry"},
            "source": {"actor": "user"},
        }

        result = provider.decide_memory_operation(
            event_text=(
                "After the rate-limit failures, use five attempts with "
                "exponential backoff in the retry helper."
            ),
            candidate_payloads=[prior_candidate],
            tool_schema={"name": "decide_memory_operation"},
        )

        self.assertEqual(result.tool_arguments["operation"], "write")
        self.assertEqual(result.tool_arguments["memory"]["subject"], "retry_policy")
        self.assertEqual(result.tool_arguments["memory"]["component"], "retry")
        self.assertEqual(result.tool_arguments["supersedes_candidate_indexes"], [0])
        self.assertEqual(result.trace.provider_role, "memory_decision")
        self.assertEqual(result.trace.deterministic_fallback_status, "fake_provider_deterministic")
        self.assertEqual(
            provider.calls[0]["event_text"],
            "After the rate-limit failures, use five attempts with exponential backoff in the retry helper.",
        )
        self.assertEqual(result.trace.tool_arguments, result.tool_arguments)
        self.assertNotIn(
            "rate-limit",
            str(result.trace.to_sanitized_record()).lower(),
        )

    def test_provider_error_marks_retryable_and_terminal_failures(self):
        retryable = ProviderError.retryable(
            provider_name="fake-qwen",
            model_id=TEXT_MODEL,
            message="timeout",
            request_id="req-timeout",
        )
        terminal = ProviderError.terminal(
            provider_name="fake-qwen",
            model_id=TEXT_MODEL,
            message="schema rejected",
            request_id="req-schema",
        )

        self.assertTrue(retryable.retryable)
        self.assertFalse(terminal.retryable)
        self.assertEqual(retryable.request_id, "req-timeout")
        self.assertEqual(terminal.model_id, TEXT_MODEL)

    def test_provider_memory_decider_adapts_to_observe_runtime_contract(self):
        tool_arguments = {
            "operation": "no_op",
            "memory": None,
            "duplicate_of_candidate_index": None,
            "supersedes_candidate_indexes": [],
            "reason": "non_memory_event",
        }
        provider = FakeMemoryDecisionProvider(tool_arguments=tool_arguments)
        decider = ProviderMemoryDecider(provider)

        result = decider.decide_memory_operation(
            request=type(
                "Request",
                (),
                {
                    "project_id": "project-a",
                    "session_id": "session-a",
                    "event_id": "turn-001",
                    "sequence_no": 1,
                    "actor": "user",
                    "kind": "message",
                    "observed_at": "2026-06-24T00:00:00Z",
                    "text": "Use five attempts with exponential backoff.",
                },
            )(),
            candidates=[],
        )

        self.assertEqual(result, tool_arguments)
        self.assertEqual(len(decider.traces), 1)
        self.assertEqual(decider.traces[0].model_id, TEXT_MODEL)
        event_payload = __import__("json").loads(provider.calls[0]["event_text"])
        self.assertEqual(event_payload["actor"], "user")
        self.assertEqual(event_payload["kind"], "message")
        self.assertEqual(event_payload["sequence_no"], 1)
        self.assertEqual(event_payload["text"], "Use five attempts with exponential backoff.")
        self.assertEqual(event_payload["source_ref"], "session-a:turn-001")

    def test_provider_memory_decider_translates_retryable_provider_errors(self):
        provider = RaisingMemoryDecisionProvider(
            ProviderError.retryable(
                provider_name="fake-qwen",
                model_id=TEXT_MODEL,
                message="timeout",
                request_id="req-timeout",
            )
        )
        decider = ProviderMemoryDecider(provider)

        with self.assertRaises(RetryableObserveError):
            decider.decide_memory_operation(
                request=type("Request", (), {"text": "hello"})(),
                candidates=[],
            )

    def test_provider_memory_decider_translates_terminal_provider_errors(self):
        provider = RaisingMemoryDecisionProvider(
            ProviderError.terminal(
                provider_name="fake-qwen",
                model_id=TEXT_MODEL,
                message="incorrect api key",
                request_id="req-auth",
            )
        )
        decider = ProviderMemoryDecider(provider)

        with self.assertRaises(TerminalObserveError):
            decider.decide_memory_operation(
                request=type("Request", (), {"text": "hello"})(),
                candidates=[],
            )

    def test_provider_ranker_adapts_rerank_indexes_to_compile_contract(self):
        memories = [
            type("Memory", (), {"id": "mem_1"})(),
            type("Memory", (), {"id": "mem_2"})(),
            type("Memory", (), {"id": "mem_3"})(),
        ]
        provider = FakeRerankProvider(ranked_indexes=[2, 0, 1])
        ranker = ProviderRanker(provider)

        ranked = ranker.rank("Modify retry behavior", memories)

        self.assertEqual([memory.id for memory in ranked], ["mem_3", "mem_1", "mem_2"])
        self.assertEqual(len(ranker.traces), 1)
        self.assertEqual(ranker.traces[0].model_id, RERANK_MODEL)

    def test_provider_ranker_revalidates_non_finite_scores(self):
        trace = FakeRerankProvider(ranked_indexes=[0]).rerank(
            goal="retry",
            documents=["current retry policy"],
            instruct="rank",
        ).trace
        malformed_result = RerankResult(
            ranked_indexes=[0],
            relevance_scores={0: float("nan")},
            trace=trace,
        )
        provider = type(
            "MalformedRerankProvider",
            (),
            {"rerank": lambda self, **kwargs: malformed_result},
        )()

        with self.assertRaisesRegex(ProviderError, "rerank_failure") as raised:
            ProviderRanker(provider).rank(
                "Modify retry behavior",
                [type("Memory", (), {"id": "mem_1"})()],
            )

        self.assertEqual(raised.exception.code, "rerank_failure")

    def test_provider_ranker_rejects_invalid_result_containers_and_bool_indexes(self):
        trace = FakeRerankProvider(ranked_indexes=[0]).rerank(
            goal="retry",
            documents=["current retry policy"],
            instruct="rank",
        ).trace
        invalid_results = [
            RerankResult([0], trace, []),
            RerankResult([0], trace, None),
            RerankResult([False], trace, {0: 0.9}),
        ]
        for malformed_result in invalid_results:
            with self.subTest(result=malformed_result):
                provider = type(
                    "MalformedRerankProvider",
                    (),
                    {"rerank": lambda self, **kwargs: malformed_result},
                )()
                with self.assertRaisesRegex(ProviderError, "rerank_failure") as raised:
                    ProviderRanker(provider).rank(
                        "Modify retry behavior",
                        [type("Memory", (), {"id": "mem_1"})()],
                    )
                self.assertEqual(raised.exception.code, "rerank_failure")

    def test_live_embedding_provider_uses_qwen_http_and_sanitizes_trace(self):
        opener = RecordingOpener(
            [
                FakeHTTPResponse(
                    '{"id":"emb-req","model":"text-embedding-v4","data":[{"embedding":[0.1,0.2,0.3]}],"usage":{"total_tokens":7}}'
                )
            ]
        )
        client = QwenCloudHTTPClient(api_key="unit-secret", opener=opener)
        provider = QwenEmbeddingProvider(
            client=client,
            compatible_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        )

        result = provider.embed_query("retry goal")

        sent = opener.requests[0]["request"]
        self.assertEqual(sent.full_url, "https://dashscope.aliyuncs.com/compatible-mode/v1/embeddings")
        self.assertEqual(sent.headers["Authorization"], "Bearer unit-secret")
        self.assertEqual(result.embedding, [0.1, 0.2, 0.3])
        self.assertEqual(result.trace.provider_name, "qwen-cloud")
        self.assertTrue(result.trace.is_live)
        self.assertEqual(result.trace.deterministic_fallback_status, "live_qwen")
        record = result.trace.to_sanitized_record()
        self.assertTrue(record["request_id_present"])
        self.assertEqual(record["request_id"], "emb-req")
        self.assertNotIn("unit-secret", str(record))

    def test_live_rerank_provider_calls_qwen3_rerank_endpoint(self):
        opener = RecordingOpener(
            [
                FakeHTTPResponse(
                    '{"id":"rerank-req","model":"qwen3-rerank","results":[{"index":1,"relevance_score":0.9},{"index":0,"relevance_score":0.2}],"usage":{"total_tokens":11}}'
                )
            ]
        )
        client = QwenCloudHTTPClient(api_key="unit-secret", opener=opener)
        provider = QwenRerankProvider(
            client=client,
            rerank_base_url="https://dashscope.aliyuncs.com/compatible-api/v1",
        )

        result = provider.rerank(
            goal="retry goal",
            documents=["old", "current"],
            instruct="rank active memories",
        )

        sent = opener.requests[0]["request"]
        self.assertEqual(sent.full_url, "https://dashscope.aliyuncs.com/compatible-api/v1/reranks")
        self.assertEqual(result.ranked_indexes, [1, 0])
        self.assertEqual(result.trace.provider_role, "rerank")
        self.assertTrue(result.trace.is_live)
        self.assertEqual(result.trace.usage["total_tokens"], 11)

    def test_live_memory_decision_provider_parses_json_response(self):
        opener = RecordingOpener(
            [
                FakeHTTPResponse(
                    '{"id":"chat-req","model":"qwen-plus","choices":[{"message":{"content":"{\\"operation\\":\\"no_op\\",\\"memory\\":null,\\"duplicate_of_candidate_index\\":null,\\"supersedes_candidate_indexes\\":[],\\"reason\\":\\"non_memory_event\\"}"}}],"usage":{"prompt_tokens":9,"completion_tokens":6,"total_tokens":15}}'
                )
            ]
        )
        client = QwenCloudHTTPClient(api_key="unit-secret", opener=opener)
        provider = QwenMemoryDecisionProvider(
            client=client,
            compatible_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            model_id="qwen-plus",
        )

        result = provider.decide_memory_operation(
            event_text="hello",
            candidate_payloads=[],
            tool_schema={"name": "decide_memory_operation"},
        )

        self.assertEqual(result.tool_arguments["operation"], "no_op")
        self.assertEqual(result.trace.provider_role, "memory_decision")
        self.assertTrue(result.trace.is_live)
        self.assertEqual(result.trace.usage["total_tokens"], 15)
        self.assertNotIn("unit-secret", str(result.trace.to_sanitized_record()))

    def test_live_memory_decision_provider_uses_tool_calling_contract(self):
        opener = RecordingOpener(
            [
                FakeHTTPResponse(
                    '{"id":"chat-req","model":"qwen3.7-plus-2026-05-26","choices":[{"message":{"tool_calls":[{"type":"function","function":{"name":"decide_memory_operation","arguments":"{\\"operation\\":\\"write\\",\\"memory\\":{\\"type\\":\\"decision\\",\\"subject\\":\\"retry_policy\\",\\"text\\":\\"Use five attempts with exponential backoff.\\",\\"scope_level\\":\\"component\\",\\"component\\":\\"retry\\"},\\"duplicate_of_candidate_index\\":null,\\"supersedes_candidate_indexes\\":[0],\\"reason\\":\\"updated_retry_policy\\"}"}}]}}],"usage":{"prompt_tokens":19,"completion_tokens":8,"total_tokens":27}}'
                )
            ]
        )
        client = QwenCloudHTTPClient(api_key="unit-secret", opener=opener)
        provider = QwenMemoryDecisionProvider(
            client=client,
            compatible_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        )

        result = provider.decide_memory_operation(
            event_text=__import__("json").dumps(
                {
                    "project_id": "project-a",
                    "session_id": "session-a",
                    "event_id": "turn-005",
                    "source_ref": "session-a:turn-005",
                    "sequence_no": 5,
                    "actor": "user",
                    "kind": "message",
                    "observed_at": "2026-06-24T00:04:00Z",
                    "text": "Switch retry to five attempts with exponential backoff.",
                },
                sort_keys=True,
            ),
            candidate_payloads=[
                {
                    "candidate_index": 0,
                    "type": "decision",
                    "subject": "retry_policy",
                    "scope_level": "component",
                    "component": "retry",
                    "source_actor": "user",
                    "source_project_event_seq": 1,
                    "text": "Use three attempts with a fixed 100 ms delay.",
                }
            ],
            tool_schema={
                "name": "decide_memory_operation",
                "description": "Choose the memory lifecycle operation.",
                "parameters": {"type": "object", "properties": {}},
            },
        )

        sent = opener.requests[0]["request"]
        payload = sent.data.decode("utf-8")
        decoded_payload = __import__("json").loads(payload)
        prompt_text = decoded_payload["messages"][1]["content"]
        prompt_contract = __import__("json").loads(prompt_text)

        self.assertEqual(result.tool_arguments["operation"], "write")
        self.assertEqual(result.tool_arguments["supersedes_candidate_indexes"], [0])
        self.assertEqual(result.trace.model_id, TEXT_MODEL)
        self.assertIn('"model": "qwen3.7-plus-2026-05-26"', payload)
        self.assertIn('"tools"', payload)
        self.assertIn('"type": "function"', payload)
        self.assertIn('"function"', payload)
        self.assertIn('"name": "decide_memory_operation"', payload)
        self.assertIn('"tool_choice"', payload)
        self.assertIn('"enable_thinking": false', payload)
        self.assertIn('"temperature": 0', payload)
        self.assertEqual(prompt_contract["event"]["actor"], "user")
        self.assertEqual(prompt_contract["event"]["kind"], "message")
        self.assertEqual(prompt_contract["event"]["source_ref"], "session-a:turn-005")
        self.assertEqual(
            prompt_contract["event"]["text"],
            "Switch retry to five attempts with exponential backoff.",
        )
        self.assertIn("must_write_when", prompt_contract["decision_policy"])
        self.assertIn("must_supersede_when", prompt_contract["decision_policy"])
        self.assertIn("write when the event states a durable coding decision", prompt_text)
        self.assertIn("preference when the user sets a durable project constraint", prompt_text)
        lower_prompt = prompt_text.lower()
        self.assertIn("do not add new dependencies", lower_prompt)
        self.assertIn("write project-scoped preference", lower_prompt)
        self.assertIn("ci_policy", lower_prompt)
        self.assertIn("fail forward", lower_prompt)
        self.assertIn("supersedes_candidate_indexes", prompt_text)

    def test_live_memory_decision_provider_normalizes_stringified_tool_arguments(self):
        opener = RecordingOpener(
            [
                FakeHTTPResponse(
                    '{"id":"chat-req","model":"qwen3.7-plus-2026-05-26","choices":[{"message":{"tool_calls":[{"type":"function","function":{"name":"decide_memory_operation","arguments":"{\\"operation\\":\\"write\\",\\"memory\\":\\"{\\\\\\"type\\\\\\": \\\\\\"decision\\\\\\", \\\\\\"subject\\\\\\": \\\\\\"retry_policy\\\\\\", \\\\\\"text\\\\\\": \\\\\\"Use five attempts with exponential backoff.\\\\\\", \\\\\\"scope_level\\\\\\": \\\\\\"component\\\\\\", \\\\\\"component\\\\\\": \\\\\\"retry\\\\\\"}\\",\\"duplicate_of_candidate_index\\":\\"\\",\\"supersedes_candidate_indexes\\":[\\"0\\"],\\"reason\\":\\"updated_retry_policy\\"}"}}]}}],"usage":{"total_tokens":31}}'
                )
            ]
        )
        provider = QwenMemoryDecisionProvider(
            client=QwenCloudHTTPClient(api_key="unit-secret", opener=opener),
            compatible_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        )

        result = provider.decide_memory_operation(
            event_text="Switch retry to five attempts with exponential backoff.",
            candidate_payloads=[],
            tool_schema={"name": "decide_memory_operation"},
        )

        self.assertEqual(result.tool_arguments["operation"], "write")
        self.assertEqual(result.tool_arguments["memory"]["type"], "decision")
        self.assertEqual(result.tool_arguments["memory"]["subject"], "retry_policy")
        self.assertIsNone(result.tool_arguments["duplicate_of_candidate_index"])
        self.assertEqual(result.tool_arguments["supersedes_candidate_indexes"], [0])
        self.assertEqual(result.trace.tool_arguments, result.tool_arguments)

    def test_qwen_http_client_maps_http_errors_to_provider_errors(self):
        body = b'{"code":"InvalidApiKey","message":"Invalid API-key provided.","request_id":"bad-key"}'
        response_error = HTTPError(
            url="https://example.invalid",
            code=401,
            msg="Unauthorized",
            hdrs={},
            fp=BytesIO(body),
        )
        opener = RecordingOpener(
            [
                response_error
            ]
        )
        client = QwenCloudHTTPClient(api_key="unit-secret", opener=opener)

        with self.assertRaises(ProviderError) as raised:
            client.post_json(
                url="https://dashscope.aliyuncs.com/compatible-mode/v1/embeddings",
                payload={"model": "text-embedding-v4", "input": "x"},
                model_id="text-embedding-v4",
            )

        self.assertTrue(raised.exception.retryable)
        self.assertEqual(
            raised.exception.code,
            "provider_operator_action_required",
        )
        self.assertEqual(raised.exception.request_id, "bad-key")
        self.assertNotIn("unit-secret", raised.exception.message)
        self.assertTrue(response_error.fp.closed)

    def test_qwen_http_error_discards_invalid_usage_without_losing_error_evidence(self):
        invalid_usage_values = [
            {"total_tokens": "7"},
            {"total_tokens": True},
            {"total_tokens": -1},
            [7],
        ]
        for invalid_usage in invalid_usage_values:
            with self.subTest(usage=invalid_usage):
                body = json.dumps(
                    {
                        "message": "bad request",
                        "request_id": "bad-usage-error",
                        "usage": invalid_usage,
                    }
                ).encode("utf-8")
                opener = RecordingOpener(
                    [
                        HTTPError(
                            url="https://example.invalid",
                            code=400,
                            msg="Bad Request",
                            hdrs={},
                            fp=BytesIO(body),
                        )
                    ]
                )
                client = QwenCloudHTTPClient(
                    api_key="unit-secret",
                    opener=opener,
                )

                with self.assertRaises(ProviderError) as raised:
                    client.post_json(
                        url="https://example.invalid/embeddings",
                        payload={"model": TEXT_EMBEDDING_MODEL, "input": "x"},
                        model_id=TEXT_EMBEDDING_MODEL,
                    )

                self.assertEqual(
                    raised.exception.code,
                    "provider_operator_action_required",
                )
                self.assertEqual(raised.exception.request_id, "bad-usage-error")
                self.assertEqual(raised.exception.usage, {})

    def test_qwen_http_client_maps_retryable_transport_taxonomy(self):
        cases = [
            (
                HTTPError(
                    url="https://example.invalid",
                    code=429,
                    msg="rate limited",
                    hdrs={"x-request-id": "rate-req"},
                    fp=BytesIO(b'{"message":"slow down"}'),
                ),
                "provider_rate_limit",
            ),
            (
                HTTPError(
                    url="https://example.invalid",
                    code=503,
                    msg="unavailable",
                    hdrs={},
                    fp=BytesIO(b'{"message":"try later"}'),
                ),
                "provider_server_error",
            ),
            (TimeoutError("timed out"), "provider_timeout"),
            (URLError("dns failed"), "provider_network_error"),
        ]

        for source_error, expected_code in cases:
            with self.subTest(expected_code=expected_code):
                client = QwenCloudHTTPClient(
                    api_key="unit-secret",
                    opener=RecordingOpener([source_error]),
                )
                with self.assertRaises(ProviderError) as raised:
                    client.post_json(
                        url="https://example.invalid/embeddings",
                        payload={"model": TEXT_EMBEDDING_MODEL, "input": "x"},
                        model_id=TEXT_EMBEDDING_MODEL,
                    )
                self.assertTrue(raised.exception.retryable)
                self.assertEqual(raised.exception.code, expected_code)
                self.assertNotIn("unit-secret", raised.exception.message)

    def test_qwen_http_client_maps_malformed_success_json_to_retryable_error(self):
        client = QwenCloudHTTPClient(
            api_key="unit-secret",
            opener=RecordingOpener(
                [FakeHTTPResponse("not-json", headers={"X-Request-Id": "bad-json"})]
            ),
        )

        with self.assertRaises(ProviderError) as raised:
            client.post_json(
                url="https://example.invalid/embeddings",
                payload={"model": TEXT_EMBEDDING_MODEL, "input": "x"},
                model_id=TEXT_EMBEDDING_MODEL,
            )

        self.assertTrue(raised.exception.retryable)
        self.assertEqual(
            raised.exception.code,
            "provider_http_response_unparseable",
        )
        self.assertEqual(raised.exception.request_id, "bad-json")

    def test_live_adapters_map_structurally_malformed_2xx_json_to_provider_error(self):
        cases = [
            (
                QwenEmbeddingProvider(
                    client=QwenCloudHTTPClient(
                        api_key="unit-secret",
                        opener=RecordingOpener([FakeHTTPResponse('{"data":[]}')]),
                    ),
                    compatible_base_url="https://example.invalid/v1",
                ),
                lambda provider: provider.embed_query("retry goal"),
            ),
            (
                QwenMemoryDecisionProvider(
                    client=QwenCloudHTTPClient(
                        api_key="unit-secret",
                        opener=RecordingOpener([FakeHTTPResponse('{"choices":[]}')]),
                    ),
                    compatible_base_url="https://example.invalid/v1",
                ),
                lambda provider: provider.decide_memory_operation(
                    event_text="{}",
                    candidate_payloads=[],
                    tool_schema={"name": "decide_memory_operation"},
                ),
            ),
        ]

        for provider, invoke in cases:
            with self.subTest(provider=type(provider).__name__):
                with self.assertRaises(ProviderError) as raised:
                    invoke(provider)
                self.assertTrue(raised.exception.retryable)
                self.assertEqual(
                    raised.exception.code,
                    "provider_http_response_unparseable",
                )

    def test_live_memory_decision_maps_invalid_nested_json_to_provider_error(self):
        response = json.dumps(
            {
                "id": "nested-json-request",
                "choices": [{"message": {"content": "{bad}"}}],
            }
        )
        provider = QwenMemoryDecisionProvider(
            client=QwenCloudHTTPClient(
                api_key="unit-secret",
                opener=RecordingOpener([FakeHTTPResponse(response)]),
            ),
            compatible_base_url="https://example.invalid/v1",
        )

        with self.assertRaises(ProviderError) as raised:
            provider.decide_memory_operation(
                event_text="{}",
                candidate_payloads=[],
                tool_schema={"name": "decide_memory_operation"},
            )

        self.assertTrue(raised.exception.retryable)
        self.assertEqual(raised.exception.code, "model_output_unparseable")
        self.assertEqual(raised.exception.request_id, "nested-json-request")

    def test_live_adapter_rejects_invalid_success_usage_before_trace_serialization(self):
        response = json.dumps(
            {
                "id": "bad-usage-request",
                "data": [{"embedding": [0.1]}],
                "usage": {"total_tokens": "7"},
            }
        )
        provider = QwenEmbeddingProvider(
            client=QwenCloudHTTPClient(
                api_key="unit-secret",
                opener=RecordingOpener([FakeHTTPResponse(response)]),
            ),
            compatible_base_url="https://example.invalid/v1",
        )

        with self.assertRaises(ProviderError) as raised:
            provider.embed_query("retry goal")

        self.assertTrue(raised.exception.retryable)
        self.assertEqual(raised.exception.code, "provider_http_response_unparseable")
        self.assertEqual(raised.exception.request_id, "bad-usage-request")
        self.assertEqual(raised.exception.usage, {})

    def test_live_memory_decision_validates_usage_before_nested_json(self):
        response = json.dumps(
            {
                "id": "combined-request",
                "choices": [{"message": {"content": "{bad}"}}],
                "usage": {"total_tokens": "7"},
            }
        )
        provider = QwenMemoryDecisionProvider(
            client=QwenCloudHTTPClient(
                api_key="unit-secret",
                opener=RecordingOpener([FakeHTTPResponse(response)]),
            ),
            compatible_base_url="https://example.invalid/v1",
        )

        with self.assertRaises(ProviderError) as raised:
            provider.decide_memory_operation(
                event_text="{}",
                candidate_payloads=[],
                tool_schema={"name": "decide_memory_operation"},
            )

        self.assertEqual(raised.exception.code, "provider_http_response_unparseable")
        self.assertEqual(raised.exception.request_id, "combined-request")
        self.assertEqual(raised.exception.usage, {})

    def test_live_memory_decision_maps_integer_limit_parse_failure(self):
        huge_integer = "9" * 5000
        nested = (
            '{"operation":"no_op","memory":null,'
            f'"duplicate_of_candidate_index":{huge_integer},'
            '"supersedes_candidate_indexes":[],"reason":"x"}'
        )
        response = json.dumps(
            {
                "id": "huge-json-request",
                "choices": [{"message": {"content": nested}}],
            }
        )
        provider = QwenMemoryDecisionProvider(
            client=QwenCloudHTTPClient(
                api_key="unit-secret",
                opener=RecordingOpener([FakeHTTPResponse(response)]),
            ),
            compatible_base_url="https://example.invalid/v1",
        )

        with self.assertRaises(ProviderError) as raised:
            provider.decide_memory_operation(
                event_text="{}",
                candidate_payloads=[],
                tool_schema={"name": "decide_memory_operation"},
            )

        self.assertTrue(raised.exception.retryable)
        self.assertEqual(raised.exception.code, "model_output_unparseable")
        self.assertEqual(raised.exception.request_id, "huge-json-request")

    def test_live_memory_decision_preserves_request_evidence_on_normalization_error(self):
        arguments = json.dumps(
            {
                "operation": "write",
                "memory": "{bad}",
                "duplicate_of_candidate_index": None,
                "supersedes_candidate_indexes": [],
                "reason": "write_memory",
            }
        )
        response = json.dumps(
            {
                "id": "normalization-request",
                "choices": [
                    {
                        "message": {
                            "tool_calls": [
                                {
                                    "function": {
                                        "name": "decide_memory_operation",
                                        "arguments": arguments,
                                    }
                                }
                            ]
                        }
                    }
                ],
                "usage": {"total_tokens": 7},
            }
        )
        provider = QwenMemoryDecisionProvider(
            client=QwenCloudHTTPClient(
                api_key="unit-secret",
                opener=RecordingOpener([FakeHTTPResponse(response)]),
            ),
            compatible_base_url="https://example.invalid/v1",
        )

        with self.assertRaises(ProviderError) as raised:
            provider.decide_memory_operation(
                event_text="{}",
                candidate_payloads=[],
                tool_schema={"name": "decide_memory_operation"},
            )

        self.assertEqual(raised.exception.request_id, "normalization-request")
        self.assertEqual(raised.exception.usage, {"total_tokens": 7})

    def test_live_rerank_malformed_result_preserves_request_evidence(self):
        response = json.dumps(
            {
                "id": "bad-rerank-request",
                "results": [{"index": 0, "relevance_score": "bad"}],
                "usage": {"total_tokens": 7},
            }
        )
        provider = QwenRerankProvider(
            client=QwenCloudHTTPClient(
                api_key="unit-secret",
                opener=RecordingOpener([FakeHTTPResponse(response)]),
            ),
            rerank_base_url="https://example.invalid/v1",
        )

        with self.assertRaises(ProviderError) as raised:
            provider.rerank("retry", ["current policy"], "rank")

        self.assertEqual(raised.exception.code, "rerank_failure")
        self.assertEqual(raised.exception.request_id, "bad-rerank-request")
        self.assertEqual(raised.exception.usage, {"total_tokens": 7})


if __name__ == "__main__":
    unittest.main()
