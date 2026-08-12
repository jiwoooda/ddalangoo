package com.ddalangoo.ddalangoo.accessibility

import org.json.JSONArray
import org.json.JSONObject

data class SearchInspectionCandidate(
    val nodeId: Int,
    val parentId: Int?,
    val text: String,
    val contentDescription: String,
    val className: String,
    val viewIdResourceName: String,
    val clickable: Boolean,
    val editable: Boolean,
    val focusable: Boolean,
    val boundsLeft: Int,
    val boundsTop: Int,
    val boundsRight: Int,
    val boundsBottom: Int,
    val centerX: Int,
    val centerY: Int,
    val depth: Int,
    val childCount: Int,
    val hasAddToCartKeyword: Boolean,
    val hasPricePattern: Boolean,
    val hasUnitPattern: Boolean
) {
    fun previewText(): String {
        return text.ifBlank {
            contentDescription.ifBlank {
                viewIdResourceName.ifBlank { className }
            }
        }
    }
}

data class SearchInspectionSnapshot(
    val step: String,
    val platform: String,
    val rawNodeCount: Int,
    val filteredNodeCount: Int,
    val candidates: List<SearchInspectionCandidate>,
    val productCandidates: List<ProductCandidate>,
    val aiFallbackSuggested: Boolean,
    val fallbackType: String?,
    val fallbackReasonCode: String?
)

object SearchInspectionStore {
    private val snapshotsByStep = linkedMapOf<String, SearchInspectionSnapshot>()
    private val accumulatedProductCandidatesByKey = linkedMapOf<String, ProductCandidate>()
    private var searchResultDumpCount = 0
    private val productCandidateExtractor = GenericProductCandidateExtractor(KurlyProductExtractionConfig.config)
    private val priceRegex = Regex("\\d{1,3}(,\\d{3})*원")
    private val unitRegex = Regex("\\d+\\s*(g|kg|ml|l|개|입|봉|팩)", RegexOption.IGNORE_CASE)

    @Synchronized
    fun inspect(
        step: String,
        platform: String,
        rawNodeCount: Int,
        filteredNodes: List<UiNode>
    ): SearchInspectionSnapshot {
        val candidates = when (step) {
            AutomationContract.Step.DUMP_SEARCH_ENTRY -> searchEntryCandidates(filteredNodes)
            AutomationContract.Step.DUMP_SEARCH_INPUT -> searchInputCandidates(filteredNodes)
            AutomationContract.Step.DUMP_SEARCH_RESULTS -> productCandidates(filteredNodes)
            else -> emptyList()
        }.take(80)
        val productCandidates = if (step == AutomationContract.Step.DUMP_SEARCH_RESULTS) {
            productCandidateExtractor.extract(filteredNodes)
        } else {
            emptyList()
        }
        if (step == AutomationContract.Step.DUMP_SEARCH_RESULTS) {
            searchResultDumpCount += 1
            mergeProductCandidates(productCandidates)
        }

        val fallbackReasonCode = fallbackReasonCodeFor(step, candidates, productCandidates)
        val snapshot = SearchInspectionSnapshot(
            step = step,
            platform = platform,
            rawNodeCount = rawNodeCount,
            filteredNodeCount = filteredNodes.size,
            candidates = candidates,
            productCandidates = productCandidates,
            aiFallbackSuggested = fallbackReasonCode != null,
            fallbackType = fallbackReasonCode?.let { "ui_tree_or_vlm" },
            fallbackReasonCode = fallbackReasonCode
        )
        snapshotsByStep[step] = snapshot
        return snapshot
    }

    @Synchronized
    fun statusMap(): Map<String, Any?> {
        val entrySnapshot = snapshotsByStep[AutomationContract.Step.DUMP_SEARCH_ENTRY]
        val inputSnapshot = snapshotsByStep[AutomationContract.Step.DUMP_SEARCH_INPUT]
        val resultsSnapshot = snapshotsByStep[AutomationContract.Step.DUMP_SEARCH_RESULTS]
        val latestSnapshot = snapshotsByStep.values.lastOrNull()

        return mapOf(
            "searchEntryCandidateCount" to (entrySnapshot?.candidates?.size ?: 0),
            "searchInputCandidateCount" to (inputSnapshot?.candidates?.size ?: 0),
            "rawProductNodeCandidateCount" to (resultsSnapshot?.candidates?.size ?: 0),
            "productCandidateCount" to (resultsSnapshot?.productCandidates?.size ?: 0),
            "accumulatedProductCandidateCount" to accumulatedProductCandidatesByKey.size,
            "platformSearchProductCount" to platformSearchProducts().size,
            "searchResultDumpCount" to searchResultDumpCount,
            "searchInspectionPreview" to latestSnapshot?.previewText(),
            "aiFallbackSuggested" to (latestSnapshot?.aiFallbackSuggested ?: false),
            "fallbackType" to latestSnapshot?.fallbackType,
            "fallbackReasonCode" to latestSnapshot?.fallbackReasonCode
        )
    }

