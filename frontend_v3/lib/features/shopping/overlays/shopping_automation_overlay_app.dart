import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../../../app/theme/app_colors.dart';
import '../../../app/theme/app_spacing.dart';
import '../../../app/theme/app_text_styles.dart';
import '../../../shared/widgets/dialogue_bubble.dart';
import '../screens/purchase_history_loading_screen.dart';

const String shoppingAutomationOverlayChannelName =
    'com.ddalangoo.ddalangoo/shopping_automation_overlay';

class ShoppingAutomationOverlayApp extends StatelessWidget {
  const ShoppingAutomationOverlayApp({super.key});

  @override
  Widget build(BuildContext context) {
    return const MaterialApp(
      debugShowCheckedModeBanner: false,
      color: Colors.transparent,
      home: ShoppingAutomationOverlayContent(),
    );
  }
}

class ShoppingAutomationOverlayContent extends StatefulWidget {
  const ShoppingAutomationOverlayContent({super.key});

  @override
  State<ShoppingAutomationOverlayContent> createState() =>
      _ShoppingAutomationOverlayContentState();
}

class _ShoppingAutomationOverlayContentState
    extends State<ShoppingAutomationOverlayContent> {
  static const MethodChannel _channel = MethodChannel(
    shoppingAutomationOverlayChannelName,
  );

  _ShoppingAutomationOverlayState _overlayState =
      const _ShoppingAutomationOverlayState();

  @override
  void initState() {
    super.initState();
    _channel.setMethodCallHandler(_handleMethodCall);
  }

  @override
  void dispose() {
    _channel.setMethodCallHandler(null);
    super.dispose();
  }

  Future<void> _handleMethodCall(MethodCall call) async {
    if (call.method != 'update') {
      return;
    }

    final arguments = call.arguments;
    if (arguments is! Map) {
      return;
    }

    setState(() {
      _overlayState = _ShoppingAutomationOverlayState.fromMap(arguments);
    });
  }

  @override
  Widget build(BuildContext context) {
    final mediaQuery = MediaQuery.of(context);
    final horizontalPadding = mediaQuery.size.width < 380
        ? AppSpacing.md
        : AppSpacing.lg;
    final topBubbleHeight = mediaQuery.size.height < 720 ? 118.0 : 136.0;
    final characterHeight = mediaQuery.size.height < 720 ? 90.0 : 108.0;

    return Material(
      type: MaterialType.transparency,
      child: SafeArea(
        child: Padding(
          padding: EdgeInsets.symmetric(horizontal: horizontalPadding),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              DialogueBubble(
                text: _overlayState.dialogueText,
                cyclePages: true,
                minHeight: topBubbleHeight,
                style: AppTextStyles.title2.copyWith(
                  color: AppColors.textStrong,
                  height: 1.32,
                  fontWeight: FontWeight.w700,
                ),
                emphasizedStyle: AppTextStyles.title2.copyWith(
                  color: AppColors.primaryPinkDark,
                  height: 1.32,
                  fontWeight: FontWeight.w800,
                ),
              ),
              const SizedBox(height: AppSpacing.md),
              const Spacer(),
              Image.asset(
                'assets/images/character/full/ddalangoo_searching.png',
                height: characterHeight,
                fit: BoxFit.contain,
              ),
              const SizedBox(height: AppSpacing.sm),
              PurchaseHistoryProgressBanner(
                statusMessage: _overlayState.statusMessage,
                helperMessage: _overlayState.helperMessage,
                progressLabel: _overlayState.progressLabel,
                isLoading: true,
              ),
              SizedBox(height: mediaQuery.padding.bottom + AppSpacing.md),
            ],
          ),
        ),
      ),
    );
  }
}

class _ShoppingAutomationOverlayState {
  const _ShoppingAutomationOverlayState({
    this.platform,
    this.currentStep,
    this.statusMessage = '구매 이력을 불러오고 있어요.',
    this.progressLabel = '자동화 진행 중',
    this.accumulatedCount = 0,
  });

  final String? platform;
  final String? currentStep;
  final String statusMessage;
  final String progressLabel;
  final int accumulatedCount;

  String get dialogueText {
    final platformLabel = switch (platform) {
      'kurly' => '컬리',
      'coupang' => '쿠팡',
      _ => '쇼핑 앱',
    };
    return '$platformLabel에서 지난 구매 이력을\n불러오는 중이에요';
  }

  String? get helperMessage {
    if (accumulatedCount <= 0) {
      return _helperMessageForStep(currentStep);
    }
    return '지금까지 $accumulatedCount개 항목을 확인했어요.';
  }

  static _ShoppingAutomationOverlayState fromMap(Map<dynamic, dynamic> map) {
    return _ShoppingAutomationOverlayState(
      platform: map['platform']?.toString(),
      currentStep: map['currentStep']?.toString(),
      statusMessage:
          map['statusMessage']?.toString().trim().isNotEmpty == true
              ? map['statusMessage'].toString()
              : '구매 이력을 불러오고 있어요.',
      progressLabel:
          map['progressLabel']?.toString().trim().isNotEmpty == true
              ? map['progressLabel'].toString()
              : '자동화 진행 중',
      accumulatedCount: _parseCount(map['accumulatedCount']),
    );
  }

  static int _parseCount(Object? value) {
    if (value is int) {
      return value;
    }
    if (value is num) {
      return value.toInt();
    }
    return int.tryParse(value?.toString() ?? '') ?? 0;
  }

  static String? _helperMessageForStep(String? step) {
    return switch (step) {
      'open_my_kurly' => '컬리 앱을 열고 있어요.',
      'open_my_coupang' => '쿠팡 앱을 열고 있어요.',
      'open_order_history' => '주문 내역 화면으로 이동하고 있어요.',
      'dump_purchase_history' => '화면에 보이는 주문 정보를 읽고 있어요.',
      'extract_purchase_history' => '상품명과 가격을 정리하고 있어요.',
      'scroll_purchase_history' => '더 많은 주문 내역을 찾고 있어요.',
      'finish_purchase_history' => '구매 이력 저장을 마무리하고 있어요.',
      _ => null,
    };
  }
}
