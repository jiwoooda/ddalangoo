package com.ddalangoo.ddalangoo.accessibility

import android.accessibilityservice.AccessibilityService
import android.graphics.Bitmap
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.util.Base64
import android.view.Display
import org.json.JSONObject
import java.io.ByteArrayOutputStream
import java.net.HttpURLConnection
import java.net.URL
import kotlin.math.roundToInt

private data class VlmFallbackContext(
    val task: AutomationTask,
    val packageName: String?,
    val rawNodeCount: Int,
    val filteredNodes: List<UiNode>,
    val trigger: String,
    val screenType: String,
    val reasonCode: String,
    val expectedState: String,
    val observedState: String
)

private data class VlmFallbackPlan(
    val action: String,
    val x: Double?,
    val y: Double?,
    val confidence: Double,
    val reason: String
)

/**
 * Rule runtime이 막힌 순간에만 호출되는 VLM 복구 실행기.
 *
 * VLM은 팝업을 닫는 보조 action만 제안한다. action 실행 후에도 step을 성공 처리하지 않고,
 * 같은 step을 다시 읽어서 기존 rule이 정상 화면 전환을 판단하게 둔다.
 */
class VlmFallbackRuntime(
    private val service: AccessibilityService,
    private val actionExecutor: ActionExecutor,
    private val scheduleProcessTick: (Long, String) -> Unit
) {
    private val handler = Handler(Looper.getMainLooper())
    private val attemptsByTask = mutableMapOf<String, Int>()
    private val attemptsByTaskStep = mutableMapOf<String, Int>()
    private var inFlightKey: String? = null
    private var screenshotRequestKey: String? = null

    fun requestRecovery(
        task: AutomationTask,
        packageName: String?,
        rawNodeCount: Int,
        filteredNodes: List<UiNode>,
        trigger: String,
        screenType: String,
        reasonCode: String,
        expectedState: String,
        observedState: String
    ): Boolean {
        val taskStepKey = "${task.taskId}:${task.currentStep}"
        if (inFlightKey == taskStepKey) {
            AutomationLogger.info("vlm_fallback skipped reason=in_flight key=$taskStepKey")
            return true
        }

        val totalAttempts = (attemptsByTask[task.taskId] ?: 0) + 1
        val stepAttempts = (attemptsByTaskStep[taskStepKey] ?: 0) + 1
        if (totalAttempts > MAX_TOTAL_ATTEMPTS || stepAttempts > MAX_ATTEMPTS_PER_STEP) {
            AutomationLogger.warn(
                "vlm_fallback limit exceeded taskId=${task.taskId} step=${task.currentStep} " +
                    "totalAttempts=$totalAttempts stepAttempts=$stepAttempts"
            )
            return false
        }

        attemptsByTask[task.taskId] = totalAttempts
        attemptsByTaskStep[taskStepKey] = stepAttempts
        inFlightKey = taskStepKey

        AutomationTaskStore.recordVlmFallbackRequested(
            packageName = packageName,
            currentStep = task.currentStep,
            rawNodeCount = rawNodeCount,
            filteredNodeCount = filteredNodes.size,
            trigger = trigger,
            reasonCode = reasonCode,
            expectedState = expectedState,
            observedState = observedState
        )

        val context = VlmFallbackContext(
            task = task,
            packageName = packageName,
            rawNodeCount = rawNodeCount,
            filteredNodes = filteredNodes,
            trigger = trigger,
            screenType = screenType,
            reasonCode = reasonCode,
            expectedState = expectedState,
            observedState = observedState
        )
        captureScreenshot(context)
        return true
    }

    fun cancel() {
        inFlightKey = null
        screenshotRequestKey = null
        attemptsByTask.clear()
        attemptsByTaskStep.clear()
    }

    private fun captureScreenshot(context: VlmFallbackContext) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.R) {
            stopWithVlmFailure(context, "vlm_screenshot_unsupported", "Android screenshot API is unavailable")
            return
        }

        val requestKey = "${context.task.taskId}:${context.task.currentStep}:${System.currentTimeMillis()}"
        screenshotRequestKey = requestKey
        AutomationLogger.info(
            "vlm_fallback screenshot requested taskId=${context.task.taskId} step=${context.task.currentStep}"
        )
        handler.postDelayed({
            if (screenshotRequestKey == requestKey) {
                screenshotRequestKey = null
                stopWithVlmFailure(
                    context,
                    "vlm_screenshot_timeout",
                    "Screenshot callback did not arrive within timeout"
                )
            }
        }, SCREENSHOT_TIMEOUT_MS)

        service.takeScreenshot(
            Display.DEFAULT_DISPLAY,
            service.mainExecutor,
            object : AccessibilityService.TakeScreenshotCallback {
                override fun onSuccess(screenshot: AccessibilityService.ScreenshotResult) {
                    if (screenshotRequestKey != requestKey) return
                    screenshotRequestKey = null
                    AutomationLogger.info(
                        "vlm_fallback screenshot captured taskId=${context.task.taskId} step=${context.task.currentStep}"
                    )
                    val bitmap = Bitmap.wrapHardwareBuffer(
                        screenshot.hardwareBuffer,
                        screenshot.colorSpace
                    )
                    val softwareBitmap = bitmap?.copy(Bitmap.Config.ARGB_8888, false)
                    screenshot.hardwareBuffer.close()

                    if (softwareBitmap == null) {
                        stopWithVlmFailure(context, "vlm_screenshot_failed", "Failed to convert screenshot")
                        return
                    }
                    val screenshotBase64 = encodeJpegBase64(softwareBitmap)
                    softwareBitmap.recycle()
                    requestPlanner(context, screenshotBase64)
                }

                override fun onFailure(errorCode: Int) {
                    if (screenshotRequestKey != requestKey) return
                    screenshotRequestKey = null
                    stopWithVlmFailure(
                        context,
                        "vlm_screenshot_failed",
                        "Failed to capture screenshot errorCode=$errorCode"
                    )
                }
            }
        )
    }

    private fun requestPlanner(context: VlmFallbackContext, screenshotBase64: String) {
        val backendBaseUrl = context.task.metadata["backendBaseUrl"]?.toString()?.trim().orEmpty()
        if (backendBaseUrl.isEmpty()) {
            stopWithVlmFailure(context, "vlm_backend_url_missing", "backendBaseUrl metadata is missing")
            return
        }

        Thread {
            try {
                val endpoint = "${backendBaseUrl.trimEnd('/')}/api/agent/automation/vlm-fallback-plan"
                val connection = (URL(endpoint).openConnection() as HttpURLConnection).apply {
                    requestMethod = "POST"
                    connectTimeout = 10000
                    readTimeout = 20000
                    doOutput = true
                    setRequestProperty("Content-Type", "application/json")
                    setRequestProperty("Accept", "application/json")
                }
                val requestJson = JSONObject()
                    .put("taskId", context.task.taskId)
                    .put("currentStep", context.task.currentStep)
                    .put("platform", context.task.platform)
                    .put("packageName", context.packageName)
                    .put("fallbackReasonCode", context.reasonCode)
                    .put("expectedState", context.expectedState)
                    .put("observedState", context.observedState)
                    .put("uiTreeSummary", buildUiTreeSummary(context.filteredNodes))
                    .put("screenshot", screenshotBase64)
                    .toString()

                connection.outputStream.use { outputStream ->
                    outputStream.write(requestJson.toByteArray(Charsets.UTF_8))
                }

                val statusCode = connection.responseCode
                val responseBody = if (statusCode in 200..299) {
                    connection.inputStream.bufferedReader().use { it.readText() }
                } else {
                    connection.errorStream?.bufferedReader()?.use { it.readText() }.orEmpty()
                }
                connection.disconnect()

                if (statusCode !in 200..299) {
                    throw IllegalStateException("planner status=$statusCode body=$responseBody")
                }

                val planJson = JSONObject(responseBody)
                val plan = VlmFallbackPlan(
                    action = planJson.optString("action"),
                    x = if (planJson.has("x") && !planJson.isNull("x")) planJson.optDouble("x") else null,
                    y = if (planJson.has("y") && !planJson.isNull("y")) planJson.optDouble("y") else null,
                    confidence = planJson.optDouble("confidence", 0.0),
                    reason = planJson.optString("reason")
                )
                handler.post { executePlan(context, plan) }
            } catch (exception: Exception) {
                handler.post {
                    stopWithVlmFailure(
                        context,
                        "vlm_planner_failed",
                        "VLM planner request failed: ${exception.message.orEmpty()}"
                    )
                }
            }
        }.start()
    }

    private fun executePlan(context: VlmFallbackContext, plan: VlmFallbackPlan) {
        inFlightKey = null
        val activeTask = AutomationTaskStore.getTask()
        if (activeTask?.taskId != context.task.taskId || activeTask.currentStep != context.task.currentStep) {
            AutomationLogger.info(
                "vlm_fallback action skipped reason=task_or_step_changed " +
                    "taskId=${context.task.taskId} step=${context.task.currentStep}"
            )
            return
        }

        when (plan.action) {
            "tap" -> executeTapPlan(context, plan)
            "wait" -> {
                AutomationTaskStore.recordVlmFallbackAction(
                    packageName = context.packageName,
                    currentStep = context.task.currentStep,
                    rawNodeCount = context.rawNodeCount,
                    filteredNodeCount = context.filteredNodes.size,
                    trigger = context.trigger,
                    action = "wait",
                    success = true,
                    method = ActionExecutionMethod.NONE.value,
                    message = "VLM requested wait confidence=${plan.confidence} reason=${plan.reason}"
                )
                scheduleProcessTick(900L, "after_vlm_wait")
            }
            "abort" -> stopWithVlmFailure(
                context,
                "vlm_recovery_aborted",
                "VLM aborted recovery confidence=${plan.confidence} reason=${plan.reason}"
            )
            else -> stopWithVlmFailure(
                context,
                "vlm_invalid_action",
                "VLM returned unsupported action=${plan.action}"
            )
        }
    }

    private fun executeTapPlan(context: VlmFallbackContext, plan: VlmFallbackPlan) {
        val normalizedX = plan.x
        val normalizedY = plan.y
        if (normalizedX == null || normalizedY == null) {
            stopWithVlmFailure(context, "vlm_invalid_tap", "VLM tap action is missing x/y")
            return
        }

        val displayMetrics = service.resources.displayMetrics
        val x = (normalizedX.coerceIn(0.0, 1.0) * displayMetrics.widthPixels).roundToInt()
        val y = (normalizedY.coerceIn(0.0, 1.0) * displayMetrics.heightPixels).roundToInt()
        val result = actionExecutor.executeCoordinateTap(
            x = x,
            y = y,
            reason = "vlm:${plan.reason}"
        )
        AutomationTaskStore.recordVlmFallbackAction(
            packageName = context.packageName,
            currentStep = context.task.currentStep,
            rawNodeCount = context.rawNodeCount,
            filteredNodeCount = context.filteredNodes.size,
            trigger = context.trigger,
            action = "tap",
            success = result.success,
            method = result.method,
            message = "VLM tap confidence=${plan.confidence} reason=${plan.reason} result=${result.message}",
            errorCode = result.errorCode
        )

        if (result.success) {
            scheduleProcessTick(900L, "after_vlm_recovery")
        } else {
            stopWithVlmFailure(
                context,
                "vlm_tap_failed",
                "VLM tap dispatch failed: ${result.message}"
            )
        }
    }

    private fun stopWithVlmFailure(context: VlmFallbackContext, reasonCode: String, message: String) {
        inFlightKey = null
        AutomationTaskStore.stopTask(
            packageName = context.packageName,
            currentStep = context.task.currentStep,
            rawNodeCount = context.rawNodeCount,
            filteredNodeCount = context.filteredNodes.size,
            trigger = context.trigger,
            screenType = context.screenType,
            reasonCode = reasonCode,
            message = message,
            failedAction = "vlm_recovery",
            expectedState = context.expectedState,
            observedState = context.observedState
        )
    }

    private fun encodeJpegBase64(bitmap: Bitmap): String {
        val resizedBitmap = resizeForPlanner(bitmap)
        val outputStream = ByteArrayOutputStream()
        resizedBitmap.compress(Bitmap.CompressFormat.JPEG, 72, outputStream)
        if (resizedBitmap !== bitmap) {
            resizedBitmap.recycle()
        }
        return Base64.encodeToString(outputStream.toByteArray(), Base64.NO_WRAP)
    }

    private fun resizeForPlanner(bitmap: Bitmap): Bitmap {
        val maxWidth = 720
        if (bitmap.width <= maxWidth) return bitmap
        val ratio = maxWidth.toFloat() / bitmap.width.toFloat()
        val targetHeight = (bitmap.height * ratio).roundToInt()
        return Bitmap.createScaledBitmap(bitmap, maxWidth, targetHeight, true)
    }

    private fun buildUiTreeSummary(nodes: List<UiNode>): String {
        return nodes.take(40).joinToString(separator = "\n") { node ->
            val text = sanitize(node.text)
            val description = sanitize(node.contentDescription)
            val viewId = sanitize(node.viewIdResourceName)
            "#${node.id} depth=${node.depth} class=${node.className.orEmpty()} " +
                "text=\"$text\" desc=\"$description\" viewId=\"$viewId\" " +
                "clickable=${node.clickable} enabled=${node.enabled} visible=${node.visibleToUser} " +
                "bounds=${node.boundsLeft},${node.boundsTop},${node.boundsRight},${node.boundsBottom}"
        }
    }

    private fun sanitize(value: String?): String {
        return value
            ?.replace(Regex("\\s+"), " ")
            ?.trim()
            ?.take(80)
            .orEmpty()
    }

    companion object {
        private const val MAX_ATTEMPTS_PER_STEP = 2
        private const val MAX_TOTAL_ATTEMPTS = 5
        private const val SCREENSHOT_TIMEOUT_MS = 5000L
    }
}
