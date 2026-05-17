"""
Webview Tool — Playwright + VLM 기반 실제 브라우저 자동화.

환경변수:
  ANTHROPIC_API_KEY  : Claude API 키
  KURLY_EMAIL        : 컬리 로그인 이메일/아이디
  KURLY_PASSWORD     : 컬리 로그인 비밀번호
"""
import anthropic
import base64
import json
import os
from playwright.sync_api import sync_playwright
from playwright_stealth import stealth_sync

client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

KURLY_EMAIL    = os.environ.get("KURLY_EMAIL", "")
KURLY_PASSWORD = os.environ.get("KURLY_PASSWORD", "")


# ══════════════════════════════════════════════
# VLM
# ══════════════════════════════════════════════

def ask_vlm(screenshot_bytes: bytes, question: str) -> dict:
    image_base64 = base64.standard_b64encode(screenshot_bytes).decode("utf-8")
    message = client.messages.create(
        model="claude-sonnet-4-6",
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
JSON 외에 다른 텍스트는 절대 포함하지 마.""",
                    },
                ],
            }
        ],
    )
    response_text = message.content[0].text.strip()
    return json.loads(response_text)


# ══════════════════════════════════════════════
# 헬퍼 함수
# ══════════════════════════════════════════════

def extract_delivery_info(page) -> dict:
    """
    상품 페이지 스크린샷에서 VLM으로 배송 정보 추출.
    Returns: {"delivery_type": str, "delivery_estimate": str, "found": bool}
    """
    screenshot = page.screenshot()
    result = ask_vlm(
        screenshot,
        """이 쇼핑 상품 페이지에서 배송 관련 정보를 찾아줘.
배송 방식 예시: 샛별배송, 택배배송, 로켓배송, 일반배송, 당일배송
배송 예정 예시: 내일 오전 7시 전 도착, 내일 도착, 오늘 출발 등

찾았을 때: {"delivery_type": "샛별배송", "delivery_estimate": "내일 오전 7시 전 도착", "found": true}
못 찾으면: {"delivery_type": "", "delivery_estimate": "", "found": false}""",
    )
    print(f"배송 정보: {result}")
    return result


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
        못 찾으면: {"x": 0, "y": 0, "found": false, "button_text": ""}""",
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

    page.wait_for_selector(
        "input[type='email'], input[name='id'], input[placeholder*='이메일'], input[placeholder*='아이디']",
        timeout=5000,
    )
    page.fill(
        "input[type='email'], input[name='id'], input[placeholder*='이메일'], input[placeholder*='아이디']",
        KURLY_EMAIL,
    )
    page.wait_for_timeout(500)
    page.fill("input[type='password']", KURLY_PASSWORD)
    page.wait_for_timeout(500)
    print("이메일/비밀번호 입력 완료")

    screenshot = page.screenshot()
    result = ask_vlm(
        screenshot,
        """화면에서 '로그인' 버튼을 찾아줘. (제출/확인 버튼 포함)
        찾았을 때: {"x": 195, "y": 500, "found": true, "button_text": "로그인"}
        못 찾으면: {"x": 0, "y": 0, "found": false, "button_text": ""}""",
    )
    print(f"로그인 버튼: {result}")

    if result.get("found", False):
        page.mouse.click(result["x"], result["y"])
    else:
        page.keyboard.press("Enter")

    page.wait_for_timeout(3000)
    print(f"로그인 완료! URL: {page.url}")


# ══════════════════════════════════════════════
# 메인 플로우
# ══════════════════════════════════════════════

def run_kurly_purchase(
    product_url: str,
    storage_state_path: str | None = None,
) -> dict:
    """
    컬리 상품 장바구니 담기.

    Parameters
    ----------
    product_url        : 상품 페이지 URL
    storage_state_path : 이전 세션 파일 경로 (연속 쇼핑 시 장바구니 유지)

    Returns
    -------
    dict : {"cart_added": bool, "storage_state_path": str | None, "delivery_info": str, "error": str | None}
    """
    playwright = sync_playwright().start()
    browser = playwright.webkit.launch(headless=False)

    context_kwargs = {
        "viewport": {"width": 390, "height": 844},
        "user_agent": (
            "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) "
            "Version/16.0 Mobile/15E148 Safari/604.1"
        ),
        "locale": "ko-KR",
    }

    # 이전 세션이 있으면 복원 (로그인 상태 + 장바구니 유지)
    if storage_state_path and os.path.exists(storage_state_path):
        context_kwargs["storage_state"] = storage_state_path
        print(f"세션 복원: {storage_state_path}")

    context = browser.new_context(**context_kwargs)
    page = context.new_page()
    stealth_sync(page)

    try:
        error_msg: str | None = None

        # ── 1. 상품 페이지 접속 ──
        print("1. 상품 페이지 접속 중...")
        page.goto(product_url)
        page.wait_for_load_state("domcontentloaded")
        page.wait_for_timeout(3000)
        print(f"2. 로딩 완료! URL: {page.url}")

        # ── 2. 배송 정보 추출 (페이지 로드 직후) ──
        delivery_result = extract_delivery_info(page)
        delivery_info = ""
        if delivery_result.get("found"):
            parts = [delivery_result.get("delivery_type", ""), delivery_result.get("delivery_estimate", "")]
            delivery_info = " ".join(p for p in parts if p)

        # ── 3. 장바구니 버튼 클릭 (비로그인) ──
        scroll_and_click_cart(page)
        page.wait_for_timeout(1000)

        # ── 4. 구매하기 버튼 클릭 ──
        # (로그인/배송지는 기저장 상태로 가정)
        scroll_and_click_cart(page)
        page.wait_for_timeout(2000)

        # ── 5. 'XXX원 장바구니 담기' 확인 버튼 클릭 ──
        screenshot = page.screenshot()
        print("4. 'XXX원 장바구니 담기' 버튼 찾는 중...")
        result = ask_vlm(
            screenshot,
            """화면에 '숫자+원 장바구니 담기' 형태의 버튼이 있어.
            예: '12,900원 장바구니 담기'처럼 가격은 가변적이야.
            찾았을 때: {"x": 195, "y": 750, "found": true, "button_text": "12,900원 장바구니 담기"}
            못 찾으면: {"x": 0, "y": 0, "found": false, "button_text": ""}""",
        )
        print(f"장바구니 담기 확인 버튼: {result}")

        if result.get("found", False):
            page.mouse.click(result["x"], result["y"])
            page.wait_for_timeout(2000)

        # ── 6. 팝업 닫기 ──
        page.wait_for_timeout(500)
        screenshot = page.screenshot()
        close_result = ask_vlm(
            screenshot,
            """팝업창의 X(닫기) 버튼을 찾아줘.
            찾았을 때: {"x": 350, "y": 200, "found": true}
            못 찾으면: {"x": 0, "y": 0, "found": false}""",
        )
        if close_result.get("found", False):
            page.mouse.click(close_result["x"], close_result["y"])
            page.wait_for_timeout(500)

        # ── 7. storageState 저장 (로그인 상태 + 장바구니 유지) ──
        saved_path = storage_state_path or f"session_{os.getpid()}.json"
        context.storage_state(path=saved_path)
        print(f"세션 저장 완료: {saved_path}")

        return {
            "cart_added": True,
            "storage_state_path": saved_path,
            "delivery_info": delivery_info,
            "error": None,
        }

    except Exception as e:
        print(f"webview 오류: {e}")
        return {"cart_added": False, "storage_state_path": None, "error": str(e)}

    finally:
        browser.close()
        playwright.stop()
