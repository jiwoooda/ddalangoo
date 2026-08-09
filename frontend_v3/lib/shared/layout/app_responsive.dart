import 'dart:math' as math;

import 'package:flutter/widgets.dart';

enum AppWidthClass { compact, regular, expanded }

enum AppHeightClass { compact, regular, tall }

class AppResponsive {
  AppResponsive._({
    required this.size,
    required this.viewInsets,
    required this.viewPadding,
  });

  factory AppResponsive.of(BuildContext context) {
    final mediaQuery = MediaQuery.of(context);
    return AppResponsive._(
      size: mediaQuery.size,
      viewInsets: mediaQuery.viewInsets,
      viewPadding: mediaQuery.viewPadding,
    );
  }

  static const Size _designSize = Size(390, 844);

  final Size size;
  final EdgeInsets viewInsets;
  final EdgeInsets viewPadding;

  double get width => size.width;
  double get height => size.height;

  AppWidthClass get widthClass {
    if (width < 360) {
      return AppWidthClass.compact;
    }
    if (width >= 600) {
      return AppWidthClass.expanded;
    }
    return AppWidthClass.regular;
  }

  AppHeightClass get heightClass {
    if (height < 740) {
      return AppHeightClass.compact;
    }
    if (height >= 920) {
      return AppHeightClass.tall;
    }
    return AppHeightClass.regular;
  }

  bool get isCompactWidth => widthClass == AppWidthClass.compact;
  bool get isExpandedWidth => widthClass == AppWidthClass.expanded;
  bool get isShortHeight => heightClass == AppHeightClass.compact;
  bool get isTallHeight => heightClass == AppHeightClass.tall;
  bool get usesCondensedLayout => isCompactWidth || isShortHeight;
  bool get prefersSingleColumn => width < 340;

  double scale(
    double base, {
    double minFactor = 0.88,
    double maxFactor = 1.12,
  }) {
    final widthFactor = _clamp(width / _designSize.width, minFactor, maxFactor);
    final heightFactor = _clamp(
      height / _designSize.height,
      minFactor,
      maxFactor,
    );
    return base * math.min(widthFactor, heightFactor);
  }

  double widthScaled(
    double base, {
    double minFactor = 0.84,
    double maxFactor = 1.16,
  }) {
    return base * _clamp(width / _designSize.width, minFactor, maxFactor);
  }

  double heightScaled(
    double base, {
    double minFactor = 0.78,
    double maxFactor = 1.14,
  }) {
    return base * _clamp(height / _designSize.height, minFactor, maxFactor);
  }

  double font(double base, {double minFactor = 0.94, double maxFactor = 1.08}) {
    return scale(base, minFactor: minFactor, maxFactor: maxFactor);
  }

  double clampScaled(
    double base, {
    required double min,
    required double max,
    double minFactor = 0.88,
    double maxFactor = 1.12,
  }) {
    return bound(
      scale(base, minFactor: minFactor, maxFactor: maxFactor),
      min: min,
      max: max,
    );
  }

  double bound(double value, {required double min, required double max}) {
    return value.clamp(min, max).toDouble();
  }

  double topSpacing(double base) {
    return bound(
      heightScaled(base, minFactor: 0.75, maxFactor: 1.05),
      min: 12,
      max: base + 6,
    );
  }

  double bottomSpacing(double base) {
    return bound(
      heightScaled(base, minFactor: 0.72, maxFactor: 1.08),
      min: 12,
      max: base + 8,
    );
  }

  EdgeInsets adaptivePadding({
    required double horizontal,
    required double top,
    required double bottom,
  }) {
    return EdgeInsets.fromLTRB(
      bound(
        widthScaled(horizontal, minFactor: 0.8, maxFactor: 1.3),
        min: 16,
        max: 36,
      ),
      topSpacing(top),
      bound(
        widthScaled(horizontal, minFactor: 0.8, maxFactor: 1.3),
        min: 16,
        max: 36,
      ),
      bottomSpacing(bottom),
    );
  }

  double _clamp(double value, double min, double max) {
    return value.clamp(min, max).toDouble();
  }
}

extension AppResponsiveContext on BuildContext {
  AppResponsive get responsive => AppResponsive.of(this);
}
