import 'dart:ui';

import 'package:flutter/material.dart';
import 'package:liquid_glass_renderer/liquid_glass_renderer.dart';

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
    final radius = BorderRadius.circular(borderRadius);
    return DecoratedBox(
      decoration: BoxDecoration(
        borderRadius: radius,
        boxShadow: [
          BoxShadow(
            color: const Color(0x1A8AA6A0).withValues(alpha: 0.12),
            blurRadius: 32,
            offset: const Offset(0, 18),
          ),
          BoxShadow(
            color: const Color(0x26FF9BC4).withValues(alpha: 0.15),
            blurRadius: 40,
            offset: const Offset(0, 8),
          ),
        ],
      ),
      child: LiquidGlass.grouped(
        shape: LiquidRoundedSuperellipse(borderRadius: borderRadius),
        clipBehavior: Clip.antiAlias,
        child: ClipRRect(
          borderRadius: radius,
          child: BackdropFilter(
            filter: ImageFilter.blur(sigmaX: blurSigma, sigmaY: blurSigma),
            child: Container(
              padding: padding,
              decoration: BoxDecoration(
                gradient: LinearGradient(
                  colors: [
                    Colors.white.withValues(alpha: backgroundOpacity + 0.14),
                    const Color(
                      0xFFFFFBFD,
                    ).withValues(alpha: backgroundOpacity - 0.02),
                    const Color(
                      0xFFF5FFFC,
                    ).withValues(alpha: backgroundOpacity - 0.12),
                  ],
                  begin: Alignment.topLeft,
                  end: Alignment.bottomRight,
                ),
                borderRadius: radius,
                border: Border.all(
                  color: const Color(0xFFFFFFFF).withValues(alpha: 0.82),
                  width: 1.05,
                ),
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
                              Colors.white.withValues(alpha: 0.55),
                              Colors.white.withValues(alpha: 0.02),
                            ],
                          ),
                        ),
                      ),
                    ),
                  ),
                  Positioned(
                    left: 0,
                    right: 0,
                    top: 0,
                    child: IgnorePointer(
                      child: Container(
                        height: 1,
                        margin: const EdgeInsets.symmetric(horizontal: 22),
                        decoration: BoxDecoration(
                          gradient: LinearGradient(
                            colors: [
                              Colors.white.withValues(alpha: 0),
                              Colors.white.withValues(alpha: 0.82),
                              Colors.white.withValues(alpha: 0),
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
        ),
      ),
    );
  }
}
