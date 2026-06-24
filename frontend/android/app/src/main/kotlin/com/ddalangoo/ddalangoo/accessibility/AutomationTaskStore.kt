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
    }

    @Synchronized
    fun advanceAfterSuccess(actionPlan: ActionPlan) {
        val task = currentTask ?: return
        val nextStep = when (actionPlan.reasonCode) {
            RuleReasonCode.POPUP_DISMISS.value -> task.currentStep
            RuleReasonCode.SEARCH_INPUT.value -> "search_submit"
            RuleReasonCode.SEARCH_BUTTON.value -> "select_product"
            RuleReasonCode.PRODUCT_CARD.value -> "add_to_cart"
            RuleReasonCode.CART_BUTTON.value -> "completed"
            RuleReasonCode.MY_COUPANG.value -> "open_order_history"
            RuleReasonCode.MY_KURLY.value -> "open_order_history"
            RuleReasonCode.ORDER_HISTORY.value -> "dump_purchase_history"
            else -> task.currentStep
        }
        currentTask = task.copy(currentStep = nextStep)
        AutomationLogger.info("task advanced taskId=${task.taskId} currentStep=${task.currentStep} nextStep=$nextStep")
    }
}
