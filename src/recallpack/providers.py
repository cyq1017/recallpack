from __future__ import annotations

import json
import math
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

from recallpack.observe import RetryableObserveError, TerminalObserveError


TEXT_EMBEDDING_MODEL = "text-embedding-v4"
RERANK_MODEL = "qwen3-rerank"
TEXT_MODEL = "qwen3.7-plus-2026-05-26"
EMBEDDING_DIMENSION = 1024


@dataclass(frozen=True)
class ProviderTrace:
    provider_name: str
    model_id: str
    provider_role: str
    request_purpose: str
    input_item_count: int
    input_token_estimate: int
    output_item_count: int
    latency_ms: int = 0
    is_live: bool = False
    deterministic_fallback_status: str = "fake_provider_deterministic"
    request_id: str | None = None
    usage: dict[str, Any] = field(default_factory=dict)
    tool_arguments: dict[str, Any] | None = None

    def to_sanitized_record(self) -> dict[str, Any]:
        return {
            "provider_role": self.provider_role,
            "model_name": self.model_id,
            "request_purpose": self.request_purpose,
            "input_item_count": self.input_item_count,
            "input_token_estimate": self.input_token_estimate,
            "output_item_count": self.output_item_count,
            "latency_ms": _safe_latency_ms(self.latency_ms),
            "is_live": self.is_live,
            "deterministic_fallback_status": self.deterministic_fallback_status,
            "request_id_present": self.request_id is not None,
            "request_id": self.request_id,
        }

    def to_v4_record(self) -> dict[str, Any]:
        return {
            "role": self.provider_role,
            "provider_family": "qwen_cloud" if self.is_live else "deterministic_fake",
            "model_name": self.model_id,
            "request_purpose": self.request_purpose,
            "input_item_count": self.input_item_count,
            "input_token_estimate": self.input_token_estimate,
            "output_item_count": self.output_item_count,
            "latency_ms": _safe_latency_ms(self.latency_ms),
            "live": self.is_live,
            "deterministic_fallback": not self.is_live,
            "request_id_present": self.request_id is not None,
            "token_usage": _normalized_token_usage(self.usage, self.is_live),
        }


@dataclass(frozen=True)
class EmbeddingResult:
    embedding: list[float]
    text_type: str
    trace: ProviderTrace


@dataclass(frozen=True)
class RerankResult:
    ranked_indexes: list[int]
    trace: ProviderTrace
    relevance_scores: dict[int, float] = field(default_factory=dict)


@dataclass(frozen=True)
class MemoryDecisionResult:
    tool_arguments: dict[str, Any]
    trace: ProviderTrace


class ProviderError(Exception):
    def __init__(
        self,
        provider_name: str,
        model_id: str,
        message: str,
        retryable: bool,
        request_id: str | None = None,
        usage: dict[str, Any] | None = None,
        code: str = "provider_failure",
        latency_ms: int = 0,
    ) -> None:
        super().__init__(message)
        self.provider_name = provider_name
        self.model_id = model_id
        self.message = message
        self.retryable = retryable
        self.request_id = request_id
        self.usage = usage or {}
        self.code = code
        self.latency_ms = _safe_latency_ms(latency_ms)

    @classmethod
    def retryable(
        cls,
        provider_name: str,
        model_id: str,
        message: str,
        request_id: str | None = None,
        usage: dict[str, Any] | None = None,
        code: str = "provider_retryable_failure",
        latency_ms: int = 0,
    ) -> ProviderError:
        return cls(
            provider_name,
            model_id,
            message,
            True,
            request_id,
            usage,
            code,
            latency_ms,
        )

    @classmethod
    def terminal(
        cls,
        provider_name: str,
        model_id: str,
        message: str,
        request_id: str | None = None,
        usage: dict[str, Any] | None = None,
        code: str = "provider_terminal_failure",
        latency_ms: int = 0,
    ) -> ProviderError:
        return cls(
            provider_name,
            model_id,
            message,
            False,
            request_id,
            usage,
            code,
            latency_ms,
        )


class EmbeddingProvider(Protocol):
    def embed_query(self, text: str) -> EmbeddingResult:
        ...

    def embed_document(self, text: str) -> EmbeddingResult:
        ...


class RerankProvider(Protocol):
    def rerank(self, goal: str, documents: list[str], instruct: str) -> RerankResult:
        ...


class MemoryDecisionProvider(Protocol):
    def decide_memory_operation(
        self,
        event_text: str,
        candidate_payloads: list[dict[str, Any]],
        tool_schema: dict[str, Any],
    ) -> MemoryDecisionResult:
        ...


class FakeEmbeddingProvider:
    def __init__(
        self,
        vectors: dict[str, list[float]] | None = None,
        provider_name: str = "fake-qwen",
    ) -> None:
        self._vectors = vectors or {}
        self._provider_name = provider_name
        self.calls: list[dict[str, Any]] = []
        self.traces: list[ProviderTrace] = []

    def embed_query(self, text: str) -> EmbeddingResult:
        return self._embed(text, text_type="query", operation="embed_query")

    def embed_document(self, text: str) -> EmbeddingResult:
        return self._embed(text, text_type="document", operation="embed_document")

    def _embed(self, text: str, text_type: str, operation: str) -> EmbeddingResult:
        self.calls.append({"operation": operation, "text": text, "text_type": text_type})
        key = f"{text_type}:{text}"
        vector = self._vectors.get(key, _zero_embedding())
        result = EmbeddingResult(
            embedding=list(vector),
            text_type=text_type,
            trace=ProviderTrace(
                provider_name=self._provider_name,
                model_id=TEXT_EMBEDDING_MODEL,
                provider_role="embedding",
                request_purpose=_embedding_request_purpose(text_type),
                input_item_count=1,
                input_token_estimate=_estimate_tokens(text),
                output_item_count=1,
                request_id=f"fake-{operation}-{len(self.calls)}",
                usage={"input_chars": len(text), "embedding_dimension": EMBEDDING_DIMENSION},
            ),
        )
        self.traces.append(result.trace)
        return result


