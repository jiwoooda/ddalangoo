import 'package:flutter/material.dart';

import '../../../app/theme/app_colors.dart';
import '../../../app/theme/app_spacing.dart';
import '../../../app/theme/app_text_styles.dart';

class VoiceActionButton extends StatelessWidget {
  const VoiceActionButton({
    super.key,
    required this.label,
    required this.onPressed,
    this.isActive = true,
  });

  final String label;
  final VoidCallback onPressed;
  final bool isActive;

  @override
  Widget build(BuildContext context) {
    final backgroundColor = isActive
        ? AppColors.primaryPink
        : AppColors.surfaceMuted;
    final foregroundColor = isActive ? Colors.white : AppColors.textMuted;

    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        GestureDetector(
          onTap: onPressed,
          child: AnimatedContainer(
            duration: const Duration(milliseconds: 220),
            width: 104,
            height: 104,
            decoration: BoxDecoration(
              color: backgroundColor,
              shape: BoxShape.circle,
              boxShadow: [
                BoxShadow(
                  color: backgroundColor.withValues(
                    alpha: isActive ? 0.28 : 0.14,
                  ),
                  blurRadius: 24,
                  offset: const Offset(0, 12),
                ),
              ],
            ),
            child: Icon(Icons.mic_rounded, size: 44, color: foregroundColor),
          ),
        ),
        const SizedBox(height: AppSpacing.md),
        Text(
          label,
          style: AppTextStyles.body2.copyWith(
            fontWeight: FontWeight.w700,
            color: isActive ? AppColors.primaryPinkDark : AppColors.textMuted,
          ),
        ),
      ],
    );
  }
}
