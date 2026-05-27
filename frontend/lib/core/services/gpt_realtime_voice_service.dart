import 'dart:async';
import 'dart:collection';
import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:audioplayers/audioplayers.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter_dotenv/flutter_dotenv.dart';
import 'package:record/record.dart';

enum RealtimeVoiceConnectionState {
  disconnected,
  connecting,
  connected,
  streaming,
  error,
}

class RealtimeTurnSnapshot {
  const RealtimeTurnSnapshot({
    required this.userTranscript,
    required this.assistantTranscript,
  });

  final String userTranscript;
  final String assistantTranscript;
}

/// Experimental realtime voice service.
///
/// Keeps the existing file-transcription/TTS services intact and adds a separate
/// implementation based on OpenAI Realtime over WebSocket.
///
/// Notes:
/// - This version is intended for native/mobile development use.
/// - It uses a standard API key directly from the client, which is convenient
///   for local testing but not appropriate for production mobile/web apps.
/// - For production client apps, prefer ephemeral credentials and WebRTC.
class GptRealtimeVoiceService {
  GptRealtimeVoiceService({
    required String apiKey,
    required String model,
  }) : _apiKey = apiKey.trim(),
       _model = model.trim().isEmpty ? _defaultRealtimeModel : model.trim();

  static const String _defaultRealtimeModel = 'gpt-realtime-mini';
  static const String _realtimeModelEnvKey = 'OPENAI_REALTIME_MODEL';
  static const String _voiceName = 'coral';
  static const int _sampleRate = 24000;
  static const int _numChannels = 1;

  static const String _sessionInstructions =
      '당신은 한국어 음성 쇼핑 보조 서비스 "딸랑구"입니다. '
      '고령층 사용자를 돕는 다정하고 인내심 있는 딸처럼 말하세요. '
      '사용자가 천천히 말하거나 중간에 잠깐 멈추더라도 서두르지 말고 끝까지 기다리세요. '
      '답변은 친절하고 따뜻하게, 너무 길지 않게 말하세요. '
      '가격, 수량, 날짜, 배송, 결제와 관련된 표현은 또렷하고 천천히 읽어주세요. '
      '사용자의 요청을 이해하지 못했으면 추측하지 말고 부드럽게 다시 물어보세요.';

  static GptRealtimeVoiceService? _instance;
  static GptRealtimeVoiceService get instance {
    final apiKey = dotenv.env['OPENAI_API_KEY'] ?? '';
    final model = dotenv.env[_realtimeModelEnvKey] ?? _defaultRealtimeModel;
    _instance ??= GptRealtimeVoiceService(apiKey: apiKey, model: model);
    return _instance!;
  }

  final String _apiKey;
  final String _model;
  final AudioRecorder _recorder = AudioRecorder();
  final AudioPlayer _player = AudioPlayer();

  WebSocket? _socket;
  StreamSubscription<dynamic>? _socketSubscription;
  StreamSubscription<Uint8List>? _recordingSubscription;

  final StreamController<RealtimeVoiceConnectionState> _connectionController =
      StreamController<RealtimeVoiceConnectionState>.broadcast();
  final StreamController<String> _userTranscriptController =
      StreamController<String>.broadcast();
  final StreamController<String> _assistantTranscriptController =
      StreamController<String>.broadcast();
  final StreamController<Map<String, dynamic>> _serverEventController =
      StreamController<Map<String, dynamic>>.broadcast();

  final BytesBuilder _assistantAudioBuffer = BytesBuilder(copy: false);
  final StringBuffer _assistantTranscriptBuffer = StringBuffer();
  final Queue<String> _pendingUserTranscripts = Queue<String>();

  Completer<void>? _responseCompleter;
  RealtimeVoiceConnectionState _connectionState =
      RealtimeVoiceConnectionState.disconnected;
  String _latestUserTranscript = '';
  String _latestAssistantTranscript = '';
  bool _isInitialized = false;
  bool _isRecording = false;
  bool _isSpeaking = false;

  bool get isRecording => _isRecording;
  bool get isSpeaking => _isSpeaking;
  bool get isConnected =>
      _connectionState == RealtimeVoiceConnectionState.connected ||
      _connectionState == RealtimeVoiceConnectionState.streaming;
  RealtimeVoiceConnectionState get connectionState => _connectionState;
  String get latestUserTranscript => _latestUserTranscript;
  String get latestAssistantTranscript => _latestAssistantTranscript;

  Stream<RealtimeVoiceConnectionState> get connectionStateStream =>
      _connectionController.stream;
  Stream<String> get userTranscriptStream => _userTranscriptController.stream;
  Stream<String> get assistantTranscriptStream =>
      _assistantTranscriptController.stream;
  Stream<Map<String, dynamic>> get serverEventStream =>
      _serverEventController.stream;

