package com.ddalangoo.ddalangoo.accessibility

data class ActionPlan(
    val actionType: String,
    val targetNodeId: Int?,
    val textToInput: String?,
    val reasonCode: String,
    val confidence: Double
)

enum class AutomationActionType(val value: String) {
    INPUT_TEXT("input_text"),
    CLICK("click"),
    SCROLL("scroll"),
    DUMP_PURCHASE_HISTORY("dump_purchase_history"),
    STOP_FOR_SENSITIVE_SCREEN("stop_for_sensitive_screen"),
    NO_TARGET_FOUND("no_target_found")
}

enum class RuleReasonCode(val value: String) {
    SEARCH_INPUT("search_input"),
    SEARCH_BUTTON("search_button"),
    PRODUCT_CARD("product_card"),
    CART_BUTTON("cart_button"),
    MY_COUPANG("my_coupang"),
    MY_KURLY("my_kurly"),
    ORDER_HISTORY("order_history"),
    PURCHASE_HISTORY_DUMP("purchase_history_dump"),
    PURCHASE_HISTORY_SCROLL("purchase_history_scroll"),
    PURCHASE_HISTORY_FINISH("purchase_history_finish"),
    REORDER_BUTTON("reorder_button"),
    POPUP_DISMISS("popup_dismiss"),
    SENSITIVE_SCREEN("sensitive_screen"),
    SCROLL_CONTAINER("scroll_container"),
    NO_TARGET("no_target")
}

class RuleBasedPlanner {
    private val sensitiveKeywords = listOf(
        "로그인",
        "비밀번호",
        "결제 비밀번호",
        "본인인증",
        "인증번호",
        "카드번호",
        "cvc",
        "주민등록번호",
        "생체인증",
        "공동인증서"
    )
    private val searchInputKeywords = listOf("검색", "검색어", "무엇을 찾고 계신가요", "상품을 검색")
    private val cartKeywords = listOf("장바구니 담기", "장바구니", "담기", "카트에 담기")
    private val popupDismissKeywords = listOf("닫기", "확인", "취소", "나중에 하기", "오늘 하루 보지 않기", "건너뛰기")
    private val myCoupangKeywords = listOf("마이쿠팡")
    private val myKurlyKeywords = listOf("마이컬리", "마이 컬리", "MY컬리", "MY 컬리")
    private val orderHistoryKeywords = listOf(
        "주문목록",
        "주문내역",
        "주문 내역",
        "구매내역",
        "구매 내역",
        "주문/배송",
        "주문배송",
        "배송조회"
    )
    private val reorderKeywords = listOf("재구매", "다시 구매", "다시구매", "장바구니 담기", "담기")

    fun plan(filteredNodes: List<UiNode>, task: AutomationTask): ActionPlan {
        // 결제/인증처럼 민감한 화면은 어떤 자동화 단계보다 먼저 중단한다.
        findSensitiveNode(filteredNodes)?.let { sensitiveNode ->
            return ActionPlan(
                actionType = AutomationActionType.STOP_FOR_SENSITIVE_SCREEN.value,
                targetNodeId = sensitiveNode.id,
                textToInput = null,
                reasonCode = RuleReasonCode.SENSITIVE_SCREEN.value,
                confidence = 1.0
            )
        }

        // 기본 팝업은 현재 단계와 무관하게 먼저 닫아야 검색/상품 노드가 드러난다.
        findPopupDismissButton(filteredNodes)?.let { popupNode ->
            return clickPlan(popupNode, RuleReasonCode.POPUP_DISMISS, 0.86)
        }

        return when (task.currentStep) {
            "open_my_coupang" -> planMyCoupang(filteredNodes)
            "open_my_kurly" -> planMyKurly(filteredNodes)
            "open_order_history" -> planOrderHistory(filteredNodes)
            "dump_purchase_history" -> planPurchaseHistoryDump()
            "extract_purchase_history" -> planPurchaseHistoryDump()
            "finish_purchase_history" -> planPurchaseHistoryFinish()
            "complete_purchase_history_collection" -> planPurchaseHistoryFinish()
            "scroll_purchase_history" -> planPurchaseHistoryScroll(filteredNodes)
            "click_reorder" -> planReorder(filteredNodes)
            "search_input" -> planSearchInput(filteredNodes, task)
            "search_submit" -> planSearchButton(filteredNodes)
            "select_product" -> planProductCard(filteredNodes, task)
            "add_to_cart" -> planCartButton(filteredNodes)
            "completed" -> noTarget("task_completed")
            else -> planSearchInput(filteredNodes, task)
        }
    }