class FakeRerankProvider:
    def __init__(
        self,
        ranked_indexes: list[int] | None = None,
        relevance_scores: list[float] | None = None,
        provider_name: str = "fake-qwen",
    ) -> None:
        self._ranked_indexes = ranked_indexes
        self._relevance_scores = relevance_scores
        self._provider_name = provider_name
        self.calls: list[dict[str, Any]] = []
        self.traces: list[ProviderTrace] = []

    def rerank(self, goal: str, documents: list[str], instruct: str) -> RerankResult:
        self.calls.append(
            {
                "operation": "rerank",
                "goal": goal,
                "documents": list(documents),
                "instruct": instruct,
            }
        )
        ranked_indexes = self._ranked_indexes
        if ranked_indexes is None:
            ranked_indexes = list(range(len(documents)))
        relevance_scores = self._relevance_scores
        if relevance_scores is None:
            relevance_scores = [float(len(ranked_indexes) - rank) for rank in range(len(ranked_indexes))]
        if len(relevance_scores) != len(ranked_indexes):
            raise _rerank_failure(
                self._provider_name,
                RERANK_MODEL,
                "relevance score count must match ranked index count",
            )
        results = [
            {"index": index, "relevance_score": score}
            for index, score in zip(ranked_indexes, relevance_scores, strict=True)
        ]
        validated_indexes, score_by_index = _validate_rerank_results(
            results=results,
            expected_count=len(documents),
            provider_name=self._provider_name,
            model_id=RERANK_MODEL,
        )
        return RerankResult(
            ranked_indexes=validated_indexes,
            trace=ProviderTrace(
                provider_name=self._provider_name,
                model_id=RERANK_MODEL,
                provider_role="rerank",
                request_purpose="precision_rerank_active_memory_candidates",
                input_item_count=len(documents),
                input_token_estimate=_estimate_tokens(goal + "\n" + "\n".join(documents)),
                output_item_count=len(validated_indexes),
                request_id=f"fake-rerank-{len(self.calls)}",
                usage={"document_count": len(documents)},
            ),
            relevance_scores=score_by_index,
        )


class DeterministicKeywordEmbeddingProvider:
    def __init__(self, provider_name: str = "fake-qwen-keyword") -> None:
        self._provider_name = provider_name
        self.calls: list[dict[str, Any]] = []
        self.traces: list[ProviderTrace] = []

    def embed_query(self, text: str) -> EmbeddingResult:
        return self._embed(text, text_type="query", operation="embed_query")

    def embed_document(self, text: str) -> EmbeddingResult:
        return self._embed(text, text_type="document", operation="embed_document")

    def _embed(self, text: str, text_type: str, operation: str) -> EmbeddingResult:
        tokens = _keyword_tokens(text)
        self.calls.append(
            {
                "operation": operation,
                "text": text,
                "text_type": text_type,
                "token_count": len(tokens),
            }
        )
        result = EmbeddingResult(
            embedding=_keyword_embedding(tokens),
            text_type=text_type,
            trace=ProviderTrace(
                provider_name=self._provider_name,
                model_id=TEXT_EMBEDDING_MODEL,
                provider_role="embedding",
                request_purpose=_embedding_request_purpose(text_type),
                input_item_count=1,
                input_token_estimate=_estimate_tokens(text),
                output_item_count=1,
                request_id=f"fake-keyword-{operation}-{len(self.calls)}",
                usage={
                    "input_chars": len(text),
                    "keyword_count": len(tokens),
                    "embedding_dimension": EMBEDDING_DIMENSION,
                    "local_provider_mode": "deterministic_keyword_fake",
                },
            ),
        )
        self.traces.append(result.trace)
        return result


class DeterministicKeywordRerankProvider:
    def __init__(self, provider_name: str = "fake-qwen-keyword") -> None:
        self._provider_name = provider_name
        self.calls: list[dict[str, Any]] = []

    def rerank(self, goal: str, documents: list[str], instruct: str) -> RerankResult:
        goal_tokens = _keyword_tokens(goal)
        scored = [
            (_keyword_overlap_score(goal_tokens, _keyword_tokens(document)), index)
            for index, document in enumerate(documents)
        ]
        scored.sort(key=lambda item: (-item[0], item[1]))
        ranked_indexes = [index for _, index in scored]
        relevance_scores = {index: score for score, index in scored}
        self.calls.append(
            {
                "operation": "rerank",
                "goal": goal,
                "documents": list(documents),
                "instruct": instruct,
                "ranked_indexes": list(ranked_indexes),
            }
        )
        return RerankResult(
            ranked_indexes=ranked_indexes,
            trace=ProviderTrace(
                provider_name=self._provider_name,
                model_id=RERANK_MODEL,
                provider_role="rerank",
                request_purpose="precision_rerank_active_memory_candidates",
                input_item_count=len(documents),
                input_token_estimate=_estimate_tokens(goal + "\n" + "\n".join(documents)),
                output_item_count=len(ranked_indexes),
                request_id=f"fake-keyword-rerank-{len(self.calls)}",
                usage={
                    "document_count": len(documents),
                    "query_keyword_count": len(goal_tokens),
                    "local_provider_mode": "deterministic_keyword_fake",
                },
            ),
            relevance_scores=relevance_scores,
        )


class FakeMemoryDecisionProvider:
    def __init__(
        self,
        tool_arguments: dict[str, Any],
        provider_name: str = "fake-qwen",
    ) -> None:
        self._tool_arguments = dict(tool_arguments)
        self._provider_name = provider_name
        self.calls: list[dict[str, Any]] = []

    def decide_memory_operation(
        self,
        event_text: str,
        candidate_payloads: list[dict[str, Any]],
        tool_schema: dict[str, Any],
    ) -> MemoryDecisionResult:
        self.calls.append(
            {
                "operation": "decide_memory_operation",
                "event_text": event_text,
                "candidate_payloads": list(candidate_payloads),
                "tool_schema": dict(tool_schema),
            }
        )
        usage = {
            "event_chars": len(event_text),
            "candidate_count": len(candidate_payloads),
        }
        return MemoryDecisionResult(
            tool_arguments=dict(self._tool_arguments),
            trace=ProviderTrace(
                provider_name=self._provider_name,
                model_id=TEXT_MODEL,
                provider_role="memory_decision",
                request_purpose="extract_classify_and_judge_memory_lifecycle",
                input_item_count=1 + len(candidate_payloads),
                input_token_estimate=_estimate_tokens(
                    event_text + "\n" + str(candidate_payloads)
                ),
                output_item_count=1,
                request_id=f"fake-decision-{len(self.calls)}",
                usage=usage,
                tool_arguments=dict(self._tool_arguments),
            ),
        )


