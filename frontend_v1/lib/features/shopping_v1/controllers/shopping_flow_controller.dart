import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:record/record.dart';

import '../../../core/network/api_client.dart';
import '../models/shopping_v1_models.dart';
import '../services/shopping_agent_service.dart';
import '../services/voice_turn_service.dart';

class ShoppingFlowController extends ChangeNotifier {
  static const Duration _ttsToUserDelay = Duration(milliseconds: 260);
  static const Duration _initialSpeechWaitTimeout = Duration(seconds: 5);
  static const Duration _maxRecordingDuration = Duration(seconds: 10);
  static const Duration _endOfSpeechSilence = Duration(milliseconds: 1700);
  static const Duration _silenceConfirmDuration = Duration(milliseconds: 700);
  static const Duration _minSpeechWindow = Duration(milliseconds: 900);
  static const Duration _unreliableAmplitudeCapture = Duration(seconds: 4);
  static const double _speechGuardRatio = 0.82;
  static const bool _forceSilentDemoTts =
      bool.fromEnvironment('SHOPPING_V1_SILENT_TTS');

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
  Timer? _userTurnTimer;
  Timer? _recordingTimeoutTimer;
  Timer? _speechSilenceTimer;
  Timer? _fallbackAutoStopTimer;
  bool _hasDetectedSpeech = false;
  double _speechNoiseFloor = -45;
  int _noiseSampleCount = 0;
  DateTime? _recordingStartedAt;
  DateTime? _lastSpeechDetectedAt;
  DateTime? _lastVadDebugAt;
  DateTime? _silenceCandidateStartedAt;
  bool _isAmplitudeTelemetryUnreliable = false;
  bool _isAwaitingSilenceConfirmation = false;
  int _amplitudeSampleCount = 0;
  int _zeroishAmplitudeCount = 0;

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
    _lastWebviewTask = null;
    _pendingWebviewTask = null;
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
    if (_step == ShoppingStep.askProduct) {
      _step = ShoppingStep.searchingProduct;
      notifyListeners();
    } else {
      notifyListeners();
    }

