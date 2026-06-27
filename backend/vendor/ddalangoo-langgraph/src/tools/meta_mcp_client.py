"""
Meta MCP Client.

platform_agent에서 호출하는 실제 Meta MCP 클라이언트.
Node.js meta-mcp/dist/server.js를 subprocess로 실행해 search_products 호출.
"""
import json
import os
import subprocess
from typing import Any
from urllib.parse import quote, urlencode, urljoin
from urllib.request import Request, urlopen

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
        return _call_kurly_search_url_fallback(params)

    client_id = os.getenv("NAVER_CLIENT_ID")
    client_secret = os.getenv("NAVER_CLIENT_SECRET")
    if not client_id or not client_secret:
        print("[meta_mcp_client] naver fallback disabled: missing credentials")
        return _call_kurly_search_url_fallback(params)

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
            with urlopen(request, timeout=10) as response:
                data = json.loads(response.read().decode("utf-8"))
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
        with urlopen(endpoint, timeout=20) as response:
            body = response.read().decode("utf-8")
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
            "raw": p,
        })
    return result


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

    remote_results = _call_remote_meta_mcp(params)
    if remote_results:
        return remote_results

    return _call_meta_mcp(params)
