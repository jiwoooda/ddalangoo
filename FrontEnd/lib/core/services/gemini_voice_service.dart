// Gemini STT/TTS 서비스
import 'dart:async';
import 'dart:collection';
import 'dart:convert';
import 'dart:io';
import 'dart:math' as math;

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
  static const int _sampleRate = 44100;
  static const int _numChannels = 1;
  static const int _ttsSampleRate = 24000;
  static const int _maxCachedTtsItems = 12;
  static const int _ttsRetryCount = 2;
  static const Duration _ttsRetryBaseDelay = Duration(milliseconds: 800);
  static const int _vadFrameMs = 30;
  static const double _vadEnergyThreshold = 0.0018;
  static const int _minSpeechFrames = 4;
  static const int _minSpeechSamples = 1600;

  final AudioRecorder _recorder = AudioRecorder();
  final AudioPlayer _player = AudioPlayer();
  final FlutterTts _fallbackTts = FlutterTts();
  final Dio _dio = Dio();
  final LinkedHashMap<String, Uint8List> _ttsCache = LinkedHashMap();
  final Map<String, Future<Uint8List>> _ttsInFlight = {};

  StreamSubscription<void>? _playerCompleteSubscription;
  StreamSubscription<PlayerState>? _playerStateSubscription;
  bool _isRecording = false;
  bool _isSpeaking = false;
  Completer<void>? _speakCompleter;
  Future<Directory?>? _ttsCacheDirectoryFuture;
  Future<Directory?>? _sttRecordingDirectoryFuture;
  LatencyRequestContext? _activeSpeakLatencyContext;
  bool _audioPlayEndLogged = false;
  String? _activeRecordingPath;

  bool get isRecording => _isRecording;
  bool get isSpeaking => _isSpeaking;

  Future<void> init() async {
    await _player.setReleaseMode(ReleaseMode.stop);
    await _configureFallbackTts();
    if (!kIsWeb) {
      _ttsCacheDirectoryFuture ??= _prepareTtsCacheDirectory();
      _sttRecordingDirectoryFuture ??= _prepareSttRecordingDirectory();
    }
  }

  GenerativeModel get _model => GenerativeModel(
    model: _sttModelName,
    apiKey: dotenv.env['GEMINI_API_KEY'] ?? '',
  );

  Future<void> startRecording() async {
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
      debugPrint(
        '🎙️ [Recording Started] sampleRate=$_sampleRate, path=$_activeRecordingPath',
      );
    } catch (e) {
      _isRecording = false;
      _activeRecordingPath = null;
      debugPrint('❌ [Recording Start Error] $e');
      rethrow;
    }
  }

  Future<String?> stopRecordingAndTranscribe() async {
    if (!_isRecording) return null;

    _isRecording = false;
    String? cleanupPath;

    try {
      final recordedPath = await _recorder.stop();
      final path = recordedPath ?? _activeRecordingPath;
      cleanupPath = path;
      _activeRecordingPath = null;
      if (path == null) {
        debugPrint('⚠️ [Gemini STT] recording path missing');
        return null;
      }

      final wavFile = File(path);
      if (!await wavFile.exists()) {
        debugPrint('⚠️ [Gemini STT] recording file missing: $path');
        return null;
      }

      final wavBytes = await wavFile.readAsBytes();
      if (wavBytes.isEmpty) {
        debugPrint('⚠️ [Gemini STT] empty recording file');
        return null;
      }

      final pcmBytes = _extractPcm16FromWav(wavBytes);
      if (pcmBytes == null) {
        debugPrint('⚠️ [Gemini STT] unable to parse wav payload');
        return null;
      }

      final speechPcmBytes = _extractSpeechPcm(pcmBytes);
      if (speechPcmBytes == null) {
        debugPrint('⚠️ [Gemini STT] speech not detected after VAD');
        return null;
      }

      final trimmedWavBytes = _wrapPcm16AsWav(
        speechPcmBytes,
        sampleRate: _sampleRate,
        channels: _numChannels,
      );

      debugPrint(
        '🎙️ [Gemini STT] model=$_sttModelName, bytes=${trimmedWavBytes.length}, source=$path',
      );

      final response = await _model.generateContent([
        Content.multi([
          DataPart('audio/wav', trimmedWavBytes),
          TextPart(
            '이 오디오에서 실제로 들리는 한국어 발화만 그대로 텍스트로 변환해줘. '
            '추측해서 보충하거나 정리하지 말고, 들리지 않거나 불분명하면 빈 문자열로 응답해. '
            '화자가 말하지 않은 문장을 만들어내지 말고 텍스트만 출력해.',
          ),
        ]),
      ]);

      return response.text?.trim();
    } catch (e) {
      debugPrint('❌ [Gemini STT Error] $e');
      return null;
    } finally {
      _activeRecordingPath = null;
      if (cleanupPath != null) {
        unawaited(_deleteIfExists(cleanupPath));
      }
    }
  }

  Future<void> speak(String text, {LatencyRequestContext? latencyContext}) async {
    if (_isSpeaking) await stopSpeaking();
    _isSpeaking = true;
    _speakCompleter = Completer<void>();
    _activeSpeakLatencyContext = latencyContext;
    _audioPlayEndLogged = false;
    if (latencyContext != null) {
      FrontendLatencyLogger.instance.mark(latencyContext, 'frontend_tts_start');
    }

    try {
      final wavBytes = await _getOrCreateSpeech(text);
      if (latencyContext != null) {
        FrontendLatencyLogger.instance.mark(latencyContext, 'frontend_tts_ready');
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

      if (latencyContext != null) {
        FrontendLatencyLogger.instance.mark(latencyContext, 'audio_play_start');
      }
      await _player.play(BytesSource(wavBytes));
      await _speakCompleter!.future;
    } catch (e) {
      debugPrint('❌ [Gemini TTS Error] $e');

      try {
        await _speakWithFallbackTts(text);
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
    await _playerCompleteSubscription?.cancel();
    await _playerStateSubscription?.cancel();
    await _recorder.dispose();
    await _player.dispose();
    await _fallbackTts.stop();
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
      '$_ttsModelName|$_ttsVoiceName|1.2|$text';

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
      debugPrint('⚠️ [Gemini STT Recording Dir Error] $e');
      return null;
    }
  }

  Future<String> _createSttRecordingPath() async {
    if (kIsWeb) {
      return 'stt-recording.wav';
    }

    final directoryFuture =
        _sttRecordingDirectoryFuture ??= _prepareSttRecordingDirectory();
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
    } catch (e) {
      debugPrint('⚠️ [Gemini STT Recording Cleanup Error] $e');
    }
  }

  Future<File?> _getCacheFile(String cacheKey) async {
    if (kIsWeb) return null;

    final directoryFuture =
        _ttsCacheDirectoryFuture ??= _prepareTtsCacheDirectory();
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

  Future<void> _configureFallbackTts() async {
    try {
      await _fallbackTts.awaitSpeakCompletion(true);
      await _fallbackTts.setLanguage('ko-KR');
      await _fallbackTts.setPitch(1.15);
      await _fallbackTts.setSpeechRate(0.52);
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

  Future<void> _speakWithFallbackTts(String text) async {
    debugPrint('🟠 [Fallback TTS] Gemini TTS 대신 로컬 TTS를 사용합니다.');
    await _player.stop();
    final latencyContext = _activeSpeakLatencyContext;
    if (latencyContext != null) {
      FrontendLatencyLogger.instance.mark(latencyContext, 'audio_play_start');
    }
    await _fallbackTts.speak(text);
  }

  Future<Uint8List> _generateSpeech(String text) async {
    final apiKey = dotenv.env['GEMINI_API_KEY'] ?? '';
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
                    'Read the exact following Korean text in a bright, cheerful, '
                    'friendly, and kind feminine voice at about 1.2x speed. '
                    'Sound lively and encouraging, but still clear and easy for '
                    'older adults to understand. Do not add or change any words.\n$text',
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
    return _wrapPcm16AsWav(
      pcmBytes,
      sampleRate: _ttsSampleRate,
      channels: 1,
    );
  }

  void _finishSpeaking() {
    unawaited(_playerCompleteSubscription?.cancel());
    unawaited(_playerStateSubscription?.cancel());
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

  Uint8List? _extractPcm16FromWav(Uint8List wavBytes) {
    if (wavBytes.length < 44) return null;

    final header = ByteData.sublistView(wavBytes);
    final riff = String.fromCharCodes(wavBytes.sublist(0, 4));
    final wave = String.fromCharCodes(wavBytes.sublist(8, 12));
    if (riff != 'RIFF' || wave != 'WAVE') {
      return null;
    }

    var offset = 12;
    while (offset + 8 <= wavBytes.length) {
      final chunkId = String.fromCharCodes(wavBytes.sublist(offset, offset + 4));
      final chunkSize = header.getUint32(offset + 4, Endian.little);
      final chunkDataStart = offset + 8;
      final chunkDataEnd = chunkDataStart + chunkSize;

      if (chunkDataEnd > wavBytes.length) {
        return null;
      }

      if (chunkId == 'data') {
        return Uint8List.sublistView(wavBytes, chunkDataStart, chunkDataEnd);
      }

      offset = chunkDataEnd + (chunkSize.isOdd ? 1 : 0);
    }

    return null;
  }

  Uint8List? _extractSpeechPcm(Uint8List pcmBytes) {
    if (pcmBytes.length < 2) return null;

    final bytesPerSample = 2;
    final totalSamples = pcmBytes.length ~/ bytesPerSample;
    if (totalSamples < _minSpeechSamples) {
      debugPrint(
        '⚠️ [Gemini STT] recording too short for STT: samples=$totalSamples',
      );
      return null;
    }

    final samplesPerFrame = (_sampleRate * _vadFrameMs) ~/ 1000;
    if (samplesPerFrame <= 0 || totalSamples < samplesPerFrame) {
      debugPrint(
        '⚠️ [Gemini STT] recording shorter than one VAD frame: samples=$totalSamples',
      );
      return null;
    }

    int? firstSpeechFrame;
    int? lastSpeechFrame;
    var speechFrameCount = 0;
    var frameIndex = 0;

    for (var sampleStart = 0;
        sampleStart + samplesPerFrame <= totalSamples;
        sampleStart += samplesPerFrame, frameIndex++) {
      final energy = _frameEnergy(
        pcmBytes,
        sampleStart: sampleStart,
        sampleCount: samplesPerFrame,
      );
      if (energy >= _vadEnergyThreshold) {
        firstSpeechFrame ??= frameIndex;
        lastSpeechFrame = frameIndex;
        speechFrameCount += 1;
      }
    }

    if (firstSpeechFrame == null ||
        lastSpeechFrame == null ||
        speechFrameCount < _minSpeechFrames) {
      debugPrint(
        '⚠️ [Gemini STT] insufficient speech frames: speechFrames=$speechFrameCount',
      );
      return null;
    }

    final keepPaddingFrames = math.max(2, 150 ~/ _vadFrameMs);
    final startFrame = (firstSpeechFrame - keepPaddingFrames).clamp(
      0,
      frameIndex - 1,
    );
    final endFrame = (lastSpeechFrame + keepPaddingFrames).clamp(
      0,
      frameIndex - 1,
    );
    final startSample = startFrame * samplesPerFrame;
    final endSample = ((endFrame + 1) * samplesPerFrame).clamp(0, totalSamples);
    final startByte = startSample * bytesPerSample;
    final endByte = endSample * bytesPerSample;

    debugPrint(
      '🎙️ [Gemini STT VAD] totalSamples=$totalSamples, '
      'speechFrames=$speechFrameCount, startFrame=$startFrame, endFrame=$endFrame',
    );

    return Uint8List.sublistView(pcmBytes, startByte, endByte);
  }

  double _frameEnergy(
    Uint8List pcmBytes, {
    required int sampleStart,
    required int sampleCount,
  }) {
    final data = ByteData.sublistView(pcmBytes);
    var sumSquares = 0.0;

    for (var i = 0; i < sampleCount; i++) {
      final sample = data.getInt16((sampleStart + i) * 2, Endian.little);
      final normalized = sample / 32768.0;
      sumSquares += normalized * normalized;
    }

    return sumSquares / sampleCount;
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
