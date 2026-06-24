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
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final mediaQuery = MediaQuery.of(context);
    final bottomInset = mediaQuery.padding.bottom;
    final bottomButtonHeight = 64.0;
    final horizontalPadding = _controller.step == ShoppingStep.showProduct
        ? 0.0
        : 20.0;
    final topTextHeight = (_controller.step == ShoppingStep.showProduct
            ? mediaQuery.size.height * 0.16
            : mediaQuery.size.height * 0.26)
        .clamp(
          _controller.step == ShoppingStep.showProduct ? 112.0 : 176.0,
          _controller.step == ShoppingStep.showProduct ? 156.0 : 250.0,
        );
    final centerResponseText = _shouldCenterResponseText(_controller.step);
    final useFakeGlass = !kIsWeb && defaultTargetPlatform == TargetPlatform.android;
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
                        if (!centerResponseText)
                          SizedBox(
                            height: topTextHeight,
                            child: Center(
                              child: DallangResponseText(
                                text: _controller.assistantText,
                                fontSize: _controller.step ==
                                        ShoppingStep.showProduct
                                    ? 28
                                    : 34,
                                maxLines: _controller.step ==
                                        ShoppingStep.showProduct
                                    ? 3
                                    : null,
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
                                    key: ValueKey('center-text-${_controller.step.name}'),
                                    children: [
                                      Expanded(
                                        child: Center(
                                          child: Padding(
                                            padding: const EdgeInsets.symmetric(
                                              horizontal: 12,
                                            ),
                                            child: DallangResponseText(
                                              text: _controller.assistantText,
                                            ),
                                          ),
                                        ),
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
                  if (_controller.shouldShowVoiceButton)
                    Positioned(
                      left: 0,
                      right: 0,
                      bottom: bottomInset + bottomButtonHeight + 14,
                      child: IgnorePointer(
                        child: Center(
                          child: VoiceTurnOrb(
                            state: _controller.voiceTurnState,
                            level: _controller.voiceLevel,
                          ),
                        ),
                      ),
                    ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }

  bool _shouldCenterResponseText(ShoppingStep step) {
    switch (step) {
      case ShoppingStep.askProduct:
      case ShoppingStep.askQuantity:
      case ShoppingStep.error:
        return true;
      case ShoppingStep.cartCompleted:
      case ShoppingStep.askMoreOrCheckout:
      case ShoppingStep.searchingProduct:
      case ShoppingStep.showProduct:
      case ShoppingStep.addingToCart:
      case ShoppingStep.confirmAddress:
      case ShoppingStep.enterPassword:
      case ShoppingStep.processingPayment:
      case ShoppingStep.paymentCompleted:
        return false;
    }
  }

  Widget _buildBody() {
    switch (_controller.step) {
      case ShoppingStep.askProduct:
      case ShoppingStep.askQuantity:
        return const SizedBox.shrink();
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
        return const Center(
          key: ValueKey('searching-product'),
          child: _SearchingShowcase(),
        );
      case ShoppingStep.showProduct:
        final product = _controller.currentProduct;
        if (product == null) {
          return const SizedBox(
            key: ValueKey('show-product-empty'),
          );
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
        return SingleChildScrollView(
          key: const ValueKey('confirm-address'),
          physics: const BouncingScrollPhysics(),
          padding: const EdgeInsets.only(bottom: 12),
          child: AddressConfirmCard(
            summary:
                _controller.checkoutSummary ??
                CheckoutSummary.mock(_controller.cartItems),
            onConfirm: _controller.confirmAddressStep,
          ),
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
        return const SizedBox.shrink();
    }
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
  const _SearchingShowcase();

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
    return AnimatedSwitcher(
      duration: const Duration(milliseconds: 450),
      child: Image.asset(
        _assets[_index],
        key: ValueKey(_assets[_index]),
        height: 210,
        fit: BoxFit.contain,
      ),
    );
  }
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
