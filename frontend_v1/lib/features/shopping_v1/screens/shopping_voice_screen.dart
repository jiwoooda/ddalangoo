import 'package:flutter/material.dart';
import 'package:flutter/foundation.dart';
import 'dart:ui';
import 'package:liquid_glass_renderer/liquid_glass_renderer.dart';

import '../../../presentation/screens/call/payment_webview_screen.dart';
import '../controllers/shopping_flow_controller.dart';
import '../models/shopping_v1_models.dart';
import '../widgets/address_confirm_card.dart';
import '../widgets/cart_progress_card.dart';
import '../widgets/dallang_response_text.dart';
import '../widgets/glass_card.dart';
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
    if (mounted) {
      setState(() {});
    }
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
      case ShoppingStep.cartCompleted:
      case ShoppingStep.askMoreOrCheckout:
      case ShoppingStep.error:
        return true;
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
      case ShoppingStep.cartCompleted:
      case ShoppingStep.askMoreOrCheckout:
        return const SizedBox.shrink();
      case ShoppingStep.searchingProduct:
        return const Center(
          key: ValueKey('searching-product'),
          child: SizedBox(
            width: 92,
            height: 92,
            child: CircularProgressIndicator(
              strokeWidth: 6,
              valueColor: AlwaysStoppedAnimation(Color(0xFFD77B9E)),
              backgroundColor: Color(0xFFF1F3F6),
            ),
          ),
        );
      case ShoppingStep.showProduct:
        return Padding(
          key: const ValueKey('show-product'),
          padding: const EdgeInsets.symmetric(horizontal: 0),
          child: ProductCard(
            product: _controller.currentProduct ?? ProductViewData.mock(),
          ),
        );
      case ShoppingStep.addingToCart:
        return CartProgressCard(
          key: const ValueKey('adding-to-cart'),
          title: _controller.cartStatusTitle,
          statusText: _controller.cartStatusText,
          helperText: _controller.cartHelperText,
          progress: _controller.cartProgress,
        );
      case ShoppingStep.confirmAddress:
        return AddressConfirmCard(
          key: const ValueKey('confirm-address'),
          summary:
              _controller.checkoutSummary ??
              CheckoutSummary.mock(_controller.cartItems),
          onConfirm: _controller.confirmAddressStep,
        );
      case ShoppingStep.enterPassword:
        return PinKeypad(
          key: const ValueKey('enter-password'),
          pin: _controller.pin,
          onDigitTap: _controller.onPasswordDigit,
          onBackspace: _controller.removePasswordDigit,
        );
      case ShoppingStep.processingPayment:
        return GlassCard(
          key: const ValueKey('processing-payment'),
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              const SizedBox(
                width: 66,
                height: 66,
                child: CircularProgressIndicator(
                  strokeWidth: 6,
                  valueColor: AlwaysStoppedAnimation(Color(0xFFD77B9E)),
                  backgroundColor: Color(0xFFF1F3F6),
                ),
              ),
              const SizedBox(height: 20),
              Text(
                _controller.assistantText.isEmpty
                    ? '결제를 진행 중이에요.'
                    : _controller.assistantText,
                textAlign: TextAlign.center,
                style: const TextStyle(
                  fontFamily: 'Pretendard',
                  fontSize: 22,
                  fontWeight: FontWeight.w800,
                  color: Color(0xFF223140),
                ),
              ),
            ],
          ),
        );
      case ShoppingStep.paymentCompleted:
        return GlassCard(
          key: const ValueKey('payment-completed'),
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              Image.asset(
                'assets/images/ddalangoo_frame2.png',
                height: 170,
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
              const SizedBox(height: 18),
              Text(
                _controller.assistantText.isEmpty
                    ? '결제가 완료되었어요'
                    : _controller.assistantText,
                textAlign: TextAlign.center,
                style: const TextStyle(
                  fontFamily: 'Pretendard',
                  fontSize: 26,
                  fontWeight: FontWeight.w900,
                  color: Color(0xFFD77B9E),
                ),
              ),
            ],
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
