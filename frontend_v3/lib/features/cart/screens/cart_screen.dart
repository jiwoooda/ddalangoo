import 'package:flutter/material.dart';

import '../../../app/theme/app_colors.dart';
import '../../../app/theme/app_radii.dart';
import '../../../app/theme/app_spacing.dart';
import '../../../app/theme/app_text_styles.dart';
import '../../../core/storage/local_storage.dart';
import '../../../data/models/cart_model.dart';
import '../../../data/repositories/agent_repository.dart';
import '../../../data/repositories/cart_repository.dart';
import '../../../shared/layout/layout_presets.dart';
import '../../../shared/layout/screen_frame.dart';
import '../../../shared/widgets/primary_button.dart';
import '../../shopping/models/shopping_flow_models.dart';
import '../../shopping/services/shopping_flow_service.dart';

class CartScreen extends StatefulWidget {
  const CartScreen({super.key});

  @override
  State<CartScreen> createState() => _CartScreenState();
}

class _CartScreenState extends State<CartScreen> {
  final CartRepository _cartRepository = CartRepository();
  final UserRepository _userRepository = UserRepository();
  final ShoppingFlowService _shoppingFlowService = ShoppingFlowService();

  bool _isLoading = true;
  String? _errorMessage;
  String? _userName;
  CartResponse? _cart;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() {
      _isLoading = true;
      _errorMessage = null;
    });

    try {
      final userId = await LocalStorage.getUserId();
      if (userId == null) {
        throw Exception('로그인된 사용자를 찾을 수 없습니다.');
      }
      final results = await Future.wait<Object>([
        _cartRepository.getUserCart(userId),
        _userRepository.getUser(userId),
      ]);
      if (!mounted) {
        return;
      }
      setState(() {
        _cart = results[0] as CartResponse;
        _userName = (results[1] as dynamic).name as String?;
        _isLoading = false;
      });
    } catch (error) {
      if (!mounted) {
        return;
      }
      setState(() {
        _isLoading = false;
        _errorMessage = error.toString().replaceFirst('Exception: ', '');
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return ScreenFrame(
      preset: LayoutPreset.cartCompact,
      child: Column(
        children: [
          Row(
            children: [
              _BackButton(onPressed: () => Navigator.of(context).maybePop()),
              const Spacer(),
              Text(
                '장바구니 보기',
                style: AppTextStyles.body1.copyWith(
                  fontWeight: FontWeight.w800,
                ),
              ),
              const Spacer(),
              const SizedBox(width: 44),
            ],
          ),
          const SizedBox(height: AppSpacing.lg),
          Expanded(child: _buildBody()),
          const SizedBox(height: AppSpacing.lg),
          PrimaryButton(
            label: '새 쇼핑 시작하기',
            icon: Icons.shopping_bag_outlined,
            onPressed: () => Navigator.of(context).pop(),
          ),
        ],
      ),
    );
  }

  Widget _buildBody() {
    if (_isLoading) {
      return const Center(child: CircularProgressIndicator());
    }
    if (_errorMessage != null) {
      return _EmptyPanel(title: '장바구니를 불러오지 못했어요.', caption: _errorMessage!);
    }
    final cart = _cart;
    if (cart == null || cart.items.isEmpty) {
      return const _EmptyPanel(
        title: '장바구니가 비어 있어요.',
        caption: '상품을 담으면 이 화면에서 한눈에 볼 수 있어요.',
      );
    }

    final totalPrice = cart.items.fold<int>(
      0,
      (sum, item) => sum + item.totalPrice,
    );

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          _userName == null || _userName!.trim().isEmpty
              ? '현재 담긴 상품'
              : '${_userName!.trim()} 님의 장바구니',
          style: AppTextStyles.title2,
        ),
        const SizedBox(height: AppSpacing.sm),
        Text('${cart.items.length}개 상품이 담겨 있어요.', style: AppTextStyles.body2),
        const SizedBox(height: AppSpacing.lg),
        Expanded(
          child: ListView.separated(
            itemCount: cart.items.length,
            separatorBuilder: (_, _) => const SizedBox(height: AppSpacing.md),
            itemBuilder: (context, index) {
              final item = cart.items[index];
              return _CartItemCard(item: item, service: _shoppingFlowService);
            },
          ),
        ),
        const SizedBox(height: AppSpacing.lg),
        Container(
          width: double.infinity,
          padding: const EdgeInsets.all(AppSpacing.md),
          decoration: BoxDecoration(
            color: AppColors.surface,
            borderRadius: BorderRadius.circular(AppRadii.lg),
            border: Border.all(color: AppColors.border),
          ),
          child: Row(
            children: [
              Text(
                '총 금액',
                style: AppTextStyles.body1.copyWith(
                  fontWeight: FontWeight.w800,
                ),
              ),
              const Spacer(),
              Text(
                '${formatPrice(totalPrice)}원',
                style: AppTextStyles.title2.copyWith(
                  color: AppColors.primaryPinkDark,
                ),
              ),
            ],
          ),
        ),
      ],
    );
  }
}