    @Synchronized
    fun resultJson(): String {
        val jsonSnapshots = JSONArray()
        snapshotsByStep.values.forEach { snapshot ->
            jsonSnapshots.put(snapshot.toJsonObject())
        }
        return JSONObject()
            .put("searchResultDumpCount", searchResultDumpCount)
            .put("accumulatedProductCandidateCount", accumulatedProductCandidatesByKey.size)
            .put(
                "accumulatedProductCandidates",
                ProductCandidateJsonSerializer.toJsonArray(accumulatedProductCandidatesByKey.values.toList())
            )
            .put(
                "platformSearchProducts",
                ProductCandidateJsonSerializer.toPlatformSearchProductJsonArray(
                    platformForSearchProducts(),
                    platformSearchProducts()
                )
            )
            .put("snapshots", jsonSnapshots)
            .toString(2)
    }

    @Synchronized
    fun clear() {
        snapshotsByStep.clear()
        accumulatedProductCandidatesByKey.clear()
        searchResultDumpCount = 0
    }

    @Synchronized
    fun searchResultDumpCount(): Int {
        return searchResultDumpCount
    }

    @Synchronized
    fun accumulatedProductCandidateCount(): Int {
        return accumulatedProductCandidatesByKey.size
    }

    @Synchronized
    fun platformSearchProductMaps(platform: String? = null): List<Map<String, Any?>> {
        return ProductCandidateJsonSerializer.toPlatformSearchProductMapList(
            platform ?: platformForSearchProducts(),
            platformSearchProducts()
        )
    }

    @Synchronized
    fun matchedProductCandidate(targetProductName: String): ProductCandidate? {
        val normalizedTarget = normalizeProductName(targetProductName)
        if (normalizedTarget.isBlank()) return null

        val targetTokens = normalizedTarget
            .split(" ")
            .filter { token -> token.length >= 2 }
            .distinct()
        if (targetTokens.isEmpty()) return null

        return accumulatedProductCandidatesByKey.values.firstOrNull { candidate ->
            val normalizedName = normalizeProductName(candidate.productName.orEmpty())
            if (normalizedName.isBlank()) return@firstOrNull false
            if (normalizedName.contains(normalizedTarget)) return@firstOrNull true

            // 상품명은 대괄호/용량/원산지 표기가 조금씩 흔들릴 수 있어서
            // 전체 문자열 일치 대신 목표 상품명의 핵심 토큰이 충분히 겹치는지 본다.
            val matchedTokenCount = targetTokens.count { token -> normalizedName.contains(token) }
            val requiredTokenCount = maxOf(2, (targetTokens.size * 2 + 2) / 3)
            matchedTokenCount >= requiredTokenCount
        }
    }

    private fun searchEntryCandidates(filteredNodes: List<UiNode>): List<SearchInspectionCandidate> {
        return filteredNodes
            .filter { node ->
                val text = node.searchableText()
                node.clickable && (
                    text.contains("검색") ||
                        text.contains("상품명") ||
                        text.contains("무엇을") ||
                        text.contains("찾고")
                    )
            }
            .map { node -> node.toSearchInspectionCandidate() }
    }

    private fun searchInputCandidates(filteredNodes: List<UiNode>): List<SearchInspectionCandidate> {
        return filteredNodes
            .filter { node ->
                val text = node.searchableText()
                node.editable ||
                    node.className.orEmpty().contains("EditText") ||
                    text.contains("검색어") ||
                    text.contains("상품명")
            }
            .map { node -> node.toSearchInspectionCandidate() }
    }

    private fun productCandidates(filteredNodes: List<UiNode>): List<SearchInspectionCandidate> {
        return filteredNodes
            .filter { node ->
                val text = node.primaryText()
                val searchableText = node.searchableText()
                searchableText.contains("담기") ||
                    priceRegex.containsMatchIn(text) ||
                    unitRegex.containsMatchIn(text) ||
                    searchableText.contains("할인") ||
                    searchableText.contains("샛별배송")
            }
            .map { node -> node.toSearchInspectionCandidate() }
    }

    private fun normalizeProductName(value: String): String {
        return value
            .lowercase()
            .replace(Regex("[^0-9a-z가-힣]+"), " ")
            .replace(Regex("\\s+"), " ")
            .trim()
    }

