from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math
import re
import sqlite3
import threading
from typing import Any

from recallpack.locking import ProjectTurn, ProjectTurnstileRegistry
from recallpack.memory import MemoryRecord
from recallpack.write_candidates import (
    EMBEDDING_DIMENSION,
    EMBEDDING_MODEL,
    build_candidate_payloads,
    select_write_candidates,
)


@dataclass(frozen=True)
class ObserveRequest:
    project_id: str
    session_id: str
    event_id: str
    sequence_no: int
    actor: str
    kind: str
    observed_at: str
    text: str


@dataclass(frozen=True)
class ObserveResponse:
    status_code: int
    error: str | None = None
    final_result: dict[str, object] | None = None
    event_internal_id: str | None = None
    project_event_seq: int | None = None
    attempt_no: int | None = None
    replayed: bool = False
    run_id: str | None = None
    provider_mode: str | None = None
    repaired: bool = False
    request_id_present: bool = False


class RetryableObserveError(Exception):
    def __init__(self, message: str, code: str | None = None) -> None:
        super().__init__(message)
        self.code = code or (
            message
            if re.fullmatch(r"[a-z][a-z0-9_]{0,63}", message)
            else "provider_network_error"
        )


class TerminalObserveError(Exception):
    def __init__(self, message: str, code: str = "provider_operator_action_required") -> None:
        super().__init__(message)
        self.code = code


_CLAIM_COORDINATOR = threading.Lock()
_DEFAULT_TURNSTILES = ProjectTurnstileRegistry()


class ObserveService:
    def __init__(self, store: object, decider: object) -> None:
        self._store = store
        self._decider = decider

    def observe(self, request: ObserveRequest) -> ObserveResponse:
        result = self._store.claim_event(request)
        if result == "pending":
            return ObserveResponse(status_code=202)
        if result == "idempotency_conflict":
            return ObserveResponse(status_code=409, error="idempotency_conflict")
        if result == "out_of_order":
            return ObserveResponse(status_code=409, error="out_of_order")
        raise RuntimeError(f"unsupported observe claim result: {result}")


