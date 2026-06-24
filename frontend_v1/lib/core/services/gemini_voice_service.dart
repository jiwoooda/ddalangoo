import 'dart:async';
import 'dart:collection';
import 'dart:convert';
import 'dart:io';

import 'package:audioplayers/audioplayers.dart';
import 'package:crypto/crypto.dart';
import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart';
import 'package:path_provider/path_provider.dart';

import '../network/api_client.dart';
import '../utils/latency_logger.dart';

class GeminiVoiceService {
  static GeminiVoiceService? _instance;
  static GeminiVoiceService get instance =>
      _instance ??= GeminiVoiceService._();
  GeminiVoiceService._();

  static const String _backendTtsCacheVersion = 'backend_tts_v1';
  static const String _backendTtsEndpointPath = '/api/voice/tts';
  static const int _maxCachedTtsItems = 12;
  static const int _ttsRetryCount = 2;
  static const int _ttsSampleRate = 24000;
  static const Duration _ttsRetryBaseDelay = Duration(milliseconds: 800);

  final AudioPlayer _player = AudioPlayer();
  final LinkedHashMap<String, Uint8List> _ttsCache = LinkedHashMap();
  final Map<String, Future<Uint8List>> _ttsInFlight = {};

  StreamSubscription<void>? _playerCompleteSubscription;
  StreamSubscription<PlayerState>? _playerStateSubscription;
  Timer? _playbackFallbackTimer;
  Completer<void>? _speakCompleter;
  Future<Directory?>? _ttsCacheDirectoryFuture;
  LatencyRequestContext? _activeSpeakLatencyContext;
  bool _isSpeaking = false;
  bool _audioPlayEndLogged = false;

  bool get isSpeaking => _isSpeaking;

  Future<void> init() async {
    await _player.setReleaseMode(ReleaseMode.stop);
    if (!kIsWeb) {
      _ttsCacheDirectoryFuture ??= _prepareTtsCacheDirectory();
    }
  }

  Future<Uint8List> synthesizeSpeechToBytes(String text) async {
    final normalized = text.trim();
    if (normalized.isEmpty) {
      throw Exception('TTS 입력 텍스트가 비어 있습니다.');
    }
    return _getOrCreateSpeech(normalized);
  }

  Future<String> synthesizeSpeechToFile(String text) async {
    final normalized = text.trim();
    if (normalized.isEmpty) {
      throw Exception('TTS 입력 텍스트가 비어 있습니다.');
    }

    final wavBytes = await _getOrCreateSpeech(normalized);
    final source = await _createSpeechPlaybackSource(normalized, wavBytes);
    if (source is DeviceFileSource) {
      return source.path;
    }

    final directory = await getTemporaryDirectory();
    final file = File(
      '${directory.path}${Platform.pathSeparator}'
      'ddalangoo_tts_${DateTime.now().microsecondsSinceEpoch}.wav',
    );
    await file.writeAsBytes(wavBytes, flush: true);
    return file.path;
  }

  Future<void> prefetchSpeech(String text) async {
    final normalized = text.trim();
    if (normalized.isEmpty) return;
    try {
      await _getOrCreateSpeech(normalized);
    } catch (e) {
      debugPrint('⚠️ [Backend TTS Prefetch Error] "$normalized" $e');
    }
  }

  Future<void> prefetchMultiple(Iterable<String> texts) async {
    for (final text in texts) {
      await prefetchSpeech(text);
    }
  }

