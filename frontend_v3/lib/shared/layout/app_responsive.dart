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

  // 타겟 디바이스 실측 해상도 1080x2340(19.5:9)를 dp 기준으로 환산한 값.
  // 해당 해상도대의 실제 기기는 대부분 density ~2.75~2.8로 리포트되며,
  // 그 결과 논리 픽셀(dp)이 390x845 근방으로 수렴한다. 스케일 계산은 절대값이
  // 아니라 이 비율(width/height) 대비 실제 화면 비율의 편차만 보므로, 이 값을
  // 1080x2340과 최대한 가깝게 맞춰두면 그 해상도 기기에서 scale factor가
  // 1.0에 가장 가깝게 나온다(= 폰트/여백이 디자인 의도값에 가장 근접).
  static const Size _designSize = Size(390, 845);

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

  /// 스몰토크/에이전트 인사/분석 안내처럼 화면 가운데에 캐릭터 한 명을
  /// 크게 보여주는 "대화형" 화면들이 공통으로 쓰는 반응형 캐릭터 높이.
  /// 화면마다 고정값(예: 330)을 쓰거나 서로 다른 스케일 범위를 쓰면 같은
  /// 그림도 화면마다 크기가 달라 보이는 문제가 있어서, 하나의 계산식으로
  /// 통일했다. base/min만 화면별로 필요하면 조정하고, 스케일 공식 자체는
  /// 항상 같게 유지한다.
  double conversationCharacterHeight({double base = 330, double min = 260}) {
    return bound(
      heightScaled(base, minFactor: 0.82, maxFactor: 1.0),
      min: min,
      max: base,
    );
  }
}

extension AppResponsiveContext on BuildContext {
  AppResponsive get responsive => AppResponsive.of(this);
}
