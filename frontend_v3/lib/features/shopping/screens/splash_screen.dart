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

  Future<void> _scheduleNavigation() async {
    await Future<void>.delayed(const Duration(seconds: 2));
    if (!mounted) return;
    Navigator.of(context).pushReplacementNamed(
      widget.useMockFlow ? AppRoutes.onboardingMock : AppRoutes.onboarding,
    );
  }

  @override
  void dispose() {
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
