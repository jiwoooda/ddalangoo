package com.ddalangoo.ddalangoo.accessibility

import android.graphics.Rect
import android.view.accessibility.AccessibilityNodeInfo
import java.util.ArrayDeque
import java.util.Collections
import java.util.IdentityHashMap

data class UiNode(
    val id: Int,
    val parentId: Int?,
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
    val childCount: Int,
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
    private data class QueueEntry(
        val node: AccessibilityNodeInfo,
        val depth: Int,
        val parentId: Int?
    )

    fun collect(root: AccessibilityNodeInfo?): List<UiNode> {
        if (root == null) return emptyList()

        val collectedNodes = mutableListOf<UiNode>()
        val visitedNodes = Collections.newSetFromMap(IdentityHashMap<AccessibilityNodeInfo, Boolean>())
        val queue = ArrayDeque<QueueEntry>()
        queue.add(QueueEntry(root, depth = 0, parentId = null))

        // 화면 UI Tree를 너비 우선으로 순회하되, 깊이와 개수를 제한해서 과도한 탐색을 막는다.
        while (queue.isNotEmpty() && collectedNodes.size < maxNodes) {
            val entry = queue.removeFirst()
            val currentNode = entry.node
            val depth = entry.depth
            if (depth > maxDepth || visitedNodes.contains(currentNode)) continue
            visitedNodes.add(currentNode)

            val nodeId = collectedNodes.size
            collectedNodes.add(
                currentNode.toUiNode(
                    id = nodeId,
                    parentId = entry.parentId,
                    depth = depth
                )
            )

            val childCount = currentNode.childCount
            for (childIndex in 0 until childCount) {
                val childNode = runCatching { currentNode.getChild(childIndex) }.getOrNull()
                if (childNode != null) {
                    queue.add(QueueEntry(childNode, depth = depth + 1, parentId = nodeId))
                }
            }
        }

        AutomationLogger.info("ui_tree rawNodeCount=${collectedNodes.size}")
        collectedNodes.take(20).forEach { node ->
            AutomationLogger.debug(
                "raw_node id=${node.id} parentId=${node.parentId ?: ""} " +
                    "depth=${node.depth} childCount=${node.childCount} class=${node.className.orEmpty()} " +
                    "text=${node.text.orEmpty()} desc=${node.contentDescription.orEmpty()} " +
                    "viewId=${node.viewIdResourceName.orEmpty()} clickable=${node.clickable} " +
                    "editable=${node.editable} bounds=${node.boundsLeft},${node.boundsTop}," +
                    "${node.boundsRight},${node.boundsBottom}"
            )
        }

        return collectedNodes
    }

    private fun AccessibilityNodeInfo.toUiNode(id: Int, parentId: Int?, depth: Int): UiNode {
        val bounds = Rect()
        getBoundsInScreen(bounds)

        return UiNode(
            id = id,
            parentId = parentId,
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
            childCount = childCount,
            sourceNode = this
        )
    }
}
