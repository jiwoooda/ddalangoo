package com.ddalangoo.ddalangoo.accessibility

import android.graphics.Rect
import android.view.accessibility.AccessibilityNodeInfo
import java.util.ArrayDeque
import java.util.Collections
import java.util.IdentityHashMap

data class UiNode(
    val id: Int,
    val text: String?,
    val contentDescription: String?,
    val className: String?,
    val viewIdResourceName: String?,
    val clickable: Boolean,
    val editable: Boolean,
    val focusable: Boolean,
    val scrollable: Boolean,
    val enabled: Boolean,
    val visibleToUser: Boolean,
    val boundsLeft: Int,
    val boundsTop: Int,
    val boundsRight: Int,
    val boundsBottom: Int,
    val centerX: Int,
    val centerY: Int,
    val depth: Int,
    val role: String? = null,
    val sourceNode: AccessibilityNodeInfo? = null
) {
    val width: Int
        get() = boundsRight - boundsLeft

    val height: Int
        get() = boundsBottom - boundsTop

    fun primaryText(): String {
        return text?.takeIf { it.isNotBlank() }
            ?: contentDescription?.takeIf { it.isNotBlank() }
            ?: viewIdResourceName.orEmpty()
    }

    fun searchableText(): String {
        return listOfNotNull(text, contentDescription, viewIdResourceName, className)
            .joinToString(" ")
            .lowercase()
    }
}

class UiTreeCollector(
    private val maxDepth: Int = 40,
    private val maxNodes: Int = 600
) {
    fun collect(root: AccessibilityNodeInfo?): List<UiNode> {
        if (root == null) return emptyList()

        val collectedNodes = mutableListOf<UiNode>()
        val visitedNodes = Collections.newSetFromMap(IdentityHashMap<AccessibilityNodeInfo, Boolean>())
        val queue = ArrayDeque<Pair<AccessibilityNodeInfo, Int>>()
        queue.add(root to 0)

        // 화면 UI Tree를 너비 우선으로 순회하되, 깊이와 개수를 제한해서 과도한 탐색을 막는다.
        while (queue.isNotEmpty() && collectedNodes.size < maxNodes) {
            val (currentNode, depth) = queue.removeFirst()
            if (depth > maxDepth || visitedNodes.contains(currentNode)) continue
            visitedNodes.add(currentNode)

            collectedNodes.add(currentNode.toUiNode(collectedNodes.size, depth))

            val childCount = currentNode.childCount
            for (childIndex in 0 until childCount) {
                val childNode = runCatching { currentNode.getChild(childIndex) }.getOrNull()
                if (childNode != null) {
                    queue.add(childNode to depth + 1)
                }
            }
        }

        AutomationLogger.info("ui_tree rawNodeCount=${collectedNodes.size}")
        collectedNodes.take(20).forEach { node ->
            AutomationLogger.debug(
                "raw_node id=${node.id} depth=${node.depth} class=${node.className.orEmpty()} " +
                    "text=${node.text.orEmpty()} desc=${node.contentDescription.orEmpty()} " +
                    "viewId=${node.viewIdResourceName.orEmpty()} clickable=${node.clickable} " +
                    "editable=${node.editable} bounds=${node.boundsLeft},${node.boundsTop}," +
                    "${node.boundsRight},${node.boundsBottom}"
            )
        }

        return collectedNodes
    }

    private fun AccessibilityNodeInfo.toUiNode(id: Int, depth: Int): UiNode {
        val bounds = Rect()
        getBoundsInScreen(bounds)

        return UiNode(
            id = id,
            text = text?.toString(),
            contentDescription = contentDescription?.toString(),
            className = className?.toString(),
            viewIdResourceName = viewIdResourceName,
            clickable = isClickable,
            editable = isEditable,
            focusable = isFocusable,
            scrollable = isScrollable,
            enabled = isEnabled,
            visibleToUser = isVisibleToUser,
            boundsLeft = bounds.left,
            boundsTop = bounds.top,
            boundsRight = bounds.right,
            boundsBottom = bounds.bottom,
            centerX = bounds.centerX(),
            centerY = bounds.centerY(),
            depth = depth,
            sourceNode = this
        )
    }
}
