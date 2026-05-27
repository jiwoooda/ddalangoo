"""
Reorder Node.

역할: 구매 이력 스냅샷(memory_agent가 search_results에 채워줌) → URL 유효성 확인
- URL 유효: product_confirm pending_action 설정 → respond (사용자 확인 대기, URL로 직접 접속)
- URL 무효/비어있음 + 후보 존재: product_url="" 로 진행 → 웹뷰에서 상품명 검색 fallback
- 구매이력 없음(no_match): stage=searching → platform_agent fallback

LLM 호출 없음. 결정 로직만.
"""
from src.state.schema import ShoppingState
from src.tools.mock_tools import mock_validate_product_url


def _latest_user_text(state: ShoppingState) -> str:
    for msg in reversed(state.get("messages") or []):
        if isinstance(msg, dict):
            if msg.get("role") in ("user", "human"):
                return str(msg.get("content") or "")
        else:
            role = getattr(msg, "type", None) or getattr(msg, "role", None)
            if role in ("user", "human"):
                return str(getattr(msg, "content", "") or "")
    return ""


def _selection_terms(text: str, keywords: list[str]) -> list[str]:
    base = f"{text} {' '.join(keywords or [])}".lower().replace(" ", "")
    terms = [base] if base else []
    aliases = {
        "\ub538\uae30": ["strawberry"],
        "\uc2e0\uc120": ["fresh"],
        "\uc0dd\ub538\uae30": ["fresh", "strawberry"],
        "\uc2e0\uc120\ub538\uae30": ["fresh", "strawberry"],
        "\ub0c9\ub3d9": ["frozen"],
        "\ub0c9\ub3d9\ub538\uae30": ["frozen", "strawberry"],
        "\uc124\ud5a5": ["\uc124\ud5a5"],
    }
    for key, values in aliases.items():
        if key in base:
            terms.extend(values)
    for token in ("500g", "1kg", "fresh", "frozen", "strawberry"):
        if token in base:
            terms.append(token)
    seen = set()
    return [term for term in terms if term and not (term in seen or seen.add(term))]


def _candidate_text(candidate: dict) -> str:
    return " ".join(
        str(candidate.get(field) or "")
        for field in ("product_name", "option_text", "brand", "category", "keyword")
    ).lower().replace(" ", "")


def _select_candidate_from_pending(state: ShoppingState) -> dict | None:
    pending = state.get("pending_action") or {}
    candidates = (pending.get("payload") or {}).get("candidates") or []
    if not candidates:
        return None

    user_text = _latest_user_text(state)
    digits = [ch for ch in user_text if ch.isdigit()]
    if digits:
        index = int(digits[0]) - 1
        if 0 <= index < len(candidates):
            return candidates[index]

    terms = _selection_terms(user_text, state.get("keywords") or [])
    scored = []
    for candidate in candidates:
        text = _candidate_text(candidate)
        score = sum(1 for term in terms if term in text)
        scored.append((score, candidate))

    scored.sort(key=lambda item: item[0], reverse=True)
    if scored and scored[0][0] > 0:
        if len(scored) == 1 or scored[0][0] > scored[1][0]:
            return scored[0][1]
    return None


def _confirm_candidate(candidate: dict, price_key: str = "price_at_purchase") -> dict:
    raw_url = candidate.get("product_url", "")
    product_url = raw_url if mock_validate_product_url(raw_url) else ""
    price = candidate.get(price_key, candidate.get("price", 0))
    product_name = candidate.get("product_name", "상품")
    return {
        "selected_product": {
            "product_id": candidate.get("product_id"),
            "product_option_id": candidate.get("product_option_id"),
            "purchase_history_id": candidate.get("purchase_history_id"),
            "product_name": product_name,
            "brand": candidate.get("brand"),
            "category": candidate.get("category"),
            "price": price,
            "platform": candidate.get("platform", ""),
            "option_text": candidate.get("option_text"),
            "selected_options": candidate.get("selected_options") or {},
            "product_url": product_url,
        },
        "product_url": product_url,
        "pending_action": {
            "type": "product_confirm",
            "message": f"{product_name}, {price:,}원이에요. 다시 주문할까요?",
            "payload": {
                "purchase_history_id": candidate.get("purchase_history_id"),
                "product_url": product_url,
                "selected_options": candidate.get("selected_options") or {},
                "option_text": candidate.get("option_text"),
            },
        },
        "stage": "product_confirming",
        "error": None,
    }


