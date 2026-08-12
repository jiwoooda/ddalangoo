import 'dart:convert';

import 'package:ddalangoo/core/services/accessibility_automation_service.dart';
import 'package:ddalangoo/data/models/accessibility_purchase_history_model.dart';
import 'package:flutter/material.dart';

class AccessibilityDebugPanel extends StatefulWidget {
  const AccessibilityDebugPanel({super.key});

  @override
  State<AccessibilityDebugPanel> createState() =>
      _AccessibilityDebugPanelState();
}

class _AccessibilityDebugPanelState extends State<AccessibilityDebugPanel> {
  static const List<String> _statusFields = [
    'serviceConnected',
    'lastPackageName',
    'lastStep',
    'taskCompleted',
    'purchaseHistoryFinishHandled',
    'searchKeyword',
    'targetProductName',
    'optionName',
    'lastScreenType',
    'lastTrigger',
    'currentRetryCount',
    'currentRecoveryCount',
    'rawNodeCount',
    'filteredNodeCount',
    'lastActionType',
    'lastReasonCode',
    'lastTargetNodeId',
    'lastSelectedNodeText',
    'lastActionSuccess',
    'lastActionMethod',
    'lastErrorCode',
    'lastMessage',
    'latestPurchaseHistoryCount',
    'accumulatedPurchaseHistoryCount',
    'searchEntryCandidateCount',
    'searchInputCandidateCount',
    'rawProductNodeCandidateCount',
    'productCandidateCount',
    'accumulatedProductCandidateCount',
    'searchResultDumpCount',
    'searchInspectionPreview',
    'aiFallbackSuggested',
    'fallbackType',
    'fallbackReasonCode',
  ];

  final AccessibilityAutomationService _automationService =
      AccessibilityAutomationService.instance;

  Map<String, dynamic>? _status;
  String _purchaseHistoryJson = '';
  String _purchaseHistoryImportResult = '';
  String _searchInspectionJson = '';
  List<AccessibilityPurchaseHistoryItem> _purchaseHistoryItems = const [];
  String? _errorMessage;
  bool _isBusy = false;

  Future<void> _runChannelAction(Future<void> Function() action) async {
    if (_isBusy) return;
    setState(() {
      _isBusy = true;
      _errorMessage = null;
    });
    try {
      await action();
    } catch (error) {
      debugPrint('[A11y Debug Panel] $error');
      if (!mounted) return;
      setState(() => _errorMessage = error.toString());
    } finally {
      if (mounted) {
        setState(() => _isBusy = false);
      }
    }
  }

  Future<void> _setKurlyPurchaseHistoryTask() {
    return _runChannelAction(() async {
      await _automationService.startKurlyPurchaseHistoryExtraction();
      await _readStatus();
    });
  }

  Future<void> _setKurlySearchEntryInspectionTask() {
    return _runChannelAction(() async {
      await _automationService.startKurlySearchEntryInspection();
      await _readStatus();
    });
  }

  Future<void> _setKurlySearchInputInspectionTask() {
    return _runChannelAction(() async {
      await _automationService.startKurlySearchInputInspection();
      await _readStatus();
    });
  }

  Future<void> _setKurlySearchResultsInspectionTask() {
    return _runChannelAction(() async {
      await _automationService.startKurlySearchResultsInspection();
      await _readStatus();
    });
  }

  Future<void> _setKurlySearchResultCollectionTask() {
    return _runChannelAction(() async {
      await _automationService.startKurlySearchResultCollection();
      await _readStatus();
    });
  }

  Future<void> _setKurlyMangoTargetSearchTask() {
    return _runChannelAction(() async {
      await _automationService.startKurlyMangoTargetSearchTest();
      await _readStatus();
    });
  }

  Future<void> _setKurlyEtudeOptionAddToCartTask() {
    return _runChannelAction(() async {
      await _automationService.startKurlyEtudeOptionAddToCartTest();
      await _readStatus();
    });
  }

  Future<void> _clearTask() {
    return _runChannelAction(() async {
      await _automationService.clearAutomationTask();
      await _readStatus();
    });
  }

  Future<void> _refreshStatus() {
    return _runChannelAction(_readStatus);
  }

  Future<void> _readStatus() async {
    final result = await _automationService.getAutomationStatus();
    if (!mounted) return;
    setState(() => _status = result);
  }

  Future<void> _loadPurchaseHistoryResult() {
    return _runChannelAction(() async {
      final result = await _automationService
          .getAccumulatedPurchaseHistoryResult();
      final items = AccessibilityPurchaseHistoryItem.expandedListFromJsonString(
        result,
      );
      if (!mounted) return;
      setState(() {
        _purchaseHistoryJson = _prettyJson(result);
        _purchaseHistoryItems = items;
      });
    });
  }

