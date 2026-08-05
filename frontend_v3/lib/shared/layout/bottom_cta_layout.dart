import 'package:flutter/material.dart';

import '../../app/theme/app_spacing.dart';

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
    return Column(
      children: [
        Expanded(child: content),
        SizedBox(height: spacing),
        cta,
      ],
    );
  }
}
