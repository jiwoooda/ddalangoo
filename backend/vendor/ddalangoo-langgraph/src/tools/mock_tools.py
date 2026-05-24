"""
외부 서비스 Mock 구현.

인터페이스/contract는 실제와 동일하게 유지.
Playwright, 결제 SDK, Meta-MCP, DB, VectorDB 모두 mock.
"""
import uuid
import time
from typing import Any, Optional

# ══════════════════════════════════════════════
# Mock 상품 데이터
# ══════════════════════════════════════════════

MOCK_PRODUCTS: dict[str, list[dict[str, Any]]] = {
    "딸기": [
        {
            "product_name": "설향 딸기 500g",
            "price": 12900,
            "rating": 4.8,
            "review_count": 1523,
            "delivery": "내일 도착",
            "delivery_fee": 0,
            "platform": "kurly",
            "image_url": "https://mock.kurly.com/strawberry.jpg",
            "product_url": "https://mock.kurly.com/products/strawberry-500g",
            "is_sold_out": False,
            "raw": {},
        },
        {
            "product_name": "죽향 딸기 1kg",
            "price": 22000,
            "rating": 4.6,
            "review_count": 892,
            "delivery": "모레 도착",
            "delivery_fee": 0,
            "platform": "coupang",
            "image_url": "https://mock.coupang.com/strawberry.jpg",
            "product_url": "https://mock.coupang.com/products/strawberry-1kg",
            "is_sold_out": False,
            "raw": {},
        },
    ],
    "운동화": [
        {
            "product_name": "아디다스 슈퍼스타",
            "price": 89000,
            "rating": 4.5,
            "review_count": 3201,
            "delivery": "내일 도착",
            "delivery_fee": 0,
            "platform": "naver",
            "image_url": "https://mock.naver.com/shoes.jpg",
            "product_url": "https://mock.naver.com/products/adidas-superstar",
            "is_sold_out": False,
            "raw": {},
        },
        {
            "product_name": "나이키 에어맥스",
            "price": 139000,
            "rating": 4.7,
            "review_count": 5104,
            "delivery": "2일 후 도착",
            "delivery_fee": 0,
            "platform": "naver",
            "image_url": "https://mock.naver.com/nike.jpg",
            "product_url": "https://mock.naver.com/products/nike-airmax",
            "is_sold_out": False,
            "raw": {},
        },
    ],
    "참기름": [
        {
            "product_name": "오뚜기 참기름 500ml",
            "price": 15900,
            "rating": 4.7,
            "review_count": 892,
            "delivery": "로켓배송",
            "delivery_fee": 0,
            "platform": "coupang",
            "image_url": "https://mock.coupang.com/sesame.jpg",
            "product_url": "https://mock.coupang.com/products/sesame-oil",
            "is_sold_out": False,
            "raw": {},
        },
    ],
}

DEFAULT_PRODUCTS = [
    {
        "product_name": "상품 A",
        "price": 15000,
        "rating": 4.3,
        "review_count": 200,
        "delivery": "내일 도착",
        "delivery_fee": 0,
        "platform": "naver",
        "image_url": "https://mock.naver.com/product-a.jpg",
        "product_url": "https://mock.naver.com/products/a",
        "is_sold_out": False,
        "raw": {},
    },
]

# ══════════════════════════════════════════════
# Mock search_product Tool
# ══════════════════════════════════════════════

def mock_search_product(
    query: str,
    platforms: list[str],
    condition: str = "relevance",
    budget_max: Optional[int] = None,
) -> list[dict[str, Any]]:
    """
    Meta-MCP search_product() mock.
    실제 외부 검색 API 대신 미리 정의된 상품 데이터를 반환한다.
    """
    results = []

    for keyword, products in MOCK_PRODUCTS.items():
        if keyword in query.lower() or any(keyword in q.lower() for q in query.split()):
            for p in products:
                if not platforms or p["platform"] in platforms:
                    results.append(p)

    if not results:
        results = DEFAULT_PRODUCTS

    if budget_max:
        results = [p for p in results if p["price"] <= budget_max]

    if condition == "price_asc":
        results = sorted(results, key=lambda x: x["price"])
    elif condition == "review_score":
        results = sorted(results, key=lambda x: (x.get("rating") or 0, x.get("review_count") or 0), reverse=True)
    elif condition == "delivery_fast":
        results = sorted(results, key=lambda x: 0 if "로켓" in (x.get("delivery") or "") or "내일" in (x.get("delivery") or "") else 1)
    elif condition == "free_shipping":
        results = sorted(results, key=lambda x: 0 if x.get("delivery_fee") == 0 else 1)

    return results


