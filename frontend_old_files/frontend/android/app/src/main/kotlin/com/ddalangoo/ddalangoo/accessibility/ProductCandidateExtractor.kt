package com.ddalangoo.ddalangoo.accessibility

import android.graphics.Rect
import kotlin.math.abs
import org.json.JSONArray
import org.json.JSONObject

data class ProductCandidate(
    val productName: String?,
    val price: Int?,
    val productNameNodeId: Int?,
    val priceNodeId: Int?,
    val addToCartNodeId: Int?,
    val bounds: Rect?,
    val centerY: Int?,
    val rawTexts: List<String>,
    val confidence: Double,
    val reasonCode: String,
    val section: String? = null
) {
    fun previewText(): String {
        return listOfNotNull(
            productName,
            price?.let { "${it}원" },
            addToCartNodeId?.let { "addNode=$it" },
            "confidence=$confidence",
            reasonCode,
            section
        ).joinToString(" / ")
    }
}

data class ProductExtractionConfig(
    val pricePatterns: List<Regex>,
    val addToCartKeywords: List<String>,
    val excludeKeywords: List<String>,
    val unitKeywords: List<String>,
    val resultAnchorKeywords: List<String>,
    val maxNamePriceDistancePx: Int = 180,
    val maxNameAddButtonDistancePx: Int = 250
)

object KurlyProductExtractionConfig {
    val config = ProductExtractionConfig(
        pricePatterns = listOf(Regex("\\d{1,3}(,\\d{3})*원")),
        addToCartKeywords = listOf("담기"),
        excludeKeywords = listOf(
            "추천순",
            "필터",
            "총",
            "연관 검색어",
            "최근 검색어",
            "추천 검색어",
            "급상승 검색어",
            "검색어를 입력해주세요",
            "Kurly Only",
            "멤버스혜택",
            "카테고리"
        ),
        unitKeywords = listOf("g", "kg", "ml", "개", "입", "팩"),
        resultAnchorKeywords = listOf("총", "추천순", "필터")
    )
}

