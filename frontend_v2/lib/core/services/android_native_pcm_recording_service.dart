import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
import 'package:record/record.dart';

class AndroidNativePcmRecordingService {
  AndroidNativePcmRecordingService._();

  static final AndroidNativePcmRecordingService instance =
      AndroidNativePcmRecordingService._();

  static const MethodChannel _methodChannel = MethodChannel(
    'com.ddalangoo.ddalangoo/native_pcm_recording',
  );
  static const EventChannel _eventChannel = EventChannel(
    'com.ddalangoo.ddalangoo/native_pcm_recording/events',
  );

  final StreamController<Amplitude> _amplitudeController =
      StreamController<Amplitude>.broadcast();

  StreamSubscription<dynamic>? _eventSubscription;
  bool _initialized = false;
  bool _isAvailable = false;
  bool _isRecording = false;
  double _maxAmplitude = -160.0;

  bool get isAvailable => _isAvailable;
  bool get isRecording => _isRecording;
  Stream<Amplitude> get amplitudeStream => _amplitudeController.stream;

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
              '⚠️ [Native PCM] event stream error: $error\n$stackTrace',
            );
          },
        );
      }
    } catch (error, stackTrace) {
      _isAvailable = false;
      debugPrint('⚠️ [Native PCM] init failed: $error\n$stackTrace');
    }

    return _isAvailable;
  }

  Future<void> startRecording({required String path}) async {
    await init();
    if (!_isAvailable) {
      throw UnsupportedError('Android native PCM recording is not available.');
    }

    _maxAmplitude = -160.0;
    await _methodChannel.invokeMethod<void>('startRecording', {'path': path});
    _isRecording = true;
  }

  Future<String?> stopRecording() async {
    if (!_isAvailable) {
      return null;
    }

    final path = await _methodChannel.invokeMethod<String>('stopRecording');
    _isRecording = false;
    return path;
  }

  Future<void> cancelRecording() async {
    if (!_isAvailable) {
      return;
    }

    await _methodChannel.invokeMethod<void>('cancelRecording');
    _isRecording = false;
  }

  Future<void> dispose() async {
    await _eventSubscription?.cancel();
    _eventSubscription = null;
    _isRecording = false;
  }

  void _handleEvent(dynamic event) {
    if (event is! Map) {
      return;
    }

    final payload = Map<String, dynamic>.from(event);
    final type = payload['type']?.toString();
    if (type != 'rms') {
      return;
    }

    final raw = payload['currentDb'];
    final current = switch (raw) {
      num value => value.toDouble(),
      String value => double.tryParse(value) ?? -160.0,
      _ => -160.0,
    }.clamp(-160.0, 0.0);
    if (current > _maxAmplitude) {
      _maxAmplitude = current;
    }
    _amplitudeController.add(Amplitude(current: current, max: _maxAmplitude));
  }
}
