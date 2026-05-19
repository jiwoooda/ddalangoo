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
import 'package:google_generative_ai/google_generative_ai.dart';
import 'package:path_provider/path_provider.dart';
import 'package:record/record.dart';

class GeminiVoiceService {
  static GeminiVoiceService? _instance;
  static GeminiVoiceService get instance =>
      _instance ??= GeminiVoiceService._();
  GeminiVoiceService._();

  static const String _sttModelName = 'models/gemini-3-flash-preview';
  static const String _ttsModelName = 'gemini-3.1-flash-tts-preview';
  static const String _ttsVoiceName = 'Puck';
  static const int _sampleRate = 16000;
  static const int _numChannels = 1;
  static const int _ttsSampleRate = 24000;
  static const int _maxCachedTtsItems = 12;
  static const List<String> _precacheTexts = [
    '안녕하세요! 무엇을 도와드릴까요?',
    '다시 말씀해주시겠어요?',
    '잠시만 기다려주세요.',
    '구매를 진행하겠습니다.',
    '결제가 완료되었습니다!',
  ];

  final AudioRecorder _recorder = AudioRecorder();
  final AudioPlayer _player = AudioPlayer();
  final Dio _dio = Dio();
  final BytesBuilder _audioBuffer = BytesBuilder(copy: false);
  final LinkedHashMap<String, Uint8List> _ttsCache = LinkedHashMap();
  final Map<String, Future<Uint8List>> _ttsInFlight = {};

  StreamSubscription<Uint8List>? _recordingSubscription;
  StreamSubscription<void>? _playerCompleteSubscription;
  StreamSubscription<PlayerState>? _playerStateSubscription;
  bool _isRecording = false;
  bool _isSpeaking = false;
  Completer<void>? _speakCompleter;
  Future<void>? _precacheTask;
  Future<Directory?>? _ttsCacheDirectoryFuture;

  bool get isRecording => _isRecording;
  bool get isSpeaking => _isSpeaking;

  Future<void> init() async {
    await _player.setReleaseMode(ReleaseMode.stop);
    if (!kIsWeb) {
      _ttsCacheDirectoryFuture ??= _prepareTtsCacheDirectory();
    }
    _precacheTask ??= _precacheCommonPhrases();
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

    _audioBuffer.clear();

    try {
      final stream = await _recorder.startStream(
        const RecordConfig(
          encoder: AudioEncoder.pcm16bits,
          sampleRate: _sampleRate,
          numChannels: _numChannels,
          autoGain: true,
          echoCancel: true,
          noiseSuppress: true,
        ),
      );

      _recordingSubscription = stream.listen(
        (chunk) {
          _audioBuffer.add(chunk);
        },
        onError: (Object error, StackTrace stackTrace) {
          debugPrint('❌ [Recording Stream Error] $error');
        },
      );

      _isRecording = true;
      debugPrint('🎙️ [Recording Started] sampleRate=$_sampleRate');
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
      await _recordingSubscription?.cancel();
      _recordingSubscription = null;
      await _recorder.stop();

      final pcmBytes = _audioBuffer.takeBytes();
      if (pcmBytes.isEmpty) {
        debugPrint('⚠️ [Gemini STT] empty recording buffer');
        return null;
      }

      final wavBytes = _wrapPcm16AsWav(
        pcmBytes,
        sampleRate: _sampleRate,
        channels: _numChannels,
      );

      debugPrint(
        '🎙️ [Gemini STT] model=$_sttModelName, bytes=${wavBytes.length}',
      );

      final response = await _model.generateContent([
        Content.multi([
          DataPart('audio/wav', wavBytes),
          TextPart(
            '이 오디오를 한국어로 정확하게 텍스트로 변환해줘. '
            '텍스트만 출력하고 다른 설명은 절대 하지 마.',
          ),
        ]),
      ]);

      return response.text?.trim();
    } catch (e) {
      debugPrint('❌ [Gemini STT Error] $e');
      return null;
    } finally {
      _audioBuffer.clear();
    }
  }

  Future<void> speak(String text) async {
    if (_isSpeaking) await stopSpeaking();
    _isSpeaking = true;
    _speakCompleter = Completer<void>();

    try {
      final wavBytes = await _getOrCreateSpeech(text);

      await _playerCompleteSubscription?.cancel();
      await _playerStateSubscription?.cancel();
      _playerCompleteSubscription = _player.onPlayerComplete.listen((_) {
        _finishSpeaking();
      });
      _playerStateSubscription = _player.onPlayerStateChanged.listen((state) {
        if (state == PlayerState.completed) {
          _finishSpeaking();
        }
      });

      await _player.play(BytesSource(wavBytes));
      await _speakCompleter!.future;
    } catch (e) {
      debugPrint('❌ [Gemini TTS Error] $e');
      _finishSpeaking();
      rethrow;
    }
  }

  Future<void> stopSpeaking() async {
    await _player.stop();
    _finishSpeaking();
  }

  Future<void> dispose() async {
    await _recordingSubscription?.cancel();
    await _playerCompleteSubscription?.cancel();
    await _playerStateSubscription?.cancel();
    await _recorder.dispose();
    await _player.dispose();
  }

  Future<void> _precacheCommonPhrases() async {
    for (final text in _precacheTexts) {
      try {
        await _getOrCreateSpeech(text);
      } catch (e) {
        debugPrint('⚠️ [Gemini TTS Precache Skipped] "$text" -> $e');
      }
    }
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

    final future = _generateSpeech(text);
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
                    'friendly, and kind voice at about 1.2x speed. '
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
    if (_speakCompleter != null && !_speakCompleter!.isCompleted) {
      _speakCompleter!.complete();
    }
    _speakCompleter = null;
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
