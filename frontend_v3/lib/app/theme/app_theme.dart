import 'package:flutter/material.dart';

import 'app_colors.dart';
import 'app_radii.dart';
import 'app_sizes.dart';
import 'app_surface_styles.dart';
import 'app_text_styles.dart';

abstract final class AppTheme {
  static ThemeData light() {
    final base = ThemeData(
      useMaterial3: true,
      scaffoldBackgroundColor: AppColors.background,
      colorScheme: ColorScheme.fromSeed(
        seedColor: AppColors.primaryPink,
        brightness: Brightness.light,
        primary: AppColors.primaryPink,
        surface: AppColors.background,
      ),
    );

    return base.copyWith(
      textTheme: const TextTheme(
        displayLarge: AppTextStyles.display,
        headlineLarge: AppTextStyles.title1,
        headlineMedium: AppTextStyles.title2,
        bodyLarge: AppTextStyles.body1,
        bodyMedium: AppTextStyles.body2,
        bodySmall: AppTextStyles.caption,
        labelLarge: AppTextStyles.button,
      ),
      filledButtonTheme: FilledButtonThemeData(
        style: FilledButton.styleFrom(
          backgroundColor: AppColors.primaryPink,
          foregroundColor: Colors.white,
          minimumSize: const Size.fromHeight(AppSizes.buttonHeight),
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(AppRadii.md),
          ),
          textStyle: AppTextStyles.button,
        ),
      ),
      cardTheme: CardThemeData(
        color: AppColors.surface,
        surfaceTintColor: Colors.transparent,
        elevation: 0,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(AppRadii.lg),
          side: const BorderSide(
            color: AppSurfaceStyles.standardOutlineColor,
            width: AppSurfaceStyles.thinOutlineWidth,
          ),
        ),
      ),
    );
  }
}
