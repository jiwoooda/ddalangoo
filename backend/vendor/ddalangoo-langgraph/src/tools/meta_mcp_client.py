"""
Meta MCP Client.

platform_agent에서 호출하는 실제 Meta MCP 클라이언트.
Node.js meta-mcp/dist/server.js를 subprocess로 실행해 search_products 호출.
"""
import json
import os
import subprocess
from typing import Any
from urllib.parse import urlencode
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

NAVER_SORT_MAP = {
    "price_low": "sim",
    "price_high": "sim",
    "recent": "date",
    "relevance": "sim",
    "popularity": "sim",
    "review_score": "sim",
    "delivery_fast": "sim",
    "free_shipping": "sim",
    "value": "sim",
}

KURLY_SHOP_KEYWORDS = ("컬리", "마켓컬리", "kurly", "컬리n마트", "컬리 n마트")


def _strip_naver_html(value: str) -> str:
    """네이버 검색 API title의 <b> 태그를 제거한다."""
    return value.replace("<b>", "").replace("</b>", "")


def _search_naver_direct(
    query: str,
    platform: str,
    condition: str,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """
    Railway 배포 환경에서 Node 기반 meta-mcp가 timeout 날 때를 대비한 Naver API fallback.
    naver와 kurly 검색만 직접 처리하고, coupang은 기존 MCP 경로에 맡긴다.
    """
    client_id = os.environ.get("NAVER_CLIENT_ID")
    client_secret = os.environ.get("NAVER_CLIENT_SECRET")
    if not client_id or not client_secret:
        print("[meta_mcp_client] missing NAVER_CLIENT_ID or NAVER_CLIENT_SECRET")
        return []

    search_query = query
    display = limit
    if platform == "kurly" and not any(k.lower() in query.lower() for k in KURLY_SHOP_KEYWORDS):
        search_query = f"{query} 컬리N마트"
        display = limit * 3

    params = urlencode({
        "query": search_query,
        "display": min(max(display, 1), 100),
        "sort": NAVER_SORT_MAP.get(condition, "sim"),
    })
    request = Request(
        f"https://openapi.naver.com/v1/search/shop.json?{params}",
        headers={
            "X-Naver-Client-Id": client_id,
            "X-Naver-Client-Secret": client_secret,
        },
    )

    try:
        with urlopen(request, timeout=8) as response:
            data = json.loads(response.read().decode("utf-8"))
    except Exception as e:
        print(f"[meta_mcp_client] naver direct search failed: {e}")
        return []

    products: list[dict[str, Any]] = []
    for item in data.get("items", []):
        name = _strip_naver_html(item.get("title", ""))
        mall_name = item.get("mallName")
        if platform == "kurly":
            lower_name = name.lower()
            lower_mall = (mall_name or "").lower()
            if not any(k.lower() in lower_name or k.lower() in lower_mall for k in KURLY_SHOP_KEYWORDS):
                continue

        price = int(item.get("lprice") or 0)
        products.append({
            "product_name": name,
            "price": price,
            "rating": None,
            "review_count": None,
            "delivery": "샛별배송 내일 아침 7시 전" if platform == "kurly" else "일반배송",
            "delivery_fee": None,
            "platform": platform,
            "image_url": item.get("image"),
            "product_url": item.get("link", ""),
            "is_sold_out": False,
            "raw": item,
        })

    return products[:limit]


def _call_meta_mcp(params: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Node.js meta-mcp 서버를 subprocess로 실행해 search_products 호출.

    MCP 프로토콜 순서:
      1) initialize  → server capabilities 수신
      2) notifications/initialized  (notification, 응답 없음)
      3) tools/call  → 결과 수신
    """
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
                        return _normalize(data.get("products", []))
            except (json.JSONDecodeError, KeyError):
                continue

    except subprocess.TimeoutExpired:
        print("[meta_mcp_client] timeout (30s)")
    except FileNotFoundError:
        print(f"[meta_mcp_client] npx not found. Node.js 설치 및 meta-mcp npm install 필요")
    except Exception as e:
        print(f"[meta_mcp_client] error: {e}")

    return []


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
            "product_url": p.get("url", ""),
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

    # Naver/Kurly는 Python에서 직접 처리한다.
    # 기존 Node meta-mcp 경로는 Railway에서 이중 npx 실행 때문에 timeout이 잦다.
    direct_results: list[dict[str, Any]] = []
    for platform in valid_platforms:
        if platform in ("naver", "kurly"):
            direct_results.extend(
                _search_naver_direct(
                    query=query,
                    platform=platform,
                    condition=condition,
                    limit=5,
                )
            )

    if direct_results:
        if condition == "price_low":
            direct_results.sort(key=lambda p: p.get("price") or 0)
        elif condition == "price_high":
            direct_results.sort(key=lambda p: p.get("price") or 0, reverse=True)
        if budget_max is not None:
            direct_results = [p for p in direct_results if (p.get("price") or 0) <= budget_max]
        return direct_results[:5]

    # Coupang 또는 직접 검색 실패 시에만 기존 MCP 경로를 시도한다.

    params: dict[str, Any] = {
        "query": query,
        "platforms": valid_platforms,
        "sort": SORT_MAP.get(condition, "price_low"),
        "limit": 5,
    }
    if budget_max is not None:
        params["max_price"] = budget_max

    return _call_meta_mcp(params)
