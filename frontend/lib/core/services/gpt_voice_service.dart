import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter_dotenv/flutter_dotenv.dart';
import 'package:path_provider/path_provider.dart';
import 'package:record/record.dart';

import 'gemini_voice_service.dart';
import '../utils/latency_logger.dart';

class GptVoiceService {
  GptVoiceService({required String apiKey})
    : _apiKey = apiKey.trim(),
      _dio = Dio(
        BaseOptions(
          baseUrl: 'https://api.openai.com/v1',
          headers: {'Authorization': 'Bearer ${apiKey.trim()}'},
        ),
      );

  static GptVoiceService? _instance;
  static GptVoiceService get instance {
    final apiKey = dotenv.env['OPENAI_API_KEY'] ?? '';
    _instance ??= GptVoiceService(apiKey: apiKey);
    return _instance!;
  }

  static const String _sttModelName = 'gpt-4o-mini-transcribe';

  /// static const String _sttModelName = 'gpt-realtime-whisper';
  static const int _sampleRate = 16000;
  static const int _numChannels = 1;

  static const String _sttPrompt =
      "이 오디오는 한국어 음성 쇼핑 보조 서비스 '딸랑구'의 사용자 발화입니다. "
      '사용자의 말을 가능한 한 들리는 그대로 정확히 전사해주세요. '
      "고령층 사용자가 천천히 말하거나, 생각하면서 중간에 쉬거나, '음', '어', '그' 같은 간투사를 말할 수 있습니다. "
      '말 사이에 짧은 침묵이 있어도 하나의 발화로 자연스럽게 이어서 전사해주세요. '
      '상품명, 수량, 가격, 배송지, 장바구니, 결제, 재주문과 관련된 표현은 특히 정확히 전사해주세요. '
      '불확실한 내용은 임의로 바꾸지 말고 들리는 대로 전사해주세요.';

  final String _apiKey;
  final Dio _dio;
  final AudioRecorder _recorder = AudioRecorder();
  final GeminiVoiceService _geminiTts = GeminiVoiceService.instance;
  Future<Directory?>? _sttRecordingDirectoryFuture;
  String? _activeRecordingPath;
  bool _isRecording = false;

  bool get isRecording => _isRecording;
  bool get isSpeaking => _geminiTts.isSpeaking;
  bool get _supportsFileAudioFlow => !kIsWeb;

  Future<void> init() async {
    _ensureApiKey();
    await _geminiTts.init();
    if (!_supportsFileAudioFlow) {
      return;
    }
    _sttRecordingDirectoryFuture ??= _prepareSttRecordingDirectory();
  }

  Future<void> startRecording() async {
    _ensureApiKey();
    _ensureRecordingSupported();
    if (_isRecording) return;

    final hasPermission = await _recorder.hasPermission();
    if (!hasPermission) {
      throw Exception('브라우저/기기에서 마이크 권한이 허용되지 않았습니다.');
    }

    try {
      final path = await _createSttRecordingPath();
      _activeRecordingPath = path;
      await _recorder.start(
        const RecordConfig(
          encoder: AudioEncoder.wav,
          sampleRate: _sampleRate,
          numChannels: _numChannels,
          autoGain: false,
          echoCancel: false,
          noiseSuppress: false,
        ),
        path: path,
      );
      _isRecording = true;
    } catch (e) {
      _isRecording = false;
      _activeRecordingPath = null;
      rethrow;
    }
  }

  Future<String> stopRecordingAndTranscribe() async {
    _ensureRecordingSupported();
    if (!_isRecording) {
      throw Exception('현재 진행 중인 녹음이 없습니다.');
    }

    _isRecording = false;
    String? cleanupPath;

    try {
      final recordedPath = await _recorder.stop();
      final path = recordedPath ?? _activeRecordingPath;
      cleanupPath = path;
      _activeRecordingPath = null;

      if (path == null) {
        throw Exception('녹음 파일 경로를 찾지 못했습니다.');
      }

      final audioFile = File(path);
      final transcript = await transcribeAudioFile(audioFile);
      return transcript;
    } finally {
      _activeRecordingPath = null;
      if (cleanupPath != null) {
        unawaited(_deleteIfExists(cleanupPath));
      }
    }
  }

