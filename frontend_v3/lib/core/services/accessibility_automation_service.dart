import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';

import '../../data/models/accessibility_purchase_history_model.dart';
import '../../data/models/agent_model.dart';
import '../network/api_client.dart';
import '../storage/local_storage.dart';

class InstalledShoppingPlatform {
  const InstalledShoppingPlatform({
    required this.platform,
    required this.displayName,
    required this.packageName,
    required this.isInstalled,
  });

  final String platform;
  final String displayName;
  final String packageName;
  final bool isInstalled;

  factory InstalledShoppingPlatform.fromMap(Map<String, dynamic> map) {
    return InstalledShoppingPlatform(
      platform: map['platform'] as String? ?? 'unknown',
      displayName: map['displayName'] as String? ?? '',
      packageName: map['packageName'] as String? ?? '',
      isInstalled: map['isInstalled'] == true,
    );
  }
}

abstract final class AccessibilityAutomationTaskType {
  static const searchAndAddToCart = 'search_and_add_to_cart';
  static const productSearch = 'product_search';
  static const purchaseHistory = 'purchase_history';
  static const purchaseHistoryValidation = 'purchase_history_validation';
  static const inspectSearchFlow = 'inspect_search_flow';
}

abstract final class AccessibilityAutomationPlatform {
  static const unknown = 'unknown';
  static const kurly = 'kurly';
  static const coupang = 'coupang';
}

abstract final class AccessibilityAutomationPackage {
  static const ddalangoo = 'com.ddalangoo.ddalangoo';
}

abstract final class AccessibilityAutomationStep {
  static const openMyCoupang = 'open_my_coupang';
  static const openMyKurly = 'open_my_kurly';
  static const openOrderHistory = 'open_order_history';
  static const dumpPurchaseHistory = 'dump_purchase_history';
  static const extractPurchaseHistory = 'extract_purchase_history';
  static const scrollPurchaseHistory = 'scroll_purchase_history';
  static const finishPurchaseHistory = 'finish_purchase_history';
  static const openSearch = 'open_search';
  static const searchInput = 'search_input';
  static const searchSubmit = 'search_submit';
  static const selectProduct = 'select_product';
  static const addToCart = 'add_to_cart';
  static const dumpSearchEntry = 'dump_search_entry';
  static const dumpSearchInput = 'dump_search_input';
  static const dumpSearchResults = 'dump_search_results';
}

class AccessibilityAutomationTask {
  const AccessibilityAutomationTask({
    required this.taskId,
    required this.taskType,
    required this.targetProductName,
    required this.quantity,
    required this.platform,
    required this.currentStep,
    this.conversationId,
    this.userId,
    this.searchKeyword = '',
    this.optionName = '',
    this.packageName,
    this.cartItemId,
    this.orderId,
    this.paymentId,
    this.metadata = const <String, dynamic>{},
  });

  final String taskId;
  final String taskType;
  final int? conversationId;
  final int? userId;
  final String targetProductName;
  final int quantity;
  final String platform;
  final String currentStep;
  final String searchKeyword;
  final String optionName;
  final String? packageName;
  final String? cartItemId;
  final int? orderId;
  final int? paymentId;
  final Map<String, dynamic> metadata;

  Map<String, dynamic> toChannelArguments() => <String, dynamic>{
    'contractVersion': AutomationContract.version,
    'taskId': taskId,
    'taskType': taskType,
    'conversationId': conversationId,
    'userId': userId,
    'targetProductName': targetProductName,
    'searchKeyword': searchKeyword,
    'optionName': optionName,
    'quantity': quantity,
    'platform': platform,
    'packageName': packageName,
    'currentStep': currentStep,
    'cartItemId': cartItemId,
    'orderId': orderId,
    'paymentId': paymentId,
    'metadata': metadata,
  }..removeWhere((_, value) => value == null);
}

class AccessibilityAutomationService {
  AccessibilityAutomationService._();

  static final AccessibilityAutomationService instance =
      AccessibilityAutomationService._();

  static const MethodChannel _channel = MethodChannel(
    'ddalangoo/accessibility_automation',
  );