  Future<void> _loadSearchInspectionResult() {
    return _runChannelAction(() async {
      final result = await _automationService.getSearchInspectionResult();
      if (!mounted) return;
      setState(() {
        _searchInspectionJson = _prettyJson(result);
      });
    });
  }

  Future<void> _importPurchaseHistoryResult() {
    return _runChannelAction(() async {
      final result = await _automationService.importAccumulatedPurchaseHistory();
      if (!mounted) return;
      setState(() {
        _purchaseHistoryImportResult =
            const JsonEncoder.withIndent('  ').convert(result);
      });
      await _readStatus();
    });
  }

  Future<void> _clearPurchaseHistoryResult() {
    return _runChannelAction(() async {
      await _automationService.clearPurchaseHistoryResult();
      if (!mounted) return;
      setState(() {
        _purchaseHistoryJson = '';
        _purchaseHistoryImportResult = '';
        _purchaseHistoryItems = const [];
      });
      await _readStatus();
    });
  }

  Future<void> _clearSearchInspectionResult() {
    return _runChannelAction(() async {
      await _automationService.clearSearchInspectionResult();
      if (!mounted) return;
      setState(() => _searchInspectionJson = '');
      await _readStatus();
    });
  }

  String _prettyJson(String rawJson) {
    try {
      const encoder = JsonEncoder.withIndent('  ');
      return encoder.convert(jsonDecode(rawJson));
    } catch (_) {
      return rawJson;
    }
  }

  String _statusText() {
    final status = _status;
    if (status == null) {
      return '아직 조회된 status가 없습니다.';
    }
    return _statusFields
        .map((field) => '$field: ${status[field] ?? 'null'}')
        .join('\n');
  }

  String _purchaseHistoryItemsText() {
    if (_purchaseHistoryItems.isEmpty) {
      return '변환된 item이 없습니다.';
    }

    final buffer = StringBuffer(
      'itemCount: ${_purchaseHistoryItems.length} '
      '(주문 단위 raw JSON을 상품 단위 DTO로 펼친 결과)',
    );
    for (var index = 0; index < _purchaseHistoryItems.length; index += 1) {
      final item = _purchaseHistoryItems[index];
      buffer
        ..writeln()
        ..writeln()
        ..writeln('#${index + 1}')
        ..writeln('platform: ${item.platform}')
        ..writeln('orderNumber: ${item.orderNumber ?? 'null'}')
        ..writeln('deliveryStatus: ${item.deliveryStatus ?? 'null'}')
        ..writeln('deliveryType: ${item.deliveryType ?? 'null'}')
        ..writeln('price: ${item.price ?? 'null'}')
        ..writeln('purchaseDate: ${item.purchaseDate ?? 'null'}')
        ..writeln('productName: ${item.productName}');
    }
    return buffer.toString();
  }

