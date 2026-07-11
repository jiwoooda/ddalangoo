import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:record/record.dart';

import '../../../core/services/android_native_speech_recognition_service.dart';
import '../../../core/services/stt_vad_response_log_service.dart';
import '../../../core/network/api_client.dart';
import '../models/shopping_v2_models.dart';
import '../services/shopping_agent_service.dart';
import '../services/voice_turn_service.dart';

enum ShoppingVoicePreviewPreset {
  askProduct,
  searchingProduct,
  showProduct,
  askQuantity,
  addingToCart,
  askMoreOrCheckout,
  confirmAddress,
  enterPassword,
  processingPayment,
  paymentCompleted,
  error,
}

class ShoppingFlowController extends ChangeNotifier {
  static const bool _manualStopRecordingEnabled = true;
  static const Duration _manualStopSafetyTimeout = Duration(seconds: 45);
  static const Duration _defaultTtsToUserDelay = Duration(milliseconds: 280);
  static const Duration _androidTtsToUserDelay = Duration(milliseconds: 220);
  static const Duration _defaultRetryPromptToUserDelay = Duration(
    milliseconds: 1200,
  );
  static const Duration _androidRetryPromptToUserDelay = Duration(
    milliseconds: 320,
  );
  static const Duration _vadAmplitudeWarmup = Duration(milliseconds: 2200);
  static const int _speechStartCandidateSampleThreshold = 2;
  static const Duration _initialSpeechWaitTimeout = Duration(
    milliseconds: 6500,
  );
  static const Duration _maxRecordingDuration = Duration(seconds: 18);
  static const Duration _endOfSpeechSilence = Duration(milliseconds: 4000);
  static const Duration _silenceConfirmDuration = Duration(milliseconds: 1700);
  static const Duration _minSpeechWindow = Duration(milliseconds: 3200);
  static const Duration _minimumRecordingDuration = Duration(
    milliseconds: 3600,
  );
  static const Duration _firstSyllableProtection = Duration(milliseconds: 2200);
  static const int _maxTurnContinuationCount = 2;
  static const double _speechGuardRatio = 0.82;
  static const bool _forceSilentDemoTts = bool.fromEnvironment(
    'SHOPPING_V1_SILENT_TTS',
  );
  static const bool textInputMode = bool.fromEnvironment('TEXT_INPUT_MODE');

  ShoppingFlowController({
    ShoppingAgentService? agentService,
    VoiceTurnService? voiceTurnService,
  }) : _agentService = agentService ?? ShoppingAgentService(),
       _voiceTurnService = voiceTurnService ?? VoiceTurnService();

  factory ShoppingFlowController.preview(
    ShoppingVoicePreviewPreset preset, {
    String userName = '김영희',
  }) {
    final controller = ShoppingFlowController();
    controller._applyPreviewPreset(preset, userName: userName);
    return controller;
  }

  final ShoppingAgentService _agentService;
  final VoiceTurnService _voiceTurnService;

  ShoppingStep _step = ShoppingStep.askProduct;
  VoiceTurnState _voiceTurnState = VoiceTurnState.idle;
  String _assistantText = '';
  int _assistantTtsDurationMs = 0;
  String? _latestTranscript;
  ProductViewData? _currentProduct;
  final List<CartItemViewData> _cartItems = [];
  CheckoutSummary? _checkoutSummary;
  String? _errorMessage;
  bool _isInitialized = false;
  bool _isMockMode = false;
  int? _conversationId;
  int _userId = 1;
  String? _userName;
  int _speakEpoch = 0;
  int _speechRunId = 0;
  int _currentQuantity = 1;
  String _cartStatusTitle = '장바구니 작업';
  String _cartStatusText = '컬리 페이지를 열고 있어요.';
  String _cartHelperText = '쇼핑 화면을 준비하고 있어요.';
  double _cartProgress = 0.18;
  String _pin = '';
  double _voiceLevel = 0.22;
  String? _lastWebviewTask;
  WebviewTaskViewData? _pendingWebviewTask;
  String? _activeSearchKeyword;
  StreamSubscription<Amplitude>? _amplitudeSubscription;
  StreamSubscription<NativeSpeechRecognitionEvent>?
  _recognitionEventSubscription;
  Timer? _cartTimer;
  Timer? _paymentTimer;
  Timer? _completionSequenceTimer;
  Timer? _userTurnTimer;
  Timer? _recordingTimeoutTimer;
  Timer? _speechSilenceTimer;
  Timer? _fallbackAutoStopTimer;
  StreamSubscription<ShoppingAgentResponse>? _agentProgressSubscription;
  bool _hasDetectedSpeech = false;
  double _speechNoiseFloor = -45;
  int _noiseSampleCount = 0;
  DateTime? _recordingStartedAt;
  DateTime? _firstSpeechDetectedAt;
  DateTime? _lastSpeechDetectedAt;
  DateTime? _lastVadDebugAt;
  DateTime? _lastUserTurnReadyAt;
  DateTime? _lastListeningBeginRequestedAt;
  DateTime? _silenceCandidateStartedAt;
  bool _isAmplitudeTelemetryUnreliable = false;
  bool _isAwaitingSilenceConfirmation = false;
  int _amplitudeSampleCount = 0;
  int _zeroishAmplitudeCount = 0;
  int _speechStartCandidateCount = 0;
  bool _hasLoggedFirstLiveAmplitude = false;
  String? _partialTranscript;
  int _turnContinuationCount = 0;
  bool _closeAppRequested = false;
  int _agentProgressRunId = 0;
  bool _suppressAutoVoiceReply = false;

  ShoppingStep get step => _step;
  VoiceTurnState get voiceTurnState => _voiceTurnState;
  String get assistantText => _assistantText;
  int get assistantTtsDurationMs => _assistantTtsDurationMs;
  String? get latestTranscript => _latestTranscript;
  ProductViewData? get currentProduct => _currentProduct;
  List<CartItemViewData> get cartItems => List.unmodifiable(_cartItems);
  CheckoutSummary? get checkoutSummary => _checkoutSummary;
  String? get errorMessage => _errorMessage;
  bool get isInitialized => _isInitialized;
  double get voiceLevel => _voiceLevel;
  String? get userName => _userName;
  bool get canRecord =>
      _voiceTurnState == VoiceTurnState.userCanSpeak ||
      _voiceTurnState == VoiceTurnState.userRecording;
  bool get isRecording => _voiceTurnState == VoiceTurnState.userRecording;
  bool get shouldShowVoiceButton =>
      _voiceTurnState == VoiceTurnState.userCanSpeak ||
      _voiceTurnState == VoiceTurnState.userRecording ||
      _voiceTurnState == VoiceTurnState.error;
  String get cartStatusTitle => _cartStatusTitle;
  String get cartStatusText => _cartStatusText;
  String get cartHelperText => _cartHelperText;
  double get cartProgress => _cartProgress;
  String get pin => _pin;
  bool get isMockMode => _isMockMode;
  WebviewTaskViewData? get pendingWebviewTask => _pendingWebviewTask;
  String? get activeSearchKeyword => _activeSearchKeyword;
  bool get _shouldBypassTtsForDemo => _forceSilentDemoTts;
  bool get _isAndroidRuntime =>
      !kIsWeb && defaultTargetPlatform == TargetPlatform.android;
  bool get _isNativeAsrMode => _voiceTurnService.isUsingNativeAndroidAsr;
  bool _isActiveEpoch(int epoch) => epoch == _speakEpoch;
  bool _canContinueUserRecording(int epoch) {
    return _isActiveEpoch(epoch) &&
        _voiceTurnState == VoiceTurnState.userRecording;
  }

  bool get closeAppRequested => _closeAppRequested;

