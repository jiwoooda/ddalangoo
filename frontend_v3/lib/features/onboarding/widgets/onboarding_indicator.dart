import 'package:flutter/material.dart';

import '../../../app/theme/app_colors.dart';
import '../../../app/theme/app_radii.dart';
import '../../../app/theme/app_spacing.dart';

class OnboardingIndicator extends StatelessWidget {
  const OnboardingIndicator({
    super.key,
    required this.count,
    required this.currentIndex,
  });

  final int count;
  final int currentIndex;

  @override
  Widget build(BuildContext context) {
    return Row(
      mainAxisAlignment: MainAxisAlignment.center,
      children: List.generate(count, (index) {
        final isActive = index == currentIndex;
        return AnimatedContainer(
          duration: const Duration(milliseconds: 220),
          curve: Curves.easeOutCubic,
          width: isActive ? 28 : 10,
          height: 10,
          margin: EdgeInsets.only(
            right: index == count - 1 ? 0 : AppSpacing.xs,
          ),
          decoration: BoxDecoration(
            color: isActive
                ? AppColors.primaryPink
                : AppColors.secondaryPink.withValues(alpha: 0.8),
            borderRadius: BorderRadius.circular(AppRadii.pill),
          ),
        );
      }),
    );
  }
}
