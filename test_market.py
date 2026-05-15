import anthropic
import base64
import json
import os
from playwright.sync_api import sync_playwright
from playwright_stealth import stealth_sync

client = anthropic.Anthropic(api_key="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")

# ── 로그인 정보 ───────────────────────────────────────────────
KURLY_EMAIL    = "happypot01"
KURLY_PASSWORD = "sophia0418!"

PRODUCT_URL = "https://www.kurly.com/goods/5106292"

# ── VLM 함수 ─────────────────────────────────────────────────

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


def scroll_and_click_cart(page) -> bool:
    """스크롤 후 장바구니 버튼을 VLM으로 찾아 클릭"""
    print("맨 아래로 스크롤 중...")
    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    page.wait_for_timeout(1000)

    print("구매하기 버튼 찾는 중...")
    screenshot = page.screenshot()
    result = ask_vlm(
        screenshot,
        """화면 하단에 '구매하기' 버튼이 있어.
        그 버튼의 중앙 x, y 좌표를 알려줘.
        찾았을 때: {"x": 195, "y": 820, "found": true, "button_text": "구매하기"}
        못 찾으면: {"x": 0, "y": 0, "found": false, "button_text": ""}"""
    )
    print(f"장바구니 버튼: {result}")

    if not result.get("found", False):
        print("장바구니 버튼을 찾지 못했습니다.")
        return False

    page.mouse.click(result["x"], result["y"])
    page.wait_for_timeout(2000)
    print(f"장바구니 클릭 완료! URL: {page.url}")
    return True


def do_login(page):
    """이메일/비밀번호 자동 입력 후 로그인"""
    print("로그인 시도 중...")

    # 이메일 입력
    page.wait_for_selector("input[type='email'], input[name='id'], input[placeholder*='이메일'], input[placeholder*='아이디']", timeout=5000)
    page.fill("input[type='email'], input[name='id'], input[placeholder*='이메일'], input[placeholder*='아이디']", KURLY_EMAIL)
    page.wait_for_timeout(500)

    # 비밀번호 입력
    page.fill("input[type='password']", KURLY_PASSWORD)
    page.wait_for_timeout(500)

    print("이메일/비밀번호 입력 완료")

    # 로그인 버튼 클릭 (VLM)
    screenshot = page.screenshot()
    result = ask_vlm(
        screenshot,
        """화면에서 '로그인' 버튼을 찾아줘. (제출/확인 버튼 포함)
        찾았을 때: {"x": 195, "y": 500, "found": true, "button_text": "로그인"}
        못 찾으면: {"x": 0, "y": 0, "found": false, "button_text": ""}"""
    )
    print(f"로그인 버튼: {result}")

    if result.get("found", False):
        page.mouse.click(result["x"], result["y"])
    else:
        # VLM 실패 시 Enter 키로 제출
        page.keyboard.press("Enter")

    page.wait_for_timeout(3000)
    print(f"로그인 완료! URL: {page.url}")


# ── 브라우저 초기화 ───────────────────────────────────────────

playwright = sync_playwright().start()
browser = playwright.webkit.launch(headless=False)
context = browser.new_context(
    viewport={"width": 390, "height": 844},
    user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1",
    locale="ko-KR",
)
page = context.new_page()
stealth_sync(page)

# ── 1. 상품 페이지 접속 ───────────────────────────────────────

print("1. 상품 페이지 접속 중...")
page.goto(PRODUCT_URL)
page.wait_for_load_state("domcontentloaded")
page.wait_for_timeout(3000)
print(f"2. 로딩 완료! URL: {page.url}")
page.screenshot(path="kurly_product.png")

# ── 2. 장바구니 버튼 클릭 (비로그인) ─────────────────────────

scroll_and_click_cart(page)
page.wait_for_timeout(1000)
page.screenshot(path="kurly_after_cart.png")

# ── 3. 로그인 페이지 감지 → 자동 로그인 ──────────────────────

current_url = page.url
if "login" in current_url or "signin" in current_url:
    print("3. 로그인 페이지 감지됨 → 자동 로그인 시도")
    do_login(page)
else:
    # 로그인 버튼이 팝업/모달로 뜨는 경우 VLM으로 확인
    screenshot = page.screenshot()
    login_check = ask_vlm(
        screenshot,
        """화면에 로그인 입력 폼 또는 '로그인하기' 버튼이 있나요?
        있으면: {"login_required": true}
        없으면: {"login_required": false}"""
    )
    if login_check.get("login_required", False):
        print("3. 로그인 필요 감지됨 → 자동 로그인 시도")
        do_login(page)
    else:
        print("3. 로그인 불필요 (이미 로그인 상태)")