    private fun planMyCoupang(filteredNodes: List<UiNode>): ActionPlan {
        val myCoupangNode = filteredNodes.firstOrNull { node -> containsAny(node, myCoupangKeywords) }
        return myCoupangNode?.let { clickPlan(it, RuleReasonCode.MY_COUPANG, 0.92) }
            ?: noTarget(RuleReasonCode.MY_COUPANG.value)
    }

    private fun planMyKurly(filteredNodes: List<UiNode>): ActionPlan {
        val myKurlyNode = filteredNodes.firstOrNull { node -> containsAny(node, myKurlyKeywords) }
        return myKurlyNode?.let { clickPlan(it, RuleReasonCode.MY_KURLY, 0.92) }
            ?: noTarget(RuleReasonCode.MY_KURLY.value)
    }

    private fun planOrderHistory(filteredNodes: List<UiNode>): ActionPlan {
        val orderHistoryNode = filteredNodes.firstOrNull { node -> containsAny(node, orderHistoryKeywords) }
        return orderHistoryNode?.let { clickPlan(it, RuleReasonCode.ORDER_HISTORY, 0.9) }
            ?: noTarget(RuleReasonCode.ORDER_HISTORY.value)
    }

    private fun planPurchaseHistoryDump(): ActionPlan {
        return ActionPlan(
            actionType = AutomationActionType.DUMP_PURCHASE_HISTORY.value,
            targetNodeId = null,
            textToInput = null,
            reasonCode = RuleReasonCode.PURCHASE_HISTORY_DUMP.value,
            confidence = 1.0
        )
    }

    private fun planPurchaseHistoryFinish(): ActionPlan {
        return ActionPlan(
            actionType = AutomationActionType.DUMP_PURCHASE_HISTORY.value,
            targetNodeId = null,
            textToInput = null,
            reasonCode = RuleReasonCode.PURCHASE_HISTORY_FINISH.value,
            confidence = 1.0
        )
    }

    private fun planPurchaseHistoryScroll(filteredNodes: List<UiNode>): ActionPlan {
        val scrollNode = filteredNodes.firstOrNull { node -> node.scrollable || node.role == "scroll_container" }
        return if (scrollNode != null) {
            ActionPlan(
                actionType = AutomationActionType.SCROLL.value,
                targetNodeId = scrollNode.id,
                textToInput = null,
                reasonCode = RuleReasonCode.PURCHASE_HISTORY_SCROLL.value,
                confidence = 0.72
            )
        } else {
            noTarget(RuleReasonCode.PURCHASE_HISTORY_SCROLL.value)
        }
    }

    private fun planReorder(filteredNodes: List<UiNode>): ActionPlan {
        val reorderNode = filteredNodes.firstOrNull { node -> containsAny(node, reorderKeywords) }
        return reorderNode?.let { clickPlan(it, RuleReasonCode.REORDER_BUTTON, 0.88) }
            ?: noTarget(RuleReasonCode.REORDER_BUTTON.value)
    }

    private fun planSearchInput(filteredNodes: List<UiNode>, task: AutomationTask): ActionPlan {
        val searchInputNode = filteredNodes
            .filter { node -> node.editable || node.role == "input" || containsAny(node, searchInputKeywords) }
            .maxByOrNull { node -> searchInputScore(node) }

        return if (searchInputNode != null) {
            ActionPlan(
                actionType = AutomationActionType.INPUT_TEXT.value,
                targetNodeId = searchInputNode.id,
                textToInput = task.targetProductName,
                reasonCode = RuleReasonCode.SEARCH_INPUT.value,
                confidence = searchInputScore(searchInputNode)
            )
        } else {
            noTarget(RuleReasonCode.SEARCH_INPUT.value)
        }
    }

    private fun planSearchButton(filteredNodes: List<UiNode>): ActionPlan {
        val searchButtonNode = filteredNodes
            .filter { node -> containsAny(node, listOf("검색")) && (node.clickable || node.role == "button" || isImageButton(node)) }
            .maxByOrNull { node -> if (node.clickable) 0.92 else 0.72 }

        return searchButtonNode?.let { clickPlan(it, RuleReasonCode.SEARCH_BUTTON, 0.9) }
            ?: noTarget(RuleReasonCode.SEARCH_BUTTON.value)
    }

