// 상태 관리
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter/foundation.dart';
import '../../data/models/agent_model.dart';
import '../../data/repositories/agent_repository.dart';
import '../../core/storage/local_storage.dart';
import '../../core/services/gemini_voice_service.dart';

enum CallStage {
  idle,
  loading,
  clarification,
  platformSelection,
  productSelection,
  cart,
  payment,
  completed,
}

class CallProvider extends ChangeNotifier {
  static const JsonEncoder _jsonEncoder = JsonEncoder.withIndent('  ');
  final AgentRepository _agentRepository = AgentRepository();
  final GeminiVoiceService _voiceService = GeminiVoiceService.instance;

  CallStage _stage = CallStage.idle;
  AgentResponse? _lastResponse;
  int? _conversationId;
  bool _isLoading = false;
  bool _isListening = false; // STT 녹음 중
  bool _isTranscribing = false; // STT 전사/전송 중
  bool _isSpeaking = false; // TTS 재생 중
  String? _errorMessage;
  final List<Map<String, dynamic>> _messages = [];

  CallStage get stage => _stage;
  AgentResponse? get lastResponse => _lastResponse;
  int? get conversationId => _conversationId;
  bool get isLoading => _isLoading;
  bool get isListening => _isListening;
  bool get isTranscribing => _isTranscribing;
  bool get isSpeaking => _isSpeaking;
  String? get errorMessage => _errorMessage;
  List<Map<String, dynamic>> get messages => _messages;
  bool get canUseVoice =>
      _stage != CallStage.idle &&
      _stage != CallStage.loading &&
      _stage != CallStage.completed &&
      !_isLoading &&
      !_isTranscribing;

  String get voiceStatusLabel {
    if (_isListening) return '말씀이 끝났으면 버튼을 다시 눌러주세요';
    if (_isTranscribing) return '로딩 중..';
    if (_isSpeaking) return '딸랑구가 말하는 중입니다';
    if (_isLoading) return '서버 응답을 기다리는 중입니다';
    return '버튼을 누르고 말씀해주세요.';
  }

  // 전화 시작
  Future<void> startCall() async {
    _setLoading(true);
    try {
      final userId = await LocalStorage.getUserId();
      if (userId == null) throw Exception('로그인이 필요합니다');

      final response = await _agentRepository.startShopping(
        userId: userId,
        message: 'INIT_CALL',
      );

      await _handleResponse(response);
    } catch (e) {
      _errorMessage = e.toString();
      notifyListeners();
    } finally {
      _setLoading(false);
    }
  }

  // 녹음 토글 (UI 버튼에서 하나만 호출하면 됨)
  Future<void> toggleListening() async {
    if (_isListening) {
      await stopListeningAndSend();
    } else {
      await startListening();
    }
  }

  // 녹음 시작 (사용자가 말할 때)
  Future<void> startListening() async {
    if (_isListening || _isLoading || _isTranscribing) return;
    try {
      _errorMessage = null;
      if (_isSpeaking) {
        await _voiceService.stopSpeaking();
        _isSpeaking = false;
      }
      await _voiceService.startRecording();
      _isListening = true;
      notifyListeners();
    } catch (e) {
      _errorMessage = '녹음을 시작하지 못했습니다: $e';
      debugPrint('❌ [Start Listening Error] $e');
      notifyListeners();
    }
  }

  // 녹음 중지 → STT → 백엔드 전송
  Future<void> stopListeningAndSend() async {
    if (!_isListening) return;

    _isListening = false;
    _isTranscribing = true;
    notifyListeners();

    try {
      // Gemini STT로 텍스트 변환
      final transcript = await _voiceService.stopRecordingAndTranscribe();

      if (transcript == null || transcript.isEmpty) {
        _errorMessage = '음성을 인식하지 못했습니다. 다시 말씀해주세요.';
        return;
      }

      _setLoading(true);
      _errorMessage = null;
      // 사용자 말풍선 추가
      _addMessage(text: transcript, isUser: true);

      // 백엔드 전송
      if (_conversationId == null) {
        final userId = await LocalStorage.getUserId();
        if (userId == null) return;
        final response = await _agentRepository.startShopping(
          userId: userId,
          message: transcript,
        );
        await _handleResponse(response);
      } else {
        final response = await _agentRepository.sendMessage(
          conversationId: _conversationId!,
          message: transcript,
        );
        await _handleResponse(response);
      }
    } catch (e) {
      _errorMessage = e.toString();
      notifyListeners();
    } finally {
      _isTranscribing = false;
      _setLoading(false);
    }
  }

  // 텍스트 메시지 전송 (데모/STT 대체용)
  Future<void> sendTextMessage(String text) async {
    if (text.isEmpty) return;

    _setLoading(true);
    _addMessage(text: text, isUser: true);

    try {
      if (_conversationId == null) {
        final userId = await LocalStorage.getUserId();
        if (userId == null) return;
        final response = await _agentRepository.startShopping(
          userId: userId,
          message: text,
        );
        await _handleResponse(response);
      } else {
        final response = await _agentRepository.sendMessage(
          conversationId: _conversationId!,
          message: text,
        );
        await _handleResponse(response);
      }
    } catch (e) {
      _errorMessage = e.toString();
      notifyListeners();
    } finally {
      _setLoading(false);
    }
  }

