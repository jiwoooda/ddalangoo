import 'package:flutter/material.dart';

import '../models/shopping_v1_models.dart';
import 'glass_card.dart';

class ProductCard extends StatelessWidget {
  const ProductCard({super.key, required this.product});

  final ProductViewData product;

  @override
  Widget build(BuildContext context) {
    return GlassCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Container(
            width: double.infinity,
            padding: const EdgeInsets.only(bottom: 8),
            decoration: BoxDecoration(
              borderRadius: BorderRadius.circular(24),
              gradient: LinearGradient(
                colors: [
                  Colors.white.withValues(alpha: 0.36),
                  Colors.white.withValues(alpha: 0.08),
                ],
              ),
            ),
            child: ClipRRect(
              borderRadius: BorderRadius.circular(22),
              child: AspectRatio(
                aspectRatio: 1.18,
                child: product.imageUrl == null
                    ? _placeholder()
                    : Image.network(
                        product.imageUrl!,
                        fit: BoxFit.cover,
                        errorBuilder: (context, error, stackTrace) =>
                            _placeholder(),
                      ),
              ),
            ),
          ),
          const SizedBox(height: 18),
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
            decoration: BoxDecoration(
              color: const Color(0xFFFFECF4),
              borderRadius: BorderRadius.circular(999),
            ),
            child: Text(
              product.platform ?? '쇼핑 플랫폼',
              style: const TextStyle(
                fontFamily: 'Pretendard',
                fontSize: 14,
                fontWeight: FontWeight.w700,
                color: Color(0xFF2B3847),
              ),
            ),
          ),
          const SizedBox(height: 16),
          Text(
            product.title,
            style: const TextStyle(
              fontFamily: 'Pretendard',
              fontSize: 28,
              fontWeight: FontWeight.w800,
              color: Color(0xFF12202F),
              height: 1.3,
            ),
          ),
          if ((product.quantityInfo ?? '').isNotEmpty) ...[
            const SizedBox(height: 10),
            Text(
              product.quantityInfo!,
              style: const TextStyle(
                fontFamily: 'Pretendard',
                fontSize: 18,
                fontWeight: FontWeight.w600,
                color: Color(0xFF5C6A77),
              ),
            ),
          ],
          const SizedBox(height: 14),
          Text(
            product.displayPrice,
            style: const TextStyle(
              fontFamily: 'Pretendard',
              fontSize: 30,
              fontWeight: FontWeight.w900,
              color: Color(0xFFFF5B98),
            ),
          ),
          if ((product.badgeText ?? '').isNotEmpty) ...[
            const SizedBox(height: 12),
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
              decoration: BoxDecoration(
                color: const Color(0xFFFFF0F6),
                borderRadius: BorderRadius.circular(18),
                border: Border.all(color: const Color(0xFFFFD6E4)),
              ),
              child: Text(
                product.badgeText!,
                style: const TextStyle(
                  fontFamily: 'Pretendard',
                  fontSize: 16,
                  fontWeight: FontWeight.w600,
                  color: Color(0xFF334152),
                  height: 1.45,
                ),
              ),
            ),
          ],
          if ((product.productUrl ?? '').isNotEmpty) ...[
            const SizedBox(height: 18),
            Align(
              alignment: Alignment.centerLeft,
              child: TextButton.icon(
                onPressed: null,
                icon: const Icon(Icons.open_in_new_rounded, size: 18),
                label: const Text('자세히 보기'),
              ),
            ),
          ],
        ],
      ),
    );
  }

  Widget _placeholder() {
    return Container(
      color: const Color(0xFFFDF0F6),
      alignment: Alignment.center,
      child: const Icon(
        Icons.shopping_bag_rounded,
        size: 72,
        color: Color(0xFFFF9ABD),
      ),
    );
  }
}