class ObserveRuntime:
    def __init__(
        self,
        store: object,
        decider: object,
        components: set[str] | None = None,
        embedding_provider: object | None = None,
        turnstile_registry: ProjectTurnstileRegistry | None = None,
    ) -> None:
        self._store = store
        self._decider = decider
        self._components = components or {"retry", "auth", "cache", "config"}
        if embedding_provider is None:
            from recallpack.providers import DeterministicKeywordEmbeddingProvider

            embedding_provider = DeterministicKeywordEmbeddingProvider()
        self._embedding_provider = embedding_provider
        self._turnstiles = turnstile_registry or _DEFAULT_TURNSTILES

    def observe(self, request: ObserveRequest, now: int) -> ObserveResponse:
        with _CLAIM_COORDINATOR:
            try:
                claim = self._store.claim_event(
                    request,
                    now=now,
                    provider_mode=_provider_mode(
                        self._decider, self._embedding_provider
                    ),
                )
            except sqlite3.Error as exc:
                return ObserveResponse(
                    status_code=503,
                    error=_sqlite_error_code(exc),
                )
            if claim.status_code != 202:
                return ObserveResponse(
                    status_code=claim.status_code,
                    error=claim.error,
                    final_result=claim.final_result,
                    event_internal_id=claim.event_internal_id,
                    project_event_seq=claim.project_event_seq,
                    attempt_no=claim.attempt_no,
                    replayed=claim.status_code == 200,
                    run_id=claim.run_id,
                    provider_mode=claim.provider_mode,
                    repaired=claim.repaired,
                    request_id_present=claim.request_id_present,
                )
            if not claim.owns_attempt:
                return self._response_for_claim(claim, 202)
            ticket = self._turnstiles.register(
                ProjectTurn(
                    project_id=request.project_id,
                    project_event_seq=int(claim.project_event_seq),
                    attempt_no=int(claim.attempt_no),
                    lease_token=str(claim.lease_token),
                )
            )

        with ticket:
            try:
                if not self._store.owns_event_attempt(
                    claim.event_internal_id,
                    claim.lease_token,
                    claim.attempt_no,
                ):
                    return self._response_for_claim(claim, 409, error="lease_lost")
                return self._observe_owned(request, claim)
            except sqlite3.Error as exc:
                return self._response_for_claim(
                    claim,
                    503,
                    error=_sqlite_error_code(exc),
                )

    @staticmethod
    def _response_for_claim(
        claim: object,
        status_code: int,
        *,
        error: str | None = None,
        final_result: dict[str, object] | None = None,
        repaired: bool | None = None,
        request_id_present: bool | None = None,
    ) -> ObserveResponse:
        return ObserveResponse(
            status_code=status_code,
            error=error,
            final_result=final_result,
            event_internal_id=claim.event_internal_id,
            project_event_seq=claim.project_event_seq,
            attempt_no=claim.attempt_no,
            run_id=claim.run_id,
            provider_mode=claim.provider_mode,
            repaired=claim.repaired if repaired is None else repaired,
            request_id_present=(
                claim.request_id_present
                if request_id_present is None
                else request_id_present
            ),
        )

    def _observe_owned(self, request: ObserveRequest, claim: object) -> ObserveResponse:
        from recallpack.providers import ProviderError

        trace_offsets = _trace_offsets(self._decider, self._embedding_provider)
        validation: list[dict[str, object]] = []
        operation: object | None = None
        repaired = False
        try:
            scored_candidates = select_write_candidates(
                store=self._store,
                project_id=request.project_id,
                raw_event=request.text,
                embedding_provider=self._embedding_provider,
                limit=8,
            )
            active_candidates = [memory for memory, _ in scored_candidates]
            candidate_payloads = build_candidate_payloads(scored_candidates, limit=8)
            operation = self._decider.decide_memory_operation(request, candidate_payloads)
        except ValueError as exc:
            error = str(exc)
            if error == "memory_embedding_backfill_required":
                return self._fail_owned_attempt(
                    claim,
                    error,
                    status_code=409,
                    run_evidence=_attempt_evidence(
                        self._decider,
                        self._embedding_provider,
                        trace_offsets,
                        operation,
                        validation,
                    ),
                )
            return self._fail_owned_attempt(
                claim,
                "provider_http_response_unparseable",
                run_evidence=_attempt_evidence(
                    self._decider,
                    self._embedding_provider,
                    trace_offsets,
                    operation,
                    validation,
                ),
            )
        except ProviderError as exc:
            error = _provider_observe_error(exc)
            evidence = _attempt_evidence(
                self._decider,
                self._embedding_provider,
                trace_offsets,
                operation,
                validation,
            )
            _append_provider_error_evidence(
                evidence,
                exc,
                role="embedding",
                purpose="retrieve_write_candidates",
            )
            return self._fail_owned_attempt(
                claim,
                error,
                detail=str(exc),
                run_evidence=evidence,
            )
        except RetryableObserveError as exc:
            if exc.code == "model_output_unparseable" and hasattr(
                self._decider, "repair_memory_operation"
            ):
                validation.append(
                    {"stage": "initial", "errors": ["model_output_unparseable"]}
                )
                repaired = True
                try:
                    operation = self._decider.repair_memory_operation(
                        request,
                        candidate_payloads,
                        ["model_output_unparseable"],
                    )
                except RetryableObserveError as repair_exc:
                    error = (
                        "model_output_unparseable_after_repair"
                        if repair_exc.code == "model_output_unparseable"
                        else repair_exc.code
                    )
                    validation.append(
                        {"stage": "repair", "errors": [repair_exc.code]}
                    )
                    return self._fail_owned_attempt(
                        claim,
                        error,
                        detail=str(repair_exc),
                        run_evidence=_attempt_evidence(
                            self._decider,
                            self._embedding_provider,
                            trace_offsets,
                            operation,
                            validation,
                        ),
                    )
                except TerminalObserveError as repair_exc:
                    return self._fail_owned_attempt(
                        claim,
                        repair_exc.code,
                        detail=str(repair_exc),
                        run_evidence=_attempt_evidence(
                            self._decider,
                            self._embedding_provider,
                            trace_offsets,
                            operation,
                            validation,
                        ),
                    )
            else:
                return self._fail_owned_attempt(
                    claim,
                    exc.code,
                    detail=str(exc),
                    run_evidence=_attempt_evidence(
                        self._decider,
                        self._embedding_provider,
                        trace_offsets,
                        operation,
                        validation,
                    ),
                )
        except TerminalObserveError as exc:
            return self._fail_owned_attempt(
                claim,
                exc.code,
                detail=str(exc),
                run_evidence=_attempt_evidence(
                    self._decider,
                    self._embedding_provider,
                    trace_offsets,
                    operation,
                    validation,
                ),
            )
        normalized, errors = _normalize_operation_with_errors(
            operation,
            request=request,
            project_event_seq=int(claim.project_event_seq or request.sequence_no),
            candidates=active_candidates,
            components=self._components,
        )
        validation.append({"stage": "repair" if repaired else "initial", "errors": errors})
        if errors and not repaired and hasattr(self._decider, "repair_memory_operation"):
            repaired = True
            try:
                operation = self._decider.repair_memory_operation(
                    request,
                    candidate_payloads,
                    errors,
                )
            except RetryableObserveError as exc:
                error = (
                    "model_output_unparseable_after_repair"
                    if exc.code == "model_output_unparseable"
                    else exc.code
                )
                validation.append({"stage": "repair", "errors": [exc.code]})
                return self._fail_owned_attempt(
                    claim,
                    error,
                    detail=str(exc),
                    run_evidence=_attempt_evidence(
                        self._decider,
                        self._embedding_provider,
                        trace_offsets,
                        operation,
                        validation,
                    ),
                )
            except TerminalObserveError as exc:
                return self._fail_owned_attempt(
                    claim,
                    exc.code,
                    detail=str(exc),
                    run_evidence=_attempt_evidence(
                        self._decider,
                        self._embedding_provider,
                        trace_offsets,
                        operation,
                        validation,
                    ),
                )
            normalized, repair_errors = _normalize_operation_with_errors(
                operation,
                request=request,
                project_event_seq=int(claim.project_event_seq or request.sequence_no),
                candidates=active_candidates,
                components=self._components,
            )
            validation.append({"stage": "repair", "errors": repair_errors})

        run_evidence = _attempt_evidence(
            self._decider,
            self._embedding_provider,
            trace_offsets,
            operation,
            validation,
        )
        if normalized.memory is None:
            completed = self._store.complete_event(
                event_internal_id=claim.event_internal_id,
                lease_token=claim.lease_token,
                attempt_no=claim.attempt_no,
                final_result=normalized.final_result,
                run_evidence=run_evidence,
            )
        else:
            if self._store.has_newer_active_lifecycle_memory(
                request.project_id,
                int(claim.project_event_seq),
                normalized.memory,
            ):
                normalized = _terminal_no_op("stale_project_event")
                completed = self._store.complete_event(
                    event_internal_id=claim.event_internal_id,
                    lease_token=claim.lease_token,
                    attempt_no=claim.attempt_no,
                    final_result=normalized.final_result,
                    run_evidence=run_evidence,
                )
                if not completed:
                    return self._response_for_claim(claim, 409, error="lease_lost")
                return self._response_for_claim(
                    claim,
                    200,
                    final_result=normalized.final_result,
                    repaired=repaired,
                    request_id_present=_evidence_has_request_id(run_evidence),
                )
            document = _embedding_document(normalized.memory)
            try:
                embedding_result = self._embedding_provider.embed_document(document)
                embedding = _embedding_metadata(embedding_result, document)
            except ProviderError as exc:
                error = _provider_observe_error(exc)
                evidence = _attempt_evidence(
                    self._decider,
                    self._embedding_provider,
                    trace_offsets,
                    operation,
                    validation,
                )
                _append_provider_error_evidence(
                    evidence,
                    exc,
                    role="embedding",
                    purpose="embed_normalized_memory_document",
                )
                return self._fail_owned_attempt(
                    claim,
                    error,
                    detail=str(exc),
                    run_evidence=evidence,
                )
            except ValueError:
                return self._fail_owned_attempt(
                    claim,
                    "provider_http_response_unparseable",
                    run_evidence=_attempt_evidence(
                        self._decider,
                        self._embedding_provider,
                        trace_offsets,
                        operation,
                        validation,
                    ),
                )
            run_evidence = _attempt_evidence(
                self._decider,
                self._embedding_provider,
                trace_offsets,
                operation,
                validation,
            )
            completed_result = self._store.complete_observe_operation(
                event_internal_id=claim.event_internal_id,
                lease_token=claim.lease_token,
                attempt_no=claim.attempt_no,
                final_result=normalized.final_result,
                memory=normalized.memory,
                supersedes_memory_ids=normalized.supersedes_memory_ids,
                embedding=embedding,
                run_evidence=run_evidence,
            )
            completed = completed_result is not None
            if completed_result is not None:
                normalized = _NormalizedOperation(
                    final_result=completed_result,
                    memory=normalized.memory,
                    supersedes_memory_ids=normalized.supersedes_memory_ids,
                )
        if not completed:
            return self._response_for_claim(claim, 409, error="lease_lost")
        return self._response_for_claim(
            claim,
            200,
            final_result=normalized.final_result,
            repaired=repaired,
            request_id_present=_evidence_has_request_id(run_evidence),
        )

    def _fail_owned_attempt(
        self,
        claim: object,
        error: str,
        *,
        status_code: int = 503,
        detail: str | None = None,
        run_evidence: dict[str, Any] | None = None,
    ) -> ObserveResponse:
        failed = self._store.fail_retryable_event(
            event_internal_id=claim.event_internal_id,
            lease_token=claim.lease_token,
            attempt_no=claim.attempt_no,
            error=error,
            run_evidence=run_evidence,
            error_detail=detail,
        )
        if not failed:
            return self._response_for_claim(claim, 409, error="lease_lost")
        return self._response_for_claim(
            claim,
            status_code,
            error=error,
            repaired=_evidence_was_repaired(run_evidence),
            request_id_present=_evidence_has_request_id(run_evidence),
        )


