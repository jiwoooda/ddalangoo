package com.ddalangoo.ddalangoo.accessibility

object AutomationTaskStore {
    private var currentTask: AutomationTask? = null
    private var pendingResult: AutomationResult? = null
    private var runtimeStatus = AutomationRuntimeStatus()
    private val retryCountsByStep = mutableMapOf<String, Int>()
    private var purchaseHistoryFinishHandled = false
    private val purchaseHistoryExpandKeys = mutableSetOf<String>()
    private var purchaseHistoryPeriodFilterOpened = false
    private var purchaseHistoryPeriodFilterHandled = false
    private var recoveryCount = 0
    private var searchInputFocusRetryCount = 0
    private var searchSubmitRetryCount = 0
    private var searchInputTextRetryCount = 0
    private var optionSelectNoEffectRetryCount = 0
    private var lastObservedOptionQuantity: Int? = null
    private val checkoutItemOutcomes = mutableListOf<Map<String, Any?>>()
    private const val MAX_RETRY_COUNT_PER_STEP = 5
    private const val MAX_RECOVERY_COUNT = 2
    private const val MAX_SEARCH_INPUT_FOCUS_RETRY_COUNT = 2
    private const val MAX_SEARCH_SUBMIT_RETRY_COUNT = 2
    private const val MAX_SEARCH_INPUT_TEXT_RETRY_COUNT = 2
    private const val MAX_OPTION_SELECT_NO_EFFECT_RETRY_COUNT = 1

    @Synchronized
    fun setTask(task: AutomationTask) {
        currentTask = task
        pendingResult = null
        retryCountsByStep.clear()
        purchaseHistoryFinishHandled = false
        purchaseHistoryExpandKeys.clear()
        purchaseHistoryPeriodFilterOpened = false
        purchaseHistoryPeriodFilterHandled = false
        recoveryCount = 0
        searchInputFocusRetryCount = 0
        searchSubmitRetryCount = 0
        searchInputTextRetryCount = 0
        optionSelectNoEffectRetryCount = 0
        lastObservedOptionQuantity = null
        checkoutItemOutcomes.clear()
        runtimeStatus = runtimeStatus.copy(
            lastPackageName = task.effectivePackageName(),
            lastStep = task.currentStep,
            lastScreenType = null,
            lastTrigger = null,
            currentRetryCount = 0,
            currentRecoveryCount = 0,
            lastActionType = null,
            lastReasonCode = null,
            lastTargetNodeId = null,
            lastSelectedNodeText = null,
            lastActionSuccess = null,
            lastActionMethod = null,
            lastErrorCode = null,
            lastMessage = "Task is waiting for accessibility events",
            aiFallbackSuggested = false,
            fallbackType = null,
            fallbackReasonCode = null,
            failedAction = null,
            expectedState = null,
            observedState = null
        )
        if (
            task.currentStep == AutomationContract.Step.EXTRACT_PURCHASE_HISTORY ||
            task.currentStep == AutomationContract.Step.DUMP_PURCHASE_HISTORY
        ) {
            PurchaseHistoryExtractionStore.clear()
        }
        if (
            task.taskType == AutomationContract.TaskType.INSPECT_SEARCH_FLOW ||
            task.currentStep == AutomationContract.Step.OPEN_SEARCH
        ) {
            SearchInspectionStore.clear()
        }
        AutomationLogger.info(
            "AutomationTask taskId=${task.taskId} 저장 " +
                "taskType=${task.taskType} platform=${task.platform} " +
                "packageName=${task.effectivePackageName()} currentStep=${task.currentStep}"
        )
    }

    @Synchronized
    fun getTask(): AutomationTask? {
        return currentTask
    }

    @Synchronized
    fun clearTask() {
        AutomationLogger.info("task cleared taskId=${currentTask?.taskId.orEmpty()}")
        currentTask = null
        retryCountsByStep.clear()
        purchaseHistoryFinishHandled = false
        purchaseHistoryExpandKeys.clear()
        purchaseHistoryPeriodFilterOpened = false
        purchaseHistoryPeriodFilterHandled = false
        recoveryCount = 0
        searchInputFocusRetryCount = 0
        searchSubmitRetryCount = 0
        searchInputTextRetryCount = 0
        optionSelectNoEffectRetryCount = 0
        lastObservedOptionQuantity = null
        checkoutItemOutcomes.clear()
        runtimeStatus = runtimeStatus.copy(
            lastStep = null,
            lastScreenType = null,
            lastTrigger = null,
            currentRetryCount = 0,
            currentRecoveryCount = 0,
            lastActionType = null,
            lastReasonCode = null,
            lastTargetNodeId = null,
            lastSelectedNodeText = null,
            lastActionSuccess = null,
            lastActionMethod = null,
            lastErrorCode = null,
            lastMessage = "Task cleared",
            aiFallbackSuggested = false,
            fallbackType = null,
            fallbackReasonCode = null,
            failedAction = null,
            expectedState = null,
            observedState = null
        )
    }

