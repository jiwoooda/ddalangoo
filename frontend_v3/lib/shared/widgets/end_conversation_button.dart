import 'package:flutter/material.dart';

import '../../app/theme/app_colors.dart';
import '../../app/theme/app_radii.dart';
import '../../app/theme/app_spacing.dart';
import '../../app/theme/app_surface_styles.dart';
import '../../app/theme/app_text_styles.dart';

enum EndConversationButtonVariant { light, dark }

class EndConversationButton extends StatelessWidget {
  const EndConversationButton({
    super.key,
    required this.onPressed,
    this.label = '대화 종료',
    this.variant = EndConversationButtonVariant.light,
    this.compact = false,
    this.iconOnly = false,
  });

  final VoidCallback onPressed;
  final String label;
  final EndConversationButtonVariant variant;
  final bool compact;
  final bool iconOnly;

  @override
  Widget build(BuildContext context) {
    final isDark = variant == EndConversationButtonVariant.dark;
    final backgroundColor = isDark ? AppColors.textStrong : Colors.white;
    final borderColor = isDark ? AppColors.textStrong : AppColors.border;
    final textColor = isDark
        ? AppColors.primaryPinkDark
        : AppColors.textPrimary;
    final minimumSize = iconOnly
        ? const Size(42, 42)
        : compact
        ? const Size(100, 42)
        : const Size(132, 52);
    final padding = compact
        ? const EdgeInsets.symmetric(
            horizontal: AppSpacing.sm,
            vertical: AppSpacing.xxs,
          )
        : const EdgeInsets.symmetric(
            horizontal: AppSpacing.lg,
            vertical: AppSpacing.sm,
          );
    final textStyle = (compact ? AppTextStyles.caption : AppTextStyles.body2)
        .copyWith(color: textColor, fontWeight: FontWeight.w800);

    return Semantics(
      button: true,
      label: label,
      child: OutlinedButton(
        onPressed: onPressed,
        style: OutlinedButton.styleFrom(
          backgroundColor: backgroundColor,
          foregroundColor: textColor,
          side: BorderSide(color: borderColor),
          elevation: compact
              ? AppSurfaceStyles.compactButtonElevation
              : AppSurfaceStyles.buttonElevation,
          shadowColor: AppSurfaceStyles.buttonShadowColor,
          surfaceTintColor: Colors.transparent,
          minimumSize: minimumSize,
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(AppRadii.pill),
          ),
          padding: iconOnly ? EdgeInsets.zero : padding,
          tapTargetSize: compact
              ? MaterialTapTargetSize.shrinkWrap
              : MaterialTapTargetSize.padded,
          visualDensity: compact
              ? const VisualDensity(horizontal: -1, vertical: -1)
              : VisualDensity.standard,
        ),
        child: iconOnly
            ? Icon(Icons.pause_rounded, size: 20, color: textColor)
            : Text(label, style: textStyle),
      ),
    );
  }
}
