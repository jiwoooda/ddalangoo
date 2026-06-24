import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:record/record.dart';

import '../models/shopping_v1_models.dart';
import '../services/shopping_agent_service.dart';
import '../services/voice_turn_service.dart';

class ShoppingFlowController extends ChangeNotifier {
  static const Duration _ttsToUserDelay = Duration(milliseconds: 500);
  static const Duration _initialSpeechWaitTimeout = Duration(seconds: 8);
  static const Duration _maxRecordingDuration = Duration(seconds: 14);
  static const Duration _endOfSpeechSilence = Duration(milliseconds: 1800);

  ShoppingFlowController({
    ShoppingAgentService? agentService,
    VoiceTurnService? voiceTurnService,
  }) : _agentService = agentService ?? ShoppingAgentService(),
       _voiceTurnService = voiceTurnService ?? VoiceTurnService();

  static const String initialPrompt = '어떤 상품을 구매하고 싶으신가요?';

  final ShoppingAgentService _agentService;
  final VoiceTurnService _voiceTurnService;

  ShoppingStep _step = ShoppingStep.askProduct;
  VoiceTurnState _voiceTurnState = VoiceTurnState.idle;
  String _assistantText = initialPrompt;
  String? _latestTranscript;
  ProductViewData? _currentProduct;
  final List<CartItemViewData> _cartItems = [];
  CheckoutSummary? _checkoutSummary;
  String? _errorMessage;
  bool _isInitialized = false;
  bool _isMockMode = false;
  int? _conversationId;
  int _userId = 1;
  int _speakEpoch = 0;
  int _currentQuantity = 1;
  String _cartStatusTitle = '장바구니 작업';
  String _cartStatusText = '컬리 페이지를 열고 있어요.';
  String _cartHelperText = '쇼핑 화면을 준비하고 있어요.';
  double _cartProgress = 0.18;
  String _pin = '';
  double _voiceLevel = 0.22;
  String? _lastWebviewTask;
  StreamSubscription<Amplitude>? _amplitudeSubscription;
  Timer? _cartTimer;
  Timer? _paymentTimer;
  Timer? _userTurnTimer;
  Timer? _recordingTimeoutTimer;
  Timer? _speechSilenceTimer;
  bool _hasDetectedSpeech = false;

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
      _voiceTurnState == VoiceTurnState.transcribing ||
      _voiceTurnState == VoiceTurnState.agentThinking ||
      _voiceTurnState == VoiceTurnState.error;
  String get cartStatusTitle => _cartStatusTitle;
  String get cartStatusText => _cartStatusText;
  String get cartHelperText => _cartHelperText;
  double get cartProgress => _cartProgress;
  String get pin => _pin;
  bool get isMockMode => _isMockMode;

  Future<void> initialize() async {
    if (_isInitialized) {
      return;
    }
    _userId = await _agentService.resolveUserId();
    await _voiceTurnService.init();
    _isInitialized = true;
    notifyListeners();
    await _presentAssistant(
      initialPrompt,
      nextStep: ShoppingStep.askProduct,
      expectVoiceReply: true,
    );
  }

  Future<void> resetConversation() async {
    _cartTimer?.cancel();
    _paymentTimer?.cancel();
    _conversationId = null;
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
    _cancelVoiceTimers();
    await _voiceTurnService.cancelRecording();
    await _presentAssistant(
      initialPrompt,
      nextStep: ShoppingStep.askProduct,
      expectVoiceReply: true,
    );
  }

