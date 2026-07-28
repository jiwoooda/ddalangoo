"""
Meta MCP Client.

platform_agent에서 호출하는 실제 Meta MCP 클라이언트.
Node.js meta-mcp/dist/server.js를 subprocess로 실행해 search_products 호출.
"""
import json
import os
import socket
import subprocess
import time
from typing import Any
from urllib.error import URLError
from urllib.parse import quote, urlencode, urljoin
from urllib.request import Request, urlopen

from src.utils.agent_logger import agent_logger

META_MCP_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "meta-mcp")
)

SORT_MAP = {
    "price_asc": "price_low",
    "price_desc": "price_high",
    "relevance": "price_low",
    "popularity": "price_low",
    "review_score": "price_low",
    "delivery_fast": "price_low",
    "free_shipping": "price_low",
    "value": "price_low",
}

NAVER_API_SORT_MAP = {
    "price_low": "sim",
    "price_high": "sim",
    "recent": "date",
}

KURLY_SHOP_KEYWORDS = ("컬리", "마켓컬리", "kurly", "컬리n마트", "컬리 n마트", "컬리N마트")
KURLY_BASE_URL = "https://www.kurly.com"
META_MCP_SERVER_URL_ENV = "META_MCP_SERVER_URL"


def _is_transient_network_error(exc: BaseException) -> bool:
    """연결/타임아웃 계열만 재시도 대상. HTTP 4xx 등 URLError 서브클래스(HTTPError)의
    영구적 실패는 URLError로도 잡히므로, reason 속성으로 소켓 타임아웃류만 좁힌다."""
    if isinstance(exc, (socket.timeout, TimeoutError, ConnectionError)):
        return True
    if isinstance(exc, URLError):
        reason = getattr(exc, "reason", None)
        return isinstance(reason, (socket.timeout, TimeoutError, OSError))
    return False


def _retry_network_call(fn, *args, max_attempts: int = 3, initial_interval: float = 0.3, backoff_factor: float = 2.0, **kwargs):
    """Tool-level 재시도: 연결/타임아웃 오류만 최대 3회 짧게 재시도하고,
    그 외(4xx 등)는 즉시 다시 던져 호출부가 다음 폴백 단계로 넘어가게 한다."""
    interval = initial_interval
    last_exc: BaseException | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            last_exc = e
            if not _is_transient_network_error(e) or attempt >= max_attempts:
                raise
            time.sleep(interval)
            interval *= backoff_factor
    raise last_exc  # pragma: no cover


def _env_true(name: str) -> bool:
    """환경변수 문자열을 boolean flag로 해석한다."""
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _kurly_mvp_mode() -> bool:
    """실제 브라우저 MVP에서는 상품 추천도 컬리 검색 URL 중심으로 고정한다."""
    return _env_true("USE_REAL_BROWSER") or os.getenv("MVP_MODE", "").strip().lower() == "kurly"


def _strip_html(value: str) -> str:
    return value.replace("<b>", "").replace("</b>", "")


def _naver_query(query: str, platform: str) -> str:
    if platform != "kurly":
        return query
    lower_query = query.lower()
    if "컬리" in lower_query or "kurly" in lower_query:
        return query
    return f"{query} 컬리N마트"


def _is_kurly_item(item: dict[str, Any]) -> bool:
    mall_name = str(item.get("mallName") or "").lower()
    title = str(item.get("title") or "").lower()
    return any(keyword in mall_name or keyword in title for keyword in KURLY_SHOP_KEYWORDS)


def _is_kurly_url(url: str) -> bool:
    """실제 브라우저 자동화가 열 수 있는 컬리 도메인인지 확인한다."""
    lowered = str(url or "").lower()
    return "kurly.com" in lowered


def _kurly_search_url(query: str) -> str:
    """컬리 상품 상세 URL이 없을 때 Playwright가 검색부터 시작할 수 있는 URL을 만든다."""
    return f"{KURLY_BASE_URL}/search?sword={quote(query)}"


