// Gemini STT/TTS 서비스
import 'dart:async';
import 'dart:typed_data';

import 'package:flutter/foundation.dart';
import 'package:flutter_dotenv/flutter_dotenv.dart';
import 'package:flutter_tts/flutter_tts.dart';
import 'package:google_generative_ai/google_generative_ai.dart';
import 'package:record/record.dart';

class GeminiVoiceService {
  static GeminiVoiceService? _instance;
  static GeminiVoiceService get instance =>
      _instance ??= GeminiVoiceService._();
  GeminiVoiceService._();

  static const String _sttModelName = 'models/gemini-3-flash-preview';
  static const int _sampleRate = 16000;
  static const int _numChannels = 1;

  final AudioRecorder _recorder = AudioRecorder();
  final FlutterTts _tts = FlutterTts();
  final BytesBuilder _audioBuffer = BytesBuilder(copy: false);

  StreamSubscription<Uint8List>? _recordingSubscription;
  bool _isRecording = false;
  bool _isSpeaking = false;

  bool get isRecording => _isRecording;
  bool get isSpeaking => _isSpeaking;

  Future<void> init() async {
    await _tts.setLanguage('ko-KR');
    await _tts.setSpeechRate(0.45);
    await _tts.setVolume(1.0);
    await _tts.setPitch(1.0);
    _tts.setCompletionHandler(() {
      _isSpeaking = false;
    });
    _tts.setCancelHandler(() {
      _isSpeaking = false;
    });
    _tts.setErrorHandler((message) {
      debugPrint('❌ [Gemini TTS Error] $message');
      _isSpeaking = false;
    });
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
    try {
      await _tts.speak(text);
    } catch (e) {
      debugPrint('❌ [Gemini TTS Error] $e');
      _isSpeaking = false;
      rethrow;
    }
  }

  Future<void> stopSpeaking() async {
    await _tts.stop();
    _isSpeaking = false;
  }

  Future<void> dispose() async {
    await _recordingSubscription?.cancel();
    await _recorder.dispose();
    await _tts.stop();
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
