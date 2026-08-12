package com.ddalangoo.ddalangoo.accessibility

/**
 * Flutter와 Android Accessibility 모듈 사이의 공개 계약을 한 곳에 모은다.
 *
 * 나중에 다른 프론트 브랜치로 옮길 때는 이 파일의 channel/method/task/step 값만
 * 맞추면 나머지 rule engine은 독립적으로 가져갈 수 있다.
 */
object AutomationContract {
    const val CONTRACT_VERSION = 1
    const val CHANNEL_NAME = "ddalangoo/accessibility_automation"

    object Method {
        const val SET_TASK = "setAutomationTask"
        const val SET_TEST_TASK = "setTestAutomationTask"
        const val CLEAR_TASK = "clearAutomationTask"
        const val GET_STATUS = "getAutomationStatus"
        const val GET_ACCUMULATED_PURCHASE_HISTORY_RESULT = "getAccumulatedPurchaseHistoryResult"
        const val GET_SEARCH_INSPECTION_RESULT = "getSearchInspectionResult"
        const val CLEAR_PURCHASE_HISTORY_RESULT = "clearPurchaseHistoryResult"
        const val CLEAR_SEARCH_INSPECTION_RESULT = "clearSearchInspectionResult"
        const val DUMP_CURRENT_UI_TREE = "dumpCurrentUiTree"
        const val LAUNCH_PLATFORM_APP = "launchPlatformApp"
    }

    object Argument {
        const val CONTRACT_VERSION = "contractVersion"
        const val TASK_ID = "taskId"
        const val TASK_TYPE = "taskType"
        const val CONVERSATION_ID = "conversationId"
        const val USER_ID = "userId"
        const val TARGET_PRODUCT_NAME = "targetProductName"
        const val SEARCH_KEYWORD = "searchKeyword"
        const val OPTION_NAME = "optionName"
        const val QUANTITY = "quantity"
        const val PLATFORM = "platform"
        const val PACKAGE_NAME = "packageName"
        const val CURRENT_STEP = "currentStep"
        const val CART_ITEM_ID = "cartItemId"
        const val ORDER_ID = "orderId"
        const val PAYMENT_ID = "paymentId"
        const val METADATA = "metadata"
    }

    object TaskType {
        const val SEARCH_AND_ADD_TO_CART = "search_and_add_to_cart"
        const val PURCHASE_HISTORY = "purchase_history"
        const val PURCHASE_HISTORY_VALIDATION = "purchase_history_validation"
        const val INSPECT_SEARCH_FLOW = "inspect_search_flow"
        const val CHECKOUT_PLATFORM_CART = "checkout_platform_cart"
    }

    object Platform {
        const val UNKNOWN = "unknown"
        const val KURLY = "kurly"
        const val COUPANG = "coupang"
    }

    object PackageName {
        const val KURLY = "com.dbs.kurly.m2"
        const val COUPANG = "com.coupang.mobile"
    }

    object Step {
        const val OPEN_MY_COUPANG = "open_my_coupang"
        const val OPEN_MY_KURLY = "open_my_kurly"
        const val OPEN_ORDER_HISTORY = "open_order_history"
        const val DUMP_PURCHASE_HISTORY = "dump_purchase_history"
        const val EXTRACT_PURCHASE_HISTORY = "extract_purchase_history"
        const val SCROLL_PURCHASE_HISTORY = "scroll_purchase_history"
        const val FINISH_PURCHASE_HISTORY = "finish_purchase_history"
        const val COMPLETE_PURCHASE_HISTORY_COLLECTION = "complete_purchase_history_collection"
        const val CLICK_REORDER = "click_reorder"
        const val OPEN_SEARCH = "open_search"
        const val SEARCH_INPUT = "search_input"
        const val SEARCH_SUBMIT = "search_submit"
        const val SELECT_PRODUCT = "select_product"
        const val WAIT_PRODUCT_DETAIL = "wait_product_detail"
        const val CLICK_DETAIL_ADD_TO_CART = "click_detail_add_to_cart"
        const val WAIT_OPTION_OR_CART_RESULT = "wait_option_or_cart_result"
        const val CONFIRM_OPTION_ADD_TO_CART = "confirm_option_add_to_cart"
        const val WAIT_OPTION_SELECTED = "wait_option_selected"
        const val VERIFY_CART_ADDED = "verify_cart_added"
        const val DUMP_SEARCH_ENTRY = "dump_search_entry"
        const val DUMP_SEARCH_INPUT = "dump_search_input"
        const val DUMP_SEARCH_RESULTS = "dump_search_results"
        const val SCROLL_SEARCH_RESULTS = "scroll_search_results"
        const val FINISH_SEARCH_RESULTS = "finish_search_results"
        const val ADD_TO_CART = "add_to_cart"
        const val SELECT_OPTION = "select_option"
        const val COMPLETED = "completed"
        const val TASK_COMPLETED_REASON = "task_completed"
    }

