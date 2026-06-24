package com.ddalangoo.ddalangoo.accessibility

import android.accessibilityservice.AccessibilityService
import android.accessibilityservice.GestureDescription
import android.graphics.Path
import android.os.Bundle
import android.view.accessibility.AccessibilityNodeInfo

data class ActionResult(
    val success: Boolean,
    val method: String,
    val errorCode: String?,
    val message: String
)

enum class ActionExecutionMethod(val value: String) {
    TARGET_ACTION("target_action"),
    PARENT_ACTION("parent_action"),
    DISPATCH_GESTURE("dispatch_gesture"),
    SET_TEXT("set_text"),
    SCROLL("scroll"),
    NONE("none")
}

class ActionExecutor(private val service: AccessibilityService) {
    fun execute(actionPlan: ActionPlan, nodes: List<UiNode>): ActionResult {
        val targetNode = actionPlan.targetNodeId?.let { targetNodeId ->
            nodes.firstOrNull { node -> node.id == targetNodeId }
        }

        return when (actionPlan.actionType) {
            AutomationActionType.CLICK.value -> executeClick(targetNode)
            AutomationActionType.INPUT_TEXT.value -> executeInputText(targetNode, actionPlan.textToInput.orEmpty())
            AutomationActionType.SCROLL.value -> executeScroll(targetNode)
            AutomationActionType.DUMP_PURCHASE_HISTORY.value -> ActionResult(
                success = true,
                method = ActionExecutionMethod.NONE.value,
                errorCode = null,
                message = "Purchase history candidates dumped"
            )
            AutomationActionType.STOP_FOR_SENSITIVE_SCREEN.value -> ActionResult(
                success = false,
                method = ActionExecutionMethod.NONE.value,
                errorCode = "SENSITIVE_SCREEN",
                message = "Sensitive screen detected. Automation stopped."
            )
            AutomationActionType.NO_TARGET_FOUND.value -> ActionResult(
                success = false,
                method = ActionExecutionMethod.NONE.value,
                errorCode = "NO_TARGET_FOUND",
                message = "No target node found for reason=${actionPlan.reasonCode}"
            )
            else -> ActionResult(
                success = false,
                method = ActionExecutionMethod.NONE.value,
                errorCode = "UNSUPPORTED_ACTION",
                message = "Unsupported actionType=${actionPlan.actionType}"
            )
        }
    }

    private fun executeClick(targetNode: UiNode?): ActionResult {
        val sourceNode = targetNode?.sourceNode
            ?: return missingNodeResult()

        // 클릭은 target -> clickable parent -> bounds 중심 gesture 순서로 점진적으로 보완한다.
        if (sourceNode.performAction(AccessibilityNodeInfo.ACTION_CLICK)) {
            return ActionResult(
                success = true,
                method = ActionExecutionMethod.TARGET_ACTION.value,
                errorCode = null,
                message = "Clicked target node id=${targetNode.id}"
            )
        }

        val clickableParent = findClickableParent(sourceNode)
        if (clickableParent?.performAction(AccessibilityNodeInfo.ACTION_CLICK) == true) {
            return ActionResult(
                success = true,
                method = ActionExecutionMethod.PARENT_ACTION.value,
                errorCode = null,
                message = "Clicked clickable parent for node id=${targetNode.id}"
            )
        }

        return dispatchTap(targetNode)
    }

    private fun executeInputText(targetNode: UiNode?, textToInput: String): ActionResult {
        val sourceNode = targetNode?.sourceNode
            ?: return missingNodeResult()

        sourceNode.performAction(AccessibilityNodeInfo.ACTION_FOCUS)
        val arguments = Bundle().apply {
            putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, textToInput)
        }

        return if (sourceNode.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, arguments)) {
            ActionResult(
                success = true,
                method = ActionExecutionMethod.SET_TEXT.value,
                errorCode = null,
                message = "Input text into node id=${targetNode.id}"
            )
        } else {
            ActionResult(
                success = false,
                method = ActionExecutionMethod.SET_TEXT.value,
                errorCode = "SET_TEXT_FAILED",
                message = "Failed to set text into node id=${targetNode.id}"
            )
        }
    }

    private fun executeScroll(targetNode: UiNode?): ActionResult {
        val sourceNode = targetNode?.sourceNode
            ?: return missingNodeResult()

        return if (sourceNode.performAction(AccessibilityNodeInfo.ACTION_SCROLL_FORWARD)) {
            ActionResult(
                success = true,
                method = ActionExecutionMethod.SCROLL.value,
                errorCode = null,
                message = "Scrolled node id=${targetNode.id}"
            )
        } else {
            ActionResult(
                success = false,
                method = ActionExecutionMethod.SCROLL.value,
                errorCode = "SCROLL_FAILED",
                message = "Failed to scroll node id=${targetNode.id}"
            )
        }
    }

    private fun dispatchTap(targetNode: UiNode): ActionResult {
        val tapPath = Path().apply {
            moveTo(targetNode.centerX.toFloat(), targetNode.centerY.toFloat())
        }
        val gesture = GestureDescription.Builder()
            .addStroke(GestureDescription.StrokeDescription(tapPath, 0L, 80L))
            .build()

        val dispatched = service.dispatchGesture(gesture, null, null)
        return if (dispatched) {
            ActionResult(
                success = true,
                method = ActionExecutionMethod.DISPATCH_GESTURE.value,
                errorCode = null,
                message = "Dispatched tap at ${targetNode.centerX},${targetNode.centerY}"
            )
        } else {
            ActionResult(
                success = false,
                method = ActionExecutionMethod.DISPATCH_GESTURE.value,
                errorCode = "GESTURE_DISPATCH_FAILED",
                message = "Failed to dispatch tap at ${targetNode.centerX},${targetNode.centerY}"
            )
        }
    }

    private fun findClickableParent(sourceNode: AccessibilityNodeInfo): AccessibilityNodeInfo? {
        var parentNode = sourceNode.parent
        while (parentNode != null) {
            if (parentNode.isClickable && parentNode.isEnabled) return parentNode
            parentNode = parentNode.parent
        }
        return null
    }

    private fun missingNodeResult(): ActionResult {
        return ActionResult(
            success = false,
            method = ActionExecutionMethod.NONE.value,
            errorCode = "TARGET_NODE_MISSING",
            message = "Target node is missing"
        )
    }
}
