"""
Webview Tool — Playwright + VLM 기반 컬리 모바일웹 자동화.

각 액션마다 DOM/CSS selector 우선 시도 → 실패 시 VLM 폴백.
  _dom_XXX : CSS selector / JS evaluate 기반 (빠름, UI 변경에 취약)
  _vlm_XXX : VLM 스크린샷 기반 (느림, UI 변경에 강함)
  _XXX     : 오케스트레이터 (DOM 먼저, 실패 시 VLM)

VLM이 필수인 단계: _select_product_from_results (검색 결과는 매번 달라서 DOM 대체 불가)

환경변수:
  ANTHROPIC_API_KEY : Claude API 키
  KURLY_EMAIL       : 컬리 로그인 이메일
  KURLY_PASSWORD    : 컬리 로그인 비밀번호
  WEBVIEW_HEADLESS  : true면 서버 환경에서 headless 브라우저로 실행
"""
import anthropic
import base64
import json
import os
import re
import threading
from collections.abc import Callable
from typing import Any
from playwright.sync_api import sync_playwright, Page

try:
    from playwright_stealth import stealth_sync
except ImportError:
    def stealth_sync(page): pass


# ── 취소 메커니즘 ──────────────────────────────────────────
class WebviewCancelledError(Exception):
    pass

_cancel_event = threading.Event()


def request_cancel() -> None:
    """진행 중인 Playwright 세션 취소 요청. API 레이어에서 호출."""
    _cancel_event.set()


def _clear_cancel() -> None:
    _cancel_event.clear()


def _check_cancel() -> None:
    if _cancel_event.is_set():
        raise WebviewCancelledError("사용자 취소 요청")
# ──────────────────────────────────────────────────────────

client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

KURLY_EMAIL    = os.environ.get("KURLY_EMAIL", "")
KURLY_PASSWORD = os.environ.get("KURLY_PASSWORD", "")
KURLY_BASE_URL = "https://www.kurly.com"
WEBVIEW_HEADLESS = os.environ.get("WEBVIEW_HEADLESS", "true").lower() != "false"

VIEWPORT = {"width": 390, "height": 844}
USER_AGENT = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) "
    "Version/16.0 Mobile/15E148 Safari/604.1"
)


ProgressCallback = Callable[[dict[str, Any]], None]


def _emit_progress(
    progress_callback: ProgressCallback | None,
    *,
    step: str,
    message: str,
    flow: str | None = None,
    status: str = "running",
    page: Page | None = None,
) -> None:
    if not progress_callback:
        return
    if step == "logging_in" and page is not None and "/member/login" not in page.url:
        return

    event: dict[str, Any] = {
        "step": step,
        "message": message,
        "status": status,
    }
    if flow:
        event["flow"] = flow
    if page:
        try:
            event["screenshot_bytes"] = page.screenshot(
                type="jpeg",
                quality=60,
                full_page=False,
            )
        except Exception as e:
            event["screenshot_error"] = str(e)

    try:
        progress_callback(event)
    except Exception as e:
        print(f"[webview:progress] emit failed: {e}")


# ══════════════════════════════════════════════
# VLM 헬퍼
# ══════════════════════════════════════════════

def _ask_vlm(screenshot_bytes: bytes, question: str) -> dict:
    """스크린샷 + 질문 → JSON 응답"""
    print(f"[webview:VLM] 질의 시작: '{question[:60]}...'")
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
    print(f"[webview:VLM] 응답: {text}")
    if "```" in text:
        m = re.search(r"```(?:json)?\s*([\s\S]+?)```", text)
        text = m.group(1).strip() if m else text
    return json.loads(text)


def _screenshot_and_ask(page: Page, question: str) -> dict:
    return _ask_vlm(page.screenshot(), question)


# ══════════════════════════════════════════════
# 로그인 상태 확인
# ══════════════════════════════════════════════

def _dom_is_logged_in(page: Page) -> bool | None:
    """localStorage 토큰 또는 로그인 링크 DOM으로 로그인 상태 판단. None = 판단 불가."""
    try:
        has_token = page.evaluate("""() => {
            const keys = ['accessToken', 'kuuid', '__token__', 'user_id', 'authToken'];
            return keys.some(k => !!localStorage.getItem(k));
        }""")
        if has_token:
            print("[webview:DOM] 로그인 상태: 토큰 확인됨")
            return True
        login_link_count = page.locator("a[href*='/member/login']").count()
        if login_link_count > 0:
            print("[webview:DOM] 로그인 상태: 로그인 링크 발견 → 미로그인")
            return False
        return None
    except Exception as e:
        print(f"[webview:DOM] 로그인 상태 확인 실패: {e}")
        return None