class FakeRuleBasedMemoryDecisionProvider:
    def __init__(self, provider_name: str = "fake-qwen") -> None:
        self._provider_name = provider_name
        self.calls: list[dict[str, Any]] = []

    def decide_memory_operation(
        self,
        event_text: str,
        candidate_payloads: list[dict[str, Any]],
        tool_schema: dict[str, Any],
    ) -> MemoryDecisionResult:
        self.calls.append(
            {
                "operation": "decide_memory_operation",
                "event_text": event_text,
                "candidate_payloads": list(candidate_payloads),
                "tool_schema": dict(tool_schema),
            }
        )
        tool_arguments = _rule_based_memory_operation(event_text, candidate_payloads)
        return MemoryDecisionResult(
            tool_arguments=tool_arguments,
            trace=ProviderTrace(
                provider_name=self._provider_name,
                model_id=TEXT_MODEL,
                provider_role="memory_decision",
                request_purpose="extract_classify_and_judge_memory_lifecycle",
                input_item_count=1 + len(candidate_payloads),
                input_token_estimate=_estimate_tokens(
                    event_text + "\n" + str(candidate_payloads)
                ),
                output_item_count=1,
                request_id=f"fake-rule-decision-{len(self.calls)}",
                usage={
                    "event_chars": len(event_text),
                    "candidate_count": len(candidate_payloads),
                },
                tool_arguments=tool_arguments,
            ),
        )


