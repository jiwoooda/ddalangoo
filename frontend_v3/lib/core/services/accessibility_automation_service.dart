import 'package:flutter/services.dart';

import '../../data/models/accessibility_purchase_history_model.dart';
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
  static const purchaseHistory = 'purchase_history';
  static const inspectSearchFlow = 'inspect_search_flow';
}

abstract final class AccessibilityAutomationPlatform {
  static const unknown = 'unknown';
  static const kurly = 'kurly';
  static const coupang = 'coupang';
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
    this.searchKeyword = '',
    this.optionName = '',
    this.packageName,
  });

  final String taskId;
  final String taskType;
  final String targetProductName;
  final int quantity;
  final String platform;
  final String currentStep;
  final String searchKeyword;
  final String optionName;
  final String? packageName;

  Map<String, dynamic> toChannelArguments() => <String, dynamic>{
    'taskId': taskId,
    'taskType': taskType,
    'targetProductName': targetProductName,
    'searchKeyword': searchKeyword,
    'optionName': optionName,
    'quantity': quantity,
    'platform': platform,
    'packageName': packageName,
    'currentStep': currentStep,
  };
}

class AccessibilityAutomationService {
  AccessibilityAutomationService._();

  static final AccessibilityAutomationService instance =
      AccessibilityAutomationService._();

  static const MethodChannel _channel = MethodChannel(
    'ddalangoo/accessibility_automation',
  );

  Future<void> setAutomationTask(AccessibilityAutomationTask task) async {
    await _channel.invokeMethod<void>(
      'setAutomationTask',
      task.toChannelArguments(),
    );
  }

  Future<void> setTestAutomationTask(AccessibilityAutomationTask task) async {
    await _channel.invokeMethod<void>(
      'setTestAutomationTask',
      task.toChannelArguments(),
    );
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
    await setTestAutomationTask(
      const AccessibilityAutomationTask(
        taskId: 'kurly-history-dump-1',
        taskType: AccessibilityAutomationTaskType.purchaseHistory,
        targetProductName: '',
        quantity: 1,
        platform: AccessibilityAutomationPlatform.kurly,
        packageName: 'com.dbs.kurly.m2',
        currentStep: AccessibilityAutomationStep.openMyKurly,
      ),
    );
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
}
