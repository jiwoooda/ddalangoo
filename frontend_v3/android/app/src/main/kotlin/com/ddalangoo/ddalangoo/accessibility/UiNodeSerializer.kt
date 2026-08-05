package com.ddalangoo.ddalangoo.accessibility

import org.json.JSONArray
import org.json.JSONObject

class UiNodeSerializer {
    private val importantKeywords = listOf(
        "검색",
        "검색어",
        "무엇을 찾고 계신가요",
        "상품을 검색",
        "장바구니",
        "담기",
        "구매",
        "옵션",
        "확인",
        "닫기",
        "취소",
        "나중에 하기",
        "오늘 하루 보지 않기",
        "건너뛰기"
    )

    fun filter(rawNodes: List<UiNode>): List<UiNode> {
        return rawNodes
            .filter { node -> shouldKeep(node) }
            .map { node -> node.copy(role = inferRole(node)) }
    }

    fun toJson(filteredNodes: List<UiNode>): String {
        val jsonNodes = JSONArray()
        filteredNodes.forEach { node ->
            jsonNodes.put(
                JSONObject()
                    .put("id", node.id)
                    .put("text", node.text.orEmpty())
                    .put("contentDescription", node.contentDescription.orEmpty())
                    .put("className", node.className.orEmpty())
                    .put("viewIdResourceName", node.viewIdResourceName.orEmpty())
                    .put("clickable", node.clickable)
                    .put("editable", node.editable)
                    .put("scrollable", node.scrollable)
                    .put("enabled", node.enabled)
                    .put("visibleToUser", node.visibleToUser)
                    .put(
                        "bounds",
                        JSONObject()
                            .put("left", node.boundsLeft)
                            .put("top", node.boundsTop)
                            .put("right", node.boundsRight)
                            .put("bottom", node.boundsBottom)
                    )
                    .put("centerX", node.centerX)
                    .put("centerY", node.centerY)
                    .put("depth", node.depth)
                    .put("role", node.role.orEmpty())
            )
        }
        return jsonNodes.toString(2)
    }

    private fun shouldKeep(node: UiNode): Boolean {
        if (!node.visibleToUser) return false
        if (node.width < 2 || node.height < 2) return false

        // 자동화 판단에 쓸 수 없는 장식용 노드는 로그와 planner 입력에서 제외한다.
        val hasLabel = !node.text.isNullOrBlank() ||
            !node.contentDescription.isNullOrBlank() ||
            !node.viewIdResourceName.isNullOrBlank()
        if (!hasLabel && !node.clickable && !node.editable && !node.scrollable) return false

        return node.clickable ||
            node.editable ||
            node.scrollable ||
            !node.text.isNullOrBlank() ||
            !node.contentDescription.isNullOrBlank() ||
            containsImportantKeyword(node)
    }

    private fun containsImportantKeyword(node: UiNode): Boolean {
        val combinedText = listOfNotNull(node.text, node.contentDescription, node.viewIdResourceName)
            .joinToString(" ")
        return importantKeywords.any { keyword -> combinedText.contains(keyword, ignoreCase = true) }
    }

    private fun inferRole(node: UiNode): String {
        val className = node.className.orEmpty()
        return when {
            node.editable || className.contains("EditText", ignoreCase = true) -> "input"
            node.clickable || className.contains("Button", ignoreCase = true) -> "button"
            node.scrollable ||
                className.contains("RecyclerView", ignoreCase = true) ||
                className.contains("ScrollView", ignoreCase = true) ||
                className.contains("ListView", ignoreCase = true) -> "scroll_container"
            !node.text.isNullOrBlank() -> "text"
            else -> "unknown"
        }
    }
}