  Future<void> setAutomationTask(AccessibilityAutomationTask task) async {
    debugPrint(
      'AutomationTask taskId=${task.taskId} MethodChannel 전송 '
      'taskType=${task.taskType} platform=${task.platform}',
    );
    await _channel.invokeMethod<void>(
      'setAutomationTask',
      _toChannelArgumentsWithRuntimeMetadata(task),
    );
  }

  Future<void> setTestAutomationTask(AccessibilityAutomationTask task) async {
    debugPrint(
      'AutomationTask taskId=${task.taskId} 테스트 MethodChannel 전송 '
      'taskType=${task.taskType} platform=${task.platform}',
    );
    await _channel.invokeMethod<void>(
      'setTestAutomationTask',
      _toChannelArgumentsWithRuntimeMetadata(task),
    );
  }

  Map<String, dynamic> _toChannelArgumentsWithRuntimeMetadata(
    AccessibilityAutomationTask task,
  ) {
    final arguments = task.toChannelArguments();
    final originalMetadata = arguments['metadata'];
    final metadata = originalMetadata is Map
        ? Map<String, dynamic>.from(originalMetadata)
        : <String, dynamic>{};

    // Android native runtime은 Dio 설정을 직접 알 수 없으므로,
    // 모든 AutomationTask가 MethodChannel을 건너기 직전에 backend 주소를 보강한다.
    metadata.putIfAbsent('backendBaseUrl', () => ApiClient.baseUrl);
    final backendBaseUrl = metadata['backendBaseUrl'];
    debugPrint(
      'AutomationTask runtime metadata '
      'taskId=${task.taskId} '
      'backendBaseUrl=$backendBaseUrl',
    );
    arguments['metadata'] = metadata;
    return arguments;
  }

  Future<bool> launchPlatformApp(String packageName) async {
    try {
      return await _channel.invokeMethod<bool>(
            'launchPlatformApp',
            <String, dynamic>{'packageName': packageName},
          ) ??
          false;
    } on MissingPluginException {
      return false;
    } on PlatformException {
      return false;
    }
  }

  Future<bool> returnToDdalangooApp() {
    return launchPlatformApp(AccessibilityAutomationPackage.ddalangoo);
  }

  /// 온보딩의 "접근성 켜기" 페이지에서 호출한다. Android 접근성 설정 목록
  /// 화면(ACTION_ACCESSIBILITY_SETTINGS)으로 즉시 이동시키고, 앱이 다시
  /// foreground로 돌아오면 [isAccessibilityServiceEnabled]로 실제로
  /// 켜졌는지 확인하면 된다.
  Future<bool> openAccessibilitySettings() async {
    try {
      return await _channel.invokeMethod<bool>('openAccessibilitySettings') ??
          false;
    } on MissingPluginException {
      return false;
    } on PlatformException {
      return false;
    }
  }

  Future<bool> isAccessibilityServiceEnabled() async {
    try {
      return await _channel.invokeMethod<bool>(
            'isAccessibilityServiceEnabled',
          ) ??
          false;
    } on MissingPluginException {
      return false;
    } on PlatformException {
      return false;
    }
  }

  Future<Map<String, dynamic>> getAutomationStatus() async {
    try {
      final result = await _channel.invokeMethod<Map<dynamic, dynamic>>(
        'getAutomationStatus',
      );
      return result?.map((key, value) => MapEntry(key.toString(), value)) ??
          <String, dynamic>{};
    } on MissingPluginException {
      return <String, dynamic>{};
    } on PlatformException {
      return <String, dynamic>{};
    }
  }

  Future<Map<String, dynamic>?> consumeAutomationResult() async {
    try {
      final result = await _channel.invokeMethod<Map<dynamic, dynamic>>(
        'consumeAutomationResult',
      );
      final mappedResult = result?.map(
        (key, value) => MapEntry(key.toString(), value),
      );
      if (mappedResult != null) {
        debugPrint(
          'AutomationResult taskId=${mappedResult['taskId']} '
          'status=${mappedResult['status']} 수신',
        );
      }
      return mappedResult;
    } on MissingPluginException {
      return null;
    } on PlatformException {
      return null;
    }
  }