@dataclass(frozen=True)
class _NormalizedOperation:
    final_result: dict[str, object]
    memory: dict[str, object] | None
    supersedes_memory_ids: list[str]


def _embedding_document(memory: dict[str, object]) -> str:
    scope = (
        "project"
        if memory["scope_level"] == "project"
        else f"{memory['scope_level']}:{memory['component']}"
    )
    return (
        f"type={memory['type']}\n"
        f"scope={scope}\n"
        f"subject={memory['subject']}\n"
        f"memory={memory['text']}"
    )


def _embedding_metadata(result: object, document: str) -> dict[str, object]:
    vector = getattr(result, "embedding", None)
    trace = getattr(result, "trace", None)
    if (
        getattr(result, "text_type", None) != "document"
        or getattr(trace, "model_id", None) != EMBEDDING_MODEL
        or not isinstance(vector, list)
        or len(vector) != EMBEDDING_DIMENSION
        or not all(
            not isinstance(value, bool)
            and isinstance(value, (int, float))
            and math.isfinite(value)
            for value in vector
        )
        or not any(float(value) != 0.0 for value in vector)
    ):
        raise ValueError("invalid_document_embedding")
    return {
        "vector": [float(value) for value in vector],
        "model": EMBEDDING_MODEL,
        "dimension": EMBEDDING_DIMENSION,
        "document_hash": hashlib.sha256(document.encode("utf-8")).hexdigest(),
        "record_schema_version": 4,
    }


