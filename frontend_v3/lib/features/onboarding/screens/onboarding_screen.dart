import 'dart:async';

import 'package:flutter/material.dart';

import '../../../app/routes.dart';
import '../../../app/theme/app_colors.dart';
import '../../../app/theme/app_radii.dart';
import '../../../app/theme/app_spacing.dart';
import '../../../app/theme/app_surface_styles.dart';
import '../../../app/theme/app_text_styles.dart';
import '../../../core/services/accessibility_automation_service.dart';
import '../../../shared/layout/app_responsive.dart';
import '../../shopping/screens/smalltalk_screen.dart';
import '../../../shared/layout/bottom_cta_layout.dart';
import '../../../shared/layout/layout_presets.dart';
import '../../../shared/layout/screen_frame.dart';
import '../../../shared/widgets/primary_button.dart';
import '../widgets/onboarding_indicator.dart';
import '../widgets/onboarding_page_card.dart';

class OnboardingScreen extends StatefulWidget {
  const OnboardingScreen({super.key, this.useMockFlow = false});

  final bool useMockFlow;

  @override
  State<OnboardingScreen> createState() => _OnboardingScreenState();
}

class _OnboardingScreenState extends State<OnboardingScreen>
    with WidgetsBindingObserver {
  late final PageController _pageController = PageController();
  final AccessibilityAutomationService _accessibilityService =
      AccessibilityAutomationService.instance;

  int _currentIndex = 0;
  bool _isAccessibilityEnabled = false;
  bool _accessibilitySettingsOpened = false;

  // "이제 딸랑구와 함께 편하게 쇼핑해보세요" 페이지를 접근성 권한 페이지보다
  // 앞에 두고, 접근성 권한 페이지를 맨 마지막으로 옮겼다. 이제 "시작하기"는
  // (isStartPage) 다음 페이지(접근성 권한)로 넘어가기만 하고, 실제 앱
  // 진입은 접근성 권한이 켜졌을 때(마지막 페이지) 일어난다.
  static const _pages = [
    _OnboardingPageData(
      title: '전화하듯 말만 하면 돼요',
      assetPath: 'assets/images/character/full/ddalangoo_calling.png',
      bubbleText: '딸기 사줘',
    ),
    _OnboardingPageData(
      title: '복잡한 결제도 걱정 마세요',
      assetPath: 'assets/images/character/full/ddalangoo_cheerful.png',
      trailingTags: ['주문 완료', '결제 승인'],
    ),
    _OnboardingPageData(
      title: '이제 딸랑구와 함께\n편하게 쇼핑해보세요',
      assetPath: 'assets/images/character/full/ddalangoo_happy.png',
      bubbleText: '신규 가입자라면 시작하기를 눌러보세요!',
      compactBubble: true,
      isStartPage: true,
    ),
    _OnboardingPageData(
      title: '자동 주문을 위해\n접근성 권한이 필요해요',
      assetPath: 'assets/images/character/full/ddalangoo_standing.png',
      description: '쇼핑 앱에서 상품을 담고 결제까지 대신 하려면\n화면을 읽고 대신 눌러줄 접근성 권한이 필요해요.',
      isAccessibilityPage: true,
    ),
  ];

  bool get _isLastPage => _currentIndex == _pages.length - 1;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    unawaited(_refreshAccessibilityStatus());
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _pageController.dispose();
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    // 사용자가 시스템 접근성 설정 화면을 갔다가 앱으로 돌아오는 시점(resumed)에
    // 실제로 권한을 켰는지 다시 확인한다. setAutomationTask 같은 다른 흐름과
    // 달리 이건 순수 OS 설정값 조회라 폴링 대신 lifecycle 이벤트로 충분하다.
    if (state == AppLifecycleState.resumed && _accessibilitySettingsOpened) {
      unawaited(_refreshAccessibilityStatus());
    }
  }

  int get _accessibilityPageIndex =>
      _pages.indexWhere((page) => page.isAccessibilityPage);

  Future<void> _refreshAccessibilityStatus() async {
    if (widget.useMockFlow) {
      return;
    }
    final enabled = await _accessibilityService.isAccessibilityServiceEnabled();
    if (!mounted) {
      return;
    }
    final wasEnabled = _isAccessibilityEnabled;
    setState(() => _isAccessibilityEnabled = enabled);
    _advanceIfJustEnabled(wasEnabled: wasEnabled);
  }

  /// 접근성 권한은 필수라 건너뛰기 버튼이 없다 — 권한이 막 켜진 걸 확인하면
  /// 사용자가 따로 누를 것 없이 자동으로 다음으로 넘어간다. 접근성 페이지가
  /// 이제 마지막 페이지라 "다음"은 곧 온보딩을 마치고 앱으로 들어가는 것이다.
  void _advanceIfJustEnabled({required bool wasEnabled}) {
    if (wasEnabled || !_isAccessibilityEnabled) {
      return;
    }
    if (_currentIndex != _accessibilityPageIndex) {
      return;
    }
    Future.delayed(const Duration(milliseconds: 500), () {
      if (!mounted || _currentIndex != _accessibilityPageIndex) {
        return;
      }
      if (_isLastPage) {
        _enterApp();
      } else {
        _goToNextPage();
      }
    });
  }

  Future<void> _handleOpenAccessibilitySettings() async {
    _accessibilitySettingsOpened = true;
    if (widget.useMockFlow) {
      final wasEnabled = _isAccessibilityEnabled;
      setState(() => _isAccessibilityEnabled = true);
      _advanceIfJustEnabled(wasEnabled: wasEnabled);
      return;
    }
    await _accessibilityService.openAccessibilitySettings();
  }

  /// 접근성 권한을 켜기 전엔 그 페이지를 통과할 수 없어야 한다. [_pageScrollPhysics]가
  /// 접근성 페이지에 머무는 동안 스와이프 자체를 막아 대부분의 경우를 원천 차단하고,
  /// 이 핸들러는 그 물리 규칙이 걸리기 전에 여러 페이지를 한 번에 넘기는 등의
  /// 예외 케이스에 대한 보조 안전장치로 남겨둔다.
  void _handlePageChanged(int index) {
    if (_currentIndex == index) return;
    if (!_isAccessibilityEnabled &&
        !widget.useMockFlow &&
        _accessibilityPageIndex != -1 &&
        index > _accessibilityPageIndex) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted) {
          _pageController.jumpToPage(_accessibilityPageIndex);
        }
      });
      return;
    }
    setState(() => _currentIndex = index);
  }

  /// 접근성 권한이 필요한 페이지에 머무르는 동안(그리고 권한이 꺼져있는 동안)엔
  /// 스와이프 자체를 비활성화해 "다음 화면으로 못 넘어가는" 상태를 물리적으로
  /// 강제한다. 권한이 켜지면 즉시 일반 스와이프 물리로 되돌아간다(양방향 모두).
  ScrollPhysics get _pageScrollPhysics {
    final blocked =
        !_isAccessibilityEnabled &&
        !widget.useMockFlow &&
        _currentIndex == _accessibilityPageIndex;
    return blocked
        ? const NeverScrollableScrollPhysics()
        : const ClampingScrollPhysics();
  }

  void _goToNextPage() {
    _pageController.nextPage(
      duration: const Duration(milliseconds: 260),
      curve: Curves.easeOutCubic,
    );
  }

  // "시작하기"는 앱을 완전히 빠져나가지 않고 다음 페이지(접근성 권한)로만
  // 넘어간다. 실제 앱 진입은 접근성 권한이 켜졌을 때 _enterApp()이 담당한다.
  void _handleStartPressed() {
    _goToNextPage();
  }

  void _enterApp() {
    if (widget.useMockFlow) {
      Navigator.of(context).pushReplacement(
        MaterialPageRoute<void>(
          builder: (_) => const SmallTalkScreen(useMockFlow: true),
        ),
      );
      return;
    }

    Navigator.of(context).pushReplacementNamed(AppRoutes.smallTalk);
  }

  @override
  Widget build(BuildContext context) {
    return ScreenFrame(
      preset: LayoutPreset.onboarding,
      child: BottomCtaLayout(
        content: Column(
          children: [
            // 페이지 인디케이터(점)를 캐릭터 아래가 아니라 화면 맨 위로
            // 옮겨서, 항상 진행 상황이 한눈에 보이도록 했다.
            OnboardingIndicator(
              count: _pages.length,
              currentIndex: _currentIndex,
            ),
            const SizedBox(height: AppSpacing.lg),
            Expanded(
              child: PageView.builder(
                controller: _pageController,
                physics: _pageScrollPhysics,
                itemCount: _pages.length,
                onPageChanged: _handlePageChanged,
                itemBuilder: (context, index) {
                  final page = _pages[index];
                  return OnboardingPageCard(
                    title: page.title,
                    assetPath: page.assetPath,
                    bubbleText: page.bubbleText,
                    compactBubble: page.compactBubble,
                    trailingTags: page.trailingTags,
                    description: page.description,
                    footer: page.isAccessibilityPage
                        ? _AccessibilityPermissionCta(
                            isEnabled: _isAccessibilityEnabled,
                            onOpenSettings: _handleOpenAccessibilitySettings,
                          )
                        : null,
                  );
                },
              ),
            ),
          ],
        ),
        cta: AnimatedSwitcher(
          duration: const Duration(milliseconds: 220),
          switchInCurve: Curves.easeOutCubic,
          switchOutCurve: Curves.easeInCubic,
          child: _pages[_currentIndex].isStartPage
              ? Column(
                  key: const ValueKey('start-button'),
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    PrimaryButton(
                      label: '시작하기',
                      onPressed: _handleStartPressed,
                    ),
                    const SizedBox(height: AppSpacing.sm),
                    TextButton(
                      onPressed: () {
                        Navigator.of(context).pushNamed(AppRoutes.login);
                      },
                      child: const Text('이미 계정이 있어요'),
                    ),
                  ],
                )
              : const SizedBox(key: ValueKey('empty-button-slot'), height: 56),
        ),
      ),
    );
  }
}

