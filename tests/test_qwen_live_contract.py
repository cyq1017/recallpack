import json
import tempfile
import unittest
from pathlib import Path

from recallpack.live_qwen_contract import (
    build_live_qwen_contract_report,
    derive_rerank_base_url,
    write_live_qwen_contract_report,
)
from recallpack.providers import TEXT_MODEL


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
        return self._responses.pop(0)


class QwenLiveContractTests(unittest.TestCase):
    def test_derive_rerank_base_url_from_compatible_mode_url(self):
        self.assertEqual(
            derive_rerank_base_url("https://dashscope.aliyuncs.com/compatible-mode/v1"),
            "https://dashscope.aliyuncs.com/compatible-api/v1",
        )
        self.assertEqual(
            derive_rerank_base_url("https://dashscope-intl.aliyuncs.com/compatible-mode/v1/"),
            "https://dashscope-intl.aliyuncs.com/compatible-api/v1",
        )

    def test_live_contract_report_contains_sanitized_live_traces(self):
        opener = RecordingOpener(
            [
                FakeHTTPResponse(
                    '{"id":"chat-req","model":"qwen-plus","choices":[{"message":{"content":"{\\"operation\\":\\"write\\",\\"memory\\":{\\"type\\":\\"decision\\",\\"subject\\":\\"retry_policy\\",\\"text\\":\\"Use five attempts with exponential backoff.\\",\\"scope_level\\":\\"component\\",\\"component\\":\\"retry\\"},\\"duplicate_of_candidate_index\\":null,\\"supersedes_candidate_indexes\\":[0],\\"reason\\":\\"updated_retry_policy\\"}"}}],"usage":{"prompt_tokens":20,"completion_tokens":12,"total_tokens":32}}'
                ),
                FakeHTTPResponse(
                    '{"id":"query-emb","model":"text-embedding-v4","data":[{"embedding":[1.0,0.0,0.0]}],"usage":{"total_tokens":8}}'
                ),
                FakeHTTPResponse(
                    '{"id":"doc-emb","model":"text-embedding-v4","data":[{"embedding":[0.9,0.1,0.0]}],"usage":{"total_tokens":7}}'
                ),
                FakeHTTPResponse(
                    '{"id":"rerank-req","model":"qwen3-rerank","results":[{"index":0,"relevance_score":0.97}],"usage":{"total_tokens":13}}'
                ),
            ]
        )

        report = build_live_qwen_contract_report(
            api_key="unit-secret",
            compatible_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            rerank_base_url="https://dashscope.aliyuncs.com/compatible-api/v1",
            text_model="qwen-plus",
            opener=opener,
        )

        self.assertTrue(report["live_qwen_run"])
        self.assertEqual(report["live_status"], "live_contract_passed")
        self.assertEqual(report["region_base_url"], "https://dashscope.aliyuncs.com/compatible-mode/v1")
        self.assertEqual(report["rerank_base_url"], "https://dashscope.aliyuncs.com/compatible-api/v1")
        self.assertEqual(
            [trace["provider_role"] for trace in report["provider_traces"]],
            ["memory_decision", "embedding", "embedding", "rerank"],
        )
        self.assertEqual(
            [trace["model_name"] for trace in report["provider_traces"]],
            ["qwen-plus", "text-embedding-v4", "text-embedding-v4", "qwen3-rerank"],
        )
        for trace in report["provider_traces"]:
            self.assertTrue(trace["is_live"])
            self.assertEqual(trace["deterministic_fallback_status"], "live_qwen")
            self.assertTrue(trace["request_id_present"])
            self.assertNotIn("unit-secret", str(trace))
        self.assertEqual(
            report["actual_qwen_token_usage"],
            {
                "memory_decision_total_tokens": 32,
                "embedding_total_tokens": 15,
                "rerank_total_tokens": 13,
            },
        )
        self.assertNotIn("unit-secret", str(report))

    def test_live_contract_default_text_model_uses_pinned_tool_contract(self):
        opener = RecordingOpener(
            [
                FakeHTTPResponse(
                    '{"id":"chat-req","model":"qwen3.7-plus-2026-05-26","choices":[{"message":{"tool_calls":[{"type":"function","function":{"name":"decide_memory_operation","arguments":"{\\"operation\\":\\"write\\",\\"memory\\":{\\"type\\":\\"decision\\",\\"subject\\":\\"retry_policy\\",\\"text\\":\\"Use five attempts with exponential backoff.\\",\\"scope_level\\":\\"component\\",\\"component\\":\\"retry\\"},\\"duplicate_of_candidate_index\\":null,\\"supersedes_candidate_indexes\\":[0],\\"reason\\":\\"updated_retry_policy\\"}"}}]}}],"usage":{"total_tokens":32}}'
                ),
                FakeHTTPResponse(
                    '{"id":"query-emb","model":"text-embedding-v4","data":[{"embedding":[1.0,0.0,0.0]}],"usage":{"total_tokens":8}}'
                ),
                FakeHTTPResponse(
                    '{"id":"doc-emb","model":"text-embedding-v4","data":[{"embedding":[0.9,0.1,0.0]}],"usage":{"total_tokens":7}}'
                ),
                FakeHTTPResponse(
                    '{"id":"rerank-req","model":"qwen3-rerank","results":[{"index":0,"relevance_score":0.97}],"usage":{"total_tokens":13}}'
                ),
            ]
        )

        report = build_live_qwen_contract_report(
            api_key="unit-secret",
            compatible_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            rerank_base_url="https://dashscope.aliyuncs.com/compatible-api/v1",
            opener=opener,
        )
        memory_payload = json.loads(opener.requests[0]["request"].data.decode("utf-8"))
        memory_prompt = json.loads(memory_payload["messages"][1]["content"])

        self.assertEqual(report["provider_traces"][0]["model_name"], TEXT_MODEL)
        self.assertEqual(memory_payload["model"], TEXT_MODEL)
        self.assertEqual(memory_prompt["event"]["actor"], "user")
        self.assertEqual(memory_prompt["event"]["kind"], "message")
        self.assertEqual(memory_prompt["event"]["source_ref"], "contract-smoke:turn-002")
        self.assertIn("must_write_when", memory_prompt["decision_policy"])
        self.assertIn("tools", memory_payload)
        tool_parameters = memory_payload["tools"][0]["function"]["parameters"]
        self.assertIn("Use write for durable project memory", tool_parameters["properties"]["operation"]["description"])
        self.assertIn("Canonical memory to write", tool_parameters["properties"]["memory"]["description"])
        self.assertIn(
            "candidate_index values for older active memories",
            tool_parameters["properties"]["supersedes_candidate_indexes"]["description"],
        )
        self.assertEqual(
            memory_payload["tool_choice"],
            {
                "type": "function",
                "function": {"name": "decide_memory_operation"},
            },
        )

    def test_write_live_contract_report_creates_review_safe_json(self):
        opener = RecordingOpener(
            [
                FakeHTTPResponse(
                    '{"id":"chat-req","model":"qwen-plus","choices":[{"message":{"content":"{\\"operation\\":\\"no_op\\",\\"memory\\":null,\\"duplicate_of_candidate_index\\":null,\\"supersedes_candidate_indexes\\":[],\\"reason\\":\\"non_memory_event\\"}"}}],"usage":{"total_tokens":10}}'
                ),
                FakeHTTPResponse(
                    '{"id":"query-emb","model":"text-embedding-v4","data":[{"embedding":[1.0]}],"usage":{"total_tokens":2}}'
                ),
                FakeHTTPResponse(
                    '{"id":"doc-emb","model":"text-embedding-v4","data":[{"embedding":[1.0]}],"usage":{"total_tokens":3}}'
                ),
                FakeHTTPResponse(
                    '{"id":"rerank-req","model":"qwen3-rerank","results":[{"index":0,"relevance_score":0.97}],"usage":{"total_tokens":4}}'
                ),
            ]
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "live-qwen-trace.json"

            report = write_live_qwen_contract_report(
                target=target,
                api_key="unit-secret",
                compatible_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
                rerank_base_url="https://dashscope.aliyuncs.com/compatible-api/v1",
                text_model="qwen-plus",
                opener=opener,
            )

            written = target.read_text()

        self.assertTrue(report["live_qwen_run"])
        self.assertIn('"live_contract_passed"', written)
        self.assertNotIn("unit-secret", written)
        self.assertNotIn("tool_arguments", written)


if __name__ == "__main__":
    unittest.main()
