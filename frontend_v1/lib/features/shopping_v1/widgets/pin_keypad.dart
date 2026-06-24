import 'package:flutter/material.dart';

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
            spacing: 12,
            children: List.generate(
              6,
              (index) => Container(
                width: 18,
                height: 18,
                decoration: BoxDecoration(
                  shape: BoxShape.circle,
                  color: index < pin.length
                      ? const Color(0xFFFF6FAE)
                      : const Color(0xFFFFE4EF),
                ),
              ),
            ),
          ),
          const SizedBox(height: 28),
          GridView.builder(
            shrinkWrap: true,
            physics: const NeverScrollableScrollPhysics(),
            itemCount: 12,
            gridDelegate: const SliverGridDelegateWithFixedCrossAxisCount(
              crossAxisCount: 3,
              mainAxisSpacing: 12,
              crossAxisSpacing: 12,
              childAspectRatio: 1.15,
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
                    fontSize: 28,
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
    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(22),
      child: Ink(
        decoration: BoxDecoration(
          color: Colors.white.withValues(alpha: 0.72),
          borderRadius: BorderRadius.circular(22),
          border: Border.all(color: const Color(0xFFFFD0E1)),
        ),
        child: Center(child: child),
      ),
    );
  }
}