# ══════════════════════════════════════════════
# Mock Playwright Browser Session
# ══════════════════════════════════════════════

class MockPageState:
    def __init__(self, url: str):
        self.url = url
        self.failed = False
        self.page = self


class MockBrowserSession:
    def __init__(self, session_id: str):
        self.id = session_id

    def open_product_page(self, product_url: str) -> MockPageState:
        page = MockPageState(product_url)
        page.failed = False
        return page


class MockOptionResult:
    def __init__(self, failed: bool = False):
        self.failed = failed


class MockCartResult:
    def __init__(self, failed: bool = False):
        self.failed = failed


class MockAddressResult:
    def __init__(self, failed: bool = False):
        self.failed = failed


class MockValidation:
    def __init__(
        self,
        available: bool = True,
        price_changed: bool = False,
        current_price: Optional[int] = None,
    ):
        self.available = available
        self.price_changed = price_changed
        self.current_price = current_price


class MockPaymentPage:
    def __init__(self, failed: bool = False):
        self.failed = failed
        self.url = "https://mock.naverpay.com/payment/checkout"


_playwright_sessions: dict[str, MockBrowserSession] = {}


def get_or_create_playwright_session(
    user_id: str,
    session_key: Optional[str] = None,
) -> MockBrowserSession:
    """Mock Playwright session 관리."""
    if session_key and session_key in _playwright_sessions:
        return _playwright_sessions[session_key]

    session_id = str(uuid.uuid4())
    session = MockBrowserSession(session_id)
    _playwright_sessions[session_id] = session
    return session


def extract_available_options(page: MockPageState) -> list[dict[str, Any]]:
    """상품 페이지에서 옵션 목록 추출 (Mock)."""
    if "strawberry" in page.url or "딸기" in page.url:
        return [
            {"key": "용량", "values": ["500g", "1kg"]},
        ]
    return []


def build_option_question(
    available_options: list[dict[str, Any]],
    current_index: int = 0,
) -> str:
    """옵션 선택 안내 메시지 생성."""
    if not available_options or current_index >= len(available_options):
        return "옵션을 선택해 주세요."
    option = available_options[current_index]
    values = ", ".join(option.get("values", []))
    return f"{option['key']}을 선택해 주세요: {values}"


def apply_options_to_page(
    page: MockPageState,
    selected_options: dict[str, Any],
) -> MockOptionResult:
    """옵션 적용 (Mock — 항상 성공)."""
    return MockOptionResult(failed=False)


def add_to_cart_or_buy_now(
    page: MockPageState,
    quantity: int = 1,
) -> MockCartResult:
    """장바구니 담기 (Mock — 항상 성공)."""
    return MockCartResult(failed=False)


def fill_delivery_address(
    page: MockPageState,
    delivery_address: dict[str, Any],
) -> MockAddressResult:
    """배송지 입력 (Mock — 항상 성공)."""
    return MockAddressResult(failed=False)


def format_address_confirm_message(delivery_address: dict[str, Any]) -> str:
    """배송지 확인 메시지 포맷."""
    addr1 = delivery_address.get("address_line1", "")
    addr2 = delivery_address.get("address_line2", "")
    recipient = delivery_address.get("recipient_name", "")
    addr = f"{addr1} {addr2}".strip()
    return f"{recipient}님, {addr}로 배송할까요?"


def revalidate_product_on_page(page: MockPageState) -> MockValidation:
    """결제 직전 상품 재검증 (Mock — 항상 유효)."""
    return MockValidation(available=True, price_changed=False)


def proceed_to_naverpay(page: MockPageState) -> MockPaymentPage:
    """네이버페이 결제창 진입 (Mock — 항상 성공)."""
    return MockPaymentPage(failed=False)


def open_webview(webview_type: str, url: str) -> dict[str, Any]:
    """웹뷰 오픈 명령 생성."""
    return {"type": "open_webview", "webview_type": webview_type, "url": url}


# ══════════════════════════════════════════════
# Mock Checkout Session
# ══════════════════════════════════════════════

