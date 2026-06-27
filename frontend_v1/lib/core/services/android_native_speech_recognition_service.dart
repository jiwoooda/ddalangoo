import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
import 'package:record/record.dart';

enum NativeSpeechRecognitionEventType { partial, result, error, state }

class NativeSpeechRecognitionEvent {
  const NativeSpeechRecognitionEvent({
    required this.type,
    this.text,
    this.code,
    this.message,
    this.state,
    this.recoverable = false,
  });

  final NativeSpeechRecognitionEventType type;
  final String? text;
  final String? code;
  final String? message;
  final String? state;
  final bool recoverable;
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

  StreamSubscription<dynamic>? _eventSubscription;
  Completer<String>? _resultCompleter;
  bool _initialized = false;
  bool _isAvailable = false;
  bool _isListening = false;
  double _maxAmplitude = -160.0;
  String _latestPartial = '';

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

    _resultCompleter = Completer<String>();
    _latestPartial = '';
    _maxAmplitude = -160.0;
    await _methodChannel.invokeMethod<void>('startListening', {
      'locale': locale,
    });
    _isListening = true;
  }

  Future<String> stopListening() async {
    if (!_isAvailable) {
      return '';
    }

    final completer = _resultCompleter ??= Completer<String>();
    await _methodChannel.invokeMethod<void>('stopListening');
    final transcript = await completer.future.timeout(
      const Duration(seconds: 5),
      onTimeout: () => _latestPartial.trim(),
    );
    _isListening = false;
    _resultCompleter = null;
    _latestPartial = transcript;
    try {
      // stopListening 이후에도 플랫폼 recognizer 인스턴스가 남아 다음 턴을
      // 불안정하게 만들 수 있어 결과 수신 뒤엔 항상 강제 정리한다.
      await _methodChannel.invokeMethod<void>('cancelListening');
    } catch (error, stackTrace) {
      debugPrint(
        '⚠️ [Native ASR] post-stop cleanup failed: $error\n$stackTrace',
      );
    }
    return transcript;
  }

  Future<void> cancelListening() async {
    if (!_isAvailable) {
      return;
    }

    await _methodChannel.invokeMethod<void>('cancelListening');
    _isListening = false;
    _completePendingResult(_latestPartial.trim());
  }

  Future<void> dispose() async {
    await _eventSubscription?.cancel();
    _eventSubscription = null;
    _isListening = false;
    _completePendingResult(_latestPartial.trim());
  }

  void _handleEvent(dynamic event) {
    if (event is! Map) {
      return;
    }

    final payload = Map<String, dynamic>.from(event);
    final type = payload['type']?.toString();
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
        debugPrint('🎙️ [Native ASR] partial="$_latestPartial"');
        _eventController.add(
          NativeSpeechRecognitionEvent(
            type: NativeSpeechRecognitionEventType.partial,
            text: _latestPartial,
          ),
        );
        return;
      case 'result':
        final transcript = payload['text']?.toString().trim() ?? '';
        debugPrint('🎙️ [Native ASR] final="$transcript"');
        _eventController.add(
          NativeSpeechRecognitionEvent(
            type: NativeSpeechRecognitionEventType.result,
            text: transcript,
          ),
        );
        _completePendingResult(transcript);
        _isListening = false;
        return;
      case 'error':
        final code = payload['code']?.toString() ?? 'unknown_error';
        final message = payload['message']?.toString() ?? '';
        final recoverable = payload['recoverable'] == true;
        debugPrint(
          '⚠️ [Native ASR] error code=$code message="$message" recoverable=$recoverable',
        );
        _eventController.add(
          NativeSpeechRecognitionEvent(
            type: NativeSpeechRecognitionEventType.error,
            code: code,
            message: message,
            recoverable: recoverable,
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
        debugPrint('🎙️ [Native ASR] state=$state');
        _eventController.add(
          NativeSpeechRecognitionEvent(
            type: NativeSpeechRecognitionEventType.state,
            state: state,
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
}
