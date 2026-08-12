package com.ddalangoo.ddalangoo

import android.content.Intent
import com.ddalangoo.ddalangoo.accessibility.AutomationLogger
import com.ddalangoo.ddalangoo.accessibility.AutomationContract
import com.ddalangoo.ddalangoo.accessibility.DdalangooAccessibilityService
import com.ddalangoo.ddalangoo.accessibility.AutomationTask
import com.ddalangoo.ddalangoo.accessibility.AutomationTaskStore
import com.ddalangoo.ddalangoo.accessibility.PurchaseHistoryExtractionStore
import com.ddalangoo.ddalangoo.accessibility.SearchInspectionStore
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
                        searchKeyword = call.argument<String>(AutomationContract.Argument.SEARCH_KEYWORD).orEmpty(),
                        optionName = call.argument<String>(AutomationContract.Argument.OPTION_NAME).orEmpty(),
                        quantity = call.argument<Int>(AutomationContract.Argument.QUANTITY) ?: 1,
                        platform = call.argument<String>(AutomationContract.Argument.PLATFORM)
                            ?: AutomationContract.Platform.UNKNOWN,
                        packageName = call.argument<String>(AutomationContract.Argument.PACKAGE_NAME),
                        currentStep = call.argument<String>(AutomationContract.Argument.CURRENT_STEP)
                            ?: AutomationContract.Step.SEARCH_INPUT
                    )
                    AutomationTaskStore.setTask(task)
                    if (shouldLaunchPackageForTask(task)) {
                        task.packageName?.let { packageName ->
                            launchPackage(packageName)
                        }
                    }
                    DdalangooAccessibilityService.scheduleTaskStartedTicks()
                    result.success(true)
                }

                AutomationContract.Method.LAUNCH_PLATFORM_APP -> {
                    val packageName = call.argument<String>(AutomationContract.Argument.PACKAGE_NAME)
                    result.success(packageName?.let { launchPackage(it) } ?: false)
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

                AutomationContract.Method.GET_SEARCH_INSPECTION_RESULT -> {
                    result.success(SearchInspectionStore.resultJson())
                }

                AutomationContract.Method.CLEAR_PURCHASE_HISTORY_RESULT -> {
                    PurchaseHistoryExtractionStore.clear()
                    result.success(true)
                }

                AutomationContract.Method.CLEAR_SEARCH_INSPECTION_RESULT -> {
                    SearchInspectionStore.clear()
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

    private fun launchPackage(packageName: String): Boolean {
        val launchIntent = packageManager.getLaunchIntentForPackage(packageName)
        if (launchIntent == null) {
            AutomationLogger.warn("launch failed packageName=$packageName reason=launchIntent_missing")
            return false
        }

        launchIntent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        startActivity(launchIntent)
        AutomationLogger.info("launch requested packageName=$packageName")
        return true
    }

    private fun shouldLaunchPackageForTask(task: AutomationTask): Boolean {
        return task.currentStep == AutomationContract.Step.OPEN_MY_KURLY ||
            task.currentStep == AutomationContract.Step.OPEN_MY_COUPANG ||
            task.currentStep == AutomationContract.Step.OPEN_SEARCH ||
            task.taskType == AutomationContract.TaskType.INSPECT_SEARCH_FLOW
    }
}
