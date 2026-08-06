import 'package:flutter/material.dart';

import '../../../app/routes.dart';
import '../../../app/theme/app_colors.dart';
import '../../../app/theme/app_radii.dart';
import '../../../app/theme/app_spacing.dart';
import '../../../app/theme/app_text_styles.dart';
import '../../../core/storage/local_storage.dart';
import '../../../data/repositories/agent_repository.dart';
import '../../../shared/layout/layout_presets.dart';
import '../../../shared/layout/screen_frame.dart';
import '../../../shared/widgets/primary_button.dart';

class RegisterScreen extends StatefulWidget {
  const RegisterScreen({super.key});

  @override
  State<RegisterScreen> createState() => _RegisterScreenState();
}

class _RegisterScreenState extends State<RegisterScreen> {
  final TextEditingController _nameController = TextEditingController();
  final TextEditingController _phoneController = TextEditingController();
  final UserRepository _userRepository = UserRepository();

  final List<String> _ageGroups = ['50대', '60대', '70대', '80대 이상'];
  final List<String> _genders = ['여성', '남성'];

  String? _selectedAgeGroup;
  String? _selectedGender;
  bool _isLoading = false;
  String? _errorMessage;

  @override
  void dispose() {
    _nameController.dispose();
    _phoneController.dispose();
    super.dispose();
  }

  String? _normalizePhone(String raw) {
    final digits = raw.replaceAll(RegExp(r'[^0-9]'), '');
    final match = RegExp(r'^(01[016789])(\d{3,4})(\d{4})$').firstMatch(digits);
    if (match == null) {
      return null;
    }
    return '${match.group(1)}-${match.group(2)}-${match.group(3)}';
  }

  Future<void> _register() async {
    final name = _nameController.text.trim();
    final phone = _phoneController.text.trim();
    if (name.isEmpty) {
      setState(() => _errorMessage = '이름을 입력해주세요.');
      return;
    }
    if (phone.isEmpty) {
      setState(() => _errorMessage = '전화번호를 입력해주세요.');
      return;
    }

    final normalizedPhone = _normalizePhone(phone);
    if (normalizedPhone == null) {
      setState(() => _errorMessage = '올바른 전화번호 형식으로 입력해주세요.');
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
      if (!mounted) {
        return;
      }
      Navigator.of(
        context,
      ).pushNamedAndRemoveUntil(AppRoutes.home, (route) => false);
    } catch (error) {
      if (!mounted) {
        return;
      }
      setState(() {
        _errorMessage = error.toString().replaceFirst('Exception: ', '');
      });
    } finally {
      if (mounted) {
        setState(() => _isLoading = false);
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return ScreenFrame(
      preset: LayoutPreset.standard,
      alignment: Alignment.center,
      scrollable: true,
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 420),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Image.asset(
              'assets/images/character/full/ddalangoo_cheerful.png',
              height: 220,
              fit: BoxFit.contain,
            ),
            const SizedBox(height: AppSpacing.lg),
            Text('회원가입', style: AppTextStyles.title1),
            const SizedBox(height: AppSpacing.sm),
            Text(
              '처음 사용하신다면 간단한 정보만 입력해주세요.',
              textAlign: TextAlign.center,
              style: AppTextStyles.body2,
            ),
            const SizedBox(height: AppSpacing.xl),
            _AuthField(controller: _nameController, hintText: '이름'),
            const SizedBox(height: AppSpacing.md),
            _AuthField(
              controller: _phoneController,
              hintText: '전화번호',
              keyboardType: TextInputType.phone,
            ),
            const SizedBox(height: AppSpacing.md),
            _DropdownField(
              value: _selectedAgeGroup,
              hintText: '연령대 선택',
              items: _ageGroups,
              onChanged: (value) => setState(() => _selectedAgeGroup = value),
            ),
            const SizedBox(height: AppSpacing.md),
            _DropdownField(
              value: _selectedGender,
              hintText: '성별 선택',
              items: _genders,
              onChanged: (value) => setState(() => _selectedGender = value),
            ),
            if (_errorMessage != null) ...[
              const SizedBox(height: AppSpacing.md),
              Text(
                _errorMessage!,
                textAlign: TextAlign.center,
                style: AppTextStyles.body2.copyWith(
                  color: AppColors.primaryPinkDark,
                  fontWeight: FontWeight.w700,
                ),
              ),
            ],
            const SizedBox(height: AppSpacing.xl),
            PrimaryButton(
              label: _isLoading ? '가입 중...' : '회원가입',
              onPressed: _isLoading ? null : _register,
            ),
            const SizedBox(height: AppSpacing.md),
            TextButton(
              onPressed: _isLoading ? null : () => Navigator.of(context).pop(),
              child: Text(
                '이미 계정이 있어요',
                style: AppTextStyles.body2.copyWith(
                  color: AppColors.primaryPinkDark,
                  fontWeight: FontWeight.w800,
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _AuthField extends StatelessWidget {
  const _AuthField({
    required this.controller,
    required this.hintText,
    this.keyboardType,
  });

  final TextEditingController controller;
  final String hintText;
  final TextInputType? keyboardType;

  @override
  Widget build(BuildContext context) {
    return TextField(
      controller: controller,
      keyboardType: keyboardType,
      decoration: InputDecoration(
        hintText: hintText,
        filled: true,
        fillColor: AppColors.surface,
        border: OutlineInputBorder(
          borderRadius: BorderRadius.circular(AppRadii.lg),
          borderSide: const BorderSide(color: AppColors.border),
        ),
        enabledBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(AppRadii.lg),
          borderSide: const BorderSide(color: AppColors.border),
        ),
        focusedBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(AppRadii.lg),
          borderSide: const BorderSide(color: AppColors.primaryPink),
        ),
      ),
      style: AppTextStyles.body1.copyWith(color: AppColors.textStrong),
    );
  }
}

class _DropdownField extends StatelessWidget {
  const _DropdownField({
    required this.value,
    required this.hintText,
    required this.items,
    required this.onChanged,
  });

  final String? value;
  final String hintText;
  final List<String> items;
  final ValueChanged<String?> onChanged;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: AppSpacing.md),
      decoration: BoxDecoration(
        color: AppColors.surface,
        borderRadius: BorderRadius.circular(AppRadii.lg),
        border: Border.all(color: AppColors.border),
      ),
      child: DropdownButtonHideUnderline(
        child: DropdownButton<String>(
          value: value,
          isExpanded: true,
          hint: Text(hintText, style: AppTextStyles.body2),
          items: items
              .map(
                (item) => DropdownMenuItem<String>(
                  value: item,
                  child: Text(item, style: AppTextStyles.body1),
                ),
              )
              .toList(growable: false),
          onChanged: onChanged,
        ),
      ),
    );
  }
}