def _vlm_is_logged_in(page: Page) -> bool:
    """VLM 스크린샷으로 로그인 상태 판단."""
    print("[webview:VLM] 로그인 상태 확인 중...")
    result = _screenshot_and_ask(
        page,
        '화면 상단에 로그인/회원가입 버튼이 보이면 {"logged_in": false}, '
        '마이페이지·프로필·장바구니 아이콘이 보이면 {"logged_in": true}',
    )
    logged = result.get("logged_in", False)
    print(f"[webview:VLM] 로그인 상태: {'로그인 됨' if logged else '미로그인'}")
    return logged


def _is_logged_in(page: Page) -> bool:
    result = _dom_is_logged_in(page)
    return result if result is not None else _vlm_is_logged_in(page)


# ══════════════════════════════════════════════
# 로그인
# ══════════════════════════════════════════════

def _dom_click_kurly_id_login(page: Page) -> bool:
    """'컬리아이디로 로그인' 버튼 DOM 클릭. 이미 이메일 입력 폼이면 True 반환."""
    # 이미 이메일 입력 폼이 보이면 클릭 불필요
    try:
        if page.locator("input[type='email'], input[name='id']").count() > 0:
            return True
    except Exception:
        pass

    selectors = [
        "text=컬리아이디로 로그인",
        "text=이메일로 로그인",
        "a:has-text('컬리아이디')",
        "button:has-text('컬리아이디')",
    ]
    for sel in selectors:
        try:
            loc = page.locator(sel).first
            if loc.count() > 0:
                loc.click(timeout=2000)
                page.wait_for_timeout(1500)
                print(f"[webview:DOM] 컬리아이디 로그인 버튼 클릭: {sel}")
                return True
        except Exception:
            continue
    return False


def _vlm_click_kurly_id_login(page: Page) -> bool:
    """VLM으로 '컬리아이디로 로그인' 버튼 탐색 후 클릭."""
    print("[webview:VLM] '컬리아이디로 로그인' 버튼 탐색 중...")
    result = _screenshot_and_ask(
        page,
        '화면에서 "컬리아이디로 로그인" 또는 "이메일로 로그인" 텍스트/버튼의 중앙 좌표를 찾아줘. '
        '{"x": 195, "y": 700, "found": true} 또는 {"x":0,"y":0,"found":false}',
    )
    if result.get("found"):
        page.mouse.click(result["x"], result["y"])
        page.wait_for_timeout(1500)
        print(f"[webview:VLM] 클릭 완료 ({result['x']}, {result['y']})")
        return True
    # 마지막 수단: 텍스트 기반 locator
    try:
        page.locator("text=/.*컬리.*로그인.*/").first.click(timeout=2000)
        page.wait_for_timeout(1500)
        return True
    except Exception:
        return False


def _dom_click_login_submit(page: Page) -> bool:
    """로그인 제출 버튼 DOM 클릭."""
    selectors = [
        "button[type='submit']",
        "button:has-text('로그인')",
        "input[type='submit']",
    ]
    for sel in selectors:
        try:
            loc = page.locator(sel).last
            if loc.count() > 0:
                loc.click(timeout=2000)
                print(f"[webview:DOM] 로그인 제출 버튼 클릭: {sel}")
                return True
        except Exception:
            continue
    try:
        page.keyboard.press("Enter")
        print("[webview:DOM] 로그인 Enter 키 입력")
        return True
    except Exception:
        return False


def _vlm_click_login_submit(page: Page) -> bool:
    """VLM으로 로그인 제출 버튼 탐색 후 클릭."""
    print("[webview:VLM] 로그인 버튼 탐색 중...")
    result = _screenshot_and_ask(
        page,
        '로그인 제출 버튼의 중앙 좌표. '
        '{"x": 195, "y": 500, "found": true} 또는 {"x":0,"y":0,"found":false}',
    )
    if result.get("found"):
        page.mouse.click(result["x"], result["y"])
        print(f"[webview:VLM] 로그인 버튼 클릭 ({result['x']}, {result['y']})")
        return True
    page.keyboard.press("Enter")
    return True


def _login(
    page: Page,
    progress_callback: ProgressCallback | None = None,
    flow: str | None = None,
) -> bool:
    """컬리 로그인 수행. 성공 여부 반환."""
    print("[webview] 로그인 페이지 진입 중...")
    page.goto(f"{KURLY_BASE_URL}/member/login")
    page.wait_for_load_state("domcontentloaded")
    page.wait_for_timeout(2000)
    _emit_progress(
        progress_callback,
        flow=flow,
        step="logging_in",
        message="로그인하고 있어요.",
        page=page,
    )

    # SNS 선택 화면 → 컬리아이디 로그인으로 전환
    if not _dom_click_kurly_id_login(page):
        _vlm_click_kurly_id_login(page)

    # 이메일 / 비밀번호 입력
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

    # 로그인 제출
    if not _dom_click_login_submit(page):
        _vlm_click_login_submit(page)

    print("[webview] 로그인 처리 대기 중...")
    page.wait_for_timeout(3000)
    logged = _is_logged_in(page)
    print(f"[webview] 로그인 {'성공' if logged else '실패'} — URL: {page.url}")
    return logged