page.screenshot(path="kurly_after_login.png")

# ── 4. 상품 페이지 복귀 → 장바구니 재시도 ────────────────────

print("4. 상품 페이지로 복귀 중...")
page.goto(PRODUCT_URL)
page.wait_for_load_state("domcontentloaded")
page.wait_for_timeout(3000)
print(f"상품 페이지 복귀 완료! URL: {page.url}")

scroll_and_click_cart(page)

# ── 5. 'XXX원 장바구니 담기' 버튼 클릭 ──────────────────────

page.wait_for_timeout(2000)
screenshot = page.screenshot(path="kurly_cart_confirm.png")
print("5. 'XXX원 장바구니 담기' 버튼 찾는 중...")
result = ask_vlm(
    screenshot,
    """화면에 '숫자+원 장바구니 담기' 형태의 버튼이 있어.
    예: '12,900원 장바구니 담기', '3,500원 장바구니 담기'처럼 가격은 가변적이야.
    그 버튼의 중앙 x, y 좌표와 버튼 텍스트를 알려줘.
    찾았을 때: {"x": 195, "y": 750, "found": true, "button_text": "12,900원 장바구니 담기"}
    못 찾으면: {"x": 0, "y": 0, "found": false, "button_text": ""}"""
)
print(f"확인 버튼: {result}")

if result.get("found", False):
    print(f"클릭 중... {result['button_text']}")
    page.mouse.click(result["x"], result["y"])
    page.wait_for_timeout(2000)
    page.screenshot(path="kurly_cart_done.png")
    print("장바구니 담기 완료! kurly_cart_done.png 확인해봐요")
else:
    print("확인 버튼을 찾지 못했습니다. kurly_cart_confirm.png 확인해봐요")

# ── 6. 팝업 X 버튼 클릭 ──────────────────────────────────────

page.wait_for_timeout(1000)
screenshot = page.screenshot(path="kurly_popup.png")
print("6. 팝업 닫기 버튼(X) 찾는 중...")
result = ask_vlm(
    screenshot,
    """화면에 팝업창이 떠 있어. 팝업을 닫는 X 버튼을 찾아줘.
    찾았을 때: {"x": 350, "y": 200, "found": true, "button_text": "X"}
    못 찾으면: {"x": 0, "y": 0, "found": false, "button_text": ""}"""
)
print(f"X 버튼: {result}")

if result.get("found", False):
    print(f"X 버튼 클릭 중... ({result['x']}, {result['y']})")
    page.mouse.click(result["x"], result["y"])
    page.wait_for_timeout(1000)
else:
    print("X 버튼을 찾지 못했습니다. kurly_popup.png 확인해봐요")

# ── 7. 장바구니 아이콘 클릭 → 장바구니 페이지 이동 ───────────

page.wait_for_timeout(500)
screenshot = page.screenshot(path="kurly_before_cart_icon.png")
print("7. 장바구니 아이콘 찾는 중...")
result = ask_vlm(
    screenshot,
    """화면 상단에 장바구니 아이콘(바구니 모양)이 있어. 그 아이콘의 중앙 x, y 좌표를 알려줘.
    찾았을 때: {"x": 355, "y": 30, "found": true, "button_text": "장바구니"}
    못 찾으면: {"x": 0, "y": 0, "found": false, "button_text": ""}"""
)
print(f"장바구니 아이콘: {result}")

if result.get("found", False):
    print(f"장바구니 아이콘 클릭 중... ({result['x']}, {result['y']})")
    page.mouse.click(result["x"], result["y"])
    page.wait_for_load_state("domcontentloaded")
    page.wait_for_timeout(4000)
    page.screenshot(path="kurly_cart_page.png")
    print(f"장바구니 페이지 이동 완료! URL: {page.url}")
else:
    print("장바구니 아이콘을 찾지 못했습니다. kurly_before_cart_icon.png 확인해봐요")

# ── 8. 장바구니 페이지 '로그인' 버튼 클릭 ────────────────────

