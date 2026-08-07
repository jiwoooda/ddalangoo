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
    this.compact = false,
  });

  final ShoppingProgressStep currentStep;
  final Set<ShoppingProgressStep> completedSteps;
  final bool showCompletedCheck;
  final bool compact;

  static const _labels = <ShoppingProgressStep, String>{
    ShoppingProgressStep.productCheck: '상품 확인',
    ShoppingProgressStep.productSelection: '상품 고르기',
    ShoppingProgressStep.addToCart: '장바구니 담기',
    ShoppingProgressStep.payment: '결제하기',
  };

  static const _compactLabels = <ShoppingProgressStep, String>{
    ShoppingProgressStep.productCheck: '상품 확인',
    ShoppingProgressStep.productSelection: '상품 선택',
    ShoppingProgressStep.addToCart: '장바구니',
    ShoppingProgressStep.payment: '결제',
  };

  @override
  Widget build(BuildContext context) {
    final steps = ShoppingProgressStep.values;
    final connectorTopPadding = compact ? 8.0 : 10.0;
    final connectorHorizontalMargin = compact ? 2.0 : 6.0;
    final stepWidth = compact ? 56.0 : 76.0;
    final indicatorSize = compact ? 20.0 : 22.0;
    final indicatorBorderWidth = compact ? 2.5 : 3.0;
    final completedIndicatorBorderWidth = compact ? 1.75 : 2.0;
    final labelSpacing = compact ? AppSpacing.xxs : AppSpacing.xs;
    final labelHeight = compact ? 15.0 : 16.0;
    final labelFontSize = compact ? 11.0 : 13.0;
    final checkIconSize = compact ? 12.0 : 14.0;
    final labels = compact ? _compactLabels : _labels;

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
              padding: EdgeInsets.only(top: connectorTopPadding),
              child: Container(
                height: 3,
                margin: EdgeInsets.symmetric(
                  horizontal: connectorHorizontalMargin,
                ),
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
          width: stepWidth,
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Container(
                width: indicatorSize,
                height: indicatorSize,
                decoration: BoxDecoration(
                  shape: BoxShape.circle,
                  color: isCompleted ? AppColors.primaryPink : Colors.white,
                  border: Border.all(
                    color: isCompleted || isCurrent
                        ? AppColors.primaryPink
                        : AppColors.border,
                    width: isCurrent
                        ? indicatorBorderWidth
                        : completedIndicatorBorderWidth,
                  ),
                ),
                child: isCompleted && showCompletedCheck
                    ? Icon(
                        Icons.check,
                        size: checkIconSize,
                        color: Colors.white,
                      )
                    : null,
              ),
              SizedBox(height: labelSpacing),
              SizedBox(
                height: labelHeight,
                child: FittedBox(
                  fit: BoxFit.scaleDown,
                  child: Text(
                    labels[step]!,
                    maxLines: 1,
                    textAlign: TextAlign.center,
                    style: TextStyle(
                      fontSize: labelFontSize,
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