# ══════════════════════════════════════════════
# 상품 검색 (VLM 불필요)
# ══════════════════════════════════════════════

def _search_product(page: Page, query: str) -> bool:
    """컬리 검색 URL로 직접 이동."""
    print(f"[webview] 상품 검색 시작: '{query}'")
    page.goto(f"{KURLY_BASE_URL}/search?sword={query}")
    page.wait_for_load_state("domcontentloaded")
    page.wait_for_timeout(2500)
    print("[webview] 검색 결과 페이지 로드 완료")
    return True


# ══════════════════════════════════════════════
# 검색 결과에서 상품 선택 (VLM 필수)
# ══════════════════════════════════════════════

def _select_product_from_results(page: Page, product_name: str) -> bool:
    """
    검색 결과에서 product_name과 가장 유사한 상품을 VLM으로 찾아 클릭.
    검색 결과는 매번 달라지므로 DOM 대체 불가 — VLM 유지.
    """
    print(f"[webview] 검색 결과에서 상품 탐색 (VLM): {product_name}")
    page.evaluate("window.scrollTo(0, 0); document.body.style.overflow = 'hidden';")
    page.wait_for_timeout(2000)

    result = _screenshot_and_ask(
        page,
        f'검색 결과 목록에서 목표 상품명: "{product_name}" 을 찾아줘.\n'
        '다음 순서대로 분석해:\n'
        '1. 화면에 보이는 상품들의 이름(텍스트)들을 전부 읽어본다.\n'
        '2. 목표 상품명과 가장 똑같은 정답 상품을 찾는다. (브랜드명이나 수식어가 약간 달라도 핵심 상품명이 일치하는 가장 첫 번째 상품)\n'
        '3. 찾은 정답 상품의 글씨가 아니라, **해당 상품명 글씨 바로 위에 있는 상품 썸네일 사진(이미지)**의 정중앙 좌표를 계산한다.\n'
        '{"reasoning": "...", "x": 195, "y": 300, "found": true, "matched_name": "..."} 또는 {"reasoning": "...", "x":0,"y":0,"found":false,"matched_name":""}',
    )
    print(f"[webview] 상품 선택 결과: {result}")

    if not result.get("found"):
        print(f"[webview] '{product_name}'을(를) 찾지 못했습니다.")
        return False

    page.mouse.click(result["x"], result["y"])
    page.wait_for_load_state("domcontentloaded")
    page.wait_for_timeout(2500)
    print("[webview] 상품 상세 페이지 로드 완료")
    return True


# ══════════════════════════════════════════════
# 구매하기 버튼 클릭
# ══════════════════════════════════════════════

def _click_purchase_button(page: Page) -> bool:
    """상품 상세 페이지에서 구매하기/담기 버튼 클릭."""
    print("[webview] 구매하기 버튼 탐색...")

    # DOM 우선: 텍스트 기반 locator
    try:
        page.locator("text=구매하기").last.click(timeout=3000)
        page.wait_for_timeout(2500)
        print("[webview:DOM] 구매하기 버튼 클릭 성공")
        return True
    except Exception:
        print("[webview:DOM] 실패 → VLM 폴백")

    # VLM 폴백
    result = _screenshot_and_ask(
        page,
        '화면에서 "구매하기", "바로구매", "장바구니 담기" 버튼 중 하나의 중앙 좌표. '
        '{"x": 195, "y": 760, "found": true, "button_text": "구매하기"} 또는 {"x":0,"y":0,"found":false,"button_text":""}',
    )
    if not result.get("found"):
        print("[webview:VLM] 구매하기 버튼을 찾지 못했습니다.")
        return False

    page.mouse.click(result["x"], result["y"])
    page.wait_for_timeout(2500)
    print(f"[webview:VLM] 구매하기 버튼 클릭 ({result['x']}, {result['y']})")
    return True


# ══════════════════════════════════════════════
# 팝업 닫기
# ══════════════════════════════════════════════

