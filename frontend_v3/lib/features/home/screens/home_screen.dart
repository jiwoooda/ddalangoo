import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';

import '../../../app/routes.dart';
import '../../../app/theme/app_colors.dart';
import '../../../app/theme/app_radii.dart';
import '../../../app/theme/app_spacing.dart';
import '../../../app/theme/app_text_styles.dart';
import '../../../core/storage/local_storage.dart';
import '../../../data/repositories/agent_repository.dart';
import '../../../data/repositories/cart_repository.dart';
import '../../../shared/layout/layout_presets.dart';
import '../../../shared/layout/screen_frame.dart';
import '../../../shared/widgets/dialogue_bubble.dart';
import '../../../shared/widgets/primary_button.dart';

class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key});

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  final UserRepository _userRepository = UserRepository();
  final CartRepository _cartRepository = CartRepository();

  String? _userName;
  int _cartCount = 0;
  bool _isLoading = true;

  @override
  void initState() {
    super.initState();
    _loadHomeData();
  }

  Future<void> _loadHomeData() async {
    try {
      final userId = await LocalStorage.getUserId();
      if (userId == null) {
        if (!mounted) {
          return;
        }
        setState(() => _isLoading = false);
        return;
      }

      final results = await Future.wait<Object>([
        _userRepository.getUser(userId),
        _cartRepository.getUserCart(userId),
      ]);
      if (!mounted) {
        return;
      }

      final user = results[0] as dynamic;
      final cart = results[1] as dynamic;
      setState(() {
        _userName = user.name as String?;
        _cartCount = cart.items.length as int;
        _isLoading = false;
      });
    } catch (_) {
      if (!mounted) {
        return;
      }
      setState(() => _isLoading = false);
    }
  }

  Future<void> _logout() async {
    await LocalStorage.clearUserId();
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
    return ScreenFrame(
      preset: LayoutPreset.standard,
      child: LayoutBuilder(
        builder: (context, constraints) {
          return Column(
            children: [
              Expanded(
                child: LayoutBuilder(
                  builder: (context, contentConstraints) {
                    final compact = contentConstraints.maxHeight < 820;
                    final imageHeight = compact ? 188.0 : 252.0;
                    final sectionGap = compact ? AppSpacing.md : AppSpacing.xl;
                    final headerGap = compact ? AppSpacing.sm : AppSpacing.lg;
                    final shortcutAspectRatio = compact ? 1.02 : 0.94;
                    final useSingleColumnShortcuts =
                        contentConstraints.maxWidth < 320;

                    Widget buildShortcutCard({
                      required IconData icon,
                      required String title,
                      required String subtitle,
                      required VoidCallback onTap,
                    }) {
                      return AspectRatio(
                        aspectRatio: shortcutAspectRatio,
                        child: _ShortcutCard(
                          icon: icon,
                          title: title,
                          subtitle: subtitle,
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
                                children: [
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
                                  fontSize: compact ? 22 : 25,
                                  height: 1.32,
                                  fontWeight: FontWeight.w600,
                                  color: AppColors.textPrimary,
                                ),
                                emphasizedStyle: AppTextStyles.title2.copyWith(
                                  fontSize: compact ? 22 : 25,
                                  height: 1.32,
                                  fontWeight: FontWeight.w800,
                                  color: AppColors.primaryPinkDark,
                                ),
                              ),
                              SizedBox(height: sectionGap),
                              Center(
                                child: Image.asset(
                                  'assets/images/character/top/ddalangoo_greeting.png',
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
                                bottom: compact ? AppSpacing.sm : AppSpacing.md,
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
                                        style: AppTextStyles.title2.copyWith(
                                          color: AppColors.primaryPinkDark,
                                          fontWeight: FontWeight.w800,
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
                                          subtitle: _isLoading
                                              ? '불러오는 중...'
                                              : '$_cartCount개 담겨 있어요',
                                          onTap: () => Navigator.of(
                                            context,
                                          ).pushNamed(AppRoutes.cart),
                                        ),
                                        const SizedBox(height: AppSpacing.md),
                                        buildShortcutCard(
                                          icon: Icons.receipt_long_outlined,
                                          title: '지난 주문 내역',
                                          subtitle: '구매 이력을 다시 불러와요',
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
                                            subtitle: _isLoading
                                                ? '불러오는 중...'
                                                : '$_cartCount개 담겨 있어요',
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
                                            subtitle: '구매 이력을 다시 불러와요',
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
              const SizedBox(height: AppSpacing.lg),
              PrimaryButton(
                label: '딸랑구야 도와줘!',
                icon: Icons.phone_in_talk_rounded,
                onPressed: () {
                  Navigator.of(context).pushNamed(AppRoutes.flowEntry);
                },
              ),
              if (kDebugMode) ...[
                const SizedBox(height: AppSpacing.sm),
                TextButton(
                  onPressed: () {
                    Navigator.of(context).pushNamed(AppRoutes.flowEntryMock);
                  },
                  child: Text(
                    'mock-data 흐름 보기',
                    style: AppTextStyles.body2.copyWith(
                      color: AppColors.primaryPinkDark,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                ),
              ],
            ],
          );
        },
      ),
    );
  }
}

class _ShortcutCard extends StatelessWidget {
  const _ShortcutCard({
    required this.icon,
    required this.title,
    required this.subtitle,
    this.onTap,
  });

  final IconData icon;
  final String title;
  final String subtitle;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    return Material(
      color: Colors.transparent,
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(AppRadii.lg),
        child: Container(
          padding: const EdgeInsets.all(AppSpacing.md),
          decoration: BoxDecoration(
            color: Colors.white,
            borderRadius: BorderRadius.circular(AppRadii.lg),
            border: Border.all(color: AppColors.border),
            boxShadow: const [
              BoxShadow(
                color: AppColors.shadow,
                blurRadius: 18,
                offset: Offset(0, 8),
              ),
            ],
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Icon(icon, color: AppColors.primaryPinkDark, size: 28),
              const SizedBox(height: AppSpacing.xl),
              Text(
                title,
                maxLines: 2,
                overflow: TextOverflow.ellipsis,
                style: AppTextStyles.body1.copyWith(
                  color: AppColors.primaryPinkDark,
                  fontWeight: FontWeight.w700,
                ),
              ),
              const SizedBox(height: AppSpacing.xs),
              Text(
                subtitle,
                maxLines: 2,
                overflow: TextOverflow.ellipsis,
                style: AppTextStyles.caption,
              ),
              const Spacer(),
            ],
          ),
        ),
      ),
    );
  }
}
