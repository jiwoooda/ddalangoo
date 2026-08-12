import 'dart:async';
import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:path_provider/path_provider.dart';

class AppLogService {
  AppLogService._();

  static final AppLogService instance = AppLogService._();

  late final DebugPrintCallback _defaultDebugPrint;
  IOSink? _sink;
  String? _currentLogPath;
  bool _initialized = false;

  String? get currentLogPath => _currentLogPath;

  Future<void> init() async {
    if (_initialized) return;
    _initialized = true;
    _defaultDebugPrint = debugPrint;

    try {
      final directory = await getApplicationDocumentsDirectory();
      final logsDir = Directory('${directory.path}/logs');
      await logsDir.create(recursive: true);

      final timestamp = _buildFileTimestamp(DateTime.now());
      final file = File('${logsDir.path}/app_run_$timestamp.log');
      _sink = file.openWrite(mode: FileMode.writeOnlyAppend);
      _currentLogPath = file.path;

      debugPrint = _handleDebugPrint;
      FlutterError.onError = (details) {
        _handleDebugPrint(
          '❌ [Flutter Error] ${details.exceptionAsString()}'
          '\n${details.stack ?? ''}',
        );
        FlutterError.presentError(details);
      };
      PlatformDispatcher.instance.onError = (error, stack) {
        _handleDebugPrint('❌ [Platform Error] $error\n$stack');
        return false;
      };

      _handleDebugPrint('📝 [App Log] session started: $_currentLogPath');
    } catch (error, stackTrace) {
      _defaultDebugPrint('⚠️ [App Log Init Error] $error');
      _defaultDebugPrint('$stackTrace');
    }
  }

  void _handleDebugPrint(String? message, {int? wrapWidth}) {
    if (message == null || message.isEmpty) {
      _defaultDebugPrint(message, wrapWidth: wrapWidth);
      return;
    }

    _defaultDebugPrint(message, wrapWidth: wrapWidth);

    final sink = _sink;
    if (sink == null) return;

    final lines = message.split('\n');
    final now = DateTime.now().toIso8601String();
    for (final line in lines) {
      sink.writeln('[$now] $line');
    }
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
