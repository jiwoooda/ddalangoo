"""
전체 유스케이스 통합 테스트.

시나리오: 우삼겹 구매 → 컬리 제안 → 추천 → 수량 → 결제 4단계 → 완료

LLM: 실제 호출 (intent_agent=GPT-4o-mini, product_agent=Claude Sonnet)
MCP: meta_mcp_client.search_products mock (네트워크 불필요)
웹뷰: USE_REAL_BROWSER=false (결제는 fake)

실행:
    python tests/test_full_usecase.py
    pytest tests/test_full_usecase.py -s -v
"""
import os
import sys
from unittest.mock import patch
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.graph.builder import build_graph
from src.state.schema import get_default_shopping_state
from src.utils.agent_logger import agent_logger

# ── Mock 상품 데이터 (컬리 우삼겹) ──────────────────────────────
MOCK_KURLY_PRODUCTS = [
    {
        "product_name": "제주 흑돼지 우삼겹 500g",
        "price": 14900,
        "rating": 4.8,
        "review_count": 1203,
        "delivery": "샛별배송 내일 아침 7시 전",
        "delivery_fee": 0,
        "platform": "kurly",
        "image_url": "https://mock.kurly.com/woosamgyeop.jpg",
        "product_url": "https://mock.kurly.com/products/woosamgyeop-500g",
        "is_sold_out": False,
        "raw": {},
    },
    {
        "product_name": "한돈 우삼겹 300g",
        "price": 9900,
        "rating": 4.5,
        "review_count": 582,
        "delivery": "샛별배송 내일 아침 7시 전",
        "delivery_fee": 0,
        "platform": "kurly",
        "image_url": "https://mock.kurly.com/woosamgyeop2.jpg",
        "product_url": "https://mock.kurly.com/products/woosamgyeop-300g",
        "is_sold_out": False,
        "raw": {},
    },
    {
        "product_name": "목우촌 우삼겹 400g",
        "price": 12500,
        "rating": 4.3,
        "review_count": 320,
        "delivery": "샛별배송 내일 아침 7시 전",
        "delivery_fee": 0,
        "platform": "kurly",
        "image_url": "https://mock.kurly.com/woosamgyeop3.jpg",
        "product_url": "https://mock.kurly.com/products/woosamgyeop-400g",
        "is_sold_out": False,
        "raw": {},
    },
]


# ── 헬퍼 ────────────────────────────────────────────────────────

def get_last_assistant_msg(graph, config) -> str:
    state = graph.get_state(config)
    for msg in reversed(state.values.get("messages", [])):
        if isinstance(msg, dict) and msg.get("role") == "assistant":
            return msg["content"]
        if getattr(msg, "type", None) == "ai":
            return msg.content
    return ""


def send(graph, config, user_input: str) -> tuple[str, dict]:
    """사용자 메시지 주입 → 그래프 실행 → (어시스턴트 응답, state values) 반환."""
    agent_logger.new_turn(user_input)
    graph.update_state(config, {"messages": [{"role": "user", "content": user_input}]})
    graph.invoke(None, config)
    state = graph.get_state(config)
    response = get_last_assistant_msg(graph, config)
    return response, state.values


def print_turn(turn: int, human: str, assistant: str, stage: str, pending: str):
    print(f"\n{'─'*55}")
    print(f"[Turn {turn}]")
    print(f"  할머니  : {human}")
    print(f"  딸랑구  : {assistant}")
    print(f"  state   : stage={stage} | pending={pending}")


# ── 메인 테스트 ──────────────────────────────────────────────────

def test_full_usecase():
    agent_logger.start_session("test-woosamgyeop")

    with patch("src.agents.platform_agent.meta_search", return_value=MOCK_KURLY_PRODUCTS):

        graph = build_graph()
        config = {"configurable": {"thread_id": "test-woosamgyeop-001"}}

        # 초기 state → wait_for_input에서 첫 interrupt
        graph.invoke(get_default_shopping_state("user_test", "sess-test-001"), config)
        print("\n" + "="*55)
        print("  [테스트 시작] 우삼겹 구매 전체 유스케이스")
        if agent_logger.log_path:
            print(f"  LOG: {agent_logger.log_path}")
        print("="*55)

        # ── Turn 1: 구매 요청 → 컬리 제안 ──
        resp, vals = send(graph, config, "우삼겹 사려고")
        print_turn(1, "우삼겹 사려고", resp,
                   vals.get("stage","?"), (vals.get("pending_action") or {}).get("type","-"))
        assert "컬리" in resp, f"컬리 제안 메시지 기대, 실제: {resp}"

        # ── Turn 2: 컬리 제안 수락 → 상품 추천 ──
        resp, vals = send(graph, config, "응")
        print_turn(2, "응", resp,
                   vals.get("stage","?"), (vals.get("pending_action") or {}).get("type","-"))
        assert vals.get("selected_product") is not None, "selected_product가 설정돼야 함"
        assert any(kw in resp for kw in ["원", "살까", "주문", "어때"]), \
            f"상품 추천 응답 기대, 실제: {resp}"

        # ── Turn 3: 구매 확인 → 수량 질문 ──
        resp, vals = send(graph, config, "응 그걸로 사줘")
        print_turn(3, "응 그걸로 사줘", resp,
                   vals.get("stage","?"), (vals.get("pending_action") or {}).get("type","-"))
        assert any(kw in resp for kw in ["개", "수량", "몇"]), \
            f"수량 질문 응답 기대, 실제: {resp}"

        # ── Turn 4: 수량 입력 → 결제수단 확인 (Step 1) ──
        resp, vals = send(graph, config, "두 개")
        print_turn(4, "두 개", resp,
                   vals.get("stage","?"), (vals.get("pending_action") or {}).get("type","-"))
        assert vals.get("quantity") == 2, f"quantity=2 기대, 실제: {vals.get('quantity')}"
        assert any(kw in resp for kw in ["원", "결제", "페이"]), \
            f"결제수단 확인 응답 기대, 실제: {resp}"

        # ── Turn 5: 결제수단 확인 → 배송지 확인 (Step 2) ──
        resp, vals = send(graph, config, "응")
        print_turn(5, "응", resp,
                   vals.get("stage","?"), (vals.get("pending_action") or {}).get("type","-"))
        assert any(kw in resp for kw in ["배송지", "주소", "보낼"]), \
            f"배송지 확인 응답 기대, 실제: {resp}"

        # ── Turn 6: 배송지 확인 → 비밀번호 요청 (Step 3) ──
        resp, vals = send(graph, config, "응")
        print_turn(6, "응", resp,
                   vals.get("stage","?"), (vals.get("pending_action") or {}).get("type","-"))
        assert any(kw in resp for kw in ["비밀번호", "입력"]), \
            f"비밀번호 요청 응답 기대, 실제: {resp}"

        # ── Turn 7: 비밀번호 입력 → 결제 완료 (Step 4) ──
        resp, vals = send(graph, config, "완료")
        print_turn(7, "완료", resp,
                   vals.get("stage","?"), (vals.get("pending_action") or {}).get("type","-"))
        assert vals.get("stage") == "completed", \
            f"최종 stage=completed 기대, 실제: {vals.get('stage')}"
        assert any(kw in resp for kw in ["완료", "도착", "구매"]), \
            f"완료 응답 기대, 실제: {resp}"

        print("\n" + "="*55)
        print("  [OK] 전체 유스케이스 테스트 통과!")
        print("="*55)


if __name__ == "__main__":
    test_full_usecase()
