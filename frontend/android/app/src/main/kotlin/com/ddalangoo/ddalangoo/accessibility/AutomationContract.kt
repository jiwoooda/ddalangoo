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
        const val DUMP_CURRENT_UI_TREE = "dumpCurrentUiTree"
    }

    object Argument {
        const val TASK_ID = "taskId"
        const val TASK_TYPE = "taskType"
        const val TARGET_PRODUCT_NAME = "targetProductName"
        const val QUANTITY = "quantity"
        const val PLATFORM = "platform"
        const val PACKAGE_NAME = "packageName"
        const val CURRENT_STEP = "currentStep"
    }

    object TaskType {
        const val SEARCH_AND_ADD_TO_CART = "search_and_add_to_cart"
        const val PURCHASE_HISTORY = "purchase_history"
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
        const val SEARCH_INPUT = "search_input"
        const val SEARCH_SUBMIT = "search_submit"
        const val SELECT_PRODUCT = "select_product"
        const val ADD_TO_CART = "add_to_cart"
        const val COMPLETED = "completed"
        const val TASK_COMPLETED_REASON = "task_completed"
    }
}
