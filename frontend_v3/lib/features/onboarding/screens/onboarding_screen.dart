import 'package:flutter/material.dart';

import '../../../app/routes.dart';
import '../../../app/theme/app_spacing.dart';
import '../../../shared/layout/bottom_cta_layout.dart';
import '../../../shared/layout/layout_presets.dart';
import '../../../shared/layout/screen_frame.dart';
import '../../../shared/widgets/primary_button.dart';
import '../widgets/onboarding_indicator.dart';
import '../widgets/onboarding_page_card.dart';

class OnboardingScreen extends StatefulWidget {
  const OnboardingScreen({super.key});

  @override
  State<OnboardingScreen> createState() => _OnboardingScreenState();
}

class _OnboardingScreenState extends State<OnboardingScreen> {
  late final PageController _pageController = PageController();

  int _currentIndex = 0;

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
    ),
  ];

  bool get _isLastPage => _currentIndex == _pages.length - 1;

  void _handlePageChanged(int index) {
    if (_currentIndex == index) return;
    setState(() => _currentIndex = index);
  }

  void _handleStartPressed() {
    Navigator.of(context).pushReplacementNamed(AppRoutes.smallTalk);
  }

  @override
  void dispose() {
    _pageController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return ScreenFrame(
      preset: LayoutPreset.onboarding,
      child: BottomCtaLayout(
        content: Column(
          children: [
            Expanded(
              child: PageView.builder(
                controller: _pageController,
                itemCount: _pages.length,
                onPageChanged: _handlePageChanged,
                itemBuilder: (context, index) {
                  final page = _pages[index];
                  return OnboardingPageCard(
                    title: page.title,
                    assetPath: page.assetPath,
                    bubbleText: page.bubbleText,
                    trailingTags: page.trailingTags,
                  );
                },
              ),
            ),
            const SizedBox(height: AppSpacing.lg),
            OnboardingIndicator(
              count: _pages.length,
              currentIndex: _currentIndex,
            ),
          ],
        ),
        cta: AnimatedSwitcher(
          duration: const Duration(milliseconds: 220),
          switchInCurve: Curves.easeOutCubic,
          switchOutCurve: Curves.easeInCubic,
          child: _isLastPage
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

class _OnboardingPageData {
  const _OnboardingPageData({
    required this.title,
    required this.assetPath,
    this.bubbleText,
    this.trailingTags = const <String>[],
  });

  final String title;
  final String assetPath;
  final String? bubbleText;
  final List<String> trailingTags;
}
