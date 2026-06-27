"""
Router 평가 스크립트.

핵심 검증:
  - intent + stage + pending_action + confidence 조합 → 올바른 목적지 노드

라우터는 LLM 없이 순수 로직으로 동작하므로,
실행 결과가 결정론적 정답과 일치하는지 확인한다.

실행:
    cd backend
    python evaluations/run_router_eval.py
"""
import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "../../.env"))

_VENDOR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../vendor/ddalangoo-langgraph"))
if _VENDOR not in sys.path:
    sys.path.insert(0, _VENDOR)

os.environ['LANGCHAIN_ENDPOINT'] = 'https://apac.api.smith.langchain.com'

from langsmith import Client, evaluate
from src.graph.router import route
from src.state.schema import get_default_shopping_state

DATASET_NAME = "router-eval"

# ── 테스트 케이스 ──────────────────────────────────────────────────
EXAMPLES = [
    # ── 1. 명확성/신뢰도 검사 ──
    {
        "inputs": {
            "state_patch": {"intent": "buy", "stage": "idle", "confidence": 0.3},
        },
        "outputs": {"expected_route": "respond"},
    },
    {
        "inputs": {
            "state_patch": {"intent": "buy", "stage": "idle", "confidence": 0.9, "needs_clarification": True},
        },
        "outputs": {"expected_route": "respond"},
    },
    {
        "inputs": {
            "state_patch": {"intent": "unclear", "stage": "idle", "confidence": 0.7},
        },
        "outputs": {"expected_route": "respond"},
    },

    # ── 2. cancel은 어디서든 ──
    {
        "inputs": {
            "state_patch": {"intent": "cancel", "stage": "product_confirming", "confidence": 0.95},
        },
        "outputs": {"expected_route": "cancel"},
    },
    {
        "inputs": {
            "state_patch": {"intent": "cancel", "stage": "payment_processing", "confidence": 0.95},
        },
        "outputs": {"expected_route": "cancel"},
    },

    # ── 3. payment_processing → payment_agent ──
    {
        "inputs": {
            "state_patch": {"intent": "confirm", "stage": "payment_processing", "confidence": 0.95},
        },
        "outputs": {"expected_route": "payment_agent"},
    },
    {
        "inputs": {
            "state_patch": {"intent": "deny", "stage": "payment_processing", "confidence": 0.95},
        },
        "outputs": {"expected_route": "payment_agent"},
    },

    # ── 4. idle 기본 라우팅 ──
    {
        "inputs": {
            "state_patch": {"intent": "buy", "stage": "idle", "confidence": 0.9},
        },
        "outputs": {"expected_route": "memory_agent"},
    },
    {
        "inputs": {
            "state_patch": {"intent": "reorder", "stage": "idle", "confidence": 0.9},
        },
        "outputs": {"expected_route": "memory_agent"},
    },
    {
        "inputs": {
            "state_patch": {"intent": "compare_platforms", "stage": "idle", "confidence": 0.9},
        },
        "outputs": {"expected_route": "platform_agent"},
    },
    {
        "inputs": {
            "state_patch": {"intent": "deny", "stage": "idle", "confidence": 0.9},
        },
        "outputs": {"expected_route": "respond"},
    },

    # ── 5. product_confirming: confirm ──
    {
        "inputs": {
            # confirm + quantity 없음 → quantity_check
            "state_patch": {
                "intent": "confirm", "stage": "product_confirming", "confidence": 0.95,
                "quantity": None, "pending_action": {"type": "product_confirm"},
            },
        },
        "outputs": {"expected_route": "quantity_check"},
    },
    {
        "inputs": {
            # confirm + quantity 있음 → payment_agent
            "state_patch": {
                "intent": "confirm", "stage": "product_confirming", "confidence": 0.95,
                "quantity": 2, "pending_action": {"type": "product_confirm"},
            },
        },
        "outputs": {"expected_route": "payment_agent"},
    },

    # ── 6. product_confirming: deny/next/ask → product_agent ──
    {
        "inputs": {
            "state_patch": {
                "intent": "deny", "stage": "product_confirming", "confidence": 0.9,
                "pending_action": {"type": "product_confirm"},
            },
        },
        "outputs": {"expected_route": "product_agent"},
    },
    {
        "inputs": {
            "state_patch": {
                "intent": "next", "stage": "product_confirming", "confidence": 0.9,
                "pending_action": {"type": "product_confirm"},
            },
        },
        "outputs": {"expected_route": "product_agent"},
    },
    {
        "inputs": {
            "state_patch": {
                "intent": "ask", "stage": "product_confirming", "confidence": 0.9,
                "pending_action": {"type": "product_confirm"},
            },
        },
        "outputs": {"expected_route": "product_agent"},
    },

    # ── 7. product_confirming: refine/compare_platforms → platform_agent ──
    {
        "inputs": {
            "state_patch": {
                "intent": "refine", "stage": "product_confirming", "confidence": 0.9,
                "pending_action": {"type": "product_confirm"},
            },
        },
        "outputs": {"expected_route": "platform_agent"},
    },

    # ── 8. product_confirming: quantity_confirm pending ──
    {
        "inputs": {
            # quantity_confirm + quantity 있음 → payment_agent
            "state_patch": {
                "intent": "confirm", "stage": "product_confirming", "confidence": 0.95,
                "quantity": 3, "pending_action": {"type": "quantity_confirm"},
            },
        },
        "outputs": {"expected_route": "payment_agent"},
    },
    {
        "inputs": {
            # quantity_confirm + quantity 없음 → quantity_check
            "state_patch": {
                "intent": "confirm", "stage": "product_confirming", "confidence": 0.95,
                "quantity": None, "pending_action": {"type": "quantity_confirm"},
            },
        },
        "outputs": {"expected_route": "quantity_check"},
    },

    # ── 9. product_confirming: product_select pending (reorder 선택) ──
    {
        "inputs": {
            "state_patch": {
                "intent": "confirm", "stage": "product_confirming", "confidence": 0.9,
                "pending_action": {"type": "product_select"},
            },
        },
        "outputs": {"expected_route": "reorder_node"},
    },

    # ── 10. searching: refine → platform_agent ──
    {
        "inputs": {
            "state_patch": {
                "intent": "refine", "stage": "searching", "confidence": 0.9,
            },
        },
        "outputs": {"expected_route": "platform_agent"},
    },
    {
        "inputs": {
            # searching + buy → respond (buy는 platform_agent로 바로 못 감, 지금 이미 searching 중)
            "state_patch": {
                "intent": "buy", "stage": "searching", "confidence": 0.9,
            },
        },
        "outputs": {"expected_route": "respond"},
    },

    # ── 11. cart_shopping ──
    {
        "inputs": {
            "state_patch": {
                "intent": "buy", "stage": "cart_shopping", "confidence": 0.9,
                "keywords": ["오이"],
            },
        },
        "outputs": {"expected_route": "platform_agent"},
    },
    {
        "inputs": {
            "state_patch": {
                "intent": "reorder", "stage": "cart_shopping", "confidence": 0.9,
            },
        },
        "outputs": {"expected_route": "memory_agent"},
    },
    {
        "inputs": {
            # cart_shopping + confirm + no pending → payment_agent
            "state_patch": {
                "intent": "confirm", "stage": "cart_shopping", "confidence": 0.9,
                "pending_action": {"type": "product_confirm"},
            },
        },
        "outputs": {"expected_route": "payment_agent"},
    },
]


