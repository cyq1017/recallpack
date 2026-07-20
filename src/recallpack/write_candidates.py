from __future__ import annotations

import hashlib
import math

from recallpack.memory import MemoryRecord


EMBEDDING_MODEL = "text-embedding-v4"
EMBEDDING_DIMENSION = 1024


def select_write_candidates(
    store: object,
    project_id: str,
    raw_event: str,
    embedding_provider: object,
    limit: int = 8,
) -> list[tuple[MemoryRecord, float]]:
    """Return the exact-cosine top candidates from active stored vectors."""
    memories = store.active_memories(project_id)
    if not memories:
        return []

    validated_memories = [
        (memory, validated_stored_vector(memory)) for memory in memories
    ]
    query_result = embedding_provider.embed_query(raw_event)
    query = validated_query_vector(query_result.embedding)
    scored: list[tuple[MemoryRecord, float]] = []
    for memory, document in validated_memories:
        scored.append((memory, cosine_similarity(query, document)))

    scored.sort(
        key=lambda item: (
            -item[1],
            -item[0].source_project_event_seq,
            item[0].id,
        )
    )
    return scored[: min(limit, 8)]


def build_candidate_payloads(
    scored_memories: list[tuple[MemoryRecord, float]], limit: int
) -> list[dict[str, object]]:
    payloads: list[dict[str, object]] = []
    for index, (memory, similarity) in enumerate(scored_memories[:limit]):
        payloads.append(
            {
                "candidate_index": index,
                "memory_id": memory.id,
                "type": memory.type,
                "subject": memory.subject,
                "text": memory.text,
                "scope_level": memory.scope_level,
                "component": memory.component,
                "source_actor": memory.source_actor,
                "source_ref": memory.source_ref.to_dict(),
                "source_project_event_seq": memory.source_project_event_seq,
                "similarity": similarity,
            }
        )
    return payloads


def validated_stored_vector(memory: MemoryRecord) -> list[float]:
    if (
        memory.record_schema_version != 4
        or memory.embedding_model != EMBEDDING_MODEL
        or memory.embedding_dimension != EMBEDDING_DIMENSION
    ):
        raise ValueError("memory_embedding_backfill_required")
    expected_hash = hashlib.sha256(
        _document_for_memory(memory).encode("utf-8")
    ).hexdigest()
    if memory.embedding_document_hash != expected_hash:
        raise ValueError("memory_embedding_backfill_required")
    try:
        return validated_vector(memory.embedding)
    except ValueError as exc:
        raise ValueError("memory_embedding_backfill_required") from exc


def validated_vector(vector: object) -> list[float]:
    if not isinstance(vector, list) or len(vector) != EMBEDDING_DIMENSION:
        raise ValueError("invalid_embedding_vector")
    if not all(
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(value)
        for value in vector
    ):
        raise ValueError("invalid_embedding_vector")
    normalized = [float(value) for value in vector]
    if not any(value != 0.0 for value in normalized):
        raise ValueError("invalid_embedding_vector")
    return normalized


def validated_query_vector(vector: object) -> list[float]:
    """Validate a query vector against the same V4 contract as stored vectors."""
    return validated_vector(vector)


def cosine_similarity(left: list[float], right: list[float]) -> float:
    left_norm = math.hypot(*left)
    right_norm = math.hypot(*right)
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    cosine = math.fsum(
        (a / left_norm) * (b / right_norm)
        for a, b in zip(left, right, strict=True)
    )
    if not math.isfinite(cosine):
        raise ValueError("invalid_embedding_vector")
    return cosine


def _document_for_memory(memory: MemoryRecord) -> str:
    scope = (
        "project"
        if memory.scope_level == "project"
        else f"{memory.scope_level}:{memory.component}"
    )
    return (
        f"type={memory.type}\n"
        f"scope={scope}\n"
        f"subject={memory.subject}\n"
        f"memory={memory.text}"
    )
