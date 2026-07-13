import 'dart:async';
import 'dart:math';

import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
import 'package:record/record.dart';

import 'voice_timeline_log_service.dart';

enum NativeSpeechRecognitionEventType { partial, result, error, state }

class NativeSpeechRecognitionEvent {
  const NativeSpeechRecognitionEvent({
    required this.type,
    this.text,
    this.code,
    this.message,
    this.state,
    this.recoverable = false,
    this.requestId,
    this.source,
    this.attempt,
    this.emittedAt,
    this.raw = const <String, dynamic>{},
  });

  final NativeSpeechRecognitionEventType type;
  final String? text;
  final String? code;
  final String? message;
  final String? state;
  final bool recoverable;
  final String? requestId;
  final String? source;
  final int? attempt;
  final DateTime? emittedAt;
  final Map<String, dynamic> raw;
}

class AndroidNativeSpeechRecognitionService {
  AndroidNativeSpeechRecognitionService._();

  static final AndroidNativeSpeechRecognitionService instance =
      AndroidNativeSpeechRecognitionService._();

  static const MethodChannel _methodChannel = MethodChannel(
    'com.ddalangoo.ddalangoo/native_speech_recognition',
  );
  static const EventChannel _eventChannel = EventChannel(
    'com.ddalangoo.ddalangoo/native_speech_recognition/events',
  );

  final StreamController<Amplitude> _amplitudeController =
      StreamController<Amplitude>.broadcast();
  final StreamController<NativeSpeechRecognitionEvent> _eventController =
      StreamController<NativeSpeechRecognitionEvent>.broadcast();
  final Random _random = Random();

  StreamSubscription<dynamic>? _eventSubscription;
  Completer<String>? _resultCompleter;
  bool _initialized = false;
  bool _isAvailable = false;
  bool _isListening = false;
  double _maxAmplitude = -160.0;
  String _latestPartial = '';
  String? _activeRequestId;
  final Map<String, int> _activeTimelineMs = {};
  int _partialCount = 0;
  int _recoverableErrorCount = 0;

  bool get isAvailable => _isAvailable;
  bool get isListening => _isListening;
  Stream<Amplitude> get amplitudeStream => _amplitudeController.stream;
  Stream<NativeSpeechRecognitionEvent> get recognitionEventStream =>
      _eventController.stream;

  Future<bool> init() async {
    if (_initialized) {
      return _isAvailable;
    }
    _initialized = true;

    try {
      _isAvailable =
          await _methodChannel.invokeMethod<bool>('isAvailable') ?? false;
      if (_isAvailable) {
        _eventSubscription = _eventChannel.receiveBroadcastStream().listen(
          _handleEvent,
          onError: (Object error, StackTrace stackTrace) {
            debugPrint(
              '⚠️ [Native ASR] event stream error: $error\n$stackTrace',
            );
          },
        );
      }
    } catch (error, stackTrace) {
      _isAvailable = false;
      debugPrint('⚠️ [Native ASR] init failed: $error\n$stackTrace');
    }

    return _isAvailable;
  }

  Future<void> startListening({String locale = 'ko-KR'}) async {
    await init();
    if (!_isAvailable) {
      throw UnsupportedError(
        'Android native speech recognition is unavailable.',
      );
    }

    _beginActiveSession(locale: locale);
    _resultCompleter = Completer<String>();
    _latestPartial = '';
    _maxAmplitude = -160.0;
    try {
      await _methodChannel.invokeMethod<void>('startListening', {
        'locale': locale,
        'requestId': _activeRequestId,
      });
      _markActiveTimeline('listenMethodReturnedAt');
      _isListening = true;
      _logActiveEvent('native_asr_listen_started', extra: {'locale': locale});
    } catch (error, stackTrace) {
      _markActiveTimeline('listenStartFailedAt');
      _logActiveEvent(
        'native_asr_listen_start_failed',
        extra: {
          'locale': locale,
          'error': error.toString(),
          'stackTrace': stackTrace.toString(),
        },
      );
      _resetActiveSession();
      rethrow;
    }
  }

