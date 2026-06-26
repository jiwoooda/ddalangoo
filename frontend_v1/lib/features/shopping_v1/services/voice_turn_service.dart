import '../../../core/services/gpt_voice_service.dart';
import '../../../core/services/gemini_voice_service.dart';
import 'package:audioplayers/audioplayers.dart';
import 'package:record/record.dart';

class VoiceTurnService {
  VoiceTurnService({GptVoiceService? voiceService})
    : _voiceService = voiceService ?? GptVoiceService.instance;

  final GptVoiceService _voiceService;
  final AudioPlayer _cuePlayer = AudioPlayer();

  Future<void> init() async {
    await _voiceService.init();
    await _cuePlayer.setReleaseMode(ReleaseMode.stop);
    await _cuePlayer.setPlayerMode(PlayerMode.lowLatency);
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

  Future<void> playListeningCue() async {
    try {
      await _cuePlayer.stop();
      await _cuePlayer.play(AssetSource('sounds/ding.mp3'));
    } catch (_) {
      // 효과음 에셋이 아직 없거나 재생에 실패해도 음성 플로우는 유지한다.
    }
  }

  Future<void> dispose() async {
    await _cuePlayer.dispose();
    await _voiceService.dispose();
  }
}