  Future<List<InstalledShoppingPlatform>>
  getInstalledShoppingPlatforms() async {
    try {
      final result = await _channel.invokeListMethod<dynamic>(
        'getInstalledShoppingPlatforms',
      );
      if (result == null) {
        return const <InstalledShoppingPlatform>[];
      }

      return result
          .whereType<Map>()
          .map(
            (item) => item.map((key, value) => MapEntry(key.toString(), value)),
          )
          .map(InstalledShoppingPlatform.fromMap)
          .toList(growable: false);
    } on MissingPluginException {
      return const <InstalledShoppingPlatform>[];
    } on PlatformException {
      return const <InstalledShoppingPlatform>[];
    }
  }

  Future<void> clearAutomationTask() async {
    await _channel.invokeMethod<void>('clearAutomationTask');
  }

  Future<void> dumpCurrentUiTree() async {
    await _channel.invokeMethod<void>('dumpCurrentUiTree');
  }

  Future<String> getAccumulatedPurchaseHistoryResult() async {
    return await _channel.invokeMethod<String>(
          'getAccumulatedPurchaseHistoryResult',
        ) ??
        '[]';
  }

  Future<String> getSearchInspectionResult() async {
    return await _channel.invokeMethod<String>('getSearchInspectionResult') ??
        '[]';
  }

  Future<void> clearPurchaseHistoryResult() async {
    await _channel.invokeMethod<void>('clearPurchaseHistoryResult');
  }

  Future<void> clearSearchInspectionResult() async {
    await _channel.invokeMethod<void>('clearSearchInspectionResult');
  }

  Future<void> startKurlyPurchaseHistoryExtraction() async {
    await startPurchaseHistoryExtraction(
      platform: AccessibilityAutomationPlatform.kurly,
      displayName: '컬리',
      packageName: 'com.dbs.kurly.m2',
      startStep: AccessibilityAutomationStep.openMyKurly,
      targetHistoryCount: 30,
    );
  }

  Future<void> startPurchaseHistoryExtraction({
    required String platform,
    required String displayName,
    String? packageName,
    String? startStep,
    int targetHistoryCount = 30,
  }) async {
    final normalizedPlatform = platform.toLowerCase().trim();
    final effectivePackageName =
        packageName ?? _defaultPackageNameForPlatform(normalizedPlatform);
    final effectiveStartStep =
        startStep ?? _defaultPurchaseHistoryStartStep(normalizedPlatform);
    await setTestAutomationTask(
      AccessibilityAutomationTask(
        taskId:
            '$normalizedPlatform-history-collect-${DateTime.now().millisecondsSinceEpoch}',
        taskType: AccessibilityAutomationTaskType.purchaseHistory,
        targetProductName: '',
        quantity: 1,
        platform: normalizedPlatform,
        packageName: effectivePackageName,
        currentStep: effectiveStartStep,
        metadata: <String, dynamic>{
          'displayName': displayName,
          'source': 'purchase_history_loading_flow',
          'targetPurchaseHistoryCount': targetHistoryCount,
        },
      ),
    );
  }

  Future<void> startCoupangPurchaseHistoryDumpInspection() async {
    await clearAutomationTask();
    await clearPurchaseHistoryResult();
    await setTestAutomationTask(
      AccessibilityAutomationTask(
        taskId: 'coupang-history-dump-${DateTime.now().millisecondsSinceEpoch}',
        taskType: AccessibilityAutomationTaskType.purchaseHistoryValidation,
        targetProductName: '',
        quantity: 1,
        platform: AccessibilityAutomationPlatform.coupang,
        packageName: 'com.coupang.mobile',
        currentStep: AccessibilityAutomationStep.dumpPurchaseHistory,
        metadata: const <String, dynamic>{
          'displayName': '쿠팡',
          'source': 'coupang_purchase_history_dump_inspection',
        },
      ),
    );
    await launchPlatformApp('com.coupang.mobile');
  }

