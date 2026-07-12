"""로컬 데모용 사용자/주소/상품/구매이력 seed 스크립트.

반복 실행해도 같은 데모 데이터는 갱신되도록 작성했다.
"""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import select

BACKEND_DIR = Path(__file__).resolve().parents[1]
PROJECT_DIR = BACKEND_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

load_dotenv(PROJECT_DIR / ".env")
load_dotenv(BACKEND_DIR / ".env", override=True)

from app.core.database import AsyncSessionLocal  # noqa: E402
from app.models.address import UserAddress  # noqa: E402
from app.models.product import ExternalProductMapping, Product  # noqa: E402
from app.models.purchase_history import PurchaseHistory  # noqa: E402
from app.models.user import User  # noqa: E402
from app.models.user_preference import UserPreferenceCache  # noqa: E402
from app.repositories.product_repository import external_product_url_hash  # noqa: E402


# Context Agent tier1(안전제약) 검증용 — mock_tools.py의 영양정보 목데이터
# 어휘(계란/우유/참깨)와 맞춘 프로필. 우유 알레르기로 둬서, 아래
# negative-feedback 구매이력(계란)과는 다른 채널(tier1 vs tier2)로 검증한다.
DEMO_PROFILE = {
    "allergens": ["우유"],
    "diet_restrictions": [],
}


DEMO_USER = {
    "name": "박미영",
    "phone_number": "010-2345-6789",
    "age_group": "60대",
    "gender": "여성",
}

DEMO_ADDRESS = {
    "address_label": "집",
    "recipient_name": "박미영",
    "recipient_phone": "010-2345-6789",
    "zip_code": None,
    "address_line1": "서울특별시 용산구 청파로47길 100 (청파동2가)",
    "address_line2": None,
    "delivery_request": "문 앞에 놓아주세요.",
    "is_default": True,
}

DEMO_PRODUCTS = [
    {
        "name": "[KF365] 당도선별 수박 1통",
        "normalized_name": "당도선별 수박",
        "brand": "Kurly",
        "category": "과일",
        "sub_category": "수박",
        "description": "데모용 박미영 재주문 수박 상품",
        "volume": "1통",
        "unit": "통",
        "image_url": (
            "https://product-image.kurly.com/hdims/resize/%5E%3E720x%3E936/"
            "cropcenter/720x936/quality/85/src/product/image/"
            "69786586-d752-4a44-8e6c-79d655faa505.jpg"
        ),
        "current_price": 19900,
        "delivery_type": "kurly",
        "current_delivery_info": "샛별배송 가능",
        "rating": 4.8,
        "review_count": 1200,
        "is_available": True,
        "platform": "kurly",
        "external_product_id": "5136384",
        "external_product_url": "https://www.kurly.com/goods/5136384",
        "purchase_history": {
            "keyword": "수박",
            "option_snapshot": "1통",
            "quantity": 1,
            "satisfaction": 5,
            "memo": "지난번에 맛있게 먹었던 수박 데모 이력",
        },
    },
    {
        # Context Agent tier2(negative feedback → exclude_additions) 검증용.
        "name": "[동물복지] 유정란 15구",
        "normalized_name": "유정란",
        "brand": "동물복지",
        "category": "축산",
        "sub_category": "계란",
        "description": "데모용 박미영 비선호 계란 상품",
        "volume": "15구",
        "unit": "판",
        "image_url": (
            "https://product-image.kurly.com/hdims/resize/%5E%3E720x%3E936/"
            "cropcenter/720x936/quality/85/src/product/image/"
            "demo-eggs.jpg"
        ),
        "current_price": 8900,
        "delivery_type": "kurly",
        "current_delivery_info": "샛별배송 가능",
        "rating": 4.2,
        "review_count": 340,
        "is_available": True,
        "platform": "kurly",
        "external_product_id": "5136385",
        "external_product_url": "https://www.kurly.com/goods/5136385",
        "purchase_history": {
            "keyword": "계란",
            "option_snapshot": "15구",
            "quantity": 1,
            "satisfaction": 1,
            "memo": "깨진 게 많아서 다신 안 삼",
        },
    },
]


async def upsert_demo_user(db) -> User:
    """박미영 데모 사용자를 생성하거나 최신 값으로 갱신한다."""
    result = await db.execute(
        select(User).where(User.phone_number == DEMO_USER["phone_number"])
    )
    user = result.scalars().first()
    if user is None:
        user = User(
            name=DEMO_USER["name"],
            phone_number=DEMO_USER["phone_number"],
            age_group=DEMO_USER["age_group"],
            gender=DEMO_USER["gender"],
            password_hash=None,
            is_active=True,
        )
        db.add(user)
        await db.flush()
    else:
        user.name = DEMO_USER["name"]
        user.age_group = DEMO_USER["age_group"]
        user.gender = DEMO_USER["gender"]
        user.is_active = True
    return user


async def upsert_default_address(db, user: User) -> UserAddress:
    """박미영 기본 배송지를 생성하거나 기본값으로 갱신한다."""
    result = await db.execute(select(UserAddress).where(UserAddress.user_id == user.id))
    addresses = list(result.scalars().all())
    address = next(
        (
            item
            for item in addresses
            if item.address_line1 == DEMO_ADDRESS["address_line1"]
        ),
        None,
    )
    for item in addresses:
        item.is_default = False
    if address is None:
        address = UserAddress(user_id=user.id, **DEMO_ADDRESS)
        db.add(address)
    else:
        for key, value in DEMO_ADDRESS.items():
            setattr(address, key, value)
    return address