def _normalize_operation(
    operation: object,
    request: ObserveRequest,
    project_event_seq: int,
    candidates: list[MemoryRecord],
    components: set[str],
) -> _NormalizedOperation:
    if not isinstance(operation, dict) or "memories" in operation:
        return _terminal_no_op("invalid_tool_output")

    op = operation.get("operation")
    if op == "no_op":
        return _normalize_no_op(operation)
    if op == "duplicate":
        return _normalize_duplicate(operation, candidates)
    if op == "write":
        return _normalize_write(operation, request, project_event_seq, candidates, components)
    return _terminal_no_op("invalid_tool_output")


def _normalize_operation_with_errors(
    operation: object,
    request: ObserveRequest,
    project_event_seq: int,
    candidates: list[MemoryRecord],
    components: set[str],
) -> tuple[_NormalizedOperation, list[str]]:
    normalized = _normalize_operation(
        operation,
        request=request,
        project_event_seq=project_event_seq,
        candidates=candidates,
        components=components,
    )
    if not isinstance(operation, dict) or set(operation) != {
        "operation",
        "memory",
        "duplicate_of_candidate_index",
        "supersedes_candidate_indexes",
        "reason",
    }:
        return normalized, ["invalid_tool_output"]
    requested_operation = operation.get("operation")
    normalized_operation = normalized.final_result.get("operation")
    if requested_operation == "no_op" and normalized_operation == "no_op":
        if normalized.final_result.get("reason") == operation.get("reason"):
            return normalized, []
    elif requested_operation == "duplicate" and normalized_operation == "duplicate":
        return normalized, []
    elif requested_operation == "write" and normalized_operation in {"write", "duplicate"}:
        return normalized, []
    reason = normalized.final_result.get("reason")
    return normalized, [reason if isinstance(reason, str) else "invalid_tool_output"]