class _BackButton extends StatelessWidget {
  const _BackButton({required this.onPressed});

  final VoidCallback onPressed;

  @override
  Widget build(BuildContext context) {
    return InkWell(
      onTap: onPressed,
      borderRadius: BorderRadius.circular(AppRadii.pill),
      child: Container(
        width: 44,
        height: 44,
        decoration: BoxDecoration(
          color: AppColors.surfaceMuted,
          borderRadius: BorderRadius.circular(AppRadii.pill),
          border: Border.all(color: AppColors.border),
        ),
        child: const Icon(
          Icons.arrow_back_ios_new_rounded,
          size: 18,
          color: AppColors.textPrimary,
        ),
      ),
    );
  }
}

class _EmptyPanel extends StatelessWidget {
  const _EmptyPanel({required this.title, required this.caption});

  final String title;
  final String caption;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Container(
        width: double.infinity,
        padding: const EdgeInsets.all(AppSpacing.cardPadding),
        decoration: BoxDecoration(
          color: Colors.white,
          borderRadius: BorderRadius.circular(AppRadii.xl),
          border: Border.all(color: AppColors.border),
        ),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Image.asset(
              'assets/images/character/full/ddalangoo_curious.png',
              height: 180,
              fit: BoxFit.contain,
            ),
            const SizedBox(height: AppSpacing.lg),
            Text(
              title,
              textAlign: TextAlign.center,
              style: AppTextStyles.body1.copyWith(fontWeight: FontWeight.w800),
            ),
            const SizedBox(height: AppSpacing.sm),
            Text(
              caption,
              textAlign: TextAlign.center,
              style: AppTextStyles.body2,
            ),
          ],
        ),
      ),
    );
  }
}

class _CartItemCard extends StatelessWidget {
  const _CartItemCard({required this.item, required this.service});

  final CartItemResponse item;
  final ShoppingFlowService service;

  @override
  Widget build(BuildContext context) {
    final previewAsset = service.assetForProductName(item.productName);
    return Container(
      padding: const EdgeInsets.all(AppSpacing.md),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(AppRadii.lg),
        border: Border.all(color: AppColors.border),
      ),
      child: Row(
        children: [
          ClipRRect(
            borderRadius: BorderRadius.circular(AppRadii.md),
            child: Container(
              width: 64,
              height: 64,
              color: previewAsset.backgroundColor,
              child: Image.asset(previewAsset.assetPath, fit: BoxFit.cover),
            ),
          ),
          const SizedBox(width: AppSpacing.md),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  item.productName,
                  style: AppTextStyles.body2.copyWith(
                    color: AppColors.textStrong,
                    fontWeight: FontWeight.w800,
                  ),
                ),
                if (item.optionText?.trim().isNotEmpty == true) ...[
                  const SizedBox(height: AppSpacing.xs),
                  Text(item.optionText!.trim(), style: AppTextStyles.caption),
                ],
                const SizedBox(height: AppSpacing.xs),
                Text(
                  '${formatPrice(item.unitPrice)}원 · ${item.quantity}개',
                  style: AppTextStyles.caption.copyWith(
                    color: AppColors.textMuted,
                    fontWeight: FontWeight.w700,
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(width: AppSpacing.sm),
          Text(
            '${formatPrice(item.totalPrice)}원',
            style: AppTextStyles.body2.copyWith(
              color: AppColors.primaryPinkDark,
              fontWeight: FontWeight.w800,
            ),
          ),
        ],
      ),
    );
  }
}
