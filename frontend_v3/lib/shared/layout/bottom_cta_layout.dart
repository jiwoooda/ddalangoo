import 'package:flutter/material.dart';

import '../../app/theme/app_spacing.dart';
import 'app_responsive.dart';

class BottomCtaLayout extends StatelessWidget {
  const BottomCtaLayout({
    super.key,
    required this.content,
    required this.cta,
    this.spacing = AppSpacing.lg,
  });

  final Widget content;
  final Widget cta;
  final double spacing;

  @override
  Widget build(BuildContext context) {
    final responsive = context.responsive;
    final resolvedSpacing = responsive.bound(
      responsive.heightScaled(spacing, minFactor: 0.55, maxFactor: 1.0),
      min: AppSpacing.sm,
      max: spacing,
    );

    return Column(
      children: [
        Expanded(child: content),
        SizedBox(height: resolvedSpacing),
        cta,
      ],
    );
  }
}