async def upsert_product_and_mapping(db, product_data: dict) -> Product:
    """데모 상품과 컬리 외부 매핑을 생성하거나 갱신한다."""
    result = await db.execute(select(Product).where(Product.name == product_data["name"]))
    product = result.scalars().first()
    product_fields = {
        key: product_data[key]
        for key in [
            "name",
            "normalized_name",
            "brand",
            "category",
            "sub_category",
            "description",
            "volume",
            "unit",
            "image_url",
            "current_price",
            "delivery_type",
            "current_delivery_info",
            "rating",
            "review_count",
            "is_available",
        ]
    }
    if product is None:
        product = Product(**product_fields)
        db.add(product)
        await db.flush()
    else:
        for key, value in product_fields.items():
            setattr(product, key, value)

    mapping_result = await db.execute(
        select(ExternalProductMapping).where(
            ExternalProductMapping.product_id == product.id,
            ExternalProductMapping.platform == product_data["platform"],
            ExternalProductMapping.external_product_url == product_data["external_product_url"],
        )
    )
    mapping = mapping_result.scalars().first()
    mapping_payload = {
        "product_id": product.id,
        "product_option_id": None,
        "platform": product_data["platform"],
        "external_product_id": product_data["external_product_id"],
        "external_option_id": None,
        "external_product_url": product_data["external_product_url"],
        "external_product_url_hash": external_product_url_hash(
            product_data["external_product_url"]
        ),
        "mall_name": "Kurly",
        "seller_name": "Kurly",
        "metadata_json": {
            "execution_url": product_data["external_product_url"],
            "canonical_product_url": product_data["external_product_url"],
            "source": "demo_seed",
        },
        "last_synced_at": datetime.now(UTC),
    }
    if mapping is None:
        db.add(ExternalProductMapping(**mapping_payload))
    else:
        for key, value in mapping_payload.items():
            setattr(mapping, key, value)
    return product


async def upsert_purchase_history(db, user: User, product: Product, product_data: dict) -> None:
    """재주문 데모용 구매이력을 생성하거나 갱신한다."""
    history_data = product_data.get("purchase_history")
    if not history_data:
        return
    result = await db.execute(
        select(PurchaseHistory).where(
            PurchaseHistory.user_id == user.id,
            PurchaseHistory.product_url_snapshot == product_data["external_product_url"],
        )
    )
    history = result.scalars().first()
    payload = {
        "user_id": user.id,
        "product_id": product.id,
        "product_option_id": None,
        "conversation_id": None,
        "order_id": None,
        "payment_id": None,
        "external_order_id": "demo-watermelon-order",
        "external_product_order_id": f"demo-kurly-{product_data['external_product_id']}",
        "platform": product_data["platform"],
        "keyword": history_data["keyword"],
        "product_name_snapshot": product_data["name"],
        "option_snapshot": history_data["option_snapshot"],
        "brand_snapshot": product_data["brand"],
        "category_snapshot": product_data["category"],
        "price_at_purchase": product_data["current_price"],
        "product_url_snapshot": product_data["external_product_url"],
        "selected_options": {"quantity_unit": history_data["option_snapshot"]},
        "quantity": history_data["quantity"],
        "total_price": product_data["current_price"] * history_data["quantity"],
        "purchased_at": datetime.now(UTC) - timedelta(days=14),
        "satisfaction": history_data["satisfaction"],
        "memo": history_data["memo"],
    }
    if history is None:
        db.add(PurchaseHistory(**payload))
    else:
        for key, value in payload.items():
            setattr(history, key, value)


async def upsert_profile(db, user: User) -> None:
    """
    스몰톡 에이전트가 나중에 채워넣을 장기 프로필(user_preference_cache,
    preference_type="profile")을 목데이터로 미리 넣는다.
    user_preference_repository.get_profile/save_profile과 같은 행을 쓴다.
    """
    result = await db.execute(
        select(UserPreferenceCache).where(
            UserPreferenceCache.user_id == user.id,
            UserPreferenceCache.preference_type == "profile",
            UserPreferenceCache.keywords_key == "",
        )
    )
    row = result.scalars().first()
    if row is None:
        db.add(
            UserPreferenceCache(
                user_id=user.id,
                preference_type="profile",
                keywords_key="",
                preference_data=DEMO_PROFILE,
                computed_at=datetime.now(UTC),
            )
        )
    else:
        row.preference_data = DEMO_PROFILE
        row.computed_at = datetime.now(UTC)


async def seed_demo_data() -> None:
    """데모에 필요한 DB 데이터를 한 번에 준비한다."""
    async with AsyncSessionLocal() as db:
        user = await upsert_demo_user(db)
        address = await upsert_default_address(db, user)
        await upsert_profile(db, user)
        products: list[Product] = []
        for product_data in DEMO_PRODUCTS:
            product = await upsert_product_and_mapping(db, product_data)
            await upsert_purchase_history(db, user, product, product_data)
            products.append(product)

        await db.commit()
        print("demo_seed_ok")
        print(f"user_id={user.id} name={user.name} phone={user.phone_number}")
        print(f"default_address_id={address.id} address={address.address_line1}")
        print(f"profile={DEMO_PROFILE}")
        for product in products:
            print(f"product_id={product.id} name={product.name}")


if __name__ == "__main__":
    if not os.getenv("DATABASE_URL"):
        raise RuntimeError("DATABASE_URL 환경변수가 필요합니다.")
    asyncio.run(seed_demo_data())