    @Synchronized
    fun stopTask(
        packageName: String?,
        currentStep: String,
        rawNodeCount: Int,
        filteredNodeCount: Int,
        trigger: String,
        screenType: String,
        reasonCode: String,
        message: String,
        failedAction: String? = null,
        expectedState: String? = null,
        observedState: String? = null
    ) {
        val task = currentTask
        val shouldSuggestFallback = reasonCode == "search_submit_not_effective" ||
            reasonCode == "search_input_text_not_applied" ||
            reasonCode == "target_product_not_found" ||
            reasonCode == "possible_popup_blocking" ||
            reasonCode == "possible_overlay_occlusion" ||
            reasonCode == "no_state_change_after_action" ||
            reasonCode == "option_increase_click_no_effect" ||
            reasonCode == "unknown_after_add_click"
        AutomationLogger.warn(
            "task stopped taskId=${currentTask?.taskId.orEmpty()} reason=$reasonCode " +
                "screenType=$screenType trigger=$trigger message=$message"
        )
        if (task != null) {
            pendingResult = AutomationResult(
                taskId = task.taskId,
                taskType = task.taskType,
                status = "failed",
                platform = task.platform,
                packageName = task.effectivePackageName(),
                currentStep = currentStep,
                errorCode = reasonCode,
                errorMessage = message,
                metadata = mapOf(
                    "trigger" to trigger,
                    "screenType" to screenType,
                    "failedAction" to failedAction,
                    "expectedState" to expectedState,
                    "observedState" to observedState,
                    "aiFallbackSuggested" to shouldSuggestFallback,
                    "fallbackType" to if (shouldSuggestFallback) fallbackTypeFor(reasonCode) else null,
                ).filterValues { it != null },
            )
            AutomationLogger.info(
                "AutomationResult taskId=${task.taskId} status=failed 생성 " +
                    "reason=$reasonCode currentStep=$currentStep"
            )
        }
        currentTask = null
        retryCountsByStep.clear()
        purchaseHistoryFinishHandled = false
        purchaseHistoryExpandKeys.clear()
        purchaseHistoryPeriodFilterOpened = false
        purchaseHistoryPeriodFilterHandled = false
        recoveryCount = 0
        searchInputFocusRetryCount = 0
        searchSubmitRetryCount = 0
        searchInputTextRetryCount = 0
        optionSelectNoEffectRetryCount = 0
        lastObservedOptionQuantity = null
        checkoutItemOutcomes.clear()
        runtimeStatus = runtimeStatus.copy(
            lastPackageName = packageName,
            lastStep = currentStep,
            lastScreenType = screenType,
            lastTrigger = trigger,
            currentRetryCount = 0,
            currentRecoveryCount = 0,
            rawNodeCount = rawNodeCount,
            filteredNodeCount = filteredNodeCount,
            lastActionType = null,
            lastReasonCode = reasonCode,
            lastTargetNodeId = null,
            lastSelectedNodeText = null,
            lastActionSuccess = false,
            lastActionMethod = null,
            lastErrorCode = reasonCode.uppercase(),
            lastMessage = message,
            aiFallbackSuggested = shouldSuggestFallback,
            fallbackType = if (shouldSuggestFallback) fallbackTypeFor(reasonCode) else null,
            fallbackReasonCode = if (shouldSuggestFallback) reasonCode else null,
            failedAction = failedAction,
            expectedState = expectedState,
            observedState = observedState
        )
    }

    private fun fallbackTypeFor(reasonCode: String): String {
        return when (reasonCode) {
            "possible_overlay_occlusion",
            "possible_popup_blocking",
            "no_state_change_after_action",
            "option_increase_click_no_effect",
            "unknown_after_add_click" -> "vlm"
            else -> "ui_tree_or_vlm"
        }
    }

    private fun checkoutItems(task: AutomationTask): List<Map<String, Any?>> {
        val rawItems = task.metadata["checkoutItems"] as? List<*> ?: return emptyList()
        return rawItems.mapNotNull { rawItem ->
            (rawItem as? Map<*, *>)?.entries?.associate { (key, value) ->
                key.toString() to value
            }
        }
    }

    private fun checkoutItemIndex(task: AutomationTask): Int {
        return intFrom(task.metadata["currentCheckoutItemIndex"])
            ?: intFrom(task.metadata["currentPlatformItemIndex"])
            ?: 0
    }

    private fun stringFrom(value: Any?): String? {
        return value?.toString()?.trim()?.takeIf { it.isNotEmpty() }
    }