  void _applyPreviewPreset(
    ShoppingVoicePreviewPreset preset, {
    required String userName,
  }) {
    final primaryProduct = ProductViewData(
      platform: 'kurly',
      shopName: '컬리',
      productUrl: 'https://example.com/products/watermelon-1kg',
      imageUrl:
          'https://images.unsplash.com/photo-1563114773-84221bd62daa?auto=format&fit=crop&w=1200&q=80',
      title: '고당도 수박',
      quantityInfo: '1kg x 1통',
      price: 9900,
      priceText: '9,900원',
      badgeText: '가격이 좋고 후기 평점이 높아요',
    );
    final secondaryProduct = ProductViewData(
      platform: 'naver',
      shopName: '네이버플러스 스토어',
      productUrl: 'https://example.com/products/eggs-15',
      imageUrl:
          'https://images.unsplash.com/photo-1506976785307-8732e854ad03?auto=format&fit=crop&w=1200&q=80',
      title: '무항생제 계란',
      quantityInfo: '15구',
      price: 6900,
      priceText: '6,900원',
      badgeText: '최근 자주 주문한 상품이에요',
    );

    _step = ShoppingStep.askProduct;
    _voiceTurnState = VoiceTurnState.idle;
    _assistantText = '';
    _assistantTtsDurationMs = 0;
    _latestTranscript = null;
    _currentProduct = null;
    _cartItems.clear();
    _checkoutSummary = null;
    _errorMessage = null;
    _isInitialized = true;
    _isMockMode = true;
    _conversationId = 9000 + preset.index;
    _userId = 1;
    _userName = userName;
    _currentQuantity = 2;
    _cartStatusTitle = '장바구니 작업';
    _cartStatusText = '상품을 장바구니에 담고 있어요.';
    _cartHelperText = '수량과 옵션을 확인한 뒤 장바구니에 담는 중이에요.';
    _cartProgress = 0.18;
    _pin = '';
    _voiceLevel = 0.34;
    _lastWebviewTask = null;
    _pendingWebviewTask = null;
    _activeSearchKeyword = null;
    _partialTranscript = null;
    _turnContinuationCount = 0;
    _closeAppRequested = false;
    _suppressAutoVoiceReply = false;

    switch (preset) {
      case ShoppingVoicePreviewPreset.askProduct:
        _step = ShoppingStep.askProduct;
        _voiceTurnState = VoiceTurnState.userCanSpeak;
        _assistantText = '$userName님, 오늘은 무엇을 구매하고 싶으신가요?';
        return;
      case ShoppingVoicePreviewPreset.searchingProduct:
        _step = ShoppingStep.searchingProduct;
        _voiceTurnState = VoiceTurnState.agentThinking;
        _activeSearchKeyword = '수박';
        _assistantText = '$userName님을 위한 수박을 찾고 있어요.';
        return;
      case ShoppingVoicePreviewPreset.showProduct:
        _step = ShoppingStep.showProduct;
        _voiceTurnState = VoiceTurnState.userCanSpeak;
        _currentProduct = primaryProduct;
        _assistantText = '컬리에서 고당도 수박 1kg를 찾았어요. 9,900원인데 담아드릴까요?';
        return;
      case ShoppingVoicePreviewPreset.askQuantity:
        _step = ShoppingStep.askQuantity;
        _voiceTurnState = VoiceTurnState.userCanSpeak;
        _currentProduct = primaryProduct;
        _assistantText = '좋아요. 몇 개 담아드릴까요?';
        return;
      case ShoppingVoicePreviewPreset.addingToCart:
        _step = ShoppingStep.addingToCart;
        _voiceTurnState = VoiceTurnState.agentThinking;
        _currentProduct = primaryProduct;
        _upsertCartPreview(product: primaryProduct, quantity: 2);
        _cartStatusTitle = '장바구니 작업';
        _cartStatusText = '고당도 수박을 장바구니에 담고 있어요.';
        _cartHelperText = '옵션과 수량을 확인한 뒤 주문서에 반영하고 있어요.';
        _cartProgress = 0.72;
        _assistantText = '장바구니에 담고 있어요.';
        return;
      case ShoppingVoicePreviewPreset.askMoreOrCheckout:
        _step = ShoppingStep.askMoreOrCheckout;
        _voiceTurnState = VoiceTurnState.userCanSpeak;
        _upsertCartPreview(product: primaryProduct, quantity: 2);
        _upsertCartPreview(product: secondaryProduct, quantity: 1);
        _assistantText = '장바구니에 담았어요. 더 구매하시겠어요, 아니면 결제할까요?';
        return;
      case ShoppingVoicePreviewPreset.confirmAddress:
        _step = ShoppingStep.confirmAddress;
        _voiceTurnState = VoiceTurnState.userCanSpeak;
        _upsertCartPreview(product: primaryProduct, quantity: 2);
        _upsertCartPreview(product: secondaryProduct, quantity: 1);
        _checkoutSummary = CheckoutSummary(
          userName: userName,
          phone: '010-1234-5678',
          address: '서울 용산구 청파로47길 100 명신관 1층',
          items: List<CartItemViewData>.unmodifiable(_cartItems),
          totalPrice: 26700,
          deliveryRequest: '문 앞에 놓아주세요',
        );
        _assistantText = '배송지 맞으시면 확인해 주세요.';
        return;
      case ShoppingVoicePreviewPreset.enterPassword:
        _step = ShoppingStep.enterPassword;
        _voiceTurnState = VoiceTurnState.idle;
        _pin = '123';
        _assistantText = '결제를 위해 비밀번호 여섯 자리를 눌러주세요.';
        return;
      case ShoppingVoicePreviewPreset.processingPayment:
        _step = ShoppingStep.processingPayment;
        _voiceTurnState = VoiceTurnState.idle;
        _assistantText = '결제를 진행하고 있어요. 잠시만 기다려주세요.';
        return;
      case ShoppingVoicePreviewPreset.paymentCompleted:
        _step = ShoppingStep.paymentCompleted;
        _voiceTurnState = VoiceTurnState.idle;
        _assistantText = '주문이 완료됐어요. 내일 오전에 도착할 예정이에요.';
        return;
      case ShoppingVoicePreviewPreset.error:
        _step = ShoppingStep.error;
        _voiceTurnState = VoiceTurnState.error;
        _errorMessage = 'agent_request_failed';
        _assistantText = '잘 못 들었어요. 다시 한번 말씀해 주세요.';
        return;
    }
  }

  int get shoppingProgressStepIndex {
    switch (_step) {
      case ShoppingStep.askProduct:
      case ShoppingStep.searchingProduct:
        return 0;
      case ShoppingStep.showProduct:
      case ShoppingStep.askQuantity:
        return 1;
      case ShoppingStep.addingToCart:
      case ShoppingStep.cartCompleted:
      case ShoppingStep.askMoreOrCheckout:
        return 2;
      case ShoppingStep.confirmAddress:
      case ShoppingStep.enterPassword:
      case ShoppingStep.processingPayment:
      case ShoppingStep.paymentCompleted:
        return 3;
      case ShoppingStep.error:
        return 0;
    }
  }

  bool get shouldShowListeningHint =>
      _voiceTurnState == VoiceTurnState.userCanSpeak ||
      _voiceTurnState == VoiceTurnState.userRecording;
  bool get shouldShowReplyExamples =>
      _voiceTurnState != VoiceTurnState.agentThinking &&
      _voiceTurnState != VoiceTurnState.agentSpeaking &&
      suggestedReplies.isNotEmpty;
  List<String> get suggestedReplies {
    switch (_step) {
      case ShoppingStep.askProduct:
        return const ['토마토 사고 싶어', '삼겹살 1근 구매해줘', '감귤 2박스 담아줘'];
      case ShoppingStep.askQuantity:
        return const ['한 개', '두 개', '세 개'];
      case ShoppingStep.showProduct:
        return const ['응 이거 담을래'];
      case ShoppingStep.askMoreOrCheckout:
      case ShoppingStep.cartCompleted:
        return const ['이제 결제할래'];
      case ShoppingStep.confirmAddress:
        return const ['배송지 맞아'];
      case ShoppingStep.error:
        return const ['다시 말할게', '처음부터 할게'];
      case ShoppingStep.searchingProduct:
      case ShoppingStep.addingToCart:
      case ShoppingStep.enterPassword:
      case ShoppingStep.processingPayment:
      case ShoppingStep.paymentCompleted:
        return const [];
    }
  }

  String get cartOwnerName =>
      (_userName?.trim().isNotEmpty ?? false) ? _userName!.trim() : '김영희';
  int get totalCartQuantity =>
      _cartItems.fold<int>(0, (sum, item) => sum + item.quantity);
  int get totalCartPrice => _cartItems.fold<int>(
    0,
    (sum, item) =>
        sum + (item.totalPrice ?? (item.product.price ?? 0) * item.quantity),
  );
  String get totalCartPriceText => '${_formatCartPrice(totalCartPrice)}원';

  Future<void> initialize() async {
    if (_isInitialized) {
      return;
    }
    _userId = await _agentService.resolveUserId();
    _userName = await _agentService.resolveUserName(userId: _userId);
    await SttVadResponseLogService.instance.init();
    debugPrint(
      '📝 [STT/VAD Log] active_path=${SttVadResponseLogService.instance.currentLogPath}',
    );
    await _voiceTurnService.init();
    _isInitialized = true;
    notifyListeners();
    await _presentPrompt(
      'initial_prompt',
      payload: {'username': _userName},
      nextStep: ShoppingStep.askProduct,
      expectVoiceReply: true,
    );
  }

  Future<void> resetConversation() async {
    final activeConversationId = _conversationId;
    _speakEpoch += 1;
    _speechRunId += 1;
    _cartTimer?.cancel();
    _paymentTimer?.cancel();
    _completionSequenceTimer?.cancel();
    _conversationId = null;
    _userName ??= await _agentService.resolveUserName(userId: _userId);
    _currentProduct = null;
    _cartItems.clear();
    _checkoutSummary = null;
    _errorMessage = null;
    _isMockMode = false;
    _currentQuantity = 1;
    _pin = '';
    _cartProgress = 0.18;
    _voiceLevel = 0.22;
    _closeAppRequested = false;
    _lastWebviewTask = null;
    _pendingWebviewTask = null;
    _activeSearchKeyword = null;
    _partialTranscript = null;
    _turnContinuationCount = 0;
    _agentProgressRunId += 1;
    await _agentProgressSubscription?.cancel();
    _agentProgressSubscription = null;
    await _agentService.disconnectProgress();
    _cancelVoiceTimers();
    await _voiceTurnService.stopSpeaking();
    await _voiceTurnService.cancelRecording();
    if (activeConversationId != null) {
      try {
        await _agentService.cancelConversation(activeConversationId);
      } catch (error, stackTrace) {
        debugPrint(
          '⚠️ [ShoppingFlowController] cancel conversation failed: $error\n$stackTrace',
        );
      }
    }
    await _presentPrompt(
      'initial_prompt',
      payload: {'username': _userName},
      nextStep: ShoppingStep.askProduct,
      expectVoiceReply: true,
    );
  }

  Future<void> onVoiceButtonTap() async {
    _suppressAutoVoiceReply = false;
    if (_voiceTurnState == VoiceTurnState.userRecording) {
      await _finishRecording(epoch: _speakEpoch);
      return;
    }
    if (_voiceTurnState == VoiceTurnState.userCanSpeak) {
      await _beginAutomaticListening(_speakEpoch);
    }
  }

  Future<void> submitSuggestedReply(String reply) async {
    final normalizedReply = reply.trim();
    if (normalizedReply.isEmpty) {
      return;
    }
    _suppressAutoVoiceReply = false;
    _latestTranscript = normalizedReply;
    notifyListeners();
    await _handleUserTranscript(normalizedReply);
  }

  Future<void> onPasswordDigit(int digit) async {
    if (_step != ShoppingStep.enterPassword || _pin.length >= 6) {
      return;
    }
    _pin = '$_pin$digit';
    notifyListeners();
    if (_pin.length == 6) {
      _step = ShoppingStep.processingPayment;
      notifyListeners();
      await _startPaymentProcessingFlow();
    }
  }

  void removePasswordDigit() {
    if (_pin.isEmpty) {
      return;
    }
    _pin = _pin.substring(0, _pin.length - 1);
    notifyListeners();
  }

  Future<void> stopListeningForTextInput() async {
    _suppressAutoVoiceReply = true;
    if (_voiceTurnState == VoiceTurnState.userCanSpeak ||
        _voiceTurnState == VoiceTurnState.userRecording) {
      _cancelVoiceTimers(keepCartAndPaymentTimers: true);
      await _voiceTurnService.cancelRecording();
      _voiceTurnState = VoiceTurnState.idle;
      notifyListeners();
    }
  }

  Future<void> submitTextInput(String text) async {
    if (_voiceTurnState == VoiceTurnState.agentThinking ||
        _voiceTurnState == VoiceTurnState.agentSpeaking) {
      return;
    }
    _suppressAutoVoiceReply = true;
    _cancelVoiceTimers(keepCartAndPaymentTimers: true);
    await _voiceTurnService.cancelRecording();
    await _handleUserTranscript(text.trim());
  }

  void setTextInputMode(bool enabled) {
    _suppressAutoVoiceReply = enabled;
  }