def _normalize_no_op(operation: dict[str, object]) -> _NormalizedOperation:
    if operation.get("operation") == "no_op":
        memory = operation.get("memory")
        duplicate = operation.get("duplicate_of_candidate_index")
        supersedes = operation.get("supersedes_candidate_indexes")
        reason = operation.get("reason")
        if memory is None and duplicate is None and supersedes == [] and isinstance(reason, str):
            return _NormalizedOperation(
                final_result=_final_result("no_op", reason),
                memory=None,
                supersedes_memory_ids=[],
            )
    return _terminal_no_op("invalid_tool_output")


def _normalize_duplicate(
    operation: dict[str, object],
    candidates: list[MemoryRecord],
) -> _NormalizedOperation:
    duplicate = operation.get("duplicate_of_candidate_index")
    if (
        operation.get("memory") is None
        and _is_candidate_index(duplicate)
        and operation.get("supersedes_candidate_indexes") == []
        and isinstance(operation.get("reason"), str)
    ):
        if not _candidate_exists(duplicate, candidates):
            return _terminal_no_op("candidate_index_out_of_range")
        result = _final_result("duplicate", str(operation["reason"]))
        result["duplicate_of_memory_id"] = candidates[duplicate].id
        return _NormalizedOperation(result, None, [])
    return _terminal_no_op("invalid_tool_output")


def _normalize_write(
    operation: dict[str, object],
    request: ObserveRequest,
    project_event_seq: int,
    candidates: list[MemoryRecord],
    components: set[str],
) -> _NormalizedOperation:
    memory = operation.get("memory")
    duplicate = operation.get("duplicate_of_candidate_index")
    supersedes = operation.get("supersedes_candidate_indexes")
    reason = operation.get("reason")
    if (
        not isinstance(memory, dict)
        or duplicate is not None
        or not isinstance(reason, str)
        or not _valid_index_array(supersedes)
    ):
        return _terminal_no_op("invalid_tool_output")

    candidate_indexes = list(supersedes)
    if any(not _candidate_exists(index, candidates) for index in candidate_indexes):
        return _terminal_no_op("candidate_index_out_of_range")

    memory_result = _normalize_memory(memory, request, components)
    if memory_result.error is not None:
        return _terminal_no_op(memory_result.error)

    normalized_memory = memory_result.memory
    duplicate_index = _equivalent_active_candidate_index(normalized_memory, candidates)
    if duplicate_index is not None:
        result = _final_result("duplicate", "equivalent_active_memory")
        result["duplicate_of_memory_id"] = candidates[duplicate_index].id
        return _NormalizedOperation(result, None, [])

    if candidate_indexes:
        supersession_error = _validate_supersession(
            normalized_memory,
            request,
            project_event_seq,
            [candidates[index] for index in candidate_indexes],
        )
        if supersession_error is not None:
            return _terminal_no_op(supersession_error)

    result = _final_result("write", reason)
    result["memory"] = normalized_memory
    superseded_memory_ids = [candidates[index].id for index in candidate_indexes]
    result["superseded_memory_ids"] = superseded_memory_ids
    return _NormalizedOperation(
        final_result=result,
        memory=normalized_memory,
        supersedes_memory_ids=superseded_memory_ids,
    )


@dataclass(frozen=True)
class _MemoryValidation:
    memory: dict[str, object]
    error: str | None


