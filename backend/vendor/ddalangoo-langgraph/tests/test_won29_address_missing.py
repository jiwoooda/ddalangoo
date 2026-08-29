"""WON-29 — 배송지 없음 처리 결함 회귀 고정.

근본 원인(AGENT_IMPROVEMENT_PROTOCOL DIAGNOSE, WON-29 Unit 1):
  RC-1: response_agent가 "저장해 드릴게요"라고 약속만 하고 저장 코드가 없음.
  RC-2: 사용자가 새 주소를 말해도(address_change + address_text) 어디에도 저장 안 함.
  RC-3: payment/node.py의 배송지 가드가 Step 1-5(cart→address 전환)에만 있고
        Step 2(address_confirm)/Step 3(payment_method_confirm)/Step 4(payment_password)
        에는 없어서 무주소로도 결제 후반부까지 진행되고 빈 주소로 주문이 나감.

이 테스트는 FIX 전에는 실패해야 한다(TEST-first).
"""
import src.tools.mock_tools as mock_tools
from src.payment.node import payment_agent_node
from src.agents.nodes import respond_node
from src.tools import db_client
from src.state.schema import get_default_shopping_state

NO_ADDR_USER = "won29_noaddr"
NEW_ADDRESS_TEXT = "서울특별시 관악구 봉천로 100"
IDLE_ADDRESS_TEXT = "경기도 성남시 분당구 판교로 200"
# _short_address는 앞 3토큰만 남기므로(payment/node.py) 3번째 토큰으로 검증한다.
NEW_ADDRESS_MARKER = "봉천로"
IDLE_ADDRESS_MARKER = "분당구"


def _clean_user(user_id: str) -> None:
    mock_tools.MOCK_ADDRESSES.pop(str(user_id), None)
    mock_tools._mock_carts.pop(str(user_id), None)


def setup_function(_func) -> None:
    _clean_user(NO_ADDR_USER)


def teardown_function(_func) -> None:
    _clean_user(NO_ADDR_USER)


def make_state(**overrides) -> dict:
    state = get_default_shopping_state(NO_ADDR_USER, "session_won29")
    state.update(overrides)
    return state


def _seed_cart() -> None:
    mock_tools.mock_add_to_cart(
        NO_ADDR_USER,
        {"product_name": "두부", "price": 3000, "platform": "kurly", "product_url": "https://mock.kurly.com/tofu"},
        1,
        ["두부"],
    )


# ── RC-3: 무주소 상태가 결제 후반 단계에 도달하면 안 된다 ──────────────────

def test_no_address_blocked_at_address_confirm_step():
    """Step 2 (address_confirm 확인) — 주소 없으면 결제수단 단계로 못 넘어간다."""
    _seed_cart()
    state = make_state(
        stage="payment_processing",
        intent="confirm",
        selected_product={"product_name": "두부", "price": 3000},
        quantity=1,
        pending_action={"type": "address_confirm"},
    )

    result = payment_agent_node(state)

    assert result["error"] == "address_required"
    assert result["pending_action"]["type"] == "address_required"
    assert result["stage"] == "cart_shopping"


def test_no_address_blocked_at_payment_method_confirm_step():
    """Step 3 (payment_method_confirm) — 주소 없으면 비밀번호 단계로 못 넘어간다."""
    _seed_cart()
    state = make_state(
        stage="payment_processing",
        intent="confirm",
        selected_product={"product_name": "두부", "price": 3000},
        quantity=1,
        pending_action={"type": "payment_method_confirm"},
    )

    result = payment_agent_node(state)

    assert result["error"] == "address_required"
    assert result["pending_action"]["type"] == "address_required"
    assert result["stage"] == "cart_shopping"


def test_no_address_blocked_at_payment_password_step():
    """Step 4 (payment_password) — 마지막 방어선. 무주소로 주문이 나가면 안 된다."""
    _seed_cart()
    state = make_state(
        stage="payment_processing",
        intent="confirm",
        selected_product={"product_name": "두부", "price": 3000},
        quantity=1,
        pending_action={"type": "payment_password"},
        payment_idempotency_key="won29-key-1",
    )

    result = payment_agent_node(state)

    assert result["error"] == "address_required"
    assert result.get("stage") == "cart_shopping"
    assert "order_id" not in result
    assert result.get("pending_action", {}).get("type") != "payment_confirm"


# ── RC-2: 결제 흐름에서 새 주소 발화(address_change)를 저장한다 ─────────────

def test_address_change_in_payment_flow_saves_new_address():
    """address_confirm 대기 중 새 주소를 말하면 저장하고 그 주소로 재확인한다."""
    _seed_cart()
    state = make_state(
        stage="payment_processing",
        intent="address_change",
        address_text=NEW_ADDRESS_TEXT,
        selected_product={"product_name": "두부", "price": 3000},
        quantity=1,
        pending_action={"type": "address_confirm"},
    )

    result = payment_agent_node(state)

    saved = db_client.get_default_address(NO_ADDR_USER, mode="mock")
    assert saved is not None
    assert saved.get("address_line1") == NEW_ADDRESS_TEXT
    assert result["pending_action"]["type"] == "address_confirm"
    assert NEW_ADDRESS_MARKER in result["pending_action"]["message"]


# ── RC-1: idle에서 새 주소 발화(R3)를 저장한다 ────────────────────────────

def test_address_change_at_idle_saves_new_address():
    """respond_node — idle에서 새 배송지를 말하면 저장하고 저장 사실을 알린다."""
    state = make_state(
        stage="idle",
        intent="address_change",
        address_text=IDLE_ADDRESS_TEXT,
        pending_action={"type": "address_confirm"},
    )

    result = respond_node(state)

    saved = db_client.get_default_address(NO_ADDR_USER, mode="mock")
    assert saved is not None
    assert saved.get("address_line1") == IDLE_ADDRESS_TEXT
    msg = result["messages"][0]["content"]
    assert "저장" in msg
    assert IDLE_ADDRESS_MARKER in msg
    assert result["pending_action"] is None


def test_idle_saved_address_is_used_by_later_payment():
    """R3 end-to-end — idle 저장 → 이후 결제 진입 시 그 주소로 확인한다."""
    respond_node(
        make_state(
            stage="idle",
            intent="address_change",
            address_text=IDLE_ADDRESS_TEXT,
            pending_action={"type": "address_confirm"},
        )
    )
    _seed_cart()

    result = payment_agent_node(
        make_state(
            stage="cart_shopping",
            intent="confirm",
            selected_product={"product_name": "두부", "price": 3000},
            quantity=1,
            pending_action={"type": "cart_review"},
        )
    )

    assert result["pending_action"]["type"] == "address_confirm"
    assert result["error"] is None
    assert IDLE_ADDRESS_MARKER in result["pending_action"]["message"]