  Future<void> _handleUserTranscript(String transcript) async {
    _cancelVoiceTimers(keepCartAndPaymentTimers: true);
    _partialTranscript = null;
    _turnContinuationCount = 0;
    _voiceTurnState = VoiceTurnState.agentThinking;
    _errorMessage = null;
    final normalizedTranscript = transcript.trim();
    if (normalizedTranscript.isEmpty) {
      debugPrint('[VAD] transcript_empty_after_stt');
      await _handleSttFailure();
      return;
    }
    final shouldUseAgentProgress = _shouldUseAgentProgress();
    if (_step == ShoppingStep.askProduct) {
      _activeSearchKeyword = _extractSearchKeywordFromMessage(
        normalizedTranscript,
      );
      _step = ShoppingStep.searchingProduct;
      _assistantText = _buildSearchingAssistantMessage();
      notifyListeners();
    } else {
      notifyListeners();
    }

    try {
      String? progressChannelId;
      if (shouldUseAgentProgress) {
        progressChannelId = _nextProgressChannelId();
        await _bindAgentProgress(progressChannelId);
      }
      final response = _conversationId == null
          ? await _agentService.startShopping(
              userId: _userId,
              message: normalizedTranscript,
              progressChannelId: progressChannelId,
            )
          : await _agentService.sendMessage(
              conversationId: _conversationId!,
              message: normalizedTranscript,
              progressChannelId: progressChannelId,
            );
      await _clearAgentProgressBinding();
      _conversationId = response.conversationId ?? _conversationId;
      await _consumeAgentResponse(response, normalizedTranscript);
    } catch (error, stackTrace) {
      await _clearAgentProgressBinding();
      debugPrint(
        '⚠️ [ShoppingFlowController] agent fallback: $error\n$stackTrace',
      );
      _isMockMode = false;
      _errorMessage = 'agent_request_failed';
      _voiceTurnState = VoiceTurnState.error;
      notifyListeners();
    }
  }

  bool _shouldUseAgentProgress() =>
      _step == ShoppingStep.askProduct ||
      _step == ShoppingStep.cartCompleted ||
      _step == ShoppingStep.askMoreOrCheckout;

  String _nextProgressChannelId() =>
      'shopping_${DateTime.now().microsecondsSinceEpoch}_${++_agentProgressRunId}';

  Future<void> _bindAgentProgress(String channelId) async {
    await _clearAgentProgressBinding();
    final runId = _agentProgressRunId;
    try {
      final stream = await _agentService.connectProgress(channelId);
      _agentProgressSubscription = stream.listen(
        (response) {
          unawaited(_consumeAgentProgress(response, runId));
        },
        onError: (Object error, StackTrace stackTrace) {
          debugPrint(
            '⚠️ [ShoppingFlowController] agent progress stream error: '
            '$error\n$stackTrace',
          );
        },
      );
    } catch (error, stackTrace) {
      debugPrint(
        '⚠️ [ShoppingFlowController] connect agent progress failed: '
        '$error\n$stackTrace',
      );
    }
  }

  Future<void> _clearAgentProgressBinding() async {
    _agentProgressRunId += 1;
    await _agentProgressSubscription?.cancel();
    _agentProgressSubscription = null;
    await _agentService.disconnectProgress();
  }

  Future<void> _consumeAgentProgress(
    ShoppingAgentResponse response,
    int runId,
  ) async {
    if (runId != _agentProgressRunId ||
        _step != ShoppingStep.searchingProduct ||
        response.assistantMessage.trim().isEmpty) {
      return;
    }
    await _presentAssistant(
      _normalizeSearchingAssistantMessage(response.assistantMessage),
      speechSegments: response.speechSegments,
      nextStep: ShoppingStep.searchingProduct,
      expectVoiceReply: false,
    );
  }

  Future<void> _consumeAgentResponse(
    ShoppingAgentResponse response,
    String transcript,
  ) async {
    final previousStep = _step;
    final inferredStep = _inferStep(response);
    final responseCartItems = _agentService.extractCartItems(response);
    if (responseCartItems.isNotEmpty) {
      _cartItems
        ..clear()
        ..addAll(responseCartItems);
    }
    final parsedProduct = _agentService.extractProduct(response);
    if (parsedProduct != null) {
      _currentProduct = _mergeWithFallback(parsedProduct);
    } else if (inferredStep == ShoppingStep.showProduct) {
      _currentProduct = null;
    }
    if (_shouldClearCurrentProduct(inferredStep, response)) {
      _currentProduct = null;
    }

    await _logUnexpectedReaskIfNeeded(
      transcript: transcript,
      previousStep: previousStep,
      inferredStep: inferredStep,
      response: response,
    );

    switch (inferredStep) {
      case ShoppingStep.showProduct:
        final productMessage = response.assistantMessage.trim();
        if (productMessage.isEmpty) {
          _errorMessage = 'empty_product_response';
          _voiceTurnState = VoiceTurnState.error;
          notifyListeners();
          return;
        }
        await _presentAssistant(
          productMessage,
          speechSegments: response.speechSegments,
          nextStep: ShoppingStep.showProduct,
          expectVoiceReply: true,
        );
        return;
      case ShoppingStep.askQuantity:
        if (response.assistantMessage.trim().isEmpty) {
          _errorMessage = 'empty_quantity_response';
          _voiceTurnState = VoiceTurnState.error;
          notifyListeners();
          return;
        }
        await _presentAssistant(
          response.assistantMessage,
          speechSegments: response.speechSegments,
          nextStep: ShoppingStep.askQuantity,
          expectVoiceReply: true,
        );
        return;
      case ShoppingStep.confirmAddress:
        final errorMap = response.error is Map
            ? Map<String, dynamic>.from(response.error as Map)
            : const <String, dynamic>{};
        final shouldUseMockAddress =
            response.deliveryAddress == null &&
            ((response.stage ?? '').toLowerCase().contains(
                  'address_required',
                ) ||
                errorMap['code']?.toString() == 'DEFAULT_ADDRESS_NOT_FOUND');
        _checkoutSummary = shouldUseMockAddress
            ? CheckoutSummary.mock(_cartItems)
            : (response.deliveryAddress != null || response.cart != null
                  ? _agentService.checkoutSummaryFromResponse(
                      response,
                      fallbackItems: _cartItems,
                    )
                  : await _agentService.fetchCheckoutSummary(
                      userId: _userId,
                      items: _cartItems,
                      deliveryAddress: response.deliveryAddress,
                    ));
        if (shouldUseMockAddress) {
          await _presentPrompt(
            'confirm_address',
            nextStep: ShoppingStep.confirmAddress,
            expectVoiceReply: true,
          );
          return;
        }
        if (response.assistantMessage.trim().isEmpty) {
          _errorMessage = 'empty_address_response';
          _voiceTurnState = VoiceTurnState.error;
          notifyListeners();
          return;
        }
        await _presentAssistant(
          response.assistantMessage,
          speechSegments: response.speechSegments,
          nextStep: ShoppingStep.confirmAddress,
          expectVoiceReply: true,
        );
        return;
      case ShoppingStep.enterPassword:
        if (response.assistantMessage.trim().isEmpty) {
          _errorMessage = 'empty_payment_password_response';
          _voiceTurnState = VoiceTurnState.error;
          notifyListeners();
          return;
        }
        await _presentAssistant(
          response.assistantMessage,
          speechSegments: response.speechSegments,
          nextStep: ShoppingStep.enterPassword,
          expectVoiceReply: false,
        );
        return;
      case ShoppingStep.addingToCart:
        _lastWebviewTask =
            response.pendingConfirmation?['type']?.toString() == 'webview_task'
            ? response.pendingConfirmation?['payload']?['task']?.toString()
            : response.uiCommand?['task']?.toString();
        _pendingWebviewTask = _agentService.extractWebviewTask(
          response,
          fallbackProduct: _currentProduct,
          defaultQuantity: _currentQuantity,
        );
        await _startCartProgressFlow(
          waitForWebview: _pendingWebviewTask != null,
          introText: response.assistantMessage,
          introSpeechSegments: response.speechSegments,
        );
        return;
      case ShoppingStep.askMoreOrCheckout:
        if (response.assistantMessage.trim().isEmpty) {
          _errorMessage = 'empty_checkout_choice_response';
          _voiceTurnState = VoiceTurnState.error;
          notifyListeners();
          return;
        }
        await _presentAssistant(
          response.assistantMessage,
          speechSegments: response.speechSegments,
          nextStep: ShoppingStep.askMoreOrCheckout,
          expectVoiceReply: true,
        );
        return;
      case ShoppingStep.paymentCompleted:
        if (response.assistantMessage.trim().isEmpty) {
          _errorMessage = 'empty_payment_completed_response';
          _voiceTurnState = VoiceTurnState.error;
          notifyListeners();
          return;
        }
        await _showPaymentCompleted(
          response.assistantMessage,
          speechSegments: response.speechSegments,
        );
        return;
      case ShoppingStep.searchingProduct:
        _step = ShoppingStep.searchingProduct;
        final searchingAssistantMessage = _normalizeSearchingAssistantMessage(
          response.assistantMessage,
        );
        if (searchingAssistantMessage.trim().isNotEmpty &&
            searchingAssistantMessage.trim() != _assistantText.trim()) {
          _assistantText = searchingAssistantMessage;
        }
        _voiceTurnState = VoiceTurnState.agentThinking;
        notifyListeners();
        return;
      case ShoppingStep.error:
        _errorMessage = response.assistantMessage;
        if (response.assistantMessage.trim().isNotEmpty) {
          await _presentAssistant(
            response.assistantMessage,
            speechSegments: response.speechSegments,
            nextStep: ShoppingStep.error,
            expectVoiceReply: true,
          );
          return;
        }
        _voiceTurnState = VoiceTurnState.error;
        notifyListeners();
        return;
      case ShoppingStep.askProduct:
        if (response.assistantMessage.trim().isEmpty) {
          _errorMessage = 'empty_restart_response';
          _voiceTurnState = VoiceTurnState.error;
          notifyListeners();
          return;
        }
        await _presentAssistant(
          response.assistantMessage,
          speechSegments: response.speechSegments,
          nextStep: ShoppingStep.askProduct,
          expectVoiceReply: true,
        );
        return;
      case ShoppingStep.cartCompleted:
      case ShoppingStep.processingPayment:
        break;
    }
  }

  Future<void> _handleSttFailure() async {
    _voiceTurnState = VoiceTurnState.error;
    notifyListeners();
    await Future<void>.delayed(const Duration(milliseconds: 420));
    await _presentPrompt(
      'stt_retry',
      nextStep: _step == ShoppingStep.searchingProduct
          ? ShoppingStep.askProduct
          : _step,
      expectVoiceReply: true,
    );
  }

