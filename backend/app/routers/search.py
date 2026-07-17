"""
Shopping SSE Search Router.

GET /sse?query=...&platforms=...&sort=...&limit_per_platform=10&limit=30

동작 방식:
- naver/coupang: 일반 쿼리로 Naver Shopping API 호출 (mallName으로 분류)
- kurly: "{query} 컬리N마트" 별도 쿼리 → mallName/link kurly 필터
- 각 플랫폼 limit_per_platform개 수집 후 SSE 응답
"""
import json
import os
import re
import concurrent.futures
from urllib.parse import quote
from urllib.request import Request, urlopen
from typing import Optional

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

router = APIRouter(prefix="/search", tags=["Search"])

_NAVER_API = "https://openapi.naver.com/v1/search/shop.json"

SORT_MAP = {
    "price_asc":     "asc",
    "price_low":     "asc",
    "price_desc":    "dsc",
    "price_high":    "dsc",
    "date":          "date",
    "sim":           "sim",
    "relevance":     "sim",
    "popularity":    "sim",
    "review_score":  "sim",
    "delivery_fast": "sim",
    "free_shipping": "sim",
    "value":         "sim",
}

_KURLY_KEYWORDS = ("컬리", "마켓컬리", "kurly", "컬리n마트", "컬리 n마트")
_COUPANG_KEYWORDS = ("쿠팡", "coupang")


def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text or "")


def _is_kurly(item: dict) -> bool:
    mall = str(item.get("mallName") or "").lower()
    link = str(item.get("link") or "").lower()
    return any(k in mall or k in link for k in _KURLY_KEYWORDS)


def _is_coupang(item: dict) -> bool:
    mall = str(item.get("mallName") or "").lower()
    link = str(item.get("link") or "").lower()
    return any(k in mall or k in link for k in _COUPANG_KEYWORDS)


def _naver_raw(query: str, sort: str, display: int) -> list[dict]:
    client_id = os.getenv("NAVER_CLIENT_ID", "")
    client_secret = os.getenv("NAVER_CLIENT_SECRET", "")
    if not client_id or not client_secret:
        return []
    url = f"{_NAVER_API}?query={quote(query)}&display={display}&sort={sort}"
    req = Request(url, headers={
        "X-Naver-Client-Id": client_id,
        "X-Naver-Client-Secret": client_secret,
    })
    try:
        with urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8")).get("items") or []
    except Exception as e:
        print(f"[search] naver API error query={query!r}: {e}")
        return []


def _to_product(item: dict, platform: str) -> dict:
    return {
        "product_name": _strip_html(item.get("title") or ""),
        "price": int(item.get("lprice") or 0),
        "rating": None,
        "review_count": None,
        "delivery": "",
        "delivery_fee": None,
        "platform": platform,
        "image_url": item.get("image"),
        "product_url": item.get("link") or "",
        "is_sold_out": False,
    }


def _fetch_all(query: str, sort: str, platforms: list[str], limit: int) -> list[dict]:
    """
    naver/coupang: 일반 쿼리 → display=(limit*3)으로 충분히 가져와서 mallName 분류
    kurly: "{query} 컬리N마트" 별도 쿼리
    """
    want_kurly = "kurly" in platforms
    want_naver = "naver" in platforms
    want_coupang = "coupang" in platforms

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
        main_future = ex.submit(_naver_raw, query, sort, min(100, limit * 6))
        kurly_future = (
            ex.submit(_naver_raw, f"{query} 컬리N마트", sort, min(100, limit * 3))
            if want_kurly else None
        )
        main_items = main_future.result()
        kurly_items = kurly_future.result() if kurly_future else []

    buckets: dict[str, list] = {p: [] for p in platforms}

    # kurly 전용 결과 먼저 처리
    for item in kurly_items:
        if want_kurly and _is_kurly(item) and len(buckets.get("kurly", [])) < limit:
            buckets.setdefault("kurly", []).append(_to_product(item, "kurly"))

    # 일반 결과 → naver / coupang 분류
    for item in main_items:
        if want_coupang and _is_coupang(item) and len(buckets.get("coupang", [])) < limit:
            buckets.setdefault("coupang", []).append(_to_product(item, "coupang"))
        elif want_naver and not _is_coupang(item) and not _is_kurly(item) and len(buckets.get("naver", [])) < limit:
            buckets.setdefault("naver", []).append(_to_product(item, "naver"))

    return [p for bucket in buckets.values() for p in bucket]


async def _sse_generator(query: str, platforms: list[str], sort: str, limit_per_platform: int):
    products = _fetch_all(query, sort, platforms, limit_per_platform)
    payload = json.dumps({"products": products}, ensure_ascii=False)
    yield f"event: search_result\ndata: {payload}\n\n"


@router.get("/sse")
async def search_sse(
    query: str = "",
    platforms: str = "naver,coupang,kurly",
    sort: str = "sim",
    limit_per_platform: int = 10,
    limit: Optional[int] = None,
):
    plat_list = [p.strip() for p in platforms.split(",") if p.strip()]
    naver_sort = SORT_MAP.get(sort, "sim")

    return StreamingResponse(
        _sse_generator(query, plat_list, naver_sort, limit_per_platform),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