def _dom_close_popup(page: Page) -> bool:
    """aria-label·텍스트 기반으로 팝업 닫기 버튼 클릭."""
    selectors = [
        "button[aria-label='닫기']",
        "button[aria-label='close']",
        "button[aria-label='Close']",
        "button:has-text('×')",
        "button:has-text('✕')",
        "button:has-text('닫기')",
    ]
    for sel in selectors:
        try:
            loc = page.locator(sel).first
            if loc.count() > 0:
                loc.click(timeout=1000)
                page.wait_for_timeout(300)
                print(f"[webview:DOM] 팝업 닫기 버튼 클릭: {sel}")
                return True
        except Exception:
            continue
    return False


def _vlm_close_popup(page: Page) -> bool:
    """VLM으로 팝업 닫기(X) 버튼 탐색 후 클릭."""
    print("[webview:VLM] 팝업 닫기 버튼 탐색 중...")
    close = _ask_vlm(
        page.screenshot(),
        '팝업 닫기(X) 버튼이 보이면 좌표. {"x":350,"y":200,"found":true} 또는 {"x":0,"y":0,"found":false}',
    )
    if close.get("found"):
        page.mouse.click(close["x"], close["y"])
        page.wait_for_timeout(300)
        print(f"[webview:VLM] 팝업 닫기 클릭 ({close['x']}, {close['y']})")
        return True
    return False


def _close_popup(page: Page) -> None:
    if not _dom_close_popup(page):
        _vlm_close_popup(page)


# ══════════════════════════════════════════════
# 장바구니 담기 확인 팝업
# ══════════════════════════════════════════════

def _dom_click_quantity_plus(page: Page, times: int) -> bool:
    """
    + 버튼 위치를 JS getBoundingClientRect()로 구한 뒤 page.tap()으로 터치 이벤트 발생.
    Kurly 모바일은 touchstart/touchend 기반이므로 JS btn.click()만으로는 반응 안 함.
    has_touch=True 컨텍스트 + page.tap()이 실제 터치를 시뮬레이션.
    """
    for i in range(times):
        coords = page.evaluate("""() => {
            const vh = window.innerHeight;
            const allBtns = Array.from(document.querySelectorAll('button'));

            // 위치 기반: 팝업 영역(y > vh*0.5), 오른쪽(x > 200), 작은 정사각형, 가장 오른쪽 = +
            const candidates = allBtns
                .map(btn => ({ btn, r: btn.getBoundingClientRect() }))
                .filter(({r}) =>
                    r.width > 0 && r.height > 0 &&
                    r.top > vh * 0.5 && r.top < vh &&
                    r.left > 200 &&
                    r.width < 80 &&
                    Math.abs(r.width - r.height) < 20
                )
                .sort((a, b) => b.r.left - a.r.left);

            if (candidates.length > 0) {
                const r = candidates[0].r;
                return { x: r.left + r.width / 2, y: r.top + r.height / 2, found: true };
            }

            // aria-label 보조
            for (const btn of allBtns) {
                const label = btn.getAttribute('aria-label') || '';
                if (label.includes('올리기') || label.includes('증가') || label.includes('더하기')) {
                    const r = btn.getBoundingClientRect();
                    return { x: r.left + r.width / 2, y: r.top + r.height / 2, found: true };
                }
            }
            return { found: false };
        }""")
        if not coords or not coords.get("found"):
            print(f"[webview:DOM] + 버튼 찾기 실패 (시도 {i+1}/{times})")
            return False
        page.touchscreen.tap(coords["x"], coords["y"])
        page.wait_for_timeout(400)
        print(f"[webview:DOM] + 버튼 tap ({coords['x']:.0f}, {coords['y']:.0f}) → 수량 {i+2}개")
    print(f"[webview:DOM] 수량 {times + 1}개 설정 완료 (tap)")
    return True


def _confirm_cart(page: Page, quantity: int = 1) -> bool:
    """구매하기 클릭 후 나타나는 팝업에서 수량 설정."""
    print("[webview] 장바구니 담기 팝업 처리 중...")

    if quantity > 1:
        print(f"[webview] 수량 {quantity}개 설정 시도 중...")
        page.wait_for_timeout(1200)  # 팝업 애니메이션 완료 대기

        plus_result = _screenshot_and_ask(
            page,
            '장바구니 팝업에 나타난 수량 조절 영역을 확인해줘.\n'
            '현재 수량을 나타내는 숫자(보통 1)를 먼저 찾고, 그 숫자의 **바로 오른쪽**에 있는 **증가(+) 아이콘**의 정중앙 좌표를 계산해.\n'
            '(주의: reasoning 내용 안에 큰따옴표(")는 절대 쓰지 마세요)\n'
            '{"reasoning": "...", "x": 300, "y": 600, "found": true} 또는 {"reasoning": "...", "x":0,"y":0,"found":false}',
        )
        if plus_result.get("found"):
            px, py = plus_result["x"], plus_result["y"]
            for i in range(quantity - 1):
                page.touchscreen.tap(px, py)
                page.wait_for_timeout(700)
                print(f"[webview:VLM] + 버튼 tap ({px}, {py}) → 수량 {i + 2}개")
            print(f"[webview:VLM] 수량 {quantity}개 설정 완료")
        else:
            print("[webview] + 버튼 미발견 → 기본 수량(1개)으로 진행")

    page.wait_for_timeout(500)
    print("[webview] 장바구니 수량 설정 완료")


