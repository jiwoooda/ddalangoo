import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:audioplayers/audioplayers.dart';
import 'package:dio/dio.dart';
import 'package:flutter_dotenv/flutter_dotenv.dart';
import 'package:path_provider/path_provider.dart';
import 'package:record/record.dart';

import '../utils/latency_logger.dart';

class GptVoiceService {
  GptVoiceService({required String apiKey})
    : _apiKey = apiKey.trim(),
      _dio = Dio(
        BaseOptions(
          baseUrl: 'https://api.openai.com/v1',
          headers: {
            'Authorization': 'Bearer ${apiKey.trim()}',
          },
        ),
      );

  static GptVoiceService? _instance;
  static GptVoiceService get instance {
    final apiKey = dotenv.env['OPENAI_API_KEY'] ?? '';
    _instance ??= GptVoiceService(apiKey: apiKey);
    return _instance!;
  }

  static const String _sttModelName = 'gpt-4o-mini-transcribe';
  static const String _ttsModelName = 'gpt-4o-mini-tts';
  static const String _ttsVoiceName = 'coral';
  static const int _sampleRate = 16000;
  static const int _numChannels = 1;

  static const String _sttPrompt =
      "이 오디오는 한국어 음성 쇼핑 보조 서비스 '딸랑구'의 사용자 발화입니다. "
      '사용자의 말을 가능한 한 들리는 그대로 정확히 전사해주세요. '
      "고령층 사용자가 천천히 말하거나, 생각하면서 중간에 쉬거나, '음', '어', '그' 같은 간투사를 말할 수 있습니다. "
      '말 사이에 짧은 침묵이 있어도 하나의 발화로 자연스럽게 이어서 전사해주세요. '
      '상품명, 수량, 가격, 배송지, 장바구니, 결제, 재주문과 관련된 표현은 특히 정확히 전사해주세요. '
      '불확실한 내용은 임의로 바꾸지 말고 들리는 대로 전사해주세요.';

  static const String _ttsInstructions =
      '한국어로 말해줘. '
      '고령층 사용자가 듣기 쉽도록 천천히, 또렷하게 말해줘. '
      '친근한 딸 같은 말투로 부드럽고 따뜻하게 말해줘. '
      '문장은 너무 길게 끌지 말고 자연스럽게 쉬어가며 말해줘. '
      '가격, 수량, 날짜, 배송 관련 표현은 특히 또박또박 말해줘.';

  final String _apiKey;
  final Dio _dio;
  final AudioRecorder _recorder = AudioRecorder();
  final AudioPlayer _player = AudioPlayer();

  StreamSubscription<void>? _playerCompleteSubscription;
  StreamSubscription<PlayerState>? _playerStateSubscription;
  Completer<void>? _speakCompleter;
  Future<Directory?>? _sttRecordingDirectoryFuture;
  LatencyRequestContext? _activeSpeakLatencyContext;
  String? _activeRecordingPath;
  bool _audioPlayEndLogged = false;
  bool _isRecording = false;
  bool _isSpeaking = false;

  bool get isRecording => _isRecording;
  bool get isSpeaking => _isSpeaking;

  Future<void> init() async {
    _ensureApiKey();
    await _player.setReleaseMode(ReleaseMode.stop);
    if (!Platform.isIOS && !Platform.isAndroid && !Platform.isMacOS) {
      _sttRecordingDirectoryFuture ??= _prepareSttRecordingDirectory();
      return;
    }
    _sttRecordingDirectoryFuture ??= _prepareSttRecordingDirectory();
  }

