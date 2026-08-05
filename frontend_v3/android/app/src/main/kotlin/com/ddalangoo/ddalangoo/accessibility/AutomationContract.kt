package com.ddalangoo.ddalangoo.accessibility

/**
 * Flutter와 Android Accessibility 모듈 사이의 공개 계약을 한 곳에 모은다.
 *
 * 나중에 다른 프론트 브랜치로 옮길 때는 이 파일의 channel/method/task/step 값만
 * 맞추면 나머지 rule engine은 독립적으로 가져갈 수 있다.
 */
object AutomationContract {
    const val CHANNEL_NAME = "ddalangoo/accessibility_automation"

    object Method {
        const val SET_TASK = "setAutomationTask"
        const val SET_TEST_TASK = "setTestAutomationTask"
        const val CLEAR_TASK = "clearAutomationTask"
        const val GET_STATUS = "getAutomationStatus"
        const val GET_INSTALLED_SHOPPING_PLATFORMS = "getInstalledShoppingPlatforms"
        const val GET_ACCUMULATED_PURCHASE_HISTORY_RESULT = "getAccumulatedPurchaseHistoryResult"
        const val GET_SEARCH_INSPECTION_RESULT = "getSearchInspectionResult"
        const val CLEAR_PURCHASE_HISTORY_RESULT = "clearPurchaseHistoryResult"
        const val CLEAR_SEARCH_INSPECTION_RESULT = "clearSearchInspectionResult"
        const val DUMP_CURRENT_UI_TREE = "dumpCurrentUiTree"
        const val LAUNCH_PLATFORM_APP = "launchPlatformApp"
    }

    object Argument {
        const val TASK_ID = "taskId"
        const val TASK_TYPE = "taskType"
        const val TARGET_PRODUCT_NAME = "targetProductName"
        const val SEARCH_KEYWORD = "searchKeyword"
        const val OPTION_NAME = "optionName"
        const val QUANTITY = "quantity"
        const val PLATFORM = "platform"
        const val PACKAGE_NAME = "packageName"
        const val CURRENT_STEP = "currentStep"
    }

    object TaskType {
        const val SEARCH_AND_ADD_TO_CART = "search_and_add_to_cart"
        const val PURCHASE_HISTORY = "purchase_history"
        const val INSPECT_SEARCH_FLOW = "inspect_search_flow"
    }

    object Platform {
        const val UNKNOWN = "unknown"
        const val KURLY = "kurly"
        const val COUPANG = "coupang"
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
}
