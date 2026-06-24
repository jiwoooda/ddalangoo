import 'dart:ui';

import 'package:flutter/material.dart';

class GlassCard extends StatelessWidget {
  const GlassCard({
    super.key,
    required this.child,
    this.padding = const EdgeInsets.all(24),
    this.borderRadius = 28,
    this.blurSigma = 18,
    this.backgroundOpacity = 0.68,
  });

  final Widget child;
  final EdgeInsetsGeometry padding;
  final double borderRadius;
  final double blurSigma;
  final double backgroundOpacity;

  @override
  Widget build(BuildContext context) {
    return ClipRRect(
      borderRadius: BorderRadius.circular(borderRadius),
      child: BackdropFilter(
        filter: ImageFilter.blur(sigmaX: blurSigma, sigmaY: blurSigma),
        child: Container(
          padding: padding,
          decoration: BoxDecoration(
            gradient: LinearGradient(
              colors: [
                Colors.white.withValues(alpha: backgroundOpacity + 0.1),
                Colors.white.withValues(alpha: backgroundOpacity - 0.08),
              ],
              begin: Alignment.topLeft,
              end: Alignment.bottomRight,
            ),
            borderRadius: BorderRadius.circular(borderRadius),
            border: Border.all(color: const Color(0xFFFFC3D9), width: 1.4),
            boxShadow: const [
              BoxShadow(
                color: Color(0x14091A2A),
                blurRadius: 28,
                offset: Offset(0, 18),
              ),
            ],
          ),
          child: Stack(
            children: [
              Positioned(
                top: -36,
                right: -24,
                child: IgnorePointer(
                  child: Container(
                    width: 120,
                    height: 120,
                    decoration: BoxDecoration(
                      shape: BoxShape.circle,
                      gradient: RadialGradient(
                        colors: [
                          Colors.white.withValues(alpha: 0.4),
                          Colors.white.withValues(alpha: 0.02),
                        ],
                      ),
                    ),
                  ),
                ),
              ),
              child,
            ],
          ),
        ),
      ),
    );
  }
}
