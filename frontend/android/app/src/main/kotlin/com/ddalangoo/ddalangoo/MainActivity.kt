package com.ddalangoo.ddalangoo

import com.ddalangoo.ddalangoo.accessibility.AutomationLogger
import com.ddalangoo.ddalangoo.accessibility.AutomationTask
import com.ddalangoo.ddalangoo.accessibility.AutomationTaskStore
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel

class MainActivity : FlutterActivity() {
    private val accessibilityAutomationChannelName = "ddalangoo/accessibility_automation"

    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)

        MethodChannel(
            flutterEngine.dartExecutor.binaryMessenger,
            accessibilityAutomationChannelName
        ).setMethodCallHandler { call, result ->
            when (call.method) {
                "setTestAutomationTask" -> {
                    val task = AutomationTask(
                        taskId = call.argument<String>("taskId") ?: "test-task",
                        taskType = call.argument<String>("taskType") ?: "search_and_add_to_cart",
                        targetProductName = call.argument<String>("targetProductName").orEmpty(),
                        quantity = call.argument<Int>("quantity") ?: 1,
                        platform = call.argument<String>("platform") ?: "unknown",
                        packageName = call.argument<String>("packageName"),
                        currentStep = call.argument<String>("currentStep") ?: "search_input"
                    )
                    AutomationTaskStore.setTask(task)
                    result.success(true)
                }

                "clearAutomationTask" -> {
                    AutomationTaskStore.clearTask()
                    result.success(true)
                }

                "dumpCurrentUiTree" -> {
                    AutomationLogger.info("dumpCurrentUiTree requested. Trigger a screen event to collect the current UI tree.")
                    result.success(true)
                }

                else -> result.notImplemented()
            }
        }
    }
}
