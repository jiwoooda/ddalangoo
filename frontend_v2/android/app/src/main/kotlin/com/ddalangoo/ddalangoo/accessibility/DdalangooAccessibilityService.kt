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
    private var suppressSearchSubmitUntilMs: Long = 0L
    private var suppressSearchResultDumpUntilMs: Long = 0L
    private var suppressAddToCartResultUntilMs: Long = 0L
    private var suppressOrderHistoryScreenGuardUntilMs: Long = 0L
    private var lastPurchaseHistoryScrollFingerprint: String? = null
    private val purchaseHistoryPeriodFilterEnabled = false
    private val pendingTickReasons = mutableSetOf<String>()
    private val defaultSearchResultDumpLimit = 2
    private val targetSearchResultDumpLimit = 20
    private val purchaseHistoryNoProgressLimit = 10
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
            lastPurchaseHistoryScrollFingerprint = null
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

        if (
            task.platform == AutomationContract.Platform.KURLY &&
            task.currentStep == AutomationContract.Step.OPEN_MY_KURLY
        ) {
            lastPurchaseHistoryScrollFingerprint = null
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

        if (task.currentStep == AutomationContract.Step.WAIT_PRODUCT_DETAIL) {
            handleWaitProductDetail(
                task = task,
                currentPackageName = currentPackageName,
                rawNodeCount = rawNodes.size,
                filteredNodes = filteredNodes,
                trigger = trigger
            )
            return
        }

        if (task.currentStep == AutomationContract.Step.WAIT_OPTION_OR_CART_RESULT) {
            if (shouldDelayAddToCartResultAfterClick(task, trigger)) {
                AutomationLogger.info(
                    "skip early add-to-cart result classification currentStep=${task.currentStep} trigger=$trigger"
                )
                scheduleProcessTick(500L, "waiting_add_to_cart_result_settle")
                return
            }
            handleWaitOptionOrCartResult(
                task = task,
                currentPackageName = currentPackageName,
                rawNodeCount = rawNodes.size,
                filteredNodes = filteredNodes,
                trigger = trigger
            )
            return
        }

        if (task.currentStep == AutomationContract.Step.VERIFY_CART_ADDED) {
            handleVerifyCartAdded(
                task = task,
                currentPackageName = currentPackageName,
                rawNodeCount = rawNodes.size,
                filteredNodes = filteredNodes,
                trigger = trigger
            )
            return
        }

        if (task.currentStep == AutomationContract.Step.WAIT_OPTION_SELECTED) {
            handleWaitOptionSelected(
                task = task,
                currentPackageName = currentPackageName,
                rawNodeCount = rawNodes.size,
                filteredNodes = filteredNodes,
                trigger = trigger
            )
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

        if (shouldLogPurchaseHistoryScrollDiagnostic(task)) {
            logPurchaseHistoryScrollDiagnostic(
                task = task,
                trigger = trigger,
                rawNodeCount = rawNodes.size,
                filteredNodes = filteredNodes
            )
        }

        if (shouldDelaySearchSubmitAfterInput(task)) {
            AutomationLogger.info(
                "skip early search submit currentStep=${task.currentStep} trigger=$trigger"
            )
            scheduleProcessTick(700L, "waiting_search_input_settle")
            return
        }

        if (verifySearchInputBeforeSubmit(
                task = task,
                currentPackageName = currentPackageName,
                rawNodeCount = rawNodes.size,
                filteredNodes = filteredNodes,
                trigger = trigger
            )
        ) {
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
            if (handlePurchaseHistoryPeriodFilterIfNeeded(task, filteredNodes)) {
                return
            }
            val orderExpandSelection = findKurlyOrderExpandNodes(task, filteredNodes)
                .firstNotNullOfOrNull { node ->
                    val expandKey = purchaseHistoryExpandKey(node, filteredNodes)
                    if (AutomationTaskStore.tryReservePurchaseHistoryExpand(expandKey)) {
                        node to expandKey
                    } else {
                        null
                    }
                }
            if (orderExpandSelection != null) {
                val (orderExpandNode, orderExpandKey) = orderExpandSelection
                val expandPlan = ActionPlan(
                    actionType = AutomationActionType.CLICK.value,
                    targetNodeId = orderExpandNode.id,
                    textToInput = null,
                    reasonCode = RuleReasonCode.PURCHASE_HISTORY_EXPAND.value,
                    confidence = 0.86
                )
                val expandResult = actionExecutor.execute(expandPlan, filteredNodes)
                AutomationLogger.info(
                    "purchase_history_expand selectedNodeText=${orderExpandNode.primaryText()} " +
                        "key=$orderExpandKey success=${expandResult.success} method=${expandResult.method}"
                )
                AutomationTaskStore.recordAction(expandPlan, expandResult, orderExpandNode)
                scheduleProcessTick(900L, "after_purchase_history_expand")
                return
            }
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
                if (task.currentStep == AutomationContract.Step.EXTRACT_PURCHASE_HISTORY) {
                    val reachedEndOfPurchaseHistory =
                        mergeResult.accumulatedOrderCount > 0 &&
                            trigger == "tick:after_scroll" &&
                            mergeResult.noProgressExtractCount >= purchaseHistoryNoProgressLimit
                    if (reachedEndOfPurchaseHistory) {
                        finishPurchaseHistorySoon(
                            reason = "purchase_history_end_detected " +
                                "currentExtractCount=${mergeResult.currentExtractCount} " +
                                "newOrderCount=${mergeResult.newOrderCount} " +
                                "updatedOrderCount=${mergeResult.updatedOrderCount} " +
                                "noProgressExtractCount=${mergeResult.noProgressExtractCount} " +
                                "accumulatedOrderCount=${mergeResult.accumulatedOrderCount}"
                        )
                    }
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

        if (
            actionPlan.reasonCode == RuleReasonCode.PURCHASE_HISTORY_SCROLL.value &&
            !actionResult.success &&
            PurchaseHistoryExtractionStore.accumulatedCandidates().isNotEmpty()
        ) {
            finishPurchaseHistorySoon(
                reason = "purchase_history_scroll_unavailable " +
                    "errorCode=${actionResult.errorCode.orEmpty()}"
            )
        } else if (actionPlan.actionType == AutomationActionType.STOP_FOR_SENSITIVE_SCREEN.value) {
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
                suppressExtractUntilMs = System.currentTimeMillis() + 1200L
                suppressOrderHistoryScreenGuardUntilMs = System.currentTimeMillis() + 1600L
                scheduleProcessTick(1300L, "after_scroll")
            }
            RuleReasonCode.PURCHASE_HISTORY_DUMP.value -> scheduleProcessTick(700L, "after_dump")
            RuleReasonCode.SEARCH_ENTRY.value -> scheduleProcessTick(900L, "after_search_entry")
            RuleReasonCode.SEARCH_INPUT_FOCUS_RETRY.value -> scheduleProcessTick(500L, "search_input_focus_retry")
            RuleReasonCode.SEARCH_INPUT.value -> {
                suppressSearchSubmitUntilMs = System.currentTimeMillis() + 700L
                scheduleProcessTick(700L, "after_search_input")
            }
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
            RuleReasonCode.CART_BUTTON.value -> {
                suppressAddToCartResultUntilMs = System.currentTimeMillis() + 1000L
                scheduleProcessTick(1000L, "after_cart_button")
            }
            RuleReasonCode.OPTION_SELECT.value -> scheduleProcessTick(600L, "after_option_select")
            RuleReasonCode.OPTION_CONFIRM.value -> scheduleProcessTick(800L, "after_option_confirm")
            RuleReasonCode.OPTION_ADD.value -> scheduleProcessTick(700L, "after_option_add")
        }
    }

    private fun handleWaitProductDetail(
        task: AutomationTask,
        currentPackageName: String?,
        rawNodeCount: Int,
        filteredNodes: List<UiNode>,
        trigger: String
    ) {
        if (isProductDetailScreen(filteredNodes, task.targetProductName)) {
            AutomationLogger.info(
                "product_detail_ready targetProductName=${task.targetProductName} trigger=$trigger"
            )
            AutomationTaskStore.updateCurrentStep(AutomationContract.Step.CLICK_DETAIL_ADD_TO_CART)
            scheduleProcessTick(200L, "product_detail_ready")
            return
        }

        val shouldRetry = AutomationTaskStore.recordWaitingForRetry(
            packageName = currentPackageName,
            currentStep = task.currentStep,
            rawNodeCount = rawNodeCount,
            filteredNodeCount = filteredNodes.size,
            trigger = trigger,
            reasonCode = "product_detail_not_ready",
            message = "Waiting for Kurly product detail screen"
        )
        if (shouldRetry) {
            scheduleProcessTick(900L, "waiting_product_detail")
        } else {
            AutomationTaskStore.stopTask(
                packageName = currentPackageName,
                currentStep = task.currentStep,
                rawNodeCount = rawNodeCount,
                filteredNodeCount = filteredNodes.size,
                trigger = trigger,
                screenType = "product_detail_not_ready",
                reasonCode = "product_detail_not_ready",
                message = "Product detail screen was not detected after target click"
            )
        }
    }

    private fun handleWaitOptionOrCartResult(
        task: AutomationTask,
        currentPackageName: String?,
        rawNodeCount: Int,
        filteredNodes: List<UiNode>,
        trigger: String
    ) {
        when (val resultType = classifyAfterAddToCartClick(filteredNodes, task)) {
            "cart_added" -> {
                AutomationTaskStore.markCompleted(
                    trigger = trigger,
                    message = "Product added to cart"
                )
            }
            "option_required" -> {
                AutomationLogger.info("option_required optionName=${task.optionName} trigger=$trigger")
                AutomationTaskStore.updateCurrentStep(AutomationContract.Step.SELECT_OPTION)
                scheduleProcessTick(200L, "option_required")
            }
            "quantity_required" -> {
                AutomationLogger.info("quantity_required trigger=$trigger")
                AutomationTaskStore.updateCurrentStep(AutomationContract.Step.CONFIRM_OPTION_ADD_TO_CART)
                scheduleProcessTick(300L, "quantity_required")
            }
            "sold_out",
            "login_required",
            "sensitive_screen" -> {
                AutomationTaskStore.stopTask(
                    packageName = currentPackageName,
                    currentStep = task.currentStep,
                    rawNodeCount = rawNodeCount,
                    filteredNodeCount = filteredNodes.size,
                    trigger = trigger,
                    screenType = resultType,
                    reasonCode = resultType,
                    message = "Automation stopped after add-to-cart click: $resultType"
                )
            }
            else -> {
                val shouldRetry = AutomationTaskStore.recordWaitingForRetry(
                    packageName = currentPackageName,
                    currentStep = task.currentStep,
                    rawNodeCount = rawNodeCount,
                    filteredNodeCount = filteredNodes.size,
                    trigger = trigger,
                    reasonCode = "unknown_after_add_click",
                    message = "Waiting for option sheet or cart-added result"
                )
                if (shouldRetry) {
                    scheduleProcessTick(800L, "waiting_after_add_click")
                } else {
                    AutomationTaskStore.stopTask(
                        packageName = currentPackageName,
                        currentStep = task.currentStep,
                        rawNodeCount = rawNodeCount,
                        filteredNodeCount = filteredNodes.size,
                        trigger = trigger,
                        screenType = "unknown_after_add_click",
                        reasonCode = "unknown_after_add_click",
                        message = "Could not classify screen after add-to-cart click"
                    )
                }
            }
        }
    }

    private fun handleVerifyCartAdded(
        task: AutomationTask,
        currentPackageName: String?,
        rawNodeCount: Int,
        filteredNodes: List<UiNode>,
        trigger: String
    ) {
        val resultType = classifyAfterAddToCartClick(filteredNodes, task)
        if (resultType == "cart_added") {
            AutomationTaskStore.markCompleted(
                trigger = trigger,
                message = "Product option added to cart"
            )
            return
        }

        val shouldRetry = AutomationTaskStore.recordWaitingForRetry(
            packageName = currentPackageName,
            currentStep = task.currentStep,
            rawNodeCount = rawNodeCount,
            filteredNodeCount = filteredNodes.size,
            trigger = trigger,
            reasonCode = "cart_added_not_verified",
            message = "Waiting for cart-added confirmation"
        )
        if (shouldRetry) {
            scheduleProcessTick(800L, "waiting_cart_added")
        } else {
            AutomationTaskStore.stopTask(
                packageName = currentPackageName,
                currentStep = task.currentStep,
                rawNodeCount = rawNodeCount,
                filteredNodeCount = filteredNodes.size,
                trigger = trigger,
                screenType = "cart_added_not_verified",
                reasonCode = "cart_added_not_verified",
                message = "Cart-added confirmation was not detected"
            )
        }
    }

    private fun handleWaitOptionSelected(
        task: AutomationTask,
        currentPackageName: String?,
        rawNodeCount: Int,
        filteredNodes: List<UiNode>,
        trigger: String
    ) {
        val selectedQuantity = selectedOptionQuantity(filteredNodes, task.optionName)
        if (selectedQuantity != null && selectedQuantity > 0) {
            AutomationLogger.info(
                "option_selected optionName=${task.optionName} quantity=$selectedQuantity trigger=$trigger"
            )
            AutomationTaskStore.updateCurrentStep(AutomationContract.Step.CONFIRM_OPTION_ADD_TO_CART)
            scheduleProcessTick(200L, "option_selected")
            return
        }

        if (AutomationTaskStore.tryReserveOptionSelectNoEffectRetry()) {
            val optionNode = findOptionNameNode(filteredNodes, task.optionName)
            if (optionNode != null) {
                val safeTapX = (optionNode.boundsLeft + 120).coerceAtMost(optionNode.boundsRight - 24)
                val safeTapY = optionNode.centerY
                val actionResult = actionExecutor.executeCoordinateTap(
                    x = safeTapX,
                    y = safeTapY,
                    reason = "option_text_safe_area"
                )
                AutomationLogger.info(
                    "option_text_safe_area_retry optionName=${task.optionName} " +
                        "tap=$safeTapX,$safeTapY success=${actionResult.success} " +
                        "observedQuantity=${selectedQuantity ?: 0}"
                )
                AutomationTaskStore.recordAction(
                    actionPlan = ActionPlan(
                        actionType = AutomationActionType.CLICK.value,
                        targetNodeId = optionNode.id,
                        textToInput = null,
                        reasonCode = "option_text_safe_area",
                        confidence = 0.5
                    ),
                    actionResult = actionResult,
                    selectedNode = optionNode
                )
                scheduleProcessTick(700L, "after_option_text_safe_area_retry")
                return
            }
        }

        AutomationTaskStore.recordWaitingForRetry(
            packageName = currentPackageName,
            currentStep = task.currentStep,
            rawNodeCount = rawNodeCount,
            filteredNodeCount = filteredNodes.size,
            trigger = trigger,
            reasonCode = "option_increase_click_no_effect",
            message = "Option increase click did not change quantity"
        )
        AutomationTaskStore.stopTask(
            packageName = currentPackageName,
            currentStep = task.currentStep,
            rawNodeCount = rawNodeCount,
            filteredNodeCount = filteredNodes.size,
            trigger = trigger,
            screenType = "possible_overlay_occlusion",
            reasonCode = "possible_overlay_occlusion",
            message = "Option node exists, but quantity did not change after click. Floating overlay may be intercepting touch.",
            failedAction = "click_increase_button",
            expectedState = "option quantity changes from 0 to 1",
            observedState = "option quantity still ${selectedQuantity ?: 0}"
        )
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

    private fun shouldLogPurchaseHistoryScrollDiagnostic(task: AutomationTask): Boolean {
        return task.platform == AutomationContract.Platform.KURLY &&
            (
                task.currentStep == AutomationContract.Step.DUMP_PURCHASE_HISTORY ||
                    task.currentStep == AutomationContract.Step.EXTRACT_PURCHASE_HISTORY ||
                    task.currentStep == AutomationContract.Step.SCROLL_PURCHASE_HISTORY
                )
    }

    private fun shouldDelayExtractAfterScroll(task: AutomationTask, trigger: String): Boolean {
        if (task.currentStep != AutomationContract.Step.EXTRACT_PURCHASE_HISTORY) return false
        if (trigger == "tick:after_scroll") return false

        return System.currentTimeMillis() < suppressExtractUntilMs ||
            trigger == "event" ||
            trigger == "tick:after_dump" ||
            trigger == "tick:after_purchase_history_expand"
    }

    private fun shouldDelayOrderHistoryGuard(task: AutomationTask): Boolean {
        return task.currentStep == AutomationContract.Step.DUMP_PURCHASE_HISTORY &&
            System.currentTimeMillis() < suppressOrderHistoryGuardUntilMs
    }

    private fun shouldDelayOrderHistoryScreenGuard(task: AutomationTask): Boolean {
        return task.currentStep == AutomationContract.Step.SCROLL_PURCHASE_HISTORY &&
            System.currentTimeMillis() < suppressOrderHistoryScreenGuardUntilMs
    }

    private fun finishPurchaseHistorySoon(reason: String) {
        AutomationLogger.info("purchase_history_finish_requested reason=$reason")
        AutomationTaskStore.updateCurrentStep(AutomationContract.Step.FINISH_PURCHASE_HISTORY)
        scheduleProcessTick(200L, "purchase_history_finish")
    }

    private fun shouldDelaySearchResultDumpAfterSubmit(task: AutomationTask): Boolean {
        return task.currentStep == AutomationContract.Step.DUMP_SEARCH_RESULTS &&
            System.currentTimeMillis() < suppressSearchResultDumpUntilMs
    }

    private fun shouldDelaySearchSubmitAfterInput(task: AutomationTask): Boolean {
        return task.currentStep == AutomationContract.Step.SEARCH_SUBMIT &&
            System.currentTimeMillis() < suppressSearchSubmitUntilMs
    }

    private fun verifySearchInputBeforeSubmit(
        task: AutomationTask,
        currentPackageName: String?,
        rawNodeCount: Int,
        filteredNodes: List<UiNode>,
        trigger: String
    ): Boolean {
        if (task.currentStep != AutomationContract.Step.SEARCH_SUBMIT) return false

        val expectedSearchKeyword = task.searchKeyword.ifBlank { task.targetProductName }.trim()
        if (expectedSearchKeyword.isBlank()) return false

        val searchInputNode = findCurrentSearchInputNode(filteredNodes)
        val actualSearchText = searchInputNode?.text
            ?.takeIf { text -> text.isNotBlank() }
            ?: searchInputNode?.contentDescription.orEmpty()
        val trimmedActualSearchText = actualSearchText.trim()
        val expectedNormalized = normalizeSearchTarget(expectedSearchKeyword)
        val actualNormalized = normalizeSearchTarget(trimmedActualSearchText)

        AutomationLogger.info(
            "verify_search_input_before_submit expected=$expectedSearchKeyword " +
                "actual=$trimmedActualSearchText nodeId=${searchInputNode?.id ?: -1} trigger=$trigger"
        )

        val keywordMatches = searchInputNode != null &&
            actualNormalized.isNotBlank() &&
            (actualNormalized == expectedNormalized || actualNormalized.contains(expectedNormalized))
        if (keywordMatches) {
            return false
        }

        val blockedReasonCode = if (searchInputNode == null) {
            "search_submit_blocked_input_not_found"
        } else {
            "search_submit_blocked_keyword_mismatch"
        }
        val blockedMessage = if (searchInputNode == null) {
            "Search input node was not found before submit"
        } else {
            "Search submit blocked because input text does not match expected keyword"
        }
        if (AutomationTaskStore.tryReserveSearchInputTextRetry()) {
            val expectedState = "search input text contains $expectedSearchKeyword"
            val observedState = if (searchInputNode == null) {
            "search input node not found"
        } else {
            "search input text is $trimmedActualSearchText"
        }
            AutomationTaskStore.recordWaitingForRetry(
                packageName = currentPackageName,
                currentStep = task.currentStep,
                rawNodeCount = rawNodeCount,
                filteredNodeCount = filteredNodes.size,
                trigger = trigger,
                reasonCode = blockedReasonCode,
                message = blockedMessage
            )
            AutomationTaskStore.recordSearchInputTextMismatch(
                packageName = currentPackageName,
                currentStep = task.currentStep,
                rawNodeCount = rawNodeCount,
                filteredNodeCount = filteredNodes.size,
                trigger = trigger,
                reasonCode = blockedReasonCode,
                message = blockedMessage,
                expectedState = expectedState,
                observedState = observedState
            )
            AutomationTaskStore.updateCurrentStep(AutomationContract.Step.SEARCH_INPUT)
            scheduleProcessTick(300L, "retry_search_input_text")
        } else {
            val finalReasonCode = "search_input_text_not_applied"
            AutomationTaskStore.stopTask(
                packageName = currentPackageName,
                currentStep = task.currentStep,
                rawNodeCount = rawNodeCount,
                filteredNodeCount = filteredNodes.size,
                trigger = trigger,
                screenType = finalReasonCode,
                reasonCode = finalReasonCode,
                message = "Search input text did not match expected keyword after retries",
                failedAction = "verify_search_input_before_submit",
                expectedState = "search input text contains $expectedSearchKeyword",
                observedState = if (searchInputNode == null) {
                    "search input node not found"
                } else {
                    "search input text is $trimmedActualSearchText"
                }
            )
        }
        return true
    }

    private fun shouldDelayAddToCartResultAfterClick(task: AutomationTask, trigger: String): Boolean {
        return task.currentStep == AutomationContract.Step.WAIT_OPTION_OR_CART_RESULT &&
            System.currentTimeMillis() < suppressAddToCartResultUntilMs
    }

    private fun findCurrentSearchInputNode(filteredNodes: List<UiNode>): UiNode? {
        return filteredNodes
            .filter { node -> node.enabled }
            .filter { node -> node.editable || node.role == "input" || isEditText(node) }
            .maxByOrNull { node ->
                var score = 0.0
                if (node.editable) score += 0.55
                if (node.role == "input") score += 0.25
                if (isEditText(node)) score += 0.25
                if (node.boundsTop in 0..420) score += 0.15
                score
            }
    }

    private fun isEditText(node: UiNode): Boolean {
        return node.className.orEmpty().contains("EditText", ignoreCase = true)
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
                if (shouldDelayOrderHistoryScreenGuard(task)) {
                    AutomationLogger.info(
                        "skip unexpected Kurly screen guard after purchase history scroll " +
                            "currentStep=${task.currentStep} trigger=$trigger"
                    )
                    return true
                }
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
        val hasOrderNumber = filteredNodes.any { node ->
            val text = node.searchableText()
            text.contains("주문번호")
        }
        val hasDeliverySignal = filteredNodes.any { node ->
            val text = node.searchableText()
            text.contains("배송완료") ||
                text.contains("배송 완료") ||
                text.contains("샛별배송") ||
                text.contains("하루배송") ||
                text.contains("택배배송")
        }
        val hasOrderAction = containsAnyText(
            filteredNodes,
            listOf("총", "주문 펼쳐보기", "주문 펼치기", "배송조회", "반품 접수", "후기 작성")
        )
        val hasPriceText = filteredNodes.any { node ->
            Regex("""\d{1,3}(,\d{3})*원""").containsMatchIn(node.primaryText())
        }
        return (hasOrderHistoryTitle && (hasOrderNumber || hasDeliverySignal || hasOrderAction)) ||
            hasOrderNumber ||
            (hasDeliverySignal && hasPriceText && hasOrderAction)
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

    private fun isProductDetailScreen(filteredNodes: List<UiNode>, targetProductName: String): Boolean {
        val hasTargetSignal = containsTargetProductSignal(filteredNodes, targetProductName)
        val hasPriceText = filteredNodes.any { node ->
            Regex("""\d{1,3}(,\d{3})*원""").containsMatchIn(node.primaryText())
        }
        val hasAddToCartAction = containsAnyText(filteredNodes, listOf("담기", "장바구니 담기"))
        val hasDetailSignal = containsAnyText(
            filteredNodes,
            listOf("상품설명", "상품 설명", "상세정보", "상세 정보", "후기", "문의", "배송")
        )
        return hasTargetSignal && hasPriceText && (hasAddToCartAction || hasDetailSignal)
    }

    private fun classifyAfterAddToCartClick(
        filteredNodes: List<UiNode>,
        task: AutomationTask
    ): String {
        if (containsAnyText(filteredNodes, sensitiveKeywords())) return "sensitive_screen"
        if (containsAnyText(filteredNodes, listOf("로그인이 필요", "로그인 후", "로그인해주세요"))) {
            return "login_required"
        }
        if (containsAnyText(filteredNodes, listOf("품절", "일시품절", "재입고", "판매 종료"))) {
            return "sold_out"
        }
        if (containsAnyText(filteredNodes, listOf("장바구니에 담겼습니다", "담겼습니다", "장바구니 보기"))) {
            return "cart_added"
        }
        val normalizedOptionName = normalizeSearchTarget(task.optionName)
        val hasRequestedOption = normalizedOptionName.isNotBlank() &&
            filteredNodes.any { node -> normalizeSearchTarget(node.searchableText()).contains(normalizedOptionName) }
        if (hasRequestedOption || containsAnyText(filteredNodes, listOf("옵션", "옵션 선택", "상품 선택"))) {
            return "option_required"
        }
        if (containsAnyText(filteredNodes, listOf("수량", "수량 선택", "개수"))) {
            return "quantity_required"
        }
        return "unknown_after_add_click"
    }

    private fun selectedOptionQuantity(filteredNodes: List<UiNode>, optionName: String): Int? {
        val optionNode = findOptionNameNode(filteredNodes, optionName)
            ?: return null

        return filteredNodes
            .filter { node -> node.viewIdResourceName.orEmpty().endsWith("numberView") }
            .filter { node -> kotlin.math.abs(node.centerY - optionNode.centerY) <= 180 }
            .mapNotNull { node -> node.primaryText().trim().toIntOrNull() }
            .maxOrNull()
    }

    private fun findOptionNameNode(filteredNodes: List<UiNode>, optionName: String): UiNode? {
        val normalizedOptionName = normalizeSearchTarget(optionName)
        if (normalizedOptionName.isBlank()) return null

        return filteredNodes
            .filter { node -> node.primaryText().isNotBlank() || node.contentDescription.orEmpty().isNotBlank() }
            .filter { node -> normalizeSearchTarget(node.searchableText()).contains(normalizedOptionName) }
            .minByOrNull { node -> node.centerY }
    }

    private fun containsTargetProductSignal(filteredNodes: List<UiNode>, targetProductName: String): Boolean {
        val normalizedTarget = normalizeSearchTarget(targetProductName)
        if (normalizedTarget.isBlank()) return false
        val combinedText = filteredNodes.joinToString(" ") { node -> normalizeSearchTarget(node.searchableText()) }
        if (combinedText.contains(normalizedTarget)) return true

        val targetTokens = normalizedTarget
            .split(" ")
            .filter { token -> token.length >= 2 }
            .distinct()
        if (targetTokens.isEmpty()) return false

        val matchedTokenCount = targetTokens.count { token -> combinedText.contains(token) }
        val requiredTokenCount = maxOf(2, (targetTokens.size * 2 + 2) / 3)
        return matchedTokenCount >= requiredTokenCount
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

    private fun findKurlyOrderExpandNodes(task: AutomationTask, filteredNodes: List<UiNode>): List<UiNode> {
        if (task.platform != AutomationContract.Platform.KURLY) return emptyList()
        val expandRegex = Regex("""총\s*\d+\s*건.*(주문|상품)?.*(펼쳐보기|펼치기|더보기)""")
        return filteredNodes
            .filter { node -> node.enabled }
            .filter { node ->
                val text = node.primaryText()
                text.contains("펼쳐보기") ||
                    text.contains("펼치기") ||
                    expandRegex.containsMatchIn(text)
            }
            .sortedByDescending { node ->
                var score = 0.0
                if (node.clickable || node.role == "button") score += 0.5
                if (node.centerY in 450..1900) score += 0.25
                if (node.primaryText().contains("총")) score += 0.15
                if (node.primaryText().contains("주문")) score += 0.1
                score
            }
    }

    private fun handlePurchaseHistoryPeriodFilterIfNeeded(
        task: AutomationTask,
        filteredNodes: List<UiNode>
    ): Boolean {
        // 마켓컬리 기간 필터는 드롭다운/바텀시트 옵션 선택 안정화가 더 필요해서 일단 비활성화한다.
        // 나중에 옵션 UI tree를 다시 확인한 뒤 이 플래그를 켜서 재사용한다.
        if (!purchaseHistoryPeriodFilterEnabled) return false
        if (task.platform != AutomationContract.Platform.KURLY) return false
        if (!AutomationTaskStore.shouldHandlePurchaseHistoryPeriodFilter()) return false

        if (AutomationTaskStore.isPurchaseHistoryPeriodFilterOpened()) {
            val maxPeriodNode = findKurlyMaxPeriodOptionNode(filteredNodes)
            if (maxPeriodNode == null) {
                AutomationTaskStore.markPurchaseHistoryPeriodFilterHandled("max_period_option_not_found")
                return false
            }

            val selectPlan = ActionPlan(
                actionType = AutomationActionType.CLICK.value,
                targetNodeId = maxPeriodNode.id,
                textToInput = null,
                reasonCode = RuleReasonCode.PURCHASE_HISTORY_PERIOD_FILTER_SELECT.value,
                confidence = 0.78
            )
            val selectResult = actionExecutor.execute(selectPlan, filteredNodes)
            AutomationLogger.info(
                "purchase_history_period_filter select " +
                    "selectedNodeText=${maxPeriodNode.primaryText()} " +
                    "success=${selectResult.success} method=${selectResult.method}"
            )
            AutomationTaskStore.recordAction(selectPlan, selectResult, maxPeriodNode)
            AutomationTaskStore.markPurchaseHistoryPeriodFilterHandled(
                if (selectResult.success) "max_period_selected" else "max_period_select_failed"
            )
            scheduleProcessTick(1000L, "after_purchase_history_period_select")
            return true
        }

        val currentPeriodNode = findKurlyCurrentPeriodFilterNode(filteredNodes) ?: return false
        if (isAlreadyMaxPurchaseHistoryPeriod(currentPeriodNode.primaryText())) {
            AutomationTaskStore.markPurchaseHistoryPeriodFilterHandled("current_period_already_max")
            return false
        }
        if (!AutomationTaskStore.tryOpenPurchaseHistoryPeriodFilter()) return false

        val openPlan = ActionPlan(
            actionType = AutomationActionType.CLICK.value,
            targetNodeId = currentPeriodNode.id,
            textToInput = null,
            reasonCode = RuleReasonCode.PURCHASE_HISTORY_PERIOD_FILTER_OPEN.value,
            confidence = 0.76
        )
        val openResult = actionExecutor.execute(openPlan, filteredNodes)
        AutomationLogger.info(
            "purchase_history_period_filter open " +
                "selectedNodeText=${currentPeriodNode.primaryText()} " +
                "success=${openResult.success} method=${openResult.method}"
        )
        AutomationTaskStore.recordAction(openPlan, openResult, currentPeriodNode)
        if (!openResult.success) {
            AutomationTaskStore.markPurchaseHistoryPeriodFilterHandled("period_filter_open_failed")
        }
        scheduleProcessTick(900L, "after_purchase_history_period_open")
        return true
    }

    private fun findKurlyCurrentPeriodFilterNode(filteredNodes: List<UiNode>): UiNode? {
        val currentPeriodRegex = Regex("""^(최근\s*)?(1|3|6)\s*개월$|^조회\s*기간$|^기간$""")
        return filteredNodes
            .filter { node -> node.visibleToUser && node.enabled }
            .filter { node ->
                val text = node.primaryText().replace(Regex("\\s+"), " ").trim()
                currentPeriodRegex.containsMatchIn(text)
            }
            .maxByOrNull { node ->
                var score = 0.0
                if (node.clickable || node.role == "button") score += 0.45
                if (node.centerY in 250..650) score += 0.35
                if (node.primaryText().contains("개월")) score += 0.2
                score
            }
    }

    private fun findKurlyMaxPeriodOptionNode(filteredNodes: List<UiNode>): UiNode? {
        return filteredNodes
            .filter { node -> node.visibleToUser && node.enabled }
            .mapNotNull { node ->
                val score = purchaseHistoryPeriodOptionScore(node.primaryText())
                if (score <= 0.0) null else node to score
            }
            .maxByOrNull { (node, score) ->
                var adjustedScore = score
                if (node.clickable || node.role == "button") adjustedScore += 0.2
                if (node.centerY in 500..2100) adjustedScore += 0.1
                adjustedScore
            }
            ?.first
    }

    private fun purchaseHistoryPeriodOptionScore(text: String): Double {
        val normalizedText = text.replace(Regex("\\s+"), "").trim()
        if (normalizedText.isBlank()) return 0.0
        if (normalizedText.contains("전체")) return 100.0
        if (normalizedText.contains("최대")) return 95.0
        if (normalizedText.contains("3년")) return 90.0
        if (normalizedText.contains("2년")) return 80.0
        if (normalizedText.contains("1년")) return 70.0
        if (normalizedText.contains("6개월")) return 60.0
        return 0.0
    }

    private fun isAlreadyMaxPurchaseHistoryPeriod(text: String): Boolean {
        return purchaseHistoryPeriodOptionScore(text) >= 70.0
    }

    private fun purchaseHistoryExpandKey(expandNode: UiNode, filteredNodes: List<UiNode>): String {
        val orderNumberRegex = Regex("""주문번호\s*([0-9]+)""")
        val nearestOrderNumber = filteredNodes
            .filter { node -> node.boundsTop <= expandNode.boundsTop }
            .mapNotNull { node ->
                val orderNumber = orderNumberRegex.find(node.primaryText())?.groupValues?.getOrNull(1)
                    ?: return@mapNotNull null
                orderNumber to kotlin.math.abs(expandNode.centerY - node.centerY)
            }
            .minByOrNull { (_, distance) -> distance }
            ?.first

        return nearestOrderNumber ?: "${expandNode.primaryText()}@${expandNode.boundsTop}-${expandNode.boundsBottom}"
    }

    private fun logPurchaseHistoryScrollDiagnostic(
        task: AutomationTask,
        trigger: String,
        rawNodeCount: Int,
        filteredNodes: List<UiNode>
    ) {
        val orderNumbers = visiblePurchaseHistoryOrderNumbers(filteredNodes)
        val expandButtons = findKurlyOrderExpandNodes(task, filteredNodes).map { node ->
            val key = purchaseHistoryExpandKey(node, filteredNodes)
            "${sanitizeDiagnosticText(node.primaryText())}@$key/y=${node.centerY}"
        }
        val meaningfulTexts = purchaseHistoryMeaningfulTexts(filteredNodes)
        val topVisibleText = meaningfulTexts.firstOrNull().orEmpty()
        val bottomVisibleText = meaningfulTexts.lastOrNull().orEmpty()
        val fingerprint = purchaseHistoryScrollFingerprint(meaningfulTexts)
        val previousFingerprint = lastPurchaseHistoryScrollFingerprint
        val scrollChanged = previousFingerprint != null && previousFingerprint != fingerprint
        lastPurchaseHistoryScrollFingerprint = fingerprint

        AutomationLogger.info(
            "purchase_history_scroll_diagnostic " +
                "step=${task.currentStep} trigger=$trigger rawNodeCount=$rawNodeCount " +
                "filteredNodeCount=${filteredNodes.size} " +
                "visibleOrderNumbers=${orderNumbers.joinToString(prefix = "[", postfix = "]")} " +
                "visibleExpandButtons=${expandButtons.joinToString(prefix = "[", postfix = "]")} " +
                "topVisibleText=$topVisibleText bottomVisibleText=$bottomVisibleText " +
                "fingerprint=$fingerprint previousFingerprint=${previousFingerprint.orEmpty()} " +
                "scrollChanged=$scrollChanged"
        )
    }

    private fun visiblePurchaseHistoryOrderNumbers(filteredNodes: List<UiNode>): List<String> {
        val orderNumberRegex = Regex("""(?:주문번호\s*)?([0-9]{10,})""")
        return filteredNodes
            .flatMap { node ->
                listOf(node.text.orEmpty(), node.contentDescription.orEmpty(), node.primaryText())
            }
            .flatMap { text -> orderNumberRegex.findAll(text).map { match -> match.groupValues[1] }.toList() }
            .distinct()
    }

    private fun purchaseHistoryMeaningfulTexts(filteredNodes: List<UiNode>): List<String> {
        return filteredNodes
            .filter { node -> node.visibleToUser }
            .filter { node -> node.boundsBottom > 295 && node.boundsTop < 2295 }
            .sortedWith(compareBy<UiNode> { it.boundsTop }.thenBy { it.boundsLeft })
            .map { node -> sanitizeDiagnosticText(node.primaryText()) }
            .filter { text -> text.isNotBlank() }
            .filterNot { text -> text == "__next" || text.contains("route-announcer") }
            .distinct()
            .take(60)
    }

    private fun purchaseHistoryScrollFingerprint(meaningfulTexts: List<String>): String {
        val fingerprintSource = meaningfulTexts.joinToString("|")
        return fingerprintSource.hashCode().toUInt().toString(16)
    }

    private fun sanitizeDiagnosticText(text: String): String {
        return text
            .replace(Regex("\\s+"), " ")
            .replace("[", "(")
            .replace("]", ")")
            .trim()
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
