import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:record/record.dart';

import '../../../core/network/api_client.dart';
import '../models/shopping_v1_models.dart';
import '../services/shopping_agent_service.dart';
import '../services/voice_turn_service.dart';

class ShoppingFlowController extends ChangeNotifier {
  static const Duration _ttsToUserDelay = Duration(milliseconds: 260);
  static const Duration _initialSpeechWaitTimeout = Duration(
    milliseconds: 6500,
  );
  static const Duration _maxRecordingDuration = Duration(seconds: 18);
  static const Duration _endOfSpeechSilence = Duration(milliseconds: 3200);
  static const Duration _silenceConfirmDuration = Duration(milliseconds: 1250);
  static const Duration _minSpeechWindow = Duration(milliseconds: 2100);
  static const Duration _firstSyllableProtection = Duration(milliseconds: 1400);
  static const Duration _unreliableAmplitudeCapture = Duration(
    milliseconds: 5600,
  );
  static const double _speechGuardRatio = 0.82;
  static const bool _forceSilentDemoTts = bool.fromEnvironment(
    'SHOPPING_V1_SILENT_TTS',
  );

  ShoppingFlowController({
    ShoppingAgentService? agentService,
    VoiceTurnService? voiceTurnService,
  }) : _agentService = agentService ?? ShoppingAgentService(),
       _voiceTurnService = voiceTurnService ?? VoiceTurnService();

  final ShoppingAgentService _agentService;
  final VoiceTurnService _voiceTurnService;

  ShoppingStep _step = ShoppingStep.askProduct;
  VoiceTurnState _voiceTurnState = VoiceTurnState.idle;
  String _assistantText = '';
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
  StreamSubscription<Amplitude>? _amplitudeSubscription;
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
  DateTime? _silenceCandidateStartedAt;
  bool _isAmplitudeTelemetryUnreliable = false;
  bool _isAwaitingSilenceConfirmation = false;
  int _amplitudeSampleCount = 0;
  int _zeroishAmplitudeCount = 0;
  bool _closeAppRequested = false;
  int _agentProgressRunId = 0;

  ShoppingStep get step => _step;
  VoiceTurnState get voiceTurnState => _voiceTurnState;
  String get assistantText => _assistantText;
  String? get latestTranscript => _latestTranscript;
  ProductViewData? get currentProduct => _currentProduct;
  List<CartItemViewData> get cartItems => List.unmodifiable(_cartItems);
  CheckoutSummary? get checkoutSummary => _checkoutSummary;
  String? get errorMessage => _errorMessage;
  bool get isInitialized => _isInitialized;
  double get voiceLevel => _voiceLevel;
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
  bool get _shouldBypassTtsForDemo => _forceSilentDemoTts;
  bool get closeAppRequested => _closeAppRequested;
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
    // V1 자동 turn-taking에서는 사용자 탭으로 녹음을 제어하지 않는다.
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

  Future<void> _handleUserTranscript(String transcript) async {
    _voiceTurnState = VoiceTurnState.agentThinking;
    _errorMessage = null;
    final normalizedTranscript = transcript.trim();
    if (_isIncompleteTranscript(normalizedTranscript)) {
      debugPrint(
        '[VAD] transcript_rejected_as_incomplete text="$normalizedTranscript"',
      );
      await _handleSttFailure();
      return;
    }
    final shouldUseAgentProgress = _shouldUseAgentProgress();
    if (_step == ShoppingStep.askProduct) {
      _step = ShoppingStep.searchingProduct;
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
      response.assistantMessage,
      speechSegments: response.speechSegments,
      nextStep: ShoppingStep.searchingProduct,
      expectVoiceReply: false,
    );
  }

