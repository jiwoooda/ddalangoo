// 안드로이드 접근성 서비스 기반 자동화를 위해, 사용자가 실제로 쓰는 쇼핑 플랫폼
// 목록을 스캔하는 동안 보여줄 대기 화면.
//
// TODO(backend/native)
// 실제로는 안드로이드 AccessibilityService가 설치된 앱 목록을 스캔해서 지원 플랫폼을 하나씩 찾아낸다.
// 지금은 프론트 단독 화면으로, 정해진 플랫폼 목록을 순서대로 "발견"하는 것처럼 흉내만 낸다.
import 'dart:async';
import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:liquid_glass_renderer/liquid_glass_renderer.dart';

import '../widgets/liquid_glass_page.dart';
import '../widgets/shopping_screen_chrome.dart';

class _ScannedPlatform {
  const _ScannedPlatform({
    required this.name,
    required this.assetPath,
    required this.alignmentX,
    required this.alignmentY,
  });

  final String name;
  final String assetPath;

  /// 중심(캐릭터) 기준 배치 방향. 실제 배치 거리는 화면 크기와 중앙 캐릭터
  /// 크기를 바탕으로 겹치지 않게 런타임에 재조정된다 (_pushOutsideCenter 참고).
  final double alignmentX;
  final double alignmentY;
}

/// 모든 플랫폼 배지가 동일한 크기 / 동일한 모서리 둥글기를 갖도록 하는 상수.
/// 중앙 캐릭터 원을 키우는 대신 배지는 살짝 작게 잡아 화면을 더 넓게 쓴다.
const double _kAvatarSize = 72.0;
const double _kAvatarBorderRadius = 18.0;

class PlatformScanScreen extends StatefulWidget {
  const PlatformScanScreen({super.key, this.userName, this.onComplete});

  final String? userName;
  final VoidCallback? onComplete;

  @override
  State<PlatformScanScreen> createState() => _PlatformScanScreenState();
}

