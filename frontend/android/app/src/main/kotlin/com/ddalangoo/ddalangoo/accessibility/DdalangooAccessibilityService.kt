package com.ddalangoo.ddalangoo.accessibility

import android.accessibilityservice.AccessibilityService
import android.os.Handler
import android.os.Looper
import android.view.accessibility.AccessibilityEvent

private enum class KurlyScreenType(val value: String) {
    ORDER_HISTORY("order_history"),
    MY_KURLY("my_kurly"),
    KURLY_HOME("kurly_home"),
    SEARCH_OR_PRODUCT_OR_CART("search_or_product_or_cart"),
    SENSITIVE("sensitive"),
    UNKNOWN("unknown")
}

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
    private var suppressExtractUntilMs: Long = 0L
    private var suppressOrderHistoryGuardUntilMs: Long = 0L
    private var suppressSearchResultDumpUntilMs: Long = 0L
    private val pendingTickReasons = mutableSetOf<String>()
    private val defaultSearchResultDumpLimit = 2
    private val targetSearchResultDumpLimit = 20
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
        val taskAtStart = AutomationTaskStore.getTask()
        if (taskAtStart?.currentStep == AutomationContract.Step.COMPLETED) {
            AutomationLogger.info("task_completed_ignore_event trigger=$trigger")
            AutomationTaskStore.recordCompletedIgnored(
                packageName = packageNameOverride ?: taskAtStart.packageName,
                rawNodeCount = 0,
                filteredNodeCount = 0,
                trigger = trigger
            )
            return
        }

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
        val task = taskAtStart
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

        if (task.currentStep == AutomationContract.Step.COMPLETED) {
            AutomationLogger.info("task_completed_ignore_event trigger=$trigger")
            AutomationTaskStore.recordCompletedIgnored(
                packageName = currentPackageName,
                rawNodeCount = rawNodes.size,
                filteredNodeCount = filteredNodes.size,
                trigger = trigger
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

        if (task.taskType == AutomationContract.TaskType.INSPECT_SEARCH_FLOW) {
            if (!isSearchInspectionScreenReady(rawNodes.size, filteredNodes.size)) {
                val shouldRetry = AutomationTaskStore.recordWaitingForRetry(
                    packageName = currentPackageName,
                    currentStep = task.currentStep,
                    rawNodeCount = rawNodes.size,
                    filteredNodeCount = filteredNodes.size,
                    trigger = trigger,
                    reasonCode = "search_inspection_screen_not_ready",
                    message = "Waiting for Kurly screen to expose enough accessibility nodes"
                )
                if (shouldRetry) {
                    scheduleProcessTick(900L, "waiting_search_inspection_screen")
                }
                return
            }
            val snapshot = SearchInspectionStore.inspect(
                step = task.currentStep,
                rawNodeCount = rawNodes.size,
                filteredNodes = filteredNodes
            )
            AutomationLogger.searchInspectionDump(
                packageName = task.packageName ?: currentPackageName,
                snapshot = snapshot
            )
            AutomationTaskStore.markCompleted(
                trigger = trigger,
                message = "Search inspection completed for step=${task.currentStep}"
            )
            return
        }

        if (task.currentStep == AutomationContract.Step.FINISH_PURCHASE_HISTORY) {
            if (AutomationTaskStore.markPurchaseHistoryFinishHandledIfNeeded()) {
                AutomationLogger.accumulatedPurchaseHistoryFinal(
                    platform = task.platform,
                    packageName = task.packageName ?: currentPackageName,
                    accumulatedCandidates = PurchaseHistoryExtractionStore.accumulatedCandidates()
                )
            }
            AutomationTaskStore.markCompleted(
                trigger = trigger,
                message = "Purchase history collection completed"
            )
            return
        }

        if (shouldDelayExtractAfterScroll(task, trigger)) {
            AutomationLogger.info(
                "skip early extract after scroll trigger=$trigger currentStep=${task.currentStep}"
            )
            return
        }

        if (normalizeKurlyPurchaseHistoryStart(
                task = task,
                currentPackageName = currentPackageName,
                rawNodeCount = rawNodes.size,
                filteredNodes = filteredNodes,
                trigger = trigger
            )
        ) {
            return
        }

        if (shouldGuardKurlyOrderHistory(task) && !isKurlyOrderHistoryScreen(filteredNodes)) {
            if (shouldDelayOrderHistoryGuard(task)) {
                AutomationLogger.info(
                    "skip order history guard during navigation settle currentStep=${task.currentStep} trigger=$trigger"
                )
                return
            }
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
        if (actionPlan.actionType == AutomationActionType.DUMP_SEARCH_RESULTS.value) {
            if (shouldDelaySearchResultDumpAfterSubmit(task)) {
                AutomationLogger.info(
                    "skip early search result dump currentStep=${task.currentStep} trigger=$trigger"
                )
                scheduleProcessTick(500L, "waiting_search_result_settle")
                return
            }
            if (!isKurlySearchResultsScreenReady(filteredNodes)) {
                val shouldRetry = AutomationTaskStore.recordWaitingForRetry(
                    packageName = currentPackageName,
                    currentStep = task.currentStep,
                    rawNodeCount = rawNodes.size,
                    filteredNodeCount = filteredNodes.size,
                    trigger = trigger,
                    reasonCode = "search_results_not_ready",
                    message = "Waiting for Kurly search results to expose product nodes"
                )
                if (shouldRetry) {
                    if (shouldRetrySearchSubmitAfterResultWait()) {
                        AutomationLogger.info(
                            "search submit appears ineffective. retrying submit " +
                                "currentStep=${task.currentStep} trigger=$trigger"
                        )
                        AutomationTaskStore.updateCurrentStep(AutomationContract.Step.SEARCH_SUBMIT)
                        scheduleProcessTick(600L, "retry_search_submit")
                    } else {
                        scheduleProcessTick(900L, "waiting_search_results")
                    }
                } else {
                    AutomationTaskStore.stopTask(
                        packageName = currentPackageName,
                        currentStep = task.currentStep,
                        rawNodeCount = rawNodes.size,
                        filteredNodeCount = filteredNodes.size,
                        trigger = trigger,
                        screenType = "search_results_not_ready",
                        reasonCode = "search_submit_not_effective",
                        message = "Search submit did not expose product results after retries"
                    )
                }
                return
            }
            val snapshot = SearchInspectionStore.inspect(
                step = AutomationContract.Step.DUMP_SEARCH_RESULTS,
                rawNodeCount = rawNodes.size,
                filteredNodes = filteredNodes
            )
            AutomationLogger.searchInspectionDump(
                packageName = task.packageName ?: currentPackageName,
                snapshot = snapshot
            )
            val isTargetSearch = isExplicitTargetSearch(task)
            val matchedTargetCandidate = if (isTargetSearch) {
                SearchInspectionStore.matchedProductCandidate(task.targetProductName)
            } else {
                null
            }
            val searchResultDumpLimit = if (isTargetSearch) {
                targetSearchResultDumpLimit
            } else {
                defaultSearchResultDumpLimit
            }
            if (matchedTargetCandidate != null) {
                AutomationLogger.info(
                    "target_product_found productName=${matchedTargetCandidate.productName.orEmpty()} " +
                        "nextStep=${AutomationContract.Step.SELECT_PRODUCT}"
                )
                AutomationTaskStore.updateCurrentStep(AutomationContract.Step.SELECT_PRODUCT)
                scheduleProcessTick(500L, "after_target_product_found")
            } else if (SearchInspectionStore.searchResultDumpCount() >= searchResultDumpLimit) {
                if (isTargetSearch) {
                    AutomationTaskStore.stopTask(
                        packageName = currentPackageName,
                        currentStep = task.currentStep,
                        rawNodeCount = rawNodes.size,
                        filteredNodeCount = filteredNodes.size,
                        trigger = trigger,
                        screenType = "search_results",
                        reasonCode = "target_product_not_found",
                        message = "Target product not found after $searchResultDumpLimit dumps " +
                            "targetProductName=${task.targetProductName}"
                    )
                } else {
                    AutomationTaskStore.markCompleted(
                        trigger = trigger,
                        message = "Search result collection completed " +
                            "accumulatedProductCandidateCount=${SearchInspectionStore.accumulatedProductCandidateCount()}"
                    )
                }
            } else {
                AutomationTaskStore.updateCurrentStep(AutomationContract.Step.SCROLL_SEARCH_RESULTS)
                scheduleProcessTick(700L, "after_search_result_dump")
            }
            return
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
                    mergeResult.currentExtractCount > 0 &&
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

    private fun isExplicitTargetSearch(task: AutomationTask): Boolean {
        val normalizedSearchKeyword = normalizeSearchTarget(task.searchKeyword)
        val normalizedTargetProductName = normalizeSearchTarget(task.targetProductName)
        return normalizedSearchKeyword.isNotBlank() &&
            normalizedTargetProductName.isNotBlank() &&
            normalizedSearchKeyword != normalizedTargetProductName
    }

    private fun normalizeSearchTarget(value: String): String {
        return value
            .lowercase()
            .replace(Regex("[^0-9a-z가-힣]+"), " ")
            .replace(Regex("\\s+"), " ")
            .trim()
    }

    override fun onInterrupt() {
        AutomationLogger.warn("service interrupted")
    }

    override fun onDestroy() {
        if (activeService === this) {
            activeService = null
        }
        pendingTickReasons.clear()
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
            RuleReasonCode.MY_COUPANG.value -> scheduleProcessTick(900L, "after_navigation")
            RuleReasonCode.ORDER_HISTORY.value -> {
                // 주문내역 진입 직후 로딩 이벤트가 retry count를 빨리 소모하지 않도록 잠깐 기다린다.
                suppressOrderHistoryGuardUntilMs = System.currentTimeMillis() + 1200L
                scheduleProcessTick(1200L, "after_order_history_navigation")
            }
            RuleReasonCode.PURCHASE_HISTORY_SCROLL.value -> {
                suppressExtractUntilMs = System.currentTimeMillis() + 850L
                scheduleProcessTick(900L, "after_scroll")
            }
            RuleReasonCode.PURCHASE_HISTORY_DUMP.value -> scheduleProcessTick(700L, "after_dump")
            RuleReasonCode.SEARCH_ENTRY.value -> scheduleProcessTick(900L, "after_search_entry")
            RuleReasonCode.SEARCH_INPUT_FOCUS_RETRY.value -> scheduleProcessTick(500L, "search_input_focus_retry")
            RuleReasonCode.SEARCH_INPUT.value -> scheduleProcessTick(700L, "after_search_input")
            RuleReasonCode.SEARCH_BUTTON.value,
            RuleReasonCode.KEYBOARD_SEARCH.value -> {
                suppressSearchResultDumpUntilMs = System.currentTimeMillis() + 1400L
                scheduleProcessTick(1400L, "after_search_submit")
            }
            RuleReasonCode.SEARCH_RESULT_SCROLL.value -> {
                suppressSearchResultDumpUntilMs = System.currentTimeMillis() + 900L
                scheduleProcessTick(900L, "after_search_result_scroll")
            }
            RuleReasonCode.PRODUCT_CARD.value -> scheduleProcessTick(1200L, "after_product_card")
            RuleReasonCode.CART_BUTTON.value -> scheduleProcessTick(900L, "after_cart_button")
            RuleReasonCode.OPTION_ADD.value -> scheduleProcessTick(700L, "after_option_add")
        }
    }

    private fun scheduleProcessTick(delayMs: Long, reason: String) {
        if (!pendingTickReasons.add(reason)) {
            AutomationLogger.info("scheduleProcessTick skipped duplicate reason=$reason")
            return
        }
        AutomationLogger.info("scheduleProcessTick delayMs=$delayMs reason=$reason")
        handler.postDelayed({
            pendingTickReasons.remove(reason)
            processCurrentRoot("tick:$reason")
        }, delayMs)
    }

    private fun shouldGuardKurlyOrderHistory(task: AutomationTask): Boolean {
        if (task.platform != AutomationContract.Platform.KURLY) return false
        return task.currentStep == AutomationContract.Step.DUMP_PURCHASE_HISTORY ||
            task.currentStep == AutomationContract.Step.EXTRACT_PURCHASE_HISTORY ||
            task.currentStep == AutomationContract.Step.SCROLL_PURCHASE_HISTORY
    }

    private fun shouldDelayExtractAfterScroll(task: AutomationTask, trigger: String): Boolean {
        return task.currentStep == AutomationContract.Step.EXTRACT_PURCHASE_HISTORY &&
            trigger == "event" &&
            System.currentTimeMillis() < suppressExtractUntilMs
    }

    private fun shouldDelayOrderHistoryGuard(task: AutomationTask): Boolean {
        return task.currentStep == AutomationContract.Step.DUMP_PURCHASE_HISTORY &&
            System.currentTimeMillis() < suppressOrderHistoryGuardUntilMs
    }

    private fun shouldDelaySearchResultDumpAfterSubmit(task: AutomationTask): Boolean {
        return task.currentStep == AutomationContract.Step.DUMP_SEARCH_RESULTS &&
            System.currentTimeMillis() < suppressSearchResultDumpUntilMs
    }

    private fun isKurlySearchResultsScreenReady(filteredNodes: List<UiNode>): Boolean {
        val hasProductAction = containsAnyText(filteredNodes, listOf("담기", "장바구니"))
        val hasPriceText = filteredNodes.any { node ->
            Regex("""\d[\d,]*\s*원""").containsMatchIn(node.primaryText())
        }
        val hasResultSortOrTab = containsAnyText(filteredNodes, listOf("추천순", "인기순", "상품", "가격"))
        return (hasProductAction && hasPriceText) || (hasResultSortOrTab && hasPriceText)
    }

    private fun shouldRetrySearchSubmitAfterResultWait(): Boolean {
        val resultWaitRetryCount = AutomationTaskStore.currentRetryCountForStep(
            AutomationContract.Step.DUMP_SEARCH_RESULTS
        )
        return resultWaitRetryCount >= 2 && AutomationTaskStore.tryReserveSearchSubmitRetry()
    }

    private fun isSearchInspectionScreenReady(rawNodeCount: Int, filteredNodeCount: Int): Boolean {
        return rawNodeCount >= 10 && filteredNodeCount >= 4
    }

    private fun normalizeKurlyPurchaseHistoryStart(
        task: AutomationTask,
        currentPackageName: String?,
        rawNodeCount: Int,
        filteredNodes: List<UiNode>,
        trigger: String
    ): Boolean {
        if (!shouldNormalizeKurlyPurchaseHistory(task)) return false

        val screenType = classifyKurlyScreen(filteredNodes)
        AutomationTaskStore.recordScreenClassification(screenType.value, trigger)
        AutomationLogger.info(
            "kurly screen classification screenType=${screenType.value} " +
                "currentStep=${task.currentStep} trigger=$trigger"
        )

        when (screenType) {
            KurlyScreenType.SENSITIVE -> {
                AutomationLogger.warn("sensitive Kurly screen detected during normalization")
                AutomationTaskStore.stopTask(
                    packageName = currentPackageName,
                    currentStep = task.currentStep,
                    rawNodeCount = rawNodeCount,
                    filteredNodeCount = filteredNodes.size,
                    trigger = trigger,
                    screenType = screenType.value,
                    reasonCode = "sensitive_screen",
                    message = "Sensitive Kurly screen detected. Automation stopped."
                )
                return true
            }
            KurlyScreenType.ORDER_HISTORY -> {
                if (shouldResetKurlyOrderHistoryResume(task)) {
                    val success = performGlobalAction(GLOBAL_ACTION_BACK)
                    AutomationLogger.info(
                        "kurly order history resumed. reset by back navigation " +
                            "currentStep=${task.currentStep} trigger=$trigger success=$success"
                    )
                    AutomationTaskStore.updateCurrentStep(AutomationContract.Step.OPEN_ORDER_HISTORY)
                    scheduleProcessTick(900L, "reset_order_history_resume")
                    return true
                }
                return false
            }
            KurlyScreenType.MY_KURLY -> {
                if (task.currentStep != AutomationContract.Step.OPEN_ORDER_HISTORY) {
                    AutomationLogger.info(
                        "kurly my page visible. " +
                            "normalize currentStep=${task.currentStep} nextStep=${AutomationContract.Step.OPEN_ORDER_HISTORY}"
                    )
                    AutomationTaskStore.updateCurrentStep(AutomationContract.Step.OPEN_ORDER_HISTORY)
                    scheduleProcessTick(100L, "normalized_my_kurly")
                    return true
                }
                return false
            }
            KurlyScreenType.KURLY_HOME -> {
                if (task.currentStep != AutomationContract.Step.OPEN_MY_KURLY) {
                    AutomationLogger.info(
                        "kurly home visible. " +
                            "normalize currentStep=${task.currentStep} nextStep=${AutomationContract.Step.OPEN_MY_KURLY}"
                    )
                    AutomationTaskStore.updateCurrentStep(AutomationContract.Step.OPEN_MY_KURLY)
                    scheduleProcessTick(100L, "normalized_kurly_home")
                    return true
                }
                return false
            }
            KurlyScreenType.SEARCH_OR_PRODUCT_OR_CART -> {
                if (shouldWaitForKurlyOrderHistoryContent(task)) {
                    AutomationLogger.info(
                        "kurly unexpected screen ignored while waiting for order history. " +
                            "currentStep=${task.currentStep} trigger=$trigger"
                    )
                    return false
                }
                val success = performGlobalAction(GLOBAL_ACTION_BACK)
                val shouldContinue = AutomationTaskStore.recordRecoveryAttempt(
                    packageName = currentPackageName,
                    currentStep = task.currentStep,
                    rawNodeCount = rawNodeCount,
                    filteredNodeCount = filteredNodes.size,
                    trigger = trigger,
                    screenType = screenType.value,
                    success = success
                )
                if (shouldContinue) {
                    scheduleProcessTick(900L, "recover_from_unexpected_screen")
                } else {
                    AutomationTaskStore.stopTask(
                        packageName = currentPackageName,
                        currentStep = task.currentStep,
                        rawNodeCount = rawNodeCount,
                        filteredNodeCount = filteredNodes.size,
                        trigger = trigger,
                        screenType = screenType.value,
                        reasonCode = "recovery_limit_exceeded",
                        message = "Recovery limit exceeded for unexpected Kurly screen"
                    )
                }
                return true
            }
            KurlyScreenType.UNKNOWN -> return false
        }
    }

    private fun shouldResetKurlyOrderHistoryResume(task: AutomationTask): Boolean {
        return task.currentStep == AutomationContract.Step.OPEN_MY_KURLY ||
            task.currentStep == AutomationContract.Step.OPEN_ORDER_HISTORY
    }

    private fun shouldWaitForKurlyOrderHistoryContent(task: AutomationTask): Boolean {
        return task.currentStep == AutomationContract.Step.DUMP_PURCHASE_HISTORY ||
            task.currentStep == AutomationContract.Step.EXTRACT_PURCHASE_HISTORY ||
            task.currentStep == AutomationContract.Step.SCROLL_PURCHASE_HISTORY
    }

    private fun shouldNormalizeKurlyPurchaseHistory(task: AutomationTask): Boolean {
        if (task.platform != AutomationContract.Platform.KURLY) return false
        return task.currentStep == AutomationContract.Step.OPEN_MY_KURLY ||
            task.currentStep == AutomationContract.Step.OPEN_ORDER_HISTORY ||
            task.currentStep == AutomationContract.Step.DUMP_PURCHASE_HISTORY ||
            task.currentStep == AutomationContract.Step.EXTRACT_PURCHASE_HISTORY ||
            task.currentStep == AutomationContract.Step.SCROLL_PURCHASE_HISTORY
    }

    private fun classifyKurlyScreen(filteredNodes: List<UiNode>): KurlyScreenType {
        if (containsAnyText(filteredNodes, sensitiveKeywords())) {
            return KurlyScreenType.SENSITIVE
        }
        if (isKurlyOrderHistoryScreen(filteredNodes)) {
            return KurlyScreenType.ORDER_HISTORY
        }
        if (isKurlyHomeScreen(filteredNodes)) {
            return KurlyScreenType.KURLY_HOME
        }
        if (isKurlyMyPageScreen(filteredNodes)) {
            return KurlyScreenType.MY_KURLY
        }
        if (isKurlySearchProductOrCartScreen(filteredNodes)) {
            return KurlyScreenType.SEARCH_OR_PRODUCT_OR_CART
        }
        return KurlyScreenType.UNKNOWN
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

    private fun isKurlyMyPageScreen(filteredNodes: List<UiNode>): Boolean {
        val hasMyPageGreeting = containsAnyText(filteredNodes, listOf("반가워요"))
        val hasMyPageAccountInfo = containsAnyText(filteredNodes, listOf("적립금", "컬리캐시", "매일혜택 포인트"))
        val hasMyPageAction = containsAnyText(filteredNodes, listOf("주문 내역", "배송지 관리", "찜", "후기"))
        return hasMyPageGreeting || (hasMyPageAccountInfo && hasMyPageAction)
    }

    private fun isKurlyHomeScreen(filteredNodes: List<UiNode>): Boolean {
        val hasKurlyTab = containsAnyText(filteredNodes, listOf("마켓컬리", "뷰티컬리"))
        val hasBottomNavigation = containsAnyText(filteredNodes, listOf("홈", "카테고리", "검색", "마이컬리"))
        val hasHomeContent = containsAnyText(filteredNodes, listOf("컬리추천", "베스트", "알뜰쇼핑", "특가", "페스타"))
        return hasKurlyTab && hasBottomNavigation && hasHomeContent
    }

    private fun isKurlySearchProductOrCartScreen(filteredNodes: List<UiNode>): Boolean {
        return containsAnyText(
            filteredNodes,
            listOf(
                "담기",
                "장바구니",
                "상품상세",
                "상품 설명",
                "후기",
                "추천순",
                "인기순",
                "결제하기",
                "상품명으로 검색"
            )
        )
    }

    private fun containsAnyText(filteredNodes: List<UiNode>, keywords: List<String>): Boolean {
        return filteredNodes.any { node ->
            val text = node.searchableText()
            keywords.any { keyword -> text.contains(keyword) }
        }
    }

    private fun sensitiveKeywords(): List<String> {
        return listOf(
            "로그인",
            "비밀번호",
            "결제 비밀번호",
            "본인인증",
            "인증번호",
            "카드번호",
            "cvc",
            "CVC",
            "주민등록번호",
            "생체인증",
            "공동인증서"
        )
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
