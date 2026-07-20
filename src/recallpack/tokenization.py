from __future__ import annotations

from collections.abc import Callable
from functools import lru_cache
from typing import Any, Protocol


ENCODING_NAME = "o200k_base"


class TokenizerUnavailableError(RuntimeError):
    """Raised when exact token counting cannot be guaranteed."""


class TokenCounter(Protocol):
    def count(self, text: str) -> int:
        ...


class ExactTokenizer:
    def __init__(
        self,
        encoding_loader: Callable[[str], Any] | None = None,
    ) -> None:
        loader = encoding_loader or _load_tiktoken_encoding
        try:
            self._encoding = loader(ENCODING_NAME)
        except Exception as exc:
            raise TokenizerUnavailableError(
                f"tokenizer_unavailable: encoding={ENCODING_NAME}"
            ) from exc

    def count(self, text: str) -> int:
        if not isinstance(text, str):
            raise TypeError("tokenizer_input_must_be_text")
        try:
            return len(self._encoding.encode(text))
        except Exception as exc:
            raise TokenizerUnavailableError(
                f"tokenizer_encode_failed: encoding={ENCODING_NAME}"
            ) from exc


@lru_cache(maxsize=1)
def default_tokenizer() -> ExactTokenizer:
    return ExactTokenizer()


def _load_tiktoken_encoding(name: str) -> Any:
    try:
        import tiktoken  # type: ignore
    except ImportError as exc:
        raise TokenizerUnavailableError("tiktoken_dependency_missing") from exc
    return tiktoken.get_encoding(name)
