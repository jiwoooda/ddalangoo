"""
Webview Tool — Playwright + VLM 기반 컬리 모바일웹 자동화.

플로우:
  1. 컬리 모바일웹 오픈
  2. 로그인 여부 확인 → 필요 시 로그인
  3. 상품명 검색
  4. VLM: 검색 결과에서 일치 상품 선택
  5. VLM: 구매하기 버튼 클릭
  6. 장바구니 담기 확인
  7. 세션 저장

환경변수:
  ANTHROPIC_API_KEY : Claude API 키
  KURLY_EMAIL       : 컬리 로그인 이메일
  KURLY_PASSWORD    : 컬리 로그인 비밀번호
"""
import anthropic
import base64
import json
import os
from playwright.sync_api import sync_playwright, Page

try:
    from playwright_stealth import stealth_sync
except ImportError:
    def stealth_sync(page): pass

client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

KURLY_EMAIL    = os.environ.get("KURLY_EMAIL", "")
KURLY_PASSWORD = os.environ.get("KURLY_PASSWORD", "")
KURLY_BASE_URL = "https://www.kurly.com"

VIEWPORT = {"width": 390, "height": 844}
USER_AGENT = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) "
    "Version/16.0 Mobile/15E148 Safari/604.1"
)


# ══════════════════════════════════════════════
# VLM 헬퍼
# ══════════════════════════════════════════════

def _ask_vlm(screenshot_bytes: bytes, question: str) -> dict:
    """스크린샷 + 질문 → JSON 응답"""
    print(f"[webview:VLM] 질의 시작: '{question}'")
    image_b64 = base64.standard_b64encode(screenshot_bytes).decode("utf-8")
    msg = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=512,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": image_b64}},
                {"type": "text", "text": question + "\n반드시 JSON만 반환."},
            ],
        }],
    )
    text = msg.content[0].text.strip()
    print(f"[webview:VLM] 응답 완료: {text}")
    # ```json ... ``` 블록 제거
    if "```" in text:
        import re
        m = re.search(r"```(?:json)?\s*([\s\S]+?)```", text)
        text = m.group(1).strip() if m else text
    return json.loads(text)


def _screenshot_and_ask(page: Page, question: str) -> dict:
    return _ask_vlm(page.screenshot(), question)


# ══════════════════════════════════════════════
# 단계별 함수
# ══════════════════════════════════════════════

def _is_logged_in(page: Page) -> bool:
    """현재 페이지가 로그인 상태인지 확인"""
    print("[webview] 로그인 상태 확인 중...")
    result = _screenshot_and_ask(
        page,
        '화면 상단에 로그인/회원가입 버튼이 보이면 {"logged_in": false}, '
        '마이페이지·프로필·장바구니 아이콘이 보이면 {"logged_in": true}',
    )
    logged = result.get("logged_in", False)
    print(f"[webview] 로그인 상태 확인 결과: {'로그인 됨' if logged else '로그아웃 됨'}")
    return logged


