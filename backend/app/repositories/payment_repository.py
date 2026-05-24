from typing import Optional
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.mock_data.payments import MOCK_PAYMENTS
from app.models.order import NaverOrderMapping, Order, Payment

def get_payment_by_id(payment_id: int) -> Optional[dict]:
    return next((p for p in MOCK_PAYMENTS if p["id"] == payment_id), None)

def get_payment_by_order_id(order_id: int) -> Optional[dict]:
    return next((p for p in MOCK_PAYMENTS if p["order_id"] == order_id), None)

def update_payment(payment_id: int, data: dict) -> Optional[dict]:
    payment = get_payment_by_id(payment_id)
    if not payment:
        return None
    payment.update(data)
    return payment


def _payment_to_dict(payment: Payment) -> dict:
    """ORM Payment를 기존 service/mapper가 쓰는 dict 형태로 변환한다."""
    return {
        "id": payment.id,
        "order_id": payment.order_id,
        "payment_provider": payment.payment_provider,
        "payment_method": payment.payment_method,
        "payment_status": payment.payment_status,
        "payment_amount": payment.payment_amount,
        "external_payment_id": payment.external_payment_id,
        "approval_number": payment.approval_number,
        "payment_url": payment.payment_url,
        "paid_at": payment.paid_at,
        "cancelled_at": payment.cancelled_at,
        "failure_reason": payment.failure_reason,
        "created_at": payment.created_at,
        "updated_at": payment.updated_at,
    }


def _naver_order_mapping_to_dict(mapping: NaverOrderMapping) -> dict:
    """ORM NaverOrderMapping을 dict로 변환한다."""
    return {
        "id": mapping.id,
        "order_id": mapping.order_id,
        "payment_id": mapping.payment_id,
        "naver_order_id": mapping.naver_order_id,
        "naver_product_order_id": mapping.naver_product_order_id,
        "naver_payment_id": mapping.naver_payment_id,
        "naver_pay_order_key": mapping.naver_pay_order_key,
        "naver_status": mapping.naver_status,
        "last_synced_at": mapping.last_synced_at,
        "created_at": mapping.created_at,
        "updated_at": mapping.updated_at,
    }


async def get_payment_by_id_db(db: AsyncSession, payment_id: int) -> Optional[dict]:
    """DB 결제 단건을 조회한다."""
    payment = await db.get(Payment, payment_id)
    if not payment:
        return None
    return _payment_to_dict(payment)


async def get_payment_by_order_id_db(db: AsyncSession, order_id: int) -> Optional[dict]:
    """DB에서 주문에 연결된 최신 결제를 조회한다."""
    result = await db.execute(
        select(Payment).where(Payment.order_id == order_id).order_by(Payment.id.desc())
    )
    payment = result.scalars().first()
    if not payment:
        return None
    return _payment_to_dict(payment)


async def update_payment_status_db(
    db: AsyncSession,
    payment_id: int,
    *,
    payment_status: str,
    failure_reason: str | None = None,
) -> Optional[dict]:
    """웹뷰 결제 결과에 맞춰 payment 상태를 갱신한다."""
    payment = await db.get(Payment, payment_id)
    if not payment:
        return None

    payment.payment_status = payment_status
    payment.failure_reason = failure_reason
    if payment_status == "paid":
        payment.paid_at = datetime.now(UTC)
        payment.cancelled_at = None
    elif payment_status == "cancelled":
        payment.cancelled_at = datetime.now(UTC)
    elif payment_status == "failed":
        payment.cancelled_at = None

    await db.commit()
    await db.refresh(payment)
    return _payment_to_dict(payment)


async def create_payment_for_order_db(
    db: AsyncSession,
    *,
    order_id: int,
    payment_provider: str = "mock",
    payment_method: str | None = "mock",
    payment_status: str = "pending_user_action",
    payment_url: str | None = None,
) -> dict:
    """주문 전체 금액 기준으로 결제 레코드와 네이버 매핑 placeholder를 생성한다."""
    existing = await get_payment_by_order_id_db(db, order_id)
    if existing:
        return {
            "payment": existing,
            "naver_order_mapping": None,
        }

    order = await db.get(Order, order_id)
    if not order:
        raise ValueError("결제를 만들 주문을 찾을 수 없습니다.")

    now = datetime.now(UTC)
    payment = Payment(
        order_id=order_id,
        payment_provider=payment_provider,
        payment_method=payment_method,
        payment_status=payment_status,
        payment_amount=order.total_payment_amount,
        payment_url=payment_url,
        paid_at=now if payment_status == "paid" else None,
    )
    db.add(payment)
    await db.flush()

    mapping = NaverOrderMapping(
        order_id=order_id,
        payment_id=payment.id,
        naver_status=payment_status,
        last_synced_at=now,
    )
    db.add(mapping)
    await db.commit()
    await db.refresh(payment)
    await db.refresh(mapping)

    return {
        "payment": _payment_to_dict(payment),
        "naver_order_mapping": _naver_order_mapping_to_dict(mapping),
    }
