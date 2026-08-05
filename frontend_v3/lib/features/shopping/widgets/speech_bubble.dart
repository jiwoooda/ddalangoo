import 'dart:math' as math;

import 'package:flutter/material.dart';

import '../../../app/theme/app_colors.dart';
import '../../../app/theme/app_radii.dart';
import '../../../app/theme/app_spacing.dart';

enum SpeechBubbleTail { none, left, right }

class SpeechBubble extends StatelessWidget {
  const SpeechBubble({
    super.key,
    required this.child,
    this.tail = SpeechBubbleTail.left,
    this.backgroundColor = AppColors.surface,
    this.borderColor = AppColors.border,
    this.padding = const EdgeInsets.all(AppSpacing.lg),
  });

  final Widget child;
  final SpeechBubbleTail tail;
  final Color backgroundColor;
  final Color borderColor;
  final EdgeInsets padding;

  @override
  Widget build(BuildContext context) {
    return Stack(
      clipBehavior: Clip.none,
      children: [
        Container(
          width: double.infinity,
          padding: padding,
          decoration: BoxDecoration(
            color: backgroundColor,
            borderRadius: BorderRadius.circular(AppRadii.xl),
            border: Border.all(color: borderColor),
            boxShadow: const [
              BoxShadow(
                color: AppColors.shadow,
                blurRadius: 18,
                offset: Offset(0, 10),
              ),
            ],
          ),
          child: child,
        ),
        if (tail != SpeechBubbleTail.none)
          Positioned(
            bottom: -7,
            left: tail == SpeechBubbleTail.left ? 26 : null,
            right: tail == SpeechBubbleTail.right ? 26 : null,
            child: Transform.rotate(
              angle: math.pi / 4,
              child: Container(
                width: 16,
                height: 16,
                decoration: BoxDecoration(
                  color: backgroundColor,
                  border: Border(
                    right: BorderSide(color: borderColor),
                    bottom: BorderSide(color: borderColor),
                  ),
                ),
              ),
            ),
          ),
      ],
    );
  }
}