    private fun intFrom(value: Any?): Int? {
        return when (value) {
            is Int -> value
            is Long -> value.toInt()
            is Number -> value.toInt()
            is String -> value.toIntOrNull()
            else -> null
        }
    }

    @Synchronized
    fun updateCurrentStep(nextStep: String) {
        val task = currentTask ?: return
        if (nextStep != task.currentStep) {
            retryCountsByStep.remove(nextStep)
        }
        currentTask = task.copy(currentStep = nextStep)
        if (nextStep != AutomationContract.Step.SEARCH_INPUT) {
            searchInputFocusRetryCount = 0
        }
        if (nextStep == AutomationContract.Step.OPEN_SEARCH || nextStep == AutomationContract.Step.SEARCH_INPUT) {
            searchSubmitRetryCount = 0
        }
        if (nextStep == AutomationContract.Step.OPEN_SEARCH) {
            searchInputTextRetryCount = 0
        }
        runtimeStatus = runtimeStatus.copy(
            lastStep = nextStep,
            currentRetryCount = retryCountsByStep[nextStep] ?: 0
        )
        AutomationLogger.info("task updated taskId=${task.taskId} currentStep=${task.currentStep} nextStep=$nextStep")
    }

    @Synchronized
    fun recordObservedOptionQuantity(quantity: Int) {
        lastObservedOptionQuantity = quantity
    }

    @Synchronized
    fun lastObservedOptionQuantity(): Int? {
        return lastObservedOptionQuantity
    }

    @Synchronized
    fun markCompleted(
        trigger: String,
        message: String,
        resultType: String? = null,
        payload: Map<String, Any?> = emptyMap()
    ) {
        val task = currentTask ?: return
        currentTask = task.copy(currentStep = AutomationContract.Step.COMPLETED)
        pendingResult = AutomationResult(
            taskId = task.taskId,
            taskType = task.taskType,
            status = "completed",
            platform = task.platform,
            packageName = task.effectivePackageName(),
            currentStep = AutomationContract.Step.COMPLETED,
            resultType = resultType,
            payload = payload,
            metadata = mapOf(
                "trigger" to trigger,
                "message" to message,
            ),
        )
        AutomationLogger.info(
            "AutomationResult taskId=${task.taskId} status=completed 생성 " +
                "currentStep=${AutomationContract.Step.COMPLETED}"
        )
        retryCountsByStep.clear()
        searchInputFocusRetryCount = 0
        searchSubmitRetryCount = 0
        searchInputTextRetryCount = 0
        optionSelectNoEffectRetryCount = 0
        lastObservedOptionQuantity = null
        checkoutItemOutcomes.clear()
        runtimeStatus = runtimeStatus.copy(
            lastStep = AutomationContract.Step.COMPLETED,
            lastTrigger = trigger,
            currentRetryCount = 0,
            currentRecoveryCount = recoveryCount,
            lastActionType = null,
            lastReasonCode = AutomationContract.Step.TASK_COMPLETED_REASON,
            lastTargetNodeId = null,
            lastSelectedNodeText = null,
            lastActionSuccess = true,
            lastActionMethod = null,
            lastErrorCode = null,
            lastMessage = message,
            aiFallbackSuggested = false,
            fallbackType = null,
            fallbackReasonCode = null,
            failedAction = null,
            expectedState = null,
            observedState = null
        )
        AutomationLogger.info("task completed taskId=${task.taskId} trigger=$trigger message=$message")
    }