def _read_cart_popup_price(page: Page) -> int | None:
    """
    담기 버튼 텍스트 "N,NNN원 장바구니 담기"에서 실제 결제 가격 추출.
    product 페이지 meta 태그보다 정확 (할인가·수량 반영됨).
    """
    try:
        price_text = page.evaluate("""() => {
            const btns = Array.from(document.querySelectorAll('button'));
            const btn = btns.find(b => {
                const t = b.textContent;
                return t.includes('담기') && t.includes('원');
            });
            return btn ? btn.textContent : null;
        }""")
        if price_text:
            m = re.search(r"([\d,]+)원", price_text)
            if m:
                price = int(m.group(1).replace(",", ""))
                print(f"[webview:DOM] 팝업 실제 가격: {price:,}원")
                return price
    except Exception as e:
        print(f"[webview:DOM] 팝업 가격 추출 실패: {e}")
    return None


def _click_cart_add_button(page: Page) -> bool:
    """수량 확인 후 담기 버튼 tap (터치 이벤트). 뷰포트 안 요소만 선택."""
    coords = page.evaluate("""() => {
        const vh = window.innerHeight;
        const btns = Array.from(document.querySelectorAll('button'));
        const btn = btns.find(b => {
            const t = b.textContent;
            if (!t.includes('담기')) return false;
            const r = b.getBoundingClientRect();
            return r.width > 0 && r.height > 0 && r.top > 0 && r.top < vh;
        });
        if (btn) {
            const r = btn.getBoundingClientRect();
            return { x: r.left + r.width / 2, y: r.top + r.height / 2, found: true };
        }
        return { found: false };
    }""")
    if coords and coords.get("found"):
        page.touchscreen.tap(coords["x"], coords["y"])
        page.wait_for_timeout(2000)
        print(f"[webview:DOM] 담기 버튼 tap ({coords['x']:.0f}, {coords['y']:.0f}) 성공")
    else:
        print("[webview:DOM] 담기 버튼 미발견 → VLM 폴백")
        result = _ask_vlm(
            page.screenshot(),
            '"장바구니 담기", "담기", "확인" 등 최종 확인 버튼이 보이면 좌표 반환. '
            '{"x": 195, "y": 750, "found": true, "button_text": "..."} 또는 {"x":0,"y":0,"found":false,"button_text":""}',
        )
        if result.get("found"):
            page.touchscreen.tap(result["x"], result["y"])
            page.wait_for_timeout(2000)
            print(f"[webview:VLM] 담기 버튼 tap ({result['x']}, {result['y']})")

    # 담기 버튼 tap 후 팝업은 자동으로 닫힘 — 별도 close 불필요
    print("[webview] 장바구니 팝업 처리 완료")
    return True


# ══════════════════════════════════════════════
# 현재 가격 추출
# ══════════════════════════════════════════════

def _dom_extract_current_price(page: Page) -> int | None:
    """DOM/meta 태그로 현재 가격 추출. 할인가 우선."""
    try:
        # 1. og:price:amount meta 태그 (가장 안정적)
        # page.get_attribute()는 locator라 요소 없으면 30초 대기 → evaluate로 대체
        price_str = page.evaluate("""() => {
            const m = document.querySelector('meta[property="og:price:amount"]');
            return m ? m.content : null;
        }""")
        if price_str:
            cleaned = re.sub(r"[^\d]", "", price_str)
            if cleaned:
                print(f"[webview:DOM] og:price:amount → {int(cleaned):,}원")
                return int(cleaned)

        # 2. JSON-LD structured data
        ld_price = page.evaluate("""() => {
            for (const s of document.querySelectorAll('script[type="application/ld+json"]')) {
                try {
                    const d = JSON.parse(s.textContent);
                    if (d.offers?.price) return String(d.offers.price);
                    if (d.price)         return String(d.price);
                } catch(e) {}
            }
            return null;
        }""")
        if ld_price:
            cleaned = re.sub(r"[^\d]", "", ld_price)
            if cleaned:
                print(f"[webview:DOM] JSON-LD → {int(cleaned):,}원")
                return int(cleaned)

        # 3. 할인가 DOM 탐색 (sale/discount class 패턴)
        dom_price = page.evaluate("""() => {
            const sels = [
                '[class*="sale"][class*="price"]',
                '[class*="discount"][class*="price"]',
                '[class*="Price"] [class*="sale"]',
                '[data-testid*="sale-price"]',
                '[data-testid*="price"]',
            ];
            for (const sel of sels) {
                const el = document.querySelector(sel);
                if (el) {
                    const t = el.textContent.replace(/[^\\d]/g, '');
                    if (t && parseInt(t) > 0) return t;
                }
            }
            return null;
        }""")
        if dom_price:
            print(f"[webview:DOM] DOM class → {int(dom_price):,}원")
            return int(dom_price)

        return None
    except Exception as e:
        print(f"[webview:DOM] 가격 추출 실패: {e}")
        return None