  Future<void> _startCartProgressFlow({
    bool waitForWebview = false,
    String? introText,
    List<SpeechSegmentViewData> introSpeechSegments = const [],
  }) async {
    _cartTimer?.cancel();
    _step = ShoppingStep.addingToCart;
    _voiceTurnState = VoiceTurnState.idle;
    final effectiveIntroText = introText?.trim();
    if (effectiveIntroText != null && effectiveIntroText.isNotEmpty) {
      await _presentAssistant(
        effectiveIntroText,
        speechSegments: introSpeechSegments,
        nextStep: ShoppingStep.addingToCart,
        expectVoiceReply: false,
      );
    } else {
      await _presentPrompt(
        'adding_to_cart',
        nextStep: ShoppingStep.addingToCart,
        expectVoiceReply: false,
      );
    }
    _cartStatusTitle = '장바구니 작업';
    _cartStatusText = _cartStatusTextForTask();
    _cartHelperText = _cartHelperTextForTask();
    _cartProgress = 0.2;
    notifyListeners();

    if (waitForWebview) {
      return;
    }

    _cartTimer = Timer.periodic(const Duration(milliseconds: 650), (timer) {
      _cartProgress = (_cartProgress + 0.16).clamp(0.0, 0.96);
      if (timer.tick == 1) {
        _cartStatusText = '상품을 확인하고 있어요.';
      } else if (timer.tick == 2) {
        _cartStatusText = '장바구니에 상품을 담고 있어요.';
      } else if (timer.tick >= 3) {
        _cartStatusText = '마무리하고 있어요.';
        _cartHelperText = '잠시만 기다려주세요.';
      }
      notifyListeners();
    });
    await Future<void>.delayed(const Duration(seconds: 3));
    _cartTimer?.cancel();
    _cartProgress = 1;
    await _presentPrompt(
      'cart_completed',
      nextStep: ShoppingStep.askMoreOrCheckout,
      expectVoiceReply: true,
    );
  }

  Future<void> handleWebviewResult(
    WebviewTaskViewData task, {
    required String result,
    Map<String, dynamic>? extraData,
  }) async {
    if (_conversationId == null) {
      return;
    }
    _pendingWebviewTask = null;
    _cartTimer?.cancel();
    _voiceTurnState = VoiceTurnState.agentThinking;
    if (result == 'cart_added') {
      _upsertCartPreview(
        product: _currentProduct,
        quantity: task.quantity > 0 ? task.quantity : _currentQuantity,
      );
    }
    _cartStatusText = result == 'cart_added'
        ? '장바구니 결과를 확인하고 있어요.'
        : '쇼핑 진행 상태를 확인하고 있어요.';
    _cartHelperText = '잠시만 기다려주세요.';
    notifyListeners();

    try {
      final response = await _agentService.sendWebviewResult(
        conversationId: _conversationId!,
        orderId: task.orderId,
        paymentId: task.paymentId,
        result: result,
        extraData: extraData,
      );
      debugPrint(
        'ℹ️ [ShoppingFlowController] webview_result_synced '
        'result=$result '
        'stage=${response.stage} '
        'assistant="${response.assistantMessage}" '
        'pendingType=${response.pendingConfirmation?['type']}',
      );
      _conversationId = response.conversationId ?? _conversationId;
      await _consumeAgentResponse(response, _latestTranscript ?? '');
    } catch (error, stackTrace) {
      debugPrint(
        '⚠️ [ShoppingFlowController] webview result fallback: $error\n$stackTrace',
      );
      _pendingWebviewTask = task;
      _voiceTurnState = VoiceTurnState.idle;
      notifyListeners();
      rethrow;
    }
  }

  Future<void> _startPaymentProcessingFlow() async {
    _paymentTimer?.cancel();
    _completionSequenceTimer?.cancel();
    await _presentPrompt(
      'processing_payment',
      nextStep: ShoppingStep.processingPayment,
      expectVoiceReply: false,
    );
    _paymentTimer = Timer(const Duration(milliseconds: 1600), () {
      unawaited(_showPaymentCompleted(''));
    });
  }

  Future<void> _showPaymentCompleted(
    String text, {
    List<SpeechSegmentViewData> speechSegments = const [],
  }) async {
    _completionSequenceTimer?.cancel();
    if (text.trim().isEmpty) {
      await _presentPrompt(
        'payment_completed',
        nextStep: ShoppingStep.paymentCompleted,
        expectVoiceReply: false,
      );
      _scheduleFarewellSequence();
      return;
    }
    await _presentAssistant(
      text,
      speechSegments: speechSegments,
      nextStep: ShoppingStep.paymentCompleted,
      expectVoiceReply: false,
    );
    _scheduleFarewellSequence();
  }

  void consumeCloseAppRequest() {
    _closeAppRequested = false;
  }

  void _scheduleFarewellSequence() {
    final sequenceEpoch = _speakEpoch;
    _completionSequenceTimer = Timer(const Duration(milliseconds: 2300), () {
      unawaited(_runFarewellSequence(sequenceEpoch));
    });
  }

  Future<void> _runFarewellSequence(int sequenceEpoch) async {
    if (sequenceEpoch != _speakEpoch ||
        _step != ShoppingStep.paymentCompleted) {
      return;
    }
    try {
      await _presentPrompt(
        'farewell_prompt',
        nextStep: ShoppingStep.paymentCompleted,
        expectVoiceReply: false,
      );
    } catch (error, stackTrace) {
      debugPrint(
        '⚠️ [ShoppingFlowController] farewell prompt failed: $error\n$stackTrace',
      );
      await _presentAssistant(
        '오늘도 딸랑구를 이용해주셔서 감사해요. 다음에 또 봐요!',
        nextStep: ShoppingStep.paymentCompleted,
        expectVoiceReply: false,
      );
    }
    if (_step != ShoppingStep.paymentCompleted) {
      return;
    }
    _closeAppRequested = true;
    notifyListeners();
  }

  Future<void> _presentAssistant(
    String text, {
    List<SpeechSegmentViewData> speechSegments = const [],
    required ShoppingStep nextStep,
    required bool expectVoiceReply,
  }) async {
    _cancelVoiceTimers();
    final epoch = ++_speakEpoch;
    final hasSegmentedSpeech =
        speechSegments.isNotEmpty && !_shouldBypassTtsForDemo;
    _step = nextStep;
    _assistantText = hasSegmentedSpeech
        ? speechSegments.first.text.trim()
        : text;
    _assistantTtsDurationMs = hasSegmentedSpeech
        ? speechSegments.fold(0, (sum, s) => sum + (s.durationMs ?? 0))
        : 0;
    _voiceTurnState = VoiceTurnState.agentSpeaking;
    _voiceLevel = 0.22;
    notifyListeners();
    if (hasSegmentedSpeech) {
      await _presentAssistantSpeechQueue(text, speechSegments, epoch);
    } else if (_shouldBypassTtsForDemo) {
      await _presentAssistantSilently(text, epoch);
    } else {
      try {
        await _voiceTurnService.speak(text);
      } catch (_) {
        await Future<void>.delayed(_estimateSilentSegmentDuration(text));
      }
    }
    if (epoch != _speakEpoch) {
      return;
    }
    if (expectVoiceReply) {
      _voiceTurnState = VoiceTurnState.userCanSpeak;
      _voiceLevel = 0.26;
      notifyListeners();
      if (_suppressAutoVoiceReply || textInputMode) {
        debugPrint(
          '[VAD] auto_listening_suppressed '
          'epoch=$epoch step=${_step.name} '
          'text_input_mode=$textInputMode',
        );
        return;
      }
      final shouldStartListeningImmediately = _isRetryPromptText(text);
      final userTurnDelay = _userTurnDelayForPrompt(
        isRetryPrompt: shouldStartListeningImmediately,
      );
      final now = DateTime.now();
      _lastUserTurnReadyAt = now;
      final ttsEndedAt = _voiceTurnService.lastTtsPlaybackEndedAt;
      debugPrint(
        '[VAD] user_turn_ready '
        'epoch=$epoch immediate=$shouldStartListeningImmediately '
        'delayMs=${userTurnDelay.inMilliseconds} '
        'at=${now.toIso8601String()} '
        'deltaSinceTtsEndMs=${_elapsedMsSince(ttsEndedAt, now)} '
        'text="${text.trim()}"',
      );
      _userTurnTimer = Timer(userTurnDelay, () {
        unawaited(_beginAutomaticListening(epoch));
      });
      return;
    }
    _voiceTurnState = VoiceTurnState.idle;
    notifyListeners();
  }

  Future<void> _presentAssistantSpeechQueue(
    String fallbackText,
    List<SpeechSegmentViewData> speechSegments,
    int epoch,
  ) async {
    final playableSegments = speechSegments
        .where((segment) => _resolveSegmentAudioUrl(segment.audioUrl) != null)
        .length;
    if (playableSegments == 0) {
      debugPrint(
        '[TTS] segmented_queue_text_only '
        'epoch=$epoch playable=0 total=${speechSegments.length} '
        'fallback_to_silent_segments=true',
      );
      await _presentAssistantSilently(fallbackText, epoch);
      return;
    }
    if (playableSegments < speechSegments.length) {
      debugPrint(
        '[TTS] segmented_queue_partial_audio '
        'epoch=$epoch playable=$playableSegments total=${speechSegments.length} '
        'fallback_to_full_message=false',
      );
    }

    final runId = ++_speechRunId;
    for (final segment in speechSegments) {
      if (epoch != _speakEpoch || runId != _speechRunId) {
        await _voiceTurnService.stopSpeaking();
        return;
      }

      _assistantText = segment.text;
      notifyListeners();

      final audioUrl = _resolveSegmentAudioUrl(segment.audioUrl);
      if (audioUrl == null) {
        debugPrint(
          '[TTS] missing_audio_url '
          'runId=$runId epoch=$epoch index=${segment.index} text="${segment.text}"',
        );
        await Future<void>.delayed(
          _estimateSilentSegmentDuration(segment.text),
        );
        continue;
      }

      try {
        final startedAt = DateTime.now();
        await _voiceTurnService.playAudioUrl(
          audioUrl,
          expectedDurationMs: segment.durationMs,
        );
        await _ensureMinimumSpeechWindow(
          startedAt: startedAt,
          expected: Duration(
            milliseconds: (segment.durationMs ?? 1600).clamp(900, 5000),
          ),
        );
      } catch (error, stackTrace) {
        debugPrint(
          '[TTS] segment_playback_failed '
          'runId=$runId epoch=$epoch index=${segment.index} url="$audioUrl" '
          'text="${segment.text}" error=$error\n$stackTrace',
        );
        await Future<void>.delayed(
          _estimateSilentSegmentDuration(segment.text),
        );
      }
    }

    if (epoch == _speakEpoch &&
        runId == _speechRunId &&
        speechSegments.isEmpty &&
        fallbackText.isNotEmpty) {
      _assistantText = fallbackText;
      notifyListeners();
    }
  }