class MockCheckoutSession:
    def __init__(
        self,
        session_id: str,
        user_id: str,
        product: dict[str, Any],
        product_url: str,
        quantity: int,
        selected_platform: Optional[str],
        delivery_address: Optional[dict[str, Any]] = None,
    ):
        self.id = session_id
        self.user_id = user_id
        self.product = product
        self.product_url = product_url
        self.quantity = quantity
        self.selected_platform = selected_platform
        self.delivery_address = delivery_address
        self.price = product.get("price", 0)
        self.payment_url = f"https://mock.naverpay.com/checkout/{session_id}"


_checkout_sessions: dict[str, MockCheckoutSession] = {}


def get_checkout_session(checkout_session_id: str) -> Optional[MockCheckoutSession]:
    return _checkout_sessions.get(checkout_session_id)


def create_checkout_session(
    user_id: str,
    conversation_id: Optional[int],
    product: dict[str, Any],
    product_url: str,
    quantity: int,
    selected_platform: Optional[str],
) -> MockCheckoutSession:
    session_id = str(uuid.uuid4())
    session = MockCheckoutSession(
        session_id=session_id,
        user_id=user_id,
        product=product,
        product_url=product_url,
        quantity=quantity,
        selected_platform=selected_platform,
    )
    _checkout_sessions[session_id] = session
    return session


def update_checkout_price(checkout_session_id: str, new_price: int) -> None:
    session = _checkout_sessions.get(checkout_session_id)
    if session:
        session.price = new_price


# ══════════════════════════════════════════════
# Mock Order / Payment Record
# ══════════════════════════════════════════════

class MockOrder:
    def __init__(self, order_id: str, checkout_id: str, payment_url: str):
        self.id = order_id
        self.checkout_id = checkout_id
        self.payment_url = payment_url


class MockPaymentRecord:
    def __init__(self, payment_id: str, order_id: str):
        self.id = payment_id
        self.order_id = order_id


_orders: dict[str, MockOrder] = {}  # checkout_id → order
_order_ids: dict[str, MockOrder] = {}  # order_id → order


def find_order_by_idempotency_key(checkout_id: str) -> Optional[MockOrder]:
    return _orders.get(checkout_id)


def create_order_from_checkout(
    checkout_id: str,
    validation: MockValidation,
) -> MockOrder:
    order_id = str(uuid.uuid4())
    order = MockOrder(
        order_id=order_id,
        checkout_id=checkout_id,
        payment_url=f"https://mock.naverpay.com/payment/{order_id}",
    )
    _orders[checkout_id] = order
    _order_ids[order_id] = order
    return order


def create_order_item(order_id: str, checkout_id: str, validation: MockValidation) -> None:
    pass


def create_payment_record(order_id: str) -> MockPaymentRecord:
    payment_id = str(uuid.uuid4())
    return MockPaymentRecord(payment_id=payment_id, order_id=order_id)


def mark_order_payment_failed(order_id: str) -> None:
    pass


# ══════════════════════════════════════════════
# Mock transaction context manager
# ══════════════════════════════════════════════

class transaction:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


# ══════════════════════════════════════════════
# Mock DB
# ══════════════════════════════════════════════

MOCK_USERS: dict[str, dict[str, Any]] = {
    "1": {
        "name": "김영희",
        "age_group": "70s",
    },
    "user_001": {
        "name": "김영희",
        "age_group": "60s",
    },
    "user_test": {
        "name": "테스트유저",
        "age_group": "30s",
    },
}

MOCK_ADDRESSES: dict[str, dict[str, Any]] = {
    "1": {
        "id": "addr_001",
        "recipient_name": "김영희",
        "recipient_phone": "010-1234-5678",
        "address_line1": "서울특별시 강남구 테헤란로 1길 10",
        "address_line2": "101호",
        "zip_code": "06000",
        "delivery_request": "문 앞에 놓아주세요",
    },
    "user_001": {
        "id": "addr_001",
        "recipient_name": "김영희",
        "recipient_phone": "010-1234-5678",
        "address_line1": "서울특별시 강남구 테헤란로 123",
        "address_line2": "101호",
        "zip_code": "06234",
        "delivery_request": "문 앞에 놓아주세요",
    },
    "user_test": {
        "id": "addr_test",
        "recipient_name": "테스트유저",
        "recipient_phone": "010-0000-0000",
        "address_line1": "서울특별시 마포구 합정동 100",
        "address_line2": "",
        "zip_code": "04040",
        "delivery_request": "",
    },
}

