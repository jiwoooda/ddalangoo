import 'package:flutter/material.dart';

import '../models/shopping_v1_models.dart';
import 'glass_button.dart';
import 'glass_card.dart';

class AddressConfirmCard extends StatelessWidget {
  const AddressConfirmCard({super.key, required this.summary, this.onConfirm});

  final CheckoutSummary summary;
  final VoidCallback? onConfirm;

  @override
  Widget build(BuildContext context) {
    return GlassCard(
      child: LayoutBuilder(
        builder: (context, constraints) {
          return SingleChildScrollView(
            physics: const BouncingScrollPhysics(),
            padding: const EdgeInsets.only(bottom: 4),
            child: ConstrainedBox(
              constraints: BoxConstraints(minHeight: constraints.maxHeight),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Text(
                    '배송지 확인',
                    style: TextStyle(
                      fontFamily: 'Pretendard',
                      fontSize: 28,
                      fontWeight: FontWeight.w800,
                      color: Color(0xFF12202F),
                    ),
                  ),
                  const SizedBox(height: 18),
                  _InfoRow(label: '주문자', value: summary.userName),
                  _InfoRow(label: '전화번호', value: summary.phone),
                  _InfoRow(label: '기본배송지', value: summary.address),
                  const SizedBox(height: 16),
                  const Text(
                    '주문 상품',
                    style: TextStyle(
                      fontFamily: 'Pretendard',
                      fontSize: 18,
                      fontWeight: FontWeight.w800,
                      color: Color(0xFF12202F),
                    ),
                  ),
                  const SizedBox(height: 10),
                  ...summary.items.map(
                    (item) => Padding(
                      padding: const EdgeInsets.only(bottom: 14),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            item.product.title,
                            style: const TextStyle(
                              fontFamily: 'Pretendard',
                              fontSize: 16,
                              fontWeight: FontWeight.w700,
                              color: Color(0xFF334152),
                              height: 1.42,
                            ),
                          ),
                          const SizedBox(height: 6),
                          Text(
                            '${item.quantity}개 · ${item.displayTotalPrice}',
                            style: const TextStyle(
                              fontFamily: 'Pretendard',
                              fontSize: 16,
                              fontWeight: FontWeight.w800,
                              color: Color(0xFFD77B9E),
                            ),
                          ),
                        ],
                      ),
                    ),
                  ),
                  const Divider(height: 28),
                  Row(
                    crossAxisAlignment: CrossAxisAlignment.end,
                    children: [
                      const Expanded(
                        child: Text(
                          '총 결제 금액',
                          style: TextStyle(
                            fontFamily: 'Pretendard',
                            fontSize: 18,
                            fontWeight: FontWeight.w700,
                            color: Color(0xFF334152),
                          ),
                        ),
                      ),
                      const SizedBox(width: 12),
                      Flexible(
                        child: Text(
                          summary.totalPriceText,
                          textAlign: TextAlign.right,
                          style: const TextStyle(
                            fontFamily: 'Pretendard',
                            fontSize: 22,
                            fontWeight: FontWeight.w900,
                            color: Color(0xFFD77B9E),
                          ),
                        ),
                      ),
                    ],
                  ),
                  if (onConfirm != null) ...[
                    const SizedBox(height: 22),
                    SizedBox(
                      width: double.infinity,
                      child: GlassButton(
                        label: '이 배송지로 진행할게요',
                        onPressed: onConfirm,
                        foregroundColor: const Color(0xFFD77B9E),
                      ),
                    ),
                  ],
                ],
              ),
            ),
          );
        },
      ),
    );
  }
}

class _InfoRow extends StatelessWidget {
  const _InfoRow({required this.label, required this.value});

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: 82,
            child: Text(
              label,
              style: const TextStyle(
                fontFamily: 'Pretendard',
                fontSize: 16,
                fontWeight: FontWeight.w700,
                color: Color(0xFF6A7782),
              ),
            ),
          ),
          Expanded(
            child: Text(
              value,
              style: const TextStyle(
                fontFamily: 'Pretendard',
                fontSize: 17,
                fontWeight: FontWeight.w600,
                color: Color(0xFF223140),
                height: 1.45,
              ),
            ),
          ),
        ],
      ),
    );
  }
}