def _normalize_memory(
    memory: dict[str, object],
    request: ObserveRequest,
    components: set[str],
) -> _MemoryValidation:
    memory_type = memory.get("type")
    subject = memory.get("subject")
    text = memory.get("text")
    scope_level = memory.get("scope_level")
    component = memory.get("component")
    if not all(isinstance(value, str) for value in [memory_type, subject, text, scope_level]):
        return _MemoryValidation({}, "invalid_tool_output")
    if memory_type not in {"decision", "preference", "lesson"}:
        return _MemoryValidation({}, "invalid_memory_type")
    if scope_level == "project" and component is not None:
        return _MemoryValidation({}, "invalid_scope_component")
    if scope_level == "component" and component not in components:
        return _MemoryValidation({}, "invalid_component")
    if scope_level not in {"project", "component"}:
        return _MemoryValidation({}, "invalid_scope")
    if memory_type == "preference" and scope_level != "project":
        return _MemoryValidation({}, "invalid_type_scope")
    if memory_type in {"decision", "lesson"} and scope_level != "component":
        return _MemoryValidation({}, "invalid_type_scope")
    if _subject_component_mismatch(subject, component):
        return _MemoryValidation({}, "subject_component_mismatch")
    if memory_type == "preference" and request.actor != "user":
        return _MemoryValidation({}, "preference_requires_user")
    if memory_type == "decision" and request.actor != "user":
        return _MemoryValidation({}, "decision_requires_user")
    return _MemoryValidation(
        {
            "type": memory_type,
            "subject": subject,
            "text": text,
            "scope_level": scope_level,
            "component": component,
        },
        None,
    )


def _validate_supersession(
    memory: dict[str, object],
    request: ObserveRequest,
    project_event_seq: int,
    priors: list[MemoryRecord],
) -> str | None:
    if memory["type"] == "lesson":
        return "forbidden_lesson_supersession"
    for prior in priors:
        if prior.project_id != request.project_id:
            return "cross_project_candidate"
        if prior.source_project_event_seq >= project_event_seq:
            return "supersession_requires_older_prior"
        if (
            prior.type != memory["type"]
            or prior.subject != memory["subject"]
            or prior.scope_level != memory["scope_level"]
            or prior.component != memory["component"]
        ):
            return "supersession_scope_mismatch"
    return None


def _equivalent_active_candidate_index(
    memory: dict[str, object],
    candidates: list[MemoryRecord],
) -> int | None:
    for index, candidate in enumerate(candidates[:8]):
        if not _same_memory_key(memory, candidate):
            continue
        if _meaning_equivalent(str(memory["text"]), candidate.text, str(memory["subject"])):
            return index
    return None


def _same_memory_key(memory: dict[str, object], candidate: MemoryRecord) -> bool:
    return (
        candidate.type == memory["type"]
        and candidate.subject == memory["subject"]
        and candidate.scope_level == memory["scope_level"]
        and candidate.component == memory["component"]
    )


def _meaning_equivalent(left: str, right: str, subject: str) -> bool:
    left_normalized = _normalize_text_for_match(left)
    right_normalized = _normalize_text_for_match(right)
    if left_normalized == right_normalized:
        return True
    if subject == "retry_policy":
        return _same_retry_policy(left_normalized, right_normalized)
    if subject == "dependency_policy":
        return _dependency_restriction(left_normalized) and _dependency_restriction(
            right_normalized
        )
    return False


def _normalize_text_for_match(text: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text.lower()).split())


def _same_retry_policy(left: str, right: str) -> bool:
    return (
        _has_all(left, ["five", "attempts", "exponential"])
        and _has_all(right, ["five", "attempts", "exponential"])
    ) or (
        _has_all(left, ["three", "attempts", "fixed"])
        and _has_all(right, ["three", "attempts", "fixed"])
    ) or (
        "exponential" in left
        and "five" not in left
        and ("fixed" in left or "delay" in left)
        and _has_all(right, ["five", "attempts", "exponential"])
    )


def _dependency_restriction(text: str) -> bool:
    mentions_dependencies = (
        "dependency" in text
        or "dependencies" in text
        or "pyproject" in text
    )
    restricts_change = (
        "do not" in text
        or "no " in f"{text} "
        or "without" in text
        or "free" in text
    )
    return mentions_dependencies and restricts_change


def _has_all(text: str, terms: list[str]) -> bool:
    return all(term in text for term in terms)


def _subject_component_mismatch(subject: object, component: object) -> bool:
    expected_components = {
        "auth_policy": "auth",
        "cache_policy": "cache",
        "config_policy": "config",
        "retry_policy": "retry",
    }
    expected = expected_components.get(subject)
    return expected is not None and component != expected


def _valid_index_array(value: object) -> bool:
    if not isinstance(value, list):
        return False
    return all(_is_candidate_index(index) for index in value) and len(set(value)) == len(value)


