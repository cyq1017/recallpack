from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from typing import Any


_EXPONENT_RE = re.compile(r"^(?P<sign>-?)(?P<int>[0-9])(?:\.(?P<frac>[0-9]+))?[eE](?P<exp>[+-]?[0-9]+)$")
_MAX_SAFE_INTEGER = (1 << 53) - 1


def parse_review_json(payload: bytes) -> Any:
    """Parse the protocol's I-JSON subset without lossy normalization."""

    try:
        text = payload.decode("utf-8", errors="strict")

        def reject_duplicate(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
            result: dict[str, Any] = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError(f"duplicate object key: {key}")
                result[key] = value
            return result

        value = json.loads(
            text,
            object_pairs_hook=reject_duplicate,
            parse_int=_parse_integer_token,
            parse_constant=lambda value: (_ for _ in ()).throw(
                ValueError(f"non-finite number: {value}")
            ),
        )
        _validate_ijson(value)
        return value
    except (UnicodeError, json.JSONDecodeError, ValueError, TypeError) as exc:
        raise ValueError(f"4.1 invalid_review_json / {exc}") from None


def canonicalize_review_json(value: Any) -> bytes:
    """Return RFC 8785 JCS bytes for the protocol's I-JSON value domain."""

    try:
        _validate_ijson(value)
        return _serialize(value).encode("utf-8")
    except (UnicodeError, ValueError, TypeError) as exc:
        raise ValueError(f"4.1 invalid_review_json / {exc}") from None


def review_json_sha256(value: Any) -> str:
    return hashlib.sha256(canonicalize_review_json(value)).hexdigest()


def execution_manifest_sha256(manifest: Mapping[str, Any]) -> str:
    if manifest.get("semantic_rules_version") == "4.1":
        return review_json_sha256(manifest)
    legacy = json.dumps(
        manifest,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(legacy).hexdigest()


def _validate_ijson(value: Any) -> None:
    if value is None or isinstance(value, (bool, str)):
        if isinstance(value, str):
            _validate_unicode(value)
        return
    if isinstance(value, int):
        if abs(value) > _MAX_SAFE_INTEGER:
            raise ValueError("integer exceeds the I-JSON safe range")
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("non-finite number")
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("object keys must be strings")
            _validate_unicode(key)
            _validate_ijson(item)
        return
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray, str)):
        for item in value:
            _validate_ijson(item)
        return
    raise TypeError(f"unsupported JSON value: {type(value).__name__}")


def _validate_unicode(value: str) -> None:
    for character in value:
        codepoint = ord(character)
        if 0xD800 <= codepoint <= 0xDFFF:
            raise ValueError("lone surrogate is not I-JSON")


def _parse_integer_token(token: str) -> int | float:
    value = int(token)
    if abs(value) <= _MAX_SAFE_INTEGER:
        return value
    as_float = float(token)
    if not math.isfinite(as_float) or _serialize_float(as_float) != token:
        raise ValueError("integer token is not stable RFC 8785 IEEE-754 JSON")
    return as_float


def _serialize(value: Any) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return _serialize_float(value)
    if isinstance(value, Mapping):
        keys = sorted(value, key=lambda key: key.encode("utf-16be"))
        return "{" + ",".join(
            f"{_serialize(key)}:{_serialize(value[key])}" for key in keys
        ) + "}"
    return "[" + ",".join(_serialize(item) for item in value) + "]"


def _serialize_float(value: float) -> str:
    if value == 0:
        return "0"
    negative = value < 0
    absolute = -value if negative else value
    rendered = repr(absolute).lower()
    if "e" not in rendered:
        if rendered.endswith(".0"):
            rendered = rendered[:-2]
        return ("-" if negative else "") + rendered

    match = _EXPONENT_RE.fullmatch(rendered)
    if match is None:
        raise ValueError("unsupported float representation")
    digits = match.group("int") + (match.group("frac") or "")
    exponent = int(match.group("exp"))
    decimal_point = 1 + exponent
    if 1e-6 <= absolute < 1e21:
        if decimal_point <= 0:
            result = "0." + "0" * (-decimal_point) + digits
        elif decimal_point >= len(digits):
            result = digits + "0" * (decimal_point - len(digits))
        else:
            result = digits[:decimal_point] + "." + digits[decimal_point:]
        result = result.rstrip("0").rstrip(".") if "." in result else result
    else:
        fraction = digits[1:].rstrip("0")
        mantissa = digits[0] + (f".{fraction}" if fraction else "")
        result = f"{mantissa}e{'+' if exponent >= 0 else ''}{exponent}"
    return ("-" if negative else "") + result
