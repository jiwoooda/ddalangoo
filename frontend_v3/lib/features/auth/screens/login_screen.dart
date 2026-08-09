import 'package:flutter/material.dart';

import '../../../app/routes.dart';
import '../../../app/theme/app_colors.dart';
import '../../../app/theme/app_radii.dart';
import '../../../app/theme/app_spacing.dart';
import '../../../app/theme/app_text_styles.dart';
import '../../../core/storage/local_storage.dart';
import '../../../data/repositories/agent_repository.dart';
import '../../../shared/layout/app_responsive.dart';
import '../../../shared/layout/layout_presets.dart';
import '../../../shared/layout/screen_frame.dart';
import '../../../shared/widgets/primary_button.dart';
import '../../../shared/widgets/secondary_button.dart';

class LoginScreen extends StatefulWidget {
  const LoginScreen({super.key});

  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
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

  String? _normalizePhone(String raw) {
    final digits = raw.replaceAll(RegExp(r'[^0-9]'), '');
    final match = RegExp(r'^(01[016789])(\d{3,4})(\d{4})$').firstMatch(digits);
    if (match == null) {
      return null;
    }
    return '${match.group(1)}-${match.group(2)}-${match.group(3)}';
  }

  Future<void> _handleLogin() async {
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
      final user = await _userRepository.login(
        name: name,
        phoneNumber: normalizedPhone,
      );
      await LocalStorage.saveUserId(user.userId);
      await LocalStorage.saveUserName(user.name);
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
    final responsive = context.responsive;

    return ScreenFrame(
      preset: LayoutPreset.standard,
      alignment: Alignment.topCenter,
      scrollable: false,
      child: ConstrainedBox(
        constraints: BoxConstraints(
          maxWidth: responsive.isExpandedWidth ? 440 : 420,
        ),
        child: LayoutBuilder(
          builder: (context, constraints) {
            final compactHeight =
                constraints.maxHeight < 760 || responsive.usesCondensedLayout;
            final imageHeight = responsive.bound(
              responsive.heightScaled(
                compactHeight ? 190 : 220,
                minFactor: 0.8,
                maxFactor: 1.0,
              ),
              min: 170,
              max: 220,
            );
            final headerTopSpacing = responsive.bound(
              responsive.heightScaled(
                AppSpacing.lg,
                minFactor: 0.7,
                maxFactor: 1.0,
              ),
              min: AppSpacing.md,
              max: AppSpacing.xl,
            );
            final sectionSpacing = responsive.bound(
              responsive.heightScaled(
                AppSpacing.xl,
                minFactor: 0.72,
                maxFactor: 1.0,
              ),
              min: AppSpacing.lg,
              max: AppSpacing.xl,
            );

            return SingleChildScrollView(
              keyboardDismissBehavior: ScrollViewKeyboardDismissBehavior.onDrag,
              child: ConstrainedBox(
                constraints: BoxConstraints(minHeight: constraints.maxHeight),
                child: IntrinsicHeight(
                  child: Column(
                    mainAxisAlignment: MainAxisAlignment.spaceBetween,
                    children: [
                      Padding(
                        padding: EdgeInsets.only(top: headerTopSpacing),
                        child: Column(
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            Image.asset(
                              'assets/images/character/top/ddalangoo_greeting_top.png',
                              height: imageHeight,
                              fit: BoxFit.contain,
                            ),
                            SizedBox(height: headerTopSpacing),
                            Text(
                              '다시 오신 걸 환영해요!',
                              style: AppTextStyles.title1.copyWith(
                                fontSize: responsive.bound(
                                  responsive.font(
                                    28,
                                    minFactor: 0.94,
                                    maxFactor: 1.0,
                                  ),
                                  min: 25,
                                  max: 28,
                                ),
                              ),
                            ),
                            SizedBox(
                              height: responsive.bound(
                                responsive.heightScaled(
                                  AppSpacing.sm,
                                  minFactor: 0.72,
                                  maxFactor: 1.0,
                                ),
                                min: AppSpacing.xs,
                                max: AppSpacing.sm,
                              ),
                            ),
                            Text(
                              '이름과 전화번호로 로그인할 수 있어요.',
                              textAlign: TextAlign.center,
                              style: AppTextStyles.body2.copyWith(
                                fontSize: responsive.font(
                                  16,
                                  minFactor: 0.94,
                                  maxFactor: 1.0,
                                ),
                              ),
                            ),
                            SizedBox(height: sectionSpacing),
                            _AuthField(
                              controller: _nameController,
                              hintText: '이름',
                              textInputAction: TextInputAction.next,
                            ),
                            const SizedBox(height: AppSpacing.md),
                            _AuthField(
                              controller: _phoneController,
                              hintText: '전화번호',
                              keyboardType: TextInputType.phone,
                              textInputAction: TextInputAction.done,
                              onSubmitted: (_) => _handleLogin(),
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
                              label: _isLoading ? '로그인 중...' : '로그인',
                              onPressed: _isLoading ? null : _handleLogin,
                            ),
                          ],
                        ),
                      ),
                      Padding(
                        padding: EdgeInsets.only(
                          top: responsive.bound(
                            responsive.heightScaled(
                              AppSpacing.xxl,
                              minFactor: 0.6,
                              maxFactor: 1.0,
                            ),
                            min: AppSpacing.lg,
                            max: AppSpacing.xxl,
                          ),
                        ),
                        child: Column(
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            Text(
                              '처음이시라면?',
                              style: AppTextStyles.body2.copyWith(
                                color: AppColors.textMuted,
                                fontWeight: FontWeight.w600,
                                fontSize: responsive.font(
                                  16,
                                  minFactor: 0.94,
                                  maxFactor: 1.0,
                                ),
                              ),
                            ),
                            const SizedBox(height: AppSpacing.sm),
                            SecondaryButton(
                              label: '회원가입',
                              onPressed: _isLoading
                                  ? null
                                  : () => Navigator.of(
                                      context,
                                    ).pushNamed(AppRoutes.register),
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

class _AuthField extends StatelessWidget {
  const _AuthField({
    required this.controller,
    required this.hintText,
    this.keyboardType,
    this.textInputAction,
    this.onSubmitted,
  });

  final TextEditingController controller;
  final String hintText;
  final TextInputType? keyboardType;
  final TextInputAction? textInputAction;
  final ValueChanged<String>? onSubmitted;

  @override
  Widget build(BuildContext context) {
    return TextField(
      controller: controller,
      keyboardType: keyboardType,
      textInputAction: textInputAction,
      onSubmitted: onSubmitted,
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
