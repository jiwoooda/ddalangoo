package com.ddalangoo.ddalangoo.accessibility

data class AutomationTask(
    val taskId: String,
    val taskType: String,
    val targetProductName: String,
    val searchKeyword: String = "",
    val optionName: String = "",
    val quantity: Int,
    val platform: String,
    val packageName: String?,
    val currentStep: String
)

data class AutomationRuntimeStatus(
    val serviceConnected: Boolean = false,
    val lastPackageName: String? = null,
    val lastStep: String? = null,
    val lastScreenType: String? = null,
    val lastTrigger: String? = null,
    val currentRetryCount: Int = 0,
    val currentRecoveryCount: Int = 0,
    val rawNodeCount: Int = 0,
    val filteredNodeCount: Int = 0,
    val lastActionType: String? = null,
    val lastReasonCode: String? = null,
    val lastTargetNodeId: Int? = null,
    val lastSelectedNodeText: String? = null,
    val lastActionSuccess: Boolean? = null,
    val lastActionMethod: String? = null,
    val lastErrorCode: String? = null,
    val lastMessage: String? = null,
    val aiFallbackSuggested: Boolean = false,
    val fallbackType: String? = null,
    val fallbackReasonCode: String? = null
)

object AutomationTaskStore {
    private var currentTask: AutomationTask? = null
    private var runtimeStatus = AutomationRuntimeStatus()
    private val retryCountsByStep = mutableMapOf<String, Int>()
    private var purchaseHistoryFinishHandled = false
    private var recoveryCount = 0
    private var searchInputFocusRetryCount = 0
    private var searchSubmitRetryCount = 0
    private const val MAX_RETRY_COUNT_PER_STEP = 5
    private const val MAX_RECOVERY_COUNT = 2
    private const val MAX_SEARCH_INPUT_FOCUS_RETRY_COUNT = 2
    private const val MAX_SEARCH_SUBMIT_RETRY_COUNT = 2

    @Synchronized
    fun setTask(task: AutomationTask) {
        currentTask = task
        retryCountsByStep.clear()
        purchaseHistoryFinishHandled = false
        recoveryCount = 0
        searchInputFocusRetryCount = 0
        searchSubmitRetryCount = 0
        runtimeStatus = runtimeStatus.copy(
            lastPackageName = task.packageName,
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
            fallbackReasonCode = null
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
        AutomationLogger.info("task set taskId=${task.taskId} platform=${task.platform} currentStep=${task.currentStep}")
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
        recoveryCount = 0
        searchInputFocusRetryCount = 0
        searchSubmitRetryCount = 0
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
            fallbackReasonCode = null
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
        message: String
    ) {
        val shouldSuggestFallback = reasonCode == "search_submit_not_effective" ||
            reasonCode == "target_product_not_found"
        AutomationLogger.warn(
            "task stopped taskId=${currentTask?.taskId.orEmpty()} reason=$reasonCode " +
                "screenType=$screenType trigger=$trigger message=$message"
        )
        currentTask = null
        retryCountsByStep.clear()
        purchaseHistoryFinishHandled = false
        recoveryCount = 0
        searchInputFocusRetryCount = 0
        searchSubmitRetryCount = 0
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
            fallbackType = if (shouldSuggestFallback) "ui_tree_or_vlm" else null,
            fallbackReasonCode = if (shouldSuggestFallback) reasonCode else null
        )
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
        runtimeStatus = runtimeStatus.copy(
            lastStep = nextStep,
            currentRetryCount = retryCountsByStep[nextStep] ?: 0
        )
        AutomationLogger.info("task updated taskId=${task.taskId} currentStep=${task.currentStep} nextStep=$nextStep")
    }

    @Synchronized
    fun markCompleted(trigger: String, message: String) {
        val task = currentTask ?: return
        currentTask = task.copy(currentStep = AutomationContract.Step.COMPLETED)
        retryCountsByStep.clear()
        searchInputFocusRetryCount = 0
        searchSubmitRetryCount = 0
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
            fallbackReasonCode = null
        )
        AutomationLogger.info("task completed taskId=${task.taskId} trigger=$trigger message=$message")
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
            RuleReasonCode.PRODUCT_CARD.value -> AutomationContract.Step.ADD_TO_CART
            RuleReasonCode.CART_BUTTON.value -> {
                if (task.optionName.isBlank()) AutomationContract.Step.COMPLETED else AutomationContract.Step.SELECT_OPTION
            }
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
    fun statusMap(): Map<String, Any?> {
        val task = currentTask
        val status = runtimeStatus
        return mapOf(
            "hasTask" to (task != null),
            "taskId" to task?.taskId,
            "taskType" to task?.taskType,
            "platform" to task?.platform,
            "searchKeyword" to task?.searchKeyword,
            "targetProductName" to task?.targetProductName,
            "optionName" to task?.optionName,
            "packageName" to task?.packageName,
            "currentStep" to task?.currentStep,
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
            "aiFallbackSuggested" to status.aiFallbackSuggested,
            "fallbackType" to status.fallbackType,
            "fallbackReasonCode" to status.fallbackReasonCode,
            "latestPurchaseHistoryCount" to PurchaseHistoryExtractionStore.latestExtractionResult().size,
            "accumulatedPurchaseHistoryCount" to PurchaseHistoryExtractionStore.accumulatedCandidates().size
        ) + SearchInspectionStore.statusMap()
    }
}
