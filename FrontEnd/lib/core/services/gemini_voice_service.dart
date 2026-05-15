// Gemini-Flash STT/TTS 서비스
import 'dart:io';
import 'package:flutter_dotenv/flutter_dotenv.dart';
import 'package:google_generative_ai/google_generative_ai.dart';
import 'package:record/record.dart';
import 'package:flutter_tts/flutter_tts.dart';
import 'package:path_provider/path_provider.dart';

class GeminiVoiceService {
  static GeminiVoiceService? _instance;
  static GeminiVoiceService get instance =>
      _instance ??= GeminiVoiceService._();
  GeminiVoiceService._();

  final AudioRecorder _recorder = AudioRecorder();
  final FlutterTts _tts = FlutterTts();
  bool _isRecording = false;
  bool _isSpeaking = false;

  bool get isRecording => _isRecording;
  bool get isSpeaking => _isSpeaking;

  // TTS 초기화 (앱 시작 시 한 번 호출)
  Future<void> init() async {
    await _tts.setLanguage('ko-KR');
    await _tts.setSpeechRate(0.45);
    await _tts.setVolume(1.0);
    await _tts.setPitch(1.0);
    _tts.setCompletionHandler(() {
      _isSpeaking = false;
    });
  }

  // Gemini 모델 (STT용)
  GenerativeModel get _model => GenerativeModel(
    model: 'gemini-3-flash-preview',
    apiKey: dotenv.env['GEMINI_API_KEY'] ?? '',
  );

  // 녹음 시작
  Future<void> startRecording() async {
    if (_isRecording) return;

    final hasPermission = await _recorder.hasPermission();
    if (!hasPermission) throw Exception('마이크 권한이 없습니다');

    final dir = await getTemporaryDirectory();
    final path = '${dir.path}/recording.m4a';

    await _recorder.start(
      const RecordConfig(
        encoder: AudioEncoder.aacLc,
        sampleRate: 16000,
        numChannels: 1,
      ),
      path: path,
    );

    _isRecording = true;
  }

  // 녹음 중지 → Gemini STT → 텍스트 반환
  Future<String?> stopRecordingAndTranscribe() async {
    if (!_isRecording) return null;

    final path = await _recorder.stop();
    _isRecording = false;

    if (path == null) return null;

    try {
      final audioBytes = await File(path).readAsBytes();

      final response = await _model.generateContent([
        Content.multi([
          DataPart('audio/mp4', audioBytes),
          TextPart(
            '이 오디오를 한국어로 정확하게 텍스트로 변환해줘. '
            '텍스트만 출력하고 다른 설명은 절대 하지 마.',
          ),
        ]),
      ]);

      return response.text?.trim();
    } catch (e) {
      return null;
    }
  }

  // TTS — 한국어 읽기
  Future<void> speak(String text) async {
    if (_isSpeaking) await stopSpeaking();
    _isSpeaking = true;
    await _tts.speak(text);
  }

  // 음성 중지
  Future<void> stopSpeaking() async {
    await _tts.stop();
    _isSpeaking = false;
  }

  // 리소스 해제
  Future<void> dispose() async {
    await _recorder.dispose();
    await _tts.stop();
  }
}
