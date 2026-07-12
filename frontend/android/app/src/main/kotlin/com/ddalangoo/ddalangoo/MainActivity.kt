package com.ddalangoo.ddalangoo

import com.ddalangoo.ddalangoo.accessibility.AutomationLogger
import com.ddalangoo.ddalangoo.accessibility.AutomationContract
import com.ddalangoo.ddalangoo.accessibility.AutomationTask
import com.ddalangoo.ddalangoo.accessibility.AutomationTaskStore
import com.ddalangoo.ddalangoo.accessibility.PurchaseHistoryExtractionStore
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel

class MainActivity : FlutterActivity() {
    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)

        MethodChannel(
            flutterEngine.dartExecutor.binaryMessenger,
            AutomationContract.CHANNEL_NAME
        ).setMethodCallHandler { call, result ->
            when (call.method) {
                AutomationContract.Method.SET_TASK,
                AutomationContract.Method.SET_TEST_TASK -> {
                    val task = AutomationTask(
                        taskId = call.argument<String>(AutomationContract.Argument.TASK_ID) ?: "test-task",
                        taskType = call.argument<String>(AutomationContract.Argument.TASK_TYPE)
                            ?: AutomationContract.TaskType.SEARCH_AND_ADD_TO_CART,
                        targetProductName = call.argument<String>(AutomationContract.Argument.TARGET_PRODUCT_NAME).orEmpty(),
                        quantity = call.argument<Int>(AutomationContract.Argument.QUANTITY) ?: 1,
                        platform = call.argument<String>(AutomationContract.Argument.PLATFORM)
                            ?: AutomationContract.Platform.UNKNOWN,
                        packageName = call.argument<String>(AutomationContract.Argument.PACKAGE_NAME),
                        currentStep = call.argument<String>(AutomationContract.Argument.CURRENT_STEP)
                            ?: AutomationContract.Step.SEARCH_INPUT
                    )
                    AutomationTaskStore.setTask(task)
                    result.success(true)
                }

                AutomationContract.Method.CLEAR_TASK -> {
                    AutomationTaskStore.clearTask()
                    result.success(true)
                }

                AutomationContract.Method.GET_STATUS -> {
                    result.success(AutomationTaskStore.statusMap())
                }

                AutomationContract.Method.GET_ACCUMULATED_PURCHASE_HISTORY_RESULT -> {
                    result.success(PurchaseHistoryExtractionStore.accumulatedCandidatesJson())
                }

                AutomationContract.Method.CLEAR_PURCHASE_HISTORY_RESULT -> {
                    PurchaseHistoryExtractionStore.clear()
                    result.success(true)
                }

                AutomationContract.Method.DUMP_CURRENT_UI_TREE -> {
                    AutomationLogger.info("dumpCurrentUiTree requested. Trigger a screen event to collect the current UI tree.")
                    result.success(true)
                }

                else -> result.notImplemented()
            }
        }
    }
}