  Future<void> onVoiceButtonTap() async {
    // Voice orb는 상태 인디케이터이므로 수동 탭 입력은 사용하지 않는다.
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
      _assistantText = '상품을 찾는 중이에요';
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
        await _presentAssistant(
          _normalizedProductMessage(
            response.assistantMessage,
            _currentProduct!,
          ),
          nextStep: ShoppingStep.showProduct,
          expectVoiceReply: true,
        );
        return;
      case ShoppingStep.askQuantity:
        await _presentAssistant(
          response.assistantMessage.trim().isEmpty
              ? '몇 개를 담을까요?'
              : response.assistantMessage,
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
              ? '배송지를 확인해주세요.'
              : response.assistantMessage,
          nextStep: ShoppingStep.confirmAddress,
          expectVoiceReply: false,
        );
        return;
      case ShoppingStep.enterPassword:
        _step = ShoppingStep.enterPassword;
        _assistantText = response.assistantMessage.trim().isEmpty
            ? '비밀번호 6자리를 입력해주세요.'
            : response.assistantMessage;
        _voiceTurnState = VoiceTurnState.idle;
        notifyListeners();
        return;
      case ShoppingStep.addingToCart:
        _lastWebviewTask =
            response.pendingConfirmation?['type']?.toString() == 'webview_task'
            ? response.pendingConfirmation?['payload']?['task']?.toString()
            : response.uiCommand?['task']?.toString();
        await _startCartProgressFlow();
        return;
      case ShoppingStep.askMoreOrCheckout:
        await _presentAssistant(
          response.assistantMessage.trim().isEmpty
              ? '다른 상품을 더 구매하실래요?'
              : response.assistantMessage,
          nextStep: ShoppingStep.askMoreOrCheckout,
          expectVoiceReply: true,
        );
        return;
      case ShoppingStep.paymentCompleted:
        await _showPaymentCompleted(response.assistantMessage);
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
        await _presentAssistant(
          '잠시 문제가 생겼어요. 다시 시도해볼게요.',
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
        _mockProductMessage(_currentProduct!),
        nextStep: ShoppingStep.showProduct,
        expectVoiceReply: true,
      );
      return;
    }

    if (current == ShoppingStep.showProduct) {
      if (_isNegative(transcript)) {
        await _presentAssistant(
          '다른 상품을 찾아볼게요. 어떤 상품을 구매하고 싶으신가요?',
          nextStep: ShoppingStep.askProduct,
          expectVoiceReply: true,
        );
        return;
      }
      await _presentAssistant(
        '몇 개를 담을까요?',
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
        await _presentAssistant(
          '좋아요. 어떤 상품을 더 구매하고 싶으신가요?',
          nextStep: ShoppingStep.askProduct,
          expectVoiceReply: true,
        );
        return;
      }
      _checkoutSummary = await _agentService.fetchCheckoutSummary(
        userId: _userId,
        items: _cartItems,
      );
      await _presentAssistant(
        '배송지를 확인해주세요.',
        nextStep: ShoppingStep.confirmAddress,
        expectVoiceReply: true,
      );
      return;
    }

    if (current == ShoppingStep.confirmAddress) {
      _step = ShoppingStep.enterPassword;
      _assistantText = '비밀번호 6자리를 입력해주세요.';
      _voiceTurnState = VoiceTurnState.idle;
      _pin = '';
      notifyListeners();
      return;
    }

