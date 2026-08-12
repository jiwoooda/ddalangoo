// 안드로이드 접근성 서비스 기반 자동화로 각 쇼핑 플랫폼의 지난 구매 이력을
// 불러오는 동안 보여줄 대기 화면.
//
// TODO(backend/native): 실제로는 플랫폼별 자동화가 구매 내역을 순서대로 긁어와
// 상품명/키워드를 추출한다. 지금은 프론트 단독 화면으로, 정해진 키워드 목록이
// 하나씩 "발견"되는 것처럼 흉내만 낸다.
import 'dart:async';
import 'dart:math' as math;

import 'package:flutter/material.dart';

import '../widgets/liquid_glass_page.dart';
import '../widgets/shopping_screen_chrome.dart';

class _HistoryBubble {
  const _HistoryBubble({
    required this.keyword,
    required this.dx,
    required this.dy,
    required this.diameter,
    required this.rotationDeg,
    required this.color,
    required this.imageAsset,
  });

  final String keyword;

  /// Alignment 좌표계 기준 (-1.0 ~ 1.0)
  final double dx;
  final double dy;
  final double diameter;
  final double rotationDeg;

  /// 이미지가 없을 때/로딩 전 배경으로 쓰는 베이스 색상.
  final Color color;

  /// assets/mock_productimages 안의 목업 상품 이미지. 반투명하게 깔리고
  /// 그 위에 키워드 텍스트가 올라간다.
  final String imageAsset;
}

class PurchaseHistoryLoadingScreen extends StatefulWidget {
  const PurchaseHistoryLoadingScreen({
    super.key,
    this.userName,
    this.onComplete,
  });

  final String? userName;
  final VoidCallback? onComplete;

  @override
  State<PurchaseHistoryLoadingScreen> createState() =>
      _PurchaseHistoryLoadingScreenState();
}