/// 접근성 권한은 필수라 건너뛰기/나중에 옵션이 없다 — 켜기 전엔 버튼 하나뿐이고,
/// 켜지면(부모의 [_advanceIfJustEnabled]가) 사용자가 따로 누를 것 없이 자동으로
/// 다음 페이지로 넘어간다. 이 위젯은 그 전환 직전 짧은 순간의 확인 표시만 보여준다.
class _AccessibilityPermissionCta extends StatelessWidget {
  const _AccessibilityPermissionCta({
    super.key,
    required this.isEnabled,
    required this.onOpenSettings,
  });

  final bool isEnabled;
  final VoidCallback onOpenSettings;

  @override
  Widget build(BuildContext context) {
    if (isEnabled) {
      return Row(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          const Icon(
            Icons.check_circle_rounded,
            color: AppColors.success,
            size: 18,
          ),
          const SizedBox(width: AppSpacing.xs),
          Text(
            '접근성 권한이 켜졌어요',
            style: AppTextStyles.body2.copyWith(
              color: AppColors.success,
              fontWeight: FontWeight.w700,
            ),
          ),
        ],
      );
    }

    return _TallAccessibilityButton(onPressed: onOpenSettings);
  }
}

/// 기본 [PrimaryButton]은 가로로 꽉 찬 형태라, 캐릭터와 제목 텍스트 사이의
/// 좁은 공간에 놓기엔 너무 넓다. 세로로 길고 가로로 좁은 전용 버튼 모양을
/// 별도로 만들어 방패 아이콘 + 2줄 라벨("접근성" / "허용하기")을 담는다.
class _TallAccessibilityButton extends StatelessWidget {
  const _TallAccessibilityButton({required this.onPressed});

