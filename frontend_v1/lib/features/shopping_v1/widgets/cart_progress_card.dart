import 'package:flutter/material.dart';

import '../models/shopping_v1_models.dart';
import 'glass_card.dart';

class CartProgressCard extends StatelessWidget {
  const CartProgressCard({
    super.key,
    required this.title,
    required this.statusText,
    required this.helperText,
    required this.progress,
    this.items = const [],
  });

  final String title;
  final String statusText;
  final String helperText;
  final double progress;
  final List<CartItemViewData> items;

  @override
  Widget build(BuildContext context) {
    return GlassCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            title,
            style: TextStyle(
              fontFamily: 'Pretendard',
              fontSize: 26,
              fontWeight: FontWeight.w800,
              color: Color(0xFF12202F),
            ),
          ),
          const SizedBox(height: 14),
          Text(
            statusText,
            style: const TextStyle(
              fontFamily: 'Pretendard',
              fontSize: 20,
              fontWeight: FontWeight.w700,
              color: Color(0xFFD77B9E),
            ),
          ),
          const SizedBox(height: 8),
          Text(
            helperText,
            style: const TextStyle(
              fontFamily: 'Pretendard',
              fontSize: 16,
              fontWeight: FontWeight.w500,
              color: Color(0xFF51606E),
            ),
          ),
          if (items.isNotEmpty) ...[
            const SizedBox(height: 18),
            const Text(
              '담은 상품',
              style: TextStyle(
                fontFamily: 'Pretendard',
                fontSize: 17,
                fontWeight: FontWeight.w800,
                color: Color(0xFF223140),
              ),
            ),
            const SizedBox(height: 10),
            ...items.take(3).map(
              (item) => Padding(
                padding: const EdgeInsets.only(bottom: 10),
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Expanded(
                      child: Text(
                        item.product.displayTitle,
                        style: const TextStyle(
                          fontFamily: 'Pretendard',
                          fontSize: 15,
                          fontWeight: FontWeight.w700,
                          color: Color(0xFF334152),
                          height: 1.35,
                        ),
                      ),
                    ),
                    const SizedBox(width: 12),
                    Text(
                      '${item.quantity}개',
                      style: const TextStyle(
                        fontFamily: 'Pretendard',
                        fontSize: 15,
                        fontWeight: FontWeight.w800,
                        color: Color(0xFFD77B9E),
                      ),
                    ),
                  ],
                ),
              ),
            ),
          ],
          const SizedBox(height: 22),
          ClipRRect(
            borderRadius: BorderRadius.circular(999),
            child: LinearProgressIndicator(
              value: progress,
              minHeight: 16,
              backgroundColor: Colors.white.withValues(alpha: 0.58),
              valueColor: const AlwaysStoppedAnimation(Color(0xFFD77B9E)),
            ),
          ),
        ],
      ),
    );
  }
}