    fun defaultPackageNameForPlatform(platform: String): String? {
        return when (platform.lowercase()) {
            Platform.KURLY -> PackageName.KURLY
            Platform.COUPANG -> PackageName.COUPANG
            else -> null
        }
    }

    fun defaultStartStepForTaskType(taskType: String, platform: String): String {
        return when (taskType) {
            TaskType.PURCHASE_HISTORY,
            TaskType.PURCHASE_HISTORY_VALIDATION -> when (platform.lowercase()) {
                Platform.COUPANG -> Step.OPEN_MY_COUPANG
                Platform.KURLY -> Step.OPEN_MY_KURLY
                else -> Step.OPEN_ORDER_HISTORY
            }
            TaskType.SEARCH_AND_ADD_TO_CART,
            TaskType.CHECKOUT_PLATFORM_CART,
            TaskType.INSPECT_SEARCH_FLOW -> Step.OPEN_SEARCH
            else -> Step.OPEN_SEARCH
        }
    }
}

/**
 * Agent → Backend → Flutter → Android Accessibility 로 내려오는 실행 요청 DTO.
 *
 * 이 타입은 실제 자동화 runtime의 시작 계약이다. pendingConfirmation처럼 사용자 확인을
 * 기다리는 값도 아니고, uiCommand처럼 화면 제어 힌트도 아니다. Android가 외부 앱에서
 * 수행해야 할 구체적인 작업 하나를 나타낸다.
 */
