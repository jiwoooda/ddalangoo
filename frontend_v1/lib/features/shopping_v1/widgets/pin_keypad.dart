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

  static const double _cardPadding = 24;
  static const double _dotAreaHeight = 16;
  static const double _dotGap = 20;
  static const double _gridSpacing = 10;
  static const int _gridRows = 4;

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (context, constraints) {
        final availableHeight = constraints.maxHeight.isFinite
            ? constraints.maxHeight
            : MediaQuery.of(context).size.height * 0.55;
        final availableWidth =
            (constraints.maxWidth.isFinite
                    ? constraints.maxWidth
                    : MediaQuery.of(context).size.width - 40)
                .clamp(0.0, double.infinity) -
            2.0;

        final exactGridHeight =
            (availableHeight -
                    _cardPadding * 2 -
                    _dotAreaHeight -
                    _dotGap -
                    _gridSpacing * (_gridRows - 1))
                .clamp(0.0, double.infinity);
        final buttonHeight = (exactGridHeight / _gridRows).clamp(44.0, 90.0);
        final buttonWidth =
            ((availableWidth - _cardPadding * 2 - _gridSpacing * 2) / 3)
                .floorToDouble();
        final aspectRatio = buttonWidth / buttonHeight;
        final gridViewHeight =
            (buttonHeight * _gridRows + _gridSpacing * (_gridRows - 1))
                .floorToDouble();

        return SizedBox(
          width: availableWidth,
          child: GlassCard(
            padding: const EdgeInsets.fromLTRB(24, 24, 24, 24),
            child: Column(
              mainAxisSize: MainAxisSize.min,
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
                const SizedBox(height: _dotGap),
                SizedBox(
                  height: gridViewHeight,
                  child: GridView.builder(
                    shrinkWrap: true,
                    physics: const NeverScrollableScrollPhysics(),
                    itemCount: 12,
                    gridDelegate: SliverGridDelegateWithFixedCrossAxisCount(
                      crossAxisCount: 3,
                      mainAxisSpacing: _gridSpacing,
                      crossAxisSpacing: _gridSpacing,
                      childAspectRatio: aspectRatio,
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
                            fontSize: 32,
                            fontWeight: FontWeight.w800,
                            color: Color(0xFF12202F),
                          ),
                        ),
                      );
                    },
                  ),
                ),
              ],
            ),
          ),
        );
      },
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
            child: Center(
              child: FittedBox(fit: BoxFit.scaleDown, child: child),
            ),
          ),
        ),
      ),
    );
  }
}
