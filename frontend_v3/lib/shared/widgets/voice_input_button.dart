import 'package:flutter/material.dart';

import '../../app/theme/app_colors.dart';
import '../../app/theme/app_spacing.dart';
import '../../app/theme/app_text_styles.dart';

enum VoiceInputState { inactive, active, listening }

class VoiceInputButton extends StatefulWidget {
  const VoiceInputButton({
    super.key,
    required this.state,
    required this.onPressed,
    this.activeLabel = '말씀해주세요',
    this.inactiveLabel = '딸랑구가 말하고 있어요',
    this.diameter = 104,
    this.iconSize = 44,
    this.labelSpacing = AppSpacing.md,
  });

  final VoiceInputState state;
  final VoidCallback onPressed;
  final String activeLabel;
  final String inactiveLabel;
  final double diameter;
  final double iconSize;
  final double labelSpacing;

  @override
  State<VoiceInputButton> createState() => _VoiceInputButtonState();
}

class _VoiceInputButtonState extends State<VoiceInputButton>
    with SingleTickerProviderStateMixin {
  late final AnimationController _pulseController = AnimationController(
    vsync: this,
    duration: const Duration(milliseconds: 1800),
  );

  @override
  void initState() {
    super.initState();
    _syncAnimation();
  }

  @override
  void didUpdateWidget(covariant VoiceInputButton oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.state != widget.state) {
      _syncAnimation();
    }
  }

  void _syncAnimation() {
    if (widget.state == VoiceInputState.active ||
        widget.state == VoiceInputState.listening) {
      _pulseController.repeat();
    } else {
      _pulseController.stop();
      _pulseController.value = 0;
    }
  }

  @override
  void dispose() {
    _pulseController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final isInactive = widget.state == VoiceInputState.inactive;
    final isInteractive = !isInactive;
    final baseColor = isInactive
        ? AppColors.surfaceMuted
        : AppColors.primaryPink;
    final foregroundColor = isInactive ? AppColors.textMuted : Colors.white;
    final labelColor = isInactive
        ? AppColors.textMuted
        : AppColors.primaryPinkDark;
    final resolvedLabel = isInactive
        ? widget.inactiveLabel
        : widget.activeLabel;

    return AnimatedBuilder(
      animation: _pulseController,
      builder: (context, _) {
        final scale = widget.state == VoiceInputState.listening
            ? 1 + (_pulseController.value * 0.08)
            : widget.state == VoiceInputState.active
            ? 1 + (_pulseController.value * 0.04)
            : 1.0;
        final glowAlpha = widget.state == VoiceInputState.listening
            ? 0.30
            : widget.state == VoiceInputState.active
            ? 0.20
            : 0.0;

        return Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Transform.scale(
              scale: scale,
              child: GestureDetector(
                onTap: isInteractive ? widget.onPressed : null,
                child: AnimatedContainer(
                  duration: const Duration(milliseconds: 220),
                  width: widget.diameter,
                  height: widget.diameter,
                  decoration: BoxDecoration(
                    color: baseColor,
                    shape: BoxShape.circle,
                    boxShadow: [
                      BoxShadow(
                        color: baseColor.withValues(alpha: glowAlpha),
                        blurRadius: widget.diameter * 0.25,
                        offset: const Offset(0, 12),
                      ),
                    ],
                  ),
                  child: Icon(
                    Icons.mic_rounded,
                    size: widget.iconSize,
                    color: foregroundColor,
                  ),
                ),
              ),
            ),
            SizedBox(height: widget.labelSpacing),
            Text(
              resolvedLabel,
              style: AppTextStyles.body2.copyWith(
                fontWeight: FontWeight.w700,
                color: labelColor,
              ),
            ),
          ],
        );
      },
    );
  }
}
