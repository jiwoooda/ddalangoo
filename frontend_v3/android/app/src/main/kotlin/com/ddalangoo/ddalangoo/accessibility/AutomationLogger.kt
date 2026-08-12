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

    fun purchaseHistoryDump(
        packageName: String?,
        rawNodeCount: Int,
        filteredNodeCount: Int,
        candidateNodes: List<UiNode>
    ) {
        info(
            "purchase_history_dump packageName=${packageName.orEmpty()} " +
                "rawNodeCount=$rawNodeCount filteredNodeCount=$filteredNodeCount " +
                "purchaseHistoryCandidateCount=${candidateNodes.size}"
        )
        candidateNodes.forEach { node ->
            info(
                "purchase_history_candidate nodeId=${node.id} " +
                    "parentId=${node.parentId ?: ""} depth=${node.depth} childCount=${node.childCount} " +
                    "text=${node.primaryText()} role=${node.role.orEmpty()} " +
                    "clickable=${node.clickable} " +
                    "bounds=${node.boundsLeft},${node.boundsTop},${node.boundsRight},${node.boundsBottom} " +
                    "centerX=${node.centerX} centerY=${node.centerY}"
            )
        }
    }

    fun searchInspectionDump(
        packageName: String?,
        snapshot: SearchInspectionSnapshot
    ) {
        info(
            "search_inspection_dump packageName=${packageName.orEmpty()} step=${snapshot.step} " +
                "rawNodeCount=${snapshot.rawNodeCount} filteredNodeCount=${snapshot.filteredNodeCount} " +
                "candidateCount=${snapshot.candidates.size} " +
                "aiFallbackSuggested=${snapshot.aiFallbackSuggested} " +
                "fallbackReasonCode=${snapshot.fallbackReasonCode.orEmpty()}"
        )
        snapshot.candidates.forEach { candidate ->
            info(
                "search_inspection_candidate nodeId=${candidate.nodeId} " +
                    "parentId=${candidate.parentId ?: ""} depth=${candidate.depth} " +
                    "childCount=${candidate.childCount} " +
                    "text=${candidate.previewText()} className=${candidate.className} " +
                    "clickable=${candidate.clickable} editable=${candidate.editable} " +
                    "focusable=${candidate.focusable} price=${candidate.hasPricePattern} " +
                    "unit=${candidate.hasUnitPattern} addToCart=${candidate.hasAddToCartKeyword} " +
                    "bounds=${candidate.boundsLeft},${candidate.boundsTop}," +
                    "${candidate.boundsRight},${candidate.boundsBottom} " +
                    "centerX=${candidate.centerX} centerY=${candidate.centerY}"
            )
        }
        snapshot.productCandidates.forEach { candidate ->
            info(
                "product_candidate productName=${candidate.productName.orEmpty()} " +
                    "price=${candidate.price ?: ""} " +
                    "productNameNodeId=${candidate.productNameNodeId ?: ""} " +
                    "priceNodeId=${candidate.priceNodeId ?: ""} " +
                    "addToCartNodeId=${candidate.addToCartNodeId ?: ""} " +
                    "confidence=${candidate.confidence} reasonCode=${candidate.reasonCode} " +
                    "section=${candidate.section.orEmpty()} rawTexts=${candidate.rawTexts.joinToString("|")}"
            )
        }
    }

    fun parsedPurchaseHistory(
        platform: String?,
        packageName: String?,
        candidates: List<PurchaseHistoryCandidate>
    ) {
        info(
            "parsedPurchaseHistory platform=${platform.orEmpty()} packageName=${packageName.orEmpty()} " +
                "orderGroupCount=${candidates.size} json=${PurchaseHistoryCandidateJsonSerializer.toJson(candidates)}"
        )
    }

    fun accumulatedPurchaseHistory(
        platform: String?,
        packageName: String?,
        mergeResult: PurchaseHistoryMergeResult
    ) {
        info(
            "accumulatedPurchaseHistory platform=${platform.orEmpty()} packageName=${packageName.orEmpty()} " +
                "currentExtractCount=${mergeResult.currentExtractCount} " +
                "accumulatedOrderCount=${mergeResult.accumulatedOrderCount} " +
                "newOrderCount=${mergeResult.newOrderCount} " +
                "updatedOrderCount=${mergeResult.updatedOrderCount} " +
                "duplicateOrderCount=${mergeResult.duplicateOrderCount} " +
                "noProgressExtractCount=${mergeResult.noProgressExtractCount} " +
                "orderNumbers=${mergeResult.orderNumbers.joinToString(prefix = "[", postfix = "]")} " +
                "json=${PurchaseHistoryCandidateJsonSerializer.toJson(mergeResult.accumulatedCandidates)}"
        )
    }

    fun accumulatedPurchaseHistoryFinal(
        platform: String?,
        packageName: String?,
        accumulatedCandidates: List<PurchaseHistoryCandidate>
    ) {
        info(
            "accumulatedPurchaseHistory final=true platform=${platform.orEmpty()} " +
                "packageName=${packageName.orEmpty()} accumulatedOrderCount=${accumulatedCandidates.size} " +
                "json=${PurchaseHistoryCandidateJsonSerializer.toJson(accumulatedCandidates)}"
        )
    }
}