class QwenCloudHTTPClient:
    def __init__(
        self,
        api_key: str,
        opener: Any | None = None,
        timeout_seconds: int = 30,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._api_key = api_key
        self._opener = opener or urllib.request.urlopen
        self._timeout_seconds = timeout_seconds
        self._clock = clock or time.monotonic

    def post_json(
        self,
        url: str,
        payload: dict[str, Any],
        model_id: str,
    ) -> tuple[dict[str, Any], dict[str, str]]:
        body, headers, _ = self.post_json_timed(url, payload, model_id)
        return body, headers

    def post_json_timed(
        self,
        url: str,
        payload: dict[str, Any],
        model_id: str,
    ) -> tuple[dict[str, Any], dict[str, str], int]:
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        started_at = self._clock()
        try:
            with self._opener(request, timeout=self._timeout_seconds) as response:
                headers = dict(getattr(response, "headers", {}) or {})
                try:
                    raw_body = response.read().decode("utf-8")
                    body = json.loads(raw_body)
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise ProviderError.retryable(
                        provider_name="qwen-cloud",
                        model_id=model_id,
                        message="Provider HTTP response was not valid UTF-8 JSON.",
                        request_id=_request_id_from_body_or_headers({}, headers),
                        code="provider_http_response_unparseable",
                        latency_ms=self._elapsed_ms(started_at),
                    ) from exc
                if not isinstance(body, dict):
                    raise ProviderError.retryable(
                        provider_name="qwen-cloud",
                        model_id=model_id,
                        message="Provider HTTP response JSON was not an object.",
                        request_id=_request_id_from_body_or_headers({}, headers),
                        code="provider_http_response_unparseable",
                        latency_ms=self._elapsed_ms(started_at),
                    )
                return body, headers, self._elapsed_ms(started_at)
        except urllib.error.HTTPError as exc:
            try:
                raw_body = exc.read().decode("utf-8", errors="replace")
                body = _loads_json_or_empty(raw_body)
                message = _provider_error_message(body, raw_body)
                request_id = _request_id_from_body_or_headers(
                    body, dict(exc.headers or {})
                )
                raise ProviderError(
                    provider_name="qwen-cloud",
                    model_id=model_id,
                    message=_redact_secret(message, self._api_key),
                    retryable=True,
                    request_id=request_id,
                    usage=_safe_usage_from_error_body(body),
                    code=_http_provider_error_code(exc.code),
                    latency_ms=self._elapsed_ms(started_at),
                ) from exc
            finally:
                exc.close()
        except TimeoutError as exc:
            raise ProviderError.retryable(
                provider_name="qwen-cloud",
                model_id=model_id,
                message="Provider request timed out.",
                code="provider_timeout",
                latency_ms=self._elapsed_ms(started_at),
            ) from exc
        except urllib.error.URLError as exc:
            raise ProviderError.retryable(
                provider_name="qwen-cloud",
                model_id=model_id,
                message=_redact_secret(str(exc.reason), self._api_key),
                code="provider_network_error",
                latency_ms=self._elapsed_ms(started_at),
            ) from exc

    def _elapsed_ms(self, started_at: float) -> int:
        return max(0, int(round((self._clock() - started_at) * 1000)))


def post_qwen_json_with_latency(
    client: Any,
    *,
    url: str,
    payload: dict[str, Any],
    model_id: str,
) -> tuple[dict[str, Any], dict[str, str], int]:
    """Call the timed client contract while preserving legacy test adapters."""
    timed_post = getattr(client, "post_json_timed", None)
    if callable(timed_post):
        body, headers, latency_ms = timed_post(
            url=url,
            payload=payload,
            model_id=model_id,
        )
        return body, headers, _safe_latency_ms(latency_ms)
    body, headers = client.post_json(
        url=url,
        payload=payload,
        model_id=model_id,
    )
    return body, headers, 0


class QwenEmbeddingProvider:
    def __init__(
        self,
        client: QwenCloudHTTPClient,
        compatible_base_url: str,
        model_id: str = TEXT_EMBEDDING_MODEL,
    ) -> None:
        self._client = client
        self._compatible_base_url = compatible_base_url.rstrip("/")
        self._model_id = model_id
        self.traces: list[ProviderTrace] = []

    def embed_query(self, text: str) -> EmbeddingResult:
        return self._embed(text, text_type="query")

    def embed_document(self, text: str) -> EmbeddingResult:
        return self._embed(text, text_type="document")

    def _embed(self, text: str, text_type: str) -> EmbeddingResult:
        body, headers, latency_ms = post_qwen_json_with_latency(
            self._client,
            url=f"{self._compatible_base_url}/embeddings",
            payload={"model": self._model_id, "input": text},
            model_id=self._model_id,
        )
        request_id = _request_id_from_body_or_headers(body, headers)
        usage = _validated_usage_from_body(body, self._model_id, headers)
        data = body.get("data")
        if (
            not isinstance(data, list)
            or len(data) != 1
            or not isinstance(data[0], dict)
            or not isinstance(data[0].get("embedding"), list)
        ):
            raise _malformed_success_response(
                model_id=self._model_id,
                body=body,
                headers=headers,
                detail="embedding response must contain exactly one data item",
                usage=usage,
                latency_ms=latency_ms,
            )
        embedding = list(data[0]["embedding"])
        result = EmbeddingResult(
            embedding=embedding,
            text_type=text_type,
            trace=ProviderTrace(
                provider_name="qwen-cloud",
                model_id=body.get("model", self._model_id),
                provider_role="embedding",
                request_purpose=_embedding_request_purpose(text_type),
                input_item_count=1,
                input_token_estimate=_estimate_tokens(text),
                output_item_count=1,
                latency_ms=latency_ms,
                is_live=True,
                deterministic_fallback_status="live_qwen",
                request_id=request_id,
                usage=usage,
            ),
        )
        self.traces.append(result.trace)
        return result


class QwenRerankProvider:
    def __init__(
        self,
        client: QwenCloudHTTPClient,
        rerank_base_url: str,
        model_id: str = RERANK_MODEL,
    ) -> None:
        self._client = client
        self._rerank_base_url = rerank_base_url.rstrip("/")
        self._model_id = model_id

    def rerank(self, goal: str, documents: list[str], instruct: str) -> RerankResult:
        body, headers, latency_ms = post_qwen_json_with_latency(
            self._client,
            url=f"{self._rerank_base_url}/reranks",
            payload={
                "model": self._model_id,
                "query": goal,
                "documents": list(documents),
                "top_n": len(documents),
                "instruct": instruct,
            },
            model_id=self._model_id,
        )
        request_id = _request_id_from_body_or_headers(body, headers)
        usage = _validated_usage_from_body(body, self._model_id, headers)
        results = body.get("results", [])
        ranked_indexes, relevance_scores = _validate_rerank_results(
            results=results,
            expected_count=len(documents),
            provider_name="qwen-cloud",
            model_id=self._model_id,
            request_id=request_id,
            usage=usage,
        )
        return RerankResult(
            ranked_indexes=ranked_indexes,
            trace=ProviderTrace(
                provider_name="qwen-cloud",
                model_id=body.get("model", self._model_id),
                provider_role="rerank",
                request_purpose="precision_rerank_active_memory_candidates",
                input_item_count=len(documents),
                input_token_estimate=_estimate_tokens(goal + "\n" + "\n".join(documents)),
                output_item_count=len(ranked_indexes),
                latency_ms=latency_ms,
                is_live=True,
                deterministic_fallback_status="live_qwen",
                request_id=request_id,
                usage=usage,
            ),
            relevance_scores=relevance_scores,
        )


class QwenMemoryDecisionProvider:
    def __init__(
        self,
        client: QwenCloudHTTPClient,
        compatible_base_url: str,
        model_id: str = TEXT_MODEL,
    ) -> None:
        self._client = client
        self._compatible_base_url = compatible_base_url.rstrip("/")
        self._model_id = model_id

    def decide_memory_operation(
        self,
        event_text: str,
        candidate_payloads: list[dict[str, Any]],
        tool_schema: dict[str, Any],
    ) -> MemoryDecisionResult:
        prompt = _memory_decision_prompt(event_text, candidate_payloads, tool_schema)
        tool = _memory_decision_tool(tool_schema)
        tool_name = tool["function"]["name"]
        body, headers, latency_ms = post_qwen_json_with_latency(
            self._client,
            url=f"{self._compatible_base_url}/chat/completions",
            payload={
                "model": self._model_id,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "Use the decide_memory_operation tool exactly once. "
                            "Classify durable coding-agent memory lifecycle events. "
                            "Do not include secrets or unrelated text."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                "tools": [tool],
                "tool_choice": {
                    "type": "function",
                    "function": {"name": tool_name},
                },
                "enable_thinking": False,
                "temperature": 0,
                "max_tokens": 512,
            },
            model_id=self._model_id,
        )
        request_id = _request_id_from_body_or_headers(body, headers)
        usage = _validated_usage_from_body(body, self._model_id, headers)
        choices = body.get("choices")
        if (
            not isinstance(choices, list)
            or not choices
            or not isinstance(choices[0], dict)
            or not isinstance(choices[0].get("message"), dict)
        ):
            raise _malformed_success_response(
                model_id=self._model_id,
                body=body,
                headers=headers,
                detail="memory decision response must contain a message choice",
                usage=usage,
                latency_ms=latency_ms,
            )
        message = choices[0]["message"]
        try:
            tool_arguments = _parse_memory_decision_message(
                message=message,
                expected_tool_name=tool_name,
                model_id=self._model_id,
            )
        except ProviderError as exc:
            raise ProviderError.retryable(
                provider_name=exc.provider_name,
                model_id=self._model_id,
                message=exc.message,
                request_id=request_id,
                usage=usage,
                code="model_output_unparseable",
                latency_ms=latency_ms,
            ) from exc
        except (ValueError, RecursionError, OverflowError) as exc:
            raise ProviderError.retryable(
                provider_name="qwen-cloud",
                model_id=self._model_id,
                message="Qwen memory decision arguments did not contain valid JSON.",
                request_id=request_id,
                usage=usage,
                code="model_output_unparseable",
                latency_ms=latency_ms,
            ) from exc
        return MemoryDecisionResult(
            tool_arguments=tool_arguments,
            trace=ProviderTrace(
                provider_name="qwen-cloud",
                model_id=body.get("model", self._model_id),
                provider_role="memory_decision",
                request_purpose="extract_classify_and_judge_memory_lifecycle",
                input_item_count=1 + len(candidate_payloads),
                input_token_estimate=_estimate_tokens(prompt),
                output_item_count=1,
                latency_ms=latency_ms,
                is_live=True,
                deterministic_fallback_status="live_qwen",
                request_id=request_id,
                usage=usage,
                tool_arguments=tool_arguments,
            ),
        )


class ProviderMemoryDecider:
    def __init__(
        self,
        provider: MemoryDecisionProvider,
        tool_schema: dict[str, Any] | None = None,
    ) -> None:
        self._provider = provider
        self._tool_schema = tool_schema or {"name": "decide_memory_operation"}
        self.traces: list[ProviderTrace] = []

    def decide_memory_operation(
        self,
        request: Any,
        candidates: list[dict[str, Any]],
    ) -> dict[str, Any]:
        try:
            result = self._provider.decide_memory_operation(
                event_text=_event_payload_text(request),
                candidate_payloads=candidates,
                tool_schema=self._tool_schema,
            )
        except ProviderError as exc:
            self.traces.append(_memory_decision_error_trace(exc, request, candidates))
            if exc.retryable:
                raise RetryableObserveError(exc.message, code=exc.code) from exc
            raise TerminalObserveError(
                exc.message,
                code="provider_operator_action_required",
            ) from exc
        self.traces.append(result.trace)
        return result.tool_arguments

    def repair_memory_operation(
        self,
        request: Any,
        candidates: list[dict[str, Any]],
        validation_errors: list[str],
    ) -> dict[str, Any]:
        repair_schema = dict(self._tool_schema)
        repair_schema["repair_attempt"] = 1
        repair_schema["validation_errors"] = list(validation_errors)
        try:
            result = self._provider.decide_memory_operation(
                event_text=_event_payload_text(request),
                candidate_payloads=candidates,
                tool_schema=repair_schema,
            )
        except ProviderError as exc:
            self.traces.append(_memory_decision_error_trace(exc, request, candidates))
            if exc.retryable:
                raise RetryableObserveError(exc.message, code=exc.code) from exc
            raise TerminalObserveError(
                exc.message,
                code="provider_operator_action_required",
            ) from exc
        self.traces.append(result.trace)
        return result.tool_arguments


def _memory_decision_error_trace(
    error: ProviderError,
    request: Any,
    candidates: list[dict[str, Any]],
) -> ProviderTrace:
    event_text = _event_payload_text(request)
    is_live = error.provider_name == "qwen-cloud"
    return ProviderTrace(
        provider_name=error.provider_name,
        model_id=error.model_id,
        provider_role="memory_decision",
        request_purpose="extract_classify_and_judge_memory_lifecycle",
        input_item_count=1 + len(candidates),
        input_token_estimate=_estimate_tokens(event_text + "\n" + str(candidates)),
        output_item_count=0,
        latency_ms=error.latency_ms,
        is_live=is_live,
        deterministic_fallback_status=("live_qwen" if is_live else "fake_provider_error"),
        request_id=error.request_id,
        usage=error.usage,
    )


class ProviderRanker:
    def __init__(
        self,
        provider: RerankProvider,
        instruct: str | None = None,
    ) -> None:
        self._provider = provider
        self._instruct = instruct or (
            "Given a coding task, rank project context records by how necessary "
            "they are for completing the task correctly under a limited context budget."
        )
        self.traces: list[ProviderTrace] = []
        self.last_relevance_scores: dict[str, float] = {}

    def rank(self, goal: str, candidates: list[Any]) -> list[Any]:
        self.last_relevance_scores = {}
        if not candidates:
            return []
        documents = [document_for_candidate(candidate) for candidate in candidates]
        result = self._provider.rerank(goal=goal, documents=documents, instruct=self._instruct)
        self.traces.append(result.trace)
        if not isinstance(result.relevance_scores, dict):
            raise _rerank_failure(
                result.trace.provider_name,
                result.trace.model_id,
                "relevance scores must be a mapping",
                request_id=result.trace.request_id,
                usage=result.trace.usage,
            )
        _validate_rerank_permutation(
            result.ranked_indexes,
            len(candidates),
            result.trace.provider_name,
            result.trace.model_id,
            request_id=result.trace.request_id,
            usage=result.trace.usage,
        )
        _, validated_scores = _validate_rerank_results(
            results=[
                {"index": index, "relevance_score": score}
                for index, score in result.relevance_scores.items()
            ],
            expected_count=len(candidates),
            provider_name=result.trace.provider_name,
            model_id=result.trace.model_id,
            request_id=result.trace.request_id,
            usage=result.trace.usage,
        )
        self.last_relevance_scores = {
            str(getattr(candidates[index], "id", "")): score
            for index, score in validated_scores.items()
        }
        return [
            candidates[index]
            for index in sorted(
                range(len(candidates)),
                key=lambda index: (
                    -validated_scores[index],
                    -int(getattr(candidates[index], "source_project_event_seq", 0)),
                    str(getattr(candidates[index], "id", "")),
                ),
            )
        ]


def _zero_embedding() -> list[float]:
    return [0.0] * EMBEDDING_DIMENSION


def _keyword_tokens(text: str) -> list[str]:
    normalized = "".join(ch.lower() if ch.isalnum() else " " for ch in text)
    return [token for token in normalized.split() if token]


def _keyword_embedding(tokens: list[str]) -> list[float]:
    vector = [0.0] * EMBEDDING_DIMENSION
    for token in tokens:
        vector[_keyword_bucket(token)] += 1.0
    return vector


def _keyword_bucket(token: str) -> int:
    return sum((index + 1) * ord(ch) for index, ch in enumerate(token)) % EMBEDDING_DIMENSION


def _keyword_overlap_score(goal_tokens: list[str], document_tokens: list[str]) -> float:
    document_token_set = set(document_tokens)
    return float(sum(1 for token in goal_tokens if token in document_token_set))


def sanitized_provider_trace_records(traces: list[ProviderTrace]) -> list[dict[str, Any]]:
    return [trace.to_sanitized_record() for trace in traces]


def _event_payload_text(request: Any) -> str:
    return json.dumps(
        {
            "project_id": getattr(request, "project_id", ""),
            "session_id": getattr(request, "session_id", ""),
            "event_id": getattr(request, "event_id", ""),
            "source_ref": (
                f"{getattr(request, 'session_id', '')}:"
                f"{getattr(request, 'event_id', '')}"
            ),
            "sequence_no": getattr(request, "sequence_no", None),
            "actor": getattr(request, "actor", ""),
            "kind": getattr(request, "kind", ""),
            "observed_at": getattr(request, "observed_at", ""),
            "text": getattr(request, "text", ""),
        },
        sort_keys=True,
    )


def _embedding_request_purpose(text_type: str) -> str:
    if text_type == "query":
        return "candidate_memory_retrieval_query"
    return "candidate_memory_retrieval_document"


def _estimate_tokens(text: str) -> int:
    return max(1, (len(text) + 3) // 4)


def _safe_latency_ms(value: Any) -> int:
    return value if type(value) is int and value >= 0 else 0


def document_for_candidate(candidate: Any) -> str:
    memory_type = getattr(candidate, "type", "")
    scope_level = getattr(candidate, "scope_level", "")
    component = getattr(candidate, "component", None)
    subject = getattr(candidate, "subject", "")
    text = getattr(candidate, "text", "")
    scope = "project" if scope_level == "project" else f"{scope_level}:{component}"
    return f"type={memory_type}\nscope={scope}\nsubject={subject}\nmemory={text}"


def _request_id_from_body_or_headers(
    body: dict[str, Any],
    headers: dict[str, Any],
) -> str | None:
    return (
        body.get("request_id")
        or body.get("id")
        or headers.get("x-request-id")
        or headers.get("X-Request-Id")
    )


def _usage_from_body(body: dict[str, Any]) -> dict[str, Any]:
    usage = body.get("usage")
    return dict(usage) if isinstance(usage, dict) else {}


def _safe_usage_from_error_body(body: dict[str, Any]) -> dict[str, Any]:
    usage = _usage_from_body(body)
    for token_field in (
        "input_tokens",
        "prompt_tokens",
        "output_tokens",
        "completion_tokens",
        "total_tokens",
    ):
        if token_field in usage:
            try:
                _nonnegative_token_count(usage[token_field])
            except ValueError:
                return {}
    return usage


def _validated_usage_from_body(
    body: dict[str, Any],
    model_id: str,
    headers: dict[str, Any],
) -> dict[str, Any]:
    raw_usage = body.get("usage")
    if raw_usage is None:
        return {}
    if not isinstance(raw_usage, dict):
        raise _malformed_success_response(
            model_id=model_id,
            body=body,
            headers=headers,
            detail="usage must be an object",
        )
    for token_field in (
        "input_tokens",
        "prompt_tokens",
        "output_tokens",
        "completion_tokens",
        "total_tokens",
    ):
        if token_field in raw_usage:
            value = raw_usage[token_field]
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise _malformed_success_response(
                    model_id=model_id,
                    body=body,
                    headers=headers,
                    detail=f"usage.{token_field} must be a non-negative integer",
                )
    return dict(raw_usage)


def _normalized_token_usage(usage: dict[str, Any], is_live: bool) -> dict[str, Any]:
    if not is_live or not usage:
        return {
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "reported_by_provider": False,
        }
    input_tokens = _nonnegative_token_count(
        usage.get("input_tokens", usage.get("prompt_tokens", 0))
    )
    output_tokens = _nonnegative_token_count(
        usage.get("output_tokens", usage.get("completion_tokens", 0))
    )
    total_tokens = _nonnegative_token_count(
        usage.get("total_tokens", input_tokens + output_tokens)
    )
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "reported_by_provider": True,
    }


def _nonnegative_token_count(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("invalid_provider_token_usage")
    return value


def _http_provider_error_code(status_code: int) -> str:
    if status_code == 408:
        return "provider_timeout"
    if status_code == 429:
        return "provider_rate_limit"
    if status_code >= 500:
        return "provider_server_error"
    return "provider_operator_action_required"


def _malformed_success_response(
    model_id: str,
    body: dict[str, Any],
    headers: dict[str, Any],
    detail: str,
    usage: dict[str, Any] | None = None,
    latency_ms: int = 0,
) -> ProviderError:
    return ProviderError.retryable(
        provider_name="qwen-cloud",
        model_id=model_id,
        message=f"Provider HTTP response structure was invalid: {detail}.",
        request_id=_request_id_from_body_or_headers(body, headers),
        usage=usage or {},
        code="provider_http_response_unparseable",
        latency_ms=latency_ms,
    )


def _validate_rerank_results(
    results: Any,
    expected_count: int,
    provider_name: str,
    model_id: str,
    request_id: str | None = None,
    usage: dict[str, Any] | None = None,
) -> tuple[list[int], dict[int, float]]:
    if not isinstance(results, list):
        raise _rerank_failure(
            provider_name, model_id, "results must be a list", request_id, usage
        )
    indexes: list[int] = []
    scores: dict[int, float] = {}
    for result in results:
        if not isinstance(result, dict) or set(result) != {"index", "relevance_score"}:
            raise _rerank_failure(
                provider_name,
                model_id,
                "each result must contain only index and relevance_score",
                request_id,
                usage,
            )
        index = result["index"]
        score = result["relevance_score"]
        if isinstance(index, bool) or not isinstance(index, int):
            raise _rerank_failure(
                provider_name, model_id, "index must be an integer", request_id, usage
            )
        if isinstance(score, bool) or not isinstance(score, (int, float)):
            raise _rerank_failure(
                provider_name, model_id, "score must be numeric", request_id, usage
            )
        numeric_score = float(score)
        if not math.isfinite(numeric_score):
            raise _rerank_failure(
                provider_name, model_id, "score must be finite", request_id, usage
            )
        indexes.append(index)
        if index in scores:
            raise _rerank_failure(
                provider_name, model_id, "indexes must be unique", request_id, usage
            )
        scores[index] = numeric_score
    _validate_rerank_permutation(
        indexes, expected_count, provider_name, model_id, request_id, usage
    )
    ranked_indexes = sorted(indexes, key=lambda index: (-scores[index], index))
    return ranked_indexes, scores


def _validate_rerank_permutation(
    indexes: list[int],
    expected_count: int,
    provider_name: str = "rerank-provider",
    model_id: str = RERANK_MODEL,
    request_id: str | None = None,
    usage: dict[str, Any] | None = None,
) -> None:
    if (
        not isinstance(indexes, list)
        or any(isinstance(index, bool) or not isinstance(index, int) for index in indexes)
        or len(indexes) != expected_count
        or set(indexes) != set(range(expected_count))
    ):
        raise _rerank_failure(
            provider_name,
            model_id,
            "indexes must be the complete 0..N-1 permutation",
            request_id,
            usage,
        )


def _rerank_failure(
    provider_name: str,
    model_id: str,
    detail: str,
    request_id: str | None = None,
    usage: dict[str, Any] | None = None,
) -> ProviderError:
    return ProviderError.retryable(
        provider_name=provider_name,
        model_id=model_id,
        message=f"rerank_failure: {detail}",
        request_id=request_id,
        usage=usage,
        code="rerank_failure",
    )


def _loads_json_or_empty(raw_text: str) -> dict[str, Any]:
    try:
        parsed = json.loads(raw_text)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _provider_error_message(body: dict[str, Any], raw_body: str) -> str:
    error = body.get("error")
    if isinstance(error, dict) and error.get("message"):
        return str(error["message"])
    if body.get("message"):
        return str(body["message"])
    return raw_body[:300]


def _redact_secret(text: str, secret: str) -> str:
    if secret:
        return text.replace(secret, "[redacted]")
    return text


def _parse_json_object(content: str) -> dict[str, Any]:
    stripped = content.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        if stripped.startswith("json"):
            stripped = stripped[4:].strip()
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ProviderError.terminal(
            provider_name="qwen-cloud",
            model_id="qwen-text",
            message="Qwen memory decision response did not contain a JSON object.",
        )
    parsed = json.loads(stripped[start : end + 1])
    if not isinstance(parsed, dict):
        raise ProviderError.terminal(
            provider_name="qwen-cloud",
            model_id="qwen-text",
            message="Qwen memory decision response JSON was not an object.",
        )
    return parsed


def _parse_memory_decision_message(
    message: dict[str, Any],
    expected_tool_name: str,
    model_id: str,
) -> dict[str, Any]:
    tool_calls = message.get("tool_calls")
    if isinstance(tool_calls, list):
        for tool_call in tool_calls:
            if not isinstance(tool_call, dict):
                continue
            function = tool_call.get("function")
            if not isinstance(function, dict):
                continue
            if function.get("name") != expected_tool_name:
                continue
            arguments = function.get("arguments")
            if isinstance(arguments, dict):
                return _normalize_memory_decision_arguments(dict(arguments), model_id)
            if isinstance(arguments, str):
                return _normalize_memory_decision_arguments(
                    _parse_json_object(arguments),
                    model_id,
                )
    content = message.get("content", "{}")
    if not isinstance(content, str):
        raise ProviderError.terminal(
            provider_name="qwen-cloud",
            model_id=model_id,
            message="Qwen memory decision response did not include tool arguments or JSON content.",
        )
    return _normalize_memory_decision_arguments(_parse_json_object(content), model_id)


def _normalize_memory_decision_arguments(
    arguments: dict[str, Any],
    model_id: str,
) -> dict[str, Any]:
    normalized = dict(arguments)
    normalized["memory"] = _normalize_memory_argument(
        normalized.get("memory"),
        model_id,
    )
    normalized["duplicate_of_candidate_index"] = _normalize_optional_index(
        normalized.get("duplicate_of_candidate_index"),
        model_id,
        field_name="duplicate_of_candidate_index",
    )
    normalized["supersedes_candidate_indexes"] = _normalize_index_list(
        normalized.get("supersedes_candidate_indexes", []),
        model_id,
        field_name="supersedes_candidate_indexes",
    )
    return normalized


def _normalize_memory_argument(value: Any, model_id: str) -> Any:
    if value is None:
        return None
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped or stripped.lower() == "null":
            return None
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise ProviderError.terminal(
                provider_name="qwen-cloud",
                model_id=model_id,
                message="Qwen memory decision returned string memory that was not valid JSON.",
            ) from exc
        if isinstance(parsed, dict):
            return dict(parsed)
        return parsed
    return value


def _normalize_optional_index(value: Any, model_id: str, field_name: str) -> Any:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return value


def _normalize_index_list(value: Any, model_id: str, field_name: str) -> Any:
    if value is None or value == "":
        return []
    if not isinstance(value, list):
        return value
    normalized: list[Any] = []
    for item in value:
        index = _normalize_optional_index(item, model_id, field_name=field_name)
        if index is not None:
            normalized.append(index)
    return normalized


def _memory_decision_tool(tool_schema: dict[str, Any]) -> dict[str, Any]:
    name = tool_schema.get("name") if isinstance(tool_schema.get("name"), str) else None
    description = (
        tool_schema.get("description")
        if isinstance(tool_schema.get("description"), str)
        else None
    )
    parameters = tool_schema.get("parameters")
    if not isinstance(parameters, dict):
        parameters = _default_memory_decision_parameters()
    return {
        "type": "function",
        "function": {
            "name": name or "decide_memory_operation",
            "description": description
            or "Choose one memory lifecycle operation for the observed event.",
            "parameters": parameters,
        },
    }


def _default_memory_decision_parameters() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "operation",
            "memory",
            "duplicate_of_candidate_index",
            "supersedes_candidate_indexes",
            "reason",
        ],
        "properties": {
            "operation": {
                "type": "string",
                "enum": ["no_op", "duplicate", "write"],
                "description": (
                    "Use write for durable project memory, duplicate when an "
                    "active candidate already captures the same memory, and "
                    "no_op only for transient or non-memory events."
                ),
            },
            "memory": {
                "description": (
                    "Canonical memory to write when operation is write; null "
                    "for no_op or duplicate."
                ),
                "anyOf": [
                    {"type": "null"},
                    {
                        "type": "object",
                        "additionalProperties": False,
                        "required": [
                            "type",
                            "subject",
                            "text",
                            "scope_level",
                            "component",
                        ],
                        "properties": {
                            "type": {
                                "type": "string",
                                "enum": ["decision", "preference", "lesson"],
                                "description": (
                                    "decision for chosen implementation policy, "
                                    "preference for user project constraints, "
                                    "lesson for reusable implementation learning."
                                ),
                            },
                            "subject": {
                                "type": "string",
                                "description": (
                                    "Stable subject such as retry_policy, "
                                    "dependency_policy, auth_policy, "
                                    "cache_policy, config_policy, or "
                                    "serializer_policy."
                                ),
                            },
                            "text": {
                                "type": "string",
                                "description": (
                                    "Short normalized memory text, not a "
                                    "summary of the whole event."
                                ),
                            },
                            "scope_level": {
                                "type": "string",
                                "enum": ["project", "component"],
                                "description": (
                                    "preference memories use project scope; "
                                    "decision and lesson memories use component scope."
                                ),
                            },
                            "component": {
                                "anyOf": [{"type": "string"}, {"type": "null"}],
                                "description": (
                                    "Component name for component-scoped memory; "
                                    "null for project-scoped preferences."
                                ),
                            },
                        },
                    },
                ]
            },
            "duplicate_of_candidate_index": {
                "anyOf": [{"type": "integer"}, {"type": "null"}],
                "description": (
                    "candidate_index of an active candidate that already "
                    "captures this memory; otherwise null."
                ),
            },
            "supersedes_candidate_indexes": {
                "type": "array",
                "items": {"type": "integer"},
                "description": (
                    "candidate_index values for older active memories replaced "
                    "by a newer write with the same type, subject, scope, and component."
                ),
            },
            "reason": {
                "type": "string",
                "description": "Short machine-readable reason for the operation.",
            },
        },
    }


