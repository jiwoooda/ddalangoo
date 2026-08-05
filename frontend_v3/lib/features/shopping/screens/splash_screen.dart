import 'dart:async';

import 'package:flutter/material.dart';

import '../../../app/routes.dart';
import '../../../core/storage/local_storage.dart';
import '../../../app/theme/app_spacing.dart';
import '../../../shared/layout/layout_presets.dart';
import '../../../shared/layout/screen_frame.dart';
import '../widgets/splash_logo_block.dart';
import '../widgets/splash_message_block.dart';

class SplashScreen extends StatefulWidget {
  const SplashScreen({super.key});

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
    final isLoggedIn = await LocalStorage.isLoggedIn();
    if (!mounted) {
      return;
    }
    Navigator.of(
      context,
    ).pushReplacementNamed(isLoggedIn ? AppRoutes.home : AppRoutes.onboarding);
  }

  @override
  void dispose() {
    _fadeController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return ScreenFrame(
      preset: LayoutPreset.standard,
      alignment: Alignment.center,
      child: FadeTransition(
        opacity: _fadeAnimation,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: const [
            SplashLogoBlock(),
            SizedBox(height: AppSpacing.lg),
            SplashMessageBlock(),
          ],
        ),
      ),
    );
  }
}
