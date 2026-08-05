import 'package:flutter/material.dart';

import '../../../app/theme/app_colors.dart';
import '../../../app/theme/app_radii.dart';
import '../../../app/theme/app_spacing.dart';
import '../../../app/theme/app_text_styles.dart';

class OnboardingPageCard extends StatelessWidget {
  const OnboardingPageCard({
    super.key,
    required this.title,
    required this.assetPath,
    this.bubbleText,
    this.trailingTags = const <String>[],
  });

  final String title;
  final String assetPath;
  final String? bubbleText;
  final List<String> trailingTags;

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        Expanded(
          child: Center(
            child: Container(
              width: double.infinity,
              padding: const EdgeInsets.symmetric(
                horizontal: AppSpacing.lg,
                vertical: AppSpacing.xl,
              ),
              decoration: BoxDecoration(
                color: AppColors.surface,
                borderRadius: BorderRadius.circular(AppRadii.xl),
                border: Border.all(color: AppColors.border),
                boxShadow: const [
                  BoxShadow(
                    color: AppColors.shadow,
                    blurRadius: 24,
                    offset: Offset(0, 12),
                  ),
                ],
              ),
              child: Column(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  if (bubbleText != null) ...[
                    _SpeechChip(label: bubbleText!),
                    const SizedBox(height: AppSpacing.xl),
                  ],
                  if (trailingTags.isNotEmpty) ...[
                    Wrap(
                      alignment: WrapAlignment.center,
                      spacing: AppSpacing.sm,
                      runSpacing: AppSpacing.sm,
                      children: [
                        for (final tag in trailingTags) _StatusTag(label: tag),
                      ],
                    ),
                    const SizedBox(height: AppSpacing.xl),
                  ],
                  Image.asset(assetPath, height: 240, fit: BoxFit.contain),
                  const SizedBox(height: AppSpacing.xl),
                  Text(
                    title,
                    textAlign: TextAlign.center,
                    style: AppTextStyles.title1.copyWith(height: 1.22),
                  ),
                ],
              ),
            ),
          ),
        ),
      ],
    );
  }
}

class _SpeechChip extends StatelessWidget {
  const _SpeechChip({required this.label});

  final String label;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(
        horizontal: AppSpacing.md,
        vertical: AppSpacing.sm,
      ),
      decoration: BoxDecoration(
        color: AppColors.background,
        borderRadius: BorderRadius.circular(AppRadii.pill),
        border: Border.all(color: AppColors.secondaryPink),
      ),
      child: Text(
        label,
        style: AppTextStyles.body1.copyWith(
          fontWeight: FontWeight.w700,
          color: AppColors.primaryPinkDark,
        ),
      ),
    );
  }
}

class _StatusTag extends StatelessWidget {
  const _StatusTag({required this.label});

  final String label;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(
        horizontal: AppSpacing.md,
        vertical: AppSpacing.sm,
      ),
      decoration: BoxDecoration(
        color: AppColors.background,
        borderRadius: BorderRadius.circular(AppRadii.md),
        border: Border.all(color: AppColors.border),
      ),
      child: Text(
        label,
        style: AppTextStyles.body2.copyWith(
          fontWeight: FontWeight.w700,
          color: AppColors.textPrimary,
        ),
      ),
    );
  }
}
