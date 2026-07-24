import 'package:flutter/services.dart';

class AccessibilityAutomationService {
  AccessibilityAutomationService._();

  static final AccessibilityAutomationService instance =
      AccessibilityAutomationService._();

  static const MethodChannel _channel = MethodChannel(
    'ddalangoo/accessibility_automation',
  );

  Future<void> startKurlyPurchaseHistoryExtraction() async {
    await _channel.invokeMethod('setTestAutomationTask', {
      'taskId': 'kurly-history-dump-1',
      'taskType': 'purchase_history_validation',
      'targetProductName': '',
      'quantity': 1,
      'platform': 'kurly',
      'packageName': 'com.dbs.kurly.m2',
      'currentStep': 'open_my_kurly',
    });
  }

  Future<void> startKurlySearchEntryInspection({
    String keyword = '두부',
  }) async {
    await _setKurlySearchInspectionTask(
      taskId: 'kurly-search-entry-inspection',
      currentStep: 'dump_search_entry',
      keyword: keyword,
    );
  }

  Future<void> startKurlySearchInputInspection({
    String keyword = '두부',
  }) async {
    await _setKurlySearchInspectionTask(
      taskId: 'kurly-search-input-inspection',
      currentStep: 'dump_search_input',
      keyword: keyword,
    );
  }

  Future<void> startKurlySearchResultsInspection({
    String keyword = '두부',
  }) async {
    await _setKurlySearchInspectionTask(
      taskId: 'kurly-search-results-inspection',
      currentStep: 'dump_search_results',
      keyword: keyword,
    );
  }

  Future<void> startKurlySearchResultCollection({
    String keyword = '초복',
    String? targetProductName,
    String? optionName,
  }) async {
    final effectiveTargetProductName = targetProductName ?? keyword;
    await _channel.invokeMethod('setTestAutomationTask', {
      'taskId': 'kurly-search-result-collection',
      'taskType': 'search_and_add_to_cart',
      'targetProductName': effectiveTargetProductName,
      'searchKeyword': keyword,
      'optionName': optionName ?? '',
      'quantity': 1,
      'platform': 'kurly',
      'packageName': 'com.dbs.kurly.m2',
      'currentStep': 'open_search',
    });
  }

  Future<void> startKurlyMangoTargetSearchTest() async {
    await startKurlySearchResultCollection(
      keyword: '망고',
      targetProductName: '태국 남독마이 골드망고 7~8입 2.3kg',
    );
  }

  Future<void> startKurlyEtudeOptionAddToCartTest() async {
    await startKurlySearchResultCollection(
      keyword: '메이크업',
      targetProductName: '[에뛰드] 왓츠인마이아이즈 33종 2g (택1)',
      optionName: '퐁당퐁당러브',
    );
  }

  Future<void> _setKurlySearchInspectionTask({
    required String taskId,
    required String currentStep,
    required String keyword,
  }) async {
    await _channel.invokeMethod('setTestAutomationTask', {
      'taskId': taskId,
      'taskType': 'inspect_search_flow',
      'targetProductName': keyword,
      'searchKeyword': keyword,
      'optionName': '',
      'quantity': 1,
      'platform': 'kurly',
      'packageName': 'com.dbs.kurly.m2',
      'currentStep': currentStep,
    });
  }

  Future<Map<String, dynamic>> getAutomationStatus() async {
    final result = await _channel.invokeMethod<Map<dynamic, dynamic>>(
      'getAutomationStatus',
    );
    return result?.map((key, value) => MapEntry(key.toString(), value)) ??
        <String, dynamic>{};
  }

  Future<void> clearAutomationTask() async {
    await _channel.invokeMethod('clearAutomationTask');
  }

  Future<String> getAccumulatedPurchaseHistoryResult() async {
    return await _channel.invokeMethod<String>(
          'getAccumulatedPurchaseHistoryResult',
        ) ??
        '[]';
  }

  Future<String> getSearchInspectionResult() async {
    return await _channel.invokeMethod<String>(
          'getSearchInspectionResult',
        ) ??
        '[]';
  }

  Future<void> clearPurchaseHistoryResult() async {
    await _channel.invokeMethod('clearPurchaseHistoryResult');
  }

  Future<void> clearSearchInspectionResult() async {
    await _channel.invokeMethod('clearSearchInspectionResult');
  }
}
