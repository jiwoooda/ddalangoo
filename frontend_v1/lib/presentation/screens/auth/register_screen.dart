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
  String? _selectedGender;
  bool _isLoading = false;
  String? _errorMessage;

  final UserRepository _userRepository = UserRepository();

  final List<String> _ageGroups = ['50대', '60대', '70대', '80대 이상'];
  final List<String> _genders = ['여성', '남성'];

  String? _normalizePhone(String raw) {
    final digits = raw.replaceAll(RegExp(r'[^0-9]'), '');
    final match = RegExp(r'^(01[016789])(\d{3,4})(\d{4})$').firstMatch(digits);
    if (match == null) return null;
    return '${match.group(1)}-${match.group(2)}-${match.group(3)}';
  }

  @override
  void dispose() {
    _nameController.dispose();
    _phoneController.dispose();
    super.dispose();
  }

  Future<void> _register() async {
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

    final normalizedPhone = _normalizePhone(phone);
    if (normalizedPhone == null) {
      setState(() => _errorMessage = '올바른 전화번호를 입력해주세요 (예: 010-1234-5678)');
      return;
    }

    setState(() {
      _isLoading = true;
      _errorMessage = null;
    });

    try {
      final user = await _userRepository.createUser(
        name: name,
        phoneNumber: normalizedPhone,
        ageGroup: _selectedAgeGroup,
        gender: _selectedGender,
      );

      await LocalStorage.saveUserId(user.userId);

      if (!mounted) return;
      context.go('/home');
    } catch (e) {
      setState(() => _errorMessage = e.toString().replaceFirst('Exception: ', ''));
    } finally {
      if (mounted) {
        setState(() => _isLoading = false);
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final viewInsets = MediaQuery.viewInsetsOf(context);

    return Scaffold(
      backgroundColor: const Color(0xFFFDF0F3),
      body: SafeArea(
        child: LayoutBuilder(
          builder: (context, constraints) {
            return AnimatedPadding(
              duration: const Duration(milliseconds: 180),
              curve: Curves.easeOut,
              padding: EdgeInsets.only(bottom: viewInsets.bottom),
              child: Center(
                child: SingleChildScrollView(
                  padding: const EdgeInsets.symmetric(horizontal: 28, vertical: 16),
                  child: ConstrainedBox(
                    constraints: BoxConstraints(
                      maxWidth: 420,
                      minHeight: constraints.maxHeight - viewInsets.bottom - 32,
                    ),
                    child: Column(
                      mainAxisAlignment: MainAxisAlignment.center,
                      children: [
                        Image.asset(
                          'assets/images/ddalangoo_logo_image.png',
                          height: 220,
                          fit: BoxFit.contain,
                        ),
                        const SizedBox(height: 14),
                        Image.asset(
                          'assets/images/ddalangoo_logo_text.png',
                          height: 72,
                          fit: BoxFit.contain,
                        ),
                        const SizedBox(height: 10),
                        const Text(
                          '처음 오셨군요! 회원가입을 위한 정보를 입력해주세요',
                          textAlign: TextAlign.center,
                          style: TextStyle(fontSize: 15, color: Color(0xFF777777)),
                        ),
                        const SizedBox(height: 20),
                        Container(
                          padding: const EdgeInsets.all(18),
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
                                  hintText: '이름 (필수)',
                                  filled: true,
                                  fillColor: const Color(0xFFF9F4F6),
                                  border: OutlineInputBorder(
                                    borderRadius: BorderRadius.circular(16),
                                    borderSide: BorderSide.none,
                                  ),
                                  isDense: true,
                                ),
                              ),
                              const SizedBox(height: 12),
                              TextField(
                                controller: _phoneController,
                                keyboardType: TextInputType.phone,
                                decoration: InputDecoration(
                                  hintText: '전화번호 (필수)',
                                  filled: true,
                                  fillColor: const Color(0xFFF9F4F6),
                                  border: OutlineInputBorder(
                                    borderRadius: BorderRadius.circular(16),
                                    borderSide: BorderSide.none,
                                  ),
                                  isDense: true,
                                ),
                              ),
                              const SizedBox(height: 12),
                              Container(
                                padding: const EdgeInsets.symmetric(horizontal: 16),
                                decoration: BoxDecoration(
                                  color: const Color(0xFFF9F4F6),
                                  borderRadius: BorderRadius.circular(16),
                                ),
                                child: DropdownButtonHideUnderline(
                                  child: DropdownButton<String>(
                                    isExpanded: true,
                                    hint: const Text('연령대 선택 (선택)'),
                                    value: _selectedAgeGroup,
                                    items: _ageGroups
                                        .map(
                                          (age) => DropdownMenuItem(
                                            value: age,
                                            child: Text(age),
                                          ),
                                        )
                                        .toList(),
                                    onChanged: (value) {
                                      setState(() => _selectedAgeGroup = value);
                                    },
                                  ),
                                ),
                              ),
                              const SizedBox(height: 12),
                              Container(
                                padding: const EdgeInsets.symmetric(horizontal: 16),
                                decoration: BoxDecoration(
                                  color: const Color(0xFFF9F4F6),
                                  borderRadius: BorderRadius.circular(16),
                                ),
                                child: DropdownButtonHideUnderline(
                                  child: DropdownButton<String>(
                                    isExpanded: true,
                                    hint: const Text('성별 선택 (선택)'),
                                    value: _selectedGender,
                                    items: _genders
                                        .map(
                                          (gender) => DropdownMenuItem(
                                            value: gender,
                                            child: Text(gender),
                                          ),
                                        )
                                        .toList(),
                                    onChanged: (value) {
                                      setState(() => _selectedGender = value);
                                    },
                                  ),
                                ),
                              ),
                              const SizedBox(height: 8),
                              if (_errorMessage != null)
                                Text(
                                  _errorMessage!,
                                  style: const TextStyle(
                                    color: Colors.red,
                                    fontSize: 13,
                                  ),
                                  textAlign: TextAlign.center,
                                ),
                              const SizedBox(height: 18),
                              SizedBox(
                                width: double.infinity,
                                height: 52,
                                child: ElevatedButton(
                                  onPressed: _isLoading ? null : _register,
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
                                      : const Text('시작하기'),
                                ),
                              ),
                              const SizedBox(height: 10),
                              TextButton(
                                onPressed: () => context.go('/login'),
                                child: Text(
                                  '이미 계정이 있으신가요? 로그인',
                                  style: Theme.of(context).textTheme.titleSmall
                                      ?.copyWith(
                                    color: const Color(0xFFE8325A),
                                    fontWeight: FontWeight.w700,
                                  ),
                                ),
                              ),
                            ],
                          ),
                        ),
                      ],
                    ),
                  ),
                ),
              ),
            );
          },
        ),
      ),
    );
  }
}