def reorder_node(state: ShoppingState) -> dict:
    """
    Reorder Node.

    memory_agent → reorder_node → respond (확인) → payment_agent
                               └→ platform_agent (URL 실패 fallback)
    """
    pending = state.get("pending_action") or {}
    if pending.get("type") == "product_select":
        candidate = _select_candidate_from_pending(state)
        if candidate:
            return {
                **_confirm_candidate(candidate),
                "reorder_resolution": {
                    "resolution_type": "resolved",
                    "resolved": True,
                    "needs_user_selection": False,
                    "selected_candidate": candidate,
                    "candidates": (pending.get("payload") or {}).get("candidates") or [],
                },
            }
        return {
            "pending_action": {
                **pending,
                "message": "어떤 상품인지 모르겠어요. 번호로 다시 말씀해 주세요.",
            },
            "stage": "product_confirming",
            "error": None,
        }

    resolution = state.get("reorder_resolution") or {}
    if resolution:
        resolution_type = resolution.get("resolution_type")
        if resolution_type == "resolved":
            candidate = resolution.get("selected_candidate") or {}
            raw_url = candidate.get("product_url", "")
            product_url = raw_url if mock_validate_product_url(raw_url) else ""

            selected_product = {
                "product_id": candidate.get("product_id"),
                "product_option_id": candidate.get("product_option_id"),
                "purchase_history_id": candidate.get("purchase_history_id"),
                "product_name": candidate.get("product_name", ""),
                "brand": candidate.get("brand"),
                "category": candidate.get("category"),
                "price": candidate.get("price_at_purchase", 0),
                "platform": candidate.get("platform", ""),
                "option_text": candidate.get("option_text"),
                "selected_options": candidate.get("selected_options") or {},
                "product_url": product_url,
            }
            pending_action = {
                "type": "product_confirm",
                "message": f"{candidate.get('product_name', '상품')}, {candidate.get('price_at_purchase', 0):,}원이에요. 다시 주문할까요?",
                "payload": {
                    "purchase_history_id": candidate.get("purchase_history_id"),
                    "product_url": product_url,
                    "selected_options": candidate.get("selected_options") or {},
                    "option_text": candidate.get("option_text"),
                },
            }
            return {
                "selected_product": selected_product,
                "product_url": product_url,
                "pending_action": pending_action,
                "stage": "product_confirming",
                "error": None,
            }

        if resolution_type == "ambiguous":
            candidates = resolution.get("candidates") or []
            return {
                "pending_action": {
                    "type": "product_select",
                    "message": resolution.get("question")
                    or "이전에 사신 상품이 여러 개예요. 어떤 걸로 할까요?",
                    "payload": {"candidates": candidates[:3]},
                },
                "search_results": state.get("search_results") or [],
                "stage": "product_confirming",
                "error": None,
            }

        if resolution_type == "no_match":
            return {
                "stage": "searching",
                "error": "reorder_no_match",
                "search_results": [],
            }

    search_results = state.get("search_results") or []
    keywords = state.get("keywords") or []

    # 구매 이력에서 첫 번째 후보 선택 (URL 없어도 상품명 검색 fallback 가능)
    candidate = search_results[0] if search_results else None

    if candidate is None:
        return {
            "stage": "searching",
            "error": "reorder_no_match",
            "search_results": [],
        }

    raw_url = candidate.get("product_url", "")
    product_url = raw_url if mock_validate_product_url(raw_url) else ""
    selected_product = {
        "product_id": candidate.get("product_id"),
        "product_option_id": candidate.get("product_option_id"),
        "product_name": candidate.get("product_name", ""),
        "price": candidate.get("price", 0),
        "platform": candidate.get("platform", ""),
        "option_text": candidate.get("option_text"),
        "selected_options": candidate.get("selected_options") or {},
        "product_url": product_url,
    }

    pending_action = {
        "type": "product_confirm",
        "message": f"{candidate.get('product_name', '상품')}, {candidate.get('price', 0):,}원이에요. 다시 주문할까요?",
        "payload": {
            "product_url": product_url,
            "selected_options": candidate.get("selected_options") or {},
            "option_text": candidate.get("option_text"),
        },
    }

    return {
        "selected_product": selected_product,
        "product_url": product_url,
        "pending_action": pending_action,
        "stage": "product_confirming",
        "error": None,
    }
