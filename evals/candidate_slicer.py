"""Eval-time candidate slicing.

Kept separate from assembly on purpose: `final_dataset.jsonl` always stores
all 100 candidates per record (reproducibility, room to compare different K
later), and only code that's about to make an LLM call should ever cut that
list down. Nothing in this module writes back to the dataset file.
"""

DEFAULT_K_LIST = [20, 30, 50]


def _find_rank(candidates: list[dict], gold_asin: str) -> int | None:
    """1-indexed rank of gold_asin within `candidates`, or None if absent."""
    for i, c in enumerate(candidates):
        if c["asin"] == gold_asin:
            return i + 1
    return None


def get_eval_candidates(record: dict, k: int = 20, ensure_gold: bool = True):
    """Slices `record["candidates"][:k]`, preserving the retriever's original
    order - no re-ranking.

    `ensure_gold=False` returns the plain top-k slice unchanged, even when
    gold_product isn't in it - a realistic retrieval-failure setting where the
    evaluated system is graded on exactly what the retriever surfaced.

    `ensure_gold=True` (default) instead guarantees gold_product is always
    present in the returned k candidates:
      - gold already within the top-k -> the top-k slice is returned as-is
      - gold outside the top-k -> the *last* slot of the top-k is swapped for
        gold_product, so the returned list is always exactly k items long

    Return shape differs by branch on purpose (kept literal per spec):
    ensure_gold=False returns the bare list, unchanged from before. ensure_gold=True
    returns {"candidates": [...], "meta": {"gold_original_rank": int | None,
    "gold_replaced": bool}} - `gold_original_rank` is gold's 1-indexed rank in
    the *full* stored candidates list (not just the top-k slice), or None if
    gold_product isn't present in `record["candidates"]` at all (the normal
    case - candidates deliberately excludes gold_product by construction, see
    stage5.assemble - in which case gold_replaced is always True).
    """
    if not ensure_gold:
        return list(record["candidates"][:k])

    all_candidates = record["candidates"]
    gold_asin = record["gold_product"]["asin"]
    gold_original_rank = _find_rank(all_candidates, gold_asin)

    top_k = list(all_candidates[:k])
    if gold_original_rank is not None and gold_original_rank <= k:
        return {
            "candidates": top_k,
            "meta": {"gold_original_rank": gold_original_rank, "gold_replaced": False},
        }

    replaced = top_k[: max(k - 1, 0)] + [record["gold_product"]]
    return {
        "candidates": replaced,
        "meta": {"gold_original_rank": gold_original_rank, "gold_replaced": True},
    }


def get_eval_candidates_batch(record: dict, k_list: list[int] = None, ensure_gold: bool = True) -> dict:
    """Same as get_eval_candidates, computed for several K values at once so
    a k=20/30/50 comparison doesn't need to re-slice per experiment run."""
    for_ks = k_list if k_list is not None else DEFAULT_K_LIST
    return {k: get_eval_candidates(record, k=k, ensure_gold=ensure_gold) for k in for_ks}


def gold_in_top_k(record: dict, k: int) -> bool:
    gold_asin = record["gold_product"]["asin"]
    return any(c["asin"] == gold_asin for c in record["candidates"][:k])
