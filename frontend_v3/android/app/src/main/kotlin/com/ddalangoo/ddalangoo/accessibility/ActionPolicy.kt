package com.ddalangoo.ddalangoo.accessibility

data class ActionPolicyDecision(
    val allowed: Boolean,
    val reason: String
)

object ActionPolicy {
    const val UNSAFE_RECOVERY_ACTION_ERROR = "UNSAFE_RECOVERY_ACTION"

    private val unsafeBusinessActionKeywords = listOf(
        "접수 취소",
        "주문 취소",
        "주문취소",
        "취소 신청",
        "반품 신청",
        "반품 접수",
        "반품",
        "교환 신청",
        "교환 접수",
        "교환",
        "환불",
        "삭제",
        "구매 확정",
        "구매확정",
        "결제하기",
        "결제",
        "바로 구매",
        "바로구매",
        "구매하기",
        "주문하기"
    )

    private val safePopupDismissKeywords = listOf(
        "닫기",
        "close",
        "오늘 그만 보기",
        "오늘은 그만 보기",
        "오늘 하루 보지 않기",
        "7일간 보지 않기",
        "7일 동안 보지 않기",
        "30일 동안 보지 않기",
        "다시 보지 않기",
        "보지 않기",
        "싫어요",
        "아니요",
        "안 할래요",
        "받지 않기",
        "나중에",
        "다음에",
        "건너뛰기"
    )

    private val popupCloseKeywords = listOf(
        "닫기",
        "close"
    )

    private val doNotShowAgainKeywords = listOf(
        "오늘 그만 보기",
        "오늘은 그만 보기",
        "오늘 하루 보지 않기",
        "7일간 보지 않기",
        "7일 동안 보지 않기",
        "30일 동안 보지 않기",
        "다시 보지 않기",
        "보지 않기"
    )

    private val notificationOptInContextKeywords = listOf(
        "배송 알림",
        "알림을 켜",
        "알림 켜기",
        "알림 받기",
        "알림을 받을",
        "알림 수신",
        "notification"
    )

    private val notificationOptInDeclineKeywords = listOf(
        "싫어요",
        "아니요",
        "안 할래요",
        "받지 않기",
        "나중에",
        "다음에",
        "닫기",
        "close"
    )

    private val popupContextKeywords = listOf(
        "팝업",
        "popup",
        "dialog",
        "overlay",
        "혜택",
        "이벤트",
        "쿠폰",
        "광고",
        "안내",
        "알림",
        "업데이트",
        "프로모션",
        "braze",
        "inappmessage",
        "inappmessage_html"
    )

    fun evaluate(
        task: AutomationTask,
        actionPlan: ActionPlan,
        selectedNode: UiNode?,
        filteredNodes: List<UiNode>,
        screenType: String?
    ): ActionPolicyDecision {
        if (!isExecutableClick(actionPlan)) {
            return ActionPolicyDecision(true, "non_click_action")
        }

        if (isRecoveryAction(actionPlan) && isUnsafeBusinessActionNode(selectedNode, filteredNodes)) {
            val reason = if (actionPlan.reasonCode == RuleReasonCode.POPUP_DISMISS.value) {
                "popup_dismiss_target_is_business_action"
            } else {
                "recovery_target_is_business_action"
            }
            return ActionPolicyDecision(false, reason)
        }

        if (
            actionPlan.reasonCode == RuleReasonCode.POPUP_DISMISS.value &&
            (selectedNode == null || !isSafePopupDismissCandidate(selectedNode, filteredNodes, screenType))
        ) {
            return ActionPolicyDecision(false, "popup_dismiss_lacks_positive_evidence")
        }

        return ActionPolicyDecision(true, "allowed")
    }

    fun isSafePopupDismissCandidate(
        node: UiNode,
        filteredNodes: List<UiNode>,
        screenType: String?
    ): Boolean {
        if (isUnsafeBusinessActionNode(node, filteredNodes)) return false
        if (!containsSafePopupDismissText(node.searchableText())) return false
        if (
            isDoNotShowAgainPopupOption(node) &&
            hasSeparatePopupCloseCandidate(node, filteredNodes, screenType)
        ) {
            return false
        }
        return hasPopupDismissPositiveEvidence(node, filteredNodes, screenType)
            && hasClickableDismissPath(node)
    }

    fun isDoNotShowAgainPopupOption(node: UiNode): Boolean {
        return containsAnyNormalized(node.searchableText(), doNotShowAgainKeywords)
    }

    fun isPopupCloseCandidate(
        node: UiNode,
        filteredNodes: List<UiNode>,
        screenType: String?
    ): Boolean {
        if (isUnsafeBusinessActionNode(node, filteredNodes)) return false
        if (!isPopupCloseText(node.searchableText())) return false
        return hasPopupDismissPositiveEvidence(node, filteredNodes, screenType) &&
            hasClickableDismissPath(node)
    }