screenshot = page.screenshot(path="kurly_cart_login.png")
print("8. '로그인' 버튼 찾는 중...")
result = ask_vlm(
    screenshot,
    """화면에서 '로그인' 버튼을 찾아줘.
    찾았을 때: {"x": 195, "y": 500, "found": true, "button_text": "로그인"}
    못 찾으면: {"x": 0, "y": 0, "found": false, "button_text": ""}"""
)
print(f"'로그인' 버튼: {result}")

if result.get("found", False):
    print(f"클릭 중... ({result['x']}, {result['y']})")
    page.mouse.click(result["x"], result["y"])
    page.wait_for_timeout(2000)
    page.screenshot(path="kurly_login_method.png")
    print(f"로그인 수단 선택 페이지 이동! URL: {page.url}")
else:
    print("'로그인' 버튼을 찾지 못했습니다. kurly_cart_login.png 확인해봐요")

# ── 9. '컬리 아이디로 로그인하기' 버튼 클릭 ─────────────────

page.wait_for_load_state("domcontentloaded")
page.wait_for_timeout(3000)
screenshot = page.screenshot(path="kurly_login_method.png")
print("9. '컬리 아이디로 로그인하기' 버튼 찾는 중...")
result = ask_vlm(
    screenshot,
    """화면에서 '컬리 아이디로 로그인하기' 또는 '컬리 아이디로 로그인' 버튼을 찾아줘.
    반드시 '로그인'이라는 단어가 포함된 버튼이어야 해.
    '회원가입'이 포함된 버튼은 절대 선택하면 안 돼. '로그인'과 '회원가입'은 다른 버튼이야.
    찾았을 때: {"x": 195, "y": 500, "found": true, "button_text": "컬리 아이디로 로그인하기"}
    못 찾으면: {"x": 0, "y": 0, "found": false, "button_text": ""}"""
)
print(f"'컬리 아이디로 로그인' 버튼: {result}")

if result.get("found", False):
    print(f"클릭 중... ({result['x']}, {result['y']})")
    page.mouse.click(result["x"], result["y"])
    page.wait_for_load_state("domcontentloaded")
    page.wait_for_timeout(2000)
    page.screenshot(path="kurly_login_form.png")
    print(f"로그인 폼 페이지 이동! URL: {page.url}")
else:
    print("'컬리 아이디로 로그인하기' 버튼을 찾지 못했습니다. kurly_login_method.png 확인해봐요")

# ── 10. 아이디/비밀번호 입력 후 로그인 ───────────────────────

page.wait_for_timeout(1000)
print("10. 아이디/비밀번호 입력 중...")
try:
    page.wait_for_selector(
        "input[type='email'], input[name='id'], input[placeholder*='이메일'], input[placeholder*='아이디']",
        timeout=5000
    )
    page.fill(
        "input[type='email'], input[name='id'], input[placeholder*='이메일'], input[placeholder*='아이디']",
        KURLY_EMAIL
    )
    page.wait_for_timeout(500)
    page.fill("input[type='password']", KURLY_PASSWORD)
    page.wait_for_timeout(500)
    print("아이디/비밀번호 입력 완료")
except Exception as e:
    print(f"입력 필드를 찾지 못했습니다: {e}")
    print("kurly_login_form.png 확인해봐요")

# 로그인 버튼 클릭 (VLM)
screenshot = page.screenshot(path="kurly_login_ready.png")
result = ask_vlm(
    screenshot,
    """화면에서 '로그인' 제출 버튼을 찾아줘.
    찾았을 때: {"x": 195, "y": 600, "found": true, "button_text": "로그인"}
    못 찾으면: {"x": 0, "y": 0, "found": false, "button_text": ""}"""
)
print(f"로그인 제출 버튼: {result}")

if result.get("found", False):
    page.mouse.click(result["x"], result["y"])
else:
    page.keyboard.press("Enter")

page.wait_for_load_state("domcontentloaded")
page.wait_for_timeout(3000)
page.screenshot(path="kurly_after_login.png")
print(f"로그인 완료! URL: {page.url}")

# ── 11. 비밀번호 변경 페이지 → '다음에 변경하기' 클릭 ─────────

page.wait_for_timeout(1000)
screenshot = page.screenshot(path="kurly_pw_change.png")
print("11. '다음에 변경하기' 버튼 찾는 중...")
result = ask_vlm(
    screenshot,
    """화면에서 '다음에 변경하기' 버튼을 찾아줘.
    찾았을 때: {"x": 195, "y": 600, "found": true, "button_text": "다음에 변경하기"}
    못 찾으면: {"x": 0, "y": 0, "found": false, "button_text": ""}"""
)
print(f"'다음에 변경하기' 버튼: {result}")

