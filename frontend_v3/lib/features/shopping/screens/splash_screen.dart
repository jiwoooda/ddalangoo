import 'dart:async';

import 'package:flutter/material.dart';

import '../../../app/routes.dart';
import '../../../app/theme/app_spacing.dart';
import '../../../shared/layout/layout_presets.dart';
import '../../../shared/layout/app_responsive.dart';
import '../../../shared/layout/screen_frame.dart';
import '../widgets/splash_logo_block.dart';
import '../widgets/splash_message_block.dart';

class SplashScreen extends StatefulWidget {
  const SplashScreen({super.key, this.useMockFlow = false});

  final bool useMockFlow;

  @override
  State<SplashScreen> createState() => _SplashScreenState();
}

class _SplashScreenState extends State<SplashScreen>
    with SingleTickerProviderStateMixin {
  Timer? _navigationTimer;

  late final AnimationController _fadeController = AnimationController(
    vsync: this,
    duration: const Duration(milliseconds: 700),
  )..forward();

  late final Animation<double> _fadeAnimation = CurvedAnimation(
    parent: _fadeController,
    curve: Curves.easeOut,
  );

  @override
  void initState() {
    super.initState();
    _scheduleNavigation();
  }

  void _scheduleNavigation() {
    // 테스트/빠른 화면 전환 중 SplashScreen이 dispose되면 예약된 이동도
    // 함께 취소되어야 한다. Future.delayed는 취소할 수 없어서 Timer로 둔다.
    _navigationTimer?.cancel();
    _navigationTimer = Timer(const Duration(seconds: 2), () {
      if (!mounted) return;
      Navigator.of(context).pushReplacementNamed(
        widget.useMockFlow ? AppRoutes.onboardingMock : AppRoutes.onboarding,
      );
    });
  }

  @override
  void dispose() {
    _navigationTimer?.cancel();
    _fadeController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final responsive = context.responsive;

    return ScreenFrame(
      preset: LayoutPreset.standard,
      alignment: Alignment.center,
      child: FadeTransition(
        opacity: _fadeAnimation,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const SplashLogoBlock(),
            SizedBox(
              height: responsive.bound(
                responsive.heightScaled(
                  AppSpacing.lg,
                  minFactor: 0.72,
                  maxFactor: 1.0,
                ),
                min: AppSpacing.sm,
                max: AppSpacing.lg,
              ),
            ),
            const SplashMessageBlock(),
          ],
        ),
      ),
    );
  }
}