data class AutomationTask(
    val taskId: String,
    val taskType: String,
    val conversationId: Int? = null,
    val userId: Int? = null,
    val targetProductName: String = "",
    val searchKeyword: String = "",
    val optionName: String = "",
    val quantity: Int = 1,
    val platform: String = AutomationContract.Platform.UNKNOWN,
    val packageName: String? = null,
    val currentStep: String,
    val cartItemId: String? = null,
    val orderId: Int? = null,
    val paymentId: Int? = null,
    val metadata: Map<String, Any?> = emptyMap()
) {
    fun effectivePackageName(): String? {
        return packageName ?: AutomationContract.defaultPackageNameForPlatform(platform)
    }

    fun toMap(): Map<String, Any?> {
        return mapOf(
            AutomationContract.Argument.CONTRACT_VERSION to AutomationContract.CONTRACT_VERSION,
            AutomationContract.Argument.TASK_ID to taskId,
            AutomationContract.Argument.TASK_TYPE to taskType,
            AutomationContract.Argument.CONVERSATION_ID to conversationId,
            AutomationContract.Argument.USER_ID to userId,
            AutomationContract.Argument.TARGET_PRODUCT_NAME to targetProductName,
            AutomationContract.Argument.SEARCH_KEYWORD to searchKeyword,
            AutomationContract.Argument.OPTION_NAME to optionName,
            AutomationContract.Argument.QUANTITY to quantity,
            AutomationContract.Argument.PLATFORM to platform,
            AutomationContract.Argument.PACKAGE_NAME to effectivePackageName(),
            AutomationContract.Argument.CURRENT_STEP to currentStep,
            AutomationContract.Argument.CART_ITEM_ID to cartItemId,
            AutomationContract.Argument.ORDER_ID to orderId,
            AutomationContract.Argument.PAYMENT_ID to paymentId,
            AutomationContract.Argument.METADATA to metadata
        )
    }

    companion object {
        fun fromMap(arguments: Map<String, Any?>): AutomationTask {
            val platform = stringValue(arguments[AutomationContract.Argument.PLATFORM])
                ?: AutomationContract.Platform.UNKNOWN
            val taskType = stringValue(arguments[AutomationContract.Argument.TASK_TYPE])
                ?: AutomationContract.TaskType.SEARCH_AND_ADD_TO_CART
            val currentStep = stringValue(arguments[AutomationContract.Argument.CURRENT_STEP])
                ?: AutomationContract.defaultStartStepForTaskType(taskType, platform)

            return AutomationTask(
                taskId = stringValue(arguments[AutomationContract.Argument.TASK_ID])
                    ?: "automation-${System.currentTimeMillis()}",
                taskType = taskType,
                conversationId = intValue(arguments[AutomationContract.Argument.CONVERSATION_ID]),
                userId = intValue(arguments[AutomationContract.Argument.USER_ID]),
                targetProductName = stringValue(
                    arguments[AutomationContract.Argument.TARGET_PRODUCT_NAME],
                ).orEmpty(),
                searchKeyword = stringValue(arguments[AutomationContract.Argument.SEARCH_KEYWORD]).orEmpty(),
                optionName = stringValue(arguments[AutomationContract.Argument.OPTION_NAME]).orEmpty(),
                quantity = intValue(arguments[AutomationContract.Argument.QUANTITY]) ?: 1,
                platform = platform,
                packageName = stringValue(arguments[AutomationContract.Argument.PACKAGE_NAME])
                    ?: AutomationContract.defaultPackageNameForPlatform(platform),
                currentStep = currentStep,
                cartItemId = stringValue(arguments[AutomationContract.Argument.CART_ITEM_ID]),
                orderId = intValue(arguments[AutomationContract.Argument.ORDER_ID]),
                paymentId = intValue(arguments[AutomationContract.Argument.PAYMENT_ID]),
                metadata = mapValue(arguments[AutomationContract.Argument.METADATA])
            )
        }

        private fun stringValue(value: Any?): String? {
            return value?.toString()?.trim()?.takeIf { it.isNotEmpty() }
        }

        private fun intValue(value: Any?): Int? {
            return when (value) {
                is Int -> value
                is Long -> value.toInt()
                is Number -> value.toInt()
                is String -> value.toIntOrNull()
                else -> null
            }
        }

        private fun mapValue(value: Any?): Map<String, Any?> {
            return when (value) {
                is Map<*, *> -> value.entries.associate { (key, entryValue) ->
                    key.toString() to entryValue
                }
                else -> emptyMap()
            }
        }
    }
}

data class AutomationRuntimeStatus(
    val serviceConnected: Boolean = false,
    val lastPackageName: String? = null,
    val lastStep: String? = null,
    val lastScreenType: String? = null,
    val lastTrigger: String? = null,
    val currentRetryCount: Int = 0,
    val currentRecoveryCount: Int = 0,
    val rawNodeCount: Int = 0,
    val filteredNodeCount: Int = 0,
    val lastActionType: String? = null,
    val lastReasonCode: String? = null,
    val lastTargetNodeId: Int? = null,
    val lastSelectedNodeText: String? = null,
    val lastActionSuccess: Boolean? = null,
    val lastActionMethod: String? = null,
    val lastErrorCode: String? = null,
    val lastMessage: String? = null,
    val aiFallbackSuggested: Boolean = false,
    val fallbackType: String? = null,
    val fallbackReasonCode: String? = null,
    val failedAction: String? = null,
    val expectedState: String? = null,
    val observedState: String? = null
)