  Future<void> speak(
    String text, {
    LatencyRequestContext? latencyContext,
    VoidCallback? onPlaybackStart,
  }) async {
    if (_isSpeaking) await stopSpeaking();
    _isSpeaking = true;
    _audioPlayEndLogged = false;
    _activeSpeakLatencyContext = latencyContext;
    final speakCompleter = Completer<void>();
    _speakCompleter = speakCompleter;

    if (latencyContext != null) {
      FrontendLatencyLogger.instance.mark(
        latencyContext,
        'backend_tts_request_start',
      );
    }

    try {
      final wavBytes = await _getOrCreateSpeech(text.trim());
      final speechSource = await _createSpeechPlaybackSource(text, wavBytes);
      if (latencyContext != null) {
        FrontendLatencyLogger.instance.mark(
          latencyContext,
          'backend_tts_response_received',
        );
      }

      await _playerCompleteSubscription?.cancel();
      await _playerStateSubscription?.cancel();
      _playerCompleteSubscription = _player.onPlayerComplete.listen((_) {
        _markAudioPlayEnd();
        _finishSpeaking();
      });
      _playerStateSubscription = _player.onPlayerStateChanged.listen((state) {
        if (state == PlayerState.completed) {
          _markAudioPlayEnd();
          _finishSpeaking();
        }
      });
      _startPlaybackCompletionFallback(wavBytes);

      if (latencyContext != null) {
        FrontendLatencyLogger.instance.mark(latencyContext, 'audio_play_start');
      }
      onPlaybackStart?.call();
      debugPrint('[TTS] playback started');
      await _player.play(speechSource);
      await speakCompleter.future;
    } catch (e) {
      _finishSpeaking();
      rethrow;
    }
  }

  Future<void> stopSpeaking() async {
    await _player.stop();
    _markAudioPlayEnd();
    _finishSpeaking();
  }

  Future<void> dispose() async {
    await _playerCompleteSubscription?.cancel();
    await _playerStateSubscription?.cancel();
    _playbackFallbackTimer?.cancel();
    await _player.dispose();
  }

  Future<Uint8List> _getOrCreateSpeech(String text) async {
    final cacheKey = _buildTtsCacheKey(text);
    final cached = _ttsCache.remove(cacheKey);
    if (cached != null) {
      _ttsCache[cacheKey] = cached;
      debugPrint('🔵 [Backend TTS Cache Hit] "$text"');
      return cached;
    }

    final diskCached = await _readSpeechFromDisk(cacheKey);
    if (diskCached != null) {
      _rememberTtsCache(cacheKey, diskCached);
      debugPrint('🔵 [Backend TTS Disk Cache Hit] "$text"');
      return diskCached;
    }

    final inFlight = _ttsInFlight[cacheKey];
    if (inFlight != null) {
      return inFlight;
    }

    final future = _generateSpeechWithRetry(text);
    _ttsInFlight[cacheKey] = future;

    try {
      final wavBytes = await future;
      _rememberTtsCache(cacheKey, wavBytes);
      unawaited(_writeSpeechToDisk(cacheKey, wavBytes));
      return wavBytes;
    } finally {
      _ttsInFlight.remove(cacheKey);
    }
  }

  Future<Uint8List> _generateSpeechWithRetry(String text) async {
    var attempt = 0;
    while (true) {
      attempt += 1;
      try {
        return await _generateSpeech(text);
      } on DioException catch (e) {
        final statusCode = e.response?.statusCode;
        final isRetryable = statusCode == 429 || statusCode == 503;
        if (!isRetryable || attempt > _ttsRetryCount) {
          rethrow;
        }
        final delay = Duration(
          milliseconds: _ttsRetryBaseDelay.inMilliseconds * attempt,
        );
        await Future.delayed(delay);
      }
    }
  }

  Future<Uint8List> _generateSpeech(String text) async {
    debugPrint('[TTS] provider=backend');
    debugPrint('[TTS] requestUrl=${ApiClient.baseUrl}$_backendTtsEndpointPath');
    debugPrint('[TTS] textLength=${text.runes.length}');

    final response = await ApiClient.dio.post<Map<String, dynamic>>(
      _backendTtsEndpointPath,
      data: {'text': text},
      options: Options(
        contentType: Headers.jsonContentType,
        responseType: ResponseType.json,
      ),
    );

    final data = response.data;
    final encodedAudio = data?['audioBase64'];
    final mimeType = data?['mimeType'];
    if (encodedAudio is! String || encodedAudio.isEmpty) {
      throw Exception('백엔드 TTS 응답에서 오디오 데이터를 받지 못했습니다.');
    }

    final audioBytes = base64Decode(encodedAudio);
    if (audioBytes.isEmpty) {
      throw Exception('백엔드 TTS 오디오가 비어 있습니다.');
    }
    debugPrint(
      '[TTS] response mimeType=$mimeType audioBytes=${audioBytes.length}',
    );
    return audioBytes;
  }

  String _buildTtsCacheKey(String text) => '$_backendTtsCacheVersion|$text';

