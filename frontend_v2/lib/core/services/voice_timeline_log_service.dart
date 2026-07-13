import 'dart:async';
import 'dart:convert';

import 'package:flutter/foundation.dart';

import '../utils/latency_log_writer.dart';

class VoiceTimelineLogService {
  VoiceTimelineLogService._();

  static final VoiceTimelineLogService instance = VoiceTimelineLogService._();
  static const JsonEncoder _encoder = JsonEncoder.withIndent('  ');
  static const String _fileName = 'frontend_voice_timeline.jsonl';

  void logBestEffort(String event, {required Map<String, dynamic> payload}) {
    unawaited(logEvent(event, payload: payload));
  }

  Future<void> logEvent(
    String event, {
    required Map<String, dynamic> payload,
  }) async {
    final record = <String, dynamic>{
      'loggedAt': DateTime.now().toUtc().toIso8601String(),
      'event': event,
      ...payload,
    };

    try {
      final encoded = jsonEncode(record);
      debugPrint('[VOICE_TIMELINE]\n${_encoder.convert(record)}');
      await appendLatencyJsonLine(_fileName, encoded);
    } catch (error, stackTrace) {
      debugPrint(
        '⚠️ [VOICE_TIMELINE] failed event=$event error=$error\n$stackTrace',
      );
    }
  }
}