def _rule_based_memory_operation(
    event_text: str,
    candidate_payloads: list[dict[str, Any]],
) -> dict[str, Any]:
    text = event_text.lower()
    if _mentions_retry(text) and "three attempts" in text and "fixed" in text:
        return _write_memory_operation(
            memory_type="decision",
            subject="retry_policy",
            text="Use three attempts with a fixed 100 ms delay.",
            scope_level="component",
            component="retry",
            reason="old_retry_policy",
        )
    if _mentions_retry(text) and "five attempts" in text and "exponential" in text:
        prior_index = _candidate_index(
            candidate_payloads,
            memory_type="decision",
            subject="retry_policy",
            component="retry",
        )
        return _write_memory_operation(
            memory_type="decision",
            subject="retry_policy",
            text="Use five attempts with exponential backoff.",
            scope_level="component",
            component="retry",
            reason="updated_retry_policy",
            supersedes_candidate_indexes=[] if prior_index is None else [prior_index],
        )
    if "dependency-free" in text or "do not add new dependencies" in text:
        existing_index = _candidate_index(
            candidate_payloads,
            memory_type="preference",
            subject="dependency_policy",
            component=None,
        )
        if existing_index is not None:
            return _duplicate_operation(existing_index, "same_dependency_preference")
        return _write_memory_operation(
            memory_type="preference",
            subject="dependency_policy",
            text="Do not add new dependencies.",
            scope_level="project",
            component=None,
            reason="dependency_preference",
        )
    if "do not change pyproject" in text:
        existing_index = _candidate_index(
            candidate_payloads,
            memory_type="preference",
            subject="dependency_policy",
            component=None,
        )
        if existing_index is not None:
            return _duplicate_operation(existing_index, "same_dependency_preference")
        return _write_memory_operation(
            memory_type="preference",
            subject="dependency_policy",
            text="Do not add new dependencies.",
            scope_level="project",
            component=None,
            reason="dependency_preference",
        )
    if "bearer token validation" in text or "auth uses bearer" in text:
        return _write_memory_operation(
            memory_type="decision",
            subject="auth_policy",
            text="Use bearer token validation in auth.",
            scope_level="component",
            component="auth",
            reason="auth_policy",
        )
    return _no_op_operation("non_memory_event")