  Future<void> _consumeAgentResponse(
    ShoppingAgentResponse response,
    String transcript,
  ) async {
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
            expectVoiceReply: false,
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
          expectVoiceReply: false,
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
        if (response.assistantMessage.trim().isNotEmpty &&
            response.assistantMessage.trim() != _assistantText.trim()) {
          _assistantText = response.assistantMessage;
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
      _assistantText = (await _agentService.fetchPrompt(
        kind: 'adding_to_cart',
        conversationId: _conversationId,
      )).assistantMessage;
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
    _step = ShoppingStep.cartCompleted;
    _assistantText = (await _agentService.fetchPrompt(
      kind: 'cart_completed',
      conversationId: _conversationId,
    )).assistantMessage;
    notifyListeners();
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
      final shouldStartListeningImmediately = _isRetryPromptText(text);
      final userTurnDelay = shouldStartListeningImmediately
          ? Duration.zero
          : _ttsToUserDelay;
      debugPrint(
        '[VAD] user_turn_ready '
        'epoch=$epoch immediate=$shouldStartListeningImmediately '
        'delayMs=${userTurnDelay.inMilliseconds} '
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
    _firstSpeechDetectedAt = null;
    _lastSpeechDetectedAt = null;
    _lastVadDebugAt = null;
    _silenceCandidateStartedAt = null;
    _isAmplitudeTelemetryUnreliable = false;
    _isAwaitingSilenceConfirmation = false;
    _amplitudeSampleCount = 0;
    _zeroishAmplitudeCount = 0;
    _voiceTurnState = VoiceTurnState.userRecording;
    _voiceLevel = 0.34;
    debugPrint(
      '[VAD] recording_started '
      'step=$_step epoch=$epoch '
      'initialSpeechWaitMs=${effectiveInitialWait.inMilliseconds} '
      'maxRecordingMs=${effectiveMaxRecording.inMilliseconds}',
    );
    notifyListeners();
    try {
      await _voiceTurnService.startRecording();
      _listenAmplitude();
      _recordingTimeoutTimer = Timer(effectiveMaxRecording, () {
        unawaited(_finishRecording());
      });
      _speechSilenceTimer = Timer(effectiveInitialWait, () async {
        if (_hasDetectedSpeech ||
            _voiceTurnState != VoiceTurnState.userRecording) {
          return;
        }
        debugPrint(
          '[VAD] initial_silence_timeout '
          'noiseFloor=${_speechNoiseFloor.toStringAsFixed(1)} '
          'samples=$_noiseSampleCount',
        );
        await _voiceTurnService.cancelRecording();
        _cancelVoiceTimers(keepCartAndPaymentTimers: true);
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
      await _handleSttFailure();
    }
  }

  void _listenAmplitude() {
    _amplitudeSubscription?.cancel();
    try {
      _amplitudeSubscription = _voiceTurnService
          .onAmplitudeChanged(interval: const Duration(milliseconds: 160))
          .listen((amplitude) {
            final current = amplitude.current;
            final normalized = _normalizeAmplitude(current);
            _voiceLevel = normalized;
            if (_voiceTurnState == VoiceTurnState.userRecording) {
              _updateVoiceActivity(current);
            }
            notifyListeners();
          });
    } catch (_) {
      // amplitude 연동이 불가능한 환경에서는 loop animation만 사용한다.
    }
  }

  Future<void> _finishRecording() async {
    if (_voiceTurnState != VoiceTurnState.userRecording) {
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
    _recordingTimeoutTimer?.cancel();
    _speechSilenceTimer?.cancel();
    _fallbackAutoStopTimer?.cancel();
    _firstSpeechDetectedAt = null;
    _lastSpeechDetectedAt = null;
    _recordingStartedAt = null;
    _silenceCandidateStartedAt = null;
    _isAwaitingSilenceConfirmation = false;
    try {
      final transcript = await _voiceTurnService.stopRecordingAndTranscribe();
      debugPrint(
        '[VAD] stt_result '
        'length=${transcript.trim().length} '
        'text="${transcript.trim()}"',
      );
      if (transcript.trim().isEmpty || transcript.trim().length < 2) {
        await _handleSttFailure();
        return;
      }
      _latestTranscript = transcript.trim();
      _voiceLevel = 0.32;
      notifyListeners();
      await _handleUserTranscript(_latestTranscript!);
    } catch (error, stackTrace) {
      debugPrint(
        '⚠️ [VAD] stop_or_transcribe_failed '
        'step=$_step error=$error\n$stackTrace',
      );
      await _handleSttFailure();
    }
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
    final clamped = ((amplitude + 45) / 45).clamp(0.0, 1.0);
    return 0.22 + (clamped * 0.78);
  }

  void _updateVoiceActivity(double amplitude) {
    _amplitudeSampleCount += 1;
    final zeroishAmplitude = amplitude <= -159.0 || amplitude.abs() < 0.1;
    if (zeroishAmplitude) {
      _zeroishAmplitudeCount += 1;
    }

    if (!_isAmplitudeTelemetryUnreliable &&
        _amplitudeSampleCount >= 6 &&
        _zeroishAmplitudeCount >= _amplitudeSampleCount - 1) {
      _isAmplitudeTelemetryUnreliable = true;
      _speechSilenceTimer?.cancel();
      _scheduleFallbackAutoStop();
      debugPrint(
        '[VAD] amplitude_unreliable '
        'samples=$_amplitudeSampleCount '
        'zeroish=$_zeroishAmplitudeCount '
        'amp=${amplitude.toStringAsFixed(1)}',
      );
    }

    if (!_hasDetectedSpeech && _noiseSampleCount < 6) {
      _speechNoiseFloor =
          ((_speechNoiseFloor * _noiseSampleCount) + amplitude) /
          (_noiseSampleCount + 1);
      _noiseSampleCount += 1;
    }

    final speechStartThreshold = (_speechNoiseFloor + 11).clamp(-34, -22);
    final speechContinueThreshold = (_speechNoiseFloor + 7).clamp(-40, -26);
    final effectiveEndOfSpeechSilence = _currentEndOfSpeechSilence();
    final effectiveSilenceConfirmDuration = _currentSilenceConfirmDuration();
    final now = DateTime.now();

    if (_lastVadDebugAt == null ||
        now.difference(_lastVadDebugAt!) >= const Duration(milliseconds: 480)) {
      _lastVadDebugAt = now;
      debugPrint(
        '[VAD] sample '
        'amp=${amplitude.toStringAsFixed(1)} '
        'noiseFloor=${_speechNoiseFloor.toStringAsFixed(1)} '
        'startThreshold=${speechStartThreshold.toStringAsFixed(1)} '
        'continueThreshold=${speechContinueThreshold.toStringAsFixed(1)} '
        'hasSpeech=$_hasDetectedSpeech '
        'unreliable=$_isAmplitudeTelemetryUnreliable',
      );
    }

    if (_isAmplitudeTelemetryUnreliable) {
      return;
    }

    if (!_hasDetectedSpeech &&
        !zeroishAmplitude &&
        amplitude >= speechStartThreshold) {
      _hasDetectedSpeech = true;
      _firstSpeechDetectedAt = now;
      _lastSpeechDetectedAt = now;
      _speechSilenceTimer?.cancel();
      debugPrint(
        '[VAD] speech_started '
        'amp=${amplitude.toStringAsFixed(1)} '
        'noiseFloor=${_speechNoiseFloor.toStringAsFixed(1)} '
        'threshold=${speechStartThreshold.toStringAsFixed(1)}',
      );
      return;
    }

    if (!_hasDetectedSpeech) {
      return;
    }

    if (!zeroishAmplitude && amplitude >= speechContinueThreshold) {
      _lastSpeechDetectedAt = now;
      _silenceCandidateStartedAt = null;
      _isAwaitingSilenceConfirmation = false;
      _speechSilenceTimer?.cancel();
      return;
    }

    final lastSpeechAt = _lastSpeechDetectedAt;
    final firstSpeechAt = _firstSpeechDetectedAt;
    final recordingStartedAt = _recordingStartedAt;
    if (lastSpeechAt == null ||
        firstSpeechAt == null ||
        recordingStartedAt == null) {
      return;
    }

    final speechElapsed = now.difference(recordingStartedAt);
    final firstSpeechElapsed = now.difference(firstSpeechAt);
    final silenceElapsed = now.difference(lastSpeechAt);
    if (speechElapsed >= _minSpeechWindow &&
        firstSpeechElapsed >= _firstSyllableProtection &&
        silenceElapsed >= effectiveEndOfSpeechSilence &&
        !_isAwaitingSilenceConfirmation) {
      _isAwaitingSilenceConfirmation = true;
      _silenceCandidateStartedAt = now;
      debugPrint(
        '[VAD] silence_candidate '
        'speechElapsedMs=${speechElapsed.inMilliseconds} '
        'firstSpeechElapsedMs=${firstSpeechElapsed.inMilliseconds} '
        'silenceElapsedMs=${silenceElapsed.inMilliseconds} '
        'requiredSilenceMs=${effectiveEndOfSpeechSilence.inMilliseconds} '
        'firstSyllableProtectionMs=${_firstSyllableProtection.inMilliseconds} '
        'continueThreshold=${speechContinueThreshold.toStringAsFixed(1)} '
        'amp=${amplitude.toStringAsFixed(1)}',
      );
      _speechSilenceTimer?.cancel();
      _speechSilenceTimer = Timer(effectiveSilenceConfirmDuration, () {
        if (_voiceTurnState != VoiceTurnState.userRecording) {
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
        unawaited(_finishRecording());
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
        return const Duration(seconds: 10);
      case ShoppingStep.askQuantity:
        return const Duration(seconds: 14);
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

  Duration _currentEndOfSpeechSilence() {
    switch (_step) {
      case ShoppingStep.showProduct:
      case ShoppingStep.askMoreOrCheckout:
      case ShoppingStep.confirmAddress:
        return const Duration(milliseconds: 2100);
      case ShoppingStep.askQuantity:
        return const Duration(milliseconds: 2500);
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
        return const Duration(milliseconds: 900);
      case ShoppingStep.askQuantity:
        return const Duration(milliseconds: 1050);
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

  void _scheduleFallbackAutoStop() {
    _fallbackAutoStopTimer?.cancel();
    _fallbackAutoStopTimer = Timer(_unreliableAmplitudeCapture, () {
      if (_voiceTurnState != VoiceTurnState.userRecording) {
        return;
      }
      debugPrint(
        '[VAD] fallback_auto_stop '
        'captureMs=${_unreliableAmplitudeCapture.inMilliseconds}',
      );
      unawaited(_finishRecording());
    });
  }

  bool _isIncompleteTranscript(String transcript) {
    final normalized = transcript.trim();
    if (normalized.isEmpty) {
      return true;
    }
    if (normalized.length < 2) {
      return true;
    }

    final compact = normalized.replaceAll(RegExp(r'\s+'), '');
    // 말줄임표/늘임표/대시로 끝나는 짧은 발화만 불완전 발화로 본다.
    // 일반 마침표 문장("새우깡 사줘.")은 정상 발화일 수 있으므로 제외한다.
    if (RegExp(r'(?:\.{2,}|…+|~+|-+)$').hasMatch(normalized) &&
        compact.length <= 6) {
      return true;
    }

    if (RegExp(r'^(어|음|아|그|저|응|네)[.!?…-]*$').hasMatch(compact)) {
      return true;
    }

    if (RegExp(r'^[가-힣]{1,2}[.~…-]*$').hasMatch(compact)) {
      return true;
    }

    return false;
  }

  bool _isRetryPromptText(String text) {
    final normalized = text.trim();
    return normalized.contains('다시 말씀') ||
        normalized.contains('천천히 말씀') ||
        normalized.contains('잘 못 들었');
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