  final VoidCallback onPressed;

  @override
  Widget build(BuildContext context) {
    final responsive = context.responsive;
    final width = responsive.bound(
      responsive.widthScaled(148, minFactor: 0.85, maxFactor: 1.0),
      min: 120,
      max: 160,
    );
    final height = responsive.bound(
      responsive.heightScaled(96, minFactor: 0.85, maxFactor: 1.0),
      min: 84,
      max: 104,
    );

    // 진한 핑크 배경 + 흰 글씨(FilledButton 기본 스타일)는 눈에 잘 안 띄고
    // 버튼처럼 안 느껴진다는 피드백을 반영해, 앱 전반의 칩 스타일과 같은
    // 연핑크 배경 + 진한 핑크 글씨로 바꾸고 그림자를 더해 버튼 느낌을 살렸다.
    return SizedBox(
      width: width,
      height: height,
      child: Material(
        color: AppColors.secondaryPink,
        borderRadius: BorderRadius.circular(AppRadii.lg),
        elevation: AppSurfaceStyles.compactButtonElevation,
        shadowColor: AppSurfaceStyles.buttonShadowColor,
        child: InkWell(
          onTap: onPressed,
          borderRadius: BorderRadius.circular(AppRadii.lg),
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              const Icon(
                Icons.shield_rounded,
                color: AppColors.primaryPinkDark,
                size: 22,
              ),
              const SizedBox(height: 4),
              Text(
                '접근성\n허용하기',
                textAlign: TextAlign.center,
                style: AppTextStyles.button.copyWith(
                  height: 1.25,
                  color: AppColors.primaryPinkDark,
                  fontWeight: FontWeight.w800,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _OnboardingPageData {
  const _OnboardingPageData({
    required this.title,
    required this.assetPath,
    this.bubbleText,
    this.compactBubble = false,
    this.trailingTags = const <String>[],
    this.description,
    this.isAccessibilityPage = false,
    this.isStartPage = false,
  });

  final String title;
  final String assetPath;
  final String? bubbleText;
  final bool compactBubble;
  final List<String> trailingTags;
  final String? description;
  final bool isAccessibilityPage;

  /// 하단에 "시작하기" 버튼을 보여주는 페이지인지 여부. 이 버튼은 앱을
  /// 완전히 빠져나가지 않고 다음 페이지(접근성 권한)로만 넘어간다.
  final bool isStartPage;
}
