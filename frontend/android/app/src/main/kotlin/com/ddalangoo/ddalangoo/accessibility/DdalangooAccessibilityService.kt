package com.ddalangoo.ddalangoo.accessibility

import android.accessibilityservice.AccessibilityService
import android.os.Handler
import android.os.Looper
import android.view.accessibility.AccessibilityEvent

class DdalangooAccessibilityService : AccessibilityService() {
    companion object {
        private var activeService: DdalangooAccessibilityService? = null

        fun scheduleTaskStartedTicks() {
            activeService?.scheduleTaskStartedTicks()
                ?: AutomationLogger.warn("task tick skipped reason=service_not_active")
        }
    }

    private val uiTreeCollector = UiTreeCollector()
    private val uiNodeSerializer = UiNodeSerializer()
    private val ruleBasedPlanner = RuleBasedPlanner()
    private val kurlyPurchaseHistoryExtractor = KurlyPurchaseHistoryExtractor()
    private val coupangPurchaseHistoryExtractor = CoupangPurchaseHistoryExtractor()
    private val handler = Handler(Looper.getMainLooper())
    private lateinit var actionExecutor: ActionExecutor

    override fun onServiceConnected() {
        super.onServiceConnected()
        activeService = this
        actionExecutor = ActionExecutor(this)
        AutomationTaskStore.markServiceConnected()
        AutomationLogger.info("service connected rootAvailable=${rootInActiveWindow != null}")
    }

    override fun onAccessibilityEvent(event: AccessibilityEvent?) {
        val eventType = event?.eventType ?: return
        val eventPackageName = event.packageName?.toString()
        AutomationLogger.debug("event type=$eventType packageName=${eventPackageName.orEmpty()}")
        processCurrentRoot(trigger = "event", packageNameOverride = eventPackageName)
    }

    fun processCurrentRoot(trigger: String) {
        processCurrentRoot(trigger = trigger, packageNameOverride = null)
    }