  Future<void> init() async {
    _ensureSupported();
    _ensureApiKey();
    if (_isInitialized) return;
    await _player.setReleaseMode(ReleaseMode.stop);
    _isInitialized = true;
  }

  Future<void> connect() async {
    _ensureSupported();
    _ensureApiKey();
    await init();

    if (isConnected) return;

    _setConnectionState(RealtimeVoiceConnectionState.connecting);

    final socket = await WebSocket.connect(
      'wss://api.openai.com/v1/realtime?model=$_model',
      headers: {'Authorization': 'Bearer $_apiKey'},
    );

    _socket = socket;
    _socketSubscription = socket.listen(
      _handleSocketMessage,
      onDone: _handleSocketClosed,
      onError: _handleSocketError,
      cancelOnError: false,
    );

    _setConnectionState(RealtimeVoiceConnectionState.connected);
    _sendEvent({
      'type': 'session.update',
      'session': {
        'type': 'realtime',
        'model': _model,
        'instructions': _sessionInstructions,
        'output_modalities': ['audio'],
        'audio': {
          'input': {
            'format': {'type': 'audio/pcm', 'rate': _sampleRate},
            'noise_reduction': {'type': 'near_field'},
            'turn_detection': {
              'type': 'semantic_vad',
              'eagerness': 'low',
              'create_response': true,
              'interrupt_response': true,
            },
          },
          'output': {
            'format': {'type': 'audio/pcm'},
            'voice': _voiceName,
          },
        },
      },
    });
  }

  Future<void> disconnect() async {
    await _recordingSubscription?.cancel();
    _recordingSubscription = null;
    _isRecording = false;

    await _socketSubscription?.cancel();
    _socketSubscription = null;

    await _socket?.close();
    _socket = null;

    await _player.stop();
    _isSpeaking = false;
    _assistantAudioBuffer.clear();
    _assistantTranscriptBuffer.clear();
    _responseCompleter = null;
    _setConnectionState(RealtimeVoiceConnectionState.disconnected);
  }

  Future<void> startStreamingConversation() async {
    _ensureSupported();
    await connect();

    if (_isRecording) return;

    _assistantAudioBuffer.clear();
    _assistantTranscriptBuffer.clear();
    _responseCompleter = Completer<void>();

    final stream = await _recorder.startStream(
      const RecordConfig(
        encoder: AudioEncoder.pcm16bits,
        sampleRate: _sampleRate,
        numChannels: _numChannels,
        autoGain: false,
        echoCancel: true,
        noiseSuppress: true,
      ),
    );

    _recordingSubscription = stream.listen(
      (chunk) {
        _sendEvent({
          'type': 'input_audio_buffer.append',
          'audio': base64Encode(chunk),
        });
      },
      onError: (Object error, StackTrace stackTrace) {
        _handleSocketError(error, stackTrace);
      },
    );

    _isRecording = true;
    _setConnectionState(RealtimeVoiceConnectionState.streaming);
  }

  Future<void> stopStreamingConversation() async {
    if (!_isRecording) return;

    await _recordingSubscription?.cancel();
    _recordingSubscription = null;
    await _recorder.stop();
    _isRecording = false;

    _sendEvent({'type': 'input_audio_buffer.commit'});
    _sendEvent({
      'type': 'response.create',
      'response': {
        'output_modalities': ['audio'],
      },
    });

    _setConnectionState(RealtimeVoiceConnectionState.connected);
  }

  Future<void> sendTextTurn(String text) async {
    final normalized = text.trim();
    if (normalized.isEmpty) {
      throw Exception('전송할 텍스트가 비어 있습니다.');
    }

    await connect();
    _assistantAudioBuffer.clear();
    _assistantTranscriptBuffer.clear();
    _responseCompleter = Completer<void>();

    _sendEvent({
      'type': 'conversation.item.create',
      'item': {
        'type': 'message',
        'role': 'user',
        'content': [
          {'type': 'input_text', 'text': normalized},
        ],
      },
    });
    _sendEvent({
      'type': 'response.create',
      'response': {
        'output_modalities': ['audio'],
      },
    });
  }

  Future<void> cancelResponse() async {
    if (!isConnected) return;
    _sendEvent({'type': 'response.cancel'});
    await _player.stop();
    _isSpeaking = false;
  }

  Future<void> stopSpeaking() async {
    await cancelResponse();
  }

  Future<RealtimeTurnSnapshot> waitForAssistantTurn({
    Duration timeout = const Duration(seconds: 30),
  }) async {
    final completer = _responseCompleter ??= Completer<void>();
    await completer.future.timeout(timeout);
    return RealtimeTurnSnapshot(
      userTranscript: _latestUserTranscript,
      assistantTranscript: _latestAssistantTranscript,
    );
  }

  Future<void> dispose() async {
    await disconnect();
    await _recorder.dispose();
    await _player.dispose();
    await _connectionController.close();
    await _userTranscriptController.close();
    await _assistantTranscriptController.close();
    await _serverEventController.close();
  }