MOCK_PURCHASE_HISTORY: dict[str, list[dict[str, Any]]] = {
    "user_001": [
        {
            "id": "ph_001",
            "order_id": "order_001",
            "product_name_snapshot": "설향 딸기 500g",
            "brand_snapshot": None,
            "category_snapshot": "과일",
            "platform": "kurly",
            "price_at_purchase": 12900,
            "quantity": 1,
            "selected_options": {},
            "product_url": "https://mock.kurly.com/products/strawberry-500g",
            "purchased_at": "2025-01-10T10:00:00",
        },
    ],
    "user_test": [],
}

MOCK_PREFERENCE_MEMORY: dict[str, dict[str, Any]] = {
    "user_001": {
        "platform_pattern": {"과일": "kurly", "딸기": "kurly"},
        "price_range": {
            "과일": {"samples": [12900], "min": 12900, "max": 12900, "avg": 12900}
        },
        "preferred_delivery": "새벽배송",
        "excluded_brands": [],
        "preferred_brands": [],
        "recent_keywords": ["딸기", "과일"],
        "updated_at": "2025-01-10T10:00:00",
    },
    "user_test": {
        "platform_pattern": {},
        "price_range": {},
        "preferred_delivery": None,
        "excluded_brands": [],
        "preferred_brands": [],
        "recent_keywords": [],
    },
}


def mock_get_user(user_id: str) -> Optional[dict[str, Any]]:
    return MOCK_USERS.get(user_id)


def mock_get_default_address(user_id: str) -> Optional[dict[str, Any]]:
    return MOCK_ADDRESSES.get(user_id)


def mock_get_purchase_history(user_id: str) -> list[dict[str, Any]]:
    return MOCK_PURCHASE_HISTORY.get(user_id, [])


def mock_keyword_search_history(
    user_id: str,
    keywords: list[str],
    limit: int = 5,
) -> list[dict[str, Any]]:
    history = mock_get_purchase_history(user_id)
    results = []
    for item in history:
        name = item.get("product_name_snapshot", "").lower()
        cat = item.get("category_snapshot", "").lower()
        if any(k.lower() in name or k.lower() in cat for k in keywords):
            results.append(item)
    return results[:limit]


def mock_get_preference_memory(user_id: str) -> dict[str, Any]:
    return MOCK_PREFERENCE_MEMORY.get(user_id, {})


def mock_count_purchases(user_id: str) -> int:
    return len(mock_get_purchase_history(user_id))


# ══════════════════════════════════════════════
# Mock Vector DB
# ══════════════════════════════════════════════

def mock_vector_search_personal(
    user_id: str,
    query: str,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """개인 Vector DB 검색 Mock — 구매 이력 기반 간단 반환."""
    history = mock_get_purchase_history(user_id)
    return history[:limit]


def mock_vector_search_collective(
    query: str,
    age_group: Optional[str] = None,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """집단 Vector DB 검색 Mock — 기본 상품 반환."""
    all_products = []
    for products in MOCK_PRODUCTS.values():
        all_products.extend(products)
    return all_products[:limit]


# ══════════════════════════════════════════════
# Mock URL Validator (reorder_node용)
# ══════════════════════════════════════════════

_BLOCKED_URLS: set[str] = set()


def mock_validate_product_url(url: str) -> bool:
    """
    상품 URL 접근 가능 여부 확인 (Mock).
    - mock.kurly.com / mock.coupang.com / mock.naver.com 도메인은 항상 유효
    - _BLOCKED_URLS에 등록된 URL은 실패 (테스트용)
    """
    if not url:
        return False
    if url in _BLOCKED_URLS:
        return False
    valid_domains = ("mock.kurly.com", "mock.coupang.com", "mock.naver.com")
    return any(domain in url for domain in valid_domains)


def block_product_url(url: str) -> None:
    """테스트에서 URL을 강제로 막는 헬퍼."""
    _BLOCKED_URLS.add(url)


def unblock_product_url(url: str) -> None:
    """테스트에서 URL 차단 해제."""
    _BLOCKED_URLS.discard(url)
