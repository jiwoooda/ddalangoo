import '../../../core/services/gpt_voice_service.dart';
import 'package:record/record.dart';

class VoiceTurnService {
  VoiceTurnService({GptVoiceService? voiceService})
    : _voiceService = voiceService ?? GptVoiceService.instance;

  final GptVoiceService _voiceService;

  Future<void> init() => _voiceService.init();

  Future<void> speak(String text) => _voiceService.speak(text);

  Future<void> stopSpeaking() => _voiceService.stopSpeaking();

  Future<void> startRecording() => _voiceService.startRecording();

  Future<String> stopRecordingAndTranscribe() =>
      _voiceService.stopRecordingAndTranscribe();

  Future<void> cancelRecording() => _voiceService.cancelRecording();

  Stream<Amplitude> onAmplitudeChanged({
    Duration interval = const Duration(milliseconds: 180),
  }) => _voiceService.onAmplitudeChanged(interval: interval);
}