    private fun fallbackReasonCodeFor(
        step: String,
        candidates: List<SearchInspectionCandidate>,
        productCandidates: List<ProductCandidate>
    ): String? {
        if (step == AutomationContract.Step.DUMP_SEARCH_RESULTS) {
            if (productCandidates.isEmpty()) return "product_candidate_grouping_failed"
            val hasReliableCandidate = productCandidates.any { candidate ->
                candidate.confidence >= 0.7 &&
                    listOfNotNull(candidate.productName, candidate.price, candidate.addToCartNodeId).size >= 2
            }
            return if (hasReliableCandidate) null else "low_confidence_candidates"
        }
        if (candidates.isNotEmpty()) return null
        return when (step) {
            AutomationContract.Step.DUMP_SEARCH_INPUT -> "search_input_not_found"
            AutomationContract.Step.DUMP_SEARCH_ENTRY -> "search_entry_not_found"
            else -> "search_candidates_not_found"
        }
    }

    private fun UiNode.toSearchInspectionCandidate(): SearchInspectionCandidate {
        val primaryText = primaryText()
        val searchableText = searchableText()
        return SearchInspectionCandidate(
            nodeId = id,
            parentId = parentId,
            text = text.orEmpty(),
            contentDescription = contentDescription.orEmpty(),
            className = className.orEmpty(),
            viewIdResourceName = viewIdResourceName.orEmpty(),
            clickable = clickable,
            editable = editable,
            focusable = focusable,
            boundsLeft = boundsLeft,
            boundsTop = boundsTop,
            boundsRight = boundsRight,
            boundsBottom = boundsBottom,
            centerX = centerX,
            centerY = centerY,
            depth = depth,
            childCount = childCount,
            hasAddToCartKeyword = searchableText.contains("담기"),
            hasPricePattern = priceRegex.containsMatchIn(primaryText),
            hasUnitPattern = unitRegex.containsMatchIn(primaryText)
        )
    }

    private fun SearchInspectionSnapshot.toJsonObject(): JSONObject {
        return JSONObject()
            .put("step", step)
            .put("platform", platform)
            .put("rawNodeCount", rawNodeCount)
            .put("filteredNodeCount", filteredNodeCount)
            .put("candidateCount", candidates.size)
            .put("productCandidateCount", productCandidates.size)
            .put("aiFallbackSuggested", aiFallbackSuggested)
            .put("fallbackType", fallbackType.orEmpty())
            .put("fallbackReasonCode", fallbackReasonCode.orEmpty())
            .put(
                "candidates",
                JSONArray().also { jsonCandidates ->
                    candidates.forEach { candidate ->
                        jsonCandidates.put(candidate.toJsonObject())
                    }
                }
            )
            .put("productCandidates", ProductCandidateJsonSerializer.toJsonArray(productCandidates))
    }

    private fun SearchInspectionCandidate.toJsonObject(): JSONObject {
        return JSONObject()
            .put("nodeId", nodeId)
            .put("parentId", parentId ?: JSONObject.NULL)
            .put("text", text)
            .put("contentDescription", contentDescription)
            .put("className", className)
            .put("viewIdResourceName", viewIdResourceName)
            .put("clickable", clickable)
            .put("editable", editable)
            .put("focusable", focusable)
            .put("hasAddToCartKeyword", hasAddToCartKeyword)
            .put("hasPricePattern", hasPricePattern)
            .put("hasUnitPattern", hasUnitPattern)
            .put(
                "bounds",
                JSONObject()
                    .put("left", boundsLeft)
                    .put("top", boundsTop)
                    .put("right", boundsRight)
                    .put("bottom", boundsBottom)
            )
            .put("centerX", centerX)
            .put("centerY", centerY)
            .put("depth", depth)
            .put("childCount", childCount)
    }

    private fun SearchInspectionSnapshot.previewText(): String? {
        val accumulatedProductCandidates = accumulatedProductCandidatesByKey.values.toList()
        if (accumulatedProductCandidates.isNotEmpty()) {
            return accumulatedProductCandidates
                .take(5)
                .joinToString(separator = " | ") { candidate -> candidate.previewText() }
        }
        return candidates
            .take(8)
            .joinToString(separator = " | ") { candidate -> candidate.previewText() }
            .ifBlank { null }
    }

    private fun mergeProductCandidates(productCandidates: List<ProductCandidate>) {
        productCandidates.forEach { candidate ->
            val productName = candidate.productName?.takeIf { it.isNotBlank() } ?: return@forEach
            val key = "$productName:${candidate.price ?: ""}"
            accumulatedProductCandidatesByKey.putIfAbsent(key, candidate)
        }
    }

    private fun platformSearchProducts(): List<ProductCandidate> {
        return accumulatedProductCandidatesByKey.values
            .filter { candidate ->
                !candidate.productName.isNullOrBlank() && candidate.price != null
            }
            .sortedWith(
                compareByDescending<ProductCandidate> { candidate -> candidate.confidence }
                    .thenBy { candidate -> candidate.centerY ?: Int.MAX_VALUE }
            )
    }

    private fun platformForSearchProducts(): String {
        return snapshotsByStep.values
            .lastOrNull { snapshot -> snapshot.platform.isNotBlank() }
            ?.platform
            ?: AutomationContract.Platform.UNKNOWN
    }
}