  Future<void> _presentAssistantSilently(String text, int epoch) async {
    final segments = _splitDisplaySegments(text);
    for (final segment in segments) {
      if (epoch != _speakEpoch) {
        return;
      }
      _assistantText = segment;
      notifyListeners();
      await Future.delayed(_estimateSilentSegmentDuration(segment));
    }
  }

  List<String> _splitDisplaySegments(String text) {
    final normalized = text
        .replaceAll('\n', ' ')
        .split(RegExp(r'\s+'))
        .where((part) => part.isNotEmpty)
        .join(' ')
        .trim();
    if (normalized.isEmpty) {
      return const [''];
    }

    final matches = RegExp(r'[^.!?。！？]+[.!?。！？]?').allMatches(normalized);
    final sentenceSegments = matches
        .map((match) => match.group(0)?.trim() ?? '')
        .where((segment) => segment.isNotEmpty)
        .toList();
    final baseSegments = sentenceSegments.isEmpty
        ? [normalized]
        : sentenceSegments;
    return baseSegments;
  }

  Duration _estimateSilentSegmentDuration(String segment) {
    final runeLength = segment.runes.length;
    final estimatedMs = 900 + (runeLength * 70);
    return Duration(milliseconds: estimatedMs.clamp(1100, 3200));
  }

  String? _resolveSegmentAudioUrl(String? rawUrl) {
    final trimmed = rawUrl?.trim();
    if (trimmed == null || trimmed.isEmpty) {
      return null;
    }
    if (trimmed.startsWith('http://') || trimmed.startsWith('https://')) {
      return trimmed;
    }

    final base = ApiClient.baseUrl.trim();
    if (base.isEmpty) {
      return trimmed;
    }
    final normalizedBase = base.endsWith('/')
        ? base.substring(0, base.length - 1)
        : base;
    final normalizedPath = trimmed.startsWith('/') ? trimmed : '/$trimmed';
    return '$normalizedBase$normalizedPath';
  }

  Future<void> _presentPrompt(
    String kind, {
    Map<String, dynamic>? payload,
    required ShoppingStep nextStep,
    required bool expectVoiceReply,
  }) async {
    final response = await _agentService.fetchPrompt(
      kind: kind,
      conversationId: _conversationId,
      payload: payload,
    );
    await _presentAssistant(
      response.assistantMessage,
      speechSegments: response.speechSegments,
      nextStep: nextStep,
      expectVoiceReply: expectVoiceReply,
    );
  }

  Future<void> _ensureMinimumSpeechWindow({
    required DateTime startedAt,
    required Duration expected,
  }) async {
    final minimumMs = (expected.inMilliseconds * _speechGuardRatio)
        .round()
        .clamp(700, 4200);
    final elapsedMs = DateTime.now().difference(startedAt).inMilliseconds;
    final remainingMs = minimumMs - elapsedMs;
    if (remainingMs > 0) {
      await Future<void>.delayed(Duration(milliseconds: remainingMs));
    }
  }

  Future<void> _beginAutomaticListening(int epoch) async {
    if (epoch != _speakEpoch ||
        _voiceTurnState != VoiceTurnState.userCanSpeak) {
      return;
    }

    final effectiveInitialWait = _currentInitialSpeechWaitTimeout();
    final effectiveMaxRecording = _currentMaxRecordingDuration();

    _hasDetectedSpeech = false;
    _noiseSampleCount = 0;
    _speechNoiseFloor = -45;
    _recordingStartedAt = DateTime.now();
    _lastListeningBeginRequestedAt = _recordingStartedAt;
    _firstSpeechDetectedAt = null;
    _lastSpeechDetectedAt = null;
    _lastVadDebugAt = null;
    _lastUserTurnReadyAt ??= _recordingStartedAt;
    _silenceCandidateStartedAt = null;
    _isAmplitudeTelemetryUnreliable = false;
    _isAwaitingSilenceConfirmation = false;
    _amplitudeSampleCount = 0;
    _zeroishAmplitudeCount = 0;
    _speechStartCandidateCount = 0;
    _hasLoggedFirstLiveAmplitude = false;
    _voiceTurnState = VoiceTurnState.userRecording;
    _voiceLevel = 0.34;

    notifyListeners();

    debugPrint(
      '[VAD Timeline] begin_listening '
      'epoch=$epoch '
      'at=${_recordingStartedAt!.toIso8601String()} '
      'deltaSinceTtsEndMs=${_elapsedMsSince(_voiceTurnService.lastTtsPlaybackEndedAt, _recordingStartedAt)} '
      'deltaSinceUserTurnReadyMs=${_elapsedMsSince(_lastUserTurnReadyAt, _recordingStartedAt)}',
    );

    try {
      await _voiceTurnService.playStartListeningCue();
      await _voiceTurnService.startRecording();

      if (!_canContinueUserRecording(epoch)) {
        await _voiceTurnService.cancelRecording();
        return;
      }

      final recorderStartedAt = _voiceTurnService.lastRecordingStartedAt;
      debugPrint(
        '[VAD Timeline] recorder_started '
        'epoch=$epoch '
        'at=${recorderStartedAt?.toIso8601String() ?? 'unknown'} '
        'deltaSinceTtsEndMs=${_elapsedMsSince(_voiceTurnService.lastTtsPlaybackEndedAt, recorderStartedAt)} '
        'deltaSinceBeginListeningMs=${_elapsedMsSince(_lastListeningBeginRequestedAt, recorderStartedAt)}',
      );

      _listenAmplitude(epoch);
      _listenRecognitionEvents(epoch);

      if (_isNativeAsrMode) {
        _recordingTimeoutTimer = Timer(effectiveMaxRecording, () {
          if (!_canContinueUserRecording(epoch)) return;
          debugPrint(
            '[Native ASR] final_timeout '
            'captureMs=${effectiveMaxRecording.inMilliseconds}',
          );
          unawaited(_finishRecording(epoch: epoch));
        });
        return;
      }

      if (_manualStopRecordingEnabled) {
        _recordingTimeoutTimer = Timer(_manualStopSafetyTimeout, () {
          if (!_canContinueUserRecording(epoch)) return;
          debugPrint(
            '[VAD] manual_stop_safety_timeout '
            'captureMs=${_manualStopSafetyTimeout.inMilliseconds}',
          );
          unawaited(_finishRecording(epoch: epoch));
        });
        return;
      }

      _recordingTimeoutTimer = Timer(effectiveMaxRecording, () {
        if (!_canContinueUserRecording(epoch)) return;
        unawaited(_finishRecording(epoch: epoch));
      });

      _speechSilenceTimer = Timer(effectiveInitialWait, () async {
        if (!_canContinueUserRecording(epoch) || _hasDetectedSpeech) {
          return;
        }

        await _voiceTurnService.cancelRecording();
        _cancelVoiceTimers(keepCartAndPaymentTimers: true);

        if (!_isActiveEpoch(epoch)) return;

        await _presentPrompt(
          'stt_retry_gentle',
          nextStep: _step,
          expectVoiceReply: true,
        );
      });
    } catch (error, stackTrace) {
      debugPrint(
        '⚠️ [VAD] recording_start_failed '
        'step=$_step epoch=$epoch error=$error\n$stackTrace',
      );

      _cancelVoiceTimers(keepCartAndPaymentTimers: true);
      await _voiceTurnService.cancelRecording();
      if (!_isActiveEpoch(epoch)) return;

      await _handleSttFailure();
    }
  }

  void _listenAmplitude(int epoch) {
    _amplitudeSubscription?.cancel();

    try {
      _amplitudeSubscription = _voiceTurnService
          .onAmplitudeChanged(interval: const Duration(milliseconds: 160))
          .listen((amplitude) {
            if (!_canContinueUserRecording(epoch)) return;

            final current = amplitude.current;
            final normalized = _normalizeAmplitude(current);
            _voiceLevel = normalized;
            if (_isNativeAsrMode) {
              _logNativeAsrAmplitude(current, epoch);
            } else {
              _updateVoiceActivity(current, epoch);
            }

            notifyListeners();
          });
    } catch (_) {
      // amplitude 연동이 불가능한 환경에서는 loop animation만 사용한다.
    }
  }

  void _listenRecognitionEvents(int epoch) {
    _recognitionEventSubscription?.cancel();

    try {
      _recognitionEventSubscription = _voiceTurnService
          .onRecognitionEvent()
          .listen((NativeSpeechRecognitionEvent event) {
            if (!_canContinueUserRecording(epoch)) return;
            switch (event.type) {
              case NativeSpeechRecognitionEventType.partial:
                _hasDetectedSpeech = true;
                _lastSpeechDetectedAt = DateTime.now();
                return;
              case NativeSpeechRecognitionEventType.result:
                final transcript = event.text?.trim() ?? '';
                debugPrint(
                  '[Native ASR] final_result_received '
                  'epoch=$epoch length=${transcript.length} text="$transcript"',
                );
                unawaited(_finishRecording(epoch: epoch));
                return;
              case NativeSpeechRecognitionEventType.error:
                if (event.recoverable) {
                  debugPrint(
                    '[Native ASR] recoverable_error_finish '
                    'epoch=$epoch code=${event.code} message="${event.message}" '
                    'hasSpeech=$_hasDetectedSpeech',
                  );
                  unawaited(_finishRecording(epoch: epoch));
                  return;
                }
                debugPrint(
                  '[Native ASR] terminal_error '
                  'epoch=$epoch code=${event.code} message="${event.message}"',
                );
                unawaited(_finishRecording(epoch: epoch));
                return;
              case NativeSpeechRecognitionEventType.state:
                final state = event.state ?? '';
                if (state == 'speech_begin') {
                  _hasDetectedSpeech = true;
                  _firstSpeechDetectedAt ??= DateTime.now();
                  _lastSpeechDetectedAt = DateTime.now();
                }
                return;
            }
          });
    } catch (_) {
      // native recognition event를 받을 수 없는 환경에서는 수동 종료 fallback을 사용한다.
    }
  }

