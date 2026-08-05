import 'package:flutter/material.dart';

import '../../app/theme/app_colors.dart';
import '../../app/theme/app_radii.dart';
import '../../app/theme/app_spacing.dart';
import '../../app/theme/app_text_styles.dart';

enum EndConversationButtonVariant { light, dark }

class EndConversationButton extends StatelessWidget {
  const EndConversationButton({
    super.key,
    required this.onPressed,
    this.label = '대화 종료',
    this.variant = EndConversationButtonVariant.light,
  });

  final VoidCallback onPressed;
  final String label;
  final EndConversationButtonVariant variant;

  @override
  Widget build(BuildContext context) {
    final isDark = variant == EndConversationButtonVariant.dark;
    final backgroundColor = isDark ? AppColors.textStrong : Colors.white;
    final borderColor = isDark ? AppColors.textStrong : AppColors.border;
    final textColor = isDark
        ? AppColors.primaryPinkDark
        : AppColors.textPrimary;

    return Semantics(
      button: true,
      label: label,
      child: OutlinedButton(
        onPressed: onPressed,
        style: OutlinedButton.styleFrom(
          backgroundColor: backgroundColor,
          foregroundColor: textColor,
          side: BorderSide(color: borderColor),
          minimumSize: const Size(132, 52),
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(AppRadii.pill),
          ),
          padding: const EdgeInsets.symmetric(
            horizontal: AppSpacing.lg,
            vertical: AppSpacing.sm,
          ),
        ),
        child: Text(
          label,
          style: AppTextStyles.body2.copyWith(
            color: textColor,
            fontWeight: FontWeight.w800,
          ),
        ),
      ),
    );
  }
}