def _login(page: Page) -> bool:
    """컬리 로그인 수행. 성공 여부 반환"""
    print("[webview] 로그인 페이지 진입 중...")
    page.goto(f"{KURLY_BASE_URL}/member/login")
    page.wait_for_load_state("domcontentloaded")
    page.wait_for_timeout(2000)

    # SNS 로그인 화면일 경우 '컬리아이디로 로그인' 클릭
    print("[webview] '컬리아이디로 로그인' 메뉴 탐색 중...")
    sns_login_check = _screenshot_and_ask(
        page,
        '화면에서 "컬리아이디로 로그인" 또는 "이메일로 로그인" 텍스트/버튼의 중앙 좌표를 찾아줘. '
        '{"x": 195, "y": 700, "found": true} 또는 {"x":0,"y":0,"found":false}'
    )
    if sns_login_check.get("found"):
        print(f"[webview] '컬리아이디로 로그인' 클릭 ({sns_login_check['x']}, {sns_login_check['y']})")
        page.mouse.click(sns_login_check["x"], sns_login_check["y"])
        page.wait_for_timeout(2000)
    else:
        print("[webview] '컬리아이디로 로그인' 텍스트 기반 클릭 재시도...")
        try:
            page.locator("text=/.*컬리.*로그인.*/").first.click(timeout=2000)
            page.wait_for_timeout(2000)
        except:
            pass

    try:
        print("[webview] 아이디(이메일) 입력 중...")
        page.fill("input[name='id'], input[type='email'], input[placeholder*='아이디']", KURLY_EMAIL)
        page.wait_for_timeout(300)
        print("[webview] 비밀번호 입력 중...")
        page.fill("input[type='password']", KURLY_PASSWORD)
        page.wait_for_timeout(300)
    except Exception as e:
        print(f"[webview] 입력 필드 오류: {e}")
        return False

    # 로그인 버튼 VLM 탐색
    print("[webview] 로그인 버튼 탐색 중...")
    result = _screenshot_and_ask(
        page,
        '로그인 제출 버튼의 중앙 좌표. '
        '{"x": 195, "y": 500, "found": true} 또는 {"x":0,"y":0,"found":false}',
    )
    if result.get("found"):
        print(f"[webview] 로그인 버튼 클릭 ({result['x']}, {result['y']})")
        page.mouse.click(result["x"], result["y"])
    else:
        print("[webview] 로그인 버튼을 찾지 못해 Enter 키 입력")
        page.keyboard.press("Enter")

    print("[webview] 로그인 처리 대기 중...")
    page.wait_for_timeout(3000)
    logged = _is_logged_in(page)
    print(f"[webview] 로그인 {'성공' if logged else '실패'} — URL: {page.url}")
    return logged


def _search_product(page: Page, query: str) -> bool:
    """컬리 검색창에 상품명 입력 후 결과 페이지 이동. 성공 여부 반환"""
    print(f"[webview] 상품 검색 시작: '{query}'")
    search_url = f"{KURLY_BASE_URL}/search?sword={query}"
    page.goto(search_url)
    page.wait_for_load_state("domcontentloaded")
    page.wait_for_timeout(2500)
    print("[webview] 상품 검색 결과 페이지 로드 완료")
    return True


def _select_product_from_results(page: Page, product_name: str) -> bool:
    """
    검색 결과에서 product_name과 가장 유사한 상품을 VLM으로 찾아 클릭.
    성공 여부 반환
    """
    print(f"[webview] 검색 결과에서 상품 탐색 (VLM): {product_name}")

    # 1. 강제로 스크롤 최상단 이동 후, 2. CSS로 스크롤 자체를 원천 차단(잠금)
    print("[webview] 화면 스크롤 최상단 고정 및 스크롤 원천 잠금...")
    page.evaluate("window.scrollTo(0, 0); document.body.style.overflow = 'hidden';")
    page.wait_for_timeout(2000)  # 상품 썸네일 이미지가 완전히 뜰 때까지 충분히 대기

    # VLM 기반 탐색
    result = _screenshot_and_ask(
        page,
        f'검색 결과 목록에서 목표 상품명: "{product_name}" 을 찾아줘.\n'
        '다음 순서대로 분석해:\n'
        '1. 화면에 보이는 상품들의 이름(텍스트)들을 전부 읽어본다.\n'
        '2. 목표 상품명과 가장 똑같은 정답 상품을 찾는다. (브랜드명이나 수식어가 약간 달라도 핵심 상품명이 일치하는 가장 첫 번째 상품)\n'
        '3. 찾은 정답 상품의 글씨가 아니라, **해당 상품명 글씨 바로 위에 있는 상품 썸네일 사진(이미지)**의 정중앙 좌표를 계산한다.\n'
        '결과는 반드시 JSON으로 반환하되, reasoning 필드에 어떤 상품들을 확인했고 왜 이 좌표를 선택했는지 생각 과정을 먼저 적어줘!\n'
        '{"reasoning": "화면에 A, B가 보이고... 목표와 일치하는 것은 A이므로 썸네일 좌표를 선택함", "x": 195, "y": 300, "found": true, "matched_name": "..."} 또는 {"reasoning": "...", "x":0,"y":0,"found":false,"matched_name":""}',
    )
    print(f"[webview] 상품 선택: {result}")

    if not result.get("found"):
        print(f"[webview] 검색 결과에서 '{product_name}'을(를) 찾지 못했습니다.")
        return False

    print(f"[webview] 해당 상품 클릭 ({result['x']}, {result['y']})")
    page.mouse.click(result["x"], result["y"])
    page.wait_for_load_state("domcontentloaded")
    page.wait_for_timeout(2500)
    print("[webview] 상품 상세 페이지 로드 완료")
    return True


