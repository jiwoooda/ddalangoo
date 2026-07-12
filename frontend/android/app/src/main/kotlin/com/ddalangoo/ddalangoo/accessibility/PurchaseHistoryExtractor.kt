package com.ddalangoo.ddalangoo.accessibility

import org.json.JSONArray
import org.json.JSONObject

data class PurchaseHistoryCandidate(
    val platform: String,
    val orderNumber: String?,
    val deliveryStatus: String?,
    val deliveryTypes: List<String>,
    val prices: List<String>,
    val nodeIds: List<Int>,
    val boundsLeft: Int,
    val boundsTop: Int,
    val boundsRight: Int,
    val boundsBottom: Int,
    val centerY: Int
)

interface PurchaseHistoryExtractor {
    fun extract(filteredNodes: List<UiNode>): List<PurchaseHistoryCandidate>
}

class KurlyPurchaseHistoryExtractor : PurchaseHistoryExtractor {
    private val orderNumberRegex = Regex("주문번호\\s*([0-9]+)")
    private val priceRegex = Regex("\\d{1,3}(,\\d{3})*원")
    private val deliveryStatusKeywords = listOf("배송완료", "배송 완료", "주문완료", "주문 완료")
    private val deliveryTypeKeywords = listOf("샛별배송", "하루배송", "택배배송")

    override fun extract(filteredNodes: List<UiNode>): List<PurchaseHistoryCandidate> {
        val orderNumberNodes = filteredNodes
            .filter { node -> orderNumberRegex.containsMatchIn(node.primaryText()) }
            .sortedBy { node -> node.centerY }

        if (orderNumberNodes.isEmpty()) return emptyList()

        return orderNumberNodes.mapIndexedNotNull { index, orderNumberNode ->
            val nextOrderTop = orderNumberNodes.getOrNull(index + 1)?.boundsTop ?: Int.MAX_VALUE
            val groupNodes = filteredNodes
                .filter { node -> node.centerY >= orderNumberNode.centerY && node.boundsTop < nextOrderTop }
                .sortedWith(compareBy<UiNode> { it.boundsTop }.thenBy { it.boundsLeft })

            buildCandidate(orderNumberNode, groupNodes)
        }
    }

    private fun buildCandidate(orderNumberNode: UiNode, groupNodes: List<UiNode>): PurchaseHistoryCandidate? {
        val orderNumber = orderNumberRegex.find(orderNumberNode.primaryText())?.groupValues?.getOrNull(1)
        if (orderNumber.isNullOrBlank()) return null

        val statusNode = groupNodes.firstOrNull { node ->
            deliveryStatusKeywords.any { keyword -> node.primaryText().contains(keyword) }
        }
        val deliveryTypes = groupNodes
            .map { node -> node.primaryText() }
            .filter { text -> deliveryTypeKeywords.any { keyword -> text.contains(keyword) } }
            .distinct()
        val prices = groupNodes
            .flatMap { node -> priceRegex.findAll(node.primaryText()).map { match -> match.value }.toList() }
            .distinct()

        val meaningfulNodes = groupNodes.filter { node ->
            node.id == orderNumberNode.id ||
                node.id == statusNode?.id ||
                deliveryTypes.any { deliveryType -> node.primaryText().contains(deliveryType) } ||
                prices.any { price -> node.primaryText().contains(price) }
        }
        val boundsNodes = meaningfulNodes.ifEmpty { groupNodes }

        return PurchaseHistoryCandidate(
            platform = "kurly",
            orderNumber = orderNumber,
            deliveryStatus = statusNode?.primaryText(),
            deliveryTypes = deliveryTypes,
            prices = prices,
            nodeIds = boundsNodes.map { node -> node.id }.distinct(),
            boundsLeft = boundsNodes.minOf { node -> node.boundsLeft },
            boundsTop = boundsNodes.minOf { node -> node.boundsTop },
            boundsRight = boundsNodes.maxOf { node -> node.boundsRight },
            boundsBottom = boundsNodes.maxOf { node -> node.boundsBottom },
            centerY = (boundsNodes.minOf { node -> node.boundsTop } + boundsNodes.maxOf { node -> node.boundsBottom }) / 2
        )
    }
}