  // 확인/거부
  Future<void> confirmAction({
    required int recommendationItemId,
    required String action,
  }) async {
    if (_conversationId == null) return;
    _setLoading(true);
    try {
      _addMessage(
        text: action == 'accept' ? '응 그걸로 해줘' : '다른 걸로 해줘',
        isUser: true,
      );

      final response = await _agentRepository.confirmAction(
        conversationId: _conversationId!,
        recommendationItemId: recommendationItemId,
        action: action,
      );
      await _handleResponse(response);
    } catch (e) {
      _errorMessage = e.toString();
      notifyListeners();
    } finally {
      _setLoading(false);
    }
  }

  // 결제 웹뷰 결과
  Future<void> handlePaymentResult({
    required int orderId,
    required int paymentId,
    required String result,
  }) async {
    if (_conversationId == null) return;
    _setLoading(true);
    try {
      await _agentRepository.sendWebviewResult(
        conversationId: _conversationId!,
        orderId: orderId,
        paymentId: paymentId,
        result: result,
      );
      _stage = result == 'success' ? CallStage.completed : CallStage.payment;
      notifyListeners();
    } catch (e) {
      _errorMessage = e.toString();
      notifyListeners();
    } finally {
      _setLoading(false);
    }
  }

  // 전화 끊기
  void endCall() {
    _voiceService.stopSpeaking();
    _conversationId = null;
    _lastResponse = null;
    _stage = CallStage.idle;
    _messages.clear();
    _errorMessage = null;
    _isListening = false;
    _isTranscribing = false;
    _isSpeaking = false;
    notifyListeners();
  }

  // AgentResponse 처리 + TTS 재생
  Future<void> _handleResponse(AgentResponse response) async {
    final oldStage = _stage;
    _lastResponse = response;
    _conversationId = response.conversationId;

    // 딸랑구 말풍선 추가
    _addMessage(text: response.assistantMessage, isUser: false);

    // stage 결정
    if (response.asyncStatus != null) {
      _stage = CallStage.loading;
    } else {
      switch (response.stage) {
        case 'clarification':
          _stage = CallStage.clarification;
          break;
        case 'platform_selection':
          _stage = CallStage.platformSelection;
          break;
        case 'product_selection':
          _stage = CallStage.productSelection;
          break;
        case 'cart':
          _stage = CallStage.cart;
          break;
        case 'payment':
          _stage = CallStage.payment;
          break;
        case 'completed':
          _stage = CallStage.completed;
          break;
        default:
          _stage = CallStage.clarification;
      }
    }

    debugPrint(
      '🧭 [Provider Response Mapping]\n${_jsonEncoder.convert({
        'conversationId': response.conversationId,
        'backendStatus': response.status,
        'backendStage': response.stage,
        'mappedUiStage': _stage.name,
        'pendingConfirmation': response.pendingConfirmation,
        'recommendationCount': response.recommendations.length,
        'assistantMessage': response.assistantMessage,
      })}',
    );

    if (response.stage == 'idle') {
      debugPrint(
        '🟠 [Idle Stage Mapping] '
        '백엔드 stage 가 idle 이어서 UI 는 clarification 으로 매핑했습니다. '
        'pendingConfirmation=${response.pendingConfirmation}',
      );
    }

    debugPrint(
      '🔄 [Provider State Change] $oldStage -> $_stage (ConvID: $_conversationId)',
    );
    notifyListeners();

    // TTS로 딸랑구 응답 읽어주기
    // TTS 재생 중엔 STT 비활성화 (echo 방지)
    _isSpeaking = true;
    notifyListeners();
    try {
      await _voiceService
          .speak(response.assistantMessage)
          .timeout(const Duration(seconds: 8));
    } catch (e) {
      debugPrint('🔇 [TTS Fallback] $e');
    } finally {
      _isSpeaking = false;
      notifyListeners();
    }

    // TTS 끝나면 자동으로 녹음 시작 (always-on)
    //if (_stage != CallStage.loading &&
    //    _stage != CallStage.completed &&
    //    _stage != CallStage.payment) {
    //  await startListening();
    //}

    // 대신 DEMO: TT 방식 — 자동 녹음 없음, 사용자가 버튼 눌러서 말함
  }

  void _addMessage({required String text, required bool isUser}) {
    debugPrint('💬 [Message Log] ${isUser ? "USER" : "AI"}: $text');
    _messages.add({'text': text, 'isUser': isUser, 'time': DateTime.now()});
    notifyListeners();
  }

  void _setLoading(bool value) {
    _isLoading = value;
    notifyListeners();
  }
}