def _call_kurly_search_url_fallback(params: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Naver/MCP 없이도 Kurly MVP 플로우를 시작할 수 있게 검색 URL 후보를 만든다.

    실제 상품 선택, 가격, 배송 정보는 이후 webview_tool.py가 컬리 모바일웹에서
    검색/상세 진입하면서 다시 확인한다.
    """
    platforms = params.get("platforms") or []
    if "kurly" not in platforms:
        return []

    query = str(params.get("query") or "").strip()
    if not query:
        return []

    product = {
        "name": query,
        "price": 0,
        "delivery_info": "",
        "platform": "kurly",
        "image_url": None,
        "url": _kurly_search_url(query),
        "source": "kurly_search_url_fallback",
    }
    print("[meta_mcp_client] kurly search-url fallback products=1")
    return _normalize([product])


def _call_naver_search_api(params: dict[str, Any]) -> list[dict[str, Any]]:
    """Node MCP가 없는 배포 환경에서도 네이버 쇼핑 검색을 수행한다."""
    if _kurly_mvp_mode() and "kurly" in (params.get("platforms") or []):
        print("[meta_mcp_client] naver fallback skipped: kurly mvp mode")
        agent_logger.log_source_fallback(from_source="naver_api", to_source="kurly_url_fallback", reason="kurly_mvp_mode")
        return _call_kurly_search_url_fallback(params)

    client_id = os.getenv("NAVER_CLIENT_ID")
    client_secret = os.getenv("NAVER_CLIENT_SECRET")
    if not client_id or not client_secret:
        # 여기는 kurly_mvp_mode(의도된 브라우저 구매 모드)가 아니라 "네이버 API를
        # 시도했는데 자격증명이 없어서 못 함" 케이스다. 이전에는 가격 0원짜리
        # placeholder 상품을 검색 결과인 척 반환해서, 브라우저 자동화가 돌지
        # 않는(USE_REAL_BROWSER=false) 일반 모드에서도 그 가짜 데이터가 랭킹·
        # 설명 생성·mock 결제까지 그대로 흘러가는 문제가 있었다. 빈 리스트를
        # 반환해 search_products()가 진짜 실패로 처리되게 하고, product_agent의
        # 기존 no_candidates Graceful Degradation 경로로 자연스럽게 넘어가게 한다.
        print("[meta_mcp_client] naver fallback disabled: missing credentials")
        agent_logger.log_graceful_degradation(
            node="meta_mcp_client", reason="naver_credentials_missing", stage="search"
        )
        return []

    products: list[dict[str, Any]] = []
    platforms = [p for p in params.get("platforms", []) if p in ("naver", "kurly")]
    original_query = str(params.get("query") or "")
    for platform in platforms:
        query = _naver_query(original_query, platform)
        display = int(params.get("limit") or 5)
        sort = NAVER_API_SORT_MAP.get(str(params.get("sort") or "price_low"), "sim")
        url = (
            "https://openapi.naver.com/v1/search/shop.json"
            f"?query={quote(query)}&display={display * 3 if platform == 'kurly' else display}&sort={sort}"
        )
        request = Request(
            url,
            headers={
                "X-Naver-Client-Id": client_id,
                "X-Naver-Client-Secret": client_secret,
            },
        )
        try:
            def _fetch():
                with urlopen(request, timeout=10) as response:
                    return json.loads(response.read().decode("utf-8"))
            data = _retry_network_call(_fetch)
        except Exception as e:
            print(f"[meta_mcp_client] naver fallback failed platform={platform}: {e}")
            continue

        items = data.get("items") or []
        if platform == "kurly":
            filtered = [item for item in items if _is_kurly_item(item)]
            items = filtered

        for item in items[:display]:
            price = int(item.get("lprice") or 0)
            raw_url = item.get("link") or ""
            product_url = raw_url
            if platform == "kurly" and not _is_kurly_url(raw_url):
                product_url = _kurly_search_url(original_query)
            products.append({
                "name": _strip_html(item.get("title") or ""),
                "price": price,
                "delivery_info": "",  # 실제 배송 정보는 webview에서 추출
                "platform": platform,
                "image_url": item.get("image"),
                "url": product_url,
                "source_url": raw_url,
                "shop_name": item.get("mallName"),
                # 네이버 쇼핑 API 원본 응답에 실제로 포함된 필드 — mock 아님
                "brand": item.get("brand") or item.get("maker") or None,
            })

    if params.get("sort") == "price_low":
        products.sort(key=lambda product: product.get("price") or 0)
    elif params.get("sort") == "price_high":
        products.sort(key=lambda product: product.get("price") or 0, reverse=True)

    print(f"[meta_mcp_client] naver fallback products={len(products)}")
    return _normalize(products[: int(params.get("limit") or 5)])


def _normalize_product_execution_urls(
    products: list[dict[str, Any]],
    *,
    query: str = "",
) -> list[dict[str, Any]]:
    """
    외부 검색 결과 URL과 실제 WebView 실행 URL의 의미를 분리한다.

    Kurly MVP는 네이버에서 컬리N마트 상품을 찾지만, 구매 자동화는 컬리
    모바일웹에서 다시 검색해 진행한다. 따라서 smartstore 원본 URL은
    source_url로 보존하고, 후속 Agent가 보는 product_url/url은
    kurly.com 검색 URL로 맞춘다.
    """
    normalized_products: list[dict[str, Any]] = []
    for product in products:
        normalized_product = dict(product)
        platform = str(normalized_product.get("platform") or "").lower()
        shop_name = str(
            normalized_product.get("shop_name")
            or normalized_product.get("mall_name")
            or ""
        ).strip().lower()
        raw_url = (
            normalized_product.get("url")
            or normalized_product.get("product_url")
            or normalized_product.get("execution_url")
            or ""
        )

        if (
            platform in {"naver", "kurly"}
            and ("컬리" in shop_name or "kurly" in shop_name)
        ):
            normalized_product["platform"] = "kurlynmart"
            platform = "kurlynmart"

        if platform in {"kurly", "kurlynmart"} and raw_url and not _is_kurly_url(raw_url):
            search_query = query or str(normalized_product.get("name") or "").strip()
            execution_url = _kurly_search_url(search_query)
            normalized_product.setdefault("source_url", raw_url)
            normalized_product["url"] = execution_url
            normalized_product["product_url"] = execution_url
            normalized_product["execution_url"] = execution_url

        normalized_products.append(normalized_product)

    return normalized_products


def _parse_sse_search_result(payload: str, query: str = "") -> list[dict[str, Any]]:
    """meta-mcp /sse 응답에서 search_result 이벤트의 data JSON을 꺼낸다."""
    current_event = "message"
    data_lines: list[str] = []

    for line in payload.splitlines():
        if line.startswith("event:"):
            current_event = line.removeprefix("event:").strip()
            data_lines = []
            continue
        if line.startswith("data:"):
            data_lines.append(line.removeprefix("data:").strip())
            continue
        if line.strip():
            continue

        if current_event == "search_result" and data_lines:
            data = json.loads("\n".join(data_lines))
            products = _normalize_product_execution_urls(data.get("products", []), query=query)
            return _normalize(products)
        data_lines = []

    if current_event == "search_result" and data_lines:
        data = json.loads("\n".join(data_lines))
        products = _normalize_product_execution_urls(data.get("products", []), query=query)
        return _normalize(products)
    return []


def _call_remote_meta_mcp(params: dict[str, Any]) -> list[dict[str, Any]]:
    """별도 Railway Node 서비스로 분리된 meta-mcp /sse endpoint를 호출한다."""
    base_url = os.getenv(META_MCP_SERVER_URL_ENV, "").strip()
    if not base_url:
        return []

    query = urlencode({
        "query": params.get("query") or "",
        "platforms": ",".join(params.get("platforms") or []),
        "sort": params.get("sort") or "price_low",
        "limit": int(params.get("limit") or 5),
        **({"min_price": params["min_price"]} if params.get("min_price") is not None else {}),
        **({"max_price": params["max_price"]} if params.get("max_price") is not None else {}),
    })
    endpoint = f"{urljoin(base_url.rstrip('/') + '/', 'sse')}?{query}"

    try:
        print(
            "[meta_mcp_client] remote sse search start",
            f"url={base_url}",
            f"platforms={params.get('platforms')}",
            f"query={params.get('query')}",
        )
        def _fetch():
            with urlopen(endpoint, timeout=20) as response:
                return response.read().decode("utf-8")
        body = _retry_network_call(_fetch)
        products = _parse_sse_search_result(body, query=str(params.get("query") or ""))
        print(f"[meta_mcp_client] remote sse products={len(products)}")
        return products
    except Exception as error:
        print(f"[meta_mcp_client] remote sse failed: {error}")
        return []


def _call_meta_mcp(params: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Node.js meta-mcp 서버를 subprocess로 실행해 search_products 호출.

    MCP 프로토콜 순서:
      1) initialize  → server capabilities 수신
      2) notifications/initialized  (notification, 응답 없음)
      3) tools/call  → 결과 수신
    """
    sdk_dir = os.path.join(META_MCP_DIR, "node_modules", "@modelcontextprotocol", "sdk")
    if not os.path.isdir(sdk_dir):
        print("[meta_mcp_client] meta-mcp dependencies missing; using naver fallback")
        agent_logger.log_source_fallback(from_source="local_mcp", to_source="naver_api", reason="dependencies_missing")
        return _call_naver_search_api(params)

    messages = "\n".join([
        json.dumps({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "python-client", "version": "1.0.0"},
            },
        }),
        json.dumps({
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
            "params": {},
        }),
        json.dumps({
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "search_products",
                "arguments": params,
            },
        }),
    ]) + "\n"

    # Windows에서 Node.js가 PATH에 없을 때 nodejs 폴더를 PATH에 추가
    _NODE_DIRS = [
        r"C:\Program Files\nodejs",
        r"C:\Program Files (x86)\nodejs",
    ]
    proc_env = {**os.environ}
    for nd in _NODE_DIRS:
        if os.path.isdir(nd) and nd not in proc_env.get("PATH", ""):
            proc_env["PATH"] = nd + os.pathsep + proc_env.get("PATH", "")
            break

    _NPX_CANDIDATES = [
        r"C:\Program Files\nodejs\npx.cmd",
        r"C:\Program Files (x86)\nodejs\npx.cmd",
        "npx",
    ]
    npx_cmd = next((c for c in _NPX_CANDIDATES if os.path.isfile(c)), "npx")

    try:
        print(
            "[meta_mcp_client] search start",
            f"platforms={params.get('platforms')}",
            f"query={params.get('query')}",
            f"naver_id_set={bool(proc_env.get('NAVER_CLIENT_ID'))}",
            f"naver_secret_set={bool(proc_env.get('NAVER_CLIENT_SECRET'))}",
        )
        proc = subprocess.run(
            [npx_cmd, "tsx", "src/server.ts"],
            input=messages,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
            cwd=META_MCP_DIR,
            env=proc_env,
        )

        if proc.returncode != 0 and proc.stderr:
            print(f"[meta_mcp_client] stderr: {proc.stderr[:500]}")
        else:
            print(
                "[meta_mcp_client] process done",
                f"returncode={proc.returncode}",
                f"stdout_lines={len(proc.stdout.splitlines())}",
                f"stderr={proc.stderr[:300] if proc.stderr else ''}",
            )

        for line in proc.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                response = json.loads(line)
                # id=2 인 응답이 tools/call 결과
                if response.get("id") == 2:
                    content = response.get("result", {}).get("content", [])
                    if content:
                        data = json.loads(content[0]["text"])
                        products = _normalize_product_execution_urls(
                            data.get("products", []),
                            query=str(params.get("query") or ""),
                        )
                        products = _normalize(products)
                        print(f"[meta_mcp_client] products={len(products)}")
                        return products
            except (json.JSONDecodeError, KeyError):
                continue

    except subprocess.TimeoutExpired:
        print("[meta_mcp_client] timeout (30s)")
    except FileNotFoundError:
        print(f"[meta_mcp_client] npx not found. Node.js 설치 및 meta-mcp npm install 필요")
    except Exception as e:
        print(f"[meta_mcp_client] error: {e}")

    agent_logger.log_source_fallback(from_source="local_mcp", to_source="naver_api", reason="subprocess_failed_or_empty")
    return _call_naver_search_api(params)


