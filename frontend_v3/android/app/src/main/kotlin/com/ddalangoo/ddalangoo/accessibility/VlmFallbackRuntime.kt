package com.ddalangoo.ddalangoo.accessibility

import android.accessibilityservice.AccessibilityService
import android.graphics.Bitmap
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.util.Base64
import android.view.Display
import org.json.JSONArray
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
    val rootAvailable: Boolean,
    val trigger: String,
    val screenType: String,
    val recoveryGoal: String?,
    val reasonCode: String,
    val expectedState: String,
    val observedState: String,
    val observationFingerprint: String
)

private data class VlmFallbackPlan(
    val action: String,
    val targetDescription: String?,
    val nodeId: Int?,
    val x: Double?,
    val y: Double?,
    val direction: String?,
    val distance: Double?,
    val confidence: Double,
    val reason: String
)

private data class VlmActionHistoryEntry(
    val taskId: String,
    val step: String,
    val action: String,
    val targetDescription: String?,
    val success: Boolean,
    val outcome: String,
    val reason: String
)

enum class RecoveryRequestResult {
    STARTED,
    ALREADY_IN_FLIGHT,
    SKIPPED_POLICY,
    UNAVAILABLE
}

/**
 * Rule runtime 바깥에서 현재 step 화면을 먼저 관찰하는 VLM sentinel.
 *
 * VLM은 step-entry에서는 팝업/시스템 인터럽션을 정리하고, rule failure에서는
 * 현재 step 목표 달성을 위한 작은 복구 action만 제안한다.
 * action 실행 후에도 step을 성공 처리하지 않고,
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
    private val lastRecoveryObservationByTaskStep = mutableMapOf<String, String>()
    private val noProgressByTaskStep = mutableMapOf<String, Int>()
    private val recentActions = ArrayDeque<VlmActionHistoryEntry>()
    private val uiTreeCollector = UiTreeCollector()
    private val uiNodeSerializer = UiNodeSerializer()
    private var inFlightKey: String? = null
    private var screenshotRequestKey: String? = null

    fun requestRecovery(
        task: AutomationTask,
        packageName: String?,
        rawNodeCount: Int,
        filteredNodes: List<UiNode>,
        rootAvailable: Boolean,
        trigger: String,
        screenType: String,
        recoveryGoal: String? = null,
        reasonCode: String,
        expectedState: String,
        observedState: String
    ): RecoveryRequestResult {
        val taskStepKey = "${task.taskId}:${task.currentStep}"
        if (isHostAppForeground(packageName)) {
            AutomationLogger.warn(
                "vlm_fallback skipped reason=host_app_foreground " +
                    "taskId=${task.taskId} step=${task.currentStep} " +
                    "foregroundPackage=${packageName.orEmpty()} " +
                    "targetPackage=${task.effectivePackageName().orEmpty()}"
            )
            return RecoveryRequestResult.SKIPPED_POLICY
        }
        if (inFlightKey == taskStepKey) {
            AutomationLogger.info("vlm_fallback skipped reason=in_flight key=$taskStepKey")
            return RecoveryRequestResult.ALREADY_IN_FLIGHT
        }

        val observationFingerprint = observationFingerprint(rootAvailable, filteredNodes)
        val recoveryProgressFingerprint = listOf(
            screenType,
            recoveryGoal.orEmpty(),
            observationFingerprint
        ).joinToString(":")
        val previousRecoveryFingerprint = lastRecoveryObservationByTaskStep[taskStepKey]
        val noProgressCount = if (
            !recoveryGoal.isNullOrBlank() &&
            previousRecoveryFingerprint == recoveryProgressFingerprint
        ) {
            (noProgressByTaskStep[taskStepKey] ?: 0) + 1
        } else {
            0
        }
        lastRecoveryObservationByTaskStep[taskStepKey] = recoveryProgressFingerprint
        noProgressByTaskStep[taskStepKey] = noProgressCount
        if (noProgressCount >= MAX_NO_PROGRESS_PER_STEP) {
            AutomationLogger.warn(
                "vlm_fallback no progress taskId=${task.taskId} step=${task.currentStep} " +
                    "screenType=$screenType recoveryGoal=${recoveryGoal.orEmpty()} " +
                    "noProgressCount=$noProgressCount"
            )
            return RecoveryRequestResult.UNAVAILABLE
        }

        val totalAttempts = (attemptsByTask[task.taskId] ?: 0) + 1
        val stepAttempts = (attemptsByTaskStep[taskStepKey] ?: 0) + 1
        if (totalAttempts > MAX_TOTAL_ATTEMPTS || stepAttempts > MAX_ATTEMPTS_PER_STEP) {
            AutomationLogger.warn(
                "vlm_fallback limit exceeded taskId=${task.taskId} step=${task.currentStep} " +
                    "totalAttempts=$totalAttempts stepAttempts=$stepAttempts"
            )
            return RecoveryRequestResult.UNAVAILABLE
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
        if (!rootAvailable) {
            AutomationLogger.info(
                "visual_sentinel_screenshot_only taskId=${task.taskId} taskType=${task.taskType} " +
                    "platform=${task.platform} currentStep=${task.currentStep} " +
                    "foregroundPackage=${packageName.orEmpty()} rootAvailable=false " +
                    "reason=$reasonCode action=request confidence= sentinelAttemptCount=$stepAttempts"
            )
        }

        val context = VlmFallbackContext(
            task = task,
            packageName = packageName,
            rawNodeCount = rawNodeCount,
            filteredNodes = filteredNodes,
            rootAvailable = rootAvailable,
            trigger = trigger,
            screenType = screenType,
            recoveryGoal = recoveryGoal,
            reasonCode = reasonCode,
            expectedState = expectedState,
            observedState = observedState,
            observationFingerprint = observationFingerprint
        )
        captureScreenshot(context)
        return RecoveryRequestResult.STARTED
    }

    fun cancel() {
        inFlightKey = null
        screenshotRequestKey = null
        attemptsByTask.clear()
        attemptsByTaskStep.clear()
        lastRecoveryObservationByTaskStep.clear()
        noProgressByTaskStep.clear()
        recentActions.clear()
    }

    private fun captureScreenshot(context: VlmFallbackContext) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.R) {
            continueWithoutVlm(context, "vlm_screenshot_unsupported", "Android screenshot API is unavailable")
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
                continueWithoutVlm(
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
                        continueWithoutVlm(context, "vlm_screenshot_failed", "Failed to convert screenshot")
                        return
                    }
                    val screenshotBase64 = encodeJpegBase64(softwareBitmap)
                    softwareBitmap.recycle()
                    requestPlanner(context, screenshotBase64)
                }

                override fun onFailure(errorCode: Int) {
                    if (screenshotRequestKey != requestKey) return
                    screenshotRequestKey = null
                    continueWithoutVlm(
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
            continueWithoutVlm(context, "vlm_backend_url_missing", "backendBaseUrl metadata is missing")
            return
        }
        val taskStepKey = "${context.task.taskId}:${context.task.currentStep}"

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
                    .put("currentScreen", context.screenType)
                    .put("recoveryGoal", context.recoveryGoal)
                    .put("fallbackReasonCode", context.reasonCode)
                    .put("expectedState", context.expectedState)
                    .put("observedState", context.observedState)
                    .put("uiTreeSummary", buildUiTreeSummary(context.filteredNodes))
                    .put("recentActions", buildRecentActionsJson())
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
                    targetDescription = planJson.optString("targetDescription").takeIf { it.isNotBlank() },
                    nodeId = if (planJson.has("nodeId") && !planJson.isNull("nodeId")) planJson.optInt("nodeId") else null,
                    x = if (planJson.has("x") && !planJson.isNull("x")) planJson.optDouble("x") else null,
                    y = if (planJson.has("y") && !planJson.isNull("y")) planJson.optDouble("y") else null,
                    direction = planJson.optString("direction").takeIf { it.isNotBlank() },
                    distance = if (planJson.has("distance") && !planJson.isNull("distance")) planJson.optDouble("distance") else null,
                    confidence = planJson.optDouble("confidence", 0.0),
                    reason = planJson.optString("reason")
                )
                AutomationLogger.info(
                    "visual_sentinel_action taskId=${context.task.taskId} taskType=${context.task.taskType} " +
                        "platform=${context.task.platform} currentStep=${context.task.currentStep} " +
                        "foregroundPackage=${context.packageName.orEmpty()} " +
                        "rootAvailable=${context.rootAvailable} reason=${context.reasonCode} " +
                        "action=${plan.action} confidence=${plan.confidence} " +
                        "sentinelAttemptCount=${attemptsByTaskStep[taskStepKey] ?: 0}"
                )
                handler.post { executePlan(context, plan) }
            } catch (exception: Exception) {
                handler.post {
                    continueWithoutVlm(
                        context,
                        "vlm_planner_failed",
                        "VLM planner request failed: ${exception.message.orEmpty()}"
                    )
                }
            }
        }.start()
    }

    private fun continueWithoutVlm(context: VlmFallbackContext, reasonCode: String, message: String) {
        inFlightKey = null
        AutomationLogger.warn(
            "vlm_fallback unavailable taskId=${context.task.taskId} step=${context.task.currentStep} " +
                "reason=$reasonCode message=$message"
        )
        AutomationTaskStore.recordVlmFallbackAction(
            packageName = context.packageName,
            currentStep = context.task.currentStep,
            rawNodeCount = context.rawNodeCount,
            filteredNodeCount = context.filteredNodes.size,
            trigger = context.trigger,
            action = "unavailable",
            success = false,
            method = ActionExecutionMethod.NONE.value,
            message = message,
            errorCode = reasonCode
        )
        scheduleProcessTick(700L, "after_vlm_unavailable")
    }

    private fun discardStaleVlmResponse(
        context: VlmFallbackContext,
        currentStep: String?,
        detail: String
    ) {
        AutomationLogger.warn(
            "vlm_response_discarded reason=stale_observation " +
                "detail=$detail taskId=${context.task.taskId} " +
                "requestStep=${context.task.currentStep} currentStep=${currentStep.orEmpty()}"
        )
        scheduleProcessTick(250L, "after_vlm_stale_result")
    }

    private fun isStaleObservation(context: VlmFallbackContext): Boolean {
        val currentFingerprint = currentObservationFingerprint() ?: return false
        return currentFingerprint != context.observationFingerprint
    }

    private fun currentObservationFingerprint(): String? {
        val rootNode = service.rootInActiveWindow ?: return observationFingerprint(
            rootAvailable = false,
            filteredNodes = emptyList()
        )
        val rawNodes = uiTreeCollector.collect(rootNode)
        val filteredNodes = uiNodeSerializer.filter(rawNodes)
        return observationFingerprint(rootAvailable = true, filteredNodes = filteredNodes)
    }

    private fun observationFingerprint(rootAvailable: Boolean, filteredNodes: List<UiNode>): String {
        if (!rootAvailable) return "root_unavailable"
        val fingerprintSource = filteredNodes
            .filter { node -> node.visibleToUser }
            .sortedWith(compareBy<UiNode> { it.boundsTop }.thenBy { it.boundsLeft })
            .map { node ->
                listOf(
                    node.boundsLeft.toString(),
                    node.boundsTop.toString(),
                    node.boundsRight.toString(),
                    node.boundsBottom.toString(),
                    node.className.orEmpty(),
                    node.viewIdResourceName.orEmpty(),
                    node.primaryText().replace(Regex("\\s+"), " ").trim().take(48)
                ).joinToString(":")
            }
            .take(80)
            .joinToString("|")
        return fingerprintSource.hashCode().toUInt().toString(16)
    }

    private fun markVlmSearchSubmitIfNeeded(context: VlmFallbackContext, plan: VlmFallbackPlan): Boolean {
        if (context.task.currentStep != AutomationContract.Step.SEARCH_SUBMIT) return false
        if (plan.action != "tap" && plan.action != "tap_coordinate" && plan.action != "tap_node") return false

        val actionText = listOf(plan.reason, plan.targetDescription.orEmpty())
            .joinToString(" ")
            .lowercase()
        val looksLikeSubmit = listOf("search", "submit", "keyboard", "enter", "검색", "엔터")
            .any { keyword -> actionText.contains(keyword) }
        if (!looksLikeSubmit) return false

        AutomationLogger.info(
            "search_submit_owner=vlm taskId=${context.task.taskId} step=${context.task.currentStep} " +
                "action=${plan.action} reason=${plan.reason}"
        )
        AutomationTaskStore.updateCurrentStep(AutomationContract.Step.ENSURE_RECOMMENDED_SORT)
        return true
    }

    private fun executePlan(context: VlmFallbackContext, plan: VlmFallbackPlan) {
        inFlightKey = null
        val activeTask = AutomationTaskStore.getTask()
        if (activeTask?.taskId != context.task.taskId || activeTask.currentStep != context.task.currentStep) {
            discardStaleVlmResponse(
                context = context,
                currentStep = activeTask?.currentStep,
                detail = "task_or_step_changed"
            )
            return
        }
        if (isStaleObservation(context)) {
            discardStaleVlmResponse(
                context = context,
                currentStep = activeTask.currentStep,
                detail = "screen_fingerprint_changed"
            )
            return
        }
        if (isHostAppForeground(context.packageName)) {
            AutomationLogger.warn(
                "visual_sentinel_abort taskId=${context.task.taskId} taskType=${context.task.taskType} " +
                    "platform=${context.task.platform} currentStep=${context.task.currentStep} " +
                    "foregroundPackage=${context.packageName.orEmpty()} rootAvailable=${context.rootAvailable} " +
                    "reason=host_app_foreground action=${plan.action} confidence=${plan.confidence} " +
                    "sentinelAttemptCount=${sentinelAttemptCount(context)}"
            )
            scheduleProcessTick(500L, "after_vlm_host_app_skip")
            return
        }

        val policyOverridePlan = systemPermissionPolicyOverride(context, plan)
        if (policyOverridePlan != null) {
            AutomationLogger.warn(
                "visual_sentinel_system_policy_override taskId=${context.task.taskId} " +
                    "taskType=${context.task.taskType} platform=${context.task.platform} " +
                    "currentStep=${context.task.currentStep} foregroundPackage=${context.packageName.orEmpty()} " +
                    "rootAvailable=${context.rootAvailable} originalAction=${plan.action} action=back " +
                    "confidence=${plan.confidence} sentinelAttemptCount=${sentinelAttemptCount(context)} " +
                    "reason=notification_permission_tap_blocked"
            )
            executeBackPlan(context, policyOverridePlan)
            return
        }

        if (isUnsafeSystemUiAction(context, plan)) {
            AutomationLogger.warn(
                    "visual_sentinel_abort taskId=${context.task.taskId} taskType=${context.task.taskType} " +
                        "platform=${context.task.platform} currentStep=${context.task.currentStep} " +
                        "foregroundPackage=${context.packageName.orEmpty()} " +
                    "rootAvailable=${context.rootAvailable} reason=unsafe_system_ui_action " +
                    "action=${plan.action} confidence=${plan.confidence} " +
                    "sentinelAttemptCount=${sentinelAttemptCount(context)}"
            )
            stopWithVlmFailure(
                context,
                "vlm_unsafe_system_ui_action",
                "VLM returned unsafe system UI action=${plan.action} target=${plan.targetDescription.orEmpty()}"
            )
            return
        }
        if (isUnsafeBusinessRecoveryAction(context, plan)) {
            blockUnsafeBusinessRecoveryAction(context, plan)
            return
        }

        when (plan.action) {
            "tap",
            "tap_coordinate" -> executeTapPlan(context, plan)
            "tap_node" -> executeTapNodePlan(context, plan)
            "back" -> executeBackPlan(context, plan)
            "swipe" -> executeSwipePlan(context, plan)
            "none" -> {
                AutomationLogger.info(
                    "visual_sentinel_none taskId=${context.task.taskId} taskType=${context.task.taskType} " +
                        "platform=${context.task.platform} currentStep=${context.task.currentStep} " +
                        "foregroundPackage=${context.packageName.orEmpty()} " +
                        "rootAvailable=${context.rootAvailable} reason=${context.reasonCode} " +
                        "action=none confidence=${plan.confidence} " +
                        "sentinelAttemptCount=${sentinelAttemptCount(context)}"
                )
                rememberAction(context, plan, true, "none")
                AutomationTaskStore.recordVlmFallbackAction(
                    packageName = context.packageName,
                    currentStep = context.task.currentStep,
                    rawNodeCount = context.rawNodeCount,
                    filteredNodeCount = context.filteredNodes.size,
                    trigger = context.trigger,
                    action = "none",
                    success = true,
                    method = ActionExecutionMethod.NONE.value,
                    message = "VLM found no blocking overlay confidence=${plan.confidence} reason=${plan.reason}"
                )
                scheduleProcessTick(350L, "after_vlm_none")
            }
            "wait" -> {
                AutomationLogger.info(
                    "visual_sentinel_same_step_retry taskId=${context.task.taskId} taskType=${context.task.taskType} " +
                        "platform=${context.task.platform} currentStep=${context.task.currentStep} " +
                        "foregroundPackage=${context.packageName.orEmpty()} " +
                        "rootAvailable=${context.rootAvailable} reason=${context.reasonCode} " +
                        "action=wait confidence=${plan.confidence} " +
                        "sentinelAttemptCount=${sentinelAttemptCount(context)}"
                )
                rememberAction(context, plan, true, "wait")
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
            "abort" -> {
                AutomationLogger.warn(
                    "visual_sentinel_abort taskId=${context.task.taskId} taskType=${context.task.taskType} " +
                        "platform=${context.task.platform} currentStep=${context.task.currentStep} " +
                        "foregroundPackage=${context.packageName.orEmpty()} " +
                        "rootAvailable=${context.rootAvailable} reason=${context.reasonCode} " +
                        "action=abort confidence=${plan.confidence} " +
                        "sentinelAttemptCount=${sentinelAttemptCount(context)}"
                )
                stopWithVlmFailure(
                    context,
                    "vlm_recovery_aborted",
                    "VLM aborted recovery confidence=${plan.confidence} reason=${plan.reason}"
                )
            }
            else -> {
                AutomationLogger.warn(
                    "visual_sentinel_abort taskId=${context.task.taskId} taskType=${context.task.taskType} " +
                        "platform=${context.task.platform} currentStep=${context.task.currentStep} " +
                        "foregroundPackage=${context.packageName.orEmpty()} " +
                        "rootAvailable=${context.rootAvailable} reason=invalid_action " +
                        "action=${plan.action} confidence=${plan.confidence} " +
                        "sentinelAttemptCount=${sentinelAttemptCount(context)}"
                )
                stopWithVlmFailure(
                    context,
                    "vlm_invalid_action",
                    "VLM returned unsupported action=${plan.action}"
                )
            }
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
        rememberAction(context, plan, result.success, result.message)

        if (result.success) {
            AutomationLogger.info(
                    "visual_sentinel_same_step_retry taskId=${context.task.taskId} taskType=${context.task.taskType} " +
                        "platform=${context.task.platform} currentStep=${context.task.currentStep} " +
                        "foregroundPackage=${context.packageName.orEmpty()} " +
                    "rootAvailable=${context.rootAvailable} reason=${context.reasonCode} " +
                    "action=tap confidence=${plan.confidence} " +
                    "sentinelAttemptCount=${sentinelAttemptCount(context)}"
            )
            if (markVlmSearchSubmitIfNeeded(context, plan)) {
                scheduleProcessTick(500L, "after_vlm_submit")
            } else {
                scheduleProcessTick(500L, "after_vlm_recovery")
            }
        } else {
            stopWithVlmFailure(
                context,
                "vlm_tap_failed",
                "VLM tap dispatch failed: ${result.message}"
            )
        }
    }

    private fun executeTapNodePlan(context: VlmFallbackContext, plan: VlmFallbackPlan) {
        val nodeId = plan.nodeId
        if (nodeId == null) {
            stopWithVlmFailure(context, "vlm_invalid_tap_node", "VLM tap_node action is missing nodeId")
            return
        }
        val actionPlan = ActionPlan(
            actionType = AutomationActionType.CLICK.value,
            targetNodeId = nodeId,
            textToInput = null,
            reasonCode = "vlm_tap_node",
            confidence = plan.confidence
        )
        val result = actionExecutor.execute(actionPlan, context.filteredNodes)
        AutomationTaskStore.recordVlmFallbackAction(
            packageName = context.packageName,
            currentStep = context.task.currentStep,
            rawNodeCount = context.rawNodeCount,
            filteredNodeCount = context.filteredNodes.size,
            trigger = context.trigger,
            action = "tap_node",
            success = result.success,
            method = result.method,
            message = "VLM tap_node nodeId=$nodeId target=${plan.targetDescription.orEmpty()} " +
                "confidence=${plan.confidence} reason=${plan.reason} result=${result.message}",
            errorCode = result.errorCode
        )
        rememberAction(context, plan, result.success, result.message)
        if (result.success) {
            AutomationLogger.info(
                    "visual_sentinel_same_step_retry taskId=${context.task.taskId} taskType=${context.task.taskType} " +
                        "platform=${context.task.platform} currentStep=${context.task.currentStep} " +
                        "foregroundPackage=${context.packageName.orEmpty()} " +
                    "rootAvailable=${context.rootAvailable} reason=${context.reasonCode} " +
                    "action=tap_node confidence=${plan.confidence} " +
                    "sentinelAttemptCount=${sentinelAttemptCount(context)}"
            )
            if (markVlmSearchSubmitIfNeeded(context, plan)) {
                scheduleProcessTick(500L, "after_vlm_submit")
            } else {
                scheduleProcessTick(500L, "after_vlm_recovery")
            }
        } else {
            scheduleProcessTick(500L, "after_vlm_tap_node_failed")
        }
    }

    private fun executeBackPlan(context: VlmFallbackContext, plan: VlmFallbackPlan) {
        val result = actionExecutor.executeBack(reason = "vlm:${plan.reason}")
        AutomationTaskStore.recordVlmFallbackAction(
            packageName = context.packageName,
            currentStep = context.task.currentStep,
            rawNodeCount = context.rawNodeCount,
            filteredNodeCount = context.filteredNodes.size,
            trigger = context.trigger,
            action = "back",
            success = result.success,
            method = result.method,
            message = "VLM back target=${plan.targetDescription.orEmpty()} " +
                "confidence=${plan.confidence} reason=${plan.reason} result=${result.message}",
            errorCode = result.errorCode
        )
        rememberAction(context, plan, result.success, result.message)
        if (result.success) {
            AutomationLogger.info(
                    "visual_sentinel_same_step_retry taskId=${context.task.taskId} taskType=${context.task.taskType} " +
                        "platform=${context.task.platform} currentStep=${context.task.currentStep} " +
                        "foregroundPackage=${context.packageName.orEmpty()} " +
                    "rootAvailable=${context.rootAvailable} reason=${context.reasonCode} " +
                    "action=back confidence=${plan.confidence} " +
                    "sentinelAttemptCount=${sentinelAttemptCount(context)}"
            )
            scheduleProcessTick(900L, "after_vlm_recovery")
        } else {
            scheduleProcessTick(500L, "after_vlm_back_failed")
        }
    }

    private fun executeSwipePlan(context: VlmFallbackContext, plan: VlmFallbackPlan) {
        val direction = plan.direction
        if (direction.isNullOrBlank()) {
            stopWithVlmFailure(context, "vlm_invalid_swipe", "VLM swipe action is missing direction")
            return
        }
        val distance = (plan.distance ?: 0.55).toFloat()
        val result = actionExecutor.executeCoordinateSwipe(
            direction = direction,
            distance = distance,
            reason = "vlm:${plan.reason}"
        )
        AutomationTaskStore.recordVlmFallbackAction(
            packageName = context.packageName,
            currentStep = context.task.currentStep,
            rawNodeCount = context.rawNodeCount,
            filteredNodeCount = context.filteredNodes.size,
            trigger = context.trigger,
            action = "swipe",
            success = result.success,
            method = result.method,
            message = "VLM swipe direction=$direction distance=$distance target=${plan.targetDescription.orEmpty()} " +
                "confidence=${plan.confidence} reason=${plan.reason} result=${result.message}",
            errorCode = result.errorCode
        )
        rememberAction(context, plan, result.success, result.message)
        if (result.success) {
            AutomationLogger.info(
                    "visual_sentinel_same_step_retry taskId=${context.task.taskId} taskType=${context.task.taskType} " +
                        "platform=${context.task.platform} currentStep=${context.task.currentStep} " +
                        "foregroundPackage=${context.packageName.orEmpty()} " +
                    "rootAvailable=${context.rootAvailable} reason=${context.reasonCode} " +
                    "action=swipe confidence=${plan.confidence} " +
                    "sentinelAttemptCount=${sentinelAttemptCount(context)}"
            )
            scheduleProcessTick(900L, "after_vlm_recovery")
        } else {
            scheduleProcessTick(500L, "after_vlm_swipe_failed")
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

    private fun rememberAction(
        context: VlmFallbackContext,
        plan: VlmFallbackPlan,
        success: Boolean,
        outcome: String
    ) {
        recentActions.addLast(
            VlmActionHistoryEntry(
                taskId = context.task.taskId,
                step = context.task.currentStep,
                action = plan.action,
                targetDescription = plan.targetDescription,
                success = success,
                outcome = outcome.take(160),
                reason = plan.reason.take(160)
            )
        )
        while (recentActions.size > 8) {
            recentActions.removeFirst()
        }
    }

    private fun buildRecentActionsJson(): JSONArray {
        val actions = JSONArray()
        recentActions.takeLast(5).forEach { action ->
            actions.put(
                JSONObject()
                    .put("taskId", action.taskId)
                    .put("step", action.step)
                    .put("action", action.action)
                    .put("targetDescription", action.targetDescription.orEmpty())
                    .put("success", action.success)
                    .put("outcome", action.outcome)
                    .put("reason", action.reason)
            )
        }
        return actions
    }

    private fun sentinelAttemptCount(context: VlmFallbackContext): Int {
        return attemptsByTaskStep["${context.task.taskId}:${context.task.currentStep}"] ?: 0
    }

    private fun isUnsafeSystemUiAction(context: VlmFallbackContext, plan: VlmFallbackPlan): Boolean {
        if (!isSystemInterruptionPackage(context.packageName) && !isLikelySystemPermissionPlan(context, plan)) {
            return false
        }
        if (containsSensitiveSystemUiSignal(context)) return true
        return when (plan.action) {
            "none",
            "wait",
            "back",
            "abort" -> false
            "tap",
            "tap_coordinate",
            "tap_node" -> !isSafeSystemDismissTarget(plan)
            else -> true
        }
    }

    private fun isUnsafeBusinessRecoveryAction(context: VlmFallbackContext, plan: VlmFallbackPlan): Boolean {
        if (plan.action !in listOf("tap", "tap_coordinate", "tap_node")) return false

        val planText = listOfNotNull(plan.targetDescription, plan.reason).joinToString(" ")
        if (ActionPolicy.isUnsafeBusinessActionText(planText)) return true
        if (isNotificationOptInAction(context, plan)) return true

        val targetNode = findVlmPolicyTargetNode(context, plan)
        if (isNotificationOptInTarget(context, targetNode)) return true
        return ActionPolicy.isUnsafeBusinessActionNode(targetNode, context.filteredNodes)
    }

    private fun isNotificationOptInAction(context: VlmFallbackContext, plan: VlmFallbackPlan): Boolean {
        val contextText = context.filteredNodes.joinToString(" ") { node -> node.searchableText() }
        val targetText = plan.targetDescription.orEmpty()
        return containsNotificationOptInContext(contextText) &&
            !containsNotificationOptInDeclineText(targetText) &&
            containsNotificationOptInAcceptText(targetText)
    }

    private fun isNotificationOptInTarget(context: VlmFallbackContext, targetNode: UiNode?): Boolean {
        if (targetNode == null) return false
        val contextText = context.filteredNodes.joinToString(" ") { node -> node.searchableText() }
        val targetText = targetNode.searchableText()
        return containsNotificationOptInContext(contextText) &&
            !containsNotificationOptInDeclineText(targetText) &&
            containsNotificationOptInAcceptText(targetText)
    }

    private fun containsNotificationOptInContext(text: String): Boolean {
        val normalizedText = text.lowercase()
        return normalizedText.contains("배송 알림") ||
            normalizedText.contains("주문 알림") ||
            normalizedText.contains("알림 켜") ||
            normalizedText.contains("알림을 켜") ||
            normalizedText.contains("알림 받") ||
            normalizedText.contains("알림을 받을") ||
            normalizedText.contains("notification")
    }

    private fun containsNotificationOptInAcceptText(text: String): Boolean {
        val normalizedText = text.lowercase()
        return normalizedText.contains("알림 켜기") ||
            normalizedText.contains("알림 받기") ||
            normalizedText.contains("알림을 켜") ||
            normalizedText.contains("알림을 받을") ||
            normalizedText.contains("허용") ||
            normalizedText.contains("allow") ||
            normalizedText.contains("enable")
    }

    private fun containsNotificationOptInDeclineText(text: String): Boolean {
        val normalizedText = text.lowercase()
        return normalizedText.contains("싫어요") ||
            normalizedText.contains("아니요") ||
            normalizedText.contains("안 할래요") ||
            normalizedText.contains("받지 않기") ||
            normalizedText.contains("나중에") ||
            normalizedText.contains("다음에") ||
            normalizedText.contains("닫기") ||
            normalizedText.contains("close")
    }

    private fun findVlmPolicyTargetNode(context: VlmFallbackContext, plan: VlmFallbackPlan): UiNode? {
        plan.nodeId?.let { nodeId ->
            return context.filteredNodes.firstOrNull { node -> node.id == nodeId }
        }

        val normalizedX = plan.x ?: return null
        val normalizedY = plan.y ?: return null
        val displayMetrics = service.resources.displayMetrics
        val x = (normalizedX.coerceIn(0.0, 1.0) * displayMetrics.widthPixels).roundToInt()
        val y = (normalizedY.coerceIn(0.0, 1.0) * displayMetrics.heightPixels).roundToInt()

        return context.filteredNodes
            .filter { node ->
                x in node.boundsLeft..node.boundsRight &&
                    y in node.boundsTop..node.boundsBottom
            }
            .minByOrNull { node -> node.width * node.height }
            ?: context.filteredNodes.minByOrNull { node ->
                kotlin.math.abs(node.centerX - x) + kotlin.math.abs(node.centerY - y)
            }
    }

    private fun blockUnsafeBusinessRecoveryAction(context: VlmFallbackContext, plan: VlmFallbackPlan) {
        val targetNodeText = plan.nodeId
            ?.let { nodeId -> context.filteredNodes.firstOrNull { node -> node.id == nodeId } }
            ?.searchableText()
            .orEmpty()
        val message = "Blocked unsafe VLM recovery action=${plan.action} " +
            "target=${plan.targetDescription.orEmpty()} nodeText=$targetNodeText reason=${plan.reason}"
        AutomationLogger.warn(
            "vlm_action_blocked_by_policy taskId=${context.task.taskId} " +
                "currentStep=${context.task.currentStep} actionType=${plan.action} " +
                "target=${plan.targetDescription.orEmpty()} nodeText=$targetNodeText " +
                "policyReason=recovery_target_is_business_action"
        )
        AutomationLogger.warn(
            "visual_sentinel_blocked taskId=${context.task.taskId} taskType=${context.task.taskType} " +
                "platform=${context.task.platform} currentStep=${context.task.currentStep} " +
                "foregroundPackage=${context.packageName.orEmpty()} rootAvailable=${context.rootAvailable} " +
                "reason=unsafe_business_recovery_action action=${plan.action} " +
                "confidence=${plan.confidence} sentinelAttemptCount=${sentinelAttemptCount(context)}"
        )
        rememberAction(context, plan, false, message)
        AutomationTaskStore.recordVlmFallbackAction(
            packageName = context.packageName,
            currentStep = context.task.currentStep,
            rawNodeCount = context.rawNodeCount,
            filteredNodeCount = context.filteredNodes.size,
            trigger = context.trigger,
            action = plan.action,
            success = false,
            method = ActionExecutionMethod.NONE.value,
            message = message,
            errorCode = ActionPolicy.UNSAFE_RECOVERY_ACTION_ERROR
        )
        scheduleProcessTick(500L, "after_vlm_unsafe_business_action")
    }

    private fun systemPermissionPolicyOverride(
        context: VlmFallbackContext,
        plan: VlmFallbackPlan
    ): VlmFallbackPlan? {
        if (context.rootAvailable) return null
        if (!isLikelyNotificationPermissionPlan(context, plan)) return null
        if (plan.action !in listOf("tap", "tap_coordinate", "tap_node")) return null

        return plan.copy(
            action = "back",
            targetDescription = "notification permission dialog",
            reason = "Android policy: notification permission dialogs must be dismissed with back, not coordinate tap. ${plan.reason}"
        )
    }

    private fun isSystemInterruptionPackage(packageName: String?): Boolean {
        return packageName == "com.google.android.permissioncontroller" ||
            packageName == "com.android.permissioncontroller" ||
            packageName == "com.android.settings" ||
            packageName == "com.android.systemui"
    }

    private fun isHostAppForeground(packageName: String?): Boolean {
        return packageName == service.packageName
    }

    private fun containsSensitiveSystemUiSignal(context: VlmFallbackContext): Boolean {
        val text = listOf(
            context.expectedState,
            context.observedState,
            context.screenType,
            context.reasonCode
        ).joinToString(" ").lowercase()
        return text.contains("password") ||
            text.contains("비밀번호") ||
            text.contains("결제") ||
            text.contains("인증") ||
            text.contains("camera") ||
            text.contains("카메라") ||
            text.contains("microphone") ||
            text.contains("마이크") ||
            text.contains("contacts") ||
            text.contains("연락처") ||
            text.contains("files") ||
            text.contains("사진")
    }

    private fun isSafeSystemDismissTarget(plan: VlmFallbackPlan): Boolean {
        val targetText = listOfNotNull(plan.targetDescription, plan.reason)
            .joinToString(" ")
            .lowercase()
        return targetText.contains("dismiss") ||
            targetText.contains("close") ||
            targetText.contains("deny") ||
            targetText.contains("don't allow") ||
            targetText.contains("don’t allow") ||
            targetText.contains("not allow") ||
            targetText.contains("거부") ||
            targetText.contains("허용 안함") ||
            targetText.contains("닫기")
    }

    private fun isLikelySystemPermissionPlan(context: VlmFallbackContext, plan: VlmFallbackPlan): Boolean {
        val text = permissionPlanText(context, plan)
        return text.contains("permission") ||
            text.contains("권한") ||
            text.contains("허용하시겠습니까")
    }

    private fun isLikelyNotificationPermissionPlan(context: VlmFallbackContext, plan: VlmFallbackPlan): Boolean {
        val text = permissionPlanText(context, plan)
        val hasNotificationSignal = text.contains("notification") ||
            text.contains("notifications") ||
            text.contains("알림")
        val hasPermissionSignal = text.contains("permission") ||
            text.contains("권한") ||
            text.contains("허용하시겠습니까") ||
            text.contains("allow") ||
            text.contains("허용")
        return hasNotificationSignal && hasPermissionSignal
    }

    private fun permissionPlanText(context: VlmFallbackContext, plan: VlmFallbackPlan): String {
        return listOfNotNull(
            context.packageName,
            context.screenType,
            context.reasonCode,
            context.expectedState,
            context.observedState,
            plan.targetDescription,
            plan.reason
        ).joinToString(" ").lowercase()
    }

    private fun sanitize(value: String?): String {
        return value
            ?.replace(Regex("\\s+"), " ")
            ?.trim()
            ?.take(80)
            .orEmpty()
    }

    companion object {
        private const val MAX_ATTEMPTS_PER_STEP = 3
        private const val MAX_TOTAL_ATTEMPTS = 8
        private const val MAX_NO_PROGRESS_PER_STEP = 2
        private const val SCREENSHOT_TIMEOUT_MS = 5000L
    }
}
