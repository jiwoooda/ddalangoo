import 'package:flutter/material.dart';

import '../../app/theme/app_colors.dart';
import '../../app/theme/app_radii.dart';
import '../../app/theme/app_spacing.dart';
import '../../app/theme/app_text_styles.dart';

class BottomStatusBanner extends StatelessWidget {
  const BottomStatusBanner({
    super.key,
    required this.message,
    this.characterAssetPath,
    this.onClosePressed,
    this.trailing,
    this.messageStyle,
    this.padding = const EdgeInsets.all(AppSpacing.md),
    this.avatarSize = 52,
  });

  final String message;
  final String? characterAssetPath;
  final VoidCallback? onClosePressed;
  final Widget? trailing;
  final TextStyle? messageStyle;
  final EdgeInsets padding;
  final double avatarSize;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: padding,
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(AppRadii.xl),
        border: Border.all(color: AppColors.border),
        boxShadow: const [
          BoxShadow(
            color: AppColors.shadow,
            blurRadius: 18,
            offset: Offset(0, -4),
          ),
        ],
      ),
      child: Row(
        children: [
          if (characterAssetPath != null)
            Container(
              width: avatarSize,
              height: avatarSize,
              margin: const EdgeInsets.only(right: AppSpacing.md),
              decoration: BoxDecoration(
                shape: BoxShape.circle,
                color: AppColors.surface,
                border: Border.all(color: AppColors.border),
              ),
              clipBehavior: Clip.antiAlias,
              child: Image.asset(characterAssetPath!, fit: BoxFit.cover),
            ),
          Expanded(
            child: Text(
              message,
              style:
                  messageStyle ??
                  AppTextStyles.body1.copyWith(
                    color: AppColors.textPrimary,
                    fontWeight: FontWeight.w800,
                  ),
            ),
          ),
          if (trailing != null) ...[
            const SizedBox(width: AppSpacing.md),
            trailing!,
          ] else if (onClosePressed != null) ...[
            const SizedBox(width: AppSpacing.md),
            IconButton(
              onPressed: onClosePressed,
              icon: const Icon(Icons.close_rounded),
              color: AppColors.primaryPinkDark,
            ),
          ],
        ],
      ),
    );
  }
}