def _vlm_extract_current_price(page: Page) -> int | None:
    """VLM 스크린샷으로 현재 가격 추출."""
    print("[webview:VLM] 현재 가격 추출 중...")
    result = _screenshot_and_ask(
        page,
        '이 상품 상세 페이지에서 현재 판매 가격을 찾아줘. 할인가가 있으면 할인가 우선. '
        '숫자만 반환하고 쉼표·"원" 문자는 제거해. '
        '{"price": 15900, "found": true} 또는 {"price": 0, "found": false}',
    )
    if result.get("found") and result.get("price"):
        price = int(result["price"])
        print(f"[webview:VLM] 현재 가격: {price:,}원")
        return price
    print("[webview:VLM] 가격을 찾지 못했습니다.")
    return None


def _extract_current_price(page: Page) -> int | None:
    result = _dom_extract_current_price(page)
    return result if result is not None else _vlm_extract_current_price(page)


# ══════════════════════════════════════════════
# 배송 정보 추출
# ══════════════════════════════════════════════

def _dom_extract_delivery_info(page: Page) -> str | None:
    """DOM 텍스트에서 배송 키워드 탐색으로 배송 정보 추출."""
    try:
        result = page.evaluate("""() => {
            const keywords = ['샛별배송', '로켓배송', '당일배송', '새벽배송', '익일배송', '무료배송', '일반배송'];
            const body = document.body.innerText;
            for (const kw of keywords) {
                const idx = body.indexOf(kw);
                if (idx !== -1) {
                    return body.substring(Math.max(0, idx), Math.min(body.length, idx + 40)).trim();
                }
            }
            return null;
        }""")
        if result:
            print(f"[webview:DOM] 배송 정보: {result}")
            return result.strip()
        return None
    except Exception as e:
        print(f"[webview:DOM] 배송 정보 추출 실패: {e}")
        return None


def _vlm_extract_delivery_info(page: Page) -> str:
    """VLM 스크린샷으로 배송 정보 추출."""
    print("[webview:VLM] 배송 정보 추출 중...")
    result = _screenshot_and_ask(
        page,
        '이 페이지에서 배송 방식과 예상 도착 시간을 찾아줘. '
        '{"delivery_type": "샛별배송", "delivery_estimate": "내일 오전 7시 전", "found": true} '
        '또는 {"delivery_type":"","delivery_estimate":"","found":false}',
    )
    if result.get("found"):
        parts = [result.get("delivery_type", ""), result.get("delivery_estimate", "")]
        info = " ".join(p for p in parts if p)
        print(f"[webview:VLM] 배송 정보: {info}")
        return info
    print("[webview:VLM] 배송 정보를 찾지 못했습니다.")
    return ""


def _extract_delivery_info(page: Page) -> str:
    result = _dom_extract_delivery_info(page)
    return result if result else _vlm_extract_delivery_info(page)


# ══════════════════════════════════════════════
# 가격 확인 (장바구니 담기 없이)
# ══════════════════════════════════════════════

def check_product_price(
    product_url: str,
    storage_state_path: str | None = None,
) -> dict:
    """
    상품 URL로 진입해 현재 가격만 확인하고 종료. 장바구니는 건드리지 않는다.

    Returns: {"current_price": int | None, "error": str | None}
    """
    if not storage_state_path:
        storage_state_path = "kurly_session.json"

    playwright = sync_playwright().start()
    # Railway 같은 서버 환경에는 화면이 없으므로 기본값은 headless 실행이다.
    browser = playwright.webkit.launch(headless=WEBVIEW_HEADLESS)

    context_kwargs = {
        "viewport": VIEWPORT,
        "user_agent": USER_AGENT,
        "locale": "ko-KR",
        "has_touch": True,
    }
    if storage_state_path and os.path.exists(storage_state_path):
        context_kwargs["storage_state"] = storage_state_path

    context = browser.new_context(**context_kwargs)
    page = context.new_page()
    page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined});")
    stealth_sync(page)

    try:
        print(f"[webview:price_check] 상품 페이지 진입: {product_url}")
        page.goto(product_url, timeout=10000)
        page.wait_for_load_state("domcontentloaded")
        page.wait_for_timeout(2000)

        current_price = _extract_current_price(page)
        return {"current_price": current_price, "error": None}
    except Exception as e:
        print(f"[webview:price_check] 오류: {e}")
        return {"current_price": None, "error": str(e)}
    finally:
        browser.close()
        playwright.stop()


