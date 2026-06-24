import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart';
import 'package:path_provider/path_provider.dart';
import 'package:record/record.dart';

import 'gemini_voice_service.dart';
import '../network/api_client.dart';
import '../utils/latency_logger.dart';

class GptVoiceService {
  GptVoiceService();

  static GptVoiceService? _instance;
  static GptVoiceService get instance {
    _instance ??= GptVoiceService();
    return _instance!;
  }

  // STT는 백엔드 /api/voice/stt 로 위임한다. 직접 모델명을 관리하지 않는다.
  static const int _sampleRate = 16000;
  static const int _numChannels = 1;
  static const String _sttMultipartFieldName = 'file';
  static const String _sttEndpointPath = '/api/voice/stt';

  // STT 프롬프트는 백엔드 voice_service.py에서 관리한다.

  final AudioRecorder _recorder = AudioRecorder();
  final GeminiVoiceService _geminiTts = GeminiVoiceService.instance;
  Future<Directory?>? _sttRecordingDirectoryFuture;
  String? _activeRecordingPath;
  bool _isRecording = false;

  bool get isRecording => _isRecording;
  bool get isSpeaking => _geminiTts.isSpeaking;
  bool get _supportsFileAudioFlow => !kIsWeb;

  Stream<Amplitude> onAmplitudeChanged({
    Duration interval = const Duration(milliseconds: 180),
  }) {
    _ensureRecordingSupported();
    return _recorder.onAmplitudeChanged(interval);
  }

  Future<void> init() async {
    await _geminiTts.init();
    if (!_supportsFileAudioFlow) {
      return;
    }
    _sttRecordingDirectoryFuture ??= _prepareSttRecordingDirectory();
  }

  Future<void> startRecording() async {
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
          autoGain: true,
          echoCancel: true,
          noiseSuppress: true,
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
      await _logRecordedFile('recording_stopped', audioFile);
      final transcript = await transcribeAudioFile(audioFile);
      return transcript;
    } finally {
      _activeRecordingPath = null;
      if (cleanupPath != null) {
        unawaited(_deleteIfExists(cleanupPath));
      }
    }
  }

  /// 백엔드 /api/voice/stt 로 오디오 파일을 전송하고 전사 텍스트를 받는다.
  /// OPENAI_API_KEY / GEMINI_API_KEY를 프론트에서 사용하지 않는다.
  Future<String> transcribeAudioFile(File audioFile) async {
    if (!await audioFile.exists()) {
      throw Exception('전사할 오디오 파일이 존재하지 않습니다.');
    }

    final fileLength = await audioFile.length();
    if (fileLength <= 0) {
      throw Exception('전사할 오디오 파일이 비어 있습니다.');
    }

    try {
      await _logRecordedFile('stt_request_prepare', audioFile);
      final formData = FormData.fromMap({
        _sttMultipartFieldName: await MultipartFile.fromFile(
          audioFile.path,
          filename: audioFile.uri.pathSegments.isNotEmpty
              ? audioFile.uri.pathSegments.last
              : 'voice.wav',
        ),
      });

      debugPrint(
        '🎙️ [STT Request] '
        'requestUrl=${ApiClient.baseUrl}$_sttEndpointPath, '
        'multipartFieldName=$_sttMultipartFieldName, '
        'fileSize=$fileLength',
      );

      final response = await ApiClient.dio.post<Map<String, dynamic>>(
        _sttEndpointPath,
        data: formData,
        options: Options(
          contentType: 'multipart/form-data',
          responseType: ResponseType.json,
        ),
      );

      final text = _extractTranscriptText(response.data);
      return text; // 빈 발화는 빈 문자열로 반환 (오류 아님)
    } on DioException catch (e) {
      await _logRecordedFile('stt_request_failed', audioFile);
      debugPrint(
        '❌ [STT Dio Error] '
        'requestUrl=${ApiClient.baseUrl}$_sttEndpointPath, '
        'multipartFieldName=$_sttMultipartFieldName, '
        'type=${e.type.name}, '
        'message=${e.message}, '
        'statusCode=${e.response?.statusCode}, '
        'data=${e.response?.data}',
      );
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

  Future<void> speakWithSegments(
    String text, {
    LatencyRequestContext? latencyContext,
    VoidCallback? onPlaybackStart,
    ValueChanged<TtsSegmentData>? onSegmentStart,
  }) async {
    final normalized = text.trim();
    if (normalized.isEmpty) {
      throw Exception('음성으로 읽을 텍스트가 비어 있습니다.');
    }
    await _geminiTts.speakWithSegments(
      normalized,
      latencyContext: latencyContext,
      onPlaybackStart: onPlaybackStart,
      onSegmentStart: onSegmentStart,
    );
  }

  Future<void> stopSpeaking() async {
    await _geminiTts.stopSpeaking();
  }

  Future<void> playAudioUrl(
    String url, {
    int? expectedDurationMs,
    VoidCallback? onPlaybackStart,
  }) async {
    final normalized = url.trim();
    if (normalized.isEmpty) {
      throw Exception('재생할 오디오 URL이 비어 있습니다.');
    }
    await _geminiTts.playAudioUrl(
      normalized,
      expectedDurationMs: expectedDurationMs,
      onPlaybackStart: onPlaybackStart,
    );
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

  Future<void> _logRecordedFile(String event, File audioFile) async {
    final exists = await audioFile.exists();
    final size = exists ? await audioFile.length() : 0;
    debugPrint(
      '🎙️ [STT File] '
      'event=$event, '
      'recordPath=${audioFile.path}, '
      'fileExists=$exists, '
      'fileSize=$size',
    );
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
    final transportError = error.error?.toString();
    return '$label 요청에 실패했습니다'
        '${statusCode == null ? '' : ' (HTTP $statusCode)'}'
        ' [${error.type.name}]'
        '${error.message == null ? '' : ': ${error.message}'}'
        '${transportError == null ? '' : ' / $transportError'}'
        '${details.isEmpty ? '' : ': $details'}';
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
