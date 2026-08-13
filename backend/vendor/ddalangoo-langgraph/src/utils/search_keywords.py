"""Conservative normalization for product-search keywords."""
from __future__ import annotations

import re
from collections.abc import Iterable


_QUANTITY_PHRASE = re.compile(
    r"(?:\d+|하나|한|둘|두|셋|세|넷|네|다섯|여섯|일곱|여덟|아홉|열)\s*"
    r"(?:개|판|팩|봉|봉지|병|캔|상자|박스|묶음|세트|통|포|kg|g|ml|l)\b",
    re.IGNORECASE,
)
_SPELLING_ALIASES = {"소세지": "소시지"}


def _display_keyword(value: object) -> str:
    text = re.sub(r"\s+", " ", str(value).strip())
    text = _QUANTITY_PHRASE.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip(" ,")


def _equivalence_key(value: str) -> str:
    key = value.lower().replace(" ", "")
    for alias, canonical in _SPELLING_ALIASES.items():
        key = key.replace(alias, canonical)
    return key


def normalize_search_keywords(values: Iterable[object] | None) -> list[str]:
    """Remove quantities and equivalent duplicates while retaining search meaning."""
    result: list[str] = []
    keys: list[str] = []
    for value in values or []:
        keyword = _display_keyword(value)
        if not keyword:
            continue
        key = _equivalence_key(keyword)
        if key in keys:
            continue
        contained_index = next(
            (index for index, existing in enumerate(keys) if key in existing or existing in key),
            None,
        )
        if contained_index is not None:
            if len(key) > len(keys[contained_index]):
                result[contained_index] = keyword
                keys[contained_index] = key
            continue
        result.append(keyword)
        keys.append(key)
    return result


def build_search_query(values: Iterable[object] | None) -> str:
    """Build the single query string passed to a shopping platform."""
    return " ".join(normalize_search_keywords(values))