# ══════════════════════════════════════════════
# 메인 진입점
# ══════════════════════════════════════════════

def run_kurly_purchase(
    product_name: str,
    keywords: list[str] | None = None,
    quantity: int = 1,
    storage_state_path: str | None = None,
    reorder_url: str | None = None,
    history_price: int | None = None,
    progress_callback: ProgressCallback | None = None,
    progress_flow: str | None = None,
) -> dict:
    """
    컬리 모바일웹에서 장바구니 담기.

    Parameters
    ----------
    product_name       : 선택된 상품명 (검색 + VLM 매칭에 사용)
    keywords           : 검색 키워드 (없으면 product_name 사용)
    quantity           : 장바구니에 담을 수량
    storage_state_path : 이전 세션 파일 경로 (로그인 상태 유지용)
    reorder_url        : 재구매 시 바로 진입할 상품 URL.
                         제공되면 검색/VLM 단계를 건너뜀.
                         로그인 리다이렉트 등 실패 시 검색 방식으로 자동 fallback.
    history_price      : 이전 구매가. 제공 시 팝업 실제가와 비교해 변동 감지.
                         None이면 가격 체크 스킵 (사용자가 이미 확인한 경우).

    Returns
    -------
    dict: {"cart_added": bool, "storage_state_path": str|None, "delivery_info": str,
           "product_url": str|None, "error": str|None}
          가격 변동 시: {"cart_added": False, "price_changed": True,
                        "current_price": int, "history_price": int, ...}
          취소 시: {"cart_added": False, "cancelled": True, ...}
    """
    if not storage_state_path:
        storage_state_path = "kurly_session.json"

    _clear_cancel()
    playwright = sync_playwright().start()
    print("[webview] 브라우저(Webkit) 시작...")
    # Railway 같은 서버 환경에는 화면이 없으므로 기본값은 headless 실행이다.
    browser = playwright.webkit.launch(headless=WEBVIEW_HEADLESS)

    context_kwargs = {
        "viewport": VIEWPORT,
        "user_agent": USER_AGENT,
        "locale": "ko-KR",
        "has_touch": True,  # 모바일 터치 이벤트 활성화 (page.tap() 필수)
    }
    if storage_state_path and os.path.exists(storage_state_path):
        context_kwargs["storage_state"] = storage_state_path
        print(f"[webview] 세션 복원: {storage_state_path}")

    context = browser.new_context(**context_kwargs)
    page = context.new_page()
    page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined});")
    stealth_sync(page)
    flow = progress_flow or ("reorder" if reorder_url else "new_purchase")

    try:
        # ── 재구매: URL로 바로 진입 (검색/VLM 단계 스킵) ──
        if reorder_url:
            _check_cancel()
            try:
                print(f"[webview] 재구매 직접 진입: {reorder_url}")
                _emit_progress(
                    progress_callback,
                    flow=flow,
                    step="opening_product",
                    message="이전 상품 페이지 열고 있어요.",
                )
                page.goto(reorder_url, timeout=10000)
                page.wait_for_load_state("domcontentloaded")
                page.wait_for_timeout(2000)

                current = page.url
                if ("login" in current or "member" in current
                        or "404" in current or "not-found" in current
                        or current.rstrip("/") == KURLY_BASE_URL.rstrip("/")):
                    raise ValueError(f"비정상 페이지 감지: {current}")

                product_url = current
                _emit_progress(
                    progress_callback,
                    flow=flow,
                    step="opening_product",
                    message="이전 상품 페이지 열고 있어요.",
                    page=page,
                )
                print(f"[webview] 상품 URL 확인: {product_url}")

            except Exception as e:
                print(f"[webview] URL 직접 진입 실패 ({e}) → 검색 방식으로 fallback")
                _emit_progress(
                    progress_callback,
                    flow=flow,
                    step="fallback_searching",
                    message="상품이 바뀌어서 다시 찾고 있어요.",
                    page=page,
                )
                reorder_url = None

        # ── 일반 구매 (또는 reorder fallback) ──
        if not reorder_url:
            _check_cancel()
            print("[webview] 컬리 접속 중...")
            _emit_progress(
                progress_callback,
                flow=flow,
                step="opening_shop",
                message="컬리에 접속하고 있어요.",
            )
            page.goto(KURLY_BASE_URL)
            page.wait_for_load_state("domcontentloaded")
            page.wait_for_timeout(2000)
            _emit_progress(
                progress_callback,
                flow=flow,
                step="opening_shop",
                message="컬리에 접속하고 있어요.",
                page=page,
            )

            _check_cancel()
            if not _is_logged_in(page):
                print("[webview] 로그인 플로우 시작...")
                _emit_progress(
                    progress_callback,
                    flow=flow,
                    step="logging_in",
                    message="로그인하고 있어요.",
                    page=page,
                )
                if not _login(page, progress_callback=progress_callback, flow=flow):
                    return {"cart_added": False, "storage_state_path": None,
                            "delivery_info": "", "product_url": None, "error": "login_failed"}

            _check_cancel()
            print(f"[webview] Step 2. 상품 검색: {product_name}")
            _search_product(page, product_name)
            _emit_progress(
                progress_callback,
                flow=flow,
                step="searching_product",
                message="상품을 찾고 있어요.",
                page=page,
            )

            _check_cancel()
            print(f"[webview] Step 3. 검색 결과에서 상품 선택: {product_name}")
            if not _select_product_from_results(page, product_name):
                return {"cart_added": False, "storage_state_path": None,
                        "delivery_info": "", "product_url": None, "error": "product_not_found_in_search"}

            product_url = page.url
            _emit_progress(
                progress_callback,
                flow=flow,
                step="searching_product",
                message="상품을 찾고 있어요.",
                page=page,
            )
            print(f"[webview] 상품 URL: {product_url}")

        # ── Step 4. 배송 정보 추출 ──
        _check_cancel()
        print("[webview] Step 4. 배송 정보 확인")
        delivery_info = _extract_delivery_info(page)

        # ── Step 5. 구매하기 클릭 → 팝업 오픈 ──
        _check_cancel()
        print("[webview] Step 5. 구매하기 버튼 클릭")
        if not _click_purchase_button(page):
            return {"cart_added": False, "storage_state_path": None,
                    "delivery_info": delivery_info, "error": "purchase_button_not_found"}

        # ── Step 5b. 팝업 단가 읽기 + 가격 변동 확인 (수량 설정 전, quantity=1 상태) ──
        if history_price:
            page.wait_for_timeout(800)  # 팝업 애니메이션 완료 대기
            current_price = _read_cart_popup_price(page)  # quantity=1이므로 = 단가
            if current_price and history_price > 0:
                diff = abs(current_price - history_price)
                ratio = diff / history_price
                if diff >= 500 or ratio >= 0.1:
                    direction = "올랐어요" if current_price > history_price else "내렸어요"
                    print(f"[webview] 가격 변동 감지: {history_price:,}원 → {current_price:,}원 ({direction})")
                    _close_popup(page)
                    context.storage_state(path=storage_state_path)
                    return {
                        "cart_added": False,
                        "price_changed": True,
                        "current_price": current_price,
                        "history_price": history_price,
                        "storage_state_path": storage_state_path,
                        "delivery_info": delivery_info,
                        "product_url": product_url,
                        "error": None,
                    }

        # ── Step 6. 수량 설정 ──
        _check_cancel()
        print("[webview] Step 6. 장바구니 팝업 처리")
        _emit_progress(
            progress_callback,
            flow=flow,
            step="adding_to_cart",
            message="장바구니에 담고 있어요.",
            page=page,
        )
        _confirm_cart(page, quantity=quantity)

        # ── Step 6b. 담기 버튼 클릭 ──
        _click_cart_add_button(page)

        # ── Step 7. 세션 저장 ──
        print("[webview] Step 7. 세션 저장")
        context.storage_state(path=storage_state_path)
        print(f"[webview] 세션 저장 완료: {storage_state_path}")

        return {
            "cart_added": True,
            "storage_state_path": storage_state_path,
            "delivery_info": delivery_info,
            "product_url": product_url,
            "error": None,
        }

    except WebviewCancelledError:
        print("[webview] 사용자 취소 요청으로 종료")
        return {"cart_added": False, "cancelled": True, "storage_state_path": None,
                "delivery_info": "", "product_url": None, "error": "user_cancelled"}

    except Exception as e:
        print(f"[webview] 오류: {e}")
        return {"cart_added": False, "storage_state_path": None,
                "delivery_info": "", "error": str(e)}

    finally:
        browser.close()
        playwright.stop()