  @override
  Widget build(BuildContext context) {
    final buttonStyle = OutlinedButton.styleFrom(
      minimumSize: const Size.fromHeight(42),
      alignment: Alignment.centerLeft,
    );

    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: Colors.white.withValues(alpha: 0.78),
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: const Color(0xFFEAD6DE)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            children: [
              const Icon(Icons.accessibility_new, size: 20),
              const SizedBox(width: 8),
              const Expanded(
                child: Text(
                  'Accessibility Debug',
                  style: TextStyle(fontWeight: FontWeight.w800),
                ),
              ),
              if (_isBusy)
                const SizedBox(
                  width: 16,
                  height: 16,
                  child: CircularProgressIndicator(strokeWidth: 2),
                ),
            ],
          ),
          const SizedBox(height: 10),
          OutlinedButton.icon(
            style: buttonStyle,
            onPressed: _isBusy ? null : _setKurlyPurchaseHistoryTask,
            icon: const Icon(Icons.history, size: 20),
            label: const Text('마켓컬리 구매이력 추출 task 시작'),
          ),
          const SizedBox(height: 8),
          OutlinedButton.icon(
            style: buttonStyle,
            onPressed: _isBusy ? null : _setKurlySearchEntryInspectionTask,
            icon: const Icon(Icons.search, size: 20),
            label: const Text('마켓컬리 검색 진입 node dump'),
          ),
          const SizedBox(height: 8),
          OutlinedButton.icon(
            style: buttonStyle,
            onPressed: _isBusy ? null : _setKurlySearchInputInspectionTask,
            icon: const Icon(Icons.edit, size: 20),
            label: const Text('마켓컬리 검색 입력 화면 dump'),
          ),
          const SizedBox(height: 8),
          OutlinedButton.icon(
            style: buttonStyle,
            onPressed: _isBusy ? null : _setKurlySearchResultsInspectionTask,
            icon: const Icon(Icons.inventory_2_outlined, size: 20),
            label: const Text('마켓컬리 검색 결과 node dump'),
          ),
          const SizedBox(height: 8),
          OutlinedButton.icon(
            style: buttonStyle,
            onPressed: _isBusy ? null : _setKurlySearchResultCollectionTask,
            icon: const Icon(Icons.manage_search, size: 20),
            label: const Text('마켓컬리 검색 결과 수집 task 시작'),
          ),
          const SizedBox(height: 8),
          OutlinedButton.icon(
            style: buttonStyle,
            onPressed: _isBusy ? null : _setKurlyMangoTargetSearchTask,
            icon: const Icon(Icons.travel_explore, size: 20),
            label: const Text('망고 검색 후 목표 골드망고 찾기'),
          ),
          const SizedBox(height: 8),
          OutlinedButton.icon(
            style: buttonStyle,
            onPressed: _isBusy ? null : _setKurlyEtudeOptionAddToCartTask,
            icon: const Icon(Icons.add_shopping_cart, size: 20),
            label: const Text('에뛰드 옵션 상품 장바구니 담기'),
          ),
          const SizedBox(height: 8),
          OutlinedButton.icon(
            style: buttonStyle,
            onPressed: _isBusy ? null : _refreshStatus,
            icon: const Icon(Icons.refresh, size: 20),
            label: const Text('Automation status 조회'),
          ),
          const SizedBox(height: 8),
          OutlinedButton.icon(
            style: buttonStyle,
            onPressed: _isBusy ? null : _loadPurchaseHistoryResult,
            icon: const Icon(Icons.data_object, size: 20),
            label: const Text('누적 구매이력 JSON 조회'),
          ),
          const SizedBox(height: 8),
          OutlinedButton.icon(
            style: buttonStyle,
            onPressed: _isBusy ? null : _importPurchaseHistoryResult,
            icon: const Icon(Icons.cloud_upload_outlined, size: 20),
            label: const Text('누적 구매이력 백엔드 저장'),
          ),
          const SizedBox(height: 8),
          OutlinedButton.icon(
            style: buttonStyle,
            onPressed: _isBusy ? null : _loadSearchInspectionResult,
            icon: const Icon(Icons.account_tree_outlined, size: 20),
            label: const Text('검색 inspection JSON 조회'),
          ),
          const SizedBox(height: 8),
          TextButton.icon(
            onPressed: _isBusy ? null : _clearTask,
            icon: const Icon(Icons.clear, size: 20),
            label: const Text('Task clear'),
          ),
          TextButton.icon(
            onPressed: _isBusy ? null : _clearPurchaseHistoryResult,
            icon: const Icon(Icons.delete_sweep_outlined, size: 20),
            label: const Text('누적 구매이력 clear'),
          ),
          TextButton.icon(
            onPressed: _isBusy ? null : _clearSearchInspectionResult,
            icon: const Icon(Icons.cleaning_services_outlined, size: 20),
            label: const Text('검색 inspection clear'),
          ),
          if (_errorMessage != null) ...[
            const SizedBox(height: 8),
            Text(
              _errorMessage!,
              style: const TextStyle(color: Colors.red, fontSize: 12),
            ),
          ],
          const SizedBox(height: 10),
          _DebugTextBlock(title: 'Status', text: _statusText()),
          const SizedBox(height: 10),
          _DebugTextBlock(
            title: 'Accumulated Purchase History',
            text: _purchaseHistoryJson.isEmpty
                ? '아직 조회된 JSON이 없습니다.'
                : _purchaseHistoryJson,
          ),
          const SizedBox(height: 10),
          _DebugTextBlock(
            title: 'Search Inspection',
            text: _searchInspectionJson.isEmpty
                ? '아직 조회된 검색 inspection JSON이 없습니다.'
                : _searchInspectionJson,
          ),
          const SizedBox(height: 10),
          _DebugTextBlock(
            title: 'Purchase History Import Result',
            text: _purchaseHistoryImportResult.isEmpty
                ? '아직 저장 결과가 없습니다.'
                : _purchaseHistoryImportResult,
          ),
          const SizedBox(height: 10),
          _DebugTextBlock(
            title: 'DTO Preview',
            text: _purchaseHistoryItemsText(),
          ),
        ],
      ),
    );
  }
}

class _DebugTextBlock extends StatelessWidget {
  const _DebugTextBlock({required this.title, required this.text});

  final String title;
  final String text;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(10),
      decoration: BoxDecoration(
        color: const Color(0xFF2D2730),
        borderRadius: BorderRadius.circular(10),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            title,
            style: const TextStyle(
              color: Color(0xFFFFC2D0),
              fontWeight: FontWeight.w800,
              fontSize: 12,
            ),
          ),
          const SizedBox(height: 6),
          SelectableText(
            text,
            style: const TextStyle(
              color: Colors.white,
              fontSize: 11,
              height: 1.35,
              fontFamily: 'monospace',
            ),
          ),
        ],
      ),
    );
  }
}