    await _presentAssistant(
      '어떤 상품을 구매하고 싶으신가요?',
      nextStep: ShoppingStep.askProduct,
      expectVoiceReply: true,
    );
  }

  Future<void> _handleSttFailure() async {
    _voiceTurnState = VoiceTurnState.error;
    notifyListeners();
    await Future<void>.delayed(const Duration(milliseconds: 420));
    await _presentAssistant(
      '잘 못 들었어요. 다시 말씀해주세요.',
      nextStep: _step == ShoppingStep.searchingProduct
          ? ShoppingStep.askProduct
          : _step,
      expectVoiceReply: true,
    );
  }

  Future<void> _startCartProgressFlow() async {
    _cartTimer?.cancel();
    _step = ShoppingStep.addingToCart;
    _voiceTurnState = VoiceTurnState.idle;
    _assistantText = '상품을 장바구니에 담을게요.';
    _cartStatusTitle = '장바구니 작업';
    _cartStatusText = _cartStatusTextForTask();
    _cartHelperText = _cartHelperTextForTask();
    _cartProgress = 0.2;
    notifyListeners();
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
    _assistantText = '상품을 담았어요! 다른 상품을 더 구매하실래요?';
    notifyListeners();
    await _presentAssistant(
      '상품을 담았어요! 다른 상품을 더 구매하실래요?',
      nextStep: ShoppingStep.askMoreOrCheckout,
      expectVoiceReply: true,
    );
  }

  Future<void> _startPaymentProcessingFlow() async {
    _paymentTimer?.cancel();
    _voiceTurnState = VoiceTurnState.idle;
    _assistantText = '결제를 진행 중이에요.';
    notifyListeners();
    _paymentTimer = Timer(const Duration(milliseconds: 1600), () {
      unawaited(_showPaymentCompleted('결제가 완료되었어요.'));
    });
  }

  Future<void> _showPaymentCompleted(String text) async {
    _step = ShoppingStep.paymentCompleted;
    _assistantText = text.trim().isEmpty ? '결제가 완료되었어요.' : text;
    _voiceTurnState = VoiceTurnState.idle;
    notifyListeners();
    try {
      await _voiceTurnService.speak(_assistantText);
    } catch (_) {
      notifyListeners();
    }
  }

  Future<void> _presentAssistant(
    String text, {
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
    try {
      await _voiceTurnService.speak(text);
    } catch (_) {
      // TTS 실패 시에도 텍스트 UI는 유지하고 다음 턴으로 넘어간다.
    }
    if (epoch != _speakEpoch) {
      return;
    }
    if (expectVoiceReply) {
      _voiceTurnState = VoiceTurnState.userCanSpeak;
      _voiceLevel = 0.28;
      notifyListeners();
      _userTurnTimer = Timer(_ttsToUserDelay, () {
        unawaited(_beginAutomaticListening(epoch));
      });
      return;
    }
    _voiceTurnState = VoiceTurnState.idle;
    notifyListeners();
  }

  Future<void> _beginAutomaticListening(int epoch) async {
    if (epoch != _speakEpoch ||
        _voiceTurnState != VoiceTurnState.userCanSpeak) {
      return;
    }
    _hasDetectedSpeech = false;
    _voiceTurnState = VoiceTurnState.userRecording;
    _voiceLevel = 0.34;
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
        await _voiceTurnService.cancelRecording();
        _cancelVoiceTimers(keepCartAndPaymentTimers: true);
        await _presentAssistant(
          '천천히 말씀해주셔도 괜찮아요. 다시 말씀해주세요.',
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
            final normalized = _normalizeAmplitude(amplitude.current);
            _voiceLevel = normalized;
            if (_voiceTurnState == VoiceTurnState.userRecording &&
                amplitude.current > -33) {
              _hasDetectedSpeech = true;
              _speechSilenceTimer?.cancel();
              _speechSilenceTimer = Timer(_endOfSpeechSilence, () {
                unawaited(_finishRecording());
              });
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
    _voiceTurnState = VoiceTurnState.transcribing;
    _voiceLevel = 0.4;
    notifyListeners();
    _recordingTimeoutTimer?.cancel();
    _speechSilenceTimer?.cancel();
    try {
      final transcript = await _voiceTurnService.stopRecordingAndTranscribe();
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

  String _normalizedProductMessage(
    String assistantMessage,
    ProductViewData product,
  ) {
    final normalized = assistantMessage.trim();
    if (normalized.isNotEmpty && normalized != '무엇을 도와드릴까요?') {
      return normalized;
    }
    return _mockProductMessage(product);
  }

  String _mockProductMessage(ProductViewData product) {
    return '${product.title}가 ${product.quantityInfo ?? '1개'} ${product.displayPrice}이에요. ${product.badgeText ?? '리뷰가 좋고 30일 중 가장 싼 가격이에요!'} 이 상품을 구매할까요?';
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
    _step = ShoppingStep.enterPassword;
    _pin = '';
    _assistantText = '비밀번호 6자리를 입력해주세요.';
    _voiceTurnState = VoiceTurnState.idle;
    notifyListeners();
    try {
      await _voiceTurnService.speak(_assistantText);
    } catch (_) {}
  }

  double _normalizeAmplitude(double amplitude) {
    final clamped = ((amplitude + 45) / 45).clamp(0.0, 1.0);
    return 0.22 + (clamped * 0.78);
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
    _amplitudeSubscription?.cancel();
    _amplitudeSubscription = null;
    if (!keepCartAndPaymentTimers) {
      _cartTimer?.cancel();
      _paymentTimer?.cancel();
    }
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
