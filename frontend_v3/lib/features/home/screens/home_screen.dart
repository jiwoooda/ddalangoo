import 'package:flutter/material.dart';

import '../../../app/routes.dart';
import '../../../app/theme/app_colors.dart';
import '../../../app/theme/app_radii.dart';
import '../../../app/theme/app_spacing.dart';
import '../../../app/theme/app_text_styles.dart';
import '../../../core/storage/local_storage.dart';
import '../../../data/repositories/agent_repository.dart';
import '../../../data/repositories/cart_repository.dart';
import '../../../shared/layout/bottom_cta_layout.dart';
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
      child: BottomCtaLayout(
        content: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Container(
                  width: 44,
                  height: 44,
                  decoration: BoxDecoration(
                    color: AppColors.surfaceMuted,
                    borderRadius: BorderRadius.circular(AppRadii.pill),
                    border: Border.all(color: AppColors.border),
                  ),
                  child: const Icon(
                    Icons.home_rounded,
                    color: AppColors.textMuted,
                  ),
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
            const SizedBox(height: AppSpacing.lg),
            DialogueBubble(
              text: _greetingText,
              highlightedWords: _userName == null ? ['딸랑구'] : [_userName!],
              style: AppTextStyles.body1,
            ),
            const SizedBox(height: AppSpacing.xl),
            Center(
              child: Image.asset(
                'assets/images/ddalangoo_happy.png',
                height: 240,
                fit: BoxFit.contain,
              ),
            ),
            const SizedBox(height: AppSpacing.xl),
            const Text('바로가기', style: AppTextStyles.title2),
            const SizedBox(height: AppSpacing.md),
            Row(
              children: [
                Expanded(
                  child: _ShortcutCard(
                    icon: Icons.shopping_cart_outlined,
                    title: '장바구니 보기',
                    subtitle: _isLoading ? '불러오는 중...' : '$_cartCount개 담겨 있어요',
                    backgroundColor: AppColors.secondaryPink,
                    onTap: () =>
                        Navigator.of(context).pushNamed(AppRoutes.cart),
                  ),
                ),
                const SizedBox(width: AppSpacing.md),
                Expanded(
                  child: _ShortcutCard(
                    icon: Icons.receipt_long_outlined,
                    title: '지난 주문 내역',
                    subtitle: '구매 이력을 다시 불러와요',
                    backgroundColor: const Color(0xFFFFF0C7),
                    onTap: () {
                      Navigator.of(
                        context,
                      ).pushReplacementNamed(AppRoutes.purchaseHistoryLoading);
                    },
                  ),
                ),
              ],
            ),
          ],
        ),
        cta: PrimaryButton(
          label: '딸랑구야 도와줘!',
          icon: Icons.phone_in_talk_rounded,
          onPressed: () {
            Navigator.of(context).pushNamed(AppRoutes.flowEntry);
          },
        ),
      ),
    );
  }
}

class _ShortcutCard extends StatelessWidget {
  const _ShortcutCard({
    required this.icon,
    required this.title,
    required this.subtitle,
    required this.backgroundColor,
    this.onTap,
  });

  final IconData icon;
  final String title;
  final String subtitle;
  final Color backgroundColor;
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
            color: backgroundColor,
            borderRadius: BorderRadius.circular(AppRadii.lg),
            border: Border.all(color: AppColors.border),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Icon(icon, color: AppColors.textStrong, size: 28),
              const SizedBox(height: AppSpacing.lg),
              Text(
                title,
                style: AppTextStyles.body1.copyWith(
                  fontWeight: FontWeight.w700,
                ),
              ),
              const SizedBox(height: AppSpacing.xs),
              Text(subtitle, style: AppTextStyles.caption),
            ],
          ),
        ),
      ),
    );
  }
}
