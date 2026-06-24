import 'package:flutter/material.dart';

import '../controllers/shopping_flow_controller.dart';
import '../models/shopping_v1_models.dart';
import '../widgets/address_confirm_card.dart';
import '../widgets/cart_progress_card.dart';
import '../widgets/dallang_response_text.dart';
import '../widgets/glass_card.dart';
import '../widgets/loading_dots.dart';
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
    if (mounted) {
      setState(() {});
    }
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
    final bottomAreaHeight = _controller.shouldShowVoiceButton ? 172.0 : 112.0;
    final topTextHeight = (mediaQuery.size.height * 0.26).clamp(176.0, 250.0);
    return Scaffold(
      body: Container(
        decoration: const BoxDecoration(
          gradient: LinearGradient(
            colors: [Color(0xFFF7FFF9), Color(0xFFF9F4FF), Color(0xFFFFF8FB)],
            begin: Alignment.topLeft,
            end: Alignment.bottomRight,
          ),
        ),
        child: SafeArea(
          child: Stack(
            children: [
              Positioned(
                top: -40,
                left: -20,
                child: _blurOrb(const Color(0xFFA8F0D1), 180),
              ),
              Positioned(
                top: 120,
                right: -40,
                child: _blurOrb(const Color(0xFFFFC7DC), 200),
              ),
              Padding(
                padding: const EdgeInsets.symmetric(
                  horizontal: 20,
                  vertical: 14,
                ),
                child: Column(
                  children: [
                    SizedBox(
                      height: topTextHeight,
                      child: Center(
                        child: DallangResponseText(
                          text: _controller.assistantText,
                        ),
                      ),
                    ),
                    Expanded(
                      child: AnimatedSwitcher(
                        duration: const Duration(milliseconds: 320),
                        child: _buildBody(),
                      ),
                    ),
                    const SizedBox(height: 16),
                    Padding(
                      padding: EdgeInsets.only(bottom: bottomInset > 0 ? 4 : 0),
                      child: Column(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          SizedBox(
                            height: bottomAreaHeight,
                            child: Center(
                              child: _controller.shouldShowVoiceButton
                                  ? VoiceTurnOrb(
                                      state: _controller.voiceTurnState,
                                      level: _controller.voiceLevel,
                                    )
                                  : const SizedBox.shrink(),
                            ),
                          ),
                          SizedBox(
                            width: double.infinity,
                            child: FilledButton(
                              style: FilledButton.styleFrom(
                                backgroundColor: const Color(0xFFFFE6F0),
                                foregroundColor: const Color(0xFFFF5B98),
                                padding: const EdgeInsets.symmetric(
                                  vertical: 18,
                                ),
                                textStyle: const TextStyle(
                                  fontFamily: 'Pretendard',
                                  fontSize: 18,
                                  fontWeight: FontWeight.w800,
                                ),
                                shape: RoundedRectangleBorder(
                                  borderRadius: BorderRadius.circular(22),
                                ),
                              ),
                              onPressed: () async {
                                if (Navigator.of(context).canPop()) {
                                  Navigator.of(context).pop();
                                  return;
                                }
                                await _controller.resetConversation();
                              },
                              child: const Text('대화 종료'),
                            ),
                          ),
                        ],
                      ),
                    ),
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildBody() {
    switch (_controller.step) {
      case ShoppingStep.askProduct:
        return _statusCard(
          key: const ValueKey('ask-product'),
          title: '음성으로 편하게 말씀해주세요',
          message: '예: 흑임자 인절미 사고 싶어',
        );
      case ShoppingStep.searchingProduct:
        return GlassCard(
          key: const ValueKey('searching-product'),
          child: const Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              SizedBox(
                width: 64,
                height: 64,
                child: CircularProgressIndicator(
                  strokeWidth: 6,
                  valueColor: AlwaysStoppedAnimation(Color(0xFFFF6FAE)),
                  backgroundColor: Color(0xFFFFE7F1),
                ),
              ),
              SizedBox(height: 20),
              LoadingDots(),
            ],
          ),
        );
      case ShoppingStep.showProduct:
        return ProductCard(
          key: const ValueKey('show-product'),
          product: _controller.currentProduct ?? ProductViewData.mock(),
        );
      case ShoppingStep.askQuantity:
        return _statusCard(
          key: const ValueKey('ask-quantity'),
          title: '수량을 알려주세요',
          message: '예: 3개 살래',
        );
      case ShoppingStep.addingToCart:
        return CartProgressCard(
          key: const ValueKey('adding-to-cart'),
          title: _controller.cartStatusTitle,
          statusText: _controller.cartStatusText,
          helperText: _controller.cartHelperText,
          progress: _controller.cartProgress,
        );
      case ShoppingStep.cartCompleted:
      case ShoppingStep.askMoreOrCheckout:
        return _statusCard(
          key: const ValueKey('ask-more-checkout'),
          title: '다음 단계를 말씀해주세요',
          message: '예: 하나 더 살래 / 결제해줘',
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
          child: const Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              SizedBox(
                width: 66,
                height: 66,
                child: CircularProgressIndicator(
                  strokeWidth: 6,
                  valueColor: AlwaysStoppedAnimation(Color(0xFFFF6FAE)),
                  backgroundColor: Color(0xFFFFE7F1),
                ),
              ),
              SizedBox(height: 20),
              Text(
                '결제를 진행 중이에요.',
                style: TextStyle(
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
                    color: const Color(0xFFFFEEF5),
                    borderRadius: BorderRadius.circular(30),
                  ),
                  child: const Icon(
                    Icons.favorite_rounded,
                    size: 88,
                    color: Color(0xFFFF8FB8),
                  ),
                ),
              ),
              const SizedBox(height: 18),
              Text(
                _controller.isMockMode ? '결제가 완료되었어요' : '결제가 완료되었어요',
                style: const TextStyle(
                  fontFamily: 'Pretendard',
                  fontSize: 26,
                  fontWeight: FontWeight.w900,
                  color: Color(0xFFFF5B98),
                ),
              ),
            ],
          ),
        );
      case ShoppingStep.error:
        return _statusCard(
          key: const ValueKey('error-state'),
          title: '다시 한 번 말씀해주세요',
          message: _controller.errorMessage ?? '잠시 문제가 생겼어요.',
        );
    }
  }

  Widget _statusCard({
    required Key key,
    required String title,
    required String message,
  }) {
    return GlassCard(
      key: key,
      child: Center(
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Text(
              title,
              textAlign: TextAlign.center,
              style: const TextStyle(
                fontFamily: 'Pretendard',
                fontSize: 26,
                fontWeight: FontWeight.w800,
                color: Color(0xFF12202F),
              ),
            ),
            const SizedBox(height: 14),
            Text(
              message,
              textAlign: TextAlign.center,
              style: const TextStyle(
                fontFamily: 'Pretendard',
                fontSize: 18,
                fontWeight: FontWeight.w600,
                color: Color(0xFF5A6672),
                height: 1.45,
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _blurOrb(Color color, double size) {
    return IgnorePointer(
      child: Container(
        width: size,
        height: size,
        decoration: BoxDecoration(
          shape: BoxShape.circle,
          color: color.withValues(alpha: 0.42),
          boxShadow: [
            BoxShadow(
              color: color.withValues(alpha: 0.35),
              blurRadius: 70,
              spreadRadius: 10,
            ),
          ],
        ),
      ),
    );
  }
}