def _click_purchase_button(page: Page) -> bool:
    """상품 상세 페이지에서 구매하기/담기 버튼 클릭. 성공 여부 반환"""
    print("[webview] 구매하기 버튼 탐색...")

    result = _screenshot_and_ask(
        page,
        '화면에서 "구매하기", "바로구매", "장바구니 담기" 버튼 중 하나의 중앙 좌표. '
        '{"x": 195, "y": 760, "found": true, "button_text": "구매하기"} 또는 {"x":0,"y":0,"found":false,"button_text":""}',
    )
    print(f"[webview] 구매 버튼: {result}")

    if not result.get("found"):
        print("[webview] 구매하기 버튼을 찾지 못했습니다.")
        return False

    print(f"[webview] 구매하기 버튼 클릭 ({result['x']}, {result['y']})")
    page.mouse.click(result["x"], result["y"])
    page.wait_for_timeout(2500)
    return True


def _confirm_cart(page: Page) -> bool:
    """
    구매하기 클릭 후 나타나는 확인 팝업(금액+장바구니 담기 버튼)을 처리.
    성공 여부 반환
    """
    print("[webview] 장바구니 담기 최종 확인 팝업 탐색...")
    screenshot = page.screenshot()
    result = _ask_vlm(
        screenshot,
        '"장바구니 담기", "담기", "확인" 등 최종 확인 버튼이 보이면 좌표 반환. '
        '{"x": 195, "y": 750, "found": true, "button_text": "..."} 또는 {"x":0,"y":0,"found":false,"button_text":""}',
    )
    print(f"[webview] 장바구니 확인 버튼: {result}")

    if result.get("found"):
        print(f"[webview] 장바구니 최종 담기 버튼 클릭 ({result['x']}, {result['y']})")
        page.mouse.click(result["x"], result["y"])
        page.wait_for_timeout(2000)

    # 팝업 닫기
    print("[webview] 확인 팝업 닫기(X) 버튼 탐색...")
    screenshot = page.screenshot()
    close = _ask_vlm(
        screenshot,
        '팝업 닫기(X) 버튼이 보이면 좌표. {"x":350,"y":200,"found":true} 또는 {"x":0,"y":0,"found":false}',
    )
    if close.get("found"):
        print(f"[webview] 팝업 닫기 클릭 ({close['x']}, {close['y']})")
        page.mouse.click(close["x"], close["y"])
        page.wait_for_timeout(500)

    print("[webview] 장바구니 확인 절차 완료")
    return True


def _extract_delivery_info(page: Page) -> str:
    """상품 페이지에서 배송 정보 추출"""
    print("[webview] 배송 정보 추출 시도 중...")
    result = _screenshot_and_ask(
        page,
        '이 페이지에서 배송 방식과 예상 도착 시간을 찾아줘. '
        '{"delivery_type": "샛별배송", "delivery_estimate": "내일 오전 7시 전", "found": true} '
        '또는 {"delivery_type":"","delivery_estimate":"","found":false}',
    )
    if result.get("found"):
        parts = [result.get("delivery_type", ""), result.get("delivery_estimate", "")]
        info = " ".join(p for p in parts if p)
        print(f"[webview] 추출된 배송 정보: {info}")
        return info
    print("[webview] 배송 정보를 찾지 못했습니다.")
    return ""


