package com.ddalangoo.ddalangoo.accessibility

import android.accessibilityservice.AccessibilityService
import android.content.Context
import android.graphics.PixelFormat
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.view.Gravity
import android.view.View
import android.view.WindowManager
import io.flutter.FlutterInjector
import io.flutter.embedding.android.FlutterTextureView
import io.flutter.embedding.android.FlutterView
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.embedding.engine.dart.DartExecutor
import io.flutter.plugin.common.MethodChannel

class ShoppingAutomationFlutterOverlay(
    private val service: AccessibilityService
) {
    private val mainHandler = Handler(Looper.getMainLooper())
    private val windowManager =
        service.getSystemService(Context.WINDOW_SERVICE) as WindowManager

    private var flutterEngine: FlutterEngine? = null
    private var flutterView: FlutterView? = null
    private var channel: MethodChannel? = null
    private var isVisible = false
    private var lastState: Map<String, Any?>? = null

    fun show(task: AutomationTask) {
        lastState = stateMapFor(task)
        if (!isVisible) {
            createAndAttachFlutterView()
        }
        sendState()
    }

    fun update(task: AutomationTask) {
        lastState = stateMapFor(task)
        if (isVisible) {
            sendState()
        } else {
            show(task)
        }
    }

    fun hide() {
        if (!isVisible && flutterEngine == null && flutterView == null) {
            return
        }

        flutterView?.let { view ->
            runCatching {
                windowManager.removeView(view)
            }.onFailure { error ->
                AutomationLogger.warn(
                    "shopping_flutter_overlay remove failed reason=${error.message.orEmpty()}"
                )
            }
            view.detachFromFlutterEngine()
        }
        flutterEngine?.destroy()
        flutterView = null
        flutterEngine = null
        channel = null
        isVisible = false
    }

    fun hideForScreenshot(): Boolean {
        val view = flutterView ?: return false
        if (!isVisible || view.visibility != View.VISIBLE) {
            return false
        }
        view.visibility = View.INVISIBLE
        return true
    }

    fun restoreAfterScreenshot() {
        val view = flutterView ?: return
        if (isVisible) {
            view.visibility = View.VISIBLE
            sendState()
        }
    }

    private fun createAndAttachFlutterView() {
        val appContext = service.applicationContext
        val loader = FlutterInjector.instance().flutterLoader()
        loader.startInitialization(appContext)
        loader.ensureInitializationComplete(appContext, null)

        val engine = FlutterEngine(appContext)
        val entrypoint = DartExecutor.DartEntrypoint(
            loader.findAppBundlePath(),
            OVERLAY_ENTRYPOINT
        )
        engine.dartExecutor.executeDartEntrypoint(entrypoint)

        val textureView = FlutterTextureView(service).apply {
            setOpaque(false)
        }
        val view = FlutterView(service, textureView).apply {
            setBackgroundColor(android.graphics.Color.TRANSPARENT)
            importantForAccessibility = View.IMPORTANT_FOR_ACCESSIBILITY_NO_HIDE_DESCENDANTS
            attachToFlutterEngine(engine)
        }

        val params = WindowManager.LayoutParams(
            WindowManager.LayoutParams.MATCH_PARENT,
            WindowManager.LayoutParams.MATCH_PARENT,
            WindowManager.LayoutParams.TYPE_ACCESSIBILITY_OVERLAY,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or
                WindowManager.LayoutParams.FLAG_NOT_TOUCHABLE or
                WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN,
            PixelFormat.TRANSLUCENT
        ).apply {
            gravity = Gravity.TOP or Gravity.START
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
                layoutInDisplayCutoutMode =
                    WindowManager.LayoutParams.LAYOUT_IN_DISPLAY_CUTOUT_MODE_SHORT_EDGES
            }
        }

        runCatching {
            windowManager.addView(view, params)
            flutterEngine = engine
            flutterView = view
            channel = MethodChannel(engine.dartExecutor.binaryMessenger, CHANNEL_NAME)
            isVisible = true
            AutomationLogger.info("shopping_flutter_overlay shown")
        }.onFailure { error ->
            AutomationLogger.warn(
                "shopping_flutter_overlay show failed reason=${error.message.orEmpty()}"
            )
            view.detachFromFlutterEngine()
            engine.destroy()
            flutterEngine = null
            flutterView = null
            channel = null
            isVisible = false
        }
    }

    private fun sendState() {
        val state = lastState ?: return
        mainHandler.post {
            channel?.invokeMethod("update", state)
        }
        mainHandler.postDelayed({
            channel?.invokeMethod("update", state)
        }, INITIAL_STATE_REPLAY_DELAY_MS)
    }

    private fun stateMapFor(task: AutomationTask): Map<String, Any?> {
        val accumulatedCount = PurchaseHistoryExtractionStore.accumulatedCandidates().size
        return mapOf(
            "platform" to task.platform,
            "currentStep" to task.currentStep,
            "statusMessage" to statusMessageFor(task, accumulatedCount),
            "progressLabel" to progressLabelFor(task, accumulatedCount),
            "accumulatedCount" to accumulatedCount
        )
    }

    private fun statusMessageFor(task: AutomationTask, accumulatedCount: Int): String {
        if (accumulatedCount > 0) {
            return "구매 이력 ${accumulatedCount}개를 확인했어요."
        }
        return when (task.currentStep) {
            AutomationContract.Step.OPEN_MY_KURLY -> "컬리 앱으로 이동하고 있어요."
            AutomationContract.Step.OPEN_MY_COUPANG -> "쿠팡 앱으로 이동하고 있어요."
            AutomationContract.Step.OPEN_ORDER_HISTORY -> "주문 내역 화면으로 이동하고 있어요."
            AutomationContract.Step.DUMP_PURCHASE_HISTORY -> "주문 내역 화면을 읽고 있어요."
            AutomationContract.Step.EXTRACT_PURCHASE_HISTORY -> "구매한 상품 정보를 정리하고 있어요."
            AutomationContract.Step.SCROLL_PURCHASE_HISTORY -> "더 많은 구매 이력을 찾고 있어요."
            AutomationContract.Step.FINISH_PURCHASE_HISTORY -> "구매 이력 저장을 마무리하고 있어요."
            else -> "구매 이력을 불러오고 있어요."
        }
    }

    private fun progressLabelFor(task: AutomationTask, accumulatedCount: Int): String {
        if (accumulatedCount > 0) {
            return "${accumulatedCount}개 항목 확인됨"
        }
        return when (task.currentStep) {
            AutomationContract.Step.OPEN_MY_KURLY -> "컬리 앱 여는 중"
            AutomationContract.Step.OPEN_MY_COUPANG -> "쿠팡 앱 여는 중"
            AutomationContract.Step.OPEN_ORDER_HISTORY -> "주문 내역 여는 중"
            AutomationContract.Step.DUMP_PURCHASE_HISTORY -> "주문 내역 읽는 중"
            AutomationContract.Step.EXTRACT_PURCHASE_HISTORY -> "상품명 정리 중"
            AutomationContract.Step.SCROLL_PURCHASE_HISTORY -> "더 많은 이력 찾는 중"
            AutomationContract.Step.FINISH_PURCHASE_HISTORY -> "마무리 중"
            else -> "자동화 진행 중"
        }
    }

    private companion object {
        const val CHANNEL_NAME = "com.ddalangoo.ddalangoo/shopping_automation_overlay"
        const val OVERLAY_ENTRYPOINT = "shoppingAutomationOverlayMain"
        const val INITIAL_STATE_REPLAY_DELAY_MS = 350L
    }
}