    @Synchronized
    fun advanceCheckoutItemOrComplete(
        trigger: String,
        itemOutcome: Map<String, Any?>
    ): AutomationTask? {
        val task = currentTask ?: return null
        if (task.taskType != AutomationContract.TaskType.CHECKOUT_PLATFORM_CART) {
            return null
        }

        checkoutItemOutcomes.add(itemOutcome)
        val checkoutItems = checkoutItems(task)
        val currentIndex = checkoutItemIndex(task)
        val nextIndex = currentIndex + 1
        if (nextIndex >= checkoutItems.size) {
            markCompleted(
                trigger = trigger,
                message = "Checkout platform cart automation completed",
                resultType = AutomationContract.ResultType.CHECKOUT_PLATFORM_CART_COMPLETED,
                payload = mapOf(
                    "itemOutcomes" to checkoutItemOutcomes.toList(),
                    "completedItemCount" to checkoutItemOutcomes.size,
                    "requestedItemCount" to checkoutItems.size,
                    "platforms" to (task.metadata["platforms"] ?: emptyList<String>()),
                    "orderId" to task.orderId,
                    "paymentId" to task.paymentId,
                )
            )
            return null
        }

        val nextItem = checkoutItems[nextIndex]
        val nextPlatform = stringFrom(nextItem["platform"]) ?: task.platform
        val nextPackageName = stringFrom(nextItem["packageName"])
            ?: AutomationContract.defaultPackageNameForPlatform(nextPlatform)
        val nextTask = task.copy(
            platform = nextPlatform,
            packageName = nextPackageName,
            currentStep = AutomationContract.Step.OPEN_SEARCH,
            targetProductName = stringFrom(nextItem["productName"]).orEmpty(),
            searchKeyword = stringFrom(nextItem["searchKeyword"])
                ?: stringFrom(nextItem["productName"]).orEmpty(),
            optionName = stringFrom(nextItem["optionName"]).orEmpty(),
            quantity = intFrom(nextItem["quantity"]) ?: 1,
            cartItemId = stringFrom(nextItem["cartItemId"]),
            metadata = task.metadata + mapOf(
                "currentCheckoutItemIndex" to nextIndex,
                "currentCheckoutItem" to nextItem,
                "itemOutcomes" to checkoutItemOutcomes.toList(),
            )
        )
        currentTask = nextTask
        retryCountsByStep.clear()
        recoveryCount = 0
        searchInputFocusRetryCount = 0
        searchSubmitRetryCount = 0
        searchInputTextRetryCount = 0
        optionSelectNoEffectRetryCount = 0
        lastObservedOptionQuantity = null
        SearchInspectionStore.clear()
        runtimeStatus = runtimeStatus.copy(
            lastPackageName = nextTask.effectivePackageName(),
            lastStep = nextTask.currentStep,
            currentRetryCount = 0,
            currentRecoveryCount = 0,
            lastReasonCode = "checkout_next_item",
            lastMessage = "Checkout automation moved to next cart item"
        )
        AutomationLogger.info(
            "checkout next item taskId=${task.taskId} nextIndex=$nextIndex " +
                "platform=$nextPlatform packageName=$nextPackageName " +
                "productName=${nextTask.targetProductName} quantity=${nextTask.quantity}"
        )
        return nextTask
    }

    @Synchronized
    fun markPurchaseHistoryFinishHandledIfNeeded(): Boolean {
        if (purchaseHistoryFinishHandled) {
            return false
        }
        purchaseHistoryFinishHandled = true
        return true
    }

    @Synchronized
    fun recordCompletedIgnored(
        packageName: String?,
        rawNodeCount: Int,
        filteredNodeCount: Int,
        trigger: String
    ) {
        runtimeStatus = runtimeStatus.copy(
            lastPackageName = packageName,
            lastStep = AutomationContract.Step.COMPLETED,
            lastTrigger = trigger,
            currentRetryCount = 0,
            currentRecoveryCount = recoveryCount,
            rawNodeCount = rawNodeCount,
            filteredNodeCount = filteredNodeCount,
            lastActionType = null,
            lastReasonCode = AutomationContract.Step.TASK_COMPLETED_REASON,
            lastTargetNodeId = null,
            lastSelectedNodeText = null,
            lastActionSuccess = true,
            lastActionMethod = null,
            lastErrorCode = null,
            lastMessage = "Task completed; ignoring further events"
        )
    }

    @Synchronized
    fun recordScreenClassification(screenType: String, trigger: String) {
        runtimeStatus = runtimeStatus.copy(
            lastScreenType = screenType,
            lastTrigger = trigger,
            currentRecoveryCount = recoveryCount
        )
    }

    @Synchronized
    fun recordRecoveryAttempt(
        packageName: String?,
        currentStep: String,
        rawNodeCount: Int,
        filteredNodeCount: Int,
        trigger: String,
        screenType: String,
        success: Boolean
    ): Boolean {
        recoveryCount += 1
        val exceeded = recoveryCount > MAX_RECOVERY_COUNT
        runtimeStatus = runtimeStatus.copy(
            lastPackageName = packageName,
            lastStep = currentStep,
            lastScreenType = screenType,
            lastTrigger = trigger,
            currentRecoveryCount = recoveryCount,
            rawNodeCount = rawNodeCount,
            filteredNodeCount = filteredNodeCount,
            lastActionType = "global_back",
            lastReasonCode = "recover_from_unexpected_screen",
            lastTargetNodeId = null,
            lastSelectedNodeText = null,
            lastActionSuccess = success,
            lastActionMethod = "global_action_back",
            lastErrorCode = if (exceeded) "RECOVERY_LIMIT_EXCEEDED" else null,
            lastMessage = if (exceeded) {
                "Recovery limit exceeded for screen=$screenType"
            } else {
                "Unexpected Kurly screen; pressed back to recover"
            }
        )
        AutomationLogger.info(
            "recovery step=$currentStep screenType=$screenType trigger=$trigger " +
                "recoveryCount=$recoveryCount exceeded=$exceeded success=$success"
        )
        return !exceeded
    }