  Future<String> stopListening() async {
    if (!_isAvailable) {
      return '';
    }

    final completer = _resultCompleter ??= Completer<String>();
    _markActiveTimeline('stopRequestedAt');
    _logActiveEvent(
      'native_asr_stop_requested',
      extra: {'latestPartialLength': _latestPartial.trim().runes.length},
    );
    await _methodChannel.invokeMethod<void>('stopListening');
    final transcript = await completer.future.timeout(
      const Duration(seconds: 5),
      onTimeout: () {
        _markActiveTimeline('resultTimeoutFallbackAt');
        _logActiveEvent(
          'native_asr_timeout_fallback',
          extra: {'latestPartialLength': _latestPartial.trim().runes.length},
        );
        return _latestPartial.trim();
      },
    );
    _markActiveTimeline('resultResolvedAt');
    _isListening = false;
    _resultCompleter = null;
    _latestPartial = transcript;
    _logSessionSummary(
      'native_asr_completed',
      transcript: transcript,
      resolution: 'stop_listening',
    );
    try {
      // stopListening 이후에도 플랫폼 recognizer 인스턴스가 남아 다음 턴을
      // 불안정하게 만들 수 있어 결과 수신 뒤엔 항상 강제 정리한다.
      await _methodChannel.invokeMethod<void>('cancelListening');
    } catch (error, stackTrace) {
      debugPrint(
        '⚠️ [Native ASR] post-stop cleanup failed: $error\n$stackTrace',
      );
    }
    _resetActiveSession();
    return transcript;
  }

  Future<void> cancelListening() async {
    if (!_isAvailable) {
      return;
    }

    _markActiveTimeline('cancelRequestedAt');
    _logActiveEvent(
      'native_asr_cancel_requested',
      extra: {'latestPartialLength': _latestPartial.trim().runes.length},
    );
    await _methodChannel.invokeMethod<void>('cancelListening');
    _isListening = false;
    _completePendingResult(_latestPartial.trim());
    _logSessionSummary(
      'native_asr_cancelled',
      transcript: _latestPartial.trim(),
      resolution: 'cancel_listening',
    );
    _resetActiveSession();
  }

  Future<void> dispose() async {
    await _eventSubscription?.cancel();
    _eventSubscription = null;
    _isListening = false;
    _completePendingResult(_latestPartial.trim());
    _resetActiveSession();
  }