  void _handleSocketMessage(dynamic message) {
    try {
      final raw = message is List<int> ? utf8.decode(message) : '$message';
      final event = jsonDecode(raw);
      if (event is! Map<String, dynamic>) return;

      _serverEventController.add(event);
      final type = event['type'] as String?;
      if (type == null) return;

      switch (type) {
        case 'session.created':
        case 'session.updated':
          _setConnectionState(
            _isRecording
                ? RealtimeVoiceConnectionState.streaming
                : RealtimeVoiceConnectionState.connected,
          );
          break;
        case 'conversation.item.input_audio_transcription.completed':
          _handleUserTranscriptCompleted(event);
          break;
        case 'response.output_audio.delta':
          final delta = event['delta'];
          if (delta is String && delta.isNotEmpty) {
            _assistantAudioBuffer.add(base64Decode(delta));
          }
          break;
        case 'response.output_audio_transcript.delta':
          final delta = event['delta'];
          if (delta is String && delta.isNotEmpty) {
            _assistantTranscriptBuffer.write(delta);
            _assistantTranscriptController.add(_assistantTranscriptBuffer.toString());
          }
          break;
        case 'response.output_audio_transcript.done':
        case 'response.output_text.done':
          _finalizeAssistantTranscript(event);
          break;
        case 'response.done':
          unawaited(_completeResponseAndPlay());
          break;
        case 'error':
          final error = event['error'];
          final messageText = error is Map<String, dynamic>
              ? error['message']
              : error;
          throw Exception(messageText ?? 'Realtime API error');
      }
    } catch (e, stackTrace) {
      _handleSocketError(e, stackTrace);
    }
  }

  void _handleUserTranscriptCompleted(Map<String, dynamic> event) {
    final transcript = (event['transcript'] as String? ?? '').trim();
    if (transcript.isEmpty) return;
    _latestUserTranscript = transcript;
    _pendingUserTranscripts.add(transcript);
    _userTranscriptController.add(transcript);
  }

  void _finalizeAssistantTranscript(Map<String, dynamic> event) {
    final transcript =
        (event['transcript'] as String? ??
                event['text'] as String? ??
                _assistantTranscriptBuffer.toString())
            .trim();
    if (transcript.isEmpty) return;
    _latestAssistantTranscript = transcript;
    _assistantTranscriptController.add(transcript);
  }

  Future<void> _playBufferedAssistantAudio() async {
    final pcmBytes = _assistantAudioBuffer.takeBytes();
    if (pcmBytes.isEmpty) return;

    _isSpeaking = true;
    try {
      final wavBytes = _wrapPcm16AsWav(
        pcmBytes,
        sampleRate: _sampleRate,
        channels: _numChannels,
      );
      await _player.play(BytesSource(wavBytes));
    } finally {
      _isSpeaking = false;
    }
  }

  Future<void> _completeResponseAndPlay() async {
    await _playBufferedAssistantAudio();
    _completeCurrentResponse();
  }

  void _completeCurrentResponse() {
    if (_assistantTranscriptBuffer.isNotEmpty) {
      final transcript = _assistantTranscriptBuffer.toString().trim();
      if (transcript.isNotEmpty) {
        _latestAssistantTranscript = transcript;
        _assistantTranscriptController.add(transcript);
      }
    }

    if (_responseCompleter != null && !_responseCompleter!.isCompleted) {
      _responseCompleter!.complete();
    }
  }

  void _handleSocketClosed() {
    _socket = null;
    _socketSubscription = null;
    _isRecording = false;
    _isSpeaking = false;
    _setConnectionState(RealtimeVoiceConnectionState.disconnected);
  }

  void _handleSocketError(Object error, [StackTrace? stackTrace]) {
    debugPrint('❌ [Realtime Voice Error] $error');
    if (stackTrace != null) {
      debugPrint('$stackTrace');
    }
    _setConnectionState(RealtimeVoiceConnectionState.error);
  }

  void _sendEvent(Map<String, dynamic> event) {
    final socket = _socket;
    if (socket == null) {
      throw Exception('Realtime session is not connected.');
    }
    socket.add(jsonEncode(event));
  }

  void _setConnectionState(RealtimeVoiceConnectionState state) {
    if (_connectionState == state) return;
    _connectionState = state;
    _connectionController.add(state);
  }

  void _ensureApiKey() {
    if (_apiKey.isEmpty) {
      throw Exception('OPENAI_API_KEY가 설정되지 않았습니다.');
    }
  }

  void _ensureSupported() {
    if (kIsWeb) {
      throw UnsupportedError(
        'GptRealtimeVoiceService는 현재 Flutter Web을 지원하지 않습니다. '
        '모바일/데스크톱 네이티브 환경에서 테스트해주세요.',
      );
    }
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
