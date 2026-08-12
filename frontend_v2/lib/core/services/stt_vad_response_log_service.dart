import 'dart:convert';
import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:path_provider/path_provider.dart';

class SttVadResponseLogService {
  SttVadResponseLogService._();

  static final SttVadResponseLogService instance = SttVadResponseLogService._();

  IOSink? _sink;
  String? _currentLogPath;
  bool _initialized = false;

  String? get currentLogPath => _currentLogPath;

  Future<void> init() async {
    if (_initialized) {
      return;
    }
    _initialized = true;

    try {
      final directory = await getApplicationDocumentsDirectory();
      final logsDir = Directory('${directory.path}/logs/stt_vad_response');
      await logsDir.create(recursive: true);

      final timestamp = _buildFileTimestamp(DateTime.now());
      final file = File('${logsDir.path}/session_$timestamp.log');
      _sink = file.openWrite(mode: FileMode.writeOnlyAppend);
      _currentLogPath = file.path;

      debugPrint('📝 [STT/VAD Log] session started: $_currentLogPath');
    } catch (error, stackTrace) {
      debugPrint('⚠️ [STT/VAD Log] init failed: $error\n$stackTrace');
    }
  }

  Future<void> logEvent(
    String event, {
    required Map<String, dynamic> payload,
  }) async {
    if (!_initialized) {
      await init();
    }
    final sink = _sink;
    if (sink == null) {
      return;
    }

    final record = <String, dynamic>{
      'timestamp': DateTime.now().toIso8601String(),
      'event': event,
      ...payload,
    };
    sink.writeln(jsonEncode(record));
    await sink.flush();
  }

  String _buildFileTimestamp(DateTime dateTime) {
    final year = dateTime.year.toString().padLeft(4, '0');
    final month = dateTime.month.toString().padLeft(2, '0');
    final day = dateTime.day.toString().padLeft(2, '0');
    final hour = dateTime.hour.toString().padLeft(2, '0');
    final minute = dateTime.minute.toString().padLeft(2, '0');
    final second = dateTime.second.toString().padLeft(2, '0');
    return '$year$month$day-$hour$minute$second';
  }
}