  void _logNativeAsrAmplitude(double amplitude, int epoch) {
    if (!_canContinueUserRecording(epoch)) return;
    final effectiveAmplitude = _sanitizeAmplitude(amplitude);
    final now = DateTime.now();
    final zeroishAmplitude =
        effectiveAmplitude <= -159.0 || effectiveAmplitude.abs() < 0.1;

    if (!_hasLoggedFirstLiveAmplitude && !zeroishAmplitude) {
      _hasLoggedFirstLiveAmplitude = true;
      debugPrint(
        '[VAD Timeline] first_live_amplitude '
        'epoch=$epoch '
        'at=${now.toIso8601String()} '
        'amp=${effectiveAmplitude.toStringAsFixed(1)} '
        'deltaSinceTtsEndMs=${_elapsedMsSince(_voiceTurnService.lastTtsPlaybackEndedAt, now)} '
        'deltaSinceRecorderStartMs=${_elapsedMsSince(_voiceTurnService.lastRecordingStartedAt, now)} '
        'deltaSinceUserTurnReadyMs=${_elapsedMsSince(_lastUserTurnReadyAt, now)}',
      );
    }

    if (_lastVadDebugAt == null ||
        now.difference(_lastVadDebugAt!) >= const Duration(milliseconds: 480)) {
      _lastVadDebugAt = now;
      debugPrint(
        '[Native ASR] sample '
        'amp=${effectiveAmplitude.toStringAsFixed(1)} '
        'hasSpeech=$_hasDetectedSpeech',
      );
    }
  }

  Future<void> _finishRecording({required int epoch}) async {
    if (!_canContinueUserRecording(epoch)) {
      return;
    }

    final recordingStartedAt = _recordingStartedAt;
    final elapsedMs = recordingStartedAt == null
        ? null
        : DateTime.now().difference(recordingStartedAt).inMilliseconds;

    debugPrint(
      '[VAD] recording_stopped '
      'elapsedMs=${elapsedMs ?? -1} '
      'hasDetectedSpeech=$_hasDetectedSpeech '
      'lastSpeechAt=${_lastSpeechDetectedAt?.toIso8601String()} '
      'noiseFloor=${_speechNoiseFloor.toStringAsFixed(1)}',
    );

    _voiceTurnState = VoiceTurnState.transcribing;
    _voiceLevel = 0.4;
    notifyListeners();

    _cancelVoiceTimers(keepCartAndPaymentTimers: true);

    _firstSpeechDetectedAt = null;
    _lastSpeechDetectedAt = null;
    _recordingStartedAt = null;
    _silenceCandidateStartedAt = null;
    _isAwaitingSilenceConfirmation = false;

    try {
      final transcriptFuture = _voiceTurnService.stopRecordingAndTranscribe();
      unawaited(_voiceTurnService.playStopListeningCue());
      final transcript = await transcriptFuture;

      if (!_isActiveEpoch(epoch)) return;

      debugPrint(
        '[VAD] stt_result '
        'length=${transcript.trim().length} '
        'text="${transcript.trim()}"',
      );

      await _handleDetectedTurn(transcript, epoch: epoch);
    } catch (error, stackTrace) {
      debugPrint(
        '⚠️ [VAD] stop_or_transcribe_failed '
        'step=$_step error=$error\n$stackTrace',
      );

      if (!_isActiveEpoch(epoch)) return;
      await _handleSttFailure();
    }
  }

  Future<void> _handleDetectedTurn(
    String transcript, {
    required int epoch,
  }) async {
    final normalizedTranscript = transcript.trim();
    // "네", "응", "한" 같은 짧은 한국어 응답도 유효할 수 있으므로
    // 길이만으로 버리지 않고 turn detection으로 넘긴다.
    if (normalizedTranscript.isEmpty) {
      await _handleNoiseOrEmptyTurn(epoch);
      return;
    }

    final detection = await _detectTurnWithFallback(normalizedTranscript);
    debugPrint(
      '[TurnDetection] result=${detection.status.name} '
      'reason=${detection.reason} '
      'merged="${detection.mergedTranscript}" '
      'continuation=$_turnContinuationCount',
    );

    if (!_isActiveEpoch(epoch)) return;

    switch (detection.status) {
      case TurnDetectionStatus.complete:
        final merged = detection.mergedTranscript.trim();
        _latestTranscript = merged.isNotEmpty ? merged : normalizedTranscript;
        _partialTranscript = null;
        _turnContinuationCount = 0;
        _voiceLevel = 0.32;
        notifyListeners();
        await _handleUserTranscript(_latestTranscript!);
        return;
      case TurnDetectionStatus.incomplete:
        _partialTranscript = detection.mergedTranscript.trim().isNotEmpty
            ? detection.mergedTranscript.trim()
            : normalizedTranscript;
        _turnContinuationCount += 1;
        if (detection.shouldAskClarification ||
            _turnContinuationCount > _maxTurnContinuationCount) {
          await _askTurnClarification();
          return;
        }
        await _continueListeningWithoutTts(epoch);
        return;
      case TurnDetectionStatus.noiseOrEmpty:
        await _handleNoiseOrEmptyTurn(epoch);
        return;
    }
  }

  Future<TurnDetectionViewData> _detectTurnWithFallback(
    String transcript,
  ) async {
    try {
      return await _agentService.detectTurn(
        transcript: transcript,
        partialTranscript: _partialTranscript,
        step: _step.name,
        continuationCount: _turnContinuationCount,
      );
    } catch (error, stackTrace) {
      debugPrint('⚠️ [TurnDetection] backend fallback: $error\n$stackTrace');
      final merged = [
        if ((_partialTranscript ?? '').trim().isNotEmpty)
          _partialTranscript!.trim(),
        transcript.trim(),
      ].join(' ').trim();
      return TurnDetectionViewData(
        status: TurnDetectionStatus.complete,
        mergedTranscript: merged,
        reason: 'frontend_rule_complete_after_backend_error',
      );
    }
  }

  Future<void> _handleNoiseOrEmptyTurn(int epoch) async {
    if ((_partialTranscript ?? '').trim().isNotEmpty &&
        _turnContinuationCount <= _maxTurnContinuationCount) {
      _turnContinuationCount += 1;
      await _continueListeningWithoutTts(epoch);
      return;
    }
    await _handleSttFailure();
  }

  Future<void> _continueListeningWithoutTts(int epoch) async {
    if (!_isActiveEpoch(epoch)) return;
    _voiceTurnState = VoiceTurnState.userCanSpeak;
    _voiceLevel = 0.26;
    notifyListeners();
    unawaited(_beginAutomaticListening(epoch));
  }

  Future<void> _askTurnClarification() async {
    final partial = (_partialTranscript ?? '').trim();
    _partialTranscript = null;
    _turnContinuationCount = 0;
    final message = partial.isEmpty
        ? '다시 한 번만 말씀해주세요.'
        : '$partial라고 말씀하셨어요. 이어서 조금 더 구체적으로 말씀해주세요.';
    await _presentAssistant(message, nextStep: _step, expectVoiceReply: true);
  }

  ShoppingStep _inferStep(ShoppingAgentResponse response) {
    final pendingType = response.pendingConfirmation?['type']?.toString();
    final pendingPayload = response.pendingConfirmation?['payload'];
    final pendingSubType = pendingPayload is Map
        ? pendingPayload['subType']?.toString()
        : null;
    final stage = (response.stage ?? '').toLowerCase();
    final message = response.assistantMessage;

    if (message.contains('결제가 완료')) {
      return ShoppingStep.paymentCompleted;
    }
    if (_isRestartOrRetryPrompt(response)) {
      return ShoppingStep.askProduct;
    }
    if (pendingType == 'address' || stage.contains('address')) {
      return ShoppingStep.confirmAddress;
    }
    if (pendingType == 'payment' &&
        (pendingSubType == 'payment_password' || message.contains('비밀번호'))) {
      return ShoppingStep.enterPassword;
    }
    if (pendingType == 'webview_task' ||
        response.uiCommand?['type']?.toString() == 'open_webview' ||
        stage.contains('cart_processing') ||
        stage.contains('webview_cart')) {
      return ShoppingStep.addingToCart;
    }
    if (pendingType == 'quantity' || message.contains('몇 개')) {
      return ShoppingStep.askQuantity;
    }
    if (pendingType == 'product' ||
        response.recommendations.isNotEmpty ||
        response.selectedProduct != null) {
      return ShoppingStep.showProduct;
    }
    if (message.contains('다른 상품') || message.contains('더 구매')) {
      return ShoppingStep.askMoreOrCheckout;
    }
    if (stage.contains('searching')) {
      return ShoppingStep.searchingProduct;
    }
    if (response.error != null) {
      return ShoppingStep.error;
    }
    return _step;
  }

  bool _isRestartOrRetryPrompt(ShoppingAgentResponse response) {
    final pendingType = response.pendingConfirmation?['type']?.toString();
    final stage = (response.stage ?? '').toLowerCase();
    final message = response.assistantMessage.trim();
    if (pendingType == 'clarification') {
      return true;
    }
    if (stage.contains('clarification') || stage == 'idle') {
      if (message.contains('다시 말씀') ||
          message.contains('어떤 상품') ||
          message.contains('잘 못 들었') ||
          message.contains('무슨 말씀인지') ||
          message.contains('무슨 뜻인지') ||
          message.contains('찾지 못했') ||
          message.contains('죄송')) {
        return true;
      }
    }
    return message.contains('다시 말씀') ||
        message.contains('어떤 상품을') ||
        message.contains('무슨 말씀인지') ||
        message.contains('무슨 뜻인지');
  }

  bool _shouldClearCurrentProduct(
    ShoppingStep inferredStep,
    ShoppingAgentResponse response,
  ) {
    if (inferredStep == ShoppingStep.askProduct ||
        inferredStep == ShoppingStep.searchingProduct ||
        inferredStep == ShoppingStep.error) {
      return true;
    }
    return _isRestartOrRetryPrompt(response);
  }

  ProductViewData _mergeWithFallback(ProductViewData source) {
    final fallback = ProductViewData.mock(productUrl: source.productUrl);
    return ProductViewData(
      platform: source.platform ?? fallback.platform,
      shopName: source.shopName ?? fallback.shopName,
      productUrl: source.productUrl ?? fallback.productUrl,
      imageUrl: source.imageUrl ?? fallback.imageUrl,
      title: source.title,
      subtitle: source.subtitle ?? fallback.subtitle,
      quantityInfo: source.quantityInfo,
      price: source.price ?? fallback.price,
      priceText: source.priceText ?? fallback.priceText,
      badgeText: source.badgeText ?? fallback.badgeText,
    );
  }

  bool wantsCheckout(String text) {
    return RegExp(r'결제|이제|그만|아니|됐어', caseSensitive: false).hasMatch(text);
  }

  Future<void> confirmAddressStep() async {
    _pin = '';
    await _presentPrompt(
      'pin_prompt',
      nextStep: ShoppingStep.enterPassword,
      expectVoiceReply: false,
    );
  }

  double _normalizeAmplitude(double amplitude) {
    final sanitized = _sanitizeAmplitude(amplitude);
    final clamped = ((sanitized + 45) / 45).clamp(0.0, 1.0);
    return 0.22 + (clamped * 0.78);
  }

