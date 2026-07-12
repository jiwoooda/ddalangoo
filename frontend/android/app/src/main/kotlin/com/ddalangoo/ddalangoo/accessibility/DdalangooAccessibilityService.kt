package com.ddalangoo.ddalangoo.accessibility

import android.accessibilityservice.AccessibilityService
import android.view.accessibility.AccessibilityEvent

class DdalangooAccessibilityService : AccessibilityService() {
    private val uiTreeCollector = UiTreeCollector()
    private val uiNodeSerializer = UiNodeSerializer()
    private val ruleBasedPlanner = RuleBasedPlanner()
    private val kurlyPurchaseHistoryExtractor = KurlyPurchaseHistoryExtractor()
    private val coupangPurchaseHistoryExtractor = CoupangPurchaseHistoryExtractor()
    private lateinit var actionExecutor: ActionExecutor

    override fun onServiceConnected() {
        super.onServiceConnected()
        actionExecutor = ActionExecutor(this)
        AutomationLogger.info("service connected rootAvailable=${rootInActiveWindow != null}")
    }

    override fun onAccessibilityEvent(event: AccessibilityEvent?) {
        val eventType = event?.eventType ?: return
        val eventPackageName = event.packageName?.toString()
        AutomationLogger.debug("event type=$eventType packageName=${eventPackageName.orEmpty()}")

        val rootNode = rootInActiveWindow
        if (rootNode == null) {
            AutomationLogger.warn("rootInActiveWindow unavailable")
            return
        }

        val rawNodes = uiTreeCollector.collect(rootNode)
        val filteredNodes = uiNodeSerializer.filter(rawNodes)
        AutomationLogger.info("ui_tree filteredNodeCount=${filteredNodes.size}")
        AutomationLogger.debug("filtered_nodes_json=${uiNodeSerializer.toJson(filteredNodes)}")

        // task가 없을 때는 자동 클릭/입력 없이 UI Tree 검증 로그만 남긴다.
        val task = AutomationTaskStore.getTask()
        if (task == null) {
            AutomationLogger.validation(
                platform = null,
                packageName = eventPackageName,
                currentStep = null,
                rawNodeCount = rawNodes.size,
                filteredNodeCount = filteredNodes.size,
                actionPlan = null,
                actionResult = null,
                selectedNode = null
            )
            return
        }

        if (!task.packageName.isNullOrBlank() && task.packageName != eventPackageName) {
            AutomationLogger.debug(
                "task waiting targetPackage=${task.packageName} currentPackage=${eventPackageName.orEmpty()} " +
                    "currentStep=${task.currentStep}"
            )
            AutomationLogger.validation(
                platform = task.platform,
                packageName = eventPackageName,
                currentStep = task.currentStep,
                rawNodeCount = rawNodes.size,
                filteredNodeCount = filteredNodes.size,
                actionPlan = null,
                actionResult = null,
                selectedNode = null
            )
            return
        }

        val actionPlan = ruleBasedPlanner.plan(filteredNodes, task)
        val selectedNode = actionPlan.targetNodeId?.let { targetNodeId ->
            filteredNodes.firstOrNull { node -> node.id == targetNodeId }
        }
        if (actionPlan.actionType == AutomationActionType.DUMP_PURCHASE_HISTORY.value) {
            val shouldExtractPurchaseHistory = actionPlan.reasonCode != RuleReasonCode.PURCHASE_HISTORY_FINISH.value
            val parsedPurchaseHistory = if (shouldExtractPurchaseHistory) {
                purchaseHistoryExtractorFor(task.platform).extract(filteredNodes)
            } else {
                emptyList()
            }
            AutomationLogger.purchaseHistoryDump(
                packageName = task.packageName ?: eventPackageName,
                rawNodeCount = rawNodes.size,
                filteredNodeCount = filteredNodes.size,
                candidateNodes = findPurchaseHistoryCandidates(filteredNodes)
            )
            if (shouldExtractPurchaseHistory) {
                val mergeResult = PurchaseHistoryExtractionStore.merge(parsedPurchaseHistory)
                AutomationLogger.parsedPurchaseHistory(
                    platform = task.platform,
                    packageName = task.packageName ?: eventPackageName,
                    candidates = parsedPurchaseHistory
                )
                AutomationLogger.accumulatedPurchaseHistory(
                    platform = task.platform,
                    packageName = task.packageName ?: eventPackageName,
                    mergeResult = mergeResult
                )
                if (
                    task.currentStep == AutomationContract.Step.EXTRACT_PURCHASE_HISTORY &&
                    mergeResult.newOrderCount == 0
                ) {
                    AutomationTaskStore.updateCurrentStep(AutomationContract.Step.FINISH_PURCHASE_HISTORY)
                }
            } else {
                AutomationLogger.accumulatedPurchaseHistoryFinal(
                    platform = task.platform,
                    packageName = task.packageName ?: eventPackageName,
                    accumulatedCandidates = PurchaseHistoryExtractionStore.accumulatedCandidates()
                )
            }
        }
        AutomationLogger.info(
            "plan actionType=${actionPlan.actionType} targetNodeId=${actionPlan.targetNodeId} " +
                "reasonCode=${actionPlan.reasonCode} confidence=${actionPlan.confidence}"
        )

        val actionResult = actionExecutor.execute(actionPlan, filteredNodes)
        AutomationLogger.info(
            "action_result success=${actionResult.success} method=${actionResult.method} " +
                "errorCode=${actionResult.errorCode.orEmpty()} message=${actionResult.message}"
        )

        if (actionPlan.actionType == AutomationActionType.STOP_FOR_SENSITIVE_SCREEN.value) {
            AutomationTaskStore.clearTask()
        } else if (actionResult.success && AutomationTaskStore.getTask()?.currentStep == task.currentStep) {
            AutomationTaskStore.advanceAfterSuccess(actionPlan)
        }

        AutomationLogger.validation(
            platform = task.platform,
            packageName = task.packageName ?: eventPackageName,
            currentStep = task.currentStep,
            rawNodeCount = rawNodes.size,
            filteredNodeCount = filteredNodes.size,
            actionPlan = actionPlan,
            actionResult = actionResult,
            selectedNode = selectedNode
        )
    }

    override fun onInterrupt() {
        AutomationLogger.warn("service interrupted")
    }

    private fun findPurchaseHistoryCandidates(filteredNodes: List<UiNode>): List<UiNode> {
        val purchaseHistoryKeywords = listOf(
            "주문",
            "주문일",
            "결제",
            "가격",
            "원",
            "재구매",
            "다시 구매",
            "배송조회",
            "배송",
            "배송완료",
            "배송 완료",
            "주문완료",
            "주문 완료",
            "결제완료",
            "결제 완료",
            "결제금액",
            "장바구니",
            "장바구니 담기",
            "재구매",
            "다시구매",
            "다시 구매",
            "담기"
        )

        return filteredNodes
            .filter { node ->
                val nodeText = node.searchableText()
                purchaseHistoryKeywords.any { keyword -> nodeText.contains(keyword.lowercase()) }
            }
            .take(80)
    }

    private fun purchaseHistoryExtractorFor(platform: String): PurchaseHistoryExtractor {
        return when (platform.lowercase()) {
            "kurly" -> kurlyPurchaseHistoryExtractor
            "coupang" -> coupangPurchaseHistoryExtractor
            else -> object : PurchaseHistoryExtractor {
                override fun extract(filteredNodes: List<UiNode>): List<PurchaseHistoryCandidate> {
                    return emptyList()
                }
            }
        }
    }
}
