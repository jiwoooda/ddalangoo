package com.ddalangoo.ddalangoo.accessibility

import android.accessibilityservice.AccessibilityService
import android.view.accessibility.AccessibilityEvent

class DdalangooAccessibilityService : AccessibilityService() {
    private val uiTreeCollector = UiTreeCollector()
    private val uiNodeSerializer = UiNodeSerializer()
    private val ruleBasedPlanner = RuleBasedPlanner()
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

        val actionPlan = ruleBasedPlanner.plan(filteredNodes, task)
        val selectedNode = actionPlan.targetNodeId?.let { targetNodeId ->
            filteredNodes.firstOrNull { node -> node.id == targetNodeId }
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
        } else if (actionResult.success) {
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
}