    fun isNotificationOptInDeclineCandidate(
        node: UiNode,
        filteredNodes: List<UiNode>
    ): Boolean {
        if (isUnsafeBusinessActionNode(node, filteredNodes)) return false
        val combinedText = filteredNodes.joinToString(" ") { nearbyNode -> nearbyNode.searchableText() }
        return containsAnyNormalized(combinedText, notificationOptInContextKeywords) &&
            containsAnyNormalized(node.searchableText(), notificationOptInDeclineKeywords) &&
            hasClickableDismissPath(node)
    }

    fun isUnsafeBusinessActionNode(node: UiNode?, filteredNodes: List<UiNode> = emptyList()): Boolean {
        if (node == null) return false
        if (isUnsafeBusinessActionText(node.searchableText())) return true
        val nearbyText = filteredNodes
            .filter { nearbyNode -> kotlin.math.abs(nearbyNode.centerY - node.centerY) <= 120 }
            .joinToString(" ") { nearbyNode -> nearbyNode.searchableText() }
        return isUnsafeBusinessActionText(nearbyText)
    }

    fun isUnsafeBusinessActionText(text: String): Boolean {
        return containsAnyNormalized(text, unsafeBusinessActionKeywords)
    }

    fun isRecoveryAction(actionPlan: ActionPlan): Boolean {
        return actionPlan.reasonCode == RuleReasonCode.POPUP_DISMISS.value ||
            actionPlan.reasonCode.startsWith("vlm") ||
            actionPlan.reasonCode.contains("recovery")
    }

    private fun isExecutableClick(actionPlan: ActionPlan): Boolean {
        return actionPlan.actionType == AutomationActionType.CLICK.value
    }

    private fun containsSafePopupDismissText(text: String): Boolean {
        val normalizedText = normalize(text)
        if (normalizedText in setOf("x", "×")) return true
        if (normalizedText.replace(" ", "") in setOf("닫기x", "닫기×")) return true
        if (normalizedText == "취소" || normalizedText.contains(" 취소")) return false
        return containsAnyNormalized(text, safePopupDismissKeywords)
    }

    private fun hasClickableDismissPath(node: UiNode): Boolean {
        if (node.clickable || node.role == "button") return true

        // 일부 WebView/인앱 메시지 팝업은 "닫기X" 텍스트 노드 자체는 clickable=false지만
        // AccessibilityNodeInfo 부모에 클릭 액션이 붙는다. 실행기는 부모 클릭을 지원하므로
        // 정책도 같은 범위까지 안전한 닫기 후보로 인정한다.
        var parentNode = node.sourceNode?.parent
        var depth = 0
        while (parentNode != null && depth < 4) {
            if (parentNode.isClickable) return true
            parentNode = parentNode.parent
            depth += 1
        }
        return false
    }

    private fun hasPopupDismissPositiveEvidence(
        node: UiNode,
        filteredNodes: List<UiNode>,
        screenType: String?
    ): Boolean {
        val text = node.searchableText()
        val isCloseIcon = isPopupCloseText(text)
        val isNearTopCloseButton = isCloseIcon && node.centerY <= 700
        val hasPopupContextText = containsAnyNormalized(
            filteredNodes.joinToString(" ") { nearbyNode -> nearbyNode.searchableText() },
            popupContextKeywords
        )
        val isDismissDurationText = isDoNotShowAgainPopupOption(node)
        return isNearTopCloseButton ||
            isDismissDurationText ||
            hasPopupContextText ||
            screenType == "popup" ||
            screenType == "overlay" ||
            screenType == "dialog"
    }

    private fun hasSeparatePopupCloseCandidate(
        optionNode: UiNode,
        filteredNodes: List<UiNode>,
        screenType: String?
    ): Boolean {
        return filteredNodes.any { candidateNode ->
            candidateNode.id != optionNode.id &&
                !isUnsafeBusinessActionNode(candidateNode, filteredNodes) &&
                isPopupCloseText(candidateNode.searchableText()) &&
                hasClickableDismissPath(candidateNode) &&
                hasPopupDismissPositiveEvidence(candidateNode, filteredNodes, screenType)
        }
    }

    private fun isPopupCloseText(text: String): Boolean {
        val normalizedText = normalize(text)
        if (normalizedText in setOf("x", "×", "close", "닫기")) return true
        if (normalizedText.replace(" ", "") in setOf("닫기x", "닫기×")) return true
        return containsAnyNormalized(text, popupCloseKeywords)
    }

    private fun containsAnyNormalized(text: String, keywords: List<String>): Boolean {
        val normalizedText = normalize(text)
        if (normalizedText.isBlank()) return false
        val compactText = normalizedText.replace(" ", "")
        return keywords.any { keyword ->
            val normalizedKeyword = normalize(keyword)
            normalizedText.contains(normalizedKeyword) ||
                compactText.contains(normalizedKeyword.replace(" ", ""))
        }
    }

    private fun normalize(value: String): String {
        return value.lowercase()
            .replace(Regex("\\s+"), " ")
            .trim()
    }
}
