### Memory Agent

```powershell
from datetime import datetime
from typing import Any, Optional

class MemoryAgent:
    """
    Memory Agent

    역할:
    - 사용자 기본 프로필 조회
    - 구매 이력 조회/저장
    - 개인 선호 메모리 저장/갱신
    - 추천용 Retrieval Context 생성

    주의:
    - 결제 옵션/주소/checkout 상태는 ShoppingState에 저장하지 않는다.
    - 구매 완료 후 저장은 Payment 결과 또는 Order snapshot 기준으로 수행한다.
    """

    PERSONAL_VECTOR_THRESHOLD = 20

    def load_user_profile(self, user_id: str) -> dict[str, Any]:
        """사용자 기본 정보와 기본 배송지를 조회한다."""

        store_data = self.store.get(("users", user_id), "profile")
        profile = store_data.value if store_data else {}

        user = self.db.query_one("""
            SELECT name, age_group
            FROM users
            WHERE id = %s
        """, user_id)

        default_address = self.db.query_one("""
            SELECT id, recipient_name, recipient_phone,
                   address_line1, address_line2, zip_code, delivery_request
            FROM user_addresses
            WHERE user_id = %s
              AND is_default = true
            LIMIT 1
        """, user_id)

        return {
            "user_id": user_id,
            "name": user.get("name") if user else None,
            "age_group": user.get("age_group") if user else None,
            "default_address": default_address,
            "created_preferences": profile.get("created_preferences", {}),
        }

    def load_preference_memory(self, user_id: str) -> dict[str, Any]:
        """사용자 선호 패턴을 조회한다."""

        store_data = self.store.get(("users", user_id), "preference_memory")
        memory = store_data.value if store_data else {}

        return {
            "platform_pattern": memory.get("platform_pattern", {}),
            "price_range": memory.get("price_range", {}),
            "preferred_delivery": memory.get("preferred_delivery"),
            "excluded_brands": memory.get("excluded_brands", []),
            "preferred_brands": memory.get("preferred_brands", []),
            "recent_keywords": memory.get("recent_keywords", []),
        }

    def count_purchases(self, user_id: str) -> int:
        """사용자 구매 횟수를 조회한다."""

        row = self.db.query_one("""
            SELECT COUNT(*) AS purchase_count
            FROM purchase_histories
            WHERE user_id = %s
        """, user_id)

        return int(row.get("purchase_count", 0)) if row else 0

    def keyword_search_history(
        self,
        user_id: str,
        keywords: list[str],
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """재구매/정확 매칭용 키워드 기반 구매 이력 검색."""

        if not keywords:
            return []

        like_keywords = [f"%{k}%" for k in keywords]

        return self.db.query("""
            SELECT id,
                   order_id,
                   product_name_snapshot,
                   brand_snapshot,
                   category_snapshot,
                   platform,
                   price_at_purchase,
                   quantity,
                   selected_options,
                   product_url,
                   purchased_at
            FROM purchase_histories
            WHERE user_id = %s
              AND (
                   product_name_snapshot ILIKE ANY(%s)
                   OR category_snapshot ILIKE ANY(%s)
                   OR brand_snapshot ILIKE ANY(%s)
              )
            ORDER BY purchased_at DESC
            LIMIT %s
        """, user_id, like_keywords, like_keywords, like_keywords, limit)

    def vector_search_personal(
        self,
        user_id: str,
        query: str,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """
        개인 Vector DB 검색.
        구매 20개 이상일 때만 사용한다.
        실제 vector DB 구현체는 별도 adapter로 분리하는 것이 좋다.
        """

        if not query:
            return []

        return self.personal_vector_db.search(
            namespace=f"user:{user_id}",
            query=query,
            limit=limit,
        )

    def vector_search_collective(
        self,
        query: str,
        user_profile: Optional[dict[str, Any]] = None,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """
        집단 Vector DB 검색.
        Cold-start, 코호트 패턴, 트렌드 파악용.
        """

        if not query:
            return []

        filters = {}

        if user_profile:
            age_group = user_profile.get("age_group")
            if age_group:
                filters["age_group"] = age_group

        return self.collective_vector_db.search(
            namespace="collective:purchases",
            query=query,
            filters=filters,
            limit=limit,
        )

    def get_recommendation_context(
        self,
        user_id: str,
        query: str,
        keywords: list[str],
        intent: Optional[str] = None,
    ) -> dict[str, Any]:
        """
        추천용 Retrieval Context 생성.

        기준:
        - 재구매: keyword search 우선
        - 구매 20개 미만: keyword + collective vector
        - 구매 20개 이상: keyword + personal vector + collective vector
        """

        user_profile = self.load_user_profile(user_id)
        preference_memory = self.load_preference_memory(user_id)
        purchase_count = self.count_purchases(user_id)

        keyword_results = self.keyword_search_history(user_id, keywords)

        use_personal_vector = purchase_count >= self.PERSONAL_VECTOR_THRESHOLD

        personal_vector_results = (
            self.vector_search_personal(user_id, query)
            if use_personal_vector
            else []
        )

        collective_vector_results = self.vector_search_collective(
            query=query,
            user_profile=user_profile,
        )

        if use_personal_vector:
            retrieval_mode = "hybrid_personal_collective"
        else:
            retrieval_mode = "keyword_collective"

        if intent == "reorder":
            retrieval_mode = "keyword_first_reorder"

        merged_context = self.merge_recommendation_results(
            keyword_results=keyword_results,
            personal_vector_results=personal_vector_results,
            collective_vector_results=collective_vector_results,
            intent=intent,
        )

        return {
            "user_profile": user_profile,
            "preference_memory": preference_memory,
            "purchase_count": purchase_count,
            "retrieval_mode": retrieval_mode,
            "keyword_results": keyword_results,
            "personal_vector_results": personal_vector_results,
            "collective_vector_results": collective_vector_results,
            "merged_context": merged_context,
        }

    def merge_recommendation_results(
        self,
        keyword_results: list[dict[str, Any]],
        personal_vector_results: list[dict[str, Any]],
        collective_vector_results: list[dict[str, Any]],
        intent: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """
        추천 검색 결과 병합.
        단순 버전:
        - reorder는 keyword 우선
        - 일반 추천은 personal vector > keyword > collective 순
        """

        merged = []
        seen = set()

        if intent == "reorder":
            sources = [
                ("keyword", keyword_results),
                ("personal_vector", personal_vector_results),
                ("collective_vector", collective_vector_results),
            ]
        else:
            sources = [
                ("personal_vector", personal_vector_results),
                ("keyword", keyword_results),
                ("collective_vector", collective_vector_results),
            ]

        for source, results in sources:
            for item in results:
                key = (
                    item.get("product_url")
                    or item.get("product_name_snapshot")
                    or item.get("product_name")
                    or item.get("id")
                )

                if not key or key in seen:
                    continue

                item["_memory_source"] = source
                merged.append(item)
                seen.add(key)

        return merged[:10]

    def save_purchase_from_order(
        self,
        order: dict[str, Any],
        payment: Optional[dict[str, Any]] = None,
    ) -> None:
        """
        결제 완료 후 구매 이력을 저장한다.
        ShoppingState가 아니라 Order/Payment snapshot 기준으로 저장한다.
        """

        user_id = order.get("user_id")
        product = order.get("product") or {}

        if not user_id or not product:
            return

        quantity = order.get("quantity") or 1
        price = order.get("price") or product.get("price") or 0
        selected_platform = order.get("platform") or product.get("platform")
        product_name = product.get("product_name") or product.get("name")

        self.db.insert("purchase_histories", {
            "user_id": user_id,
            "conversation_id": order.get("conversation_id"),
            "order_id": order.get("id"),
            "product_name_snapshot": product_name,
            "brand_snapshot": product.get("brand"),
            "category_snapshot": product.get("category"),
            "platform": selected_platform,
            "price_at_purchase": price,
            "quantity": quantity,
            "total_price": price * quantity,
            "product_url": product.get("product_url") or product.get("url"),
            "selected_options": order.get("selected_options") or {},
            "purchased_at": datetime.now(),
            "payment_id": payment.get("id") if payment else None,
        })

        self.update_preference_memory_from_order(order)

        # 개인 vector DB 업데이트는 구매 이력 저장 후 별도 처리
        self.upsert_personal_purchase_embedding(order)

    def update_preference_memory_from_order(self, order: dict[str, Any]) -> None:
        """구매 완료 후 개인 선호 메모리를 갱신한다."""

        user_id = order.get("user_id")
        product = order.get("product") or {}

        if not user_id or not product:
            return

        store_data = self.store.get(("users", user_id), "preference_memory")
        memory = store_data.value if store_data else {}

        keywords = order.get("keywords") or []
        selected_platform = order.get("platform") or product.get("platform")
        brand = product.get("brand")
        category = product.get("category")
        price = order.get("price") or product.get("price")

        platform_pattern = memory.get("platform_pattern", {})
        recent_keywords = memory.get("recent_keywords", [])
        preferred_brands = memory.get("preferred_brands", [])
        price_range = memory.get("price_range", {})

        if selected_platform:
            for kw in keywords:
                platform_pattern[kw] = selected_platform

        if brand and brand not in preferred_brands:
            preferred_brands.append(brand)

        if category and price:
            current = price_range.get(category, {})
            prices = current.get("samples", [])
            prices.append(price)
            prices = prices[-20:]

            price_range[category] = {
                "samples": prices,
                "min": min(prices),
                "max": max(prices),
                "avg": sum(prices) / len(prices),
            }

        recent_keywords = keywords + [
            k for k in recent_keywords
            if k not in keywords
        ]

        memory["platform_pattern"] = platform_pattern
        memory["recent_keywords"] = recent_keywords[:20]
        memory["preferred_brands"] = preferred_brands[:20]
        memory["price_range"] = price_range
        memory["updated_at"] = datetime.now().isoformat()

        self.store.put(("users", user_id), "preference_memory", memory)

    def upsert_personal_purchase_embedding(self, order: dict[str, Any]) -> None:
        """
        개인 구매 이력 embedding 저장.
        실제 embedding 생성 로직은 embedding_service에 위임한다.
        """

        user_id = order.get("user_id")
        product = order.get("product") or {}

        if not user_id or not product:
            return

        text = self.build_purchase_embedding_text(order)

        vector = self.embedding_service.embed(text)

        self.personal_vector_db.upsert(
            namespace=f"user:{user_id}",
            id=str(order.get("id")),
            vector=vector,
            metadata={
                "user_id": user_id,
                "order_id": order.get("id"),
                "product_name": product.get("product_name") or product.get("name"),
                "brand": product.get("brand"),
                "category": product.get("category"),
                "platform": order.get("platform") or product.get("platform"),
                "price": order.get("price") or product.get("price"),
                "purchased_at": datetime.now().isoformat(),
            },
        )

    def build_purchase_embedding_text(self, order: dict[str, Any]) -> str:
        """구매 이력 embedding용 텍스트를 생성한다."""

        product = order.get("product") or {}
        selected_options = order.get("selected_options") or {}

        parts = [
            f"상품명: {product.get('product_name') or product.get('name')}",
            f"브랜드: {product.get('brand')}",
            f"카테고리: {product.get('category')}",
            f"플랫폼: {order.get('platform') or product.get('platform')}",
            f"가격: {order.get('price') or product.get('price')}",
            f"옵션: {selected_options}",
            f"키워드: {order.get('keywords') or []}",
        ]

        return "\n".join([p for p in parts if p and "None" not in p])

    def log_intent(self, state: ShoppingState) -> None:
        """사용자 요청과 Intent Agent 결과를 분석용으로 기록한다."""

        messages = state.get("messages", [])
        last_message = None

        if messages:
            last = messages[-1]
            last_message = (
                last.get("content")
                if isinstance(last, dict)
                else getattr(last, "content", None)
            )

        intent = state.get("intent")

        intent_type_map = {
            "buy": "new_purchase",
            "reorder": "repurchase",
            "cancel": "cancel_request",
            "ask": "product_question",
            "unclear": "clarification_needed",
            "confirm": "confirmation",
            "deny": "rejection",
            "refine": "search_refinement",
            "next": "next_product_request",
            "compare_platforms": "platform_comparison",
            "quantity_change": "quantity_change",
            "address_change": "address_change",
            "option_select": "option_select",
        }

        keywords = state.get("keywords", [])

        self.db.insert("agent_intents", {
            "conversation_id": state.get("conversation_id"),
            "session_id": state.get("session_id"),
            "user_id": state.get("user_id"),
            "raw_user_request": last_message,
            "intent": intent,
            "intent_type": intent_type_map.get(intent, "unknown"),
            "stage": state.get("stage"),
            "pending_action_type": (state.get("pending_action") or {}).get("type"),
            "target_product_name": keywords[0] if keywords else None,
            "extracted_keywords": ",".join(keywords),
            "confidence": state.get("confidence"),
            "needs_clarification": state.get("needs_clarification"),
            "clarification_reason": state.get("clarification_reason"),
            "created_at": datetime.now(),
        })
```