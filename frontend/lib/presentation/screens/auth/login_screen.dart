import 'package:ddalangoo/data/repositories/agent_repository.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:go_router/go_router.dart';

import '../../../core/storage/local_storage.dart';

class LoginScreen extends StatefulWidget {
  const LoginScreen({super.key});

  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  static const MethodChannel _accessibilityAutomationChannel = MethodChannel(
    'ddalangoo/accessibility_automation',
  );
  final TextEditingController _nameController = TextEditingController();
  final TextEditingController _phoneController = TextEditingController();
  final UserRepository _userRepository = UserRepository();
  bool _isLoading = false;
  String? _errorMessage;

  @override
  void dispose() {
    _nameController.dispose();
    _phoneController.dispose();
    super.dispose();
  }

  /// 전화번호 정규화. "01012345678" → "010-1234-5678"
  /// 유효하지 않으면 null 반환.
  String? _normalizePhone(String raw) {
    final digits = raw.replaceAll(RegExp(r'[^0-9]'), '');
    final match = RegExp(r'^(01[016789])(\d{3,4})(\d{4})$').firstMatch(digits);
    if (match == null) return null;
    return '${match.group(1)}-${match.group(2)}-${match.group(3)}';
  }

  Future<void> _handleLogin() async {
    final name = _nameController.text.trim();
    final phone = _phoneController.text.trim();

    if (name.isEmpty) {
      setState(() => _errorMessage = '이름을 입력해주세요');
      return;
    }
    if (phone.isEmpty) {
      setState(() => _errorMessage = '전화번호를 입력해주세요');
      return;
    }
    final normalized = _normalizePhone(phone);
    if (normalized == null) {
      setState(() => _errorMessage = '올바른 전화번호를 입력해주세요 (예: 010-1234-5678)');
      return;
    }

    setState(() {
      _isLoading = true;
      _errorMessage = null;
    });

    try {
      final user = await _userRepository.login(
        name: name,
        phoneNumber: normalized,
      );

      await LocalStorage.saveUserId(user.userId);

      if (!mounted) return;
      context.go('/home');
    } catch (e) {
      setState(
        () => _errorMessage = e.toString().replaceFirst('Exception: ', ''),
      );
      debugPrint('❌ [Login Error] $e');
    } finally {
      if (mounted) setState(() => _isLoading = false);
    }
  }

