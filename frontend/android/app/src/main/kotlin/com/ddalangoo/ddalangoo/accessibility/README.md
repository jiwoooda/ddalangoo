# Ddalangoo Accessibility Automation Module

이 폴더는 Android AccessibilityService 기반 자동화 모듈이다. Flutter 화면이나 Agent API에 직접 의존하지 않고, `MethodChannel`로 받은 task를 실행하는 독립 모듈로 유지한다.

## 통합할 때 필요한 파일

- `frontend/android/app/src/main/kotlin/com/ddalangoo/ddalangoo/accessibility/` 전체
- `frontend/android/app/src/main/res/xml/accessibility_service_config.xml`
- `AndroidManifest.xml`의 `DdalangooAccessibilityService` 등록
- `MainActivity.kt`의 `MethodChannel(AutomationContract.CHANNEL_NAME, ...)` 연결

## Flutter와 Android 사이 계약

공개 계약은 `AutomationContract.kt`에 모아둔다. 다른 브랜치에 통합할 때는 문자열을 새로 만들지 말고 이 값을 기준으로 맞춘다.

채널:

```text
ddalangoo/accessibility_automation
```

주요 메서드:

```text
setAutomationTask
setTestAutomationTask
clearAutomationTask
getAutomationStatus
dumpCurrentUiTree
```

`setAutomationTask` 입력 예시:

```json
{
  "taskId": "cart-001",
  "taskType": "search_and_add_to_cart",
  "targetProductName": "못생겨도 맛있는 사과",
  "quantity": 1,
  "platform": "kurly",
  "packageName": "com.kurly.mobile",
  "currentStep": "search_input"
}
```

`getAutomationStatus` 응답 예시:

```json
{
  "hasTask": true,
  "taskId": "cart-001",
  "taskType": "search_and_add_to_cart",
  "platform": "kurly",
  "packageName": "com.kurly.mobile",
  "currentStep": "select_product",
  "serviceConnected": true,
  "lastPackageName": "com.kurly.mobile",
  "lastStep": "select_product",
  "rawNodeCount": 142,
  "filteredNodeCount": 31,
  "lastActionType": "click",
  "lastReasonCode": "product_card",
  "lastTargetNodeId": 18,
  "lastSelectedNodeText": "못생겨도 맛있는 사과 1.3kg",
  "lastActionSuccess": true,
  "lastActionMethod": "target_action",
  "lastErrorCode": null,
  "lastMessage": "Clicked target node id=18",
  "latestPurchaseHistoryCount": 0,
  "accumulatedPurchaseHistoryCount": 0
}
```

## 현재 지원 흐름

상품 검색 후 장바구니 담기:

```text
search_input
→ search_submit
→ select_product
→ add_to_cart
→ completed
```

구매내역 수집:

```text
open_my_coupang 또는 open_my_kurly
→ open_order_history
→ dump_purchase_history / extract_purchase_history
→ scroll_purchase_history
→ finish_purchase_history
```

## 모듈 경계

이 모듈이 직접 하면 안 되는 일:

- Flutter controller 직접 호출
- Agent API 직접 호출
- 결제 비밀번호/본인인증 화면 자동 입력
- 특정 브랜치의 UI 상태에 의존

이 모듈이 담당하는 일:

- 현재 화면의 Accessibility node tree 수집
- rule 기반 다음 action 결정
- click/input/scroll 실행
- 민감 화면 감지 시 자동화 중단
- 구매내역 후보 추출 및 로그 출력

## 테스트 로그 확인

```bash
adb logcat -s DdalangooA11y
```

`dumpCurrentUiTree`는 즉시 tree를 반환하지 않고, 다음 accessibility event가 들어올 때 현재 화면 tree를 로그로 남긴다.