    private fun processCurrentRoot(trigger: String, packageNameOverride: String?) {
        AutomationLogger.info("processCurrentRoot trigger=$trigger")
        val rootNode = rootInActiveWindow
        if (rootNode == null) {
            AutomationLogger.warn("rootInActiveWindow unavailable trigger=$trigger")
            scheduleProcessTick(1000L, "root_unavailable")
            return
        }

        val currentPackageName = packageNameOverride ?: rootNode.packageName?.toString()
        val rawNodes = uiTreeCollector.collect(rootNode)
        val filteredNodes = uiNodeSerializer.filter(rawNodes)
        AutomationLogger.info("ui_tree filteredNodeCount=${filteredNodes.size}")
        AutomationLogger.debug("filtered_nodes_json=${uiNodeSerializer.toJson(filteredNodes)}")

        // task가 없을 때는 자동 클릭/입력 없이 UI Tree 검증 로그만 남긴다.
        val task = AutomationTaskStore.getTask()
        if (task == null) {
            AutomationTaskStore.recordObservation(
                packageName = currentPackageName,
                currentStep = null,
                rawNodeCount = rawNodes.size,
                filteredNodeCount = filteredNodes.size,
                trigger = trigger
            )
            AutomationLogger.validation(
                platform = null,
                packageName = currentPackageName,
                currentStep = null,
                rawNodeCount = rawNodes.size,
                filteredNodeCount = filteredNodes.size,
                actionPlan = null,
                actionResult = null,
                selectedNode = null
            )
            return
        }

        if (!task.packageName.isNullOrBlank() && task.packageName != currentPackageName) {
            AutomationTaskStore.recordWaitingForPackage(
                packageName = currentPackageName,
                currentStep = task.currentStep,
                rawNodeCount = rawNodes.size,
                filteredNodeCount = filteredNodes.size,
                targetPackageName = task.packageName,
                trigger = trigger
            )
            AutomationLogger.debug(
                "task waiting targetPackage=${task.packageName} currentPackage=${currentPackageName.orEmpty()} " +
                    "currentStep=${task.currentStep} trigger=$trigger"
            )
            AutomationLogger.validation(
                platform = task.platform,
                packageName = currentPackageName,
                currentStep = task.currentStep,
                rawNodeCount = rawNodes.size,
                filteredNodeCount = filteredNodes.size,
                actionPlan = null,
                actionResult = null,
                selectedNode = null
            )
            scheduleProcessTick(1000L, "waiting_for_package")
            return
        }

        AutomationTaskStore.recordObservation(
            packageName = currentPackageName,
            currentStep = task.currentStep,
            rawNodeCount = rawNodes.size,
            filteredNodeCount = filteredNodes.size,
            trigger = trigger
        )

        if (shouldGuardKurlyOrderHistory(task) && !isKurlyOrderHistoryScreen(filteredNodes)) {
            val shouldRetry = AutomationTaskStore.recordWaitingForRetry(
                packageName = currentPackageName,
                currentStep = task.currentStep,
                rawNodeCount = rawNodes.size,
                filteredNodeCount = filteredNodes.size,
                trigger = trigger,
                reasonCode = "not_order_history_screen",
                message = "Waiting for Kurly order history screen"
            )
            AutomationLogger.validation(
                platform = task.platform,
                packageName = currentPackageName,
                currentStep = task.currentStep,
                rawNodeCount = rawNodes.size,
                filteredNodeCount = filteredNodes.size,
                actionPlan = null,
                actionResult = null,
                selectedNode = null
            )
            if (shouldRetry) {
                scheduleProcessTick(1000L, "waiting_order_history_screen")
            }
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
                packageName = task.packageName ?: currentPackageName,
                rawNodeCount = rawNodes.size,
                filteredNodeCount = filteredNodes.size,
                candidateNodes = findPurchaseHistoryCandidates(filteredNodes)
            )
            if (shouldExtractPurchaseHistory) {
                val mergeResult = PurchaseHistoryExtractionStore.merge(parsedPurchaseHistory)
                AutomationLogger.parsedPurchaseHistory(
                    platform = task.platform,
                    packageName = task.packageName ?: currentPackageName,
                    candidates = parsedPurchaseHistory
                )
                AutomationLogger.accumulatedPurchaseHistory(
                    platform = task.platform,
                    packageName = task.packageName ?: currentPackageName,
                    mergeResult = mergeResult
                )
                if (
                    task.currentStep == AutomationContract.Step.EXTRACT_PURCHASE_HISTORY &&
                    mergeResult.accumulatedOrderCount > 0 &&
                    mergeResult.newOrderCount == 0
                ) {
                    AutomationTaskStore.updateCurrentStep(AutomationContract.Step.FINISH_PURCHASE_HISTORY)
                }
            } else {
                AutomationLogger.accumulatedPurchaseHistoryFinal(
                    platform = task.platform,
                    packageName = task.packageName ?: currentPackageName,
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
        AutomationTaskStore.recordAction(actionPlan, actionResult, selectedNode)

        if (actionPlan.actionType == AutomationActionType.STOP_FOR_SENSITIVE_SCREEN.value) {
            AutomationTaskStore.clearTask()
        } else if (actionResult.success && AutomationTaskStore.getTask()?.currentStep == task.currentStep) {
            AutomationTaskStore.advanceAfterSuccess(actionPlan)
            scheduleAfterSuccessfulAction(actionPlan)
        }

        AutomationLogger.validation(
            platform = task.platform,
            packageName = task.packageName ?: currentPackageName,
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

    override fun onDestroy() {
        if (activeService === this) {
            activeService = null
        }
        handler.removeCallbacksAndMessages(null)
        super.onDestroy()
    }

    private fun scheduleTaskStartedTicks() {
        scheduleProcessTick(700L, "task_started")
        scheduleProcessTick(1700L, "task_started_retry_1")
        scheduleProcessTick(3000L, "task_started_retry_2")
    }

    private fun scheduleAfterSuccessfulAction(actionPlan: ActionPlan) {
        when (actionPlan.reasonCode) {
            RuleReasonCode.MY_KURLY.value,
            RuleReasonCode.MY_COUPANG.value,
            RuleReasonCode.ORDER_HISTORY.value -> scheduleProcessTick(900L, "after_navigation")
            RuleReasonCode.PURCHASE_HISTORY_SCROLL.value -> scheduleProcessTick(900L, "after_scroll")
            RuleReasonCode.PURCHASE_HISTORY_DUMP.value -> scheduleProcessTick(700L, "after_dump")
        }
    }

    private fun scheduleProcessTick(delayMs: Long, reason: String) {
        AutomationLogger.info("scheduleProcessTick delayMs=$delayMs reason=$reason")
        handler.postDelayed({
            processCurrentRoot("tick:$reason")
        }, delayMs)
    }

    private fun shouldGuardKurlyOrderHistory(task: AutomationTask): Boolean {
        if (task.platform != AutomationContract.Platform.KURLY) return false
        return task.currentStep == AutomationContract.Step.DUMP_PURCHASE_HISTORY ||
            task.currentStep == AutomationContract.Step.EXTRACT_PURCHASE_HISTORY ||
            task.currentStep == AutomationContract.Step.SCROLL_PURCHASE_HISTORY
    }

    private fun isKurlyOrderHistoryScreen(filteredNodes: List<UiNode>): Boolean {
        val hasOrderHistoryTitle = filteredNodes.any { node ->
            node.searchableText().contains("주문 내역")
        }
        val hasOrderContent = filteredNodes.any { node ->
            val text = node.searchableText()
            text.contains("주문번호") || text.contains("배송완료")
        }
        return hasOrderHistoryTitle && hasOrderContent
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
