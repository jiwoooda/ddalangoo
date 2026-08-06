import 'package:flutter/material.dart';

import 'app_colors.dart';

abstract final class AppSurfaceStyles {
  static const double thinOutlineWidth = 1.25;
  static const double emphasisOutlineWidth = 3.0;
  static const double pinPadOutlineWidth = 2.2;

  static const Color standardOutlineColor = AppColors.border;
  static const Color emphasisOutlineColor = AppColors.textStrong;

  static const List<BoxShadow> raisedShadow = [
    BoxShadow(color: Color(0x0A000000), blurRadius: 4, offset: Offset(0, 2)),
    BoxShadow(color: AppColors.shadow, blurRadius: 18, offset: Offset(0, 8)),
  ];

  static const List<BoxShadow> featuredProductShadow = [
    BoxShadow(color: Color(0x0C000000), blurRadius: 6, offset: Offset(0, 2)),
    BoxShadow(color: Color(0x18000000), blurRadius: 26, offset: Offset(0, 14)),
  ];

  static const List<BoxShadow> bubbleShadow = [
    BoxShadow(color: Color(0x0C000000), blurRadius: 4, offset: Offset(0, 2)),
    BoxShadow(color: Color(0x16000000), blurRadius: 22, offset: Offset(0, 10)),
  ];

  static BoxDecoration elevatedCard({
    required double radius,
    Color color = Colors.white,
    Color borderColor = standardOutlineColor,
    double borderWidth = thinOutlineWidth,
    List<BoxShadow> boxShadow = raisedShadow,
  }) {
    return BoxDecoration(
      color: color,
      borderRadius: BorderRadius.circular(radius),
      border: Border.all(color: borderColor, width: borderWidth),
      boxShadow: boxShadow,
    );
  }

  static BoxDecoration emphasizedPanel({
    required double radius,
    Color color = Colors.white,
    Color borderColor = emphasisOutlineColor,
    double borderWidth = emphasisOutlineWidth,
    List<BoxShadow>? boxShadow,
  }) {
    return BoxDecoration(
      color: color,
      borderRadius: BorderRadius.circular(radius),
      border: Border.all(color: borderColor, width: borderWidth),
      boxShadow: boxShadow,
    );
  }

  static BoxDecoration floatingCard({
    required double radius,
    Color color = Colors.white,
    List<BoxShadow> boxShadow = raisedShadow,
  }) {
    return BoxDecoration(
      color: color,
      borderRadius: BorderRadius.circular(radius),
      boxShadow: boxShadow,
    );
  }
}