    @Synchronized
    fun advanceAfterSuccess(actionPlan: ActionPlan) {
        val task = currentTask ?: return
        val nextStep = when (actionPlan.reasonCode) {
            RuleReasonCode.POPUP_DISMISS.value -> task.currentStep
            RuleReasonCode.SEARCH_ENTRY.value -> AutomationContract.Step.SEARCH_INPUT
            RuleReasonCode.SEARCH_INPUT_FOCUS_RETRY.value -> AutomationContract.Step.SEARCH_INPUT
            RuleReasonCode.SEARCH_INPUT.value -> AutomationContract.Step.SEARCH_SUBMIT
            RuleReasonCode.SEARCH_BUTTON.value -> AutomationContract.Step.DUMP_SEARCH_RESULTS
            RuleReasonCode.KEYBOARD_SEARCH.value -> AutomationContract.Step.DUMP_SEARCH_RESULTS
            RuleReasonCode.SEARCH_RESULT_DUMP.value -> AutomationContract.Step.SCROLL_SEARCH_RESULTS
            RuleReasonCode.SEARCH_RESULT_SCROLL.value -> AutomationContract.Step.DUMP_SEARCH_RESULTS
            RuleReasonCode.SEARCH_RESULT_FINISH.value -> AutomationContract.Step.COMPLETED
            RuleReasonCode.PRODUCT_CARD.value -> AutomationContract.Step.WAIT_PRODUCT_DETAIL
            RuleReasonCode.CART_BUTTON.value -> AutomationContract.Step.WAIT_OPTION_OR_CART_RESULT
            RuleReasonCode.OPTION_SELECT.value -> AutomationContract.Step.WAIT_OPTION_SELECTED
            RuleReasonCode.OPTION_CONFIRM.value -> AutomationContract.Step.VERIFY_CART_ADDED
            RuleReasonCode.OPTION_ADD.value -> AutomationContract.Step.COMPLETED
            RuleReasonCode.MY_COUPANG.value -> AutomationContract.Step.OPEN_ORDER_HISTORY
            RuleReasonCode.MY_KURLY.value -> AutomationContract.Step.OPEN_ORDER_HISTORY
            RuleReasonCode.ORDER_HISTORY.value -> AutomationContract.Step.DUMP_PURCHASE_HISTORY
            RuleReasonCode.PURCHASE_HISTORY_DUMP.value -> when (task.currentStep) {
                AutomationContract.Step.EXTRACT_PURCHASE_HISTORY -> AutomationContract.Step.SCROLL_PURCHASE_HISTORY
                AutomationContract.Step.DUMP_PURCHASE_HISTORY -> AutomationContract.Step.SCROLL_PURCHASE_HISTORY
                else -> task.currentStep
            }
            RuleReasonCode.PURCHASE_HISTORY_SCROLL.value -> AutomationContract.Step.EXTRACT_PURCHASE_HISTORY
            RuleReasonCode.PURCHASE_HISTORY_FINISH.value -> AutomationContract.Step.FINISH_PURCHASE_HISTORY
            else -> task.currentStep
        }
        currentTask = task.copy(currentStep = nextStep)
        if (nextStep != task.currentStep) {
            retryCountsByStep.remove(nextStep)
        }
        if (nextStep != AutomationContract.Step.SEARCH_INPUT) {
            searchInputFocusRetryCount = 0
        }
        if (nextStep == AutomationContract.Step.OPEN_SEARCH || nextStep == AutomationContract.Step.SEARCH_INPUT) {
            searchSubmitRetryCount = 0
        }
        if (nextStep == AutomationContract.Step.OPEN_SEARCH) {
            searchInputTextRetryCount = 0
        }
        runtimeStatus = runtimeStatus.copy(
            lastStep = nextStep,
            currentRetryCount = retryCountsByStep[nextStep] ?: 0
        )
        AutomationLogger.info("task advanced taskId=${task.taskId} currentStep=${task.currentStep} nextStep=$nextStep")
    }

    @Synchronized
    fun markServiceConnected() {
        runtimeStatus = runtimeStatus.copy(
            serviceConnected = true,
            lastMessage = "Accessibility service connected"
        )
    }

    @Synchronized
    fun recordObservation(
        packageName: String?,
        currentStep: String?,
        rawNodeCount: Int,
        filteredNodeCount: Int,
        trigger: String? = null
    ) {
        runtimeStatus = runtimeStatus.copy(
            lastPackageName = packageName,
            lastStep = currentStep,
            lastTrigger = trigger ?: runtimeStatus.lastTrigger,
            currentRetryCount = currentStep?.let { retryCountsByStep[it] } ?: 0,
            currentRecoveryCount = recoveryCount,
            rawNodeCount = rawNodeCount,
            filteredNodeCount = filteredNodeCount
        )
    }

