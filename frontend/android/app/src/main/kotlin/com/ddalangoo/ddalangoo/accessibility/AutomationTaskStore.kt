package com.ddalangoo.ddalangoo.accessibility

data class AutomationTask(
    val taskId: String,
    val taskType: String,
    val targetProductName: String,
    val quantity: Int,
    val platform: String,
    val packageName: String?,
    val currentStep: String
)

data class AutomationRuntimeStatus(
    val serviceConnected: Boolean = false,
    val lastPackageName: String? = null,
    val lastStep: String? = null,
    val rawNodeCount: Int = 0,
    val filteredNodeCount: Int = 0,
    val lastActionType: String? = null,
    val lastReasonCode: String? = null,
    val lastTargetNodeId: Int? = null,
    val lastSelectedNodeText: String? = null,
    val lastActionSuccess: Boolean? = null,
    val lastActionMethod: String? = null,
    val lastErrorCode: String? = null,
    val lastMessage: String? = null
)

object AutomationTaskStore {
    private var currentTask: AutomationTask? = null
    private var runtimeStatus = AutomationRuntimeStatus()

    @Synchronized
    fun setTask(task: AutomationTask) {
        currentTask = task
        runtimeStatus = runtimeStatus.copy(
            lastPackageName = task.packageName,
            lastStep = task.currentStep,
            lastActionType = null,
            lastReasonCode = null,
            lastTargetNodeId = null,
            lastSelectedNodeText = null,
            lastActionSuccess = null,
            lastActionMethod = null,
            lastErrorCode = null,
            lastMessage = "Task is waiting for accessibility events"
        )
        if (
            task.currentStep == AutomationContract.Step.EXTRACT_PURCHASE_HISTORY ||
            task.currentStep == AutomationContract.Step.DUMP_PURCHASE_HISTORY
        ) {
            PurchaseHistoryExtractionStore.clear()
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
        runtimeStatus = runtimeStatus.copy(
            lastStep = null,
            lastActionType = null,
            lastReasonCode = null,
            lastTargetNodeId = null,
            lastSelectedNodeText = null,
            lastActionSuccess = null,
            lastActionMethod = null,
            lastErrorCode = null,
            lastMessage = "Task cleared"
        )
        PurchaseHistoryExtractionStore.clear()
    }

    @Synchronized
    fun updateCurrentStep(nextStep: String) {
        val task = currentTask ?: return
        currentTask = task.copy(currentStep = nextStep)
        runtimeStatus = runtimeStatus.copy(lastStep = nextStep)
        AutomationLogger.info("task updated taskId=${task.taskId} currentStep=${task.currentStep} nextStep=$nextStep")
    }

    @Synchronized
    fun advanceAfterSuccess(actionPlan: ActionPlan) {
        val task = currentTask ?: return
        val nextStep = when (actionPlan.reasonCode) {
            RuleReasonCode.POPUP_DISMISS.value -> task.currentStep
            RuleReasonCode.SEARCH_INPUT.value -> AutomationContract.Step.SEARCH_SUBMIT
            RuleReasonCode.SEARCH_BUTTON.value -> AutomationContract.Step.SELECT_PRODUCT
            RuleReasonCode.PRODUCT_CARD.value -> AutomationContract.Step.ADD_TO_CART
            RuleReasonCode.CART_BUTTON.value -> AutomationContract.Step.COMPLETED
            RuleReasonCode.MY_COUPANG.value -> AutomationContract.Step.OPEN_ORDER_HISTORY
            RuleReasonCode.MY_KURLY.value -> AutomationContract.Step.OPEN_ORDER_HISTORY
            RuleReasonCode.ORDER_HISTORY.value -> AutomationContract.Step.DUMP_PURCHASE_HISTORY
            RuleReasonCode.PURCHASE_HISTORY_DUMP.value -> when (task.currentStep) {
                AutomationContract.Step.EXTRACT_PURCHASE_HISTORY -> AutomationContract.Step.SCROLL_PURCHASE_HISTORY
                AutomationContract.Step.DUMP_PURCHASE_HISTORY -> task.currentStep
                else -> task.currentStep
            }
            RuleReasonCode.PURCHASE_HISTORY_SCROLL.value -> AutomationContract.Step.EXTRACT_PURCHASE_HISTORY
            RuleReasonCode.PURCHASE_HISTORY_FINISH.value -> AutomationContract.Step.FINISH_PURCHASE_HISTORY
            else -> task.currentStep
        }
        currentTask = task.copy(currentStep = nextStep)
        runtimeStatus = runtimeStatus.copy(lastStep = nextStep)
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
        filteredNodeCount: Int
    ) {
        runtimeStatus = runtimeStatus.copy(
            lastPackageName = packageName,
            lastStep = currentStep,
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
        targetPackageName: String
    ) {
        runtimeStatus = runtimeStatus.copy(
            lastPackageName = packageName,
            lastStep = currentStep,
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
    fun recordAction(
        actionPlan: ActionPlan,
        actionResult: ActionResult,
        selectedNode: UiNode?
    ) {
        runtimeStatus = runtimeStatus.copy(
            lastActionType = actionPlan.actionType,
            lastReasonCode = actionPlan.reasonCode,
            lastTargetNodeId = actionPlan.targetNodeId,
            lastSelectedNodeText = selectedNode?.primaryText(),
            lastActionSuccess = actionResult.success,
            lastActionMethod = actionResult.method,
            lastErrorCode = actionResult.errorCode,
            lastMessage = actionResult.message
        )
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
            "packageName" to task?.packageName,
            "currentStep" to task?.currentStep,
            "serviceConnected" to status.serviceConnected,
            "lastPackageName" to status.lastPackageName,
            "lastStep" to status.lastStep,
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
            "latestPurchaseHistoryCount" to PurchaseHistoryExtractionStore.latestExtractionResult().size,
            "accumulatedPurchaseHistoryCount" to PurchaseHistoryExtractionStore.accumulatedCandidates().size
        )
    }
}
