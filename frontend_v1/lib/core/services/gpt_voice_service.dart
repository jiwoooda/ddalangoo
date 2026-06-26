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
  static const Duration _defaultRecordingStartCooldown = Duration(
    milliseconds: 260,
  );
  static const Duration _androidRecordingStartCooldown = Duration(
    milliseconds: 240,
  );

  // STT 프롬프트는 백엔드 voice_service.py에서 관리한다.

  AudioRecorder? _recorder;
  final GeminiVoiceService _geminiTts = GeminiVoiceService.instance;
  Future<Directory?>? _sttRecordingDirectoryFuture;
  String? _activeRecordingPath;
  bool _isRecording = false;
  DateTime? _lastRecordingStartedAt;

  bool get isRecording => _isRecording;
  bool get isSpeaking => _geminiTts.isSpeaking;
  DateTime? get lastTtsPlaybackEndedAt => _geminiTts.lastPlaybackEndedAt;
  DateTime? get lastRecordingStartedAt => _lastRecordingStartedAt;
  bool get _supportsFileAudioFlow => !kIsWeb;
  AudioRecorder get _activeRecorder => _recorder ??= AudioRecorder();
  Duration get _recordingStartCooldown {
    if (Platform.isAndroid) {
      return _androidRecordingStartCooldown;
    }
    return _defaultRecordingStartCooldown;
  }

  AudioEncoder get _preferredRecordingEncoder {
    if (Platform.isAndroid || Platform.isIOS || Platform.isMacOS) {
      return AudioEncoder.aacLc;
    }
    return AudioEncoder.wav;
  }

  Stream<Amplitude> onAmplitudeChanged({
    Duration interval = const Duration(milliseconds: 180),
  }) {
    _ensureRecordingSupported();
    return _activeRecorder.onAmplitudeChanged(interval);
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
    final requestedAt = DateTime.now();
    debugPrint(
      '🎙️ [STT] recording_start_requested '
      'at=${requestedAt.toIso8601String()} '
      'deltaSinceTtsEndMs=${_elapsedMsSince(lastTtsPlaybackEndedAt, requestedAt)} '
      'cooldownMs=${_recordingStartCooldown.inMilliseconds}',
    );
    if (_isRecording) {
      debugPrint(
        '🎙️ [STT] startRecording requested while already recording, resetting recorder',
      );
      await cancelRecording();
    }

    // 직전 TTS 재생이 끝났더라도 오디오 포커스/세션 정리가 지연될 수 있어
    // 바로 녹음을 시작하면 후속 턴에서 무음 파일이 생기기도 한다.
    await _geminiTts.stopSpeaking();
    final stopSpeakingCompletedAt = DateTime.now();
    debugPrint(
      '🎙️ [STT] tts_stop_confirmed '
      'at=${stopSpeakingCompletedAt.toIso8601String()} '
      'deltaSinceTtsEndMs=${_elapsedMsSince(lastTtsPlaybackEndedAt, stopSpeakingCompletedAt)}',
    );
    await Future<void>.delayed(_recordingStartCooldown);
    final cooldownEndedAt = DateTime.now();
    debugPrint(
      '🎙️ [STT] recording_cooldown_elapsed '
      'at=${cooldownEndedAt.toIso8601String()} '
      'deltaSinceTtsEndMs=${_elapsedMsSince(lastTtsPlaybackEndedAt, cooldownEndedAt)}',
    );

    final recorder = _activeRecorder;
    final hasPermission = await recorder.hasPermission();
    if (!hasPermission) {
      throw Exception('브라우저/기기에서 마이크 권한이 허용되지 않았습니다.');
    }

    try {
      final encoder = await _resolveRecordingEncoder(recorder);
      final path = await _createSttRecordingPath(
        extension: _extensionForEncoder(encoder),
      );
      _activeRecordingPath = path;
      await _startRecorderWithRetry(
        recorder: recorder,
        encoder: encoder,
        path: path,
      );
      _lastRecordingStartedAt = DateTime.now();
      _isRecording = true;
      debugPrint(
        '🎙️ [STT] recording_started '
        'at=${_lastRecordingStartedAt!.toIso8601String()} '
        'deltaSinceTtsEndMs=${_elapsedMsSince(lastTtsPlaybackEndedAt, _lastRecordingStartedAt!)} '
        'path=$path '
        'encoder=${encoder.name} '
        'mimeType=${_mimeTypeForEncoder(encoder)}',
      );
    } catch (e) {
      _isRecording = false;
      _activeRecordingPath = null;
      _lastRecordingStartedAt = null;
      debugPrint('❌ [STT] recording_start_failed error=$e');
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
      final recorder = _activeRecorder;
      final recordedPath = await recorder.stop();
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
      _lastRecordingStartedAt = null;
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
      final inferredMimeType = _inferMimeTypeFromPath(audioFile.path);
      await _logRecordedFile('stt_request_prepare', audioFile);
      final formData = FormData.fromMap({
        _sttMultipartFieldName: await MultipartFile.fromFile(
          audioFile.path,
          filename: audioFile.uri.pathSegments.isNotEmpty
              ? audioFile.uri.pathSegments.last
              : 'voice.${_extensionFromMimeType(inferredMimeType)}',
          contentType: DioMediaType.parse(inferredMimeType),
        ),
      });

      debugPrint(
        '🎙️ [STT Request] '
        'requestUrl=${ApiClient.baseUrl}$_sttEndpointPath, '
        'multipartFieldName=$_sttMultipartFieldName, '
        'mimeType=$inferredMimeType, '
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
    await _disposeRecorder();
  }

  Future<void> cancelRecording() async {
    _ensureRecordingSupported();
    if (!_isRecording) return;

    _isRecording = false;
    final path = _activeRecordingPath;
    _activeRecordingPath = null;
    _lastRecordingStartedAt = null;
    debugPrint('🎙️ [STT] recording_cancel_requested path=$path');
    await _activeRecorder.cancel();
    if (path != null) {
      await _deleteIfExists(path);
    }
  }

  Future<void> _disposeRecorder() async {
    final recorder = _recorder;
    _recorder = null;
    if (recorder == null) {
      return;
    }
    try {
      await recorder.dispose();
    } catch (_) {}
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

  Future<String> _createSttRecordingPath({required String extension}) async {
    final directoryFuture = _sttRecordingDirectoryFuture ??=
        _prepareSttRecordingDirectory();
    final directory = await directoryFuture;
    if (directory == null) {
      throw Exception('STT 임시 녹음 디렉터리를 준비하지 못했습니다.');
    }

    final now = DateTime.now().microsecondsSinceEpoch;
    return '${directory.path}${Platform.pathSeparator}stt_$now.$extension';
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
      'mimeType=${_inferMimeTypeFromPath(audioFile.path)}, '
      'fileExists=$exists, '
      'fileSize=$size',
    );
  }

  Future<void> _startRecorderWithRetry({
    required AudioRecorder recorder,
    required AudioEncoder encoder,
    required String path,
  }) async {
    final config = _buildRecordingConfig(encoder);
    try {
      await recorder.start(config, path: path);
      return;
    } catch (error) {
      debugPrint('⚠️ [STT] recorder_start_retry_recreate error=$error');
      await _disposeRecorder();
      final retryRecorder = _activeRecorder;
      await retryRecorder.start(config, path: path);
    }
  }

  Future<AudioEncoder> _resolveRecordingEncoder(AudioRecorder recorder) async {
    final preferred = _preferredRecordingEncoder;
    try {
      if (await recorder.isEncoderSupported(preferred)) {
        return preferred;
      }
      if (preferred != AudioEncoder.wav &&
          await recorder.isEncoderSupported(AudioEncoder.wav)) {
        debugPrint(
          '🎙️ [STT] preferred encoder unsupported, falling back to wav',
        );
        return AudioEncoder.wav;
      }
    } catch (e) {
      debugPrint('⚠️ [STT] encoder_support_check_failed error=$e');
    }
    return preferred;
  }

  RecordConfig _buildRecordingConfig(AudioEncoder encoder) {
    final androidConfig = Platform.isAndroid
        ? const AndroidRecordConfig(
            // Android 에뮬레이터/일부 기기에서 기본 고급 recorder가
            // 무음 또는 깨진 입력을 만드는 경우가 있어 안정성 우선으로 둔다.
            useLegacy: true,
            // 에뮬레이터에서 voiceRecognition 라우팅이 후속 턴에
            // 0 샘플만 반환하는 경우가 있어 기본 MIC 라우팅으로 되돌린다.
            audioSource: AndroidAudioSource.mic,
          )
        : const AndroidRecordConfig();

    return RecordConfig(
      // Android 일부 환경에서는 WAV가 포화된 톤처럼 저장되는 경우가 있어
      // 우선 하드웨어 지원이 안정적인 AAC 컨테이너를 선호한다.
      encoder: encoder,
      sampleRate: _sampleRate,
      numChannels: _numChannels,
      // 에뮬레이터/일부 기기에서는 DSP 옵션이 원본 음성을 심하게 왜곡해
      // 진동음처럼 저장되는 경우가 있어 우선 생(raw) 캡처에 가깝게 둔다.
      autoGain: false,
      echoCancel: false,
      noiseSuppress: false,
      androidConfig: androidConfig,
    );
  }

  String _extensionForEncoder(AudioEncoder encoder) {
    switch (encoder) {
      case AudioEncoder.aacLc:
      case AudioEncoder.aacEld:
      case AudioEncoder.aacHe:
        return 'm4a';
      case AudioEncoder.amrNb:
      case AudioEncoder.amrWb:
        return '3gp';
      case AudioEncoder.opus:
        return 'opus';
      case AudioEncoder.flac:
        return 'flac';
      case AudioEncoder.wav:
        return 'wav';
      case AudioEncoder.pcm16bits:
        return 'pcm';
    }
  }

  String _mimeTypeForEncoder(AudioEncoder encoder) {
    switch (encoder) {
      case AudioEncoder.aacLc:
      case AudioEncoder.aacEld:
      case AudioEncoder.aacHe:
        return 'audio/mp4';
      case AudioEncoder.amrNb:
      case AudioEncoder.amrWb:
        return 'audio/3gpp';
      case AudioEncoder.opus:
        return 'audio/ogg';
      case AudioEncoder.flac:
        return 'audio/flac';
      case AudioEncoder.wav:
        return 'audio/wav';
      case AudioEncoder.pcm16bits:
        return 'audio/pcm';
    }
  }

  String _inferMimeTypeFromPath(String path) {
    final lowerPath = path.toLowerCase();
    if (lowerPath.endsWith('.m4a') || lowerPath.endsWith('.mp4')) {
      return 'audio/mp4';
    }
    if (lowerPath.endsWith('.mp3')) {
      return 'audio/mpeg';
    }
    if (lowerPath.endsWith('.webm')) {
      return 'audio/webm';
    }
    if (lowerPath.endsWith('.ogg') || lowerPath.endsWith('.opus')) {
      return 'audio/ogg';
    }
    if (lowerPath.endsWith('.flac')) {
      return 'audio/flac';
    }
    if (lowerPath.endsWith('.pcm')) {
      return 'audio/pcm';
    }
    return 'audio/wav';
  }

  String _extensionFromMimeType(String mimeType) {
    switch (mimeType) {
      case 'audio/mp4':
        return 'm4a';
      case 'audio/mpeg':
        return 'mp3';
      case 'audio/webm':
        return 'webm';
      case 'audio/ogg':
        return 'ogg';
      case 'audio/flac':
        return 'flac';
      case 'audio/pcm':
        return 'pcm';
      case 'audio/wav':
      default:
        return 'wav';
    }
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

  int _elapsedMsSince(DateTime? since, DateTime now) {
    if (since == null) {
      return -1;
    }
    return now.difference(since).inMilliseconds;
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