  void _rememberTtsCache(String cacheKey, Uint8List wavBytes) {
    _ttsCache.remove(cacheKey);
    _ttsCache[cacheKey] = wavBytes;
    while (_ttsCache.length > _maxCachedTtsItems) {
      _ttsCache.remove(_ttsCache.keys.first);
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
    } catch (e) {
      debugPrint('⚠️ [Backend TTS Cache Dir Error] $e');
      return null;
    }
  }

  Future<File?> _getCacheFile(String cacheKey) async {
    if (kIsWeb) return null;

    final directoryFuture = _ttsCacheDirectoryFuture ??=
        _prepareTtsCacheDirectory();
    final directory = await directoryFuture;
    if (directory == null) return null;

    return File(
      '${directory.path}${Platform.pathSeparator}${_hashCacheKey(cacheKey)}.wav',
    );
  }

  Future<Uint8List?> _readSpeechFromDisk(String cacheKey) async {
    try {
      final file = await _getCacheFile(cacheKey);
      if (file == null || !await file.exists()) return null;
      return await file.readAsBytes();
    } catch (e) {
      debugPrint('⚠️ [Backend TTS Disk Read Error] $e');
      return null;
    }
  }

  Future<void> _writeSpeechToDisk(String cacheKey, Uint8List wavBytes) async {
    try {
      final file = await _getCacheFile(cacheKey);
      if (file == null) return;
      await file.writeAsBytes(wavBytes, flush: true);
    } catch (e) {
      debugPrint('⚠️ [Backend TTS Disk Write Error] $e');
    }
  }

  String _hashCacheKey(String input) {
    return sha1.convert(utf8.encode(input)).toString();
  }

  Future<Source> _createSpeechPlaybackSource(
    String text,
    Uint8List wavBytes,
  ) async {
    if (kIsWeb) {
      return BytesSource(wavBytes);
    }

    final tempDirectory = await getTemporaryDirectory();
    final playbackFile = File(
      '${tempDirectory.path}${Platform.pathSeparator}'
      'ddalangoo_tts_playback_${_hashCacheKey(_buildTtsCacheKey(text))}.wav',
    );

    final shouldWrite =
        !await playbackFile.exists() ||
        await playbackFile.length() != wavBytes.length;
    if (shouldWrite) {
      await playbackFile.writeAsBytes(wavBytes, flush: true);
    }

    return DeviceFileSource(playbackFile.path);
  }

  void _startPlaybackCompletionFallback(Uint8List wavBytes) {
    _playbackFallbackTimer?.cancel();
    final expectedDuration = _estimateWavDuration(wavBytes);
    final fallbackDelay = expectedDuration + const Duration(milliseconds: 1800);
    _playbackFallbackTimer = Timer(fallbackDelay, () {
      if (!_isSpeaking) return;
      _markAudioPlayEnd();
      _finishSpeaking();
    });
  }

  Duration _estimateWavDuration(Uint8List wavBytes) {
    if (wavBytes.length <= 44) {
      return const Duration(seconds: 2);
    }

    final pcmLength = wavBytes.length - 44;
    const bytesPerSample = 2;
    final bytesPerSecond = _ttsSampleRate * bytesPerSample;
    final durationMs = ((pcmLength * 1000) / bytesPerSecond).ceil();
    return Duration(milliseconds: durationMs.clamp(1000, 30000));
  }

  void _finishSpeaking() {
    unawaited(_playerCompleteSubscription?.cancel());
    unawaited(_playerStateSubscription?.cancel());
    _playbackFallbackTimer?.cancel();
    _playbackFallbackTimer = null;
    _playerCompleteSubscription = null;
    _playerStateSubscription = null;
    _isSpeaking = false;
    _activeSpeakLatencyContext = null;
    _audioPlayEndLogged = false;
    if (_speakCompleter != null && !_speakCompleter!.isCompleted) {
      _speakCompleter!.complete();
    }
    _speakCompleter = null;
  }

  void _markAudioPlayEnd() {
    if (_audioPlayEndLogged) return;
    debugPrint('[TTS] playback ended');
    final latencyContext = _activeSpeakLatencyContext;
    if (latencyContext != null) {
      FrontendLatencyLogger.instance.mark(latencyContext, 'audio_play_end');
    }
    _audioPlayEndLogged = true;
  }
}
