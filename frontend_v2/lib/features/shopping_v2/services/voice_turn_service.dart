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

  /// 음성 인식이 "시작"될 때 사용자가 쉽게 알아챌 수 있도록 재생하는 신호음.
  /// 별도 오디오 에셋 없이 플랫폼 내장(System) 효과음을 사용한다.
  Future<void> playStartListeningCue() async {
    try {
      SystemSound.play(SystemSoundType.click);
      HapticFeedback.lightImpact();
    } catch (_) {
      // 내장 효과음이 재생되지 않아도 음성 플로우는 유지한다.
    }
  }

  /// 음성 인식이 "종료"될 때 재생하는 신호음. 시작음과 소리를 달리해
  /// 켜짐/꺼짐을 청각적으로 구분할 수 있게 한다.
  Future<void> playStopListeningCue() async {
    try {
      SystemSound.play(SystemSoundType.alert);
      HapticFeedback.selectionClick();
    } catch (_) {
      // 내장 효과음이 재생되지 않아도 음성 플로우는 유지한다.
    }
  }

  /// 하위 호환용 alias (기존 호출부가 남아있을 경우 시작음으로 동작).
  @Deprecated('Use playStartListeningCue or playStopListeningCue instead.')
  Future<void> playListeningCue() => playStartListeningCue();

  Future<void> dispose() async {
    await _voiceService.dispose();
  }
}
