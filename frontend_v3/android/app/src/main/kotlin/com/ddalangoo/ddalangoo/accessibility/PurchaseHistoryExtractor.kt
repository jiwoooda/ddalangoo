package com.ddalangoo.ddalangoo.accessibility

import java.time.LocalDate
import org.json.JSONArray
import org.json.JSONObject

data class PurchaseHistoryCandidate(
    val platform: String,
    val orderNumber: String?,
    val purchaseDate: String?,
    val deliveryStatus: String?,
    val deliveryTypes: List<String>,
    val productNames: List<String>,
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
    private val purchaseDateLikeRegex = Regex("""(\d{1,2})\.(\d{1,2})\([월화수목금토일]\)\s*(\d{1,2}):(\d{2})""")
    private val deliveryStatusKeywords = listOf("배송완료", "배송 완료", "주문완료", "주문 완료")
    private val deliveryTypeKeywords = listOf("샛별배송", "하루배송", "택배배송")
    private val productNameSkipKeywords = listOf(
        "주문번호",
        "배송완료",
        "배송 완료",
        "주문완료",
        "주문 완료",
        "샛별배송",
        "하루배송",
        "택배배송",
        "배송조회",
        "장바구니",
        "담기",
        "재구매",
        "펼쳐보기",
        "펼치기",
        "반품 접수",
        "후기 작성",
        "배송조회",
        "__next",
        "route-announcer"
    )
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
        val purchaseDate = groupNodes
            .mapNotNull { node -> normalizeKurlyPurchaseDate(node.primaryText()) }
            .firstOrNull()
        val deliveryTypes = groupNodes
            .map { node -> node.primaryText() }
            .filter { text -> deliveryTypeKeywords.any { keyword -> text.contains(keyword) } }
            .distinct()
        val prices = groupNodes
            .flatMap { node -> priceRegex.findAll(node.primaryText()).map { match -> match.value }.toList() }
            .distinct()
        val productNames = groupNodes
            .map { node -> node.primaryText().trim() }
            .filter { text -> isLikelyProductName(text) }
            .distinct()

        val meaningfulNodes = groupNodes.filter { node ->
            node.id == orderNumberNode.id ||
                node.id == statusNode?.id ||
                deliveryTypes.any { deliveryType -> node.primaryText().contains(deliveryType) } ||
                prices.any { price -> node.primaryText().contains(price) } ||
                productNames.any { productName -> node.primaryText().contains(productName) }
        }
        val boundsNodes = meaningfulNodes.ifEmpty { groupNodes }

        return PurchaseHistoryCandidate(
            platform = "kurly",
            orderNumber = orderNumber,
            purchaseDate = purchaseDate,
            deliveryStatus = statusNode?.primaryText(),
            deliveryTypes = deliveryTypes,
            productNames = productNames,
            prices = prices,
            nodeIds = boundsNodes.map { node -> node.id }.distinct(),
            boundsLeft = boundsNodes.minOf { node -> node.boundsLeft },
            boundsTop = boundsNodes.minOf { node -> node.boundsTop },
            boundsRight = boundsNodes.maxOf { node -> node.boundsRight },
            boundsBottom = boundsNodes.maxOf { node -> node.boundsBottom },
            centerY = (boundsNodes.minOf { node -> node.boundsTop } + boundsNodes.maxOf { node -> node.boundsBottom }) / 2
        )
    }

    private fun isLikelyProductName(text: String): Boolean {
        if (text.length < 4) return false
        if (orderNumberRegex.containsMatchIn(text)) return false
        if (priceRegex.matches(text)) return false
        if (purchaseDateLikeRegex.containsMatchIn(text)) return false
        if (productNameSkipKeywords.any { keyword -> text.contains(keyword) }) return false
        if (text.all { character -> character.isDigit() || character.isWhitespace() }) return false
        return text.contains("[") || text.contains("]")
    }

    private fun normalizeKurlyPurchaseDate(text: String): String? {
        val match = purchaseDateLikeRegex.find(text) ?: return null
        val month = match.groupValues[1].toIntOrNull() ?: return null
        val day = match.groupValues[2].toIntOrNull() ?: return null
        val hour = match.groupValues[3].toIntOrNull() ?: return null
        val minute = match.groupValues[4].toIntOrNull() ?: return null
        val today = LocalDate.now()
        var date = LocalDate.of(today.year, month, day)

        // 화면에는 연도가 없으므로 현재 연도를 기본으로 쓴다.
        // 단, 현재 날짜보다 미래로 해석되면 작년 구매로 본다.
        if (date.isAfter(today)) {
            date = date.minusYears(1)
        }
        return "%04d-%02d-%02dT%02d:%02d:00+09:00".format(
            date.year,
            date.monthValue,
            date.dayOfMonth,
            hour,
            minute
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
                    .put("purchaseDate", candidate.purchaseDate.orEmpty())
                    .put("deliveryStatus", candidate.deliveryStatus.orEmpty())
                    .put("deliveryTypes", JSONArray(candidate.deliveryTypes))
                    .put("productNames", JSONArray(candidate.productNames))
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
    val updatedOrderCount: Int,
    val duplicateOrderCount: Int,
    val noProgressExtractCount: Int,
    val orderNumbers: List<String>,
    val accumulatedCandidates: List<PurchaseHistoryCandidate>
)

object PurchaseHistoryExtractionStore {
    private val accumulatedCandidatesByOrderNumber = linkedMapOf<String, PurchaseHistoryCandidate>()
    private var latestExtractionResult: List<PurchaseHistoryCandidate> = emptyList()
    private var noProgressExtractCount = 0

    @Synchronized
    fun merge(extractedCandidates: List<PurchaseHistoryCandidate>): PurchaseHistoryMergeResult {
        latestExtractionResult = extractedCandidates

        var newOrderCount = 0
        var updatedOrderCount = 0
        var duplicateOrderCount = 0
        extractedCandidates.forEach { candidate ->
            val orderNumber = candidate.orderNumber
            if (orderNumber.isNullOrBlank()) return@forEach

            val existingCandidate = accumulatedCandidatesByOrderNumber[orderNumber]
            if (existingCandidate != null) {
                val mergedCandidate = mergeCandidate(existingCandidate, candidate)
                if (mergedCandidate != existingCandidate) {
                    accumulatedCandidatesByOrderNumber[orderNumber] = mergedCandidate
                    updatedOrderCount += 1
                }
                duplicateOrderCount += 1
            } else {
                accumulatedCandidatesByOrderNumber[orderNumber] = candidate
                newOrderCount += 1
            }
        }
        if (newOrderCount == 0 && updatedOrderCount == 0) {
            noProgressExtractCount += 1
        } else {
            noProgressExtractCount = 0
        }

        return PurchaseHistoryMergeResult(
            currentExtractCount = extractedCandidates.size,
            accumulatedOrderCount = accumulatedCandidatesByOrderNumber.size,
            newOrderCount = newOrderCount,
            updatedOrderCount = updatedOrderCount,
            duplicateOrderCount = duplicateOrderCount,
            noProgressExtractCount = noProgressExtractCount,
            orderNumbers = accumulatedCandidatesByOrderNumber.keys.toList(),
            accumulatedCandidates = accumulatedCandidatesByOrderNumber.values.toList()
        )
    }

    private fun mergeCandidate(
        existingCandidate: PurchaseHistoryCandidate,
        newCandidate: PurchaseHistoryCandidate
    ): PurchaseHistoryCandidate {
        val mergedDeliveryTypes = (existingCandidate.deliveryTypes + newCandidate.deliveryTypes).distinct()
        val mergedProductNames = (existingCandidate.productNames + newCandidate.productNames).distinct()
        val mergedPrices = (existingCandidate.prices + newCandidate.prices).distinct()
        val mergedNodeIds = (existingCandidate.nodeIds + newCandidate.nodeIds).distinct()

        return existingCandidate.copy(
            purchaseDate = existingCandidate.purchaseDate ?: newCandidate.purchaseDate,
            deliveryStatus = existingCandidate.deliveryStatus ?: newCandidate.deliveryStatus,
            deliveryTypes = mergedDeliveryTypes,
            productNames = mergedProductNames,
            prices = mergedPrices,
            nodeIds = mergedNodeIds,
            boundsLeft = minOf(existingCandidate.boundsLeft, newCandidate.boundsLeft),
            boundsTop = minOf(existingCandidate.boundsTop, newCandidate.boundsTop),
            boundsRight = maxOf(existingCandidate.boundsRight, newCandidate.boundsRight),
            boundsBottom = maxOf(existingCandidate.boundsBottom, newCandidate.boundsBottom),
            centerY = (
                minOf(existingCandidate.boundsTop, newCandidate.boundsTop) +
                    maxOf(existingCandidate.boundsBottom, newCandidate.boundsBottom)
                ) / 2
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
        noProgressExtractCount = 0
    }
}
