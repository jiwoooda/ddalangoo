import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import '../../../core/storage/local_storage.dart';

class SplashScreen extends StatefulWidget {
  const SplashScreen({super.key});

  @override
  State<SplashScreen> createState() => _SplashScreenState();
}

class _SplashScreenState extends State<SplashScreen> {
  @override
  void initState() {
    super.initState();
    _navigate();
  }

  Future<void> _navigate() async {
    // 2초 딸랑구 로고 보여주기
    await Future.delayed(const Duration(seconds: 2));

    if (!mounted) return;

    // 로그인 여부 확인 후 화면 이동
    final isLoggedIn = await LocalStorage.isLoggedIn();
    if (!mounted) return;

    if (isLoggedIn) {
      context.go('/home');
    } else {
      context.go('/login');
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFFFDF0F3),
      body: Center(
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            // 딸랑구 캐릭터 이모지
            const Text('🧒', style: TextStyle(fontSize: 80)),
            const SizedBox(height: 24),
            // 딸랑구 로고 텍스트
            const Text(
              '딸랑구',
              style: TextStyle(
                fontSize: 36,
                fontWeight: FontWeight.bold,
                color: Color(0xFFE8325A),
              ),
            ),
            const SizedBox(height: 12),
            const Text(
              '부모님께서 더 쉽게 온라인 쇼핑을 할 수 있도록\n도와드리는 AI 어시스턴트입니다',
              textAlign: TextAlign.center,
              style: TextStyle(fontSize: 14, color: Color(0xFF888888)),
            ),
            const SizedBox(height: 40),
            // 로딩 인디케이터
            const CircularProgressIndicator(color: Color(0xFFE8325A)),
          ],
        ),
      ),
    );
  }
}