    @Synchronized
    fun recordWaitingForPackage(
        packageName: String?,
        currentStep: String,
        rawNodeCount: Int,
        filteredNodeCount: Int,
        targetPackageName: String,
        trigger: String? = null
    ) {
        runtimeStatus = runtimeStatus.copy(
            lastPackageName = packageName,
            lastStep = currentStep,
            lastTrigger = trigger ?: runtimeStatus.lastTrigger,
            currentRetryCount = retryCountsByStep[currentStep] ?: 0,
            currentRecoveryCount = recoveryCount,
            rawNodeCount = rawNodeCount,
            filteredNodeCount = filteredNodeCount,
            lastActionType = null,
            lastReasonCode = null,
            lastTargetNodeId = null,
            lastSelectedNodeText = null,
            lastActionSuccess = null,
            lastActionMethod = null,
            lastErrorCode = "WAITING_FOR_TARGET_PACKAGE",
            lastMessage = "Waiting for package=$targetPackageName"
        )
    }

    @Synchronized
    fun recordWaitingForRetry(
        packageName: String?,
        currentStep: String,
        rawNodeCount: Int,
        filteredNodeCount: Int,
        trigger: String,
        reasonCode: String,
        message: String
    ): Boolean {
        val retryCount = (retryCountsByStep[currentStep] ?: 0) + 1
        retryCountsByStep[currentStep] = retryCount
        val exceeded = retryCount > MAX_RETRY_COUNT_PER_STEP
        runtimeStatus = runtimeStatus.copy(
            lastPackageName = packageName,
            lastStep = currentStep,
            lastTrigger = trigger,
            currentRetryCount = retryCount,
            currentRecoveryCount = recoveryCount,
            rawNodeCount = rawNodeCount,
            filteredNodeCount = filteredNodeCount,
            lastActionType = null,
            lastReasonCode = reasonCode,
            lastTargetNodeId = null,
            lastSelectedNodeText = null,
            lastActionSuccess = false,
            lastActionMethod = null,
            lastErrorCode = if (exceeded) "RETRY_LIMIT_EXCEEDED" else reasonCode.uppercase(),
            lastMessage = if (exceeded) "Retry limit exceeded for step=$currentStep" else message
        )
        AutomationLogger.info(
            "waiting step=$currentStep reason=$reasonCode trigger=$trigger " +
                "retryCount=$retryCount exceeded=$exceeded message=$message"
        )
        return !exceeded
    }

    @Synchronized
    fun recordVlmFallbackRequested(
        packageName: String?,
        currentStep: String,
        rawNodeCount: Int,
        filteredNodeCount: Int,
        trigger: String,
        reasonCode: String,
        expectedState: String,
        observedState: String
    ) {
        runtimeStatus = runtimeStatus.copy(
            lastPackageName = packageName,
            lastStep = currentStep,
            lastTrigger = trigger,
            currentRetryCount = retryCountsByStep[currentStep] ?: 0,
            currentRecoveryCount = recoveryCount,
            rawNodeCount = rawNodeCount,
            filteredNodeCount = filteredNodeCount,
            lastActionType = "vlm_fallback_request",
            lastReasonCode = reasonCode,
            lastTargetNodeId = null,
            lastSelectedNodeText = null,
            lastActionSuccess = null,
            lastActionMethod = null,
            lastErrorCode = null,
            lastMessage = "VLM fallback requested for step=$currentStep",
            aiFallbackSuggested = true,
            fallbackType = "vlm",
            fallbackReasonCode = reasonCode,
            failedAction = currentStep,
            expectedState = expectedState,
            observedState = observedState
        )
        AutomationLogger.info(
            "vlm_fallback requested taskId=${currentTask?.taskId.orEmpty()} step=$currentStep " +
                "reason=$reasonCode trigger=$trigger"
        )
    }

    @Synchronized
    fun recordVlmFallbackAction(
        packageName: String?,
        currentStep: String,
        rawNodeCount: Int,
        filteredNodeCount: Int,
        trigger: String,
        action: String,
        success: Boolean,
        method: String?,
        message: String,
        errorCode: String? = null
    ) {
        runtimeStatus = runtimeStatus.copy(
            lastPackageName = packageName,
            lastStep = currentStep,
            lastTrigger = trigger,
            currentRetryCount = retryCountsByStep[currentStep] ?: 0,
            currentRecoveryCount = recoveryCount,
            rawNodeCount = rawNodeCount,
            filteredNodeCount = filteredNodeCount,
            lastActionType = "vlm_$action",
            lastReasonCode = "vlm_recovery_action",
            lastTargetNodeId = null,
            lastSelectedNodeText = null,
            lastActionSuccess = success,
            lastActionMethod = method,
            lastErrorCode = errorCode,
            lastMessage = message,
            aiFallbackSuggested = true,
            fallbackType = "vlm",
            fallbackReasonCode = "possible_popup_blocking"
        )
        AutomationLogger.info(
            "vlm_fallback action taskId=${currentTask?.taskId.orEmpty()} step=$currentStep " +
                "action=$action success=$success method=${method.orEmpty()} message=$message"
        )
    }

