import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';

import '../../../app/routes.dart';
import '../../../app/theme/app_colors.dart';
import '../../../app/theme/app_radii.dart';
import '../../../app/theme/app_spacing.dart';
import '../../../app/theme/app_surface_styles.dart';
import '../../../app/theme/app_text_styles.dart';
import '../../../core/storage/local_storage.dart';
import '../../../data/repositories/agent_repository.dart';
import '../../../shared/layout/layout_presets.dart';
import '../../../shared/layout/screen_frame.dart';
import '../../../shared/layout/app_responsive.dart';
import '../../../shared/widgets/dialogue_bubble.dart';
import '../../../shared/widgets/primary_button.dart';

class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key});

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  final UserRepository _userRepository = UserRepository();
  static const Color _temporaryDebugColor = Color(0xFF1E9E4A);

  String? _userName;

  @override
  void initState() {
    super.initState();
    _loadHomeData();
  }

  Future<void> _loadHomeData() async {
    try {
      final cachedUserName = await LocalStorage.getUserName();
      if (mounted &&
          cachedUserName != null &&
          cachedUserName.trim().isNotEmpty) {
        setState(() {
          _userName = cachedUserName.trim();
        });
      }

      final userId = await LocalStorage.getUserId();
      if (userId == null) {
        return;
      }

      final results = await Future.wait<Object>([
        _userRepository.getUser(userId),
      ]);
      if (!mounted) {
        return;
      }

      final user = results[0] as dynamic;
      setState(() {
        _userName = user.name as String?;
      });
    } catch (_) {
      // Home data is best-effort; keep the default greeting on failure.
    }
  }

  Future<void> _logout() async {
    await LocalStorage.clearSession();
    if (!mounted) {
      return;
    }
    Navigator.of(
      context,
    ).pushNamedAndRemoveUntil(AppRoutes.login, (route) => false);
  }

  String get _greetingText {
    final trimmed = _userName?.trim();
    if (trimmed == null || trimmed.isEmpty) {
      return '안녕하세요! 저는 딸랑구예요 :)\n오늘도 반갑게 인사하러 왔어요!';
    }
    return '$trimmed님, 안녕하세요!\n오늘도 딸랑구가 쇼핑을 도와드릴게요.';
  }

  @override
  Widget build(BuildContext context) {
    final responsive = context.responsive;

    return ScreenFrame(
      preset: LayoutPreset.standard,
      child: LayoutBuilder(
        builder: (context, constraints) {
          return Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Expanded(
                child: LayoutBuilder(
                  builder: (context, contentConstraints) {
                    final compact =
                        contentConstraints.maxHeight < 820 ||
                        responsive.usesCondensedLayout;
                    final imageHeight = responsive.bound(
                      responsive.heightScaled(
                        compact ? 236 : 300,
                        minFactor: 0.8,
                        maxFactor: 1.0,
                      ),
                      min: 210,
                      max: 300,
                    );
                    final sectionGap = responsive.bound(
                      responsive.heightScaled(
                        compact ? AppSpacing.md : AppSpacing.xl,
                        minFactor: 0.72,
                        maxFactor: 1.0,
                      ),
                      min: AppSpacing.sm,
                      max: AppSpacing.xl,
                    );
                    final headerGap = responsive.bound(
                      responsive.heightScaled(
                        compact ? AppSpacing.sm : AppSpacing.lg,
                        minFactor: 0.72,
                        maxFactor: 1.0,
                      ),
                      min: AppSpacing.xs,
                      max: AppSpacing.lg,
                    );
                    final shortcutHeight = responsive.bound(
                      responsive.heightScaled(
                        compact ? 116 : 128,
                        minFactor: 0.84,
                        maxFactor: 1.0,
                      ),
                      min: 104,
                      max: 128,
                    );
                    final useSingleColumnShortcuts =
                        contentConstraints.maxWidth < 340;

                    Widget buildShortcutCard({
                      required IconData icon,
                      required String title,
                      required VoidCallback onTap,
                    }) {
                      return SizedBox(
                        height: shortcutHeight,
                        child: _ShortcutCard(
                          icon: icon,
                          title: title,
                          onTap: onTap,
                        ),
                      );
                    }

                    return CustomScrollView(
                      physics: const ClampingScrollPhysics(),
                      slivers: [
                        SliverToBoxAdapter(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Row(
                                crossAxisAlignment: CrossAxisAlignment.start,
                                children: [
                                  if (kDebugMode)
                                    Column(
                                      crossAxisAlignment:
                                          CrossAxisAlignment.start,
                                      children: [
                                        TextButton(
                                          onPressed: () {
                                            Navigator.of(
                                              context,
                                            ).pushNamedAndRemoveUntil(
                                              AppRoutes.splashMock,
                                              (route) => false,
                                            );
                                          },
                                          style: TextButton.styleFrom(
                                            padding: const EdgeInsets.symmetric(
                                              horizontal: AppSpacing.xs,
                                              vertical: AppSpacing.xxs,
                                            ),
                                            minimumSize: Size.zero,
                                            tapTargetSize: MaterialTapTargetSize
                                                .shrinkWrap,
                                          ),
                                          child: Text(
                                            'mock 첫 흐름 보기',
                                            style: AppTextStyles.caption
                                                .copyWith(
                                                  color: _temporaryDebugColor,
                                                  fontWeight: FontWeight.w800,
                                                ),
                                          ),
                                        ),
                                        TextButton(
                                          onPressed: () {
                                            Navigator.of(context).pushNamed(
                                              AppRoutes.flowEntryMock,
                                            );
                                          },
                                          style: TextButton.styleFrom(
                                            padding: const EdgeInsets.symmetric(
                                              horizontal: AppSpacing.xs,
                                              vertical: AppSpacing.xxs,
                                            ),
                                            minimumSize: Size.zero,
                                            tapTargetSize: MaterialTapTargetSize
                                                .shrinkWrap,
                                          ),
                                          child: Text(
                                            'mock 쇼핑 흐름 보기',
                                            style: AppTextStyles.caption
                                                .copyWith(
                                                  color: _temporaryDebugColor,
                                                  fontWeight: FontWeight.w800,
                                                ),
                                          ),
                                        ),
                                      ],
                                    ),
                                  const Spacer(),
                                  TextButton(
                                    onPressed: _logout,
                                    child: Text(
                                      '로그아웃',
                                      style: AppTextStyles.body2.copyWith(
                                        color: AppColors.primaryPinkDark,
                                        fontWeight: FontWeight.w800,
                                      ),
                                    ),
                                  ),
                                ],
                              ),
                              SizedBox(height: headerGap),
                              DialogueBubble(
                                text: _greetingText,
                                highlightedWords: _userName == null
                                    ? ['딸랑구']
                                    : [_userName!],
                                style: AppTextStyles.title2.copyWith(
                                  fontSize: responsive.bound(
                                    responsive.font(compact ? 22 : 25),
                                    min: 21,
                                    max: 25,
                                  ),
                                  height: 1.32,
                                  fontWeight: FontWeight.w600,
                                  color: AppColors.textPrimary,
                                ),
                                emphasizedStyle: AppTextStyles.title2.copyWith(
                                  fontSize: responsive.bound(
                                    responsive.font(compact ? 22 : 25),
                                    min: 21,
                                    max: 25,
                                  ),
                                  height: 1.32,
                                  fontWeight: FontWeight.w800,
                                  color: AppColors.primaryPinkDark,
                                ),
                              ),
                              SizedBox(height: sectionGap),
                              Center(
                                child: Image.asset(
                                  'assets/images/character/top/ddalangoo_greeting_top.png',
                                  height: imageHeight,
                                  fit: BoxFit.contain,
                                ),
                              ),
                            ],
                          ),
                        ),
                        SliverFillRemaining(
                          hasScrollBody: false,
                          fillOverscroll: true,
                          child: Align(
                            alignment: Alignment.bottomLeft,
                            child: Padding(
                              padding: EdgeInsets.only(
                                top: sectionGap,
                                bottom: responsive.bound(
                                  responsive.heightScaled(
                                    compact ? AppSpacing.lg : AppSpacing.xl,
                                    minFactor: 0.76,
                                    maxFactor: 1.0,
                                  ),
                                  min: AppSpacing.md,
                                  max: AppSpacing.xl,
                                ),
                              ),
                              child: Column(
                                mainAxisSize: MainAxisSize.min,
                                crossAxisAlignment: CrossAxisAlignment.start,
                                children: [
                                  Row(
                                    mainAxisSize: MainAxisSize.min,
                                    children: [
                                      Container(
                                        width: 10,
                                        height: 10,
                                        decoration: const BoxDecoration(
                                          color: AppColors.primaryPink,
                                          shape: BoxShape.circle,
                                        ),
                                      ),
                                      const SizedBox(width: AppSpacing.xs),
                                      Text(
                                        '바로가기',
                                        style: AppTextStyles.body1.copyWith(
                                          color: AppColors.primaryPinkDark,
                                          fontWeight: FontWeight.w700,
                                          height: 1.25,
                                        ),
                                      ),
                                    ],
                                  ),
                                  const SizedBox(height: AppSpacing.md),
                                  if (useSingleColumnShortcuts)
                                    Column(
                                      children: [
                                        buildShortcutCard(
                                          icon: Icons.shopping_cart_outlined,
                                          title: '장바구니 보기',
                                          onTap: () => Navigator.of(
                                            context,
                                          ).pushNamed(AppRoutes.cart),
                                        ),
                                        const SizedBox(height: AppSpacing.md),
                                        buildShortcutCard(
                                          icon: Icons.receipt_long_outlined,
                                          title: '지난 주문 내역',
                                          onTap: () {
                                            Navigator.of(
                                              context,
                                            ).pushReplacementNamed(
                                              AppRoutes.purchaseHistoryLoading,
                                            );
                                          },
                                        ),
                                      ],
                                    )
                                  else
                                    Row(
                                      children: [
                                        Expanded(
                                          child: buildShortcutCard(
                                            icon: Icons.shopping_cart_outlined,
                                            title: '장바구니 보기',
                                            onTap: () => Navigator.of(
                                              context,
                                            ).pushNamed(AppRoutes.cart),
                                          ),
                                        ),
                                        const SizedBox(width: AppSpacing.md),
                                        Expanded(
                                          child: buildShortcutCard(
                                            icon: Icons.receipt_long_outlined,
                                            title: '지난 주문 내역',
                                            onTap: () {
                                              Navigator.of(
                                                context,
                                              ).pushReplacementNamed(
                                                AppRoutes
                                                    .purchaseHistoryLoading,
                                              );
                                            },
                                          ),
                                        ),
                                      ],
                                    ),
                                ],
                              ),
                            ),
                          ),
                        ),
                      ],
                    );
                  },
                ),
              ),
              SizedBox(
                height: responsive.bound(
                  responsive.heightScaled(
                    AppSpacing.lg,
                    minFactor: 0.72,
                    maxFactor: 1.0,
                  ),
                  min: AppSpacing.sm,
                  max: AppSpacing.lg,
                ),
              ),
              Text(
                '딸랑구를 불러보세요!',
                textAlign: TextAlign.center,
                style: AppTextStyles.body2.copyWith(
                  color: AppColors.textMuted,
                  fontWeight: FontWeight.w600,
                  fontSize: responsive.font(
                    16,
                    minFactor: 0.94,
                    maxFactor: 1.0,
                  ),
                ),
              ),
              SizedBox(
                height: responsive.bound(
                  responsive.heightScaled(
                    AppSpacing.xs,
                    minFactor: 0.7,
                    maxFactor: 1.0,
                  ),
                  min: AppSpacing.xxs,
                  max: AppSpacing.xs,
                ),
              ),
              PrimaryButton(
                label: '딸랑구야 도와줘!',
                icon: Icons.phone_in_talk_rounded,
                onPressed: () {
                  Navigator.of(context).pushNamed(AppRoutes.flowEntry);
                },
              ),
            ],
          );
        },
      ),
    );
  }
}

