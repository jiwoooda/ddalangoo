import 'package:flutter/material.dart';

class ShoppingProgressSteps extends StatelessWidget {
  const ShoppingProgressSteps({super.key, required this.currentStep});

  static const List<String> _labels = <String>[
    '상품 확인',
    '상품 고르기',
    '장바구니\n담기',
    '결제하기',
  ];

  final int currentStep;

  @override
  Widget build(BuildContext context) {
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: List.generate(_labels.length * 2 - 1, (index) {
        if (index.isOdd) {
          final connectorIndex = index ~/ 2;
          final isCompleted = connectorIndex < currentStep;
          return Expanded(
            child: Container(
              height: 2,
              margin: const EdgeInsets.only(bottom: 22),
              color: isCompleted
                  ? const Color(0xFFD77B9E).withValues(alpha: 0.72)
                  : const Color(0xFFD9E0E7),
            ),
          );
        }

        final stepIndex = index ~/ 2;
        final isCompleted = stepIndex < currentStep;
        final isCurrent = stepIndex == currentStep;
        final Color completedColor = const Color(0xFFD77B9E);
        final Color currentBorderColor = const Color(0xFFD77B9E);
        final Color inactiveBorderColor = const Color(0xFFC9D2DB);

        return SizedBox(
          width: 72,
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Stack(
                alignment: Alignment.center,
                children: [
                  AnimatedContainer(
                    duration: const Duration(milliseconds: 220),
                    width: 18,
                    height: 18,
                    decoration: BoxDecoration(
                      shape: BoxShape.circle,
                      color: isCompleted ? completedColor : Colors.white,
                      border: Border.all(
                        color: isCompleted
                            ? completedColor
                            : isCurrent
                            ? currentBorderColor
                            : inactiveBorderColor,
                        width: isCurrent ? 3 : 2,
                      ),
                    ),
                  ),
                  if (isCompleted)
                    const Icon(Icons.check, size: 12, color: Colors.white),
                ],
              ),
              const SizedBox(height: 8),
              Text(
                _labels[stepIndex],
                textAlign: TextAlign.center,
                style: TextStyle(
                  fontFamily: 'Pretendard',
                  fontSize: 13,
                  fontWeight: isCurrent ? FontWeight.w800 : FontWeight.w600,
                  color: isCompleted || isCurrent
                      ? const Color(0xFF223140)
                      : const Color(0xFF94A0AD),
                ),
              ),
            ],
          ),
        );
      }),
    );
  }
}