class GenericProductCandidateExtractor(
    private val config: ProductExtractionConfig
) {
    fun extract(filteredNodes: List<UiNode>): List<ProductCandidate> {
        val nameNodes = filteredNodes
            .filter { node -> isProductNameCandidate(node) }
            .sortedWith(compareBy<UiNode> { it.centerY }.thenBy { it.centerX })
        val priceNodes = filteredNodes
            .mapNotNull { node -> node.toPriceMatch() }
            .sortedWith(compareBy<PriceNodeMatch> { it.node.centerY }.thenBy { it.node.centerX })
        val addButtonNodes = filteredNodes
            .filter { node -> containsAny(node.searchableText(), config.addToCartKeywords) }
            .sortedWith(compareBy<UiNode> { it.centerY }.thenBy { it.centerX })
        val resultAnchorY = findResultAnchorY(filteredNodes)

        val usedPriceNodeIds = mutableSetOf<Int>()
        val usedAddButtonNodeIds = mutableSetOf<Int>()

        return nameNodes.map { nameNode ->
            val priceMatch = nearestPrice(nameNode, priceNodes, usedPriceNodeIds)
            val addButtonNode = nearestAddButton(nameNode, addButtonNodes, usedAddButtonNodeIds)

            if (priceMatch != null) {
                usedPriceNodeIds.add(priceMatch.node.id)
            }
            if (addButtonNode != null) {
                usedAddButtonNodeIds.add(addButtonNode.id)
            }

            buildProductCandidate(
                nameNode = nameNode,
                priceMatch = priceMatch,
                addButtonNode = addButtonNode,
                resultAnchorY = resultAnchorY
            )
        }.filter { candidate ->
            candidate.productName != null &&
                (candidate.price != null || candidate.addToCartNodeId != null || candidate.confidence >= 0.45)
        }
    }

    private fun isProductNameCandidate(node: UiNode): Boolean {
        val text = node.primaryText().trim()
        if (text.length < 6) return false
        if (!containsKoreanOrBracket(text)) return false
        if (containsAny(text, config.excludeKeywords)) return false
        if (containsAny(node.searchableText(), config.addToCartKeywords)) return false
        if (isPriceOnly(text)) return false

        val hasProductSignal = hasUnitKeyword(text) || text.contains("[") || text.contains("]")
        val isLongDescriptiveName = text.length >= 12 && !text.contains("\n")
        return hasProductSignal || isLongDescriptiveName
    }

    private fun UiNode.toPriceMatch(): PriceNodeMatch? {
        val text = primaryText().trim()
        val matchedPrice = config.pricePatterns
            .asSequence()
            .mapNotNull { regex -> regex.find(text)?.value }
            .firstOrNull()
            ?: return null
        return PriceNodeMatch(
            node = this,
            price = parsePrice(matchedPrice),
            rawPriceText = matchedPrice
        )
    }

    private fun nearestPrice(
        nameNode: UiNode,
        priceNodes: List<PriceNodeMatch>,
        usedPriceNodeIds: Set<Int>
    ): PriceNodeMatch? {
        return priceNodes
            .filter { match -> match.node.id !in usedPriceNodeIds }
            .filter { match -> abs(match.node.centerY - nameNode.centerY) <= config.maxNamePriceDistancePx }
            .minByOrNull { match ->
                abs(match.node.centerY - nameNode.centerY) + horizontalPenalty(nameNode, match.node)
            }
    }

    private fun nearestAddButton(
        nameNode: UiNode,
        addButtonNodes: List<UiNode>,
        usedAddButtonNodeIds: Set<Int>
    ): UiNode? {
        return addButtonNodes
            .filter { node -> node.id !in usedAddButtonNodeIds }
            .filter { node -> abs(node.centerY - nameNode.centerY) <= config.maxNameAddButtonDistancePx }
            .minByOrNull { node ->
                abs(node.centerY - nameNode.centerY) + horizontalPenalty(nameNode, node)
            }
    }

    private fun horizontalPenalty(leftNode: UiNode, rightNode: UiNode): Int {
        return if (rangesOverlap(leftNode.boundsLeft, leftNode.boundsRight, rightNode.boundsLeft, rightNode.boundsRight)) {
            0
        } else {
            abs(leftNode.centerX - rightNode.centerX) / 4
        }
    }

    private fun buildProductCandidate(
        nameNode: UiNode,
        priceMatch: PriceNodeMatch?,
        addButtonNode: UiNode?,
        resultAnchorY: Int?
    ): ProductCandidate {
        val matchedNodes = listOfNotNull(nameNode, priceMatch?.node, addButtonNode)
        val confidence = when {
            priceMatch != null && addButtonNode != null -> 0.92
            priceMatch != null -> 0.72
            addButtonNode != null -> 0.62
            else -> 0.38
        }
        val reasonCode = when {
            priceMatch != null && addButtonNode != null -> "matched_name_price_add_by_y"
            priceMatch != null -> "matched_name_price_only"
            addButtonNode == null -> "missing_add_button"
            else -> "low_confidence_candidate"
        }

        return ProductCandidate(
            productName = nameNode.primaryText(),
            price = priceMatch?.price,
            productNameNodeId = nameNode.id,
            priceNodeId = priceMatch?.node?.id,
            addToCartNodeId = addButtonNode?.id,
            bounds = mergeBounds(matchedNodes),
            centerY = matchedNodes.takeIf { it.isNotEmpty() }?.map { it.centerY }?.average()?.toInt(),
            rawTexts = matchedNodes.map { it.primaryText() }.filter { it.isNotBlank() }.distinct(),
            confidence = confidence,
            reasonCode = reasonCode,
            section = sectionFor(nameNode, resultAnchorY)
        )
    }

    private fun findResultAnchorY(filteredNodes: List<UiNode>): Int? {
        return filteredNodes
            .filter { node -> containsAny(node.primaryText(), config.resultAnchorKeywords) }
            .minByOrNull { node -> node.centerY }
            ?.centerY
    }

    private fun sectionFor(nameNode: UiNode, resultAnchorY: Int?): String {
        if (resultAnchorY == null) return "unknown"
        return if (nameNode.centerY >= resultAnchorY) "search_result" else "banner_or_related"
    }

    private fun mergeBounds(nodes: List<UiNode>): Rect? {
        if (nodes.isEmpty()) return null
        return Rect(
            nodes.minOf { node -> node.boundsLeft },
            nodes.minOf { node -> node.boundsTop },
            nodes.maxOf { node -> node.boundsRight },
            nodes.maxOf { node -> node.boundsBottom }
        )
    }

    private fun containsAny(text: String, keywords: List<String>): Boolean {
        return keywords.any { keyword -> text.contains(keyword, ignoreCase = true) }
    }

    private fun containsKoreanOrBracket(text: String): Boolean {
        return text.any { char -> char in '가'..'힣' } || text.contains("[")
    }

    private fun hasUnitKeyword(text: String): Boolean {
        return config.unitKeywords.any { keyword ->
            Regex("\\d+\\s*${Regex.escape(keyword)}", RegexOption.IGNORE_CASE).containsMatchIn(text)
        }
    }

    private fun isPriceOnly(text: String): Boolean {
        return config.pricePatterns.any { regex -> regex.matches(text) }
    }

    private fun parsePrice(priceText: String): Int? {
        return priceText.filter { char -> char.isDigit() }.toIntOrNull()
    }

    private fun rangesOverlap(leftStart: Int, leftEnd: Int, rightStart: Int, rightEnd: Int): Boolean {
        return leftStart <= rightEnd && rightStart <= leftEnd
    }
}

private data class PriceNodeMatch(
    val node: UiNode,
    val price: Int?,
    val rawPriceText: String
)

object ProductCandidateJsonSerializer {
    fun toJsonArray(candidates: List<ProductCandidate>): JSONArray {
        return JSONArray().also { jsonCandidates ->
            candidates.forEach { candidate ->
                jsonCandidates.put(candidate.toJsonObject())
            }
        }
    }

    private fun ProductCandidate.toJsonObject(): JSONObject {
        return JSONObject()
            .put("productName", productName.orEmpty())
            .put("price", price ?: JSONObject.NULL)
            .put("productNameNodeId", productNameNodeId ?: JSONObject.NULL)
            .put("priceNodeId", priceNodeId ?: JSONObject.NULL)
            .put("addToCartNodeId", addToCartNodeId ?: JSONObject.NULL)
            .put("centerY", centerY ?: JSONObject.NULL)
            .put("rawTexts", JSONArray(rawTexts))
            .put("confidence", confidence)
            .put("reasonCode", reasonCode)
            .put("section", section.orEmpty())
            .put(
                "bounds",
                bounds?.let { rect ->
                    JSONObject()
                        .put("left", rect.left)
                        .put("top", rect.top)
                        .put("right", rect.right)
                        .put("bottom", rect.bottom)
                } ?: JSONObject.NULL
            )
    }
}