  Future<String> transcribeAudioFile(File audioFile) async {
    _ensureApiKey();

    if (!await audioFile.exists()) {
      throw Exception('전사할 오디오 파일이 존재하지 않습니다.');
    }

    final fileLength = await audioFile.length();
    if (fileLength <= 0) {
      throw Exception('전사할 오디오 파일이 비어 있습니다.');
    }

    try {
      final formData = FormData.fromMap({
        'model': _sttModelName,
        'language': 'ko',
        'response_format': 'json',
        'prompt': _sttPrompt,
        'file': await MultipartFile.fromFile(
          audioFile.path,
          filename: audioFile.uri.pathSegments.isNotEmpty
              ? audioFile.uri.pathSegments.last
              : 'voice.wav',
        ),
      });

      final response = await _dio.post<Map<String, dynamic>>(
        '/audio/transcriptions',
        data: formData,
        options: Options(
          contentType: 'multipart/form-data',
          responseType: ResponseType.json,
        ),
      );

      final text = _extractTranscriptText(response.data);
      if (text.isEmpty) {
        throw Exception('음성 인식 결과가 비어 있습니다.');
      }
      return text;
    } on DioException catch (e) {
      throw Exception(_buildHttpErrorMessage('STT', e));
    }
  }

  Future<Uint8List> synthesizeSpeechToBytes(String text) async {
    return _geminiTts.synthesizeSpeechToBytes(text);
  }

  Future<String> synthesizeSpeechToFile(String text) async {
    return _geminiTts.synthesizeSpeechToFile(text);
  }

  Future<void> prefetchSpeech(String text) async {
    await _geminiTts.prefetchSpeech(text);
  }

  Future<void> prefetchMultiple(Iterable<String> texts) async {
    await _geminiTts.prefetchMultiple(texts);
  }

  Future<void> speak(
    String text, {
    LatencyRequestContext? latencyContext,
    VoidCallback? onPlaybackStart,
  }) async {
    final normalized = text.trim();
    if (normalized.isEmpty) {
      throw Exception('음성으로 읽을 텍스트가 비어 있습니다.');
    }
    await _geminiTts.speak(
      normalized,
      latencyContext: latencyContext,
      onPlaybackStart: onPlaybackStart,
    );
  }

  Future<void> stopSpeaking() async {
    await _geminiTts.stopSpeaking();
  }

  Future<void> dispose() async {
    await _recorder.dispose();
  }

  Future<void> cancelRecording() async {
    _ensureRecordingSupported();
    if (!_isRecording) return;

    _isRecording = false;
    final path = _activeRecordingPath;
    _activeRecordingPath = null;
    await _recorder.cancel();
    if (path != null) {
      await _deleteIfExists(path);
    }
  }

  Future<Directory?> _prepareSttRecordingDirectory() async {
    try {
      final baseDirectory = await getTemporaryDirectory();
      final recordingDirectory = Directory(
        '${baseDirectory.path}${Platform.pathSeparator}stt_recordings',
      );
      if (!await recordingDirectory.exists()) {
        await recordingDirectory.create(recursive: true);
      }
      return recordingDirectory;
    } catch (e) {
      throw Exception('STT 임시 디렉터리를 준비하지 못했습니다: $e');
    }
  }

  Future<String> _createSttRecordingPath() async {
    final directoryFuture = _sttRecordingDirectoryFuture ??=
        _prepareSttRecordingDirectory();
    final directory = await directoryFuture;
    if (directory == null) {
      throw Exception('STT 임시 녹음 디렉터리를 준비하지 못했습니다.');
    }

    final now = DateTime.now().microsecondsSinceEpoch;
    return '${directory.path}${Platform.pathSeparator}stt_$now.wav';
  }

  Future<void> _deleteIfExists(String path) async {
    try {
      final file = File(path);
      if (await file.exists()) {
        await file.delete();
      }
    } catch (_) {}
  }

  String _extractTranscriptText(Map<String, dynamic>? data) {
    if (data == null) return '';

    final text = data['text'];
    if (text is String) {
      return text.trim();
    }

    final transcript = data['transcript'];
    if (transcript is String) {
      return transcript.trim();
    }

    return '';
  }

  String _buildHttpErrorMessage(String label, DioException error) {
    final statusCode = error.response?.statusCode;
    final body = error.response?.data;
    final details = body is String ? body : jsonEncode(body);
    return '$label 요청에 실패했습니다'
        '${statusCode == null ? '' : ' (HTTP $statusCode)'}'
        '${details.isEmpty ? '' : ': $details'}';
  }

  void _ensureApiKey() {
    if (_apiKey.isEmpty) {
      throw Exception('OPENAI_API_KEY가 설정되지 않았습니다.');
    }
  }

  void _ensureRecordingSupported() {
    if (!_supportsFileAudioFlow) {
      throw UnsupportedError(
        'GptVoiceService의 현재 파일 기반 STT/TTS 구현은 Flutter Web을 지원하지 않습니다. '
        'Android/iOS/macOS 앱에서 실행해주세요.',
      );
    }
  }

}