def _normalize(products: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Meta MCP Product → platform_agent가 기대하는 형식으로 변환."""
    result = []
    for p in products:
        delivery_info = p.get("delivery_info", "일반배송")
        result.append({
            "product_name": p.get("name", ""),
            "price": p.get("price", 0),
            "rating": None,
            "review_count": None,
            "delivery": delivery_info,
            "delivery_fee": 0 if any(k in delivery_info for k in ("로켓", "무료")) else None,
            "platform": p.get("platform", ""),
            "image_url": p.get("image_url"),
            "product_url": p.get("product_url") or p.get("execution_url") or p.get("url", ""),
            "execution_url": p.get("execution_url") or p.get("product_url") or p.get("url", ""),
            "source_url": p.get("source_url"),
            "is_sold_out": False,
            "brand": p.get("brand"),
            # 실제 영양성분 API 연동 전까지는 값 없음 — mock 모드처럼 채워넣지 않음
            # (mcp 모드에서 nutrition_info가 비어있으면 tier1 필터가 이 사실 자체를 반영해야 함)
            "nutrition_info": p.get("nutrition_info"),
            "raw": p,
        })
    return result


_KURLY_WEBVIEW_ENRICH_LIMIT = 3


def _enrich_kurly_delivery(products: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    실제 kurly.com 상품 URL이 확보된 후보 중 상위 몇 개만 webview로 열어
    진짜 배송정보를 채운다. 후보마다 브라우저를 새로 띄우는 비용이 커서
    개수를 제한한다 (지연시간 vs 정확도 트레이드오프).
    """
    try:
        from src.tools.webview_tool import check_product_price
    except ImportError as e:
        print(f"[meta_mcp_client] webview_tool 사용 불가, 배송정보 보강 스킵: {e}")
        return products

    enriched_count = 0
    for product in products:
        if enriched_count >= _KURLY_WEBVIEW_ENRICH_LIMIT:
            break
        if str(product.get("platform") or "") not in ("kurly", "kurlynmart"):
            continue
        url = product.get("product_url") or product.get("execution_url") or ""
        if not _is_kurly_url(url):
            continue
        try:
            result = check_product_price(url, include_delivery=True)
        except Exception as e:
            print(f"[meta_mcp_client] kurly webview 배송정보 보강 실패 url={url}: {e}")
            enriched_count += 1
            continue
        delivery_info = result.get("delivery_info")
        if delivery_info:
            product["delivery"] = delivery_info
            product["delivery_fee"] = 0 if any(k in delivery_info for k in ("로켓", "무료", "새벽")) else product.get("delivery_fee")
        if result.get("current_price"):
            product["price"] = result["current_price"]
        enriched_count += 1
    return products


def search_products(
    query: str,
    platforms: list[str],
    condition: str = "relevance",
    budget_max: int | None = None,
) -> list[dict[str, Any]]:
    """platform_agent에서 호출하는 단일 진입점."""
    valid_platforms = [p for p in platforms if p in ("naver", "coupang", "kurly")]
    if not valid_platforms:
        valid_platforms = ["naver", "coupang"]

    params: dict[str, Any] = {
        "query": query,
        "platforms": valid_platforms,
        "sort": SORT_MAP.get(condition, "price_low"),
        "limit": 5,
    }
    if budget_max is not None:
        params["max_price"] = budget_max

    results = _call_remote_meta_mcp(params)
    if not results:
        agent_logger.log_source_fallback(from_source="remote_mcp", to_source="local_mcp", reason="empty_or_failed")
        results = _call_meta_mcp(params)

    if "kurly" in valid_platforms and results:
        results = _enrich_kurly_delivery(results)

    return results
