// 상태 관리
import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter_dotenv/flutter_dotenv.dart';
import '../../core/network/api_client.dart';
import '../../data/models/agent_model.dart';
import '../../data/repositories/agent_repository.dart';
import '../../core/storage/local_storage.dart';
import '../../core/services/gpt_voice_service.dart';
import '../../core/services/gpt_realtime_voice_service.dart';
import '../../core/utils/latency_logger.dart';

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
  static const Duration _minTtsTimeout = Duration(seconds: 20);
  static const Duration _maxTtsTimeout = Duration(seconds: 45);
  final AgentRepository _agentRepository = AgentRepository();
  final UserRepository _userRepository = UserRepository();
  final GptVoiceService _voiceService = GptVoiceService.instance;
  final GptRealtimeVoiceService _realtimeVoiceService =
      GptRealtimeVoiceService.instance;

  CallStage _stage = CallStage.idle;
  AgentResponse? _lastResponse;
  int? _conversationId;
  bool _isLoading = false;
  bool _isListening = false; // STT 녹음 중
  bool _isTranscribing = false; // STT 전사/전송 중
  bool _isSpeaking = false; // TTS 재생 중
  bool _isAwaitingAssistantPresentation = false;
  String? _errorMessage;
  String _userDisplayName = '';
  String? _assistantPresentationMessage;
  final List<Map<String, dynamic>> _messages = [];
  LatencyRequestContext? _activeLatencyContext;

  CallStage get stage => _stage;
  AgentResponse? get lastResponse => _lastResponse;
  int? get conversationId => _conversationId;
  bool get isLoading => _isLoading;
  bool get isListening => _isListening;
  bool get isTranscribing => _isTranscribing;
  bool get isSpeaking => _isSpeaking;
  bool get isAwaitingAssistantPresentation => _isAwaitingAssistantPresentation;
  String? get errorMessage => _errorMessage;
  List<Map<String, dynamic>> get messages => _messages;
  String? get assistantPresentationMessage => _assistantPresentationMessage;
  String get currentAssistantMessage =>
      (_lastResponse?.assistantMessage ?? '').trim();
  String? get currentAsyncStatusMessage {
    final asyncStatus = _lastResponse?.asyncStatus;
    if (asyncStatus is Map && asyncStatus['message'] is String) {
      final message = (asyncStatus['message'] as String).trim();
      return message.isEmpty ? null : message;
    }
    return null;
  }
  String? get webviewStreamUrl {
    final conversationId = _conversationId;
    if (conversationId == null) return null;

    final baseUri = Uri.parse(ApiClient.baseUrl);
    final wsScheme = baseUri.scheme == 'https' ? 'wss' : 'ws';
    return baseUri.replace(
      scheme: wsScheme,
      path: '/api/agent/conversations/$conversationId/webview',
      query: null,
      fragment: null,
    ).toString();
  }
  String get webviewUrl => 'about:blank';
  bool get canShowWebviewProgress =>
      _conversationId != null &&
      (_stage == CallStage.cart ||
          _stage == CallStage.payment ||
          (_stage == CallStage.productSelection && _isLoading));
  String get webviewStatusText {
    final asyncMessage = currentAsyncStatusMessage;
    if (asyncMessage != null) return asyncMessage;
    if (currentAssistantMessage.isNotEmpty) return currentAssistantMessage;
    if (_stage == CallStage.productSelection && _isLoading) {
      return '선택하신 상품을 장바구니에 담는 중이에요.';
    }
    if (_stage == CallStage.cart) return '장바구니에 담는 중이에요.';
    if (_stage == CallStage.payment) return '결제 화면을 준비하고 있어요.';
    return '웹 화면을 준비하고 있어요.';
  }
  String get webviewTargetLabel {
    if (_stage == CallStage.productSelection && _isLoading) {
      return '장바구니 작업';
    }
    if (_stage == CallStage.cart) return '장바구니 작업';
    if (_stage == CallStage.payment) return '결제 진행';
    return '웹 진행 상황';
  }
  int? get currentOrderId {
    final order = _lastResponse?.order;
    if (order is Map && order['orderId'] is int) return order['orderId'] as int;
    final pending = _lastResponse?.pendingConfirmation;
    if (pending is Map &&
        pending['payload'] is Map &&
        pending['payload']['orderId'] is int) {
      return pending['payload']['orderId'] as int;
    }
    return null;
  }
  int? get currentPaymentId {
    final payment = _lastResponse?.payment;
    if (payment is Map && payment['paymentId'] is int) {
      return payment['paymentId'] as int;
    }
    final pending = _lastResponse?.pendingConfirmation;
    if (pending is Map &&
        pending['payload'] is Map &&
        pending['payload']['paymentId'] is int) {
      return pending['payload']['paymentId'] as int;
    }
    return null;
  }
  Future<Map<String, dynamic>?> getWebviewStatus() async {
    final conversationId = _conversationId;
    if (conversationId == null) return null;
    return _agentRepository.getWebviewStatus(conversationId);
  }
  bool get canUseVoice =>
      _stage != CallStage.loading &&
      _stage != CallStage.completed &&
      !_isLoading &&
      !_isTranscribing;
  bool get _useRealtimeVoice =>
      (dotenv.env['USE_OPENAI_REALTIME_VOICE'] ?? '').toLowerCase() == 'true';

  String get voiceStatusLabel {
    if (_isListening) return '말씀이 끝났으면 버튼을 다시 눌러주세요';
    if (_isTranscribing) return '로딩 중..';
    if (_isSpeaking) return '딸랑구가 말하는 중입니다';
    if (_isLoading) return '서버 응답을 기다리는 중입니다';
    return '버튼을 누르고 말씀해주세요.';
  }

  // 전화 시작
  Future<void> startCall() async {
    try {
      FrontendLatencyLogger.instance.startSession();
      final userId = await LocalStorage.getUserId();
      if (userId == null) throw Exception('로그인이 필요합니다');

      String greetingName = '';
      try {
        final user = await _userRepository.getUser(userId);
        greetingName = user.name.trim();
        _userDisplayName = greetingName;
      } catch (e) {
        debugPrint('⚠️ [Call Start User Load Error] $e');
      }

      _conversationId = null;
      _lastResponse = null;
      _stage = CallStage.idle;
      _errorMessage = null;
      _assistantPresentationMessage = null;
      _isAwaitingAssistantPresentation = false;
      _messages.clear();
      final greetingText = greetingName.isEmpty
          ? '무엇을 구매하고 싶으신가요?'
          : '$greetingName님, 무엇을 구매하고 싶으신가요?';
      unawaited(_voiceService.prefetchSpeech(greetingText));
      var greetingPresented = false;
      _isSpeaking = true;
      notifyListeners();
      try {
        await _voiceService.speak(
          greetingText,
          onPlaybackStart: () {
            if (greetingPresented) return;
            greetingPresented = true;
            _addMessage(
              text: greetingText,
              isUser: false,
            );
          },
        );
      } finally {
        if (!greetingPresented) {
          _addMessage(
            text: greetingText,
            isUser: false,
          );
        }
        _isSpeaking = false;
        notifyListeners();
      }
    } catch (e) {
      _errorMessage = e.toString();
      notifyListeners();
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
        if (_useRealtimeVoice) {
          await _realtimeVoiceService.stopSpeaking();
        } else {
          await _voiceService.stopSpeaking();
        }
        _isSpeaking = false;
      }
      final latencyContext = FrontendLatencyLogger.instance.beginTurn();
      _activeLatencyContext = latencyContext;
      FrontendLatencyLogger.instance.mark(latencyContext, 'user_speech_start');
      if (_useRealtimeVoice) {
        await _realtimeVoiceService.startStreamingConversation();
      } else {
        await _voiceService.startRecording();
      }
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
      final latencyContext = _activeLatencyContext;
      if (latencyContext != null) {
        FrontendLatencyLogger.instance.mark(latencyContext, 'user_speech_end');
        FrontendLatencyLogger.instance.mark(latencyContext, 'frontend_stt_start');
      }

      if (_useRealtimeVoice) {
        _isSpeaking = true;
        notifyListeners();
        await _realtimeVoiceService.stopStreamingConversation();
        final snapshot = await _realtimeVoiceService.waitForAssistantTurn();
        if (latencyContext != null) {
          FrontendLatencyLogger.instance.mark(latencyContext, 'frontend_stt_end');
        }
        if (snapshot.userTranscript.isEmpty) {
          _errorMessage = '음성을 인식하지 못했습니다. 다시 말씀해주세요.';
          _activeLatencyContext = null;
          return;
        }

        _errorMessage = null;
        _addMessage(text: snapshot.userTranscript, isUser: true);
        if (snapshot.assistantTranscript.isNotEmpty) {
          _addMessage(text: snapshot.assistantTranscript, isUser: false);
        }
        _stage = CallStage.clarification;
        notifyListeners();
      } else {
        // OpenAI STT로 텍스트 변환
        final transcript = await _voiceService.stopRecordingAndTranscribe();
        if (latencyContext != null) {
          FrontendLatencyLogger.instance.mark(latencyContext, 'frontend_stt_end');
        }

        if (transcript.isEmpty) {
          _errorMessage = '음성을 인식하지 못했습니다. 다시 말씀해주세요.';
          _activeLatencyContext = null;
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
            latencyContext: latencyContext,
          );
          await _handleResponse(response, latencyContext: latencyContext);
        } else {
          final response = await _agentRepository.sendMessage(
            conversationId: _conversationId!,
            message: transcript,
            latencyContext: latencyContext,
          );
          await _handleResponse(response, latencyContext: latencyContext);
        }
      }
    } catch (e) {
      _errorMessage = e.toString();
      notifyListeners();
    } finally {
      _activeLatencyContext = null;
      _isTranscribing = false;
      _isSpeaking = false;
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

  Future<void> submitPaymentPassword(String password) async {
    if (password.length != 6 || _conversationId == null) return;

    _setLoading(true);
    _addMessage(text: '●●●●●●', isUser: true, isSensitive: true);

    try {
      final response = await _agentRepository.sendMessage(
        conversationId: _conversationId!,
        message: password,
        redactMessageForLogs: true,
      );
      await _handleResponse(response);
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
      final response = await _agentRepository.sendWebviewResult(
        conversationId: _conversationId!,
        orderId: orderId,
        paymentId: paymentId,
        result: result,
      );
      await _handleResponse(response);
    } catch (e) {
      _errorMessage = e.toString();
      notifyListeners();
    } finally {
      _setLoading(false);
    }
  }

  // 전화 끊기
  void endCall() {
    if (_useRealtimeVoice) {
      _realtimeVoiceService.stopSpeaking();
      _realtimeVoiceService.disconnect();
    } else {
      _voiceService.stopSpeaking();
      _voiceService.cancelRecording();
    }
    FrontendLatencyLogger.instance.endSession();
    _conversationId = null;
    _lastResponse = null;
    _stage = CallStage.idle;
    _messages.clear();
    _errorMessage = null;
    _isListening = false;
    _isTranscribing = false;
    _isSpeaking = false;
    _isAwaitingAssistantPresentation = false;
    _assistantPresentationMessage = null;
    _activeLatencyContext = null;
    notifyListeners();
  }

  // AgentResponse 처리 + TTS 재생
  Future<void> _handleResponse(
    AgentResponse response, {
    LatencyRequestContext? latencyContext,
  }) async {
    final oldStage = _stage;
    final nextStage = _mapResponseStage(response);
    _conversationId = response.conversationId;
    _assistantPresentationMessage = _buildAssistantPresentationMessage(
      response,
      nextStage,
    );
    _isAwaitingAssistantPresentation = true;
    var responsePresented = false;

    // stage 결정
    if (response.asyncStatus != null) {
      _stage = CallStage.loading;
    }

    debugPrint(
      '🧭 [Provider Response Mapping]\n${_jsonEncoder.convert({
        'conversationId': response.conversationId,
        'backendStatus': response.status,
        'backendStage': response.stage,
        'mappedUiStage': nextStage.name,
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
      '🔄 [Provider State Change] $oldStage -> ${nextStage.name} (ConvID: $_conversationId)',
    );
    notifyListeners();

    // TTS로 딸랑구 응답 읽어주기
    // TTS 재생 중엔 STT 비활성화 (echo 방지)
    _isSpeaking = true;
    notifyListeners();
    try {
      await _voiceService
          .speak(
            response.assistantMessage,
            latencyContext: latencyContext,
            onPlaybackStart: () {
              if (responsePresented) return;
              responsePresented = true;
              _presentAssistantResponse(response, nextStage);
            },
          )
          .timeout(_ttsTimeoutFor(response.assistantMessage));
    } on TimeoutException catch (e) {
      debugPrint(
        '🔇 [TTS Playback Timeout] TTS 전체 처리 대기 중 타임아웃되었습니다. '
        'messageLength=${response.assistantMessage.runes.length}, '
        'timeout=${_ttsTimeoutFor(response.assistantMessage).inSeconds}s, '
        '$e',
      );
      await _voiceService.stopSpeaking();
    } catch (e) {
      debugPrint('🔇 [TTS Fallback] $e');
    } finally {
      if (!responsePresented) {
        _presentAssistantResponse(response, nextStage);
      }
      _isSpeaking = false;
      _isAwaitingAssistantPresentation = false;
      _assistantPresentationMessage = null;
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

  void _addMessage({
    required String text,
    required bool isUser,
    bool isSensitive = false,
  }) {
    final logText = isSensitive ? '******' : text;
    debugPrint('💬 [Message Log] ${isUser ? "USER" : "AI"}: $logText');
    _messages.add({
      'text': text,
      'isUser': isUser,
      'isSensitive': isSensitive,
      'time': DateTime.now(),
    });
    notifyListeners();
  }

  void _setLoading(bool value) {
    _isLoading = value;
    notifyListeners();
  }

  void _presentAssistantResponse(AgentResponse response, CallStage nextStage) {
    final lastMessage = _messages.isNotEmpty ? _messages.last : null;
    final alreadyAddedAssistant =
        lastMessage != null &&
        lastMessage['isUser'] == false &&
        lastMessage['text'] == response.assistantMessage;
    _lastResponse = response;
    _stage = nextStage;
    if (!alreadyAddedAssistant) {
      _addMessage(text: response.assistantMessage, isUser: false);
    }
  }

  CallStage _mapResponseStage(AgentResponse response) {
    if (response.asyncStatus != null) {
      return CallStage.loading;
    }

    switch (response.stage) {
      case 'clarification':
        return CallStage.clarification;
      case 'platform_selection':
        return CallStage.platformSelection;
      case 'product_selection':
      case 'product_confirming':
        return CallStage.productSelection;
      case 'cart':
      case 'cart_shopping':
        return CallStage.cart;
      case 'payment':
      case 'address_confirming':
      case 'payment_precheck':
      case 'payment_password_required':
      case 'payment_processing':
        return CallStage.payment;
      case 'completed':
        return CallStage.completed;
      default:
        return CallStage.clarification;
    }
  }

  String _buildAssistantPresentationMessage(
    AgentResponse response,
    CallStage nextStage,
  ) {
    final prefix = _userDisplayName.isEmpty ? '' : '$_userDisplayName님을 위한 ';
    if (response.asyncStatus is Map && response.asyncStatus['message'] is String) {
      final asyncMessage = (response.asyncStatus['message'] as String).trim();
      if (asyncMessage.isNotEmpty) return asyncMessage;
    }

    switch (nextStage) {
      case CallStage.productSelection:
        return '$prefix맞춤 상품을 정리하고 있어요.';
      case CallStage.cart:
        return '장바구니 진행 상황을 차분히 안내하고 있어요.';
      case CallStage.payment:
        return '결제에 필요한 내용을 천천히 안내하고 있어요.';
      case CallStage.completed:
        return '주문 결과를 정리해서 안내하고 있어요.';
      case CallStage.platformSelection:
        return '$prefix쇼핑 플랫폼을 살펴보고 있어요.';
      case CallStage.clarification:
        return '말씀하신 내용을 이해해서 안내를 준비하고 있어요.';
      case CallStage.loading:
        return '처리 결과를 정리하고 있어요.';
      case CallStage.idle:
        return '답변을 준비하고 있어요.';
    }
  }

  Duration _ttsTimeoutFor(String text) {
    final estimatedSeconds = 20 + (text.runes.length ~/ 10);
    final clampedSeconds = estimatedSeconds.clamp(
      _minTtsTimeout.inSeconds,
      _maxTtsTimeout.inSeconds,
    );
    return Duration(seconds: clampedSeconds);
  }

  void loadPreviewState({
    required CallStage stage,
    AgentResponse? response,
    List<Map<String, dynamic>> messages = const [],
    int? conversationId,
    String userDisplayName = '김영희',
    bool isLoading = false,
    bool isListening = false,
    bool isTranscribing = false,
    bool isSpeaking = false,
    bool isAwaitingAssistantPresentation = false,
    String? assistantPresentationMessage,
    String? errorMessage,
  }) {
    _stage = stage;
    _lastResponse = response;
    _conversationId = conversationId;
    _userDisplayName = userDisplayName;
    _isLoading = isLoading;
    _isListening = isListening;
    _isTranscribing = isTranscribing;
    _isSpeaking = isSpeaking;
    _isAwaitingAssistantPresentation = isAwaitingAssistantPresentation;
    _assistantPresentationMessage = assistantPresentationMessage;
    _errorMessage = errorMessage;
    _messages
      ..clear()
      ..addAll(messages);
    notifyListeners();
  }
}
