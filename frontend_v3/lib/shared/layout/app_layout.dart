import 'package:flutter/material.dart';

import '../../app/theme/app_spacing.dart';
import 'app_responsive.dart';
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
    final responsive = AppResponsive.of(context);
    final horizontalBase = responsive.width < 380
        ? 20.0
        : AppSpacing.screenHorizontal;

    return switch (preset) {
      LayoutPreset.standard => AppLayout(
        padding: responsive.adaptivePadding(
          horizontal: horizontalBase,
          top: AppSpacing.screenTop,
          bottom: AppSpacing.screenBottom,
        ),
        maxWidth: responsive.isExpandedWidth
            ? ContentConstraints.wide
            : ContentConstraints.regular,
        topSpacing: responsive.topSpacing(AppSpacing.screenTop),
        bottomSpacing: responsive.bottomSpacing(AppSpacing.screenBottom),
      ),
      LayoutPreset.onboarding => AppLayout(
        padding: responsive.adaptivePadding(
          horizontal: horizontalBase,
          top: AppSpacing.screenTop,
          bottom: 32,
        ),
        maxWidth: responsive.isExpandedWidth
            ? ContentConstraints.wide
            : ContentConstraints.regular,
        topSpacing: responsive.topSpacing(AppSpacing.screenTop),
        bottomSpacing: responsive.bottomSpacing(32),
      ),
      LayoutPreset.conversation => AppLayout(
        padding: responsive.adaptivePadding(
          horizontal: horizontalBase,
          top: 16,
          bottom: 28,
        ),
        maxWidth: responsive.isExpandedWidth
            ? ContentConstraints.wide
            : ContentConstraints.regular,
        topSpacing: responsive.topSpacing(16),
        bottomSpacing: responsive.bottomSpacing(28),
      ),
      LayoutPreset.loading => AppLayout(
        padding: responsive.adaptivePadding(
          horizontal: horizontalBase,
          top: 16,
          bottom: 20,
        ),
        maxWidth: ContentConstraints.wide,
        topSpacing: responsive.topSpacing(16),
        bottomSpacing: responsive.bottomSpacing(20),
      ),
      LayoutPreset.cartCompact => AppLayout(
        padding: responsive.adaptivePadding(
          horizontal: horizontalBase,
          top: 16,
          bottom: 20,
        ),
        maxWidth: ContentConstraints.regular,
        topSpacing: responsive.topSpacing(16),
        bottomSpacing: responsive.bottomSpacing(20),
      ),
    };
  }
}
