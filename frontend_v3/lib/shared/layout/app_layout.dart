import 'package:flutter/material.dart';

import '../../app/theme/app_spacing.dart';
import 'content_constraints.dart';
import 'layout_presets.dart';

class AppLayout {
  const AppLayout({
    required this.padding,
    required this.maxWidth,
    required this.topSpacing,
    required this.bottomSpacing,
  });

  final EdgeInsets padding;
  final double maxWidth;
  final double topSpacing;
  final double bottomSpacing;

  factory AppLayout.of(BuildContext context, LayoutPreset preset) {
    final width = MediaQuery.sizeOf(context).width;
    final horizontal = width < 380 ? 20.0 : AppSpacing.screenHorizontal;

    return switch (preset) {
      LayoutPreset.standard => AppLayout(
        padding: EdgeInsets.fromLTRB(
          horizontal,
          AppSpacing.screenTop,
          horizontal,
          AppSpacing.screenBottom,
        ),
        maxWidth: ContentConstraints.regular,
        topSpacing: AppSpacing.screenTop,
        bottomSpacing: AppSpacing.screenBottom,
      ),
      LayoutPreset.onboarding => AppLayout(
        padding: EdgeInsets.fromLTRB(
          horizontal,
          AppSpacing.screenTop,
          horizontal,
          32,
        ),
        maxWidth: ContentConstraints.regular,
        topSpacing: AppSpacing.screenTop,
        bottomSpacing: 32,
      ),
      LayoutPreset.conversation => AppLayout(
        padding: EdgeInsets.fromLTRB(horizontal, 16, horizontal, 28),
        maxWidth: ContentConstraints.regular,
        topSpacing: 16,
        bottomSpacing: 28,
      ),
      LayoutPreset.loading => AppLayout(
        padding: EdgeInsets.fromLTRB(horizontal, 16, horizontal, 20),
        maxWidth: ContentConstraints.wide,
        topSpacing: 16,
        bottomSpacing: 20,
      ),
      LayoutPreset.cartCompact => AppLayout(
        padding: EdgeInsets.fromLTRB(horizontal, 16, horizontal, 20),
        maxWidth: ContentConstraints.regular,
        topSpacing: 16,
        bottomSpacing: 20,
      ),
    };
  }
}
