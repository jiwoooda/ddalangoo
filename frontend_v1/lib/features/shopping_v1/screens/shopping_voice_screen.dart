import 'dart:async';
import 'package:flutter/material.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
import 'dart:ui';
import 'package:liquid_glass_renderer/liquid_glass_renderer.dart';

import '../../../presentation/screens/call/payment_webview_screen.dart';
import '../controllers/shopping_flow_controller.dart';
import '../models/shopping_v1_models.dart';
import '../widgets/address_confirm_card.dart';
import '../widgets/cart_progress_card.dart';
import '../widgets/cart_summary_card.dart';
import '../widgets/dallang_response_text.dart';
import '../widgets/glass_button.dart';
import '../widgets/pin_keypad.dart';
import '../widgets/product_card.dart';
import '../widgets/shopping_progress_steps.dart';
import '../widgets/voice_turn_orb.dart';

class ShoppingVoiceScreen extends StatefulWidget {
  const ShoppingVoiceScreen({
    super.key,
    this.controller,
    this.autoInitialize = true,
  });

  final ShoppingFlowController? controller;
  final bool autoInitialize;

  @override
  State<ShoppingVoiceScreen> createState() => _ShoppingVoiceScreenState();
}

class _ShoppingVoiceScreenState extends State<ShoppingVoiceScreen> {
  late final ShoppingFlowController _controller =
      (widget.controller ?? ShoppingFlowController())
        ..addListener(_onControllerChanged);
  bool _isWebviewOpen = false;
  String? _lastWebviewCommandKey;
  final Set<String> _completedWebviewCommandKeys = <String>{};
  final TextEditingController _textInputController = TextEditingController();
  // _showTextInput은 토글 모드(TEXT_INPUT_MODE=false)에서만 사용
  bool _showTextInput = false;

  static const bool _textInputMode = ShoppingFlowController.textInputMode;

