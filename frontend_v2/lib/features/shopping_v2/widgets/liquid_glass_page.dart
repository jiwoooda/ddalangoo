import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:liquid_glass_renderer/liquid_glass_renderer.dart';

class LiquidGlassPage extends StatelessWidget {
  const LiquidGlassPage({super.key, required this.child, this.settings});

  final Widget child;
  final LiquidGlassSettings? settings;

  @override
  Widget build(BuildContext context) {
    final useFakeGlass =
        !kIsWeb && defaultTargetPlatform == TargetPlatform.android;

    return LiquidGlassLayer(
      fake: useFakeGlass,
      settings:
          settings ??
          LiquidGlassSettings(
            glassColor: Colors.white.withValues(alpha: 0.08),
            thickness: 26,
            blur: 9,
            lightIntensity: 0.85,
            ambientStrength: 0.24,
            saturation: 1.18,
            refractiveIndex: 1.16,
          ),
      child: LiquidGlassBlendGroup(blend: 0, child: child),
    );
  }
}
