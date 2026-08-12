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
    val quantities: List<Int> = emptyList(),
    val nodeIds: List<Int>,
    val boundsLeft: Int,
    val boundsTop: Int,
    val boundsRight: Int,
    val boundsBottom: Int,
    val centerY: Int,
    val thumbnailPath: String? = null
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
    private val purchaseDateRegex = Regex("""^(\d{4})\.\s*(\d{1,2})\.\s*(\d{1,2})$""")
    private val arrivalDateRegex = Regex("""\d{1,2}/\d{1,2}\([월화수목금토일]\)\s*도착""")
    private val priceAndQuantityRegex = Regex("""(.+?)\s+(\d{1,3}(?:,\d{3})*)\s*원\s+(\d+)\s*개$""")
    private val deliveryStatusKeywords = listOf("배송완료", "배송중", "배송 준비중", "주문완료", "반품완료", "취소완료")
    private val deliveryTypeMap = listOf(
        "ROCKET_MERCHANT" to "판매자로켓",
        "LOGO_WOW" to "와우",
        "WOW" to "와우",
        "ROCKET" to "로켓배송"
    )
    private val productNameSkipKeywords = listOf(
        "장바구니",
        "바로구매",
        "배송 · 주문 관리",
        "배송 주문 관리",
        "주문내역",
        "주문목록",
        "검색",
        "홈",
        "마이쿠팡"
    )

    override fun extract(filteredNodes: List<UiNode>): List<PurchaseHistoryCandidate> {
        val sortedNodes = filteredNodes
            .filter { node -> isVisiblePurchaseHistoryNode(node) }
            .sortedWith(compareBy<UiNode> { it.boundsTop }.thenBy { it.boundsLeft })
        val dateNodes = sortedNodes
            .filter { node -> purchaseDateRegex.matches(node.primaryText().trim()) }

        val productNodes = sortedNodes
            .filter { node -> parseProductSummary(rawProductText(node)).isValid }

        if (productNodes.isEmpty()) return emptyList()

        return productNodes.mapNotNull { productNode ->
            val productSummary = parseProductSummary(rawProductText(productNode))
            if (!productSummary.isValid) return@mapNotNull null

            val purchaseDateNode = dateNodes
                .filter { dateNode -> dateNode.centerY <= productNode.centerY }
                .maxByOrNull { dateNode -> dateNode.centerY }
                ?: dateNodes.minByOrNull { dateNode -> kotlin.math.abs(dateNode.centerY - productNode.centerY) }
            val groupTop = purchaseDateNode?.centerY ?: maxOf(0, productNode.centerY - 360)
            val groupBottom = productNode.boundsBottom + 220
            val groupNodes = sortedNodes.filter { node ->
                node.centerY in groupTop..groupBottom
            }
            val deliveryStatus = groupNodes
                .map { node -> node.primaryText().trim() }
                .firstOrNull { text -> deliveryStatusKeywords.any { keyword -> text.contains(keyword) } }
            val deliveryTypes = groupNodes
                .mapNotNull { node -> deliveryTypeFrom(rawNodeText(node)) }
                .distinct()
            val purchaseDate = purchaseDateNode?.primaryText()?.let { normalizeCoupangPurchaseDate(it) }
                ?: return@mapNotNull null
            val orderNumber = buildSyntheticOrderNumber(
                purchaseDate = purchaseDate,
                productName = productSummary.productName,
            )
            val boundsNodes = groupNodes.filter { node ->
                node.id == purchaseDateNode?.id ||
                    node.id == productNode.id ||
                    deliveryStatus != null && node.primaryText().contains(deliveryStatus)
            }.ifEmpty { listOf(productNode) }

            PurchaseHistoryCandidate(
                platform = "coupang",
                orderNumber = orderNumber,
                purchaseDate = purchaseDate,
                deliveryStatus = deliveryStatus,
                deliveryTypes = deliveryTypes,
                productNames = listOf(productSummary.productName),
                prices = listOf(productSummary.price),
                quantities = listOf(productSummary.quantity),
                nodeIds = boundsNodes.map { node -> node.id }.distinct(),
                boundsLeft = boundsNodes.minOf { node -> node.boundsLeft },
                boundsTop = boundsNodes.minOf { node -> node.boundsTop },
                boundsRight = boundsNodes.maxOf { node -> node.boundsRight },
                boundsBottom = boundsNodes.maxOf { node -> node.boundsBottom },
                centerY = (boundsNodes.minOf { node -> node.boundsTop } + boundsNodes.maxOf { node -> node.boundsBottom }) / 2
            )
        }
    }

    private data class ProductSummary(
        val productName: String = "",
        val price: String = "",
        val quantity: Int = 1
    ) {
        val isValid: Boolean
            get() = productName.isNotBlank() && price.isNotBlank()
    }

    private fun parseProductSummary(rawText: String?): ProductSummary {
        val text = rawText?.trim().orEmpty()
        if (text.isBlank()) return ProductSummary()
        val match = priceAndQuantityRegex.find(text) ?: return ProductSummary()
        val productName = match.groupValues[1].trim()
        val price = "${match.groupValues[2]} 원"
        val quantity = match.groupValues[3].toIntOrNull() ?: 1
        if (!isLikelyCoupangProductName(productName)) return ProductSummary()
        return ProductSummary(productName = productName, price = price, quantity = quantity)
    }

    private fun isVisiblePurchaseHistoryNode(node: UiNode): Boolean {
        if (!node.visibleToUser || !node.enabled) return false
        if (node.width <= 0 || node.height <= 0) return false
        if (node.boundsRight <= 0 || node.boundsBottom <= 0) return false
        if (node.boundsBottom <= 220) return false
        if (node.boundsTop >= 2300) return false
        return true
    }

    private fun isLikelyCoupangProductName(productName: String): Boolean {
        if (productName.length < 2) return false
        if (productNameSkipKeywords.any { keyword -> productName.contains(keyword) }) return false
        if (arrivalDateRegex.containsMatchIn(productName)) return false
        if (purchaseDateRegex.matches(productName)) return false
        if (productName.all { character -> character.isDigit() || character.isWhitespace() }) return false
        return true
    }

    private fun rawProductText(node: UiNode): String {
        return node.contentDescription?.takeIf { it.isNotBlank() }
            ?: node.text.orEmpty()
    }

    private fun rawNodeText(node: UiNode): String {
        return listOfNotNull(node.text, node.contentDescription, node.viewIdResourceName)
            .joinToString(" ")
            .trim()
    }

    private fun normalizeCoupangPurchaseDate(rawText: String): String? {
        val match = purchaseDateRegex.find(rawText.trim()) ?: return null
        val year = match.groupValues[1].toIntOrNull() ?: return null
        val month = match.groupValues[2].toIntOrNull() ?: return null
        val day = match.groupValues[3].toIntOrNull() ?: return null
        return "%04d-%02d-%02dT00:00:00+09:00".format(year, month, day)
    }

    private fun deliveryTypeFrom(rawText: String?): String? {
        val text = rawText?.trim().orEmpty()
        if (text.isBlank()) return null
        if (arrivalDateRegex.containsMatchIn(text)) return null
        return deliveryTypeMap
            .firstOrNull { (keyword, _) -> text.contains(keyword, ignoreCase = true) }
            ?.second
    }

    private fun buildSyntheticOrderNumber(purchaseDate: String?, productName: String): String {
        val dateKey = purchaseDate?.take(10)?.replace("-", "") ?: "unknown-date"
        val productKey = kotlin.math.abs(productName.hashCode()).toString()
        return "coupang-$dateKey-$productKey"
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
                    .put("quantities", JSONArray(candidate.quantities))
                    .put("thumbnailPath", candidate.thumbnailPath.orEmpty())
                    .put("imageUrl", candidate.thumbnailPath.orEmpty())
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
        val mergedQuantities = existingCandidate.quantities.ifEmpty { newCandidate.quantities }
        val mergedNodeIds = (existingCandidate.nodeIds + newCandidate.nodeIds).distinct()

        return existingCandidate.copy(
            purchaseDate = existingCandidate.purchaseDate ?: newCandidate.purchaseDate,
            deliveryStatus = existingCandidate.deliveryStatus ?: newCandidate.deliveryStatus,
            deliveryTypes = mergedDeliveryTypes,
            productNames = mergedProductNames,
            prices = mergedPrices,
            quantities = mergedQuantities,
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
