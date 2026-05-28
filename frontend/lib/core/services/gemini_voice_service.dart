// Gemini STT/TTS 서비스
import 'dart:async';
import 'dart:collection';
import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:audioplayers/audioplayers.dart';
import 'package:crypto/crypto.dart';
import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter_dotenv/flutter_dotenv.dart';
import 'package:flutter_tts/flutter_tts.dart';
import 'package:google_generative_ai/google_generative_ai.dart';
import 'package:path_provider/path_provider.dart';
import 'package:record/record.dart';

import '../utils/latency_logger.dart';

class GeminiVoiceService {
  static GeminiVoiceService? _instance;
  static GeminiVoiceService get instance =>
      _instance ??= GeminiVoiceService._();
  GeminiVoiceService._();

  static const String _sttModelName = 'models/gemini-3-flash-preview';
  static const String _ttsModelName = 'gemini-3.1-flash-tts-preview';
  static const String _ttsVoiceName = 'Zephyr';
  static const String _useGeminiTtsEnvKey = 'USE_GEMINI_TTS';
  static const String _geminiApiKeyEnvKey = 'GEMINI_API_KEY';
  static const String _definedUseGeminiTts = String.fromEnvironment(
    _useGeminiTtsEnvKey,
  );
  static const String _definedGeminiApiKey = String.fromEnvironment(
    _geminiApiKeyEnvKey,
  );
  static const double _ttsSpeedMultiplier = 1.2;
  static const int _sampleRate = 44100;
  static const int _numChannels = 1;
  static const int _ttsSampleRate = 24000;
  static const int _maxCachedTtsItems = 12;
  static const int _ttsRetryCount = 2;
  static const int _minPcmBytesForStt = 12000;
  static const int _maxTranscriptLength = 80;
  static const Duration _ttsRetryBaseDelay = Duration(milliseconds: 800);

  final AudioRecorder _recorder = AudioRecorder();
  final AudioPlayer _player = AudioPlayer();
  final FlutterTts _fallbackTts = FlutterTts();
  final Dio _dio = Dio();
  final BytesBuilder _audioBuffer = BytesBuilder(copy: false);
  final LinkedHashMap<String, Uint8List> _ttsCache = LinkedHashMap();
  final Map<String, Future<Uint8List>> _ttsInFlight = {};

  StreamSubscription<Uint8List>? _recordingSubscription;
  StreamSubscription<void>? _playerCompleteSubscription;
  StreamSubscription<PlayerState>? _playerStateSubscription;
  Timer? _playbackFallbackTimer;
  bool _isRecording = false;
  bool _isSpeaking = false;
  Completer<void>? _speakCompleter;
  Future<Directory?>? _ttsCacheDirectoryFuture;
  LatencyRequestContext? _activeSpeakLatencyContext;
  DateTime? _recordingStartedAt;
  String? _recordingFilePath;
  bool _isRecordingToFile = false;
  int _recordedByteCount = 0;
  bool _audioPlayEndLogged = false;
  bool _hasLoggedMissingGeminiTtsKey = false;

  bool get isRecording => _isRecording;
  bool get isSpeaking => _isSpeaking;
  bool get _isGeminiTtsRequested =>
      _readRuntimeValue(
        key: _useGeminiTtsEnvKey,
        definedValue: _definedUseGeminiTts,
      ).toLowerCase() ==
      'true';
  bool get _hasGeminiApiKey => _geminiApiKey.isNotEmpty;
  bool get _shouldUseGeminiTts => _isGeminiTtsRequested && _hasGeminiApiKey;
  String get _geminiApiKey => _readRuntimeValue(
    key: _geminiApiKeyEnvKey,
    definedValue: _definedGeminiApiKey,
  );

  Future<void> init() async {
    await _player.setReleaseMode(ReleaseMode.stop);
    await _configureFallbackTts();
    if (!kIsWeb) {
      _ttsCacheDirectoryFuture ??= _prepareTtsCacheDirectory();
    }
  }