  void _updateVoiceActivity(double amplitude, int epoch) {
    if (!_canContinueUserRecording(epoch)) return;
    final effectiveAmplitude = _sanitizeAmplitude(amplitude);
    _amplitudeSampleCount += 1;
    final zeroishAmplitude =
        effectiveAmplitude <= -159.0 || effectiveAmplitude.abs() < 0.1;
    if (zeroishAmplitude) {
      _zeroishAmplitudeCount += 1;
    }

    final recordingStartedAt = _recordingStartedAt;
    final elapsedSinceRecordingStart = recordingStartedAt == null
        ? Duration.zero
        : DateTime.now().difference(recordingStartedAt);
    if (!_isAmplitudeTelemetryUnreliable &&
        elapsedSinceRecordingStart >= _vadAmplitudeWarmup &&
        _amplitudeSampleCount >= 12 &&
        _zeroishAmplitudeCount >= _amplitudeSampleCount - 1) {
      _isAmplitudeTelemetryUnreliable = true;
      if (_hasDetectedSpeech && !_manualStopRecordingEnabled) {
        _speechSilenceTimer?.cancel();
        _scheduleFallbackAutoStop(epoch);
      }
      debugPrint(
        '[VAD] amplitude_unreliable '
        'samples=$_amplitudeSampleCount '
        'zeroish=$_zeroishAmplitudeCount '
        'amp=${effectiveAmplitude.toStringAsFixed(1)} '
        'elapsedMs=${elapsedSinceRecordingStart.inMilliseconds} '
        'hasDetectedSpeech=$_hasDetectedSpeech '
        'keepInitialWait=${!_hasDetectedSpeech}',
      );
    }

    if (!_hasDetectedSpeech && _noiseSampleCount < 6) {
      _speechNoiseFloor =
          ((_speechNoiseFloor * _noiseSampleCount) + effectiveAmplitude) /
          (_noiseSampleCount + 1);
      _noiseSampleCount += 1;
    }

    final speechStartThreshold = (_speechNoiseFloor + 8).clamp(-40, -22);
    final speechContinueThreshold = (_speechNoiseFloor + 5).clamp(-44, -26);
    final effectiveMinimumRecordingDuration =
        _currentMinimumRecordingDuration();
    final effectiveEndOfSpeechSilence = _currentEndOfSpeechSilence();
    final effectiveSilenceConfirmDuration = _currentSilenceConfirmDuration();
    final now = DateTime.now();

    if (_lastVadDebugAt == null ||
        now.difference(_lastVadDebugAt!) >= const Duration(milliseconds: 480)) {
      _lastVadDebugAt = now;
      debugPrint(
        '[VAD] sample '
        'amp=${effectiveAmplitude.toStringAsFixed(1)} '
        'noiseFloor=${_speechNoiseFloor.toStringAsFixed(1)} '
        'startThreshold=${speechStartThreshold.toStringAsFixed(1)} '
        'continueThreshold=${speechContinueThreshold.toStringAsFixed(1)} '
        'hasSpeech=$_hasDetectedSpeech '
        'unreliable=$_isAmplitudeTelemetryUnreliable',
      );
    }

    if (!_hasLoggedFirstLiveAmplitude && !zeroishAmplitude) {
      _hasLoggedFirstLiveAmplitude = true;
      debugPrint(
        '[VAD Timeline] first_live_amplitude '
        'epoch=$epoch '
        'at=${now.toIso8601String()} '
        'amp=${effectiveAmplitude.toStringAsFixed(1)} '
        'deltaSinceTtsEndMs=${_elapsedMsSince(_voiceTurnService.lastTtsPlaybackEndedAt, now)} '
        'deltaSinceRecorderStartMs=${_elapsedMsSince(_voiceTurnService.lastRecordingStartedAt, now)} '
        'deltaSinceUserTurnReadyMs=${_elapsedMsSince(_lastUserTurnReadyAt, now)}',
      );
    }

    if (_isAmplitudeTelemetryUnreliable) {
      return;
    }

    if (!_hasDetectedSpeech &&
        !zeroishAmplitude &&
        effectiveAmplitude >= speechStartThreshold) {
      _speechStartCandidateCount += 1;
      if (_speechStartCandidateCount >= _speechStartCandidateSampleThreshold) {
        _hasDetectedSpeech = true;
        _firstSpeechDetectedAt = now;
        _lastSpeechDetectedAt = now;
        _speechSilenceTimer?.cancel();
        debugPrint(
          '[VAD] speech_started '
          'amp=${effectiveAmplitude.toStringAsFixed(1)} '
          'noiseFloor=${_speechNoiseFloor.toStringAsFixed(1)} '
          'threshold=${speechStartThreshold.toStringAsFixed(1)} '
          'candidateSamples=$_speechStartCandidateCount',
        );
      } else {
        debugPrint(
          '[VAD] speech_candidate '
          'amp=${effectiveAmplitude.toStringAsFixed(1)} '
          'threshold=${speechStartThreshold.toStringAsFixed(1)} '
          'candidateSamples=$_speechStartCandidateCount',
        );
      }
      return;
    }

    if (!_hasDetectedSpeech) {
      _speechStartCandidateCount = 0;
    }

    if (!_hasDetectedSpeech) {
      return;
    }

    if (!zeroishAmplitude && effectiveAmplitude >= speechContinueThreshold) {
      _lastSpeechDetectedAt = now;
      _silenceCandidateStartedAt = null;
      _isAwaitingSilenceConfirmation = false;
      _speechSilenceTimer?.cancel();
      return;
    }

    if (_manualStopRecordingEnabled) {
      return;
    }

    final lastSpeechAt = _lastSpeechDetectedAt;
    final firstSpeechAt = _firstSpeechDetectedAt;
    if (lastSpeechAt == null ||
        firstSpeechAt == null ||
        recordingStartedAt == null) {
      return;
    }

    final speechElapsed = now.difference(recordingStartedAt);
    final firstSpeechElapsed = now.difference(firstSpeechAt);
    final silenceElapsed = now.difference(lastSpeechAt);
    if (speechElapsed >= effectiveMinimumRecordingDuration &&
        speechElapsed >= _minSpeechWindow &&
        firstSpeechElapsed >= _firstSyllableProtection &&
        silenceElapsed >= effectiveEndOfSpeechSilence &&
        !_isAwaitingSilenceConfirmation) {
      _isAwaitingSilenceConfirmation = true;
      _silenceCandidateStartedAt = now;
      debugPrint(
        '[VAD] silence_candidate '
        'speechElapsedMs=${speechElapsed.inMilliseconds} '
        'minimumRecordingMs=${effectiveMinimumRecordingDuration.inMilliseconds} '
        'firstSpeechElapsedMs=${firstSpeechElapsed.inMilliseconds} '
        'silenceElapsedMs=${silenceElapsed.inMilliseconds} '
        'requiredSilenceMs=${effectiveEndOfSpeechSilence.inMilliseconds} '
        'firstSyllableProtectionMs=${_firstSyllableProtection.inMilliseconds} '
        'continueThreshold=${speechContinueThreshold.toStringAsFixed(1)} '
        'amp=${effectiveAmplitude.toStringAsFixed(1)}',
      );
      _speechSilenceTimer?.cancel();
      _speechSilenceTimer = Timer(effectiveSilenceConfirmDuration, () {
        if (!_canContinueUserRecording(epoch)) {
          return;
        }

        final confirmFrom = _silenceCandidateStartedAt ?? now;
        final confirmedSilenceMs = DateTime.now()
            .difference(confirmFrom)
            .inMilliseconds;

        debugPrint(
          '[VAD] speech_ended_confirmed '
          'confirmMs=$confirmedSilenceMs '
          'extraConfirmMs=${effectiveSilenceConfirmDuration.inMilliseconds}',
        );

        unawaited(_finishRecording(epoch: epoch));
      });
    }
  }

  Duration _currentInitialSpeechWaitTimeout() {
    switch (_step) {
      case ShoppingStep.showProduct:
      case ShoppingStep.askMoreOrCheckout:
      case ShoppingStep.confirmAddress:
        return const Duration(milliseconds: 5600);
      case ShoppingStep.askQuantity:
        return const Duration(milliseconds: 6400);
      case ShoppingStep.askProduct:
      case ShoppingStep.searchingProduct:
      case ShoppingStep.addingToCart:
      case ShoppingStep.cartCompleted:
      case ShoppingStep.enterPassword:
      case ShoppingStep.processingPayment:
      case ShoppingStep.paymentCompleted:
      case ShoppingStep.error:
        return _initialSpeechWaitTimeout;
    }
  }

  Duration _currentMaxRecordingDuration() {
    switch (_step) {
      case ShoppingStep.showProduct:
      case ShoppingStep.askMoreOrCheckout:
      case ShoppingStep.confirmAddress:
        return const Duration(seconds: 13);
      case ShoppingStep.askQuantity:
        return const Duration(seconds: 16);
      case ShoppingStep.askProduct:
        return _maxRecordingDuration;
      case ShoppingStep.searchingProduct:
      case ShoppingStep.addingToCart:
      case ShoppingStep.cartCompleted:
      case ShoppingStep.enterPassword:
      case ShoppingStep.processingPayment:
      case ShoppingStep.paymentCompleted:
      case ShoppingStep.error:
        return const Duration(seconds: 12);
    }
  }

  Duration _currentMinimumRecordingDuration() {
    switch (_step) {
      case ShoppingStep.askProduct:
        return const Duration(milliseconds: 4200);
      case ShoppingStep.askQuantity:
        return const Duration(milliseconds: 3800);
      case ShoppingStep.showProduct:
      case ShoppingStep.askMoreOrCheckout:
      case ShoppingStep.confirmAddress:
        return const Duration(milliseconds: 3400);
      case ShoppingStep.searchingProduct:
      case ShoppingStep.addingToCart:
      case ShoppingStep.cartCompleted:
      case ShoppingStep.enterPassword:
      case ShoppingStep.processingPayment:
      case ShoppingStep.paymentCompleted:
      case ShoppingStep.error:
        return _minimumRecordingDuration;
    }
  }

  Duration _currentEndOfSpeechSilence() {
    switch (_step) {
      case ShoppingStep.showProduct:
      case ShoppingStep.askMoreOrCheckout:
      case ShoppingStep.confirmAddress:
        return const Duration(milliseconds: 3000);
      case ShoppingStep.askQuantity:
        return const Duration(milliseconds: 3400);
      case ShoppingStep.askProduct:
      case ShoppingStep.searchingProduct:
      case ShoppingStep.addingToCart:
      case ShoppingStep.cartCompleted:
      case ShoppingStep.enterPassword:
      case ShoppingStep.processingPayment:
      case ShoppingStep.paymentCompleted:
      case ShoppingStep.error:
        return _endOfSpeechSilence;
    }
  }