class _PlatformScanScreenState extends State<PlatformScanScreen>
    with TickerProviderStateMixin {
  static const _platforms = <_ScannedPlatform>[
    _ScannedPlatform(
      name: '마켓컬리',
      assetPath: 'assets/images/kurly.png',
      alignmentX: -0.30,
      alignmentY: 0.46,
    ),
    _ScannedPlatform(
      name: '쿠팡',
      assetPath: 'assets/images/coupang.png',
      alignmentX: -0.56,
      alignmentY: -0.56,
    ),
    _ScannedPlatform(
      name: '네이버',
      assetPath: 'assets/images/naver.png',
      alignmentX: 0.66,
      alignmentY: 0.02,
    ),
    _ScannedPlatform(
      name: '컬리N마트',
      assetPath: 'assets/images/kurlynmart.png',
      alignmentX: 0.28,
      alignmentY: 0.72,
    ),
    _ScannedPlatform(
      name: '현대홈쇼핑',
      assetPath: 'assets/images/hyundaihomeshopping.png',
      alignmentX: -0.72,
      alignmentY: -0.12,
    ),
  ];

  late final AnimationController _sweepController = AnimationController(
    vsync: this,
    duration: const Duration(milliseconds: 3400),
  )..repeat();

  int _foundCount = 0;
  Timer? _revealTimer;
  bool _completedNotified = false;

  @override
  void initState() {
    super.initState();
    _revealTimer = Timer.periodic(const Duration(milliseconds: 1500), (timer) {
      if (!mounted) return;
      if (_foundCount >= _platforms.length) {
        timer.cancel();
        if (!_completedNotified) {
          _completedNotified = true;
          widget.onComplete?.call();
        }
        return;
      }
      setState(() => _foundCount += 1);
    });
  }

  @override
  void dispose() {
    _revealTimer?.cancel();
    _sweepController.dispose();
    super.dispose();
  }

  String get _headerText {
    final name = widget.userName;
    return (name == null || name.isEmpty)
        ? '사용하시는 쇼핑 플랫폼을 모으고 있어요'
        : '$name님이 사용하시는\n쇼핑 플랫폼을 모으고 있어요';
  }

  bool get _isDone => _foundCount >= _platforms.length;

  @override
  Widget build(BuildContext context) {
    final bottomInset = MediaQuery.of(context).padding.bottom;

    return LiquidGlassPage(
      child: Scaffold(
        backgroundColor: const Color(0xFFF9FCFB),
        body: SafeArea(
          child: Stack(
            children: [
              const Positioned.fill(child: ShoppingScreenBackground()),
              Positioned(
                top: -80,
                right: -40,
                child: _GlowBlob(
                  size: 220,
                  color: Color(0xFFFF9CC6),
                  opacity: 0.14,
                ),
              ),
              Positioned(
                left: -50,
                bottom: 120,
                child: _GlowBlob(
                  size: 180,
                  color: Color.fromARGB(255, 250, 65, 198),
                  opacity: 0.12,
                ),
              ),
              Padding(
                padding: const EdgeInsets.fromLTRB(12, 12, 12, 20),
                child: Column(
                  children: [
                    const Align(
                      alignment: Alignment.centerLeft,
                      child: ShoppingScreenBackButton(),
                    ),
                    const SizedBox(height: 16),
                    Text(
                      _headerText,
                      textAlign: TextAlign.center,
                      style: const TextStyle(
                        fontFamily: 'Pretendard',
                        fontSize: 28,
                        fontWeight: FontWeight.w800,
                        height: 1.35,
                        color: Color(0xFF233243),
                      ),
                    ),
                    const SizedBox(height: 10),
                    Icon(
                      Icons.radar_rounded,
                      size: 20,
                      color: const Color(0xFF51606E).withValues(alpha: 0.60),
                    ),
                    Expanded(
                      child: LayoutBuilder(
                        builder: (context, constraints) {
                          final size = math.min(
                            constraints.maxWidth,
                            constraints.maxHeight,
                          );
                          final maxRadius = size / 2;
                          final centerDiameter = math.max(
                            150.0,
                            math.min(240.0, size * 0.44),
                          );
                          // 배지가 가운데 딸랑구 원(글래스 테두리 + 은은한 글로우 포함)과
                          // 겹치지 않도록, 중앙 원 반지름 + 배지 반지름 + 여유 여백만큼은
                          // 최소로 떨어뜨려 배치한다. 여백을 넉넉히 잡아 그림자/글로우까지 감안한다.
                          final minDistancePx =
                              centerDiameter / 2 + _kAvatarSize / 2 + 36;
                          final minRadiusFraction = math.min(
                            0.98,
                            minDistancePx / maxRadius,
                          );
                          return Center(
                            child: SizedBox(
                              width: size,
                              height: size,
                              child: Stack(
                                alignment: Alignment.center,
                                children: [
                                  AnimatedBuilder(
                                    animation: _sweepController,
                                    builder: (context, _) {
                                      return CustomPaint(
                                        size: Size(size, size),
                                        painter: _RadarPainter(
                                          sweepAngle:
                                              _sweepController.value *
                                              2 *
                                              math.pi,
                                        ),
                                      );
                                    },
                                  ),
                                  for (final platform in _platforms)
                                    _buildPlatformBubble(
                                      platform,
                                      found:
                                          _platforms.indexOf(platform) <
                                          _foundCount,
                                      minRadiusFraction: minRadiusFraction,
                                    ),
                                  _CenterCharacter(size: size * 0.44),
                                ],
                              ),
                            ),
                          );
                        },
                      ),
                    ),
                    Text(
                      _isDone
                          ? '${_platforms.length}개의 플랫폼을 찾았어요!'
                          : '$_foundCount / ${_platforms.length}개 찾는 중 · 잠시만 기다려주세요',
                      style: const TextStyle(
                        fontFamily: 'Pretendard',
                        color: Color(0xFF51606E),
                        fontWeight: FontWeight.w700,
                        fontSize: 15,
                      ),
                    ),
                    const SizedBox(height: 14),
                    ShoppingScreenBottomButton(
                      label: '대화 종료',
                      bottomInset: bottomInset,
                      onPressed: () => Navigator.of(context).maybePop(),
                    ),
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildPlatformBubble(
    _ScannedPlatform platform, {
    required bool found,
    required double minRadiusFraction,
  }) {
    final placement = _pushOutsideCenter(
      platform.alignmentX,
      platform.alignmentY,
      minRadiusFraction,
    );
    return Align(
      alignment: Alignment(placement.dx, placement.dy),
      child: AnimatedScale(
        scale: found ? 1.0 : 0.0,
        duration: const Duration(milliseconds: 420),
        curve: Curves.elasticOut,
        child: AnimatedOpacity(
          opacity: found ? 1.0 : 0.0,
          duration: const Duration(milliseconds: 260),
          child: _PlatformAvatar(platform: platform),
        ),
      ),
    );
  }

  /// 배치 좌표(alignmentX, alignmentY)를 원점(중앙 캐릭터) 방향에서
  /// minMagnitude 이상 떨어지도록 바깥쪽으로 밀어낸다. 방향은 유지한 채
  /// 거리만 늘리므로 기존에 잡아둔 시각적 배치(레이아웃 느낌)는 그대로 둔다.
  Offset _pushOutsideCenter(double x, double y, double minMagnitude) {
    final magnitude = math.sqrt(x * x + y * y);
    if (magnitude == 0) {
      return Offset(minMagnitude, 0);
    }
    if (magnitude >= minMagnitude) {
      return Offset(
        math.max(-0.985, math.min(0.985, x)),
        math.max(-0.985, math.min(0.985, y)),
      );
    }
    final scale = minMagnitude / magnitude;
    return Offset(
      math.max(-0.985, math.min(0.985, x * scale)),
      math.max(-0.985, math.min(0.985, y * scale)),
    );
  }
}

class _GlowBlob extends StatelessWidget {
  const _GlowBlob({
    required this.size,
    required this.color,
    required this.opacity,
  });

  final double size;
  final Color color;
  final double opacity;

  @override
  Widget build(BuildContext context) {
    return IgnorePointer(
      child: Container(
        width: size,
        height: size,
        decoration: BoxDecoration(
          shape: BoxShape.circle,
          gradient: RadialGradient(
            colors: [
              color.withValues(alpha: opacity),
              color.withValues(alpha: 0),
            ],
          ),
        ),
      ),
    );
  }
}

class _PlatformAvatar extends StatelessWidget {
  const _PlatformAvatar({required this.platform});

  final _ScannedPlatform platform;

  @override
  Widget build(BuildContext context) {
    return DecoratedBox(
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(_kAvatarBorderRadius),
        border: Border.all(
          color: Colors.white.withValues(alpha: 0.92),
          width: 2,
        ),
        boxShadow: [
          BoxShadow(
            color: const Color(0xFFFF7AB6).withValues(alpha: 0.18),
            blurRadius: 24,
            offset: const Offset(0, 10),
          ),
          BoxShadow(
            color: Colors.black.withValues(alpha: 0.10),
            blurRadius: 18,
            offset: const Offset(0, 8),
          ),
        ],
      ),
      child: ClipRRect(
        borderRadius: BorderRadius.circular(_kAvatarBorderRadius),
        child: SizedBox(
          width: _kAvatarSize,
          height: _kAvatarSize,
          child: Image.asset(
            platform.assetPath,
            // 로고 원본 비율이 서로 달라도 배지 크기/모양이 항상 동일하게
            // 보이도록 cover로 꽉 채운다.
            fit: BoxFit.cover,
            filterQuality: FilterQuality.high,
            errorBuilder: (context, error, stackTrace) => Container(
              color: Colors.white.withValues(alpha: 0.24),
              alignment: Alignment.center,
              child: const Icon(
                Icons.storefront_rounded,
                color: Color(0xFF51606E),
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class _CenterCharacter extends StatelessWidget {
  const _CenterCharacter({required this.size});

  final double size;

  @override
  Widget build(BuildContext context) {
    final clamped = math.max(150.0, math.min(240.0, size));
    final borderRadius = clamped / 2;
    return DecoratedBox(
      decoration: BoxDecoration(
        boxShadow: [
          BoxShadow(
            color: Colors.white.withValues(alpha: 0.22),
            blurRadius: 22,
            spreadRadius: 1,
          ),
          BoxShadow(
            color: const Color(0xFFFF9CC6).withValues(alpha: 0.18),
            blurRadius: 28,
            offset: const Offset(0, 12),
          ),
        ],
      ),
      child: LiquidGlass.grouped(
        shape: LiquidRoundedSuperellipse(borderRadius: borderRadius),
        clipBehavior: Clip.antiAlias,
        child: Container(
          width: clamped,
          height: clamped,
          padding: const EdgeInsets.all(10),
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(borderRadius),
            border: Border.all(
              color: Colors.white.withValues(alpha: 0.82),
              width: 1.4,
            ),
            gradient: LinearGradient(
              colors: [
                Colors.white.withValues(alpha: 0.40),
                Colors.white.withValues(alpha: 0.26),
                const Color(0xFFFFF9FC).withValues(alpha: 0.18),
              ],
              begin: Alignment.topLeft,
              end: Alignment.bottomRight,
            ),
          ),
          child: Stack(
            fit: StackFit.expand,
            children: [
              Positioned(
                top: 10,
                left: 14,
                right: 14,
                child: IgnorePointer(
                  child: Container(
                    height: clamped * 0.16,
                    decoration: BoxDecoration(
                      borderRadius: BorderRadius.circular(clamped * 0.08),
                      gradient: LinearGradient(
                        colors: [
                          Colors.white.withValues(alpha: 0.42),
                          Colors.white.withValues(alpha: 0.04),
                        ],
                      ),
                    ),
                  ),
                ),
              ),
              DecoratedBox(
                decoration: BoxDecoration(
                  shape: BoxShape.circle,
                  border: Border.all(
                    color: Colors.white.withValues(alpha: 0.58),
                    width: 1.2,
                  ),
                ),
                child: ClipOval(
                  child: Padding(
                    padding: const EdgeInsets.all(6),
                    child: Image.asset(
                      'assets/images/ddalangoo_curious.png',
                      fit: BoxFit.contain,
                      errorBuilder: (context, error, stackTrace) => const Icon(
                        Icons.favorite_rounded,
                        color: Colors.white,
                        size: 40,
                      ),
                    ),
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

/// 동심원 + 회전하는 레이더 스윕 라인을 그리는 페인터.
class _RadarPainter extends CustomPainter {
  _RadarPainter({required this.sweepAngle});

  final double sweepAngle;

  @override
  void paint(Canvas canvas, Size size) {
    final center = Offset(size.width / 2, size.height / 2);
    final maxRadius = size.width / 2;

    // 1) 배경 핑크 방사형 wash를 먼저 깐다.
    final fillPaint = Paint()
      ..shader = RadialGradient(
        colors: [
          Colors.white.withValues(alpha: 0.10),
          const Color(0xFFFF8DBB).withValues(alpha: 0.12),
          const Color(0xFFFF8DBB).withValues(alpha: 0.0),
        ],
        stops: const [0.0, 0.35, 1.0],
      ).createShader(Rect.fromCircle(center: center, radius: maxRadius));
    canvas.drawCircle(center, maxRadius, fillPaint);

    // 2) 회전하는 레이더 스윕 쐐기.
    final sweepRect = Rect.fromCircle(center: center, radius: maxRadius);
    final sweepPaint = Paint()
      ..shader = SweepGradient(
        startAngle: 0,
        endAngle: math.pi / 2.2,
        colors: [
          const Color.fromARGB(255, 232, 127, 174).withValues(alpha: 0.68),
          const Color.fromARGB(255, 255, 141, 187).withValues(alpha: 0.26),
          const Color.fromARGB(255, 255, 95, 167).withValues(alpha: 0.0),
        ],
        transform: GradientRotation(sweepAngle),
      ).createShader(sweepRect);
    canvas.drawCircle(center, maxRadius, sweepPaint);

    // 3) 흰색 동심원 테두리는 배경/스윕 위에 마지막으로 그려서
    // 핑크 배경 위로 "칸칸이" 선명하게 보이도록 한다.
    final ringPaint = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = 1.6;

    const ringCount = 4;
    for (var i = 1; i <= ringCount; i++) {
      final radius = maxRadius * (i / ringCount);
      ringPaint.color = Colors.white.withValues(alpha: 0.85);
      canvas.drawCircle(center, radius, ringPaint);
    }
  }

  @override
  bool shouldRepaint(covariant _RadarPainter oldDelegate) =>
      oldDelegate.sweepAngle != sweepAngle;
}
