import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import '../../../core/storage/local_storage.dart';
import '../../../data/repositories/agent_repository.dart';

class RegisterScreen extends StatefulWidget {
  const RegisterScreen({super.key});

  @override
  State<RegisterScreen> createState() => _RegisterScreenState();
}

class _RegisterScreenState extends State<RegisterScreen> {
  final _nameController = TextEditingController();
  final _phoneController = TextEditingController();
  String? _selectedAgeGroup;
  bool _isLoading = false;
  String? _errorMessage;

  final UserRepository _userRepository = UserRepository();

  final List<String> _ageGroups = ['50대', '60대', '70대', '80대 이상'];

  @override
  void dispose() {
    _nameController.dispose();
    _phoneController.dispose();
    super.dispose();
  }

  Future<void> _register() async {
    if (_nameController.text.isEmpty) {
      setState(() => _errorMessage = '이름을 입력해주세요');
      return;
    }

    setState(() {
      _isLoading = true;
      _errorMessage = null;
    });

    try {
      final user = await _userRepository.createUser(
        name: _nameController.text,
        phoneNumber: _phoneController.text.isEmpty
            ? null
            : _phoneController.text,
        ageGroup: _selectedAgeGroup,
      );

      await LocalStorage.saveUserId(user.userId);

      if (!mounted) return;
      context.go('/home');
    } catch (e) {
      setState(() => _errorMessage = '회원가입에 실패했습니다. 다시 시도해주세요');
    } finally {
      setState(() => _isLoading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFFFDF0F3),
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(32.0),
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              Image.asset(
                'assets/images/ddalangoo_logo_image.png',
                height: 84,
                fit: BoxFit.contain,
              ),
              const SizedBox(height: 16),
              const Text(
                '딸랑구',
                style: TextStyle(
                  fontSize: 32,
                  fontWeight: FontWeight.bold,
                  color: Color(0xFFE8325A),
                ),
              ),
              const SizedBox(height: 8),
              const Text(
                '처음 오셨군요! 간단히 가입해주세요',
                style: TextStyle(fontSize: 14, color: Color(0xFF888888)),
              ),
              const SizedBox(height: 40),

              // 이름 입력
              TextField(
                controller: _nameController,
                decoration: InputDecoration(
                  hintText: '이름 (필수)',
                  filled: true,
                  fillColor: Colors.white,
                  border: OutlineInputBorder(
                    borderRadius: BorderRadius.circular(12),
                    borderSide: BorderSide.none,
                  ),
                ),
              ),
              const SizedBox(height: 12),

              // 전화번호 입력
              TextField(
                controller: _phoneController,
                keyboardType: TextInputType.phone,
                decoration: InputDecoration(
                  hintText: '전화번호 (선택)',
                  filled: true,
                  fillColor: Colors.white,
                  border: OutlineInputBorder(
                    borderRadius: BorderRadius.circular(12),
                    borderSide: BorderSide.none,
                  ),
                ),
              ),
              const SizedBox(height: 12),

              // 연령대 선택
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 16),
                decoration: BoxDecoration(
                  color: Colors.white,
                  borderRadius: BorderRadius.circular(12),
                ),
                child: DropdownButtonHideUnderline(
                  child: DropdownButton<String>(
                    isExpanded: true,
                    hint: const Text('연령대 선택 (선택)'),
                    value: _selectedAgeGroup,
                    items: _ageGroups
                        .map(
                          (age) =>
                              DropdownMenuItem(value: age, child: Text(age)),
                        )
                        .toList(),
                    onChanged: (value) {
                      setState(() => _selectedAgeGroup = value);
                    },
                  ),
                ),
              ),
              const SizedBox(height: 8),

              // 에러 메시지
              if (_errorMessage != null)
                Text(
                  _errorMessage!,
                  style: const TextStyle(color: Colors.red, fontSize: 13),
                ),
              const SizedBox(height: 24),

              // 회원가입 버튼
              SizedBox(
                width: double.infinity,
                height: 52,
                child: ElevatedButton(
                  onPressed: _isLoading ? null : _register,
                  style: ElevatedButton.styleFrom(
                    backgroundColor: const Color(0xFFE8325A),
                    shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(12),
                    ),
                  ),
                  child: _isLoading
                      ? const CircularProgressIndicator(color: Colors.white)
                      : const Text(
                          '시작하기',
                          style: TextStyle(
                            fontSize: 16,
                            color: Colors.white,
                            fontWeight: FontWeight.bold,
                          ),
                        ),
                ),
              ),
              const SizedBox(height: 16),

              // 로그인으로 이동
              TextButton(
                onPressed: () => context.go('/login'),
                child: const Text(
                  '이미 계정이 있으신가요? 로그인',
                  style: TextStyle(color: Color(0xFFE8325A)),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