    try {
      final response = _conversationId == null
          ? await _agentService.startShopping(
              userId: _userId,
              message: transcript,
            )
          : await _agentService.sendMessage(
              conversationId: _conversationId!,
              message: transcript,
            );
      _conversationId = response.conversationId ?? _conversationId;
      await _consumeAgentResponse(response, transcript);
    } catch (error, stackTrace) {
      debugPrint(
        '⚠️ [ShoppingFlowController] agent fallback: $error\n$stackTrace',
      );
      _isMockMode = true;
      await _consumeMockFlow(transcript);
    }
  }

  Future<void> _consumeAgentResponse(
    ShoppingAgentResponse response,
    String transcript,
  ) async {
    final inferredStep = _inferStep(response);
    final parsedProduct = _agentService.extractProduct(response);
    if (parsedProduct != null) {
      _currentProduct = _mergeWithFallback(parsedProduct);
    } else {
      _currentProduct ??= ProductViewData.mock();
    }

    switch (inferredStep) {
      case ShoppingStep.showProduct:
        final productMessage = response.assistantMessage.trim().isNotEmpty
            ? response.assistantMessage
            : (await _agentService.fetchPrompt(
                kind: 'mock_product',
                conversationId: _conversationId,
                payload: {
                  'title': _currentProduct!.title,
                  'quantityInfo': _currentProduct!.quantityInfo,
                  'priceText': _currentProduct!.displayPrice,
                  'badgeText': _currentProduct!.badgeText,
                },
              )).assistantMessage;
        await _presentAssistant(
          productMessage,
          speechSegments: response.speechSegments,
          nextStep: ShoppingStep.showProduct,
          expectVoiceReply: true,
        );
        return;
      case ShoppingStep.askQuantity:
        await _presentAssistant(
          response.assistantMessage.trim().isEmpty
              ? (await _agentService.fetchPrompt(
                  kind: 'ask_quantity',
                  conversationId: _conversationId,
                )).assistantMessage
              : response.assistantMessage,
          speechSegments: response.speechSegments,
          nextStep: ShoppingStep.askQuantity,
          expectVoiceReply: true,
        );
        return;
      case ShoppingStep.confirmAddress:
        _checkoutSummary =
            response.deliveryAddress != null || response.cart != null
            ? _agentService.checkoutSummaryFromResponse(
                response,
                fallbackItems: _cartItems,
              )
            : await _agentService.fetchCheckoutSummary(
                userId: _userId,
                items: _cartItems,
                deliveryAddress: response.deliveryAddress,
              );
        await _presentAssistant(
          response.assistantMessage.trim().isEmpty
              ? (await _agentService.fetchPrompt(
                  kind: 'confirm_address',
                  conversationId: _conversationId,
                )).assistantMessage
              : response.assistantMessage,
          speechSegments: response.speechSegments,
          nextStep: ShoppingStep.confirmAddress,
          expectVoiceReply: false,
        );
        return;
      case ShoppingStep.enterPassword:
        if (response.assistantMessage.trim().isEmpty) {
          await _presentPrompt(
            'pin_prompt',
            nextStep: ShoppingStep.enterPassword,
            expectVoiceReply: false,
          );
        } else {
          await _presentAssistant(
            response.assistantMessage,
            speechSegments: response.speechSegments,
            nextStep: ShoppingStep.enterPassword,
            expectVoiceReply: false,
          );
        }
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
        await _presentAssistant(
          response.assistantMessage.trim().isEmpty
              ? (await _agentService.fetchPrompt(
                  kind: 'ask_more_or_checkout',
                  conversationId: _conversationId,
                )).assistantMessage
              : response.assistantMessage,
          speechSegments: response.speechSegments,
          nextStep: ShoppingStep.askMoreOrCheckout,
          expectVoiceReply: true,
        );
        return;
      case ShoppingStep.paymentCompleted:
        await _showPaymentCompleted(
          response.assistantMessage,
          speechSegments: response.speechSegments,
        );
        return;
      case ShoppingStep.searchingProduct:
        _step = ShoppingStep.searchingProduct;
        _assistantText = response.assistantMessage;
        notifyListeners();
        await Future<void>.delayed(const Duration(milliseconds: 700));
        await _consumeMockFlow(transcript);
        return;
      case ShoppingStep.error:
        _errorMessage = response.assistantMessage;
        await _presentPrompt(
          'error_retry',
          nextStep: ShoppingStep.error,
          expectVoiceReply: true,
        );
        return;
      case ShoppingStep.askProduct:
      case ShoppingStep.cartCompleted:
      case ShoppingStep.processingPayment:
        break;
    }

    await _consumeMockFlow(transcript);
  }

  Future<void> _consumeMockFlow(String transcript) async {
    final current = _step;
    if (current == ShoppingStep.askProduct ||
        current == ShoppingStep.searchingProduct) {
      _currentProduct = _currentProduct ?? ProductViewData.mock();
      await _presentAssistant(
        (await _agentService.fetchPrompt(
          kind: 'mock_product',
          conversationId: _conversationId,
          payload: {
            'title': _currentProduct!.title,
            'quantityInfo': _currentProduct!.quantityInfo,
            'priceText': _currentProduct!.displayPrice,
            'badgeText': _currentProduct!.badgeText,
          },
        )).assistantMessage,
        nextStep: ShoppingStep.showProduct,
        expectVoiceReply: true,
      );
      return;
    }

    if (current == ShoppingStep.showProduct) {
      if (_isNegative(transcript)) {
        await _presentPrompt(
          'negative_restart',
          nextStep: ShoppingStep.askProduct,
          expectVoiceReply: true,
        );
        return;
      }
      await _presentPrompt(
        'ask_quantity',
        nextStep: ShoppingStep.askQuantity,
        expectVoiceReply: true,
      );
      return;
    }

    if (current == ShoppingStep.askQuantity) {
      _currentQuantity = _extractQuantity(transcript) ?? 1;
      final product = _currentProduct ?? ProductViewData.mock();
      final total = (product.price ?? 12900) * _currentQuantity;
      _cartItems
        ..clear()
        ..add(
          CartItemViewData(
            product: product,
            quantity: _currentQuantity,
            totalPrice: total,
            totalPriceText: '${_formatPrice(total)}원',
          ),
        );
      await _startCartProgressFlow();
      return;
    }

    if (current == ShoppingStep.askMoreOrCheckout ||
        current == ShoppingStep.cartCompleted) {
      if (_wantsMoreShopping(transcript)) {
        await _presentPrompt(
          'more_shopping',
          nextStep: ShoppingStep.askProduct,
          expectVoiceReply: true,
        );
        return;
      }
      _checkoutSummary = await _agentService.fetchCheckoutSummary(
        userId: _userId,
        items: _cartItems,
      );
      await _presentPrompt(
        'confirm_address',
        nextStep: ShoppingStep.confirmAddress,
        expectVoiceReply: true,
      );
      return;
    }

    if (current == ShoppingStep.confirmAddress) {
      _pin = '';
      await _presentPrompt(
        'pin_prompt',
        nextStep: ShoppingStep.enterPassword,
        expectVoiceReply: false,
      );
      return;
    }

    await _presentPrompt(
      'initial_prompt',
      payload: {'username': _userName},
      nextStep: ShoppingStep.askProduct,
      expectVoiceReply: true,
    );
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
      _conversationId = response.conversationId ?? _conversationId;
      await _consumeAgentResponse(response, _latestTranscript ?? '');
    } catch (error, stackTrace) {
      debugPrint(
        '⚠️ [ShoppingFlowController] webview result fallback: $error\n$stackTrace',
      );
      if (result == 'cart_added') {
        _cartProgress = 1;
        _step = ShoppingStep.cartCompleted;
        await _presentPrompt(
          'cart_completed',
          nextStep: ShoppingStep.askMoreOrCheckout,
          expectVoiceReply: true,
        );
        return;
      }
      await _presentPrompt(
        'error_retry',
        nextStep: ShoppingStep.askMoreOrCheckout,
        expectVoiceReply: true,
      );
    }
  }

  Future<void> _startPaymentProcessingFlow() async {
    _paymentTimer?.cancel();
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
    if (text.trim().isEmpty) {
      await _presentPrompt(
        'payment_completed',
        nextStep: ShoppingStep.paymentCompleted,
        expectVoiceReply: false,
      );
      return;
    }
    await _presentAssistant(
      text,
      speechSegments: speechSegments,
      nextStep: ShoppingStep.paymentCompleted,
      expectVoiceReply: false,
    );
  }

  Future<void> _presentAssistant(
    String text, {
    List<SpeechSegmentViewData> speechSegments = const [],
    required ShoppingStep nextStep,
    required bool expectVoiceReply,
  }) async {
    _cancelVoiceTimers();
    final epoch = ++_speakEpoch;
    _step = nextStep;
    _assistantText = text;
    _voiceTurnState = VoiceTurnState.agentSpeaking;
    _voiceLevel = 0.22;
    notifyListeners();
    if (speechSegments.isNotEmpty && !_shouldBypassTtsForDemo) {
      await _presentAssistantSpeechQueue(
        text,
        speechSegments,
        epoch,
      );
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
      _userTurnTimer = Timer(_ttsToUserDelay, () {
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
        await Future<void>.delayed(_estimateSilentSegmentDuration(segment.text));
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
      } catch (_) {
        await Future<void>.delayed(_estimateSilentSegmentDuration(segment.text));
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
    final baseSegments = sentenceSegments.isEmpty ? [normalized] : sentenceSegments;
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
    final minimumMs =
        (expected.inMilliseconds * _speechGuardRatio).round().clamp(700, 4200);
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
    _hasDetectedSpeech = false;
    _noiseSampleCount = 0;
    _speechNoiseFloor = -45;
    _recordingStartedAt = DateTime.now();
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
      'initialSpeechWaitMs=${_initialSpeechWaitTimeout.inMilliseconds} '
      'maxRecordingMs=${_maxRecordingDuration.inMilliseconds}',
    );
    notifyListeners();
    try {
      await _voiceTurnService.startRecording();
      _listenAmplitude();
      _recordingTimeoutTimer = Timer(_maxRecordingDuration, () {
        unawaited(_finishRecording());
      });
      _speechSilenceTimer = Timer(_initialSpeechWaitTimeout, () async {
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
    } catch (_) {
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
    } catch (_) {
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

  ProductViewData _mergeWithFallback(ProductViewData source) {
    final fallback = ProductViewData.mock(productUrl: source.productUrl);
    return ProductViewData(
      platform: source.platform ?? fallback.platform,
      shopName: source.shopName ?? fallback.shopName,
      productUrl: source.productUrl ?? fallback.productUrl,
      imageUrl: source.imageUrl ?? fallback.imageUrl,
      title: source.title,
      subtitle: source.subtitle ?? fallback.subtitle,
      quantityInfo: source.quantityInfo ?? fallback.quantityInfo,
      price: source.price ?? fallback.price,
      priceText: source.priceText ?? fallback.priceText,
      badgeText: source.badgeText ?? fallback.badgeText,
    );
  }

  bool _isNegative(String text) {
    return RegExp(r'아니|말고|다른|싫', caseSensitive: false).hasMatch(text);
  }

  bool _wantsMoreShopping(String text) {
    return RegExp(r'응|네|더|하나 더|살래', caseSensitive: false).hasMatch(text) &&
        !RegExp(r'결제|그만|아니', caseSensitive: false).hasMatch(text);
  }

  int? _extractQuantity(String text) {
    final digitMatch = RegExp(r'(\d+)').firstMatch(text);
    if (digitMatch != null) {
      return int.tryParse(digitMatch.group(1)!);
    }

    const koreanNumbers = <String, int>{
      '한': 1,
      '하나': 1,
      '두': 2,
      '둘': 2,
      '세': 3,
      '셋': 3,
      '네': 4,
      '넷': 4,
      '다섯': 5,
      '여섯': 6,
      '일곱': 7,
      '여덟': 8,
      '아홉': 9,
      '열': 10,
    };
    for (final entry in koreanNumbers.entries) {
      if (text.contains(entry.key)) {
        return entry.value;
      }
    }
    return null;
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
    final speechContinueThreshold =
        (_speechNoiseFloor + 7).clamp(-40, -26);
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
    final recordingStartedAt = _recordingStartedAt;
    if (lastSpeechAt == null || recordingStartedAt == null) {
      return;
    }

    final speechElapsed = now.difference(recordingStartedAt);
    final silenceElapsed = now.difference(lastSpeechAt);
    if (speechElapsed >= _minSpeechWindow &&
        silenceElapsed >= _endOfSpeechSilence &&
        !_isAwaitingSilenceConfirmation) {
      _isAwaitingSilenceConfirmation = true;
      _silenceCandidateStartedAt = now;
      debugPrint(
        '[VAD] silence_candidate '
        'speechElapsedMs=${speechElapsed.inMilliseconds} '
        'silenceElapsedMs=${silenceElapsed.inMilliseconds} '
        'continueThreshold=${speechContinueThreshold.toStringAsFixed(1)} '
        'amp=${amplitude.toStringAsFixed(1)}',
      );
      _speechSilenceTimer?.cancel();
      _speechSilenceTimer = Timer(_silenceConfirmDuration, () {
        if (_voiceTurnState != VoiceTurnState.userRecording) {
          return;
        }
        final confirmFrom = _silenceCandidateStartedAt ?? now;
        final confirmedSilenceMs =
            DateTime.now().difference(confirmFrom).inMilliseconds;
        debugPrint(
          '[VAD] speech_ended_confirmed '
          'confirmMs=$confirmedSilenceMs '
          'extraConfirmMs=${_silenceConfirmDuration.inMilliseconds}',
        );
        unawaited(_finishRecording());
      });
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

  @override
  void dispose() {
    _cancelVoiceTimers();
    _cartTimer?.cancel();
    _paymentTimer?.cancel();
    super.dispose();
  }
}

String _formatPrice(int value) {
  final source = value.toString();
  final buffer = StringBuffer();
  for (var i = 0; i < source.length; i++) {
    final reversedIndex = source.length - i;
    buffer.write(source[i]);
    if (reversedIndex > 1 && reversedIndex % 3 == 1) {
      buffer.write(',');
    }
  }
  return buffer.toString();
}