    @Synchronized
    fun recordSearchInputTextMismatch(
        packageName: String?,
        currentStep: String,
        rawNodeCount: Int,
        filteredNodeCount: Int,
        trigger: String,
        reasonCode: String,
        message: String,
        expectedState: String,
        observedState: String
    ) {
        runtimeStatus = runtimeStatus.copy(
            lastPackageName = packageName,
            lastStep = currentStep,
            lastTrigger = trigger,
            currentRetryCount = retryCountsByStep[currentStep] ?: 0,
            currentRecoveryCount = recoveryCount,
            rawNodeCount = rawNodeCount,
            filteredNodeCount = filteredNodeCount,
            lastActionType = null,
            lastReasonCode = reasonCode,
            lastTargetNodeId = null,
            lastSelectedNodeText = null,
            lastActionSuccess = false,
            lastActionMethod = null,
            lastErrorCode = reasonCode.uppercase(),
            lastMessage = message,
            aiFallbackSuggested = false,
            fallbackType = null,
            fallbackReasonCode = null,
            failedAction = "verify_search_input_before_submit",
            expectedState = expectedState,
            observedState = observedState
        )
        AutomationLogger.info(
            "search_input_text_mismatch step=$currentStep reason=$reasonCode trigger=$trigger " +
                "message=$message expectedState=$expectedState observedState=$observedState"
        )
    }

    @Synchronized
    fun recordAction(
        actionPlan: ActionPlan,
        actionResult: ActionResult,
        selectedNode: UiNode?
    ) {
        val searchInputNodeNotFound = actionPlan.reasonCode == RuleReasonCode.SEARCH_INPUT_NODE_NOT_FOUND.value
        runtimeStatus = runtimeStatus.copy(
            lastActionType = actionPlan.actionType,
            lastReasonCode = actionPlan.reasonCode,
            lastTargetNodeId = actionPlan.targetNodeId,
            lastSelectedNodeText = selectedNode?.primaryText(),
            lastActionSuccess = actionResult.success,
            lastActionMethod = actionResult.method,
            lastErrorCode = actionResult.errorCode,
            lastMessage = if (actionPlan.reasonCode == RuleReasonCode.SEARCH_INPUT_FOCUS_RETRY.value) {
                "Search input node not ready; clicked search field candidate and will retry"
            } else {
                actionResult.message
            },
            aiFallbackSuggested = searchInputNodeNotFound,
            fallbackType = if (searchInputNodeNotFound) "ui_tree_or_vlm" else null,
            fallbackReasonCode = if (searchInputNodeNotFound) {
                RuleReasonCode.SEARCH_INPUT_NODE_NOT_FOUND.value
            } else {
                null
            }
        )
    }

    @Synchronized
    fun tryReserveSearchInputFocusRetry(): Boolean {
        if (searchInputFocusRetryCount >= MAX_SEARCH_INPUT_FOCUS_RETRY_COUNT) {
            AutomationLogger.warn("search_input_focus_retry limit exceeded count=$searchInputFocusRetryCount")
            return false
        }
        searchInputFocusRetryCount += 1
        AutomationLogger.info("search_input_focus_retry reserved count=$searchInputFocusRetryCount")
        return true
    }

    @Synchronized
    fun tryReservePurchaseHistoryExpand(expandKey: String): Boolean {
        if (!purchaseHistoryExpandKeys.add(expandKey)) {
            AutomationLogger.info("purchase_history_expand skipped duplicate key=$expandKey")
            return false
        }
        AutomationLogger.info("purchase_history_expand reserved key=$expandKey")
        return true
    }

    @Synchronized
    fun shouldHandlePurchaseHistoryPeriodFilter(): Boolean {
        return !purchaseHistoryPeriodFilterHandled
    }

    @Synchronized
    fun isPurchaseHistoryPeriodFilterOpened(): Boolean {
        return purchaseHistoryPeriodFilterOpened && !purchaseHistoryPeriodFilterHandled
    }

    @Synchronized
    fun tryOpenPurchaseHistoryPeriodFilter(): Boolean {
        if (purchaseHistoryPeriodFilterHandled || purchaseHistoryPeriodFilterOpened) {
            return false
        }
        purchaseHistoryPeriodFilterOpened = true
        AutomationLogger.info("purchase_history_period_filter open reserved")
        return true
    }

    @Synchronized
    fun markPurchaseHistoryPeriodFilterHandled(reason: String) {
        purchaseHistoryPeriodFilterOpened = false
        purchaseHistoryPeriodFilterHandled = true
        AutomationLogger.info("purchase_history_period_filter handled reason=$reason")
    }