class _ShortcutCard extends StatelessWidget {
  const _ShortcutCard({required this.icon, required this.title, this.onTap});

  final IconData icon;
  final String title;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    final responsive = context.responsive;

    return Material(
      color: Colors.transparent,
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(AppRadii.lg),
        child: Container(
          padding: EdgeInsets.all(
            responsive.bound(
              responsive.scale(AppSpacing.md, minFactor: 0.84, maxFactor: 1.0),
              min: AppSpacing.sm,
              max: AppSpacing.md,
            ),
          ),
          decoration: AppSurfaceStyles.elevatedCard(radius: AppRadii.lg),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              const Spacer(),
              Center(
                child: Icon(
                  icon,
                  color: AppColors.primaryPinkDark,
                  size: responsive.bound(
                    responsive.scale(30, minFactor: 0.86, maxFactor: 1.0),
                    min: 26,
                    max: 30,
                  ),
                ),
              ),
              const SizedBox(height: AppSpacing.md),
              Text(
                title,
                maxLines: 2,
                textAlign: TextAlign.center,
                style: AppTextStyles.body1.copyWith(
                  color: AppColors.primaryPinkDark,
                  fontWeight: FontWeight.w700,
                  height: 1.25,
                  fontSize: responsive.bound(
                    responsive.font(18, minFactor: 0.94, maxFactor: 1.0),
                    min: 16,
                    max: 18,
                  ),
                ),
              ),
              const Spacer(),
            ],
          ),
        ),
      ),
    );
  }
}