  // NOTE: STT는 백엔드 /api/voice/stt 로 위임됐으므로 이 모델은 사용되지 않는다.
  // USE_GEMINI_TTS=false 설정 시 TTS도 로컬 FlutterTts 폴백을 사용하므로
  // GEMINI_API_KEY가 없어도 앱이 정상 동작한다.
  // Gemini TTS 백엔드 이전 완료 후 이 getter와 _generateSpeech를 제거할 것.
  GenerativeModel get _model =>
      GenerativeModel(model: _sttModelName, apiKey: _geminiApiKey);

  Future<void> startRecording() async {
    if (_isRecording) return;

    final hasPermission = await _recorder.hasPermission();
    if (!hasPermission) {
      throw Exception('브라우저/기기에서 마이크 권한이 허용되지 않았습니다.');
    }

    _audioBuffer.clear();
    _recordingStartedAt = null;
    _recordingFilePath = null;
    _isRecordingToFile = false;
    _recordedByteCount = 0;

    try {
      final stream = await _recorder.startStream(
        const RecordConfig(
          encoder: AudioEncoder.pcm16bits,
          sampleRate: _sampleRate,
          numChannels: _numChannels,
          autoGain: false,
          echoCancel: false,
          noiseSuppress: false,
        ),
      );

      _recordingSubscription = stream.listen(
        (chunk) {
          _audioBuffer.add(chunk);
          _recordedByteCount += chunk.length;
        },
        onError: (Object error, StackTrace stackTrace) {
          debugPrint('❌ [Recording Stream Error] $error');
        },
      );

      _isRecording = true;
      _recordingStartedAt = DateTime.now();
      debugPrint('🎙️ [Recording Started] sampleRate=$_sampleRate');
      unawaited(_logRecordingHealthCheck());
    } catch (e) {
      await _recordingSubscription?.cancel();
      _recordingSubscription = null;
      _isRecording = false;
      debugPrint('❌ [Recording Start Error] $e');
      rethrow;
    }
  }