def _is_candidate_index(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _candidate_exists(index: object, candidates: list[MemoryRecord]) -> bool:
    if not _is_candidate_index(index):
        return False
    return 0 <= index < min(len(candidates), 8)


def _terminal_no_op(reason: str) -> _NormalizedOperation:
    return _NormalizedOperation(
        final_result=_final_result("no_op", reason),
        memory=None,
        supersedes_memory_ids=[],
    )


def _trace_offsets(*providers: object) -> dict[int, int]:
    return {
        id(provider): len(getattr(provider, "traces", []))
        for provider in providers
        if isinstance(getattr(provider, "traces", None), list)
    }


def _attempt_evidence(
    decider: object,
    embedding_provider: object,
    offsets: dict[int, int],
    tool_arguments: object,
    validation: list[dict[str, object]],
) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    for provider in (decider, embedding_provider):
        traces = getattr(provider, "traces", None)
        if not isinstance(traces, list):
            continue
        for trace in traces[offsets.get(id(provider), 0) :]:
            to_v4_record = getattr(trace, "to_v4_record", None)
            if callable(to_v4_record):
                records.append(to_v4_record())
    return {
        "model_calls": [
            record for record in records if record.get("role") == "memory_decision"
        ],
        "embedding_calls": [
            record for record in records if record.get("role") == "embedding"
        ],
        "tool_arguments": tool_arguments if isinstance(tool_arguments, dict) else None,
        "validation": list(validation),
    }


def _append_provider_error_evidence(
    evidence: dict[str, Any],
    error: object,
    *,
    role: str,
    purpose: str,
) -> None:
    from recallpack.providers import ProviderTrace

    provider_name = str(getattr(error, "provider_name", "unknown-provider"))
    is_live = provider_name == "qwen-cloud"
    trace = ProviderTrace(
        provider_name=provider_name,
        model_id=str(getattr(error, "model_id", EMBEDDING_MODEL)),
        provider_role=role,
        request_purpose=purpose,
        input_item_count=1,
        input_token_estimate=0,
        output_item_count=0,
        is_live=is_live,
        deterministic_fallback_status=("live_qwen" if is_live else "fake_provider_error"),
        request_id=getattr(error, "request_id", None),
        usage=getattr(error, "usage", {}),
    ).to_v4_record()
    target = "embedding_calls" if role == "embedding" else "model_calls"
    evidence.setdefault(target, []).append(trace)


def _evidence_has_request_id(evidence: dict[str, Any] | None) -> bool:
    if not evidence:
        return False
    calls = [
        *evidence.get("model_calls", []),
        *evidence.get("embedding_calls", []),
    ]
    return any(
        isinstance(call, dict) and call.get("request_id_present") is True
        for call in calls
    )


def _evidence_was_repaired(evidence: dict[str, Any] | None) -> bool:
    if not evidence:
        return False
    validation = evidence.get("validation", [])
    return any(
        isinstance(item, dict) and item.get("stage") == "repair"
        for item in validation
    )


def _provider_mode(*providers: object) -> str:
    pending = list(providers)
    seen: set[int] = set()
    while pending:
        provider = pending.pop()
        if id(provider) in seen:
            continue
        seen.add(id(provider))
        traces = getattr(provider, "traces", [])
        if any(getattr(trace, "is_live", False) for trace in traces):
            return "live"
        if getattr(provider, "is_live", False) is True:
            return "live"
        if provider.__class__.__name__.startswith("Qwen"):
            return "live"
        nested = getattr(provider, "_provider", None)
        if nested is not None:
            pending.append(nested)
    return "fake"


def _provider_observe_error(error: object) -> str:
    allowed = {
        "provider_timeout",
        "provider_rate_limit",
        "provider_server_error",
        "provider_network_error",
        "provider_http_response_unparseable",
        "model_output_unparseable_after_repair",
        "provider_operator_action_required",
    }
    code = getattr(error, "code", None)
    if code in allowed:
        return str(code)
    if getattr(error, "retryable", False):
        return "provider_network_error"
    return "provider_operator_action_required"


def _sqlite_error_code(error: sqlite3.Error) -> str:
    message = str(error).lower()
    if "locked" in message or "busy" in message:
        return "sqlite_busy"
    return "sqlite_io_error"


def _final_result(operation: str, reason: str) -> dict[str, Any]:
    return {
        "operation": operation,
        "memory": None,
        "reason": reason,
    }
