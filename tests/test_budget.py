import unittest

from recallpack.budget import (
    BudgetSelector,
    BudgetTooSmallError,
    canonical_json,
    count_canonical_json_tokens,
)
from recallpack.tokenization import ExactTokenizer, TokenizerUnavailableError


class Utf8TestTokenizer:
    def count(self, text: str) -> int:
        return len(text.encode("utf-8"))


class FixedCountTokenizer:
    def __init__(self, count: int) -> None:
        self._count = count
        self.seen: list[str] = []

    def count(self, text: str) -> int:
        self.seen.append(text)
        return self._count


class SequenceCountTokenizer:
    def __init__(self, counts: list[int]) -> None:
        self._counts = list(counts)
        self.seen: list[str] = []

    def count(self, text: str) -> int:
        self.seen.append(text)
        return self._counts.pop(0)


class RecordingEncoding:
    def __init__(self) -> None:
        self.seen: list[str] = []

    def encode(self, text: str) -> list[int]:
        self.seen.append(text)
        return list(text.encode("utf-8"))


class BudgetSelectorTests(unittest.TestCase):
    def test_budget_counts_full_canonical_downstream_json(self):
        tokenizer = Utf8TestTokenizer()
        selector = BudgetSelector(max_tokens=512, tokenizer=tokenizer)
        selected = selector.select(
            [
                {
                    "id": "mem_retry_policy",
                    "type": "decision",
                    "subject": "retry_policy",
                    "text": "Use five attempts with exponential backoff in the retry helper.",
                    "scope": "component:retry",
                    "source_ref": "session-a:turn-005",
                }
            ]
        )

        canonical = selected.to_canonical_json()

        self.assertEqual(
            canonical,
            '{"memories":[{"id":"mem_retry_policy","scope":"component:retry","source_ref":"session-a:turn-005","subject":"retry_policy","text":"Use five attempts with exponential backoff in the retry helper.","type":"decision"}]}',
        )
        self.assertEqual(
            count_canonical_json_tokens(canonical, tokenizer=tokenizer),
            len(canonical.encode("utf-8")),
        )

    def test_items_that_do_not_fit_are_skipped_without_truncation(self):
        selector = BudgetSelector(max_tokens=240, tokenizer=Utf8TestTokenizer())
        huge_text = "retry " * 200
        selected = selector.select(
            [
                {
                    "id": "mem_too_large",
                    "type": "decision",
                    "subject": "retry_policy",
                    "text": huge_text,
                    "scope": "component:retry",
                    "source_ref": "session-a:turn-005",
                },
                {
                    "id": "mem_small",
                    "type": "preference",
                    "subject": "dependency_policy",
                    "text": "Keep retry behavior dependency-free.",
                    "scope": "project",
                    "source_ref": "session-a:turn-003",
                },
            ]
        )

        self.assertEqual([item["id"] for item in selected.memories], ["mem_small"])
        self.assertNotIn("mem_too_large", selected.to_canonical_json())

    def test_exact_tokenizer_loads_only_o200k_base_and_counts_unicode_canonical_json(self):
        encoding = RecordingEncoding()
        requested: list[str] = []

        def load_encoding(name: str) -> RecordingEncoding:
            requested.append(name)
            return encoding

        tokenizer = ExactTokenizer(encoding_loader=load_encoding)
        canonical = canonical_json({"memory": "重试策略", "active": True})

        count = tokenizer.count(canonical)

        self.assertEqual(requested, ["o200k_base"])
        self.assertEqual(encoding.seen, [canonical])
        self.assertEqual(count, len(canonical.encode("utf-8")))
        self.assertIn("重试策略", canonical)

    def test_exact_tokenizer_unavailability_and_encode_failure_fail_closed(self):
        def unavailable(_name: str):
            raise ImportError("tiktoken is absent")

        with self.assertRaisesRegex(TokenizerUnavailableError, "tokenizer_unavailable"):
            ExactTokenizer(encoding_loader=unavailable)

        class BrokenEncoding:
            def encode(self, _text: str):
                raise RuntimeError("encoding data corrupt")

        tokenizer = ExactTokenizer(encoding_loader=lambda _name: BrokenEncoding())
        with self.assertRaisesRegex(TokenizerUnavailableError, "tokenizer_encode_failed"):
            tokenizer.count("{}")

    def test_512_token_pack_is_accepted(self):
        tokenizer = SequenceCountTokenizer([1, 512])
        selector = BudgetSelector(max_tokens=512, tokenizer=tokenizer)

        selected = selector.select([{"id": "mem_exact_boundary"}])

        self.assertEqual(selected.memories, [{"id": "mem_exact_boundary"}])
        self.assertEqual(len(tokenizer.seen), 2)

    def test_513_token_pack_is_rejected_without_estimate_fallback(self):
        tokenizer = SequenceCountTokenizer([1, 513])
        selector = BudgetSelector(max_tokens=512, tokenizer=tokenizer)

        selected = selector.select([{"id": "mem_over_boundary"}])

        self.assertEqual(selected.memories, [])
        self.assertEqual(len(tokenizer.seen), 2)

    def test_empty_canonical_envelope_over_budget_fails_explicitly(self):
        selector = BudgetSelector(max_tokens=1, tokenizer=FixedCountTokenizer(2))

        with self.assertRaisesRegex(BudgetTooSmallError, "budget_too_small"):
            selector.select([])


if __name__ == "__main__":
    unittest.main()