# ── 데이터셋 생성 ──────────────────────────────────────────────────
def create_dataset(client: Client) -> str:
    existing = [d for d in client.list_datasets() if d.name == DATASET_NAME]
    if existing:
        print(f"기존 데이터셋 사용: {DATASET_NAME}")
        return existing[0].id

    dataset = client.create_dataset(DATASET_NAME, description="router intent+stage → node 라우팅 정확도 평가")
    for ex in EXAMPLES:
        client.create_example(inputs=ex["inputs"], outputs=ex["outputs"], dataset_id=dataset.id)
    print(f"데이터셋 생성 완료: {DATASET_NAME} ({len(EXAMPLES)}개)")
    return dataset.id


# ── 평가 대상 함수 ──────────────────────────────────────────────────
def target(inputs: dict) -> dict:
    state = get_default_shopping_state(user_id="eval_user", session_id="eval_session")
    state.update(inputs.get("state_patch", {}))
    result = route(state)
    return {"route": result}


# ── Evaluator ───────────────────────────────────────────────────────
def eval_route_match(run, example):
    expected = (example.outputs or {}).get("expected_route", "")
    predicted = (run.outputs or {}).get("route", "")
    return {
        "key": "route_match",
        "score": 1.0 if predicted == expected else 0.0,
        "comment": f"expected={expected}, got={predicted}",
    }


# ── 실행 ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    client = Client(
        api_url="https://apac.api.smith.langchain.com",
        api_key=os.environ.get("LANGCHAIN_API_KEY"),
    )
    create_dataset(client)

    print("=== Router 평가 시작 ===")
    results = evaluate(
        target,
        data=DATASET_NAME,
        evaluators=[eval_route_match],
        experiment_prefix="router",
        metadata={"version": "v1"},
    )
    print("\n=== 평가 완료 ===")