def _mentions_retry(text: str) -> bool:
    return "retry" in text or "rate-limit" in text or "rate limit" in text


def _write_memory_operation(
    memory_type: str,
    subject: str,
    text: str,
    scope_level: str,
    component: str | None,
    reason: str,
    supersedes_candidate_indexes: list[int] | None = None,
) -> dict[str, Any]:
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
        "supersedes_candidate_indexes": list(supersedes_candidate_indexes or []),
        "reason": reason,
    }


def _duplicate_operation(candidate_index: int, reason: str) -> dict[str, Any]:
    return {
        "operation": "duplicate",
        "memory": None,
        "duplicate_of_candidate_index": candidate_index,
        "supersedes_candidate_indexes": [],
        "reason": reason,
    }


def _no_op_operation(reason: str) -> dict[str, Any]:
    return {
        "operation": "no_op",
        "memory": None,
        "duplicate_of_candidate_index": None,
        "supersedes_candidate_indexes": [],
        "reason": reason,
    }


def _candidate_index(
    candidate_payloads: list[dict[str, Any]],
    memory_type: str,
    subject: str,
    component: str | None,
) -> int | None:
    for fallback_index, candidate in enumerate(candidate_payloads):
        if (
            candidate.get("type") == memory_type
            and candidate.get("subject") == subject
            and _candidate_component(candidate) == component
        ):
            return int(candidate.get("candidate_index", fallback_index))
    return None


