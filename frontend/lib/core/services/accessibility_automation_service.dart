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

  Future<void> clearPurchaseHistoryResult() async {
    await _channel.invokeMethod('clearPurchaseHistoryResult');
  }
}
