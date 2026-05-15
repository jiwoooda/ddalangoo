import anthropic
import base64
import json
import os
from playwright.sync_api import sync_playwright
from playwright_stealth import stealth_sync

client = anthropic.Anthropic(api_key="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")

def ask_vlm(screenshot_bytes: bytes, question: str) -> dict:
    image_base64 = base64.standard_b64encode(screenshot_bytes).decode("utf-8")
    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1024,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": image_base64,
                        },
                    },
                    {
                        "type": "text",
                        "text": f"""{question}
응답은 반드시 JSON 형식으로만 해줘.
JSON 외에 다른 텍스트는 절대 포함하지 마."""
                    }
                ],
            }
        ],
    )
    response_text = message.content[0].text.strip()
    return json.loads(response_text)


def scroll_and_click_cart(page):
    """스크롤 후 장바구니 버튼을 VLM으로 찾아 클릭"""
    print("맨 아래로 스크롤 중...")
    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    page.wait_for_timeout(1000)

    print("장바구니 버튼 찾는 중...")
    screenshot = page.screenshot()
    result = ask_vlm(
        screenshot,
        """화면 맨 아래에 보라색 '장바구니 담기' 버튼이 있어.
        그 버튼의 중앙 x, y 좌표를 알려줘.
        버튼은 화면 하단에 가로로 길게 있어.
        JSON: {"x": 270, "y": 820, "found": true, "button_text": "장바구니 담기"}
        못 찾으면: {"x": 0, "y": 0, "found": false, "button_text": ""}"""
    )
    print(f"버튼 위치: {result}")

    if not result.get("found", False):
        print("장바구니 버튼을 찾지 못했습니다.")
        return False

    page.mouse.click(result["x"], result["y"])
    page.wait_for_timeout(3000)
    print(f"장바구니 클릭 완료! URL: {page.url}")
    return True


# ── 브라우저 초기화 ──────────────────────────────────────────

playwright = sync_playwright().start()
browser = playwright.webkit.launch(headless=False)
context = browser.new_context(
    viewport={"width": 390, "height": 844},
    user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1",
    locale="ko-KR",
)
page = context.new_page()
stealth_sync(page)

url = "https://shopping.naver.com/window-products/kurlynmart/12273078535?nl-query=%EB%A7%88%EC%BC%93%EC%BB%AC%EB%A6%AC&nl-au=b38deea928fb4c4e9ee7403456dbef34&NaPm=ci%3Db38deea928fb4c4e9ee7403456dbef34%7Cct%3Dmp578ws0%7Ctr%3Dnslknm%7Csn%3DCC03%7Chk%3D530716dc7cb1d95a72d85c893079cf3f20ab8468"

# ── 1차 시도: 상품 페이지 접속 → 장바구니 클릭 ──────────────

print("1. 상품 페이지 접속 중...")
page.goto(url)
page.wait_for_load_state("networkidle")
page.wait_for_timeout(3000)
print(f"2. 로딩 완료! URL: {page.url}")

print("3. 화면 확인 중...")
page.screenshot(path="result.png")
print("4. 스크린샷 저장됨! result.png 확인해봐요")

# 5. input() 제거 → 바로 진행
scroll_and_click_cart(page)

# ── 로그인 버튼 클릭 ─────────────────────────────────────────

screenshot = page.screenshot(path="after_cart.png")
print("로그인 버튼 찾는 중...")
result = ask_vlm(
    screenshot,
    """화면에서 '로그인하기' 또는 '로그인' 버튼을 찾아줘.
    그 버튼의 중앙 x, y 좌표를 알려줘.
    JSON: {"x": 180, "y": 400, "found": true, "button_text": "로그인하기"}
    못 찾으면: {"x": 0, "y": 0, "found": false, "button_text": ""}"""
)
print(f"로그인 버튼 위치: {result}")

if result.get("found", False):
    page.mouse.click(result["x"], result["y"])
    page.wait_for_timeout(3000)
    page.screenshot(path="login_page.png")
    print(f"로그인 페이지 이동 완료! URL: {page.url}")

# ── 사용자 직접 로그인 대기 ──────────────────────────────────

print("\n로그인 페이지입니다. 브라우저에서 직접 로그인해주세요.")
print("로그인 완료 시 자동으로 다음 단계가 진행됩니다...\n")

# nid.naver.com(로그인 페이지)에서 벗어나면 로그인 완료로 판단 (최대 3분 대기)
page.wait_for_url(
    lambda u: "nid.naver.com" not in u,
    timeout=180000
)
print(f"로그인 완료 감지! 현재 URL: {page.url}")

# ── 2차 시도: 원래 상품 URL로 복귀 → 장바구니 재시도 ─────────

print("\n원래 상품 페이지로 돌아가는 중...")
page.goto(url)
page.wait_for_load_state("networkidle")
page.wait_for_timeout(3000)
print(f"상품 페이지 복귀 완료! URL: {page.url}")

page.screenshot(path="result_after_login.png")
print("스크린샷 저장됨! result_after_login.png")

scroll_and_click_cart(page)

# ── 'XXX원 장바구니에 담기' 확인 버튼 클릭 ───────────────────

page.wait_for_timeout(2000)
screenshot = page.screenshot(path="after_cart_loggedin.png")
print("'XXX원 장바구니에 담기' 버튼 찾는 중...")
result = ask_vlm(
    screenshot,
    """화면에 '숫자+원 장바구니에 담기' 형태의 버튼이 있어.
    예: '12,900원 장바구니에 담기', '3,500원 장바구니에 담기'처럼 가격은 가변적이야.
    그 버튼의 중앙 x, y 좌표와 버튼에 표시된 텍스트를 알려줘.
    찾았을 때: {"x": 195, "y": 750, "found": true, "button_text": "12,900원 장바구니에 담기"}
    못 찾으면: {"x": 0, "y": 0, "found": false, "button_text": ""}"""
)
print(f"'장바구니에 담기' 확인 버튼: {result}")

if result.get("found", False):
    print(f"버튼 클릭 중... ({result['x']}, {result['y']}) / {result['button_text']}")
    page.mouse.click(result["x"], result["y"])
    page.wait_for_timeout(2000)
    page.screenshot(path="cart_confirmed.png")
    print("장바구니 담기 최종 완료! cart_confirmed.png 확인해봐요")
else:
    print("'XXX원 장바구니에 담기' 버튼을 찾지 못했습니다. after_cart_loggedin.png 확인해봐요")

# ── '장바구니 바로가기' 버튼 클릭 ────────────────────────────

page.wait_for_timeout(1000)
screenshot = page.screenshot(path="before_go_cart.png")
print("'장바구니 바로가기' 버튼 찾는 중...")
result = ask_vlm(
    screenshot,
    """화면에서 '장바구니 바로가기' 버튼을 찾아줘.
    그 버튼의 중앙 x, y 좌표를 알려줘.
    찾았을 때: {"x": 195, "y": 750, "found": true, "button_text": "장바구니 바로가기"}
    못 찾으면: {"x": 0, "y": 0, "found": false, "button_text": ""}"""
)
print(f"'장바구니 바로가기' 버튼: {result}")

if result.get("found", False):
    print(f"버튼 클릭 중... ({result['x']}, {result['y']})")
    page.mouse.click(result["x"], result["y"])
    page.wait_for_timeout(3000)
    page.screenshot(path="cart_page.png")
    print(f"장바구니 페이지 이동 완료! URL: {page.url}")
else:
    print("'장바구니 바로가기' 버튼을 찾지 못했습니다. before_go_cart.png 확인해봐요")

input("\nEnter 누르면 종료...")
browser.close()
playwright.stop()
