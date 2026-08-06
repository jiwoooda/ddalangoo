import 'package:flutter/material.dart';

import '../../app/theme/app_colors.dart';
import '../../app/theme/app_spacing.dart';

enum ShoppingProgressStep { productCheck, productSelection, addToCart, payment }

class ShoppingProgressStepper extends StatelessWidget {
  const ShoppingProgressStepper({
    super.key,
    required this.currentStep,
    this.completedSteps = const <ShoppingProgressStep>{},
    this.showCompletedCheck = true,
  });

  final ShoppingProgressStep currentStep;
  final Set<ShoppingProgressStep> completedSteps;
  final bool showCompletedCheck;

  static const _labels = <ShoppingProgressStep, String>{
    ShoppingProgressStep.productCheck: '상품 확인',
    ShoppingProgressStep.productSelection: '상품 고르기',
    ShoppingProgressStep.addToCart: '장바구니 담기',
    ShoppingProgressStep.payment: '결제하기',
  };

  @override
  Widget build(BuildContext context) {
    final steps = ShoppingProgressStep.values;

    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: List.generate(steps.length * 2 - 1, (index) {
        if (index.isOdd) {
          final connectorIndex = index ~/ 2;
          final connectorStep = steps[connectorIndex];
          final isActiveConnector =
              completedSteps.contains(connectorStep) ||
              connectorIndex < currentStep.index;
          return Expanded(
            child: Padding(
              padding: const EdgeInsets.only(top: 10),
              child: Container(
                height: 3,
                margin: const EdgeInsets.symmetric(horizontal: 6),
                decoration: BoxDecoration(
                  color: isActiveConnector
                      ? AppColors.primaryPink.withValues(alpha: 0.78)
                      : AppColors.border,
                  borderRadius: BorderRadius.circular(999),
                ),
              ),
            ),
          );
        }

        final step = steps[index ~/ 2];
        final isCurrent = step == currentStep;
        final isCompleted =
            completedSteps.contains(step) || step.index < currentStep.index;

        return SizedBox(
          width: 76,
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Container(
                width: 22,
                height: 22,
                decoration: BoxDecoration(
                  shape: BoxShape.circle,
                  color: isCompleted ? AppColors.primaryPink : Colors.white,
                  border: Border.all(
                    color: isCompleted || isCurrent
                        ? AppColors.primaryPink
                        : AppColors.border,
                    width: isCurrent ? 3 : 2,
                  ),
                ),
                child: isCompleted && showCompletedCheck
                    ? const Icon(Icons.check, size: 14, color: Colors.white)
                    : null,
              ),
              const SizedBox(height: AppSpacing.xs),
              SizedBox(
                height: 16,
                child: FittedBox(
                  fit: BoxFit.scaleDown,
                  child: Text(
                    _labels[step]!,
                    maxLines: 1,
                    textAlign: TextAlign.center,
                    style: TextStyle(
                      fontSize: 13,
                      height: 1.1,
                      fontWeight: isCurrent ? FontWeight.w800 : FontWeight.w600,
                      color: isCurrent
                          ? AppColors.primaryPinkDark
                          : isCompleted
                          ? AppColors.textStrong
                          : AppColors.textMuted,
                    ),
                  ),
                ),
              ),
            ],
          ),
        );
      }),
    );
  }
}
