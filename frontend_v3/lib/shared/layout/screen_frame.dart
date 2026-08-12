import 'package:flutter/material.dart';

import '../../app/theme/app_colors.dart';
import 'app_layout.dart';
import 'layout_presets.dart';

class ScreenFrame extends StatelessWidget {
  const ScreenFrame({
    super.key,
    required this.child,
    this.preset = LayoutPreset.standard,
    this.alignment = Alignment.topCenter,
    this.scrollable = false,
    this.backgroundColor = AppColors.background,
  });

  final Widget child;
  final LayoutPreset preset;
  final Alignment alignment;
  final bool scrollable;
  final Color backgroundColor;

  @override
  Widget build(BuildContext context) {
    final layout = AppLayout.of(context, preset);
    final constrainedChild = Align(
      alignment: alignment,
      child: ConstrainedBox(
        constraints: BoxConstraints(maxWidth: layout.maxWidth),
        child: child,
      ),
    );

    return Scaffold(
      backgroundColor: backgroundColor,
      body: SafeArea(
        child: Padding(
          padding: layout.padding,
          child: scrollable
              ? SingleChildScrollView(child: constrainedChild)
              : constrainedChild,
        ),
      ),
    );
  }
}
