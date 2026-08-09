import 'package:flutter/material.dart';

import '../../app/theme/app_colors.dart';
import '../../app/theme/app_radii.dart';
import '../../app/theme/app_sizes.dart';
import '../../app/theme/app_surface_styles.dart';
import '../../app/theme/app_text_styles.dart';
import '../layout/app_responsive.dart';

class SecondaryButton extends StatelessWidget {
  const SecondaryButton({super.key, required this.label, this.onPressed});

  final String label;
  final VoidCallback? onPressed;

  @override
  Widget build(BuildContext context) {
    final responsive = context.responsive;
    final buttonHeight = responsive.bound(
      responsive.heightScaled(
        AppSizes.buttonHeight,
        minFactor: 0.86,
        maxFactor: 1.0,
      ),
      min: AppSizes.compactButtonHeight,
      max: AppSizes.buttonHeight,
    );

    return SizedBox(
      width: double.infinity,
      height: buttonHeight,
      child: FilledButton(
        onPressed: onPressed,
        style: FilledButton.styleFrom(
          backgroundColor: AppColors.secondaryPink,
          foregroundColor: AppColors.primaryPinkDark,
          elevation: AppSurfaceStyles.buttonElevation,
          shadowColor: AppSurfaceStyles.buttonShadowColor,
          surfaceTintColor: Colors.transparent,
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(AppRadii.md),
          ),
        ),
        child: Text(
          label,
          style: AppTextStyles.body1.copyWith(
            fontWeight: FontWeight.w700,
            color: AppColors.primaryPinkDark,
          ),
        ),
      ),
    );
  }
}
