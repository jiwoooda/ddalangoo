import 'dart:async';
import 'dart:collection';
import 'dart:convert';
import 'dart:io';

import 'package:audioplayers/audioplayers.dart';
import 'package:crypto/crypto.dart';
import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter_tts/flutter_tts.dart';
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
  // Gemini TTS quota가 회복되기 전까지 백엔드 TTS 요청 자체를 보내지 않고
  // 기기 내장 TTS만 사용한다. quota가 회복되면 false로 되돌리면 된다.
  static const bool _forceDeviceFallbackTts = true;

  // 백엔드 TTS 응답(오디오 바이트) 캐시. 온보딩/스몰토크 대사는 상당수가
  // 고정 문구라 같은 문장을 반복 재생할 때 매번 새로 네트워크를 타지 않도록
  // 메모리(LRU) → 디스크 순으로 캐시를 둔다. front_v2의 gemini_voice_service
  // 캐시 구조를 참고해 v3의 단순 audioBase64 응답 형태에 맞게 옮겼다.
  static const String _ttsCacheVersion = 'backend_tts_v1';
  static const int _maxMemoryCachedTtsItems = 16;

  final AudioPlayer _player = AudioPlayer();
  final FlutterTts _fallbackTts = FlutterTts();
  final LinkedHashMap<String, Uint8List> _ttsMemoryCache = LinkedHashMap();
  // 같은 문장에 대해 speak()가 짧은 시간 안에 중복 호출돼도(예: 위젯 재빌드,
  // 실수로 두 번 트리거) 네트워크 요청이 두 번 나가지 않도록 진행 중인
  // Future를 공유한다.
  final Map<String, Future<Uint8List>> _ttsInFlight = {};
  Future<Directory?>? _ttsCacheDirectoryFuture;
  AudioRecorder? _recorder;
  String? _recordingPath;
  bool _isInitialized = false;
  bool _isFallbackTtsReady = false;
  bool _isRecording = false;
  bool _isSpeaking = false;

  bool get isRecording => _isRecording;
  bool get isSpeaking => _isSpeaking;

  AudioRecorder get _activeRecorder => _recorder ??= AudioRecorder();

  // AudioPlayer(오디오 재생 플러그인)의 모든 메서드는 네이티브 플랫폼 채널을
  // 거치는 Future다. 에뮬레이터 등 오디오 출력이 불안정한 환경에서는 이
  // 채널 호출 자체가 콜백을 못 받고 영원히 끝나지 않는 경우가 있다(오류를
  // 던지지도 않음). 이런 지점을 그대로 await하면 _isSpeaking이 계속 true로
  // 남아 마이크 버튼이 영구히 멈춘 것처럼 보인다. 아래처럼 모든 네이티브
  // 호출에 타임아웃을 걸어 최악의 경우에도 반드시 회복되게 한다.
  static const _nativeCallTimeout = Duration(seconds: 8);

  Future<void> init() async {
    if (_isInitialized) {
      return;
    }
    _isInitialized = true;
    debugPrint('[VoiceService] init: setReleaseMode start');
    try {
      await _player
          .setReleaseMode(ReleaseMode.stop)
          .timeout(_nativeCallTimeout);
      debugPrint('[VoiceService] init: setReleaseMode done');
    } on TimeoutException {
      debugPrint(
        '[VoiceService] init: setReleaseMode TIMED OUT — 오디오 플러그인이 '
        '응답하지 않습니다(에뮬레이터 오디오 문제일 수 있음).',
      );
    } catch (error) {
      debugPrint('[VoiceService] init: setReleaseMode failed error=$error');
    }
  }

  Future<void> speak(String text) async {
    final normalized = text.trim();
    if (normalized.isEmpty) {
      return;
    }

    debugPrint('[VoiceService] speak: init start');
    await init();
    debugPrint('[VoiceService] speak: stopSpeaking start');
    await stopSpeaking();

    if (_forceDeviceFallbackTts) {
      debugPrint(
        '[VoiceService] speak: backend TTS skipped by force fallback flag',
      );
      await _speakViaDeviceFallback(normalized);
      return;
    }

    // 백엔드 TTS(서버에서 오디오 파일을 만들어 내려주는 방식)가 응답을 못 주거나
    // (연결 타임아웃 등), 응답은 왔는데 재생 자체가 실패하는 경우 등 어떤
    // 이유로든 실패하면, 완전히 무음으로 끝나는 대신 기기에 내장된
    // flutter_tts(OS 기본 음성 엔진)로 대신 읽어준다. 품질은 서버 TTS보다
    // 떨어지지만, 사용자 입장에서는 "아예 말을 안 하는 것"보다 훨씬 낫다.
    try {
      await _speakViaBackend(normalized);
    } catch (error) {
      debugPrint(
        '[VoiceService] speak: backend TTS failed, falling back to '
        'on-device TTS error=$error',
      );
      await _speakViaDeviceFallback(normalized);
    }
  }

  Future<void> _speakViaBackend(String normalized) async {
    final audioBytes = await _getOrFetchTtsAudio(normalized);
    final source = await _audioSourceFromBytes(audioBytes);
    _isSpeaking = true;
    try {
      debugPrint('[VoiceService] speak: player.play start');
      try {
        await _player.play(source).timeout(_nativeCallTimeout);
        debugPrint('[VoiceService] speak: player.play returned');
      } on TimeoutException {
        debugPrint(
          '[VoiceService] speak: player.play TIMED OUT — 재생 시작 자체가 '
          '응답하지 않습니다.',
        );
        throw TimeoutException('player.play did not return');
      }
      // 일부 기기/오디오 경로에서는 재생이 멈추거나 포커스를 잃어도
      // onPlayerComplete 이벤트가 아예 발생하지 않을 수 있다. 그 경우
      // 이 await가 영원히 끝나지 않아 _isSpeaking이 계속 true로 남고,
      // 결과적으로 마이크 버튼이 영구히 비활성 상태로 멈추게 된다.
      // 타임아웃을 걸어 최악의 경우에도 UI가 반드시 회복되게 한다.
      try {
        await _player.onPlayerComplete.first.timeout(
          const Duration(seconds: 30),
        );
        debugPrint('[VoiceService] speak: onPlayerComplete fired');
      } on TimeoutException {
        debugPrint(
          '[VoiceService] speak: onPlayerComplete TIMED OUT after 30s',
        );
        await _player.stop().timeout(
          _nativeCallTimeout,
          onTimeout: () {
            debugPrint('[VoiceService] speak: recovery player.stop TIMED OUT');
          },
        );
      }
    } finally {
      _isSpeaking = false;
    }
  }

  /// 메모리 캐시 → 디스크 캐시 → (진행 중인 동일 요청 합류) → 네트워크 순으로
  /// TTS 오디오 바이트를 가져온다.
  Future<Uint8List> _getOrFetchTtsAudio(String text) async {
    final cacheKey = _buildTtsCacheKey(text);

    final memoryCached = _ttsMemoryCache.remove(cacheKey);
    if (memoryCached != null) {
      // LinkedHashMap에 다시 넣어 가장 최근 사용 항목으로 순서를 갱신한다(LRU).
      _ttsMemoryCache[cacheKey] = memoryCached;
      debugPrint('[VoiceService] TTS memory cache hit text="$text"');
      return memoryCached;
    }

    final diskCached = await _readTtsAudioFromDisk(cacheKey);
    if (diskCached != null) {
      _rememberTtsMemoryCache(cacheKey, diskCached);
      debugPrint('[VoiceService] TTS disk cache hit text="$text"');
      return diskCached;
    }

    final inFlight = _ttsInFlight[cacheKey];
    if (inFlight != null) {
      debugPrint('[VoiceService] TTS request already in flight, joining text="$text"');
      return inFlight;
    }

    final future = _fetchTtsAudioFromBackend(text);
    _ttsInFlight[cacheKey] = future;
    try {
      final audioBytes = await future;
      _rememberTtsMemoryCache(cacheKey, audioBytes);
      unawaited(_writeTtsAudioToDisk(cacheKey, audioBytes));
      return audioBytes;
    } finally {
      _ttsInFlight.remove(cacheKey);
    }
  }

  Future<Uint8List> _fetchTtsAudioFromBackend(String normalized) async {
    debugPrint('[VoiceService] speak: TTS request start text="$normalized"');

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
    return audioBytes;
  }

  String _buildTtsCacheKey(String text) => '$_ttsCacheVersion|$text';

  void _rememberTtsMemoryCache(String cacheKey, Uint8List audioBytes) {
    _ttsMemoryCache.remove(cacheKey);
    _ttsMemoryCache[cacheKey] = audioBytes;
    while (_ttsMemoryCache.length > _maxMemoryCachedTtsItems) {
      _ttsMemoryCache.remove(_ttsMemoryCache.keys.first);
    }
  }

  Future<Directory?> _prepareTtsCacheDirectory() async {
    try {
      final baseDirectory = await getApplicationSupportDirectory();
      final cacheDirectory = Directory(
        '${baseDirectory.path}${Platform.pathSeparator}tts_cache',
      );
      if (!await cacheDirectory.exists()) {
        await cacheDirectory.create(recursive: true);
      }
      return cacheDirectory;
    } catch (error) {
      debugPrint('[VoiceService] TTS cache dir prepare failed error=$error');
      return null;
    }
  }

  Future<File?> _ttsDiskCacheFile(String cacheKey) async {
    if (kIsWeb) {
      return null;
    }
    final directoryFuture = _ttsCacheDirectoryFuture ??=
        _prepareTtsCacheDirectory();
    final directory = await directoryFuture;
    if (directory == null) {
      return null;
    }
    final hashed = sha1.convert(utf8.encode(cacheKey)).toString();
    return File('${directory.path}${Platform.pathSeparator}$hashed.audio');
  }

  Future<Uint8List?> _readTtsAudioFromDisk(String cacheKey) async {
    try {
      final file = await _ttsDiskCacheFile(cacheKey);
      if (file == null || !await file.exists()) {
        return null;
      }
      return await file.readAsBytes();
    } catch (error) {
      debugPrint('[VoiceService] TTS disk cache read failed error=$error');
      return null;
    }
  }

  Future<void> _writeTtsAudioToDisk(String cacheKey, Uint8List audioBytes) async {
    try {
      final file = await _ttsDiskCacheFile(cacheKey);
      if (file == null) {
        return;
      }
      await file.writeAsBytes(audioBytes, flush: true);
    } catch (error) {
      debugPrint('[VoiceService] TTS disk cache write failed error=$error');
    }
  }

  Future<void> _ensureFallbackTtsReady() async {
    if (_isFallbackTtsReady) {
      return;
    }
    try {
      await _fallbackTts.awaitSpeakCompletion(true);
      await _fallbackTts.setLanguage('ko-KR');
      await _fallbackTts.setSpeechRate(0.48);
      await _fallbackTts.setVolume(1.0);
      await _fallbackTts.setPitch(1.0);
      _isFallbackTtsReady = true;
      debugPrint('[VoiceService] fallback tts ready');
    } catch (error) {
      debugPrint('[VoiceService] fallback tts setup failed error=$error');
    }
  }

  Future<void> _speakViaDeviceFallback(String normalized) async {
    await _ensureFallbackTtsReady();
    _isSpeaking = true;
    try {
      debugPrint('[VoiceService] speak: fallback flutter_tts start');
      // awaitSpeakCompletion(true)로 설정해뒀기 때문에 speak()의 Future는
      // 실제로 읽기가 끝나야 완료된다. 기기 TTS 엔진도 드물게 콜백 없이
      // 멈출 수 있으므로 다른 네이티브 호출과 동일하게 타임아웃을 둔다.
      await _fallbackTts.speak(normalized).timeout(
        const Duration(seconds: 30),
        onTimeout: () {
          debugPrint('[VoiceService] speak: fallback flutter_tts TIMED OUT');
          return 1;
        },
      );
      debugPrint('[VoiceService] speak: fallback flutter_tts finished');
    } catch (error) {
      debugPrint('[VoiceService] speak: fallback flutter_tts failed error=$error');
    } finally {
      _isSpeaking = false;
    }
  }

  Future<void> stopSpeaking() async {
    _isSpeaking = false;
    try {
      await _player.stop().timeout(_nativeCallTimeout);
    } on TimeoutException {
      debugPrint('[VoiceService] stopSpeaking: player.stop TIMED OUT');
    }
    try {
      await _fallbackTts.stop();
    } catch (_) {
      // 기기 TTS가 초기화되기 전이거나 이미 멈춰있으면 무시한다.
    }
  }

  Future<void> startRecording() async {
    await init();
    debugPrint('[VoiceService] startRecording requested');
    if (kIsWeb) {
      debugPrint('[VoiceService] startRecording blocked: web unsupported');
      throw UnsupportedError('현재 음성 입력은 앱 환경에서만 지원합니다.');
    }

    if (_isRecording) {
      debugPrint('[VoiceService] startRecording while recording; cancel previous');
      await cancelRecording();
    }

    final hasPermission = await _activeRecorder.hasPermission();
    debugPrint('[VoiceService] microphone permission=$hasPermission');
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
    debugPrint('[VoiceService] recording started path=$path');
  }

  Future<String> stopRecordingAndTranscribe() async {
    debugPrint('[VoiceService] stopRecordingAndTranscribe requested');
    if (!_isRecording) {
      debugPrint('[VoiceService] stopRecording blocked: not recording');
      throw Exception('현재 녹음 중이 아닙니다.');
    }

    _isRecording = false;
    final recordedPath = await _activeRecorder.stop() ?? _recordingPath;
    _recordingPath = null;
    debugPrint('[VoiceService] recorder stopped path=$recordedPath');
    if (recordedPath == null) {
      throw Exception('녹음 파일을 찾지 못했습니다.');
    }

    final file = File(recordedPath);
    if (!await file.exists()) {
      debugPrint('[VoiceService] recorded file missing path=$recordedPath');
      throw Exception('녹음 파일이 존재하지 않습니다.');
    }
    final fileSize = await file.length();
    debugPrint('[VoiceService] recorded file ready size=$fileSize path=$recordedPath');

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
      debugPrint('[VoiceService] STT request started path=$_sttPath size=$fileSize');
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
      debugPrint(
        '[VoiceService] STT request succeeded status=${response.statusCode} '
        'transcriptLength=${transcript.length} transcript="$transcript"',
      );
      return transcript;
    } catch (error, stackTrace) {
      debugPrint('[VoiceService] STT request failed error=$error');
      debugPrintStack(stackTrace: stackTrace, label: '[VoiceService] STT stack');
      rethrow;
    } finally {
      debugPrint('[VoiceService] deleting recorded file path=${file.path}');
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
    debugPrint('[VoiceService] cancelRecording path=$path');
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