class _PurchaseHistoryLoadingScreenState
    extends State<PurchaseHistoryLoadingScreen> {
  // TODO(backend): 실제 구매 이력 키워드 추출 결과로 실시간 버블 업데이트
  static const _bubbles = <_HistoryBubble>[
    _HistoryBubble(
      keyword: '금실딸기',
      dx: -0.62,
      dy: -0.66,
      diameter: 118,
      rotationDeg: -6,
      color: Color(0xFFFFE1EA),
      imageAsset: 'assets/mock_productimages/strawberry.jpg',
    ),
    _HistoryBubble(
      keyword: '바나나',
      dx: 0.55,
      dy: -0.72,
      diameter: 100,
      rotationDeg: 5,
      color: Color(0xFFFFF3D6),
      imageAsset: 'assets/mock_productimages/banana.png',
    ),
    _HistoryBubble(
      keyword: '시루콧토\n페이스타올',
      dx: 0.0,
      dy: -0.36,
      diameter: 140,
      rotationDeg: -3,
      color: Color(0xFFE4F3FF),
      imageAsset: 'assets/mock_productimages/sirukotto.png',
    ),
    _HistoryBubble(
      keyword: '무항생제\n계란',
      dx: -0.72,
      dy: 0.0,
      diameter: 108,
      rotationDeg: 8,
      color: Color(0xFFE8FBEA),
      imageAsset: 'assets/mock_productimages/eggs.png',
    ),
    _HistoryBubble(
      keyword: '조각 수박',
      dx: 0.7,
      dy: -0.02,
      diameter: 96,
      rotationDeg: -8,
      color: Color(0xFFEFE7FF),
      imageAsset: 'assets/mock_productimages/watermelon.png',
    ),
    _HistoryBubble(
      keyword: '고구마\n말랭이',
      dx: -0.42,
      dy: 0.42,
      diameter: 104,
      rotationDeg: 4,
      color: Color(0xFFFFEAE1),
      imageAsset: 'assets/mock_productimages/sweetpotato.png',
    ),
    _HistoryBubble(
      keyword: '한라봉',
      dx: 0.5,
      dy: 0.5,
      diameter: 118,
      rotationDeg: -5,
      color: Color(0xFFE1F6F0),
      imageAsset: 'assets/mock_productimages/hallabong.png',
    ),
    _HistoryBubble(
      keyword: '토레타',
      dx: 0.02,
      dy: 0.72,
      diameter: 112,
      rotationDeg: 6,
      color: Color(0xFFFFF0F5),
      imageAsset: 'assets/mock_productimages/toreta.png',
    ),
    _HistoryBubble(
      keyword: '콩국수',
      dx: 0.02,
      dy: 0.72,
      diameter: 112,
      rotationDeg: 6,
      color: Color(0xFFFFF0F5),
      imageAsset: 'assets/mock_productimages/beannoodle.png',
    ),
  ];

  int _revealCount = 0;
  Timer? _revealTimer;
  bool _completedNotified = false;

  @override
  void initState() {
    super.initState();
    _revealTimer = Timer.periodic(const Duration(milliseconds: 750), (timer) {
      if (!mounted) return;
      if (_revealCount >= _bubbles.length) {
        timer.cancel();
        if (!_completedNotified) {
          _completedNotified = true;
          widget.onComplete?.call();
        }
        return;
      }
      setState(() => _revealCount += 1);
    });
  }

  @override
  void dispose() {
    _revealTimer?.cancel();
    super.dispose();
  }

  bool get _isDone => _revealCount >= _bubbles.length;

  String get _headerText {
    final name = widget.userName;
    return (name == null || name.isEmpty)
        ? '지난 구매 이력을 불러오는 중이에요'
        : '$name님의 지난 구매 이력을\n불러오는 중이에요';
  }

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
              Padding(
                padding: const EdgeInsets.fromLTRB(24, 12, 24, 24),
                child: Column(
                  children: [
                    const Align(
                      alignment: Alignment.centerLeft,
                      child: ShoppingScreenBackButton(),
                    ),
                    const SizedBox(height: 20),
                    Text(
                      _headerText,
                      textAlign: TextAlign.center,
                      style: const TextStyle(
                        fontFamily: 'Pretendard',
                        fontSize: 30,
                        fontWeight: FontWeight.w800,
                        height: 1.35,
                        color: Color(0xFF2B2130),
                      ),
                    ),
                    const SizedBox(height: 6),
                    Text(
                      '$_revealCount / ${_bubbles.length}개 확인 중',
                      style: const TextStyle(
                        fontFamily: 'Pretendard',
                        fontSize: 13,
                        fontWeight: FontWeight.w600,
                        color: Color(0xFF9B8A93),
                      ),
                    ),
                    Expanded(
                      child: LayoutBuilder(
                        builder: (context, constraints) {
                          return Stack(
                            alignment: Alignment.center,
                            children: [
                              for (var i = 0; i < _bubbles.length; i++)
                                _buildBubble(
                                  _bubbles[i],
                                  found: i < _revealCount,
                                ),
                            ],
                          );
                        },
                      ),
                    ),
                    if (_isDone)
                      const Text(
                        '구매 이력을 다 모았어요',
                        style: TextStyle(
                          fontFamily: 'Pretendard',
                          fontSize: 14,
                          fontWeight: FontWeight.w700,
                          color: Color(0xFF51606E),
                        ),
                      )
                    else
                      const _LoadingDotsRow(),
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

  Widget _buildBubble(_HistoryBubble bubble, {required bool found}) {
    return Align(
      alignment: Alignment(bubble.dx, bubble.dy),
      child: TweenAnimationBuilder<double>(
        tween: Tween(begin: 0, end: found ? 1 : 0),
        duration: const Duration(milliseconds: 420),
        curve: Curves.elasticOut,
        builder: (context, value, child) {
          return Transform.rotate(
            angle: bubble.rotationDeg * math.pi / 180 * value,
            child: Transform.scale(scale: value, child: child),
          );
        },
        child: Container(
          width: bubble.diameter,
          height: bubble.diameter,
          decoration: BoxDecoration(
            color: bubble.color,
            shape: BoxShape.circle,
            border: Border.all(color: Colors.white, width: 3),
            boxShadow: [
              BoxShadow(
                color: Colors.black.withValues(alpha: 0.08),
                blurRadius: 16,
                offset: const Offset(0, 8),
              ),
            ],
          ),
          child: ClipOval(
            child: Stack(
              alignment: Alignment.center,
              fit: StackFit.expand,
              children: [
                // 반투명 목업 상품 이미지 - 버블 배경으로 은은하게 깔린다.
                Opacity(
                  opacity: 0.42,
                  child: Image.asset(
                    bubble.imageAsset,
                    fit: BoxFit.cover,
                    errorBuilder: (context, error, stackTrace) =>
                        const SizedBox.shrink(),
                  ),
                ),
                // 이미지 위에서도 글자가 또렷하게 보이도록 옅은 화이트 스크림을 얹는다.
                Container(color: Colors.white.withValues(alpha: 0.18)),
                Padding(
                  padding: const EdgeInsets.all(10),
                  child: Text(
                    bubble.keyword,
                    textAlign: TextAlign.center,
                    maxLines: 2,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(
                      fontFamily: 'Pretendard',
                      fontSize: 14,
                      fontWeight: FontWeight.w800,
                      color: Color(0xFF3A2E35),
                      height: 1.15,
                      shadows: [Shadow(color: Colors.white, blurRadius: 6)],
                    ),
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _LoadingDotsRow extends StatefulWidget {
  const _LoadingDotsRow();

  @override
  State<_LoadingDotsRow> createState() => _LoadingDotsRowState();
}

class _LoadingDotsRowState extends State<_LoadingDotsRow>
    with SingleTickerProviderStateMixin {
  late final AnimationController _controller = AnimationController(
    vsync: this,
    duration: const Duration(milliseconds: 1000),
  )..repeat();

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AnimatedBuilder(
      animation: _controller,
      builder: (context, _) {
        return Row(
          mainAxisAlignment: MainAxisAlignment.center,
          children: List.generate(3, (index) {
            final phase = (_controller.value + index * 0.2) % 1.0;
            final scale = 0.6 + 0.4 * math.sin(phase * math.pi);
            return Padding(
              padding: const EdgeInsets.symmetric(horizontal: 4),
              child: Transform.scale(
                scale: scale,
                child: Container(
                  width: 9,
                  height: 9,
                  decoration: const BoxDecoration(
                    color: Color(0xFFD77B9E),
                    shape: BoxShape.circle,
                  ),
                ),
              ),
            );
          }),
        );
      },
    );
  }
}
