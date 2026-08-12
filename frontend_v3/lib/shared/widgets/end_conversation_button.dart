import 'package:flutter/material.dart';

import '../../app/theme/app_colors.dart';
import '../../app/theme/app_radii.dart';
import '../../app/theme/app_sizes.dart';
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
    this.fullWidth = false,
  });

  final VoidCallback onPressed;
  final String label;
  final EndConversationButtonVariant variant;
  final bool compact;
  final bool iconOnly;

  /// true면 화면 하단에 두는 전체 너비 버튼 형태로 렌더링한다. 화면마다
  /// 상단 우측에 떠 있던 대화 종료 버튼을 하단으로 통일해서 옮기기 위한
  /// 옵션 — [compact]/[iconOnly]는 이 모드에서는 사용하지 않는다.
  final bool fullWidth;

  @override
  Widget build(BuildContext context) {
    final isDark = variant == EndConversationButtonVariant.dark;
    // dark variant는 원래 AppColors.textSecondary(진회색)를 배경으로 썼는데,
    // 화면에서 너무 눈에 띄고 무거워 보인다는 피드백을 받아 더 연한 회색으로
    // 바꿨다.
    final backgroundColor = isDark ? AppColors.surfaceMuted : Colors.white;
    final borderColor = AppColors.border;
    final textColor = isDark
        ? AppColors.primaryPinkDark
        : AppColors.textPrimary;

    if (fullWidth) {
      return Semantics(
        button: true,
        label: label,
        child: SizedBox(
          width: double.infinity,
          height: AppSizes.compactButtonHeight,
          child: OutlinedButton.icon(
            onPressed: onPressed,
            icon: Icon(
              Icons.pause_circle_outline_rounded,
              size: 20,
              color: textColor,
            ),
            label: Text(
              label,
              style: AppTextStyles.body2.copyWith(
                color: textColor,
                fontWeight: FontWeight.w800,
              ),
            ),
            style: OutlinedButton.styleFrom(
              backgroundColor: backgroundColor,
              foregroundColor: textColor,
              side: BorderSide(color: borderColor),
              elevation: AppSurfaceStyles.compactButtonElevation,
              shadowColor: AppSurfaceStyles.buttonShadowColor,
              surfaceTintColor: Colors.transparent,
              shape: RoundedRectangleBorder(
                borderRadius: BorderRadius.circular(AppRadii.lg),
              ),
            ),
          ),
        ),
      );
    }

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