if result.get("found", False):
    print(f"클릭 중... ({result['x']}, {result['y']})")
    page.mouse.click(result["x"], result["y"])
    page.wait_for_load_state("domcontentloaded")
    page.wait_for_timeout(2000)
    page.screenshot(path="kurly_order_page.png")
    print(f"주문 페이지 이동! URL: {page.url}")
else:
    print("'다음에 변경하기' 버튼을 찾지 못했습니다. kurly_pw_change.png 확인해봐요")

# ── 12. '혜택없이 XXX원 주문하기' 버튼 클릭 ─────────────────

print("12. 맨 아래로 스크롤 중...")
page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
page.wait_for_timeout(1000)
screenshot = page.screenshot(path="kurly_order_btn.png")
print("'혜택없이 XXX원 주문하기' 버튼 찾는 중...")
result = ask_vlm(
    screenshot,
    """화면에 주문하기 버튼이 2개 있어. 두 버튼의 좌표를 모두 알려줘.
    {"buttons": [{"x": 195, "y": 700, "text": "15,900원 주문하기"}, {"x": 195, "y": 780, "text": "혜택없이 17,900원 주문하기"}]}
    버튼이 1개만 보이면 그것만, 못 찾으면 {"buttons": []} 로 응답해."""
)

buttons = result.get("buttons", [])
if buttons:
    bottom_button = max(buttons, key=lambda b: b["y"])
    print(f"선택된 버튼: {bottom_button['text']}")
    page.mouse.click(bottom_button["x"], bottom_button["y"])
    page.wait_for_timeout(2000)
    page.screenshot(path="kurly_order_popup1.png")
else:
    print("버튼을 찾지 못했습니다. kurly_order_btn.png 확인해봐요")

# ── 13. 첫 번째 팝업 → 'XXX원 주문하기' 클릭 ─────────────────

page.wait_for_timeout(1000)
screenshot = page.screenshot(path="kurly_order_popup1.png")
print("13. 팝업 'XXX원 주문하기' 버튼 찾는 중...")
result = ask_vlm(
    screenshot,
    """화면에 팝업창이 떠 있어. 팝업 안에서 '숫자+원 주문하기' 형태의 버튼을 찾아줘.
    예: '12,900원 주문하기'처럼 가격은 가변적이야.
    찾았을 때: {"x": 195, "y": 600, "found": true, "button_text": "12,900원 주문하기"}
    못 찾으면: {"x": 0, "y": 0, "found": false, "button_text": ""}"""
)
print(f"첫 번째 팝업 주문 버튼: {result}")

if result.get("found", False):
    print(f"클릭 중... {result['button_text']}")
    page.mouse.click(result["x"], result["y"])
    page.wait_for_timeout(2000)
    page.screenshot(path="kurly_order_popup2.png")
else:
    print("첫 번째 팝업 버튼을 찾지 못했습니다. kurly_order_popup1.png 확인해봐요")

# ── 14. 두 번째 팝업 → 'XXX원 주문하기' 클릭 (최종) ──────────

page.wait_for_timeout(1000)
screenshot = page.screenshot(path="kurly_order_popup2.png")
print("14. 두 번째 팝업 'XXX원 주문하기' 버튼 찾는 중...")
result = ask_vlm(
    screenshot,
    """화면에 팝업창이 떠 있어. 팝업 안에서 '숫자+원 주문하기' 형태의 버튼을 찾아줘.
    예: '12,900원 주문하기'처럼 가격은 가변적이야.
    찾았을 때: {"x": 195, "y": 600, "found": true, "button_text": "12,900원 주문하기"}
    못 찾으면: {"x": 0, "y": 0, "found": false, "button_text": ""}"""
)
print(f"두 번째 팝업 주문 버튼: {result}")

if result.get("found", False):
    print(f"최종 주문 클릭 중... {result['button_text']}")
    page.mouse.click(result["x"], result["y"])
    page.wait_for_timeout(3000)
    page.screenshot(path="kurly_order_complete.png")
    print(f"주문 완료! URL: {page.url}")
else:
    print("두 번째 팝업 버튼을 찾지 못했습니다. kurly_order_popup2.png 확인해봐요")

input("\nEnter 누르면 종료...")
browser.close()
playwright.stop()
