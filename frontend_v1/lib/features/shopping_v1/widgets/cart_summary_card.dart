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
      backgroundOpacity: 0.30,
      blurSigma: 30,
      child: Stack(
        clipBehavior: Clip.none,
        children: [
          Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Text(
                '$userName 님의 장바구니',
                textAlign: TextAlign.center,
                style: const TextStyle(
                  fontFamily: 'Pretendard',
                  fontSize: 27,
                  fontWeight: FontWeight.w900,
                  color: Color(0xFFD77B9E),
                ),
              ),
              const SizedBox(height: 18),
              const Text(
                '상품명 x 수량',
                style: TextStyle(
                  fontFamily: 'Pretendard',
                  fontSize: 19,
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
                      fontSize: 25,
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
                    fontSize: 23,
                    color: Color(0xFF8F8F97),
                    fontWeight: FontWeight.w700,
                  ),
                  children: const [
                    TextSpan(text: '배송료 '),
                    TextSpan(
                      text: '0원',
                      style: TextStyle(
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
                    fontSize: 23,
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
        ],
      ),
    );
  }
}