  @override
  void initState() {
    super.initState();
    if (widget.autoInitialize) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        _controller.initialize();
      });
    }
  }

  void _onControllerChanged() {
    _handlePendingWebviewTask();
    _handleCloseAppRequest();
    if (mounted) {
      setState(() {});
    }
  }

  void _handleCloseAppRequest() {
    if (!_controller.closeAppRequested || !mounted) {
      return;
    }
    _controller.consumeCloseAppRequest();
    WidgetsBinding.instance.addPostFrameCallback((_) async {
      if (!mounted) {
        return;
      }
      if (!kIsWeb && defaultTargetPlatform == TargetPlatform.android) {
        await SystemNavigator.pop();
        return;
      }
      await _controller.resetConversation();
    });
  }

  void _handlePendingWebviewTask() {
    final task = _controller.pendingWebviewTask;
    if (!mounted || task == null) {
      return;
    }
    if (_completedWebviewCommandKeys.contains(task.commandKey)) {
      return;
    }
    if (_isWebviewOpen || _lastWebviewCommandKey == task.commandKey) {
      return;
    }

    _isWebviewOpen = true;
    _lastWebviewCommandKey = task.commandKey;
    WidgetsBinding.instance.addPostFrameCallback((_) async {
      if (!mounted) {
        _isWebviewOpen = false;
        return;
      }
      await Navigator.of(context).push(
        MaterialPageRoute<void>(
          builder: (_) => PaymentWebViewScreen(
            url: task.url,
            platform: task.platform,
            shopName: task.shopName,
            assistantMessage: _controller.assistantText,
            task: task.task,
            orderId: task.orderId,
            paymentId: task.paymentId,
            productName: task.productName,
            quantity: task.quantity,
            canonicalProductUrl: task.canonicalProductUrl,
            onResult: (result, extraData) {
              return _controller.handleWebviewResult(
                task,
                result: result,
                extraData: extraData,
              );
            },
          ),
        ),
      );
      _isWebviewOpen = false;
      _completedWebviewCommandKeys.add(task.commandKey);
      if (_lastWebviewCommandKey == task.commandKey) {
        _lastWebviewCommandKey = null;
      }
    });
  }

  @override
  void dispose() {
    _controller.removeListener(_onControllerChanged);
    if (widget.controller == null) {
      _controller.dispose();
    }
    _textInputController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final mediaQuery = MediaQuery.of(context);
    final bottomInset = mediaQuery.padding.bottom;
    final bottomButtonHeight = 64.0;
    final usesProductDetailLayout =
        _controller.step == ShoppingStep.showProduct ||
        _controller.step == ShoppingStep.askQuantity;
    final horizontalPadding = usesProductDetailLayout
        ? 0.0
        : 20.0;
    final topTextHeight =
        (usesProductDetailLayout
                ? mediaQuery.size.height * 0.16
                : mediaQuery.size.height * 0.26)
            .clamp(
              usesProductDetailLayout ? 112.0 : 176.0,
              usesProductDetailLayout ? 156.0 : 250.0,
            );
    final centerResponseText = _shouldCenterResponseText(_controller.step);
    final useFakeGlass =
        !kIsWeb && defaultTargetPlatform == TargetPlatform.android;
    return Scaffold(
      body: LiquidGlassLayer(
        fake: useFakeGlass,
        settings: LiquidGlassSettings(
          glassColor: Colors.white.withValues(alpha: 0.08),
          thickness: 28,
          blur: 9,
          lightIntensity: 0.85,
          ambientStrength: 0.24,
          saturation: 1.22,
          refractiveIndex: 1.16,
        ),
        child: LiquidGlassBlendGroup(
          blend: 0,
          child: Container(
            decoration: const BoxDecoration(color: Color(0xFFF9FCFB)),
            child: SafeArea(
              child: Stack(
                children: [
                  const Positioned.fill(child: _GlassBackgroundLayer()),
                  Padding(
                    padding: EdgeInsets.symmetric(
                      horizontal: horizontalPadding,
                      vertical: 14,
                    ),
                    child: Column(
                      children: [
                        Padding(
                          padding: const EdgeInsets.only(bottom: 16),
                          child: ShoppingProgressSteps(
                            currentStep: _controller.shoppingProgressStepIndex,
                          ),
                        ),
                        if (!centerResponseText &&
                            _controller.step != ShoppingStep.confirmAddress)
                          ClipRect(
                            child: SizedBox(
                              height: topTextHeight,
                              child: Center(
                                child: _buildPromptText(
                                  fontSize: _promptFontSizeForStep(
                                    _controller.step,
                                  ),
                                  maxLines: _promptMaxLinesForStep(
                                    _controller.step,
                                  ),
                                ),
                              ),
                            ),
                          ),
                        Expanded(
                          child: AnimatedSwitcher(
                            duration: const Duration(milliseconds: 320),
                            layoutBuilder: (currentChild, previousChildren) {
                              return currentChild ?? const SizedBox.shrink();
                            },
                            child: centerResponseText
                                ? Column(
                                    key: ValueKey(
                                      'center-text-${_controller.step.name}',
                                    ),
                                    children: [
                                      Expanded(
                                        child: Center(
                                          child: Padding(
                                            padding: const EdgeInsets.symmetric(
                                              horizontal: 12,
                                            ),
                                            child: _buildPromptText(
                                              fontSize: _promptFontSizeForStep(
                                                _controller.step,
                                              ),
                                              maxLines: _promptMaxLinesForStep(
                                                _controller.step,
                                              ),
                                            ),
                                          ),
                                        ),
                                      ),
                                      if (_controller.shouldShowVoiceButton &&
                                          !_textInputMode)
                                        Padding(
                                          padding: const EdgeInsets.only(bottom: 24),
                                          child: _buildVoiceOrb(),
                                        ),
                                      if (_controller.shouldShowVoiceButton &&
                                          _textInputMode)
                                        Padding(
                                          padding: const EdgeInsets.fromLTRB(
                                            20, 0, 20, 20,
                                          ),
                                          child: _buildTextInputBar(),
                                        ),
                                      _buildBody(),
                                    ],
                                  )
                                : _buildBody(),
                          ),
                        ),
                        const SizedBox(height: 16),
                        Padding(
                          padding: EdgeInsets.only(
                            bottom: bottomInset > 0 ? 4 : 0,
                          ),
                          child: SizedBox(
                            width: double.infinity,
                            height: bottomButtonHeight,
                            child: GlassButton(
                              label: '대화 종료',
                              foregroundColor: const Color(0xFFD77B9E),
                              onPressed: () async {
                                await _controller.resetConversation();
                              },
                            ),
                          ),
                        ),
                      ],
                    ),
                  ),
                  if (!_textInputMode &&
                      _controller.shouldShowVoiceButton &&
                      !centerResponseText)
                    _controller.step == ShoppingStep.showProduct
                        ? Positioned(
                            left: 0,
                            right: 0,
                            top: topTextHeight + 94,
                            child: _buildVoiceOrb(),
                          )
                        : Positioned(
                            left: 0,
                            right: 0,
                            bottom: bottomInset + bottomButtonHeight + 14,
                            child: _buildVoiceOrb(),
                          ),
                  if (_textInputMode &&
                      _controller.shouldShowVoiceButton &&
                      !centerResponseText)
                    Positioned(
                      left: 20,
                      right: 20,
                      bottom: bottomInset + bottomButtonHeight + 10,
                      child: _buildTextInputBar(),
                    )
                  else if (!_textInputMode && _controller.shouldShowVoiceButton)
                    Positioned(
                      right: 20,
                      bottom: bottomInset + bottomButtonHeight + 14,
                      child: _buildKeyboardToggle(),
                    ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }

  // TEXT_INPUT_MODE=true 빌드에서 항상 표시되는 고정 입력창
  Widget _buildTextInputBar() {
    return Row(
      children: [
        Expanded(
          child: TextField(
            controller: _textInputController,
            autofocus: false,
            style: const TextStyle(
              fontFamily: 'Pretendard',
              fontSize: 17,
              color: Colors.black87,
            ),
            decoration: InputDecoration(
              hintText: '메시지를 입력하세요',
              hintStyle: const TextStyle(color: Colors.black38),
              filled: true,
              fillColor: Colors.white.withValues(alpha: 0.88),
              contentPadding: const EdgeInsets.symmetric(
                horizontal: 18,
                vertical: 12,
              ),
              border: OutlineInputBorder(
                borderRadius: BorderRadius.circular(28),
                borderSide: BorderSide.none,
              ),
              enabledBorder: OutlineInputBorder(
                borderRadius: BorderRadius.circular(28),
                borderSide: BorderSide(
                  color: const Color(0xFFD77B9E).withValues(alpha: 0.3),
                  width: 1.2,
                ),
              ),
              focusedBorder: OutlineInputBorder(
                borderRadius: BorderRadius.circular(28),
                borderSide: const BorderSide(
                  color: Color(0xFFD77B9E),
                  width: 1.6,
                ),
              ),
            ),
            onSubmitted: _submitText,
          ),
        ),
        const SizedBox(width: 8),
        GestureDetector(
          onTap: () => _submitText(_textInputController.text),
          child: Container(
            width: 46,
            height: 46,
            decoration: const BoxDecoration(
              color: Color(0xFFD77B9E),
              shape: BoxShape.circle,
            ),
            child: const Icon(Icons.send_rounded, color: Colors.white, size: 22),
          ),
        ),
      ],
    );
  }

  Future<void> _submitText(String text) async {
    if (text.trim().isEmpty) return;
    _textInputController.clear();
    await _controller.submitTextInput(text);
  }

  // 토글 버튼 (TEXT_INPUT_MODE=false 빌드 전용)
  Widget _buildKeyboardToggle() {
    return Column(
      mainAxisSize: MainAxisSize.min,
      crossAxisAlignment: CrossAxisAlignment.end,
      children: [
        if (_showTextInput)
          Padding(
            padding: const EdgeInsets.only(bottom: 8),
            child: SizedBox(
              width: MediaQuery.of(context).size.width - 40,
              child: Row(
                children: [
                  Expanded(
                    child: TextField(
                      controller: _textInputController,
                      autofocus: true,
                      style: const TextStyle(color: Colors.black87),
                      decoration: InputDecoration(
                        hintText: '메시지 입력...',
                        hintStyle: const TextStyle(color: Colors.black38),
                        filled: true,
                        fillColor: const Color(0x22000000),
                        contentPadding: const EdgeInsets.symmetric(
                          horizontal: 16,
                          vertical: 10,
                        ),
                        border: OutlineInputBorder(
                          borderRadius: BorderRadius.circular(24),
                          borderSide: BorderSide.none,
                        ),
                      ),
                      onSubmitted: (text) async {
                        if (text.trim().isEmpty) return;
                        _textInputController.clear();
                        setState(() => _showTextInput = false);
                        _controller.setTextInputMode(false);
                        await _controller.submitTextInput(text);
                      },
                    ),
                  ),
                  const SizedBox(width: 8),
                  IconButton(
                    icon: const Icon(Icons.send, color: Colors.black54),
                    onPressed: () async {
                      final text = _textInputController.text;
                      if (text.trim().isEmpty) return;
                      _textInputController.clear();
                      setState(() => _showTextInput = false);
                      _controller.setTextInputMode(false);
                      await _controller.submitTextInput(text);
                    },
                  ),
                ],
              ),
            ),
          ),
        GestureDetector(
          onTap: () {
            final next = !_showTextInput;
            setState(() => _showTextInput = next);
            _controller.setTextInputMode(next);
            if (next) {
              unawaited(_controller.stopListeningForTextInput());
            }
          },
          child: Container(
            width: 40,
            height: 40,
            decoration: const BoxDecoration(
              color: Color(0x22000000),
              shape: BoxShape.circle,
            ),
            child: Icon(
              _showTextInput ? Icons.keyboard_hide : Icons.keyboard,
              color: Colors.black45,
              size: 20,
            ),
          ),
        ),
      ],
    );
  }

  Widget _buildVoiceOrb() {
    return Center(
      child: GestureDetector(
        behavior: HitTestBehavior.translucent,
        onTap: () {
          unawaited(_controller.onVoiceButtonTap());
        },
        child: VoiceTurnOrb(
          state: _controller.voiceTurnState,
          level: _controller.voiceLevel,
        ),
      ),
    );
  }

  bool _shouldCenterResponseText(ShoppingStep step) {
    switch (step) {
      case ShoppingStep.askProduct:
      case ShoppingStep.error:
        return true;
      case ShoppingStep.askQuantity:
      case ShoppingStep.showProduct:
      case ShoppingStep.cartCompleted:
      case ShoppingStep.askMoreOrCheckout:
      case ShoppingStep.searchingProduct:
      case ShoppingStep.addingToCart:
      case ShoppingStep.confirmAddress:
      case ShoppingStep.enterPassword:
      case ShoppingStep.processingPayment:
      case ShoppingStep.paymentCompleted:
        return false;
    }
  }

  double _promptFontSizeForStep(ShoppingStep step) {
    switch (step) {
      case ShoppingStep.showProduct:
      case ShoppingStep.askQuantity:
      case ShoppingStep.addingToCart:
        return 38;
      case ShoppingStep.cartCompleted:
      case ShoppingStep.askMoreOrCheckout:
        return 24;
      case ShoppingStep.enterPassword:
        return 30;
      case ShoppingStep.askProduct:
      case ShoppingStep.searchingProduct:
      case ShoppingStep.confirmAddress:
      case ShoppingStep.processingPayment:
      case ShoppingStep.paymentCompleted:
      case ShoppingStep.error:
        return 38;
    }
  }

  int? _promptMaxLinesForStep(ShoppingStep step) {
    switch (step) {
      case ShoppingStep.showProduct:
      case ShoppingStep.askQuantity:
      case ShoppingStep.addingToCart:
        return 1;
      case ShoppingStep.cartCompleted:
      case ShoppingStep.askMoreOrCheckout:
        return 2;
      case ShoppingStep.askProduct:
      case ShoppingStep.searchingProduct:
      case ShoppingStep.confirmAddress:
      case ShoppingStep.enterPassword:
      case ShoppingStep.processingPayment:
      case ShoppingStep.paymentCompleted:
      case ShoppingStep.error:
        return null;
    }
  }

  Widget _buildBody() {
    switch (_controller.step) {
      case ShoppingStep.askProduct:
        return _buildReplyExamples();
      case ShoppingStep.askQuantity:
        final product = _controller.currentProduct;
        if (product == null) {
          return const SizedBox(key: ValueKey('ask-quantity-empty'));
        }
        return Stack(
          key: const ValueKey('ask-quantity'),
          children: [
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 0),
              child: ProductCard(product: product),
            ),
            Align(
              alignment: Alignment.bottomCenter,
              child: Padding(
                padding: const EdgeInsets.only(bottom: 10),
                child: _buildReplyExamples(),
              ),
            ),
          ],
        );
      case ShoppingStep.cartCompleted:
      case ShoppingStep.askMoreOrCheckout:
        return Center(
          key: ValueKey('cart-summary-${_controller.step.name}'),
          child: Padding(
            padding: const EdgeInsets.only(top: 8),
            child: CartSummaryCard(
              userName: _controller.cartOwnerName,
              items: _controller.cartItems,
              totalQuantity: _controller.totalCartQuantity,
              totalPriceText: _controller.totalCartPriceText,
            ),
          ),
        );
      case ShoppingStep.searchingProduct:
        return Center(
          key: const ValueKey('searching-product'),
          child: _SearchingShowcase(
            userName: _controller.userName,
            keyword: _controller.activeSearchKeyword,
          ),
        );
      case ShoppingStep.showProduct:
        final product = _controller.currentProduct;
        if (product == null) {
          return const SizedBox(key: ValueKey('show-product-empty'));
        }
        return Padding(
          key: const ValueKey('show-product'),
          padding: const EdgeInsets.symmetric(horizontal: 0),
          child: ProductCard(product: product),
        );
      case ShoppingStep.addingToCart:
        return CartProgressCard(
          key: const ValueKey('adding-to-cart'),
          title: _controller.cartStatusTitle,
          statusText: _controller.cartStatusText,
          helperText: _controller.cartHelperText,
          progress: _controller.cartProgress,
          items: _controller.cartItems,
        );
      case ShoppingStep.confirmAddress:
        return LayoutBuilder(
          key: const ValueKey('confirm-address'),
          builder: (context, constraints) {
            return SingleChildScrollView(
              physics: const BouncingScrollPhysics(),
              child: ConstrainedBox(
                constraints: BoxConstraints(minHeight: constraints.maxHeight),
                child: Center(
                  child: Padding(
                    padding: const EdgeInsets.only(bottom: 12),
                    child: AddressConfirmCard(
                      summary:
                          _controller.checkoutSummary ??
                          CheckoutSummary.mock(_controller.cartItems),
                    ),
                  ),
                ),
              ),
            );
          },
        );
      case ShoppingStep.enterPassword:
        return PinKeypad(
          key: const ValueKey('enter-password'),
          pin: _controller.pin,
          onDigitTap: _controller.onPasswordDigit,
          onBackspace: _controller.removePasswordDigit,
        );
      case ShoppingStep.processingPayment:
        return const Center(
          key: ValueKey('processing-payment'),
          child: SizedBox(
            width: 74,
            height: 74,
            child: CircularProgressIndicator(
              strokeWidth: 6,
              valueColor: AlwaysStoppedAnimation(Color(0xFFD77B9E)),
              backgroundColor: Color(0xFFF1F3F6),
            ),
          ),
        );
      case ShoppingStep.paymentCompleted:
        return Center(
          key: const ValueKey('payment-completed'),
          child: Image.asset(
            'assets/images/ddalangoo_happy.png',
            height: 210,
            fit: BoxFit.contain,
            errorBuilder: (context, error, stackTrace) => Container(
              width: 170,
              height: 170,
              decoration: BoxDecoration(
                color: const Color(0xFFF5F7FA),
                borderRadius: BorderRadius.circular(30),
              ),
              child: const Icon(
                Icons.favorite_rounded,
                size: 88,
                color: Color(0xFFD7A8B9),
              ),
            ),
          ),
        );
      case ShoppingStep.error:
        return _buildReplyExamples();
    }
  }

  Widget _buildPromptText({double fontSize = 38, int? maxLines}) {
    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        DallangResponseText(
          text: _controller.assistantText,
          fontSize: fontSize,
          maxLines: maxLines,
          ttsDurationMs: _controller.assistantTtsDurationMs,
        ),
      ],
    );
  }

  Widget _buildReplyExamples() {
    if (!_controller.shouldShowReplyExamples ||
        _controller.suggestedReplies.isEmpty) {
      return const SizedBox.shrink();
    }

    return Padding(
      padding: const EdgeInsets.only(left: 6, right: 6, bottom: 10),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Text(
            '예시 답변',
            style: TextStyle(
              fontFamily: 'Pretendard',
              fontSize: 15,
              fontWeight: FontWeight.w700,
              color: const Color(0xFF7F8B97).withValues(alpha: 0.96),
            ),
          ),
          const SizedBox(height: 12),
          Wrap(
            alignment: WrapAlignment.center,
            spacing: 8,
            runSpacing: 8,
            children: _controller.suggestedReplies.map((reply) {
              return InkWell(
                borderRadius: BorderRadius.circular(999),
                onTap: () {
                  unawaited(_controller.submitSuggestedReply(reply));
                },
                child: Container(
                  padding: const EdgeInsets.symmetric(
                    horizontal: 16,
                    vertical: 10,
                  ),
                  decoration: BoxDecoration(
                    color: Colors.white.withValues(alpha: 0.72),
                    borderRadius: BorderRadius.circular(999),
                    border: Border.all(color: const Color(0xFFDDE4EB)),
                  ),
                  child: Text(
                    reply,
                    style: const TextStyle(
                      fontFamily: 'Pretendard',
                      fontSize: 16,
                      fontWeight: FontWeight.w600,
                      color: Color(0xFF51606E),
                    ),
                  ),
                ),
              );
            }).toList(),
          ),
        ],
      ),
    );
  }
}

class _GlassBackgroundLayer extends StatelessWidget {
  const _GlassBackgroundLayer();

  @override
  Widget build(BuildContext context) {
    return Stack(
      children: [
        Container(
          decoration: const BoxDecoration(
            gradient: LinearGradient(
              colors: [Color(0xFFFDFEFE), Color(0xFFF8FAFC), Color(0xFFFDFDFE)],
              begin: Alignment.topLeft,
              end: Alignment.bottomRight,
              stops: [0, 0.52, 1],
            ),
          ),
        ),
        Positioned(
          top: -120,
          left: -80,
          child: _BlurredBlob(
            width: 280,
            height: 280,
            colors: const [Color(0xFFFFFFFF), Color(0xFFF4F7FB)],
            borderRadius: 180,
            blurSigma: 36,
          ),
        ),
        Positioned(
          top: 90,
          right: -110,
          child: _BlurredBlob(
            width: 320,
            height: 320,
            colors: const [Color(0xFFFFFFFF), Color(0xFFF3F5F9)],
            borderRadius: 220,
            blurSigma: 38,
          ),
        ),
        Positioned(
          bottom: 110,
          left: -70,
          child: _BlurredBlob(
            width: 230,
            height: 230,
            colors: const [Color(0xFFFFFFFF), Color(0xFFF5F7FA)],
            borderRadius: 180,
            blurSigma: 32,
          ),
        ),
        Positioned(
          bottom: -40,
          right: -30,
          child: _BlurredBlob(
            width: 210,
            height: 210,
            colors: const [Color(0xFFFDFEFF), Color(0xFFF1F4F8)],
            borderRadius: 160,
            blurSigma: 30,
          ),
        ),
        IgnorePointer(
          child: Container(
            decoration: BoxDecoration(
              gradient: LinearGradient(
                colors: [
                  Colors.white.withValues(alpha: 0.4),
                  Colors.white.withValues(alpha: 0.08),
                  Colors.white.withValues(alpha: 0.28),
                ],
                begin: Alignment.topCenter,
                end: Alignment.bottomCenter,
              ),
            ),
          ),
        ),
      ],
    );
  }
}

class _SearchingShowcase extends StatefulWidget {
  const _SearchingShowcase({this.userName, this.keyword});

  final String? userName;
  final String? keyword;

  @override
  State<_SearchingShowcase> createState() => _SearchingShowcaseState();
}

class _SearchingShowcaseState extends State<_SearchingShowcase> {
  static const _assets = <String>[
    'assets/images/ddalangoo_curious.png',
    'assets/images/dddalangoo_cart.png',
    'assets/images/ddalangoo_cheerful.png',
  ];

  Timer? _timer;
  int _index = 0;

  List<String> get _messages {
    final trimmedName = widget.userName?.trim();
    final displayName = (trimmedName != null && trimmedName.isNotEmpty)
        ? '$trimmedName님'
        : '고객님';
    final keyword = widget.keyword?.trim() ?? '';
    final targetText = keyword.isNotEmpty
        ? '$keyword${_hasBatchim(keyword) ? '을' : '를'}'
        : '상품을';
    return <String>[
      '$targetText 찾고 있어요',
      keyword.isNotEmpty ? '$keyword 상품을 비교하고 있어요' : '상품을 비교하고 있어요',
      '$displayName을 위한\n최고의 상품을 고르고 있어요',
    ];
  }

  @override
  void initState() {
    super.initState();
    _timer = Timer.periodic(const Duration(seconds: 2), (_) {
      if (!mounted) {
        return;
      }
      setState(() {
        _index = (_index + 1) % _assets.length;
      });
    });
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        AnimatedSwitcher(
          duration: const Duration(milliseconds: 250),
          child: Text(
            _messages[_index % _messages.length],
            key: ValueKey('search-message-$_index'),
            textAlign: TextAlign.center,
            style: const TextStyle(
              fontFamily: 'Pretendard',
              fontSize: 20,
              fontWeight: FontWeight.w700,
              color: Color(0xFF51606E),
              height: 1.45,
            ),
          ),
        ),
        const SizedBox(height: 18),
        AnimatedSwitcher(
          duration: const Duration(milliseconds: 450),
          child: Image.asset(
            _assets[_index],
            key: ValueKey(_assets[_index]),
            height: 210,
            fit: BoxFit.contain,
          ),
        ),
      ],
    );
  }
}

bool _hasBatchim(String text) {
  final trimmed = text.trim();
  if (trimmed.isEmpty) {
    return false;
  }
  final codeUnit = trimmed.codeUnitAt(trimmed.length - 1);
  return codeUnit >= 0xAC00 &&
      codeUnit <= 0xD7A3 &&
      ((codeUnit - 0xAC00) % 28 != 0);
}

class _BlurredBlob extends StatelessWidget {
  const _BlurredBlob({
    required this.width,
    required this.height,
    required this.colors,
    required this.borderRadius,
    required this.blurSigma,
  });

  final double width;
  final double height;
  final List<Color> colors;
  final double borderRadius;
  final double blurSigma;

  @override
  Widget build(BuildContext context) {
    return IgnorePointer(
      child: ImageFiltered(
        imageFilter: ImageFilter.blur(sigmaX: blurSigma, sigmaY: blurSigma),
        child: Container(
          width: width,
          height: height,
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(borderRadius),
            gradient: RadialGradient(
              colors: [
                colors.first.withValues(alpha: 0.68),
                colors.last.withValues(alpha: 0.3),
                Colors.white.withValues(alpha: 0.02),
              ],
              stops: const [0.08, 0.55, 1],
            ),
          ),
        ),
      ),
    );
  }
}
