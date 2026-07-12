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

object AutomationTaskStore {
    private var currentTask: AutomationTask? = null

    @Synchronized
    fun setTask(task: AutomationTask) {
        currentTask = task
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
        PurchaseHistoryExtractionStore.clear()
    }

    @Synchronized
    fun updateCurrentStep(nextStep: String) {
        val task = currentTask ?: return
        currentTask = task.copy(currentStep = nextStep)
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
        AutomationLogger.info("task advanced taskId=${task.taskId} currentStep=${task.currentStep} nextStep=$nextStep")
    }

    @Synchronized
    fun statusMap(): Map<String, Any?> {
        val task = currentTask
        return mapOf(
            "hasTask" to (task != null),
            "taskId" to task?.taskId,
            "taskType" to task?.taskType,
            "platform" to task?.platform,
            "packageName" to task?.packageName,
            "currentStep" to task?.currentStep,
            "latestPurchaseHistoryCount" to PurchaseHistoryExtractionStore.latestExtractionResult().size,
            "accumulatedPurchaseHistoryCount" to PurchaseHistoryExtractionStore.accumulatedCandidates().size
        )
    }
}