  Future<void> startCoupangPurchaseHistoryExtractionFromCurrentScreen({
    int targetHistoryCount = 30,
  }) async {
    await clearAutomationTask();
    await clearPurchaseHistoryResult();
    await setTestAutomationTask(
      AccessibilityAutomationTask(
        taskId:
            'coupang-history-debug-collect-${DateTime.now().millisecondsSinceEpoch}',
        taskType: AccessibilityAutomationTaskType.purchaseHistory,
        targetProductName: '',
        quantity: 1,
        platform: AccessibilityAutomationPlatform.coupang,
        packageName: 'com.coupang.mobile',
        currentStep: AccessibilityAutomationStep.dumpPurchaseHistory,
        metadata: <String, dynamic>{
          'displayName': '쿠팡',
          'source': 'coupang_purchase_history_debug_collection',
          'targetPurchaseHistoryCount': targetHistoryCount,
        },
      ),
    );
    await launchPlatformApp('com.coupang.mobile');
  }

  Future<void> startKurlySearchEntryInspection({String keyword = '두부'}) async {
    await _setKurlySearchInspectionTask(
      taskId: 'kurly-search-entry-inspection',
      currentStep: AccessibilityAutomationStep.dumpSearchEntry,
      keyword: keyword,
    );
  }

  Future<void> startKurlySearchInputInspection({String keyword = '두부'}) async {
    await _setKurlySearchInspectionTask(
      taskId: 'kurly-search-input-inspection',
      currentStep: AccessibilityAutomationStep.dumpSearchInput,
      keyword: keyword,
    );
  }

  Future<void> startKurlySearchResultsInspection({
    String keyword = '두부',
  }) async {
    await _setKurlySearchInspectionTask(
      taskId: 'kurly-search-results-inspection',
      currentStep: AccessibilityAutomationStep.dumpSearchResults,
      keyword: keyword,
    );
  }

  Future<void> startKurlySearchResultCollection({
    String keyword = '초복',
    String? targetProductName,
    String? optionName,
  }) async {
    final effectiveTargetProductName = targetProductName ?? keyword;
    await setTestAutomationTask(
      AccessibilityAutomationTask(
        taskId: 'kurly-search-result-collection',
        taskType: AccessibilityAutomationTaskType.searchAndAddToCart,
        targetProductName: effectiveTargetProductName,
        searchKeyword: keyword,
        optionName: optionName ?? '',
        quantity: 1,
        platform: AccessibilityAutomationPlatform.kurly,
        packageName: 'com.dbs.kurly.m2',
        currentStep: AccessibilityAutomationStep.openSearch,
      ),
    );
  }

  Future<Map<String, dynamic>> importAccumulatedPurchaseHistory() async {
    final userId = await LocalStorage.getUserId();
    if (userId == null) {
      throw StateError('A logged-in userId is required to import history.');
    }

    final rawJson = await getAccumulatedPurchaseHistoryResult();
    final items = AccessibilityPurchaseHistoryItem.expandedListFromJsonString(
      rawJson,
    );
    final response = await ApiClient.dio.post<Map<String, dynamic>>(
      '/api/users/$userId/purchase-histories/accessibility-import',
      data: <String, dynamic>{
        'items': items.map((item) => item.toBackendJson()).toList(),
      },
    );
    return response.data ?? <String, dynamic>{};
  }

  Future<void> _setKurlySearchInspectionTask({
    required String taskId,
    required String currentStep,
    required String keyword,
  }) async {
    await setTestAutomationTask(
      AccessibilityAutomationTask(
        taskId: taskId,
        taskType: AccessibilityAutomationTaskType.inspectSearchFlow,
        targetProductName: keyword,
        searchKeyword: keyword,
        quantity: 1,
        platform: AccessibilityAutomationPlatform.kurly,
        packageName: 'com.dbs.kurly.m2',
        currentStep: currentStep,
      ),
    );
  }

  String? _defaultPackageNameForPlatform(String platform) {
    return switch (platform) {
      AccessibilityAutomationPlatform.kurly => 'com.dbs.kurly.m2',
      AccessibilityAutomationPlatform.coupang => 'com.coupang.mobile',
      _ => null,
    };
  }

  String _defaultPurchaseHistoryStartStep(String platform) {
    return switch (platform) {
      AccessibilityAutomationPlatform.coupang =>
        AccessibilityAutomationStep.openMyCoupang,
      AccessibilityAutomationPlatform.kurly =>
        AccessibilityAutomationStep.openMyKurly,
      _ => AccessibilityAutomationStep.openOrderHistory,
    };
  }
}