    @Synchronized
    fun currentRetryCountForStep(step: String): Int {
        return retryCountsByStep[step] ?: 0
    }

    @Synchronized
    fun tryReserveSearchSubmitRetry(): Boolean {
        if (searchSubmitRetryCount >= MAX_SEARCH_SUBMIT_RETRY_COUNT) {
            AutomationLogger.warn("search_submit_retry limit exceeded count=$searchSubmitRetryCount")
            return false
        }
        searchSubmitRetryCount += 1
        AutomationLogger.info("search_submit_retry reserved count=$searchSubmitRetryCount")
        return true
    }

    @Synchronized
    fun tryReserveSearchInputTextRetry(): Boolean {
        if (searchInputTextRetryCount >= MAX_SEARCH_INPUT_TEXT_RETRY_COUNT) {
            AutomationLogger.warn("search_input_text_retry limit exceeded count=$searchInputTextRetryCount")
            return false
        }
        searchInputTextRetryCount += 1
        AutomationLogger.info("search_input_text_retry reserved count=$searchInputTextRetryCount")
        return true
    }

    @Synchronized
    fun tryReserveOptionSelectNoEffectRetry(): Boolean {
        if (optionSelectNoEffectRetryCount >= MAX_OPTION_SELECT_NO_EFFECT_RETRY_COUNT) {
            AutomationLogger.warn(
                "option_select_no_effect_retry limit exceeded count=$optionSelectNoEffectRetryCount"
            )
            return false
        }
        optionSelectNoEffectRetryCount += 1
        AutomationLogger.info("option_select_no_effect_retry reserved count=$optionSelectNoEffectRetryCount")
        return true
    }

    @Synchronized
    fun statusMap(): Map<String, Any?> {
        val task = currentTask
        val status = runtimeStatus
        return mapOf(
            "contractVersion" to AutomationContract.CONTRACT_VERSION,
            "hasTask" to (task != null),
            "taskId" to task?.taskId,
            "taskType" to task?.taskType,
            "conversationId" to task?.conversationId,
            "userId" to task?.userId,
            "platform" to task?.platform,
            "searchKeyword" to task?.searchKeyword,
            "targetProductName" to task?.targetProductName,
            "optionName" to task?.optionName,
            "quantity" to task?.quantity,
            "packageName" to task?.packageName,
            "effectivePackageName" to task?.effectivePackageName(),
            "currentStep" to task?.currentStep,
            "cartItemId" to task?.cartItemId,
            "orderId" to task?.orderId,
            "paymentId" to task?.paymentId,
            "taskCompleted" to (task?.currentStep == AutomationContract.Step.COMPLETED),
            "purchaseHistoryFinishHandled" to purchaseHistoryFinishHandled,
            "serviceConnected" to status.serviceConnected,
            "lastPackageName" to status.lastPackageName,
            "lastStep" to status.lastStep,
            "lastScreenType" to status.lastScreenType,
            "lastTrigger" to status.lastTrigger,
            "currentRetryCount" to status.currentRetryCount,
            "currentRecoveryCount" to status.currentRecoveryCount,
            "rawNodeCount" to status.rawNodeCount,
            "filteredNodeCount" to status.filteredNodeCount,
            "lastActionType" to status.lastActionType,
            "lastReasonCode" to status.lastReasonCode,
            "lastTargetNodeId" to status.lastTargetNodeId,
            "lastSelectedNodeText" to status.lastSelectedNodeText,
            "lastActionSuccess" to status.lastActionSuccess,
            "lastActionMethod" to status.lastActionMethod,
            "lastErrorCode" to status.lastErrorCode,
            "lastMessage" to status.lastMessage,
            "searchInputFocusRetryCount" to searchInputFocusRetryCount,
            "searchSubmitRetryCount" to searchSubmitRetryCount,
            "searchInputTextRetryCount" to searchInputTextRetryCount,
            "optionSelectNoEffectRetryCount" to optionSelectNoEffectRetryCount,
            "aiFallbackSuggested" to status.aiFallbackSuggested,
            "fallbackType" to status.fallbackType,
            "fallbackReasonCode" to status.fallbackReasonCode,
            "failedAction" to status.failedAction,
            "expectedState" to status.expectedState,
            "observedState" to status.observedState,
            "latestPurchaseHistoryCount" to PurchaseHistoryExtractionStore.latestExtractionResult().size,
            "accumulatedPurchaseHistoryCount" to PurchaseHistoryExtractionStore.accumulatedCandidates().size
        ) + SearchInspectionStore.statusMap()
    }

    @Synchronized
    fun consumeResultMap(): Map<String, Any?>? {
        val result = pendingResult ?: return null
        pendingResult = null
        AutomationLogger.info(
            "AutomationResult taskId=${result.taskId} status=${result.status} Flutter로 전달"
        )
        return result.toMap()
    }
}
