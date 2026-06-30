"""
Reorder Node 평가 스크립트.

핵심 검증:
  1. resolution_type=resolved → product_confirming + product_confirm pending
  2. resolution_type=ambiguous → product_confirming + product_select pending (후보 목록 포함)
  3. resolution_type=no_match → stage=searching + error=reorder_no_match
  4. product_select pending + 사용자 선택 → 올바른 후보 선택

실행:
    cd backend
    python evaluations/run_reorder_eval.py
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
from langchain_core.messages import HumanMessage
from src.agents.reorder_node import reorder_node
from src.state.schema import get_default_shopping_state

DATASET_NAME = "reorder-eval"

_RAMEN_CANDIDATE = {
    "product_id": "p001",
    "purchase_history_id": "h001",
    "product_name": "농심 신라면 5개입",
    "price_at_purchase": 3200,
    "price": 3200,
    "platform": "kurly",
    "product_url": "https://www.kurly.com/goods/1000001",
    "brand": "농심",
    "category": "라면",
    "purchased_at": "2024-12-01",
}

_EGG_CANDIDATE = {
    "product_id": "p002",
    "purchase_history_id": "h002",
    "product_name": "풀무원 달걀 10구",
    "price_at_purchase": 4900,
    "price": 4900,
    "platform": "kurly",
    "product_url": "https://www.kurly.com/goods/1000002",
    "brand": "풀무원",
    "category": "달걀",
    "purchased_at": "2024-11-20",
}

_RAMEN_2_CANDIDATE = {
    "product_id": "p003",
    "purchase_history_id": "h003",
    "product_name": "오뚜기 진라면 5개입",
    "price_at_purchase": 2900,
    "price": 2900,
    "platform": "kurly",
    "product_url": "https://www.kurly.com/goods/1000003",
    "brand": "오뚜기",
    "category": "라면",
    "purchased_at": "2024-11-10",
}

_NO_URL_CANDIDATE = {
    "product_id": "p004",
    "purchase_history_id": "h004",
    "product_name": "CJ 두부 300g",
    "price_at_purchase": 2200,
    "price": 2200,
    "platform": "kurly",
    "product_url": "",  # URL 없음
    "brand": "CJ",
    "category": "두부",
    "purchased_at": "2024-11-05",
}


EXAMPLES = [
    # ── 1. resolved: 단일 후보, URL 유효 ──
    {
        "inputs": {
            "reorder_resolution": {
                "resolution_type": "resolved",
                "resolved": True,
                "needs_user_selection": False,
                "selected_candidate": _RAMEN_CANDIDATE,
                "candidates": [_RAMEN_CANDIDATE],
            },
            "search_results": [_RAMEN_CANDIDATE],
            "messages": [],
        },
        "outputs": {
            "expected_stage": "product_confirming",
            "expected_pending_type": "product_confirm",
            "expected_product_name": "농심 신라면 5개입",
        },
    },

    # ── 2. ambiguous: 라면 2종 → product_select pending ──
    {
        "inputs": {
            "reorder_resolution": {
                "resolution_type": "ambiguous",
                "resolved": False,
                "needs_user_selection": True,
                "selected_candidate": None,
                "candidates": [_RAMEN_CANDIDATE, _RAMEN_2_CANDIDATE],
                "question": "사신 적 있는 라면이 여러 개예요. 어떤 걸로 할까요? 1. 농심 신라면 5개입, 2. 오뚜기 진라면 5개입",
            },
            "search_results": [_RAMEN_CANDIDATE, _RAMEN_2_CANDIDATE],
            "messages": [],
        },
        "outputs": {
            "expected_stage": "product_confirming",
            "expected_pending_type": "product_select",
            "expected_candidate_count": 2,
        },
    },

    # ── 3. no_match → searching ──
    {
        "inputs": {
            "reorder_resolution": {
                "resolution_type": "no_match",
                "resolved": False,
                "needs_user_selection": False,
                "selected_candidate": None,
                "candidates": [],
            },
            "search_results": [],
            "messages": [],
        },
        "outputs": {
            "expected_stage": "searching",
            "expected_error": "reorder_no_match",
        },
    },

    # ── 4. resolved: URL 없는 후보 → product_confirming (URL fallback) ──
    {
        "inputs": {
            "reorder_resolution": {
                "resolution_type": "resolved",
                "resolved": True,
                "needs_user_selection": False,
                "selected_candidate": _NO_URL_CANDIDATE,
                "candidates": [_NO_URL_CANDIDATE],
            },
            "search_results": [_NO_URL_CANDIDATE],
            "messages": [],
        },
        "outputs": {
            "expected_stage": "product_confirming",
            "expected_pending_type": "product_confirm",
            "expected_product_name": "CJ 두부 300g",
        },
    },

    # ── 5. product_select pending + 숫자로 선택 ("2번") ──
    {
        "inputs": {
            "pending_action": {
                "type": "product_select",
                "message": "어떤 라면으로 할까요?",
                "payload": {"candidates": [_RAMEN_CANDIDATE, _RAMEN_2_CANDIDATE]},
            },
            "search_results": [_RAMEN_CANDIDATE, _RAMEN_2_CANDIDATE],
            "messages": [{"role": "user", "content": "2번으로 해줘"}],
            "keywords": ["라면"],
        },
        "outputs": {
            "expected_stage": "product_confirming",
            "expected_pending_type": "product_confirm",
            "expected_product_name": "오뚜기 진라면 5개입",
        },
    },

    # ── 6. product_select pending + 키워드로 선택 ("신라면으로") ──
    {
        "inputs": {
            "pending_action": {
                "type": "product_select",
                "message": "어떤 라면으로 할까요?",
                "payload": {"candidates": [_RAMEN_CANDIDATE, _RAMEN_2_CANDIDATE]},
            },
            "search_results": [_RAMEN_CANDIDATE, _RAMEN_2_CANDIDATE],
            "messages": [{"role": "user", "content": "신라면으로"}],
            "keywords": ["라면"],
        },
        "outputs": {
            "expected_stage": "product_confirming",
            "expected_pending_type": "product_confirm",
            "expected_product_name": "농심 신라면 5개입",
        },
    },

    # ── 7. search_results만 있는 경우 (reorder_resolution 없음) ──
    {
        "inputs": {
            "reorder_resolution": None,
            "search_results": [_EGG_CANDIDATE],
            "messages": [],
        },
        "outputs": {
            "expected_stage": "product_confirming",
            "expected_pending_type": "product_confirm",
            "expected_product_name": "풀무원 달걀 10구",
        },
    },

    # ── 8. search_results 없음, reorder_resolution 없음 → no_match ──
    {
        "inputs": {
            "reorder_resolution": None,
            "search_results": [],
            "messages": [],
        },
        "outputs": {
            "expected_stage": "searching",
            "expected_error": "reorder_no_match",
        },
    },
]


# ── 데이터셋 생성 ──────────────────────────────────────────────────
def create_dataset(client: Client) -> str:
    existing = [d for d in client.list_datasets() if d.name == DATASET_NAME]
    if existing:
        print(f"기존 데이터셋 사용: {DATASET_NAME}")
        return existing[0].id

    dataset = client.create_dataset(DATASET_NAME, description="reorder_node 구매이력 재주문 해석 평가")
    for ex in EXAMPLES:
        client.create_example(inputs=ex["inputs"], outputs=ex["outputs"], dataset_id=dataset.id)
    print(f"데이터셋 생성 완료: {DATASET_NAME} ({len(EXAMPLES)}개)")
    return dataset.id


# ── 평가 대상 함수 ──────────────────────────────────────────────────
def target(inputs: dict) -> dict:
    state = get_default_shopping_state(user_id="eval_user", session_id="eval_session")
    state["reorder_resolution"] = inputs.get("reorder_resolution")
    state["search_results"] = inputs.get("search_results", [])
    state["keywords"] = inputs.get("keywords", [])

    raw_messages = inputs.get("messages", [])
    lc_messages = [HumanMessage(content=m["content"]) for m in raw_messages if m.get("role") == "user"]
    state["messages"] = lc_messages

    if "pending_action" in inputs:
        state["pending_action"] = inputs["pending_action"]

    result = reorder_node(state)
    return {
        "stage": result.get("stage"),
        "pending_type": (result.get("pending_action") or {}).get("type"),
        "product_name": (result.get("selected_product") or {}).get("product_name"),
        "error": result.get("error"),
        "candidate_count": len((result.get("pending_action") or {}).get("payload", {}).get("candidates", [])),
    }


# ── Evaluators ──────────────────────────────────────────────────────
def eval_stage_match(run, example):
    expected = (example.outputs or {}).get("expected_stage")
    if not expected:
        return {"key": "stage_match", "score": 1.0}
    predicted = (run.outputs or {}).get("stage", "")
    return {
        "key": "stage_match",
        "score": 1.0 if predicted == expected else 0.0,
        "comment": f"expected={expected}, got={predicted}",
    }


def eval_pending_type_match(run, example):
    expected = (example.outputs or {}).get("expected_pending_type")
    if not expected:
        return {"key": "pending_type_match", "score": 1.0}
    predicted = (run.outputs or {}).get("pending_type", "")
    return {
        "key": "pending_type_match",
        "score": 1.0 if predicted == expected else 0.0,
        "comment": f"expected={expected}, got={predicted}",
    }


def eval_product_name_match(run, example):
    expected = (example.outputs or {}).get("expected_product_name")
    if not expected:
        return {"key": "product_name_match", "score": 1.0}
    predicted = (run.outputs or {}).get("product_name", "")
    return {
        "key": "product_name_match",
        "score": 1.0 if predicted == expected else 0.0,
        "comment": f"expected={expected}, got={predicted}",
    }


def eval_candidate_count(run, example):
    expected = (example.outputs or {}).get("expected_candidate_count")
    if expected is None:
        return {"key": "candidate_count", "score": 1.0}
    predicted = (run.outputs or {}).get("candidate_count", 0)
    return {
        "key": "candidate_count",
        "score": 1.0 if predicted == expected else 0.0,
        "comment": f"expected={expected}, got={predicted}",
    }


def eval_error_match(run, example):
    expected = (example.outputs or {}).get("expected_error")
    if not expected:
        return {"key": "error_match", "score": 1.0}
    predicted = (run.outputs or {}).get("error", "")
    return {
        "key": "error_match",
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

    print("=== Reorder Node 평가 시작 ===")
    results = evaluate(
        target,
        data=DATASET_NAME,
        evaluators=[
            eval_stage_match,
            eval_pending_type_match,
            eval_product_name_match,
            eval_candidate_count,
            eval_error_match,
        ],
        experiment_prefix="reorder",
        metadata={"version": "v1"},
    )
    print("\n=== 평가 완료 ===")
