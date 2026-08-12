from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.product_search import ProductSearchExecution


SUPPORTED_PRODUCT_SEARCH_PLATFORMS = ("kurly", "coupang")


def order_platforms_for_product_search(
    platforms: list[str] | tuple[str, ...] | None = None,
    *,
    preferred_platform: str | None = None,
) -> list[str]:
    """선호 플랫폼이 있으면 먼저 방문하고, 나머지는 기본 순서를 유지한다."""
    normalized_platforms = []
    for platform in platforms or SUPPORTED_PRODUCT_SEARCH_PLATFORMS:
        normalized = str(platform).lower().strip()
        if normalized and normalized not in normalized_platforms:
            normalized_platforms.append(normalized)

    preferred = (preferred_platform or "").lower().strip()
    if preferred and preferred in normalized_platforms:
        return [preferred] + [
            platform for platform in normalized_platforms if platform != preferred
        ]
    return normalized_platforms


def _execution_to_dict(execution: ProductSearchExecution) -> dict[str, Any]:
    return {
        "id": execution.id,
        "search_id": execution.search_id,
        "conversation_id": execution.conversation_id,
        "user_id": execution.user_id,
        "query": execution.query,
        "status": execution.status,
        "preferred_platform": execution.preferred_platform,
        "platform_queue": list(execution.platform_queue or []),
        "current_platform": execution.current_platform,
        "current_platform_index": execution.current_platform_index,
        "products_by_platform": dict(execution.products_by_platform or {}),
        "merged_products": list(execution.merged_products or []),
        "error_code": execution.error_code,
        "error_message": execution.error_message,
        "completed_at": execution.completed_at,
        "created_at": execution.created_at,
        "updated_at": execution.updated_at,
    }


async def create_product_search_execution_db(
    db: AsyncSession,
    *,
    search_id: str,
    conversation_id: int,
    user_id: int,
    query: str,
    preferred_platform: str | None = None,
    platforms: list[str] | tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """플랫폼 상품 검색 실행을 만들고 첫 플랫폼을 running 상태로 둔다."""
    platform_queue = order_platforms_for_product_search(
        platforms,
        preferred_platform=preferred_platform,
    )
    current_platform = platform_queue[0] if platform_queue else None
    execution = ProductSearchExecution(
        search_id=search_id,
        conversation_id=conversation_id,
        user_id=user_id,
        query=query,
        status="running" if current_platform else "failed",
        preferred_platform=preferred_platform,
        platform_queue=platform_queue,
        current_platform=current_platform,
        current_platform_index=0,
        products_by_platform={},
        merged_products=[],
        error_code=None if current_platform else "no_supported_platforms",
        error_message=None if current_platform else "No supported platform is available",
    )
    db.add(execution)
    await db.commit()
    await db.refresh(execution)
    return _execution_to_dict(execution)


async def get_product_search_execution_by_search_id_db(
    db: AsyncSession,
    search_id: str,
) -> dict[str, Any] | None:
    result = await db.execute(
        select(ProductSearchExecution).where(ProductSearchExecution.search_id == search_id)
    )
    execution = result.scalar_one_or_none()
    return _execution_to_dict(execution) if execution else None


async def get_running_product_search_execution_db(
    db: AsyncSession,
    *,
    conversation_id: int,
    query: str,
) -> dict[str, Any] | None:
    """같은 대화/검색어로 아직 실행 중인 product_search가 있으면 재사용한다."""
    result = await db.execute(
        select(ProductSearchExecution)
        .where(
            ProductSearchExecution.conversation_id == conversation_id,
            ProductSearchExecution.query == query,
            ProductSearchExecution.status.in_(("requested", "running")),
        )
        .order_by(ProductSearchExecution.id.desc())
    )
    execution = result.scalars().first()
    return _execution_to_dict(execution) if execution else None


async def get_product_search_execution_for_task_id_db(
    db: AsyncSession,
    task_id: str,
) -> dict[str, Any] | None:
    """taskId는 product-search-{searchId}-{platform} 형식으로 내려간다."""
    parts = task_id.split("-")
    if len(parts) < 4 or parts[0] != "product" or parts[1] != "search":
        return None
    search_id = "-".join(parts[2:-1])
    return await get_product_search_execution_by_search_id_db(db, search_id)


async def record_platform_products_db(
    db: AsyncSession,
    *,
    search_id: str,
    platform: str,
    products: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """한 플랫폼 검색 결과를 저장하고 다음 플랫폼 또는 완료 상태로 전환한다."""
    result = await db.execute(
        select(ProductSearchExecution).where(ProductSearchExecution.search_id == search_id)
    )
    execution = result.scalar_one_or_none()
    if not execution:
        return None

    normalized_platform = platform.lower().strip()
    products_by_platform = dict(execution.products_by_platform or {})
    products_by_platform[normalized_platform] = products

    merged_products = []
    for queued_platform in execution.platform_queue or []:
        merged_products.extend(products_by_platform.get(queued_platform, []))

    next_index = execution.current_platform_index + 1
    if next_index < len(execution.platform_queue or []):
        execution.status = "running"
        execution.current_platform_index = next_index
        execution.current_platform = execution.platform_queue[next_index]
    else:
        execution.status = "collected"
        execution.current_platform = None
        execution.completed_at = datetime.now(UTC)

    execution.products_by_platform = products_by_platform
    execution.merged_products = merged_products
    await db.commit()
    await db.refresh(execution)
    return _execution_to_dict(execution)