  Future<String?> stopRecordingAndTranscribe() async {
    if (!_isRecording) return null;

    _isRecording = false;

    try {
      final recordingDurationMs = _recordingStartedAt == null
          ? null
          : DateTime.now().difference(_recordingStartedAt!).inMilliseconds;

      Uint8List wavBytes;
      int audioBytesLength;

      if (_isRecordingToFile) {
        final stoppedPath = await _stopRecorderWithTimeout();
        final filePath = stoppedPath ?? _recordingFilePath;
        if (filePath == null) {
          debugPrint('⚠️ [Gemini STT] recording file path is null');
          return null;
        }

        final recordingFile = File(filePath);
        if (!await recordingFile.exists()) {
          debugPrint('⚠️ [Gemini STT] recording file not found: $filePath');
          return null;
        }

        wavBytes = await recordingFile.readAsBytes();
        audioBytesLength = wavBytes.length;
        unawaited(
          recordingFile.delete().catchError((Object e) {
            debugPrint('⚠️ [Recording File Delete Error] $e');
            return recordingFile;
          }),
        );
      } else {
        // stream 녹음은 stop 직후 마지막 chunk가 비동기로 들어올 수 있다.
        // 구독을 먼저 끊으면 마지막 오디오 조각을 잃어서 empty buffer가 될 수 있다.
        await Future.delayed(const Duration(milliseconds: 180));
        await _recordingSubscription?.cancel();
        _recordingSubscription = null;

        await _stopRecorderWithTimeout();

        final pcmBytes = _audioBuffer.takeBytes();
        audioBytesLength = pcmBytes.length;

        if (pcmBytes.isEmpty) {
          debugPrint('⚠️ [Gemini STT] empty recording buffer');
          return null;
        }

        wavBytes = _wrapPcm16AsWav(
          pcmBytes,
          sampleRate: _sampleRate,
          channels: _numChannels,
        );
      }

      if (wavBytes.isEmpty) {
        debugPrint('⚠️ [Gemini STT] empty recording buffer');
        return null;
      }

      if (audioBytesLength < _minPcmBytesForStt) {
        debugPrint(
          '⚠️ [Gemini STT] recording too short, '
          'bytes=$audioBytesLength, durationMs=$recordingDurationMs',
        );
        return null;
      }

      debugPrint(
        '🎙️ [Gemini STT] model=$_sttModelName, '
        'bytes=${wavBytes.length}, audioBytes=$audioBytesLength, '
        'streamPcmBytes=$_recordedByteCount, fileMode=$_isRecordingToFile, '
        'durationMs=$recordingDurationMs',
      );

      final response = await _model.generateContent([
        Content.multi([
          DataPart('audio/wav', wavBytes),
          TextPart(
            '너는 한국어 음성 인식 엔진이다. '
            '오디오에서 실제로 들리는 사용자의 말만 한 줄 한국어 텍스트로 전사해라. '
            '오디오에 없는 문장, 대화 예시, 답변, 설명은 절대 만들지 마라. '
            '말이 불명확하거나 배경음/무음이면 빈 문자열만 출력해라. '
            '줄바꿈 없이 텍스트만 출력해라.',
          ),
        ]),
      ]);

      return _normalizeSttTranscript(response.text);
    } catch (e) {
      debugPrint('❌ [Gemini STT Error] $e');
      return null;
    } finally {
      _audioBuffer.clear();
      _recordingStartedAt = null;
      _recordingFilePath = null;
      _isRecordingToFile = false;
      _recordedByteCount = 0;
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
    if (!_shouldUseGeminiTts) {
      _logMissingGeminiTtsKeyIfNeeded();
      return;
    }

    try {
      await _getOrCreateSpeech(normalized);
    } catch (e) {
      debugPrint('⚠️ [Gemini TTS Prefetch Error] "$normalized" $e');
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
    final speakCompleter = Completer<void>();
    _speakCompleter = speakCompleter;
    _activeSpeakLatencyContext = latencyContext;
    _audioPlayEndLogged = false;
    if (latencyContext != null) {
      FrontendLatencyLogger.instance.mark(latencyContext, 'frontend_tts_start');
    }

    try {
      if (!_shouldUseGeminiTts) {
        _logMissingGeminiTtsKeyIfNeeded();
        if (latencyContext != null) {
          FrontendLatencyLogger.instance.mark(
            latencyContext,
            'frontend_tts_ready',
          );
        }
        await _speakWithFallbackTts(text, onPlaybackStart: onPlaybackStart);
        _markAudioPlayEnd();
        _finishSpeaking();
        return;
      }

      final wavBytes = await _getOrCreateSpeech(text);
      final speechSource = await _createSpeechPlaybackSource(text, wavBytes);
      if (latencyContext != null) {
        FrontendLatencyLogger.instance.mark(
          latencyContext,
          'frontend_tts_ready',
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
      await _player.play(speechSource);
      await speakCompleter.future;
    } catch (e) {
      debugPrint('❌ [Gemini TTS Error] $e');

      try {
        await _speakWithFallbackTts(text, onPlaybackStart: onPlaybackStart);
      } finally {
        _markAudioPlayEnd();
        _finishSpeaking();
      }
    }
  }

  Future<void> stopSpeaking() async {
    await _player.stop();
    await _fallbackTts.stop();
    _markAudioPlayEnd();
    _finishSpeaking();
  }

  Future<void> dispose() async {
    await _recordingSubscription?.cancel();
    await _playerCompleteSubscription?.cancel();
    await _playerStateSubscription?.cancel();
    _playbackFallbackTimer?.cancel();
    await _recorder.dispose();
    await _player.dispose();
    await _fallbackTts.stop();
  }

  Future<void> cancelRecording() async {
    if (!_isRecording) return;
    _isRecording = false;
    try {
      await _stopRecorderWithTimeout();
    } catch (e) {
      debugPrint('⚠️ [Recording Cancel Error] $e');
    }

    await _recordingSubscription?.cancel();
    _recordingSubscription = null;
    _audioBuffer.clear();
    _recordingStartedAt = null;
    _recordingFilePath = null;
    _isRecordingToFile = false;
    _recordedByteCount = 0;
  }

  Future<String?> _stopRecorderWithTimeout() async {
    try {
      return await _recorder.stop().timeout(const Duration(seconds: 2));
    } on TimeoutException {
      debugPrint('⚠️ [Recording Stop Timeout] recorder.stop() timed out');
      return null;
    }
  }

  Future<void> _logRecordingHealthCheck() async {
    await Future.delayed(const Duration(milliseconds: 700));
    if (!_isRecording) return;

    debugPrint(
      '🔎 [Recording Health] '
      'isRecording=$_isRecording, bufferedBytes=$_recordedByteCount',
    );

    if (_recordedByteCount == 0) {
      debugPrint(
        '⚠️ [Recording Health] 마이크 입력 chunk가 아직 없습니다. '
        'macOS 마이크 권한 또는 입력 장치를 확인해주세요.',
      );
    }
  }

  String? _normalizeSttTranscript(String? rawText) {
    final transcript = rawText?.trim();
    if (transcript == null || transcript.isEmpty) return null;

    debugPrint('📝 [Gemini STT Raw] $transcript');

    final lines = transcript
        .split(RegExp(r'[\r\n]+'))
        .map((line) => line.trim())
        .where((line) => line.isNotEmpty)
        .toList();

    // 짧은 쇼핑 명령을 기대하는 앱에서 여러 줄 상담문이 나오면
    // 실제 발화보다 모델이 대화 예시를 만든 경우일 가능성이 높다.
    if (lines.length > 1) {
      debugPrint('⚠️ [Gemini STT] rejected multi-line transcript: $transcript');
      return null;
    }

    final cleaned = _stripWrappingQuotes(lines.single);

    if (cleaned.length > _maxTranscriptLength) {
      debugPrint('⚠️ [Gemini STT] rejected long transcript: $cleaned');
      return null;
    }

    return cleaned.isEmpty ? null : cleaned;
  }

  String _stripWrappingQuotes(String text) {
    var cleaned = text.trim();
    const wrappingQuotes = ['"', "'", '“', '”', '‘', '’'];

    while (cleaned.isNotEmpty && wrappingQuotes.contains(cleaned[0])) {
      cleaned = cleaned.substring(1).trimLeft();
    }

    while (cleaned.isNotEmpty &&
        wrappingQuotes.contains(cleaned[cleaned.length - 1])) {
      cleaned = cleaned.substring(0, cleaned.length - 1).trimRight();
    }

    return cleaned.trim();
  }

  Future<Uint8List> _getOrCreateSpeech(String text) async {
    final cacheKey = _buildTtsCacheKey(text);
    final cached = _ttsCache.remove(cacheKey);
    if (cached != null) {
      _ttsCache[cacheKey] = cached;
      debugPrint('🟢 [Gemini TTS Cache Hit] "$text"');
      return cached;
    }

    final diskCached = await _readSpeechFromDisk(cacheKey);
    if (diskCached != null) {
      _rememberTtsCache(cacheKey, diskCached);
      debugPrint('🔵 [Gemini TTS Disk Cache Hit] "$text"');
      return diskCached;
    }

    final inFlight = _ttsInFlight[cacheKey];
    if (inFlight != null) {
      debugPrint('🟡 [Gemini TTS Await In-Flight] "$text"');
      return inFlight;
    }

    final future = _generateSpeechWithRetry(text);
    _ttsInFlight[cacheKey] = future;

    try {
      final wavBytes = await future;
      _rememberTtsCache(cacheKey, wavBytes);
      unawaited(_writeSpeechToDisk(cacheKey, wavBytes));
      debugPrint('🟣 [Gemini TTS Cache Store] "$text"');
      return wavBytes;
    } finally {
      _ttsInFlight.remove(cacheKey);
    }
  }

  String _buildTtsCacheKey(String text) =>
      '$_ttsModelName|$_ttsVoiceName|$_ttsSpeedMultiplier|$text';

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
      debugPrint('⚠️ [Gemini TTS Cache Dir Error] $e');
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
      debugPrint('⚠️ [Gemini TTS Disk Read Error] $e');
      return null;
    }
  }

  Future<void> _writeSpeechToDisk(String cacheKey, Uint8List wavBytes) async {
    try {
      final file = await _getCacheFile(cacheKey);
      if (file == null) return;
      await file.writeAsBytes(wavBytes, flush: true);
    } catch (e) {
      debugPrint('⚠️ [Gemini TTS Disk Write Error] $e');
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
    final cacheKey = _buildTtsCacheKey(text);
    final playbackFile = File(
      '${tempDirectory.path}${Platform.pathSeparator}'
      'ddalangoo_tts_playback_${_hashCacheKey(cacheKey)}.wav',
    );

    final shouldWrite =
        !await playbackFile.exists() ||
        await playbackFile.length() != wavBytes.length;
    if (shouldWrite) {
      await playbackFile.writeAsBytes(wavBytes, flush: true);
    }

    return DeviceFileSource(playbackFile.path);
  }

  Future<void> _configureFallbackTts() async {
    try {
      await _fallbackTts.awaitSpeakCompletion(true);
      await _fallbackTts.setLanguage('ko-KR');
      await _fallbackTts.setPitch(1.15);
      await _fallbackTts.setSpeechRate(0.62);
    } catch (e) {
      debugPrint('⚠️ [Fallback TTS Config Error] $e');
    }
  }

  Future<Uint8List> _generateSpeechWithRetry(String text) async {
    var attempt = 0;

    while (true) {
      attempt += 1;

      try {
        return await _generateSpeech(text);
      } on DioException catch (e) {
        if (!_isRetryableTtsError(e) || attempt > _ttsRetryCount) {
          rethrow;
        }

        final delay = Duration(
          milliseconds: _ttsRetryBaseDelay.inMilliseconds * attempt,
        );
        debugPrint(
          '⚠️ [Gemini TTS Retry] '
          'status=${e.response?.statusCode}, attempt=$attempt/$_ttsRetryCount, '
          'delay=${delay.inMilliseconds}ms',
        );
        await Future.delayed(delay);
      }
    }
  }

  bool _isRetryableTtsError(DioException error) {
    final statusCode = error.response?.statusCode;
    return statusCode == 429 || statusCode == 503;
  }

  Future<void> _speakWithFallbackTts(
    String text, {
    VoidCallback? onPlaybackStart,
  }) async {
    debugPrint('🟠 [Fallback TTS] Gemini TTS 대신 로컬 TTS를 사용합니다.');
    await _player.stop();
    _playbackFallbackTimer?.cancel();
    final latencyContext = _activeSpeakLatencyContext;
    if (latencyContext != null) {
      FrontendLatencyLogger.instance.mark(latencyContext, 'audio_play_start');
    }
    onPlaybackStart?.call();
    await _fallbackTts.speak(text);
  }

  Future<Uint8List> _generateSpeech(String text) async {
    final apiKey = _geminiApiKey;
    if (apiKey.isEmpty) {
      throw Exception('GEMINI_API_KEY가 설정되지 않았습니다.');
    }

    final response = await _dio.post(
      'https://generativelanguage.googleapis.com/v1beta/models/'
      '$_ttsModelName:generateContent',
      options: Options(headers: {'x-goog-api-key': apiKey}),
      data: {
        'contents': [
          {
            'parts': [
              {
                'text':
                    'Read the exact following Korean text in Korean. '
                    'Speak like a warm, affectionate daughter helping an older parent shop. '
                    'Use a bright, reassuring, and very kind tone. '
                    'Keep the voice gentle, patient, and easy for older adults to understand. '
                    'Speak about 1.2x faster than a neutral default pace without sounding rushed. '
                    'Pause naturally between sentences. '
                    'Pronounce prices, quantities, dates, addresses, and payment-related words very clearly. '
                    'Sound friendly and comforting, never cold or robotic. '
                    'Do not add, remove, or change any words.\n$text',
              },
            ],
          },
        ],
        'generationConfig': {
          'responseModalities': ['AUDIO'],
          'speechConfig': {
            'voiceConfig': {
              'prebuiltVoiceConfig': {'voiceName': _ttsVoiceName},
            },
          },
        },
        'model': _ttsModelName,
      },
    );

    final data = response.data;
    String? encodedAudio;
    if (data is Map<String, dynamic>) {
      final candidates = data['candidates'];
      if (candidates is List && candidates.isNotEmpty) {
        final firstCandidate = candidates.first;
        if (firstCandidate is Map<String, dynamic>) {
          final content = firstCandidate['content'];
          if (content is Map<String, dynamic>) {
            final parts = content['parts'];
            if (parts is List && parts.isNotEmpty) {
              final firstPart = parts.first;
              if (firstPart is Map<String, dynamic>) {
                final inlineData = firstPart['inlineData'];
                if (inlineData is Map<String, dynamic>) {
                  encodedAudio = inlineData['data'] as String?;
                }
              }
            }
          }
        }
      }
    }

    if (encodedAudio == null || encodedAudio.isEmpty) {
      throw Exception('Gemini TTS 응답에서 오디오 데이터를 받지 못했습니다.');
    }

    final pcmBytes = base64Decode(encodedAudio);
    return _wrapPcm16AsWav(pcmBytes, sampleRate: _ttsSampleRate, channels: 1);
  }

  String _readRuntimeValue({
    required String key,
    required String definedValue,
  }) {
    final fromDefine = definedValue.trim();
    if (fromDefine.isNotEmpty) return fromDefine;
    return (dotenv.env[key] ?? '').trim();
  }

  void _logMissingGeminiTtsKeyIfNeeded() {
    if (!_isGeminiTtsRequested || _hasGeminiApiKey) return;
    if (_hasLoggedMissingGeminiTtsKey) return;
    _hasLoggedMissingGeminiTtsKey = true;
    debugPrint(
      '⚠️ [Gemini TTS Disabled] USE_GEMINI_TTS=true 이지만 '
      '프론트 실행 환경에 GEMINI_API_KEY가 없어 로컬 TTS를 사용합니다.',
    );
  }

  void _startPlaybackCompletionFallback(Uint8List wavBytes) {
    _playbackFallbackTimer?.cancel();
    final expectedDuration = _estimateWavDuration(wavBytes);
    final fallbackDelay = expectedDuration + const Duration(milliseconds: 1800);
    _playbackFallbackTimer = Timer(fallbackDelay, () {
      if (!_isSpeaking) return;
      debugPrint(
        '⏱️ [Gemini TTS Playback Fallback] '
        'completion event missing, finishing after '
        '${fallbackDelay.inMilliseconds}ms',
      );
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
    if (bytesPerSecond <= 0) {
      return const Duration(seconds: 2);
    }

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
    final latencyContext = _activeSpeakLatencyContext;
    if (latencyContext != null) {
      FrontendLatencyLogger.instance.mark(latencyContext, 'audio_play_end');
    }
    _audioPlayEndLogged = true;
  }

  Uint8List _wrapPcm16AsWav(
    Uint8List pcmBytes, {
    required int sampleRate,
    required int channels,
  }) {
    const bitsPerSample = 16;
    final byteRate = sampleRate * channels * (bitsPerSample ~/ 8);
    final blockAlign = channels * (bitsPerSample ~/ 8);
    final totalLength = 44 + pcmBytes.length;
    final bytes = ByteData(totalLength);

    void writeAscii(int offset, String value) {
      for (var i = 0; i < value.length; i++) {
        bytes.setUint8(offset + i, value.codeUnitAt(i));
      }
    }

    writeAscii(0, 'RIFF');
    bytes.setUint32(4, 36 + pcmBytes.length, Endian.little);
    writeAscii(8, 'WAVE');
    writeAscii(12, 'fmt ');
    bytes.setUint32(16, 16, Endian.little);
    bytes.setUint16(20, 1, Endian.little);
    bytes.setUint16(22, channels, Endian.little);
    bytes.setUint32(24, sampleRate, Endian.little);
    bytes.setUint32(28, byteRate, Endian.little);
    bytes.setUint16(32, blockAlign, Endian.little);
    bytes.setUint16(34, bitsPerSample, Endian.little);
    writeAscii(36, 'data');
    bytes.setUint32(40, pcmBytes.length, Endian.little);

    final output = bytes.buffer.asUint8List();
    output.setRange(44, totalLength, pcmBytes);
    return output;
  }
}
