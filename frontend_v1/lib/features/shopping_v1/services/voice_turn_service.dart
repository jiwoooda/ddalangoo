import '../../../core/services/gpt_voice_service.dart';
import '../../../core/services/gemini_voice_service.dart';
import 'package:record/record.dart';

class VoiceTurnService {
  VoiceTurnService({GptVoiceService? voiceService})
    : _voiceService = voiceService ?? GptVoiceService.instance;

  final GptVoiceService _voiceService;

  Future<void> init() => _voiceService.init();

  Future<void> speak(String text) => _voiceService.speak(text);

  Future<void> speakWithSegments(
    String text, {
    void Function(TtsSegmentData segment)? onSegmentStart,
  }) => _voiceService.speakWithSegments(
    text,
    onSegmentStart: onSegmentStart,
  );

  Future<void> stopSpeaking() => _voiceService.stopSpeaking();

  Future<void> playAudioUrl(
    String url, {
    int? expectedDurationMs,
  }) => _voiceService.playAudioUrl(
    url,
    expectedDurationMs: expectedDurationMs,
  );

  Future<void> startRecording() => _voiceService.startRecording();

  Future<String> stopRecordingAndTranscribe() =>
      _voiceService.stopRecordingAndTranscribe();

  Future<void> cancelRecording() => _voiceService.cancelRecording();

  Stream<Amplitude> onAmplitudeChanged({
    Duration interval = const Duration(milliseconds: 180),
  }) => _voiceService.onAmplitudeChanged(interval: interval);
}
