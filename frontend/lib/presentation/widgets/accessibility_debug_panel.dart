import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

class AccessibilityDebugPanel extends StatefulWidget {
  const AccessibilityDebugPanel({super.key});

  @override
  State<AccessibilityDebugPanel> createState() =>
      _AccessibilityDebugPanelState();
}

class _AccessibilityDebugPanelState extends State<AccessibilityDebugPanel> {
  static const MethodChannel _channel = MethodChannel(
    'ddalangoo/accessibility_automation',
  );

  static const List<String> _statusFields = [
    'serviceConnected',
    'lastPackageName',
    'lastStep',
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
  ];

  Map<String, dynamic>? _status;
  String _purchaseHistoryJson = '';
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
      await _channel.invokeMethod('setTestAutomationTask', {
        'taskId': 'kurly-history-dump-1',
        'taskType': 'purchase_history_validation',
        'targetProductName': '',
        'quantity': 1,
        'platform': 'kurly',
        'packageName': 'com.dbs.kurly.m2',
        'currentStep': 'extract_purchase_history',
      });
      await _readStatus();
    });
  }

  Future<void> _clearTask() {
    return _runChannelAction(() async {
      await _channel.invokeMethod('clearAutomationTask');
      await _readStatus();
    });
  }

  Future<void> _refreshStatus() {
    return _runChannelAction(_readStatus);
  }

  Future<void> _readStatus() async {
    final result = await _channel.invokeMethod<Map<dynamic, dynamic>>(
      'getAutomationStatus',
    );
    if (!mounted) return;
    setState(() {
      _status = result?.map((key, value) => MapEntry(key.toString(), value));
    });
  }

  Future<void> _loadPurchaseHistoryResult() {
    return _runChannelAction(() async {
      final result = await _channel.invokeMethod<String>(
        'getAccumulatedPurchaseHistoryResult',
      );
      if (!mounted) return;
      setState(() => _purchaseHistoryJson = _prettyJson(result ?? '[]'));
    });
  }

  Future<void> _clearPurchaseHistoryResult() {
    return _runChannelAction(() async {
      await _channel.invokeMethod('clearPurchaseHistoryResult');
      if (!mounted) return;
      setState(() => _purchaseHistoryJson = '');
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
