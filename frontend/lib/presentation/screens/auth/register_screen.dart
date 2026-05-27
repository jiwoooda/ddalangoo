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

  /// 전화번호 유효성 검사 및 정규화.
  /// 입력: "01012345678" 또는 "010-1234-5678" 모두 허용.
  /// 반환: 정규화된 "010-1234-5678" 형태, 유효하지 않으면 null.
  String? _normalizePhone(String raw) {
    final digits = raw.replaceAll(RegExp(r'[^0-9]'), '');
    // 한국 휴대폰: 010/011/016/017/018/019 + 7~8자리
    final match = RegExp(r'^(01[016789])(\d{3,4})(\d{4})$').firstMatch(digits);
    if (match == null) return null;
    return '${match.group(1)}-${match.group(2)}-${match.group(3)}';
  }

  String? _validate() {
    final name = _nameController.text.trim();
    final phone = _phoneController.text.trim();

    if (name.isEmpty) return '이름을 입력해주세요';
    if (name.length < 2) return '이름은 2자 이상 입력해주세요';
    if (phone.isEmpty) return '전화번호를 입력해주세요';
    if (_normalizePhone(phone) == null) return '올바른 전화번호를 입력해주세요 (예: 010-1234-5678)';
    return null;
  }

  Future<void> _register() async {
    final error = _validate();
    if (error != null) {
      setState(() => _errorMessage = error);
      return;
    }

    setState(() {
      _isLoading = true;
      _errorMessage = null;
    });

    try {
      final user = await _userRepository.createUser(
        name: _nameController.text.trim(),
        phoneNumber: _normalizePhone(_phoneController.text.trim()),
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
        child: LayoutBuilder(
          builder: (context, constraints) {
            return Center(
              child: Padding(
                padding: const EdgeInsets.symmetric(horizontal: 28, vertical: 16),
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
                            const SizedBox(height: 8),
                            if (_errorMessage != null)
                              Text(
                                _errorMessage!,
                                style: const TextStyle(
                                  color: Colors.red,
                                  fontSize: 13,
                                ),
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
                                  color: Color(0xFFE8325A),
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
            );
          },
        ),
      ),
    );
  }
}