    private fun planProductCard(filteredNodes: List<UiNode>, task: AutomationTask): ActionPlan {
        val normalizedTarget = normalize(task.targetProductName)
        val productNode = filteredNodes
            .filter { node -> node.primaryText().isNotBlank() }
            .map { node -> node to productScore(normalizedTarget, normalize(node.primaryText())) }
            .filter { (_, score) -> score >= 0.45 }
            .maxByOrNull { (_, score) -> score }
            ?.first

        return productNode?.let { clickPlan(it, RuleReasonCode.PRODUCT_CARD, 0.78) }
            ?: fallbackScroll(filteredNodes, RuleReasonCode.PRODUCT_CARD.value)
    }

    private fun planCartButton(filteredNodes: List<UiNode>): ActionPlan {
        val cartButtonNode = filteredNodes
            .filter { node -> containsAny(node, cartKeywords) }
            .maxByOrNull { node -> if (node.clickable || node.role == "button") 0.9 else 0.65 }

        return cartButtonNode?.let { clickPlan(it, RuleReasonCode.CART_BUTTON, 0.88) }
            ?: fallbackScroll(filteredNodes, RuleReasonCode.CART_BUTTON.value)
    }

    private fun fallbackScroll(filteredNodes: List<UiNode>, reasonCode: String): ActionPlan {
        val scrollNode = filteredNodes.firstOrNull { node -> node.scrollable || node.role == "scroll_container" }
        return if (scrollNode != null) {
            ActionPlan(
                actionType = AutomationActionType.SCROLL.value,
                targetNodeId = scrollNode.id,
                textToInput = null,
                reasonCode = RuleReasonCode.SCROLL_CONTAINER.value,
                confidence = 0.55
            )
        } else {
            noTarget(reasonCode)
        }
    }

    private fun findSensitiveNode(filteredNodes: List<UiNode>): UiNode? {
        return filteredNodes.firstOrNull { node -> containsAny(node, sensitiveKeywords) }
    }

    private fun findPopupDismissButton(filteredNodes: List<UiNode>): UiNode? {
        return filteredNodes.firstOrNull { node ->
            containsAny(node, popupDismissKeywords) && (node.clickable || node.role == "button")
        }
    }

    private fun clickPlan(node: UiNode, reasonCode: RuleReasonCode, confidence: Double): ActionPlan {
        return ActionPlan(
            actionType = AutomationActionType.CLICK.value,
            targetNodeId = node.id,
            textToInput = null,
            reasonCode = reasonCode.value,
            confidence = confidence
        )
    }

    private fun noTarget(reasonCode: String): ActionPlan {
        return ActionPlan(
            actionType = AutomationActionType.NO_TARGET_FOUND.value,
            targetNodeId = null,
            textToInput = null,
            reasonCode = reasonCode,
            confidence = 0.0
        )
    }

    private fun searchInputScore(node: UiNode): Double {
        var score = 0.0
        if (node.editable) score += 0.55
        if (node.role == "input") score += 0.25
        if (containsAny(node, searchInputKeywords)) score += 0.2
        return score.coerceAtMost(1.0)
    }

    private fun productScore(normalizedTarget: String, normalizedNodeText: String): Double {
        if (normalizedTarget.isBlank() || normalizedNodeText.isBlank()) return 0.0
        if (normalizedNodeText.contains(normalizedTarget)) return 1.0
        if (normalizedTarget.contains(normalizedNodeText)) return 0.75

        val targetTokens = normalizedTarget.split(" ").filter { it.length >= 2 }.toSet()
        val nodeTokens = normalizedNodeText.split(" ").filter { it.length >= 2 }.toSet()
        if (targetTokens.isEmpty()) return 0.0

        val overlapCount = targetTokens.intersect(nodeTokens).size
        return overlapCount.toDouble() / targetTokens.size.toDouble()
    }

    private fun containsAny(node: UiNode, keywords: List<String>): Boolean {
        val combinedText = node.searchableText()
        return keywords.any { keyword -> combinedText.contains(keyword.lowercase()) }
    }

    private fun normalize(value: String): String {
        return value.lowercase()
            .replace(Regex("[^0-9a-z가-힣 ]"), " ")
            .replace(Regex("\\s+"), " ")
            .trim()
    }

    private fun isImageButton(node: UiNode): Boolean {
        return node.className.orEmpty().contains("ImageButton", ignoreCase = true)
    }
}