  void _handleEvent(dynamic event) {
    if (event is! Map) {
      return;
    }

    final payload = Map<String, dynamic>.from(event);
    final type = payload['type']?.toString();
    final requestId = payload['requestId']?.toString();
    if (requestId != null && requestId.isNotEmpty) {
      _activeRequestId ??= requestId;
    }
    final emittedAt = _parsePlatformTimestamp(payload['emittedAtMs']);
    switch (type) {
      case 'rms':
        final raw = payload['currentDb'];
        final current = switch (raw) {
          num value => value.toDouble(),
          String value => double.tryParse(value) ?? -160.0,
          _ => -160.0,
        }.clamp(-160.0, 0.0);
        if (current > _maxAmplitude) {
          _maxAmplitude = current;
        }
        _amplitudeController.add(
          Amplitude(current: current, max: _maxAmplitude),
        );
        return;
      case 'partial':
        _latestPartial = payload['text']?.toString() ?? '';
        _partialCount += 1;
        _markActiveTimeline('firstPartialAt');
        debugPrint('🎙️ [Native ASR] partial="$_latestPartial"');
        _logActiveEvent(
          'native_asr_partial_received',
          extra: {
            'partialCount': _partialCount,
            'textLength': _latestPartial.runes.length,
            'emittedAt': emittedAt?.toUtc().toIso8601String(),
          },
        );
        _eventController.add(
          NativeSpeechRecognitionEvent(
            type: NativeSpeechRecognitionEventType.partial,
            text: _latestPartial,
            requestId: requestId ?? _activeRequestId,
            emittedAt: emittedAt,
            raw: payload,
          ),
        );
        return;
      case 'result':
        final transcript = payload['text']?.toString().trim() ?? '';
        _markActiveTimeline('finalResultEventAt');
        debugPrint('🎙️ [Native ASR] final="$transcript"');
        _logActiveEvent(
          'native_asr_result_received',
          extra: {
            'textLength': transcript.runes.length,
            'source': payload['source']?.toString(),
            'emittedAt': emittedAt?.toUtc().toIso8601String(),
          },
        );
        _eventController.add(
          NativeSpeechRecognitionEvent(
            type: NativeSpeechRecognitionEventType.result,
            text: transcript,
            requestId: requestId ?? _activeRequestId,
            source: payload['source']?.toString(),
            emittedAt: emittedAt,
            raw: payload,
          ),
        );
        _completePendingResult(transcript);
        _isListening = false;
        return;
      case 'error':
        final code = payload['code']?.toString() ?? 'unknown_error';
        final message = payload['message']?.toString() ?? '';
        final recoverable = payload['recoverable'] == true;
        if (recoverable) {
          _recoverableErrorCount += 1;
        } else {
          _markActiveTimeline('terminalErrorAt');
        }
        debugPrint(
          '⚠️ [Native ASR] error code=$code message="$message" recoverable=$recoverable',
        );
        _logActiveEvent(
          recoverable
              ? 'native_asr_recoverable_error'
              : 'native_asr_terminal_error',
          extra: {
            'code': code,
            'message': message,
            'recoverable': recoverable,
            'latestPartialLength': _latestPartial.trim().runes.length,
            'recoverableErrorCount': _recoverableErrorCount,
            'emittedAt': emittedAt?.toUtc().toIso8601String(),
          },
        );
        _eventController.add(
          NativeSpeechRecognitionEvent(
            type: NativeSpeechRecognitionEventType.error,
            code: code,
            message: message,
            recoverable: recoverable,
            requestId: requestId ?? _activeRequestId,
            emittedAt: emittedAt,
            raw: payload,
          ),
        );
        if (recoverable) {
          return;
        }
        _completePendingResult(_latestPartial.trim());
        _isListening = false;
        return;
      case 'state':
        final state = payload['value']?.toString() ?? 'unknown';
        _markPlatformState(state);
        debugPrint('🎙️ [Native ASR] state=$state');
        _logActiveEvent(
          'native_asr_state',
          extra: {
            'state': state,
            'attempt': _toInt(payload['attempt']),
            'emittedAt': emittedAt?.toUtc().toIso8601String(),
          },
        );
        _eventController.add(
          NativeSpeechRecognitionEvent(
            type: NativeSpeechRecognitionEventType.state,
            state: state,
            requestId: requestId ?? _activeRequestId,
            attempt: _toInt(payload['attempt']),
            emittedAt: emittedAt,
            raw: payload,
          ),
        );
        return;
      default:
        return;
    }
  }

  void _completePendingResult(String transcript) {
    final completer = _resultCompleter;
    if (completer == null || completer.isCompleted) {
      return;
    }
    completer.complete(transcript);
  }

  void _beginActiveSession({required String locale}) {
    _activeRequestId = _newRequestId(prefix: 'native_asr');
    _activeTimelineMs.clear();
    _partialCount = 0;
    _recoverableErrorCount = 0;
    _markActiveTimeline('listenRequestedAt');
    _logActiveEvent('native_asr_listen_requested', extra: {'locale': locale});
  }

  void _resetActiveSession() {
    _activeRequestId = null;
    _activeTimelineMs.clear();
    _partialCount = 0;
    _recoverableErrorCount = 0;
  }

