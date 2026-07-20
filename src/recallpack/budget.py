from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from recallpack.tokenization import TokenCounter, default_tokenizer


class BudgetTooSmallError(ValueError):
    """Raised when the canonical empty pack cannot fit the requested budget."""


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def count_canonical_json_tokens(
    canonical: str,
    tokenizer: TokenCounter | None = None,
) -> int:
    counter = tokenizer or default_tokenizer()
    return counter.count(canonical)


@dataclass(frozen=True)
class SelectedPack:
    memories: list[dict[str, Any]]

    def to_canonical_json(self) -> str:
        return canonical_json({"memories": self.memories})


class BudgetSelector:
    def __init__(
        self,
        max_tokens: int,
        tokenizer: TokenCounter | None = None,
    ) -> None:
        if max_tokens < 1:
            raise ValueError("max_tokens must be positive")
        self._max_tokens = max_tokens
        self._tokenizer = tokenizer or default_tokenizer()

    def select(self, candidates: list[dict[str, Any]]) -> SelectedPack:
        selected: list[dict[str, Any]] = []
        empty_json = canonical_json({"memories": selected})
        if (
            count_canonical_json_tokens(empty_json, tokenizer=self._tokenizer)
            > self._max_tokens
        ):
            raise BudgetTooSmallError("budget_too_small")
        for candidate in candidates:
            trial = selected + [candidate]
            trial_json = canonical_json({"memories": trial})
            if (
                count_canonical_json_tokens(trial_json, tokenizer=self._tokenizer)
                <= self._max_tokens
            ):
                selected = trial
        return SelectedPack(memories=selected)
