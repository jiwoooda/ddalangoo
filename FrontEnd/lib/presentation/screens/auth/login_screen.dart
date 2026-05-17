import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:ddalangoo/core/services/api_test_service.dart';

class LoginScreen extends StatefulWidget {
  const LoginScreen({super.key});

  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  final TextEditingController _usernameController = TextEditingController();
  final TextEditingController _passwordController = TextEditingController();
  final ApiTestService _testService = ApiTestService();
  bool _isLoading = false;

  @override
  void dispose() {
    _usernameController.dispose();
    _passwordController.dispose();
    super.dispose();
  }

  Future<void> _handleLogin() async {
    setState(() => _isLoading = true);

    try {
      // 가상 로그인 반영 (userId: 1)
      bool success = await _testService.performMockLogin();

      if (success && mounted) {
        // 로그인 성공 시점에 쇼핑 API 연결 확인
        await _testService.sendShoppingRequest();
        if (!mounted) return;

        // 메인 화면으로 이동
        context.go('/home');
      }
    } catch (e) {
      debugPrint('로그인 처리 중 오류 발생: $e');
    } finally {
      if (mounted) setState(() => _isLoading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        // 상단 중앙에 텍스트 로고 배치
        title: Image.asset(
          'assets/images/ddalangoo_text_icon.png',
          height: 32, // 화면을 너무 많이 차지하지 않도록 적절한 높이 설정
          fit: BoxFit.contain,
        ),
        centerTitle: true,
        elevation: 0,
        backgroundColor: Colors.transparent,
      ),
      body: Padding(
        padding: const EdgeInsets.all(20.0),
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            TextField(
              controller: _usernameController,
              decoration: const InputDecoration(labelText: '이름'),
            ),
            TextField(
              controller: _passwordController,
              decoration: const InputDecoration(labelText: '전화번호'),
              obscureText: true,
            ),
            const SizedBox(height: 30),
            _isLoading
                ? const CircularProgressIndicator()
                : ElevatedButton(
                    onPressed: _handleLogin,
                    child: const Text('로그인'),
                  ),
          ],
        ),
      ),
    );
  }
}
