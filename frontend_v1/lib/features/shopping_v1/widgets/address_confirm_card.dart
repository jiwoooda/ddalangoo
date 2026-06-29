import 'package:flutter/material.dart';

import '../models/shopping_v1_models.dart';
import 'glass_card.dart';

class AddressConfirmCard extends StatelessWidget {
  const AddressConfirmCard({super.key, required this.summary, this.onConfirm});

  final CheckoutSummary summary;
  // onConfirm은 하위호환용으로 남겨두되 UI에서는 사용하지 않음
  final VoidCallback? onConfirm;

  @override
  Widget build(BuildContext context) {
    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        GlassCard(
          backgroundOpacity: 0.30,
          blurSigma: 30,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text(
                '배송지 맞으세요?',
                style: TextStyle(
                  fontFamily: 'Pretendard',
                  fontSize: 26,
                  fontWeight: FontWeight.w900,
                  color: Color(0xFFD77B9E),
                ),
              ),
              const SizedBox(height: 20),
              const Text(
                '기본 배송지',
                style: TextStyle(
                  fontFamily: 'Pretendard',
                  fontSize: 16,
                  fontWeight: FontWeight.w600,
                  color: Color(0xFF6A7782),
                ),
              ),
              const SizedBox(height: 6),
              Text(
                summary.address,
                style: const TextStyle(
                  fontFamily: 'Pretendard',
                  fontSize: 24,
                  fontWeight: FontWeight.w800,
                  color: Color(0xFF223140),
                  height: 1.45,
                ),
              ),
            ],
          ),
        ),
        const SizedBox(height: 14),
        GlassCard(
          backgroundOpacity: 0.26,
          blurSigma: 26,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              _InfoRow(
                label: '요청사항',
                value: summary.deliveryRequest.isNotEmpty
                    ? summary.deliveryRequest
                    : '없음',
              ),
              _InfoRow(label: '주문자', value: summary.userName),
              _InfoRow(label: '전화번호', value: summary.phone),
            ],
          ),
        ),
      ],
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
            width: 72,
            child: Text(
              label,
              style: const TextStyle(
                fontFamily: 'Pretendard',
                fontSize: 16,
                fontWeight: FontWeight.w600,
                color: Color(0xFF6A7782),
              ),
            ),
          ),
          Expanded(
            child: Text(
              value,
              style: const TextStyle(
                fontFamily: 'Pretendard',
                fontSize: 18,
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