def _candidate_component(candidate: dict[str, Any]) -> str | None:
    component = candidate.get("component")
    if isinstance(component, str) or component is None:
        if component is not None:
            return component
    scope = candidate.get("scope")
    if isinstance(scope, dict):
        scoped_component = scope.get("component")
        if isinstance(scoped_component, str):
            return scoped_component
    return component if isinstance(component, str) else None


def _memory_decision_prompt(
    event_text: str,
    candidate_payloads: list[dict[str, Any]],
    tool_schema: dict[str, Any],
) -> str:
    event = _memory_decision_event(event_text)
    return json.dumps(
        {
            "task": "decide_memory_operation",
            "allowed_operations": ["no_op", "duplicate", "write"],
            "event": event,
            "decision_policy": {
                "must_write_when": [
                    "actor is user and the text states a durable coding decision",
                    "actor is user and the text sets a durable project preference or constraint",
                    "the text records a reusable implementation lesson from a tool/test result",
                ],
                "must_supersede_when": [
                    "a newer decision has the same type, subject, scope_level, and component as an older active candidate",
                    "the event says the new policy replaces an earlier decision",
                ],
                "must_duplicate_when": [
                    "an active candidate already captures the same preference or decision",
                ],
                "must_no_op_when": [
                    "the event is assistant narration, transient progress, or unrelated tool chatter",
                    "the event asks for the current handoff task but does not add durable memory",
                ],
            },
            "memory_guidelines": [
                "write when the event states a durable coding decision that should guide future agent work",
                "write preference when the user sets a durable project constraint",
                "write project-scoped preference when a user says not to add new dependencies",
                "write lesson when the event captures a reusable implementation lesson",
                "duplicate when an existing candidate already captures the same active memory",
                "use supersedes_candidate_indexes when a newer decision replaces older active memory with the same type and scope",
                "use no_op only for transient status, tool chatter, or events without reusable future value",
            ],
            "memory_shape_guidelines": {
                "decision": "component scope with subject such as retry_policy, auth_policy, cache_policy, config_policy, or ci_policy",
                "preference": "project scope with null component",
                "lesson": "component scope for reusable implementation lessons",
            },
            "examples": [
                {
                    "event_text": "Use five attempts with exponential backoff in the retry helper.",
                    "operation": "write",
                    "memory": {
                        "type": "decision",
                        "subject": "retry_policy",
                        "scope_level": "component",
                        "component": "retry",
                    },
                },
                {
                    "event_text": "Do not add new dependencies for CI or test-runner fixes.",
                    "operation": "write",
                    "memory": {
                        "type": "preference",
                        "subject": "dependency_policy",
                        "scope_level": "project",
                        "component": None,
                    },
                },
                {
                    "event_text": "Treat CI JIT crashes as real bugs; fail forward and fix instead of retrying around them.",
                    "operation": "write",
                    "memory": {
                        "type": "decision",
                        "subject": "ci_policy",
                        "scope_level": "component",
                        "component": "ci_policy",
                    },
                },
                {
                    "event_text": "I can inspect retry.py and the public retry tests.",
                    "operation": "no_op",
                },
            ],
            "candidate_payloads": candidate_payloads,
            "tool_schema": tool_schema,
            "output_contract": {
                "operation": "no_op | duplicate | write",
                "memory": "object or null",
                "duplicate_of_candidate_index": "integer or null",
                "supersedes_candidate_indexes": "list of integers",
                "reason": "short string",
            },
        },
        sort_keys=True,
    )


def _memory_decision_event(event_text: str) -> dict[str, Any]:
    try:
        parsed = json.loads(event_text)
    except json.JSONDecodeError:
        parsed = {}
    if not isinstance(parsed, dict) or not isinstance(parsed.get("text"), str):
        parsed = {"text": event_text}
    return {
        "project_id": parsed.get("project_id", ""),
        "session_id": parsed.get("session_id", ""),
        "event_id": parsed.get("event_id", ""),
        "source_ref": parsed.get("source_ref", ""),
        "sequence_no": parsed.get("sequence_no"),
        "actor": parsed.get("actor", ""),
        "kind": parsed.get("kind", ""),
        "observed_at": parsed.get("observed_at", ""),
        "text": parsed.get("text", ""),
    }