# ══════════════════════════════════════════════
# 메인 진입점
# ══════════════════════════════════════════════

def run_kurly_purchase(
    product_name: str,
    keywords: list[str] | None = None,
    storage_state_path: str | None = None,
) -> dict:
    """
    컬리 모바일웹에서 상품 검색 → 장바구니 담기.

    Parameters
    ----------
    product_name       : 선택된 상품명 (검색 + VLM 매칭에 사용)
    keywords           : 검색 키워드 (없으면 product_name 사용)
    storage_state_path : 이전 세션 파일 경로 (로그인 상태 유지용)

    Returns
    -------
    dict: {"cart_added": bool, "storage_state_path": str|None, "delivery_info": str, "error": str|None}
    """
    search_query = " ".join(keywords) if keywords else product_name

    playwright = sync_playwright().start()
    print("[webview] 브라우저(Webkit) 시작 중...")
    browser = playwright.webkit.launch(headless=False)

    context_kwargs = {
        "viewport": VIEWPORT,
        "user_agent": USER_AGENT,
        "locale": "ko-KR",
    }
    if storage_state_path and os.path.exists(storage_state_path):
        context_kwargs["storage_state"] = storage_state_path
        print(f"[webview] 세션 복원: {storage_state_path}")

    context = browser.new_context(**context_kwargs)
    page = context.new_page()
    stealth_sync(page)

    try:
        # ── 1. 컬리 메인 접속 및 로그인 확인 ──
        print("[webview] 컬리 접속 중...")
        page.goto(KURLY_BASE_URL)
        page.wait_for_load_state("domcontentloaded")
        page.wait_for_timeout(2000)

        if not _is_logged_in(page):
            print("[webview] 로그인이 필요합니다. 로그인 플로우 시작...")
            success = _login(page)
            if not success:
                print("[webview] 로그인 플로우 실패. 종료합니다.")
                return {"cart_added": False, "storage_state_path": None,
                        "delivery_info": "", "error": "login_failed"}

        # ── 2. 상품 검색 ──
        print(f"\n[webview] Step 2. 상품 검색 시작 ({search_query})")
        _search_product(page, search_query)

        # ── 3. 검색 결과에서 상품 선택 ──
        print(f"\n[webview] Step 3. 검색 결과에서 상품 선택 ({product_name})")
        found = _select_product_from_results(page, product_name)
        if not found:
            return {"cart_added": False, "storage_state_path": None,
                    "delivery_info": "", "error": "product_not_found_in_search"}

        # ── 4. 배송 정보 추출 ──
        print("\n[webview] Step 4. 배송 정보 확인")
        delivery_info = _extract_delivery_info(page)

        # ── 5. 구매하기 버튼 클릭 ──
        print("\n[webview] Step 5. 구매하기 버튼 클릭")
        clicked = _click_purchase_button(page)
        if not clicked:
            return {"cart_added": False, "storage_state_path": None,
                    "delivery_info": delivery_info, "error": "purchase_button_not_found"}

        # ── 6. 장바구니 담기 확인 팝업 처리 ──
        print("\n[webview] Step 6. 장바구니 팝업 처리")
        _confirm_cart(page)

        # ── 7. 세션 저장 ──
        print("\n[webview] Step 7. 세션 저장")
        saved_path = storage_state_path or f"session_{os.getpid()}.json"
        context.storage_state(path=saved_path)
        print(f"[webview] 세션 저장: {saved_path}")

        return {
            "cart_added": True,
            "storage_state_path": saved_path,
            "delivery_info": delivery_info,
            "error": None,
        }

    except Exception as e:
        print(f"[webview] 오류: {e}")
        return {"cart_added": False, "storage_state_path": None,
                "delivery_info": "", "error": str(e)}

    finally:
        browser.close()
        playwright.stop()