  void _markActiveTimeline(String key, {int? ms}) {
    if (_activeRequestId == null) {
      return;
    }
    _activeTimelineMs.putIfAbsent(key, () => ms ?? _nowMs());
  }

  void _markPlatformState(String state) {
    switch (state) {
      case 'start_requested':
        _markActiveTimeline('platformStartRequestedAt');
        return;
      case 'ready':
        _markActiveTimeline('platformReadyAt');
        return;
      case 'speech_begin':
        _markActiveTimeline('speechBeginAt');
        return;
      case 'speech_end':
        _markActiveTimeline('speechEndAt');
        return;
      case 'stop_requested':
        _markActiveTimeline('platformStopRequestedAt');
        return;
      case 'restart_scheduled':
        _markActiveTimeline('restartScheduledAt');
        return;
      case 'restart_requested':
        _markActiveTimeline('restartRequestedAt');
        return;
      default:
        return;
    }
  }

  void _logActiveEvent(String event, {Map<String, dynamic>? extra}) {
    final requestId = _activeRequestId;
    if (requestId == null) {
      return;
    }
    VoiceTimelineLogService.instance.logBestEffort(
      event,
      payload: {
        'requestId': requestId,
        'engine': 'android_native_speech_recognizer',
        'timeline': _timelineIsoSnapshot(),
        ...?extra,
      },
    );
  }

  void _logSessionSummary(
    String event, {
    required String transcript,
    required String resolution,
  }) {
    final requestId = _activeRequestId;
    if (requestId == null) {
      return;
    }
    VoiceTimelineLogService.instance.logBestEffort(
      event,
      payload: {
        'requestId': requestId,
        'engine': 'android_native_speech_recognizer',
        'resolution': resolution,
        'partialCount': _partialCount,
        'recoverableErrorCount': _recoverableErrorCount,
        'transcriptLength': transcript.runes.length,
        'timeline': _timelineIsoSnapshot(),
        'durationsMs': {
          'listen_to_platform_ready': _diffMs(
            'listenRequestedAt',
            'platformReadyAt',
          ),
          'listen_to_speech_begin': _diffMs(
            'listenRequestedAt',
            'speechBeginAt',
          ),
          'listen_to_first_partial': _diffMs(
            'listenRequestedAt',
            'firstPartialAt',
          ),
          'listen_to_final_result_event': _diffMs(
            'listenRequestedAt',
            'finalResultEventAt',
          ),
          'stop_to_result_resolved': _diffMs(
            'stopRequestedAt',
            'resultResolvedAt',
          ),
          'speech_begin_to_final_result_event': _diffMs(
            'speechBeginAt',
            'finalResultEventAt',
          ),
        },
      },
    );
  }

  Map<String, String> _timelineIsoSnapshot() {
    return {
      for (final entry in _activeTimelineMs.entries)
        entry.key: DateTime.fromMillisecondsSinceEpoch(
          entry.value,
          isUtc: true,
        ).toIso8601String(),
    };
  }

  int? _diffMs(String startKey, String endKey) {
    final start = _activeTimelineMs[startKey];
    final end = _activeTimelineMs[endKey];
    if (start == null || end == null) {
      return null;
    }
    return end - start;
  }

  DateTime? _parsePlatformTimestamp(Object? raw) {
    final ms = _toInt(raw);
    if (ms == null) {
      return null;
    }
    return DateTime.fromMillisecondsSinceEpoch(ms, isUtc: true);
  }

  int? _toInt(Object? raw) {
    if (raw is int) {
      return raw;
    }
    if (raw is num) {
      return raw.round();
    }
    return int.tryParse(raw?.toString() ?? '');
  }

  int _nowMs() => DateTime.now().toUtc().millisecondsSinceEpoch;

  String _newRequestId({required String prefix}) {
    final now = DateTime.now().toUtc().microsecondsSinceEpoch;
    final randomPart = _random.nextInt(0x100000000).toRadixString(16);
    return '$prefix-$now-$randomPart';
  }
}
