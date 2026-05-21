"""
Meta MCP Client.

platform_agent에서 호출하는 실제 Meta MCP 클라이언트.
Node.js meta-mcp/dist/server.js를 subprocess로 실행해 search_products 호출.
"""
import json
import os
import subprocess
from typing import Any

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

    params: dict[str, Any] = {
        "query": query,
        "platforms": valid_platforms,
        "sort": SORT_MAP.get(condition, "price_low"),
        "limit": 5,
    }
    if budget_max is not None:
        params["max_price"] = budget_max

    return _call_meta_mcp(params)
