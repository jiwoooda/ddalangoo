package com.ddalangoo.ddalangoo.accessibility

import android.util.Log

object AutomationLogger {
    private const val TAG = "DdalangooA11y"

    fun debug(message: String) {
        Log.d(TAG, message)
    }

    fun info(message: String) {
        Log.i(TAG, message)
    }

    fun warn(message: String) {
        Log.w(TAG, message)
    }

    fun error(message: String, throwable: Throwable? = null) {
        if (throwable == null) {
            Log.e(TAG, message)
        } else {
            Log.e(TAG, message, throwable)
        }
    }

    fun validation(
        platform: String?,
        packageName: String?,
        currentStep: String?,
        rawNodeCount: Int,
        filteredNodeCount: Int,
        actionPlan: ActionPlan?,
        actionResult: ActionResult?,
        selectedNode: UiNode?
    ) {
        info(
            listOf(
                "platform=${platform.orEmpty()}",
                "packageName=${packageName.orEmpty()}",
                "currentStep=${currentStep.orEmpty()}",
                "rawNodeCount=$rawNodeCount",
                "filteredNodeCount=$filteredNodeCount",
                "targetNodeFound=${selectedNode != null}",
                "selectedNodeText=${selectedNode?.primaryText().orEmpty()}",
                "actionType=${actionPlan?.actionType.orEmpty()}",
                "performActionSuccess=${actionResult?.method == ActionExecutionMethod.TARGET_ACTION.value}",
                "parentActionSuccess=${actionResult?.method == ActionExecutionMethod.PARENT_ACTION.value}",
                "dispatchGestureUsed=${actionResult?.method == ActionExecutionMethod.DISPATCH_GESTURE.value}",
                "finalSuccess=${actionResult?.success ?: false}",
                "errorCode=${actionResult?.errorCode.orEmpty()}"
            ).joinToString(prefix = "validation ", separator = " ")
        )
    }
}
