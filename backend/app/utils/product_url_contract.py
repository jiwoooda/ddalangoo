from hashlib import sha256
from urllib.parse import urlparse


def is_kurly_goods_url(url: str | None) -> bool:
    """컬리 자동화가 상품 상세 URL로 직접 진입해도 되는 /goods/ URL인지 확인한다."""
    if not url:
        return False
    parsed = urlparse(url)
    return parsed.netloc.endswith("kurly.com") and parsed.path.startswith("/goods/")


def is_search_like_url(url: str | None) -> bool:
    """검색/카테고리 URL처럼 상품 dedup 기준으로 쓰면 안 되는 URL인지 확인한다."""
    if not url:
        return False
    parsed = urlparse(url)
    path = parsed.path.lower()
    query = parsed.query.lower()
    return (
        "/search" in path
        or "/category" in path
        or "sword=" in query
        or "query=" in query
        or "keyword=" in query
        or "q=" in query
    )


def canonical_product_url_for_platform(platform: str | None, *urls: str | None) -> str | None:
    """
    상품 식별용 canonical URL을 고른다.

    컬리는 /goods/ 상세 URL만 상품 식별자로 인정한다. 검색 URL은 WebView 진입용일 수는
    있어도 서로 다른 후보를 같은 상품으로 병합하는 키가 되면 안 된다.
    """
    normalized_platform = (platform or "").lower()
    for url in urls:
        if not url:
            continue
        if normalized_platform == "kurly":
            if is_kurly_goods_url(url):
                return url
            continue
        if not is_search_like_url(url):
            return url
    return None


def stable_hash(value: str | None) -> str | None:
    """외부 식별값 저장에 쓰는 안정적인 sha256 hash를 만든다."""
    if not value:
        return None
    return sha256(value.strip().encode("utf-8")).hexdigest()


def fallback_product_fingerprint(
    *,
    platform: str | None,
    product_name: str | None,
    price: int | str | None,
    image_url: str | None,
) -> str | None:
    """
    canonical URL이 없을 때 쓰는 후보 단위 fingerprint.

    검색 URL 대신 상품명/가격/이미지를 묶어 최소한 서로 다른 검색 후보가 한 상품으로
    강제 병합되지 않게 한다.
    """
    if not product_name:
        return None
    raw_key = "|".join([
        (platform or "unknown").strip().lower(),
        product_name.strip(),
        str(price or ""),
        (image_url or "").strip(),
    ])
    return stable_hash(raw_key)