  Future<void> _setCoupangPurchaseHistoryDumpTask() async {
    try {
      // 백엔드 로그인 없이도 실기기에서 쿠팡 구매이력 UI Tree 후보 로그를 확인하기 위한 임시 task 주입 버튼이다.
      await _accessibilityAutomationChannel.invokeMethod(
        'setTestAutomationTask',
        {
          'taskId': 'coupang-history-dump-1',
          'taskType': 'purchase_history_validation',
          'targetProductName': '',
          'quantity': 1,
          'platform': 'coupang',
          'packageName': 'com.coupang.mobile',
          'currentStep': 'dump_purchase_history',
        },
      );
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('쿠팡 구매이력 dump task를 넣었어요.')),
      );
    } catch (error) {
      debugPrint('⚠️ [A11y Login Test Task Error] $error');
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('task 주입 실패: $error')),
      );
    }
  }

  Future<void> _setKurlyPurchaseHistoryDumpTask() async {
    try {
      // 백엔드 로그인 없이도 실기기에서 마켓컬리 구매이력 UI Tree 후보 로그를 확인하기 위한 임시 task 주입 버튼이다.
      await _accessibilityAutomationChannel.invokeMethod(
        'setTestAutomationTask',
        {
          'taskId': 'kurly-history-dump-1',
          'taskType': 'purchase_history_validation',
          'targetProductName': '',
          'quantity': 1,
          'platform': 'kurly',
          'packageName': 'com.dbs.kurly.m2',
          'currentStep': 'dump_purchase_history',
        },
      );
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('마켓컬리 구매이력 dump task를 넣었어요.')),
      );
    } catch (error) {
      debugPrint('⚠️ [A11y Login Kurly Test Task Error] $error');
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('task 주입 실패: $error')),
      );
    }
  }

  Future<void> _clearAccessibilityAutomationTask() async {
    try {
      // 테스트 중 자동화 task를 비워서 클릭/스크롤 실행을 멈춘다.
      await _accessibilityAutomationChannel.invokeMethod('clearAutomationTask');
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Accessibility task를 비웠어요.')),
      );
    } catch (error) {
      debugPrint('⚠️ [A11y Login Clear Task Error] $error');
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('task clear 실패: $error')),
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFFFDF0F3),
      body: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(32),
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 420),
              child: Column(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  Image.asset(
                    'assets/images/ddalangoo_logo_image.png',
                    height: 250,
                    fit: BoxFit.contain,
                  ),
                  const SizedBox(height: 18),
                  Image.asset(
                    'assets/images/ddalangoo_logo_text.png',
                    height: 80,
                    fit: BoxFit.contain,
                  ),
                  const SizedBox(height: 12),
                  const Text(
                    '딸랑구와 전화 한 통으로 더 쉽게 쇼핑해보세요!',
                    textAlign: TextAlign.center,
                    style: TextStyle(fontSize: 15, color: Color(0xFF777777)),
                  ),
                  const SizedBox(height: 32),
                  Container(
                    padding: const EdgeInsets.all(22),
                    decoration: BoxDecoration(
                      color: Colors.white.withValues(alpha: 0.88),
                      borderRadius: BorderRadius.circular(24),
                      boxShadow: [
                        BoxShadow(
                          color: Colors.black.withValues(alpha: 0.05),
                          blurRadius: 18,
                          offset: const Offset(0, 8),
                        ),
                      ],
                    ),
                    child: Column(
                      children: [
                        TextField(
                          controller: _nameController,
                          decoration: InputDecoration(
                            hintText: '이름',
                            filled: true,
                            fillColor: const Color(0xFFF9F4F6),
                            border: OutlineInputBorder(
                              borderRadius: BorderRadius.circular(16),
                              borderSide: BorderSide.none,
                            ),
                          ),
                        ),
                        const SizedBox(height: 14),
                        TextField(
                          controller: _phoneController,
                          keyboardType: TextInputType.phone,
                          decoration: InputDecoration(
                            hintText: '전화번호',
                            filled: true,
                            fillColor: const Color(0xFFF9F4F6),
                            border: OutlineInputBorder(
                              borderRadius: BorderRadius.circular(16),
                              borderSide: BorderSide.none,
                            ),
                          ),
                        ),
                        if (_errorMessage != null) ...[
                          const SizedBox(height: 10),
                          Text(
                            _errorMessage!,
                            style: const TextStyle(
                              color: Colors.red,
                              fontSize: 13,
                            ),
                          ),
                        ],
                        const SizedBox(height: 22),
                        SizedBox(
                          width: double.infinity,
                          height: 54,
                          child: ElevatedButton(
                            onPressed: _isLoading ? null : _handleLogin,
                            style: ElevatedButton.styleFrom(
                              backgroundColor: const Color(0xFFE8325A),
                              foregroundColor: Colors.white,
                              shape: RoundedRectangleBorder(
                                borderRadius: BorderRadius.circular(16),
                              ),
                            ),
                            child: _isLoading
                                ? const SizedBox(
                                    width: 22,
                                    height: 22,
                                    child: CircularProgressIndicator(
                                      strokeWidth: 2.4,
                                      color: Colors.white,
                                    ),
                                  )
                                : const Text('로그인'),
                          ),
                        ),
                        const SizedBox(height: 14),
                        TextButton(
                          onPressed: () => context.go('/register'),
                          child: Text(
                            '처음이신가요? 회원가입',
                            style: Theme.of(context).textTheme.titleSmall
                                ?.copyWith(
                              color: const Color(0xFFE8325A),
                              fontWeight: FontWeight.w700,
                            ),
                          ),
                        ),
                        const SizedBox(height: 8),
                        OutlinedButton.icon(
                          onPressed: _setCoupangPurchaseHistoryDumpTask,
                          icon: const Icon(Icons.bug_report_outlined, size: 20),
                          label: const Text('쿠팡 구매이력 dump task 넣기'),
                        ),
                        const SizedBox(height: 8),
                        OutlinedButton.icon(
                          onPressed: _setKurlyPurchaseHistoryDumpTask,
                          icon: const Icon(Icons.bug_report_outlined, size: 20),
                          label: const Text('마켓컬리 구매이력 dump task 넣기'),
                        ),
                        const SizedBox(height: 8),
                        TextButton.icon(
                          onPressed: _clearAccessibilityAutomationTask,
                          icon: const Icon(Icons.clear, size: 20),
                          label: const Text('Accessibility task 비우기'),
                        ),
                      ],
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
}
