import 'package:flutter/services.dart';
import '../../../core/services/gpt_voice_service.dart';
import '../../../core/services/android_native_speech_recognition_service.dart';
import '../../../core/services/gemini_voice_service.dart';
import 'package:record/record.dart';

class VoiceTurnService {
  VoiceTurnService({GptVoiceService? voiceService})
    : _voiceService = voiceService ?? GptVoiceService.instance;

  final GptVoiceService _voiceService;

  Future<void> init() async {
    await _voiceService.init();
  }

  Future<void> speak(String text) => _voiceService.speak(text);

  Future<void> speakWithSegments(
    String text, {
    void Function(TtsSegmentData segment)? onSegmentStart,
  }) => _voiceService.speakWithSegments(text, onSegmentStart: onSegmentStart);

  Future<void> stopSpeaking() => _voiceService.stopSpeaking();

  Future<void> playAudioUrl(String url, {int? expectedDurationMs}) =>
      _voiceService.playAudioUrl(url, expectedDurationMs: expectedDurationMs);

  Future<void> startRecording() => _voiceService.startRecording();

  Future<String> stopRecordingAndTranscribe() =>
      _voiceService.stopRecordingAndTranscribe();

  Future<void> cancelRecording() => _voiceService.cancelRecording();

  Stream<Amplitude> onAmplitudeChanged({
    Duration interval = const Duration(milliseconds: 200),
  }) => _voiceService.onAmplitudeChanged(interval: interval);

  Stream<NativeSpeechRecognitionEvent> onRecognitionEvent() =>
      _voiceService.onRecognitionEvent();

  bool get isUsingNativeAndroidAsr => _voiceService.isUsingNativeAndroidAsr;
  DateTime? get lastTtsPlaybackEndedAt => _voiceService.lastTtsPlaybackEndedAt;
  DateTime? get lastRecordingStartedAt => _voiceService.lastRecordingStartedAt;

  Future<void> playListeningCue() async {
    try {
      SystemSound.play(SystemSoundType.click);
    } catch (_) {
      // 내장 효과음이 재생되지 않아도 음성 플로우는 유지한다.
    }
  }

  Future<void> dispose() async {
    await _cuePlayer.dispose();
    await _voiceService.dispose();
  }
}
