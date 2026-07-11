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

class TtsSegmentData {
  const TtsSegmentData({required this.text, required this.durationMs});

  final String text;
  final int durationMs;
}

class TtsPlaybackData {
  const TtsPlaybackData({
    required this.audioBytes,
    required this.segments,
    required this.totalDurationMs,
  });

  final Uint8List audioBytes;
  final List<TtsSegmentData> segments;
  final int totalDurationMs;
}

class GeminiVoiceService {
  static GeminiVoiceService? _instance;
  static GeminiVoiceService get instance =>
      _instance ??= GeminiVoiceService._();
  GeminiVoiceService._();

  static const String _backendTtsCacheVersion = 'backend_tts_v2_segmented';
  static const String _backendTtsEndpointPath = '/api/voice/tts';
  static const int _maxCachedTtsItems = 12;
  static const int _ttsRetryCount = 2;
  static const int _ttsSampleRate = 24000;
  static const Duration _ttsRetryBaseDelay = Duration(milliseconds: 800);
  static const double _ttsPlaybackRate = 1.0;

  final AudioPlayer _player = AudioPlayer();
  final LinkedHashMap<String, Uint8List> _ttsCache = LinkedHashMap();
  final LinkedHashMap<String, List<TtsSegmentData>> _ttsSegmentsCache =
      LinkedHashMap();
  final Map<String, Future<TtsPlaybackData>> _ttsBundleInFlight = {};

  StreamSubscription<void>? _playerCompleteSubscription;
  StreamSubscription<PlayerState>? _playerStateSubscription;
  Timer? _playbackFallbackTimer;
  Completer<void>? _speakCompleter;
  final List<Timer> _segmentTimers = [];
  Future<Directory?>? _ttsCacheDirectoryFuture;
  LatencyRequestContext? _activeSpeakLatencyContext;
  bool _isSpeaking = false;
  bool _audioPlayEndLogged = false;
  DateTime? _playbackStartedAt;
  DateTime? _lastPlaybackEndedAt;

  bool get isSpeaking => _isSpeaking;
  DateTime? get lastPlaybackEndedAt => _lastPlaybackEndedAt;

  Future<void> init() async {
    await _player.setReleaseMode(ReleaseMode.stop);
    await _player.setPlaybackRate(_ttsPlaybackRate);
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
    await speakWithSegments(
      text,
      latencyContext: latencyContext,
      onPlaybackStart: onPlaybackStart,
    );
  }

  Future<void> playAudioUrl(
    String url, {
    int? expectedDurationMs,
    VoidCallback? onPlaybackStart,
  }) async {
    if (_isSpeaking) await stopSpeaking();
    _isSpeaking = true;
    _audioPlayEndLogged = false;
    _activeSpeakLatencyContext = null;
    final speakCompleter = Completer<void>();
    _speakCompleter = speakCompleter;

    await _playerCompleteSubscription?.cancel();
    await _playerStateSubscription?.cancel();
    _playerCompleteSubscription = _player.onPlayerComplete.listen((_) {
      _handlePlaybackCompletion(expectedDurationMs);
    });
    _playerStateSubscription = _player.onPlayerStateChanged.listen((state) {
      if (state == PlayerState.completed) {
        _handlePlaybackCompletion(expectedDurationMs);
      }
    });
    if (expectedDurationMs != null) {
      _startPlaybackCompletionFallback(expectedDurationMs);
    } else {
      _playbackFallbackTimer?.cancel();
    }

    _playbackStartedAt = DateTime.now();
    onPlaybackStart?.call();
    debugPrint(
      '[TTS] remote segment playback started '
      'at=${_playbackStartedAt!.toIso8601String()} '
      'url=$url',
    );
    final source = await _createRemotePlaybackSource(url);
    await _player.setPlaybackRate(_ttsPlaybackRate);
    await _player.play(source);
    await speakCompleter.future;
  }

  Future<void> speakWithSegments(
    String text, {
    LatencyRequestContext? latencyContext,
    VoidCallback? onPlaybackStart,
    ValueChanged<TtsSegmentData>? onSegmentStart,
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
      final playbackData = await _getOrCreateSpeechBundle(text.trim());
      final wavBytes = playbackData.audioBytes;
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
        _handlePlaybackCompletion(playbackData.totalDurationMs);
      });
      _playerStateSubscription = _player.onPlayerStateChanged.listen((state) {
        if (state == PlayerState.completed) {
          _handlePlaybackCompletion(playbackData.totalDurationMs);
        }
      });
      _startPlaybackCompletionFallback(playbackData.totalDurationMs);
      _scheduleSegmentCallbacks(
        playbackData.segments,
        onSegmentStart: onSegmentStart,
      );

