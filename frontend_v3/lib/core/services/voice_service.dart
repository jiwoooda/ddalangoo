import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:audioplayers/audioplayers.dart';
import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart';
import 'package:path_provider/path_provider.dart';
import 'package:record/record.dart';

import '../network/api_client.dart';

class VoiceService {
  VoiceService._();

  static final VoiceService instance = VoiceService._();

  static const String _sttPath = '/api/voice/stt';
  static const String _ttsPath = '/api/voice/tts';
  static const int _sampleRate = 16000;
  static const int _numChannels = 1;

  final AudioPlayer _player = AudioPlayer();
  AudioRecorder? _recorder;
  String? _recordingPath;
  bool _isInitialized = false;
  bool _isRecording = false;
  bool _isSpeaking = false;

  bool get isRecording => _isRecording;
  bool get isSpeaking => _isSpeaking;

  AudioRecorder get _activeRecorder => _recorder ??= AudioRecorder();

  Future<void> init() async {
    if (_isInitialized) {
      return;
    }
    _isInitialized = true;
    await _player.setReleaseMode(ReleaseMode.stop);
  }

  Future<void> speak(String text) async {
    final normalized = text.trim();
    if (normalized.isEmpty) {
      return;
    }

    await init();
    await stopSpeaking();

    final response = await ApiClient.dio.post<Map<String, dynamic>>(
      _ttsPath,
      data: <String, dynamic>{'text': normalized},
      options: Options(
        contentType: Headers.jsonContentType,
        responseType: ResponseType.json,
      ),
    );

    final payload = response.data ?? const <String, dynamic>{};
    final encodedAudio = payload['audioBase64']?.toString();
    if (encodedAudio == null || encodedAudio.isEmpty) {
      throw Exception('TTS 응답에 오디오가 비어 있습니다.');
    }

    final audioBytes = base64Decode(encodedAudio);
    if (audioBytes.isEmpty) {
      throw Exception('TTS 오디오를 디코딩하지 못했습니다.');
    }

    final source = await _audioSourceFromBytes(audioBytes);
    _isSpeaking = true;
    try {
      await _player.play(source);
      await _player.onPlayerComplete.first;
    } finally {
      _isSpeaking = false;
    }
  }

  Future<void> stopSpeaking() async {
    _isSpeaking = false;
    await _player.stop();
  }

  Future<void> startRecording() async {
    await init();
    if (kIsWeb) {
      throw UnsupportedError('현재 음성 입력은 앱 환경에서만 지원합니다.');
    }

    if (_isRecording) {
      await cancelRecording();
    }

    final hasPermission = await _activeRecorder.hasPermission();
    if (!hasPermission) {
      throw Exception('마이크 권한이 필요합니다.');
    }

    final tempDir = await getTemporaryDirectory();
    final path =
        '${tempDir.path}${Platform.pathSeparator}voice_${DateTime.now().microsecondsSinceEpoch}.m4a';

    await _activeRecorder.start(
      const RecordConfig(
        encoder: AudioEncoder.aacLc,
        sampleRate: _sampleRate,
        numChannels: _numChannels,
        autoGain: false,
        echoCancel: false,
        noiseSuppress: false,
      ),
      path: path,
    );

    _recordingPath = path;
    _isRecording = true;
  }

  Future<String> stopRecordingAndTranscribe() async {
    if (!_isRecording) {
      throw Exception('현재 녹음 중이 아닙니다.');
    }

    _isRecording = false;
    final recordedPath = await _activeRecorder.stop() ?? _recordingPath;
    _recordingPath = null;
    if (recordedPath == null) {
      throw Exception('녹음 파일을 찾지 못했습니다.');
    }

    final file = File(recordedPath);
    if (!await file.exists()) {
      throw Exception('녹음 파일이 존재하지 않습니다.');
    }

    final formData = FormData.fromMap(<String, dynamic>{
      'file': await MultipartFile.fromFile(
        file.path,
        filename: file.uri.pathSegments.isNotEmpty
            ? file.uri.pathSegments.last
            : 'voice.m4a',
        contentType: DioMediaType.parse('audio/mp4'),
      ),
    });

    try {
      final response = await ApiClient.dio.post<Map<String, dynamic>>(
        _sttPath,
        data: formData,
        options: Options(
          contentType: 'multipart/form-data',
          responseType: ResponseType.json,
        ),
      );
      final transcript =
          response.data?['transcript']?.toString().trim() ??
          response.data?['text']?.toString().trim() ??
          '';
      return transcript;
    } finally {
      unawaited(_deleteIfExists(file.path));
    }
  }

  Future<void> cancelRecording() async {
    if (!_isRecording) {
      return;
    }

    _isRecording = false;
    final path = _recordingPath;
    _recordingPath = null;
    await _activeRecorder.cancel();
    if (path != null) {
      await _deleteIfExists(path);
    }
  }

  Future<void> dispose() async {
    await _player.dispose();
    final recorder = _recorder;
    _recorder = null;
    if (recorder != null) {
      await recorder.dispose();
    }
  }

  Future<Source> _audioSourceFromBytes(Uint8List bytes) async {
    if (kIsWeb) {
      return BytesSource(bytes);
    }

    final tempDir = await getTemporaryDirectory();
    final file = File(
      '${tempDir.path}${Platform.pathSeparator}tts_${DateTime.now().microsecondsSinceEpoch}.wav',
    );
    await file.writeAsBytes(bytes, flush: true);
    return DeviceFileSource(file.path);
  }

  Future<void> _deleteIfExists(String path) async {
    try {
      final file = File(path);
      if (await file.exists()) {
        await file.delete();
      }
    } catch (_) {}
  }
}
