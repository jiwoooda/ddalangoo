import 'package:flutter/material.dart';

import 'app_colors.dart';

abstract final class AppTextStyles {
  static const display = TextStyle(
    fontSize: 32,
    height: 1.25,
    fontWeight: FontWeight.w700,
    color: AppColors.textStrong,
  );

  static const title1 = TextStyle(
    fontSize: 28,
    height: 1.28,
    fontWeight: FontWeight.w700,
    color: AppColors.textStrong,
  );

  static const title2 = TextStyle(
    fontSize: 24,
    height: 1.33,
    fontWeight: FontWeight.w700,
    color: AppColors.textStrong,
  );

  static const body1 = TextStyle(
    fontSize: 18,
    height: 1.5,
    fontWeight: FontWeight.w500,
    color: AppColors.textPrimary,
  );

  static const body2 = TextStyle(
    fontSize: 16,
    height: 1.5,
    fontWeight: FontWeight.w500,
    color: AppColors.textSecondary,
  );

  static const caption = TextStyle(
    fontSize: 13,
    height: 1.38,
    fontWeight: FontWeight.w500,
    color: AppColors.textMuted,
  );

  static const button = TextStyle(
    fontSize: 18,
    height: 1.2,
    fontWeight: FontWeight.w700,
    color: Colors.white,
  );
}