  Duration _currentSilenceConfirmDuration() {
    switch (_step) {
      case ShoppingStep.showProduct:
      case ShoppingStep.askMoreOrCheckout:
      case ShoppingStep.confirmAddress:
        return const Duration(milliseconds: 1400);
      case ShoppingStep.askQuantity:
        return const Duration(milliseconds: 1500);
      case ShoppingStep.askProduct:
      case ShoppingStep.searchingProduct:
      case ShoppingStep.addingToCart:
      case ShoppingStep.cartCompleted:
      case ShoppingStep.enterPassword:
      case ShoppingStep.processingPayment:
      case ShoppingStep.paymentCompleted:
      case ShoppingStep.error:
        return _silenceConfirmDuration;
    }
  }

  String _cartStatusTextForTask() {
    switch (_lastWebviewTask) {
      case 'address_check':
        return '배송지 정보를 확인하고 있어요.';
      case 'payment':
        return '결제 화면을 준비하고 있어요.';
      case 'add_to_cart':
      default:
        return '상품을 장바구니에 담고 있어요.';
    }
  }

  String _cartHelperTextForTask() {
    switch (_lastWebviewTask) {
      case 'address_check':
        return '주문에 필요한 배송지 정보를 확인 중이에요.';
      case 'payment':
        return '안전하게 결제를 준비하고 있어요.';
      case 'add_to_cart':
      default:
        return '쇼핑 화면을 준비하고 있어요.';
    }
  }

  void _cancelVoiceTimers({bool keepCartAndPaymentTimers = false}) {
    _userTurnTimer?.cancel();
    _userTurnTimer = null;
    _recordingTimeoutTimer?.cancel();
    _recordingTimeoutTimer = null;
    _speechSilenceTimer?.cancel();
    _speechSilenceTimer = null;
    _fallbackAutoStopTimer?.cancel();
    _fallbackAutoStopTimer = null;
    _silenceCandidateStartedAt = null;
    _isAwaitingSilenceConfirmation = false;
    _amplitudeSubscription?.cancel();
    _amplitudeSubscription = null;
    _recognitionEventSubscription?.cancel();
    _recognitionEventSubscription = null;
    if (!keepCartAndPaymentTimers) {
      _cartTimer?.cancel();
      _paymentTimer?.cancel();
    }
  }

  void _upsertCartPreview({
    required ProductViewData? product,
    required int quantity,
  }) {
    if (product == null) {
      return;
    }
    final safeQuantity = quantity > 0 ? quantity : 1;
    final existingIndex = _cartItems.indexWhere(
      (item) => item.product.title.trim() == product.title.trim(),
    );
    final previewItem = CartItemViewData(
      product: product,
      quantity: safeQuantity,
      totalPrice: (product.price ?? 0) * safeQuantity,
      totalPriceText: product.price != null
          ? '${((product.price ?? 0) * safeQuantity).toString().replaceAllMapped(RegExp(r'\B(?=(\d{3})+(?!\d))'), (match) => ',')}원'
          : null,
    );
    if (existingIndex >= 0) {
      _cartItems[existingIndex] = previewItem;
      return;
    }
    _cartItems.add(previewItem);
  }

  String _formatCartPrice(int value) {
    final raw = value.toString();
    return raw.replaceAllMapped(
      RegExp(r'\B(?=(\d{3})+(?!\d))'),
      (match) => ',',
    );
  }

  void _scheduleFallbackAutoStop(int epoch) {
    _fallbackAutoStopTimer?.cancel();

    final effectiveMaxRecording = _currentMaxRecordingDuration();
    final fallbackDuration = Duration(
      milliseconds: (effectiveMaxRecording.inMilliseconds - 800).clamp(
        8500,
        22000,
      ),
    );

    _fallbackAutoStopTimer = Timer(fallbackDuration, () {
      if (!_canContinueUserRecording(epoch)) {
        return;
      }

      debugPrint(
        '[VAD] fallback_auto_stop '
        'captureMs=${fallbackDuration.inMilliseconds}',
      );

      unawaited(_finishRecording(epoch: epoch));
    });
  }

  double _sanitizeAmplitude(double amplitude) {
    if (!amplitude.isFinite) {
      return -160.0;
    }
    if (amplitude == -0.0) {
      return 0.0;
    }
    return amplitude.clamp(-160.0, 0.0);
  }

  int _elapsedMsSince(DateTime? since, DateTime? now) {
    if (since == null || now == null) {
      return -1;
    }
    return now.difference(since).inMilliseconds;
  }

  bool _isRetryPromptText(String text) {
    final normalized = text.trim();
    return normalized.contains('다시 말씀') ||
        normalized.contains('천천히 말씀') ||
        normalized.contains('잘 못 들었');
  }

  String _normalizeSearchingAssistantMessage(String fallbackMessage) {
    if (_step != ShoppingStep.searchingProduct) {
      return fallbackMessage;
    }
    final built = _buildSearchingAssistantMessage();
    return built.isNotEmpty ? built : fallbackMessage;
  }

  String _buildSearchingAssistantMessage() {
    final keyword = (_activeSearchKeyword ?? '').trim();
    final name = (_userName ?? '').trim();
    if (keyword.isNotEmpty) {
      if (name.isNotEmpty) {
        return '$name님을 위한 $keyword${_objectParticle(keyword)} 찾고 있어요.';
      }
      return '$keyword${_objectParticle(keyword)} 찾고 있어요.';
    }
    if (name.isNotEmpty) {
      return '$name님을 위한 상품을 찾고 있어요.';
    }
    return '원하시는 상품을 찾고 있어요.';
  }

  String _extractSearchKeywordFromMessage(String message) {
    var normalized = message.replaceAll(RegExp(r'\s+'), ' ').trim();
    if (normalized.isEmpty) {
      return '';
    }
    normalized = normalized.replaceAll(RegExp(r"[?？!！.,~…-]+$"), '').trim();
    normalized = normalized
        .replaceAll(
          RegExp(
            r"\s+(?:하나|한|둘|두|셋|세|넷|네|\d+)\s*(?:개|봉|팩|박스|통|병|입)?\s*만?\s*"
            r"(?:사\s*보라고|사보라고|사\s*봐줘요?|사봐줘|사\s*봐|사봐|사줘요?|사줘|"
            r"주문해줘요?|주문해줘|구매해줘요?|구매해줘)?$",
          ),
          '',
        )
        .trim();
    const suffixPatterns = <String>[
      r"(사고\s*싶어요?|사고\s*싶어|사고\s*싶네(?:요)?|사줘요?|찾아줘요?|주문해줘요?|구매하고\s*싶어요?)$",
      r"(사\s*보라고|사보라고|사\s*봐줘요?|사봐줘|사\s*봐|사봐)$",
      r"((?:먹고|마시고|드시고)\s*싶어요?)$",
      r"((?:먹고|마시고|드시고)\s*싶어)$",
      r"(사고)$",
      r"(살래요?|살래|주세요|찾아봐요?|알아봐줘요?)$",
      r"(있어요?|있나(?:요)?|있을까요?|있)$",
      r"(요즘\s*유행하는)\s+",
      r"^(나는|전|저는|저|나)\s+",
    ];
    for (final pattern in suffixPatterns) {
      normalized = normalized.replaceAll(RegExp(pattern), '').trim();
    }
    normalized = normalized
        .replaceAll(RegExp(r"\s+(사|사줘|사줘요|사라|주문해|주문해라|구매해|구매해라)$"), '')
        .trim();
    normalized = normalized.replaceAll(RegExp(r"(있)[-~…]?$"), '').trim();
    normalized = normalized.replaceAll(RegExp(r"\s+[-~…]+$"), '').trim();
    normalized = normalized.replaceAll(RegExp(r"[-~…]+$"), '').trim();
    return normalized.trim().replaceAll(RegExp("^[\"']|[\"']\$"), '');
  }

  String _objectParticle(String text) {
    final trimmed = text.trim();
    if (trimmed.isEmpty) {
      return '을';
    }
    final codeUnit = trimmed.codeUnitAt(trimmed.length - 1);
    final hasBatchim =
        codeUnit >= 0xAC00 &&
        codeUnit <= 0xD7A3 &&
        ((codeUnit - 0xAC00) % 28 != 0);
    return hasBatchim ? '을' : '를';
  }

  Duration _userTurnDelayForPrompt({required bool isRetryPrompt}) {
    if (_manualStopRecordingEnabled) {
      return Duration.zero;
    }
    if (_isAndroidRuntime) {
      return isRetryPrompt
          ? _androidRetryPromptToUserDelay
          : _androidTtsToUserDelay;
    }
    return isRetryPrompt
        ? _defaultRetryPromptToUserDelay
        : _defaultTtsToUserDelay;
  }

  Future<void> _logUnexpectedReaskIfNeeded({
    required String transcript,
    required ShoppingStep previousStep,
    required ShoppingStep inferredStep,
    required ShoppingAgentResponse response,
  }) async {
    final normalizedTranscript = transcript.trim();
    if (normalizedTranscript.isEmpty) {
      return;
    }

    final assistantMessage = response.assistantMessage.trim();
    final isAskProductRetry = inferredStep == ShoppingStep.askProduct;
    final isRepeatedQuantityQuestion =
        previousStep == ShoppingStep.askQuantity &&
        inferredStep == ShoppingStep.askQuantity;
    final isRepeatedChoiceQuestion =
        previousStep == ShoppingStep.askMoreOrCheckout &&
        inferredStep == ShoppingStep.askMoreOrCheckout;

    if (!isAskProductRetry &&
        !isRepeatedQuantityQuestion &&
        !isRepeatedChoiceQuestion) {
      return;
    }

    await SttVadResponseLogService.instance.logEvent(
      'non_empty_stt_reask',
      payload: {
        'conversationId': _conversationId,
        'userId': _userId,
        'userName': _userName,
        'previousStep': previousStep.name,
        'inferredStep': inferredStep.name,
        'transcript': normalizedTranscript,
        'assistantMessage': assistantMessage,
        'responseStatus': response.status,
        'responseStage': response.stage,
        'pendingType': response.pendingConfirmation?['type']?.toString(),
        'pendingSubType': response.pendingConfirmation?['payload'] is Map
            ? (response.pendingConfirmation!['payload'] as Map)['subType']
                  ?.toString()
            : null,
        'error': response.error?.toString(),
        'raw': response.raw,
      },
    );
  }

  @override
  void dispose() {
    _cancelVoiceTimers();
    _cartTimer?.cancel();
    _paymentTimer?.cancel();
    _completionSequenceTimer?.cancel();
    _agentProgressSubscription?.cancel();
    unawaited(_agentService.disconnectProgress());
    super.dispose();
  }
}
