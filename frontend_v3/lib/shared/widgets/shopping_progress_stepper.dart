import 'package:flutter/material.dart';

import '../../app/theme/app_colors.dart';
import '../../app/theme/app_spacing.dart';
import '../layout/app_responsive.dart';

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
    final responsive = context.responsive;
    final steps = ShoppingProgressStep.values;

    return LayoutBuilder(
      builder: (context, constraints) {
        final availableWidth = constraints.maxWidth.isFinite
            ? constraints.maxWidth
            : responsive.width;
        final usesCompact = compact || availableWidth < 370;
        final usesExtraCompact = availableWidth < 330;
        final connectorTopPadding = usesExtraCompact
            ? 7.0
            : (usesCompact ? 8.0 : 10.0);
        final connectorHorizontalMargin = usesExtraCompact
            ? 1.0
            : (usesCompact ? 2.0 : 6.0);
        final stepWidth = usesExtraCompact ? 48.0 : (usesCompact ? 56.0 : 76.0);
        final indicatorSize = usesExtraCompact
            ? 18.0
            : (usesCompact ? 20.0 : 22.0);
        final indicatorBorderWidth = usesCompact ? 2.5 : 3.0;
        final completedIndicatorBorderWidth = usesCompact ? 1.75 : 2.0;
        final labelSpacing = usesCompact ? AppSpacing.xxs : AppSpacing.xs;
        final labelHeight = usesExtraCompact
            ? 14.0
            : (usesCompact ? 15.0 : 16.0);
        final labelFontSize = usesExtraCompact
            ? 10.0
            : (usesCompact ? 11.0 : 13.0);
        final checkIconSize = usesExtraCompact
            ? 11.0
            : (usesCompact ? 12.0 : 14.0);
        final labels = usesCompact ? _compactLabels : _labels;

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
                          fontWeight: isCurrent
                              ? FontWeight.w800
                              : FontWeight.w600,
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
      },
    );
  }
}
