import 'package:flutter/material.dart';
import 'package:liquid_glass_renderer/liquid_glass_renderer.dart';

import 'glass_card.dart';

class PinKeypad extends StatelessWidget {
  const PinKeypad({
    super.key,
    required this.pin,
    required this.onDigitTap,
    required this.onBackspace,
  });

  final String pin;
  final ValueChanged<int> onDigitTap;
  final VoidCallback onBackspace;

  @override
  Widget build(BuildContext context) {
    return GlassCard(
      child: Column(
        children: [
          Wrap(
            alignment: WrapAlignment.center,
            spacing: 10,
            children: List.generate(
              6,
              (index) => Container(
                width: 16,
                height: 16,
                decoration: BoxDecoration(
                  shape: BoxShape.circle,
                  color: index < pin.length
                      ? const Color(0xFFD77B9E)
                      : Colors.white.withValues(alpha: 0.72),
                ),
              ),
            ),
          ),
          const SizedBox(height: 20),
          GridView.builder(
            shrinkWrap: true,
            physics: const NeverScrollableScrollPhysics(),
            itemCount: 12,
            gridDelegate: const SliverGridDelegateWithFixedCrossAxisCount(
              crossAxisCount: 3,
              mainAxisSpacing: 10,
              crossAxisSpacing: 10,
              childAspectRatio: 1.28,
            ),
            itemBuilder: (context, index) {
              if (index == 9) {
                return const SizedBox.shrink();
              }
              if (index == 11) {
                return _KeypadButton(
                  onTap: onBackspace,
                  child: const Icon(Icons.backspace_outlined),
                );
              }
              final digit = index == 10 ? 0 : index + 1;
              return _KeypadButton(
                onTap: () => onDigitTap(digit),
                child: Text(
                  '$digit',
                  style: const TextStyle(
                    fontFamily: 'Pretendard',
                    fontSize: 24,
                    fontWeight: FontWeight.w800,
                    color: Color(0xFF12202F),
                  ),
                ),
              );
            },
          ),
        ],
      ),
    );
  }
}

class _KeypadButton extends StatelessWidget {
  const _KeypadButton({required this.child, required this.onTap});

  final Widget child;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return LiquidGlass.grouped(
      shape: const LiquidRoundedSuperellipse(borderRadius: 18),
      clipBehavior: Clip.antiAlias,
      child: Material(
        color: Colors.white.withValues(alpha: 0.16),
        child: InkWell(
          onTap: onTap,
          borderRadius: BorderRadius.circular(18),
          child: Ink(
            decoration: BoxDecoration(
              color: Colors.white.withValues(alpha: 0.2),
              borderRadius: BorderRadius.circular(18),
              border: Border.all(color: Colors.white.withValues(alpha: 0.72)),
            ),
            child: Center(child: child),
          ),
        ),
      ),
    );
  }
}
