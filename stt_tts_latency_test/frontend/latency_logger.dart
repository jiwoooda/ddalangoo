import 'dart:convert';
import 'dart:math';

import 'package:flutter/foundation.dart';

class LatencyRequestContext {
  const LatencyRequestContext({
    required this.sessionId,
    required this.requestId,
    required this.turnIndex,
  });

  final String sessionId;
  final String requestId;
  final int turnIndex;

  Map<String, String> toHeaders() => {
    'X-Latency-Session-Id': sessionId,
    'X-Latency-Request-Id': requestId,
    'X-Latency-Turn-Index': '$turnIndex',
  };
}

class FrontendLatencyLogger {
  FrontendLatencyLogger._();

  static final FrontendLatencyLogger instance = FrontendLatencyLogger._();
  static const JsonEncoder _encoder = JsonEncoder.withIndent('  ');
  static const String _mode = 'FRONTEND_STT_TTS';

  final Map<String, _FrontendLatencyTurn> _turns = {};
  final List<Map<String, dynamic>> _completedLogs = [];
  final Random _random = Random();

  String? _sessionId;
  int _turnCounter = 0;

  String get sessionId => _sessionId ??= _newId(prefix: 'session');

  void startSession({String? sessionId}) {
    _sessionId = sessionId ?? _newId(prefix: 'session');
    _turnCounter = 0;
    _turns.clear();
    _completedLogs.clear();
    _log({
      'event': 'latency_session_started',
      'session_id': _sessionId,
      'mode': _mode,
      'started_at': _isoNow(),
    });
  }

  void endSession() {
    _log({
      'event': 'latency_session_ended',
      'session_id': _sessionId,
      'mode': _mode,
      'turn_count': _turnCounter,
      'ended_at': _isoNow(),
    });
  }

  LatencyRequestContext beginTurn() {
    final context = LatencyRequestContext(
      sessionId: sessionId,
      requestId: _newId(prefix: 'request'),
      turnIndex: ++_turnCounter,
    );

    final turn = _FrontendLatencyTurn(context);
    _turns[context.requestId] = turn;
    turn.mark('interaction_start');

    return context;
  }

  void mark(LatencyRequestContext context, String key, {String? responseText}) {
    final turn = _turns[context.requestId];
    if (turn == null) return;

    turn.mark(key);
    if (responseText != null) {
      turn.responseTextLength = responseText.runes.length;
    }

    if (key == 'audio_play_start' || key == 'audio_play_end') {
      final payload = turn.toStructuredLog();
      if (key == 'audio_play_end') {
        _completedLogs.add(payload);
      }
      _log(payload);
    }
  }

  List<Map<String, dynamic>> exportCompletedLogs() =>
      List.unmodifiable(_completedLogs);

  String exportCompletedLogsAsJsonLines() =>
      _completedLogs.map(jsonEncode).join('\n');

  String _newId({required String prefix}) {
    final now = DateTime.now().toUtc().microsecondsSinceEpoch;
    final randomPart = _random.nextInt(1 << 32).toRadixString(16);
    return '$prefix-$now-$randomPart';
  }

  void _log(Map<String, dynamic> payload) {
    debugPrint('[LATENCY]\n${_encoder.convert(payload)}');
  }

  String _isoNow() => DateTime.now().toUtc().toIso8601String();
}

class _FrontendLatencyTurn {
  _FrontendLatencyTurn(this.context);

  final LatencyRequestContext context;
  final Map<String, int> _timestamps = {};
  int? responseTextLength;

  void mark(String key) {
    _timestamps[key] = DateTime.now().toUtc().millisecondsSinceEpoch;
  }

  Map<String, dynamic> toStructuredLog() {
    return {
      'event': 'frontend_latency_turn',
      'session_id': context.sessionId,
      'request_id': context.requestId,
      'turn_index': context.turnIndex,
      'mode': 'FRONTEND_STT_TTS',
      'interaction_start': _iso('interaction_start'),
      'user_speech_start': _iso('user_speech_start'),
      'user_speech_end': _iso('user_speech_end'),
      'frontend_stt_start': _iso('frontend_stt_start'),
      'frontend_stt_end': _iso('frontend_stt_end'),
      'frontend_request_sent': _iso('frontend_request_sent'),
      'frontend_response_received': _iso('frontend_response_received'),
      'response_text_received': _iso('response_text_received'),
      'frontend_tts_start': _iso('frontend_tts_start'),
      'frontend_tts_ready': _iso('frontend_tts_ready'),
      'audio_play_start': _iso('audio_play_start'),
      'audio_play_end': _iso('audio_play_end'),
      'response_text_length': responseTextLength,
      'frontend_stt_processing_ms': _diff(
        'frontend_stt_start',
        'frontend_stt_end',
      ),
      'api_round_trip_ms': _diff(
        'frontend_request_sent',
        'frontend_response_received',
      ),
      'frontend_tts_processing_ms': _diff(
        'frontend_tts_start',
        'audio_play_start',
      ),
      'total_response_latency_ms': _diff('user_speech_end', 'audio_play_start'),
      'total_interaction_latency_ms': _diff(
        'interaction_start',
        'audio_play_start',
      ),
    };
  }

  String? _iso(String key) {
    final value = _timestamps[key];
    if (value == null) return null;
    return DateTime.fromMillisecondsSinceEpoch(
      value,
      isUtc: true,
    ).toIso8601String();
  }

  int? _diff(String start, String end) {
    final startMs = _timestamps[start];
    final endMs = _timestamps[end];
    if (startMs == null || endMs == null) return null;
    return endMs - startMs;
  }
}
