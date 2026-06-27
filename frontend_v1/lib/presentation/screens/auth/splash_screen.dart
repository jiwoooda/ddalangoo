import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import '../../../core/storage/local_storage.dart';
import '../../../data/repositories/agent_repository.dart';

class SplashScreen extends StatefulWidget {
  const SplashScreen({super.key});

  @override
  State<SplashScreen> createState() => _SplashScreenState();
}

class _SplashScreenState extends State<SplashScreen> {
  final UserRepository _userRepository = UserRepository();

  @override
  void initState() {
    super.initState();
    _navigate();
  }

  Future<void> _navigate() async {
    // 2초 딸랑구 로고 보여주기
    await Future.delayed(const Duration(seconds: 3));

    if (!mounted) return;

    final userId = await LocalStorage.getUserId();
    if (!mounted) return;

    if (userId == null) {
      context.go('/login');
      return;
    }

    try {
      await _userRepository.getUser(userId);
    } catch (_) {
      await LocalStorage.clearUserId();
      if (!mounted) return;
      context.go('/login');
      return;
    }

    if (!mounted) return;
    if (userId > 0) {
      context.go('/home');
    } else {
      context.go('/login');
    }
  }

  @override
  Widget build(BuildContext context) {
    final size = MediaQuery.sizeOf(context);
    final frameHeight = size.height * 0.34;
    final textLogoHeight = size.height * 0.12;

    return Scaffold(
      backgroundColor: const Color(0xFFFDF0F3),
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 20),
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.center,
                children: [
                  Center(
                    child: Image.asset(
                      'assets/images/ddalangoo_frame2.png',
                      height: frameHeight.clamp(180.0, 320.0),
                      fit: BoxFit.contain,
                    ),
                  ),
                  const SizedBox(height: 4),
                  Center(
                    child: Image.asset(
                      'assets/images/ddalangoo_logo_text.png',
                      height: textLogoHeight.clamp(44.0, 88.0),
                      fit: BoxFit.contain,
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 12),
              const Text(
                '부모님께서 더 쉽게 온라인 쇼핑을 할 수 있도록\n도와드리는 AI 어시스턴트입니다',
                textAlign: TextAlign.center,
                style: TextStyle(fontSize: 14, color: Color(0xFF888888)),
              ),
              const SizedBox(height: 28),
              const CircularProgressIndicator(color: Color(0xFFE8325A)),
            ],
          ),
        ),
      ),
    );
  }
}
