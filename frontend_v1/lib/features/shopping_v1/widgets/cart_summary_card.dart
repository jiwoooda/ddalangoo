import 'package:flutter/material.dart';

import '../models/shopping_v1_models.dart';
import 'glass_card.dart';

class CartSummaryCard extends StatelessWidget {
  const CartSummaryCard({
    super.key,
    required this.userName,
    required this.items,
    required this.totalQuantity,
    required this.totalPriceText,
  });

  final String userName;
  final List<CartItemViewData> items;
  final int totalQuantity;
  final String totalPriceText;

  @override
  Widget build(BuildContext context) {
    return GlassCard(
      padding: const EdgeInsets.fromLTRB(22, 22, 22, 20),
      child: Stack(
        clipBehavior: Clip.none,
        children: [
          Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                '$userName 님의 장바구니',
                style: const TextStyle(
                  fontFamily: 'Pretendard',
                  fontSize: 17,
                  fontWeight: FontWeight.w900,
                  color: Color(0xFFFF5DB1),
                ),
              ),
              const SizedBox(height: 18),
              const Text(
                '상품명 x 수량',
                style: TextStyle(
                  fontFamily: 'Pretendard',
                  fontSize: 16,
                  fontWeight: FontWeight.w700,
                  color: Color(0xFF9A9AA1),
                ),
              ),
              const SizedBox(height: 12),
              ...items.map(
                (item) => Padding(
                  padding: const EdgeInsets.only(bottom: 8),
                  child: Text(
                    '${item.product.displayTitle} x ${item.quantity}개',
                    style: const TextStyle(
                      fontFamily: 'Pretendard',
                      fontSize: 18,
                      fontWeight: FontWeight.w900,
                      color: Color(0xFF101923),
                      height: 1.25,
                    ),
                  ),
                ),
              ),
              const SizedBox(height: 18),
              Container(
                width: double.infinity,
                height: 1.5,
                decoration: const BoxDecoration(
                  border: Border(
                    top: BorderSide(
                      color: Color(0xFFFFB7C9),
                      width: 1.5,
                    ),
                  ),
                ),
              ),
              const SizedBox(height: 18),
              RichText(
                text: TextSpan(
                  style: const TextStyle(
                    fontFamily: 'Pretendard',
                    fontSize: 18,
                    color: Color(0xFF8F8F97),
                    fontWeight: FontWeight.w700,
                  ),
                  children: [
                    const TextSpan(text: '총 수량 '),
                    TextSpan(
                      text: '$totalQuantity개',
                      style: const TextStyle(
                        color: Color(0xFF101923),
                        fontWeight: FontWeight.w900,
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 8),
              RichText(
                text: TextSpan(
                  style: const TextStyle(
                    fontFamily: 'Pretendard',
                    fontSize: 18,
                    color: Color(0xFF8F8F97),
                    fontWeight: FontWeight.w700,
                  ),
                  children: [
                    const TextSpan(text: '총 가격 '),
                    TextSpan(
                      text: totalPriceText,
                      style: const TextStyle(
                        color: Color(0xFF101923),
                        fontWeight: FontWeight.w900,
                      ),
                    ),
                  ],
                ),
              ),
            ],
          ),
          Positioned(
            right: -6,
            bottom: -12,
            child: Container(
              width: 94,
              height: 94,
              decoration: BoxDecoration(
                borderRadius: BorderRadius.circular(26),
                gradient: const LinearGradient(
                  colors: [Color(0xFFFFB3D5), Color(0xFFFF5DB1)],
                  begin: Alignment.topLeft,
                  end: Alignment.bottomRight,
                ),
                boxShadow: [
                  BoxShadow(
                    color: const Color(0xFFFF6DB8).withValues(alpha: 0.28),
                    blurRadius: 24,
                    offset: const Offset(0, 12),
                  ),
                ],
              ),
              child: const Icon(
                Icons.shopping_basket_rounded,
                size: 52,
                color: Colors.white,
              ),
            ),
          ),
        ],
      ),
    );
  }
}