      if (latencyContext != null) {
        FrontendLatencyLogger.instance.mark(latencyContext, 'audio_play_start');
      }
      onPlaybackStart?.call();
      _playbackStartedAt = DateTime.now();
      debugPrint(
        '[TTS] playback started at=${_playbackStartedAt!.toIso8601String()}',
      );
      await _player.setPlaybackRate(_ttsPlaybackRate);
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
    final playbackData = await _getOrCreateSpeechBundle(text);
    return playbackData.audioBytes;
  }

  Future<TtsPlaybackData> _getOrCreateSpeechBundle(String text) async {
    final cacheKey = _buildTtsCacheKey(text);
    final cached = _ttsCache.remove(cacheKey);
    if (cached != null) {
      _ttsCache[cacheKey] = cached;
      final cachedSegments = _touchSegmentsCache(cacheKey);
      debugPrint('🔵 [Backend TTS Cache Hit] "$text"');
      return TtsPlaybackData(
        audioBytes: cached,
        segments: cachedSegments ?? _fallbackSegments(text, cached),
        totalDurationMs: _estimateWavDuration(cached).inMilliseconds,
      );
    }

    final diskCached = await _readSpeechFromDisk(cacheKey);
    if (diskCached != null) {
      _rememberTtsCache(cacheKey, diskCached);
      final cachedSegments = _touchSegmentsCache(cacheKey);
      debugPrint('🔵 [Backend TTS Disk Cache Hit] "$text"');
      return TtsPlaybackData(
        audioBytes: diskCached,
        segments: cachedSegments ?? _fallbackSegments(text, diskCached),
        totalDurationMs: _estimateWavDuration(diskCached).inMilliseconds,
      );
    }

    final inFlight = _ttsBundleInFlight[cacheKey];
    if (inFlight != null) {
      return inFlight;
    }

    final future = _generateSpeechBundleWithRetry(text);
    _ttsBundleInFlight[cacheKey] = future;

    try {
      final playbackData = await future;
      _rememberTtsCache(cacheKey, playbackData.audioBytes);
      _rememberSegmentsCache(cacheKey, playbackData.segments);
      unawaited(_writeSpeechToDisk(cacheKey, playbackData.audioBytes));
      return playbackData;
    } finally {
      _ttsBundleInFlight.remove(cacheKey);
    }
  }

  Future<TtsPlaybackData> _generateSpeechBundleWithRetry(String text) async {
    var attempt = 0;
    while (true) {
      attempt += 1;
      try {
        return await _generateSpeechBundle(text);
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

  Future<TtsPlaybackData> _generateSpeechBundle(String text) async {
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
    final segments = _parseSegments(data, text, audioBytes);
    final totalDurationMs =
        _toInt(data?['totalDurationMs']) ??
        segments.fold<int>(0, (sum, segment) => sum + segment.durationMs);
    return TtsPlaybackData(
      audioBytes: audioBytes,
      segments: segments,
      totalDurationMs: totalDurationMs > 0
          ? totalDurationMs
          : _estimateWavDuration(audioBytes).inMilliseconds,
    );
  }

  String _buildTtsCacheKey(String text) => '$_backendTtsCacheVersion|$text';

  void _rememberTtsCache(String cacheKey, Uint8List wavBytes) {
    _ttsCache.remove(cacheKey);
    _ttsCache[cacheKey] = wavBytes;
    while (_ttsCache.length > _maxCachedTtsItems) {
      _ttsCache.remove(_ttsCache.keys.first);
    }
  }

  void _rememberSegmentsCache(String cacheKey, List<TtsSegmentData> segments) {
    _ttsSegmentsCache.remove(cacheKey);
    _ttsSegmentsCache[cacheKey] = segments;
    while (_ttsSegmentsCache.length > _maxCachedTtsItems) {
      _ttsSegmentsCache.remove(_ttsSegmentsCache.keys.first);
    }
  }

  List<TtsSegmentData>? _touchSegmentsCache(String cacheKey) {
    final cached = _ttsSegmentsCache.remove(cacheKey);
    if (cached == null) return null;
    _ttsSegmentsCache[cacheKey] = cached;
    return cached;
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

    await playbackFile.writeAsBytes(wavBytes, flush: true);

    return DeviceFileSource(playbackFile.path);
  }

  Future<Source> _createRemotePlaybackSource(String url) async {
    if (kIsWeb) {
      return UrlSource(url);
    }

    final cachedFile = await _getRemoteAudioCacheFile(url);
    if (cachedFile != null && await cachedFile.exists()) {
      return DeviceFileSource(cachedFile.path);
    }

    final response = await ApiClient.dio.get<List<int>>(
      url,
      options: Options(responseType: ResponseType.bytes),
    );
    final rawBytes = response.data;
    if (rawBytes == null || rawBytes.isEmpty) {
      throw Exception('원격 TTS 세그먼트 오디오를 다운로드하지 못했습니다.');
    }

    final audioBytes = Uint8List.fromList(rawBytes);
    final tempDirectory = await getTemporaryDirectory();
    final extension = _fileExtensionFromUrl(url);
    final playbackFile = File(
      '${tempDirectory.path}${Platform.pathSeparator}'
      'ddalangoo_remote_tts_${_hashCacheKey(url)}.$extension',
    );
    await playbackFile.writeAsBytes(audioBytes, flush: true);

    if (cachedFile != null) {
      try {
        await cachedFile.writeAsBytes(audioBytes, flush: true);
      } catch (e) {
        debugPrint('⚠️ [Remote TTS Cache Write Error] $e');
      }
    }

    return DeviceFileSource(playbackFile.path);
  }

  Future<File?> _getRemoteAudioCacheFile(String url) async {
    if (kIsWeb) return null;
    final directoryFuture = _ttsCacheDirectoryFuture ??=
        _prepareTtsCacheDirectory();
    final directory = await directoryFuture;
    if (directory == null) return null;
    final extension = _fileExtensionFromUrl(url);
    return File(
      '${directory.path}${Platform.pathSeparator}'
      'remote_${_hashCacheKey(url)}.$extension',
    );
  }

  String _fileExtensionFromUrl(String url) {
    final uri = Uri.tryParse(url);
    final lastSegment = uri?.pathSegments.isNotEmpty == true
        ? uri!.pathSegments.last
        : url.split('/').last;
    final dotIndex = lastSegment.lastIndexOf('.');
    if (dotIndex == -1 || dotIndex == lastSegment.length - 1) {
      return 'wav';
    }
    return lastSegment.substring(dotIndex + 1).toLowerCase();
  }

  void _startPlaybackCompletionFallback(int expectedDurationMs) {
    _playbackFallbackTimer?.cancel();
    final expectedDuration = Duration(
      milliseconds: expectedDurationMs.clamp(1000, 45000),
    );
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
    for (final timer in _segmentTimers) {
      timer.cancel();
    }
    _segmentTimers.clear();
    _playbackFallbackTimer = null;
    _playbackStartedAt = null;
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
    final endedAt = DateTime.now();
    _lastPlaybackEndedAt = endedAt;
    debugPrint('[TTS] playback ended at=${endedAt.toIso8601String()}');
    final latencyContext = _activeSpeakLatencyContext;
    if (latencyContext != null) {
      FrontendLatencyLogger.instance.mark(latencyContext, 'audio_play_end');
    }
    _audioPlayEndLogged = true;
  }

  void _handlePlaybackCompletion(int? expectedDurationMs) {
    if (!_isSpeaking) return;

    final startedAt = _playbackStartedAt;
    if (startedAt != null &&
        expectedDurationMs != null &&
        expectedDurationMs >= 2500) {
      final elapsedMs = DateTime.now().difference(startedAt).inMilliseconds;
      final minReliableMs = (expectedDurationMs * 0.6).round();
      if (elapsedMs < minReliableMs) {
        debugPrint(
          '[TTS] ignoring premature completion elapsedMs=$elapsedMs expectedDurationMs=$expectedDurationMs',
        );
        return;
      }
    }

    _markAudioPlayEnd();
    _finishSpeaking();
  }

  List<TtsSegmentData> _parseSegments(
    Map<String, dynamic>? data,
    String text,
    Uint8List audioBytes,
  ) {
    final rawSegments = data?['segments'];
    if (rawSegments is List) {
      final parsed = rawSegments
          .whereType<Map>()
          .map((segment) {
            final segmentText = segment['text']?.toString().trim() ?? '';
            final durationMs = _toInt(segment['durationMs']);
            if (segmentText.isEmpty || durationMs == null || durationMs <= 0) {
              return null;
            }
            return TtsSegmentData(text: segmentText, durationMs: durationMs);
          })
          .whereType<TtsSegmentData>()
          .toList();
      if (parsed.isNotEmpty) {
        return parsed;
      }
    }
    return _fallbackSegments(text, audioBytes);
  }

  List<TtsSegmentData> _fallbackSegments(String text, Uint8List audioBytes) {
    return [
      TtsSegmentData(
        text: text.trim(),
        durationMs: _estimateWavDuration(audioBytes).inMilliseconds,
      ),
    ];
  }

  int? _toInt(Object? value) {
    if (value is int) return value;
    if (value is num) return value.round();
    return int.tryParse(value?.toString() ?? '');
  }

  void _scheduleSegmentCallbacks(
    List<TtsSegmentData> segments, {
    ValueChanged<TtsSegmentData>? onSegmentStart,
  }) {
    for (final timer in _segmentTimers) {
      timer.cancel();
    }
    _segmentTimers.clear();
    if (onSegmentStart == null || segments.isEmpty) {
      return;
    }

    var offsetMs = 0;
    for (var index = 0; index < segments.length; index += 1) {
      final segment = segments[index];
      final timer = Timer(Duration(milliseconds: offsetMs), () {
        if (!_isSpeaking) return;
        onSegmentStart(segment);
      });
      _segmentTimers.add(timer);
      offsetMs += segment.durationMs;
    }
  }
}