  Future<void> startRecording() async {
    _ensureApiKey();
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
    } catch (e) {
      _isRecording = false;
      _activeRecordingPath = null;
      rethrow;
    }
  }

  Future<String> stopRecordingAndTranscribe() async {
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
      final transcript = await transcribeAudioFile(audioFile);
      return transcript;
    } finally {
      _activeRecordingPath = null;
      if (cleanupPath != null) {
        unawaited(_deleteIfExists(cleanupPath));
      }
    }
  }

  Future<String> transcribeAudioFile(File audioFile) async {
    _ensureApiKey();

    if (!await audioFile.exists()) {
      throw Exception('전사할 오디오 파일이 존재하지 않습니다.');
    }

    final fileLength = await audioFile.length();
    if (fileLength <= 0) {
      throw Exception('전사할 오디오 파일이 비어 있습니다.');
    }

    try {
      final formData = FormData.fromMap({
        'model': _sttModelName,
        'language': 'ko',
        'response_format': 'json',
        'prompt': _sttPrompt,
        'file': await MultipartFile.fromFile(
          audioFile.path,
          filename: audioFile.uri.pathSegments.isNotEmpty
              ? audioFile.uri.pathSegments.last
              : 'voice.wav',
        ),
      });

      final response = await _dio.post<Map<String, dynamic>>(
        '/audio/transcriptions',
        data: formData,
        options: Options(
          contentType: 'multipart/form-data',
          responseType: ResponseType.json,
        ),
      );

      final text = _extractTranscriptText(response.data);
      if (text.isEmpty) {
        throw Exception('음성 인식 결과가 비어 있습니다.');
      }
      return text;
    } on DioException catch (e) {
      throw Exception(_buildHttpErrorMessage('STT', e));
    }
  }

  Future<Uint8List> synthesizeSpeechToBytes(String text) async {
    _ensureApiKey();

    final normalized = text.trim();
    if (normalized.isEmpty) {
      throw Exception('TTS 입력 텍스트가 비어 있습니다.');
    }

    try {
      final response = await _dio.post<List<int>>(
        '/audio/speech',
        data: {
          'model': _ttsModelName,
          'voice': _ttsVoiceName,
          'input': normalized,
          'response_format': 'mp3',
          'instructions': _ttsInstructions,
        },
        options: Options(responseType: ResponseType.bytes),
      );

      final bytes = response.data == null
          ? Uint8List(0)
          : Uint8List.fromList(response.data!);
      if (bytes.isEmpty) {
        throw Exception('TTS 응답 오디오가 비어 있습니다.');
      }
      return bytes;
    } on DioException catch (e) {
      throw Exception(_buildHttpErrorMessage('TTS', e));
    }
  }

  Future<String> synthesizeSpeechToFile(String text) async {
    final bytes = await synthesizeSpeechToBytes(text);
    final directory = await getTemporaryDirectory();
    final filePath =
        '${directory.path}${Platform.pathSeparator}gpt_tts_${DateTime.now().microsecondsSinceEpoch}.mp3';
    final file = File(filePath);
    await file.writeAsBytes(bytes, flush: true);
    return file.path;
  }

  Future<void> speak(String text, {LatencyRequestContext? latencyContext}) async {
    final normalized = text.trim();
    if (normalized.isEmpty) {
      throw Exception('음성으로 읽을 텍스트가 비어 있습니다.');
    }

    if (_isSpeaking) {
      await stopSpeaking();
    }

    _isSpeaking = true;
    _speakCompleter = Completer<void>();
    _activeSpeakLatencyContext = latencyContext;
    _audioPlayEndLogged = false;

    if (latencyContext != null) {
      FrontendLatencyLogger.instance.mark(latencyContext, 'frontend_tts_start');
    }

    try {
      final mp3Bytes = await synthesizeSpeechToBytes(normalized);
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

      await _player.play(BytesSource(mp3Bytes));
      await _speakCompleter!.future;
    } catch (e) {
      _markAudioPlayEnd();
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
    await _recorder.dispose();
    await _player.dispose();
  }

  Future<void> cancelRecording() async {
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
    } catch (_) {}
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
    return '$label 요청에 실패했습니다'
        '${statusCode == null ? '' : ' (HTTP $statusCode)'}'
        '${details.isEmpty ? '' : ': $details'}';
  }

  void _ensureApiKey() {
    if (_apiKey.isEmpty) {
      throw Exception('OPENAI_API_KEY가 설정되지 않았습니다.');
    }
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
}