class CoupangPurchaseHistoryExtractor : PurchaseHistoryExtractor {
    override fun extract(filteredNodes: List<UiNode>): List<PurchaseHistoryCandidate> {
        // 쿠팡 구매이력 parser는 다음 단계에서 플랫폼별 구조를 확정한 뒤 구현한다.
        return emptyList()
    }
}

object PurchaseHistoryCandidateJsonSerializer {
    fun toJson(candidates: List<PurchaseHistoryCandidate>): String {
        val jsonCandidates = JSONArray()
        candidates.forEach { candidate ->
            jsonCandidates.put(
                JSONObject()
                    .put("platform", candidate.platform)
                    .put("orderNumber", candidate.orderNumber.orEmpty())
                    .put("deliveryStatus", candidate.deliveryStatus.orEmpty())
                    .put("deliveryTypes", JSONArray(candidate.deliveryTypes))
                    .put("prices", JSONArray(candidate.prices))
                    .put("nodeIds", JSONArray(candidate.nodeIds))
                    .put(
                        "bounds",
                        JSONObject()
                            .put("left", candidate.boundsLeft)
                            .put("top", candidate.boundsTop)
                            .put("right", candidate.boundsRight)
                            .put("bottom", candidate.boundsBottom)
                    )
                    .put("centerY", candidate.centerY)
            )
        }
        return jsonCandidates.toString(2)
    }
}

data class PurchaseHistoryMergeResult(
    val currentExtractCount: Int,
    val accumulatedOrderCount: Int,
    val newOrderCount: Int,
    val duplicateOrderCount: Int,
    val orderNumbers: List<String>,
    val accumulatedCandidates: List<PurchaseHistoryCandidate>
)

object PurchaseHistoryExtractionStore {
    private val accumulatedCandidatesByOrderNumber = linkedMapOf<String, PurchaseHistoryCandidate>()
    private var latestExtractionResult: List<PurchaseHistoryCandidate> = emptyList()

    @Synchronized
    fun merge(extractedCandidates: List<PurchaseHistoryCandidate>): PurchaseHistoryMergeResult {
        latestExtractionResult = extractedCandidates

        var newOrderCount = 0
        var duplicateOrderCount = 0
        extractedCandidates.forEach { candidate ->
            val orderNumber = candidate.orderNumber
            if (orderNumber.isNullOrBlank()) return@forEach

            if (accumulatedCandidatesByOrderNumber.containsKey(orderNumber)) {
                duplicateOrderCount += 1
            } else {
                accumulatedCandidatesByOrderNumber[orderNumber] = candidate
                newOrderCount += 1
            }
        }

        return PurchaseHistoryMergeResult(
            currentExtractCount = extractedCandidates.size,
            accumulatedOrderCount = accumulatedCandidatesByOrderNumber.size,
            newOrderCount = newOrderCount,
            duplicateOrderCount = duplicateOrderCount,
            orderNumbers = accumulatedCandidatesByOrderNumber.keys.toList(),
            accumulatedCandidates = accumulatedCandidatesByOrderNumber.values.toList()
        )
    }

    @Synchronized
    fun latestExtractionResult(): List<PurchaseHistoryCandidate> {
        return latestExtractionResult
    }

    @Synchronized
    fun accumulatedCandidates(): List<PurchaseHistoryCandidate> {
        return accumulatedCandidatesByOrderNumber.values.toList()
    }

    @Synchronized
    fun accumulatedCandidatesJson(): String {
        return PurchaseHistoryCandidateJsonSerializer.toJson(accumulatedCandidatesByOrderNumber.values.toList())
    }

    @Synchronized
    fun clear() {
        latestExtractionResult = emptyList()
        accumulatedCandidatesByOrderNumber.clear()
    }
}
