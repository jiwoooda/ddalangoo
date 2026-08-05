import 'package:flutter/material.dart';

import '../../app/theme/app_colors.dart';
import '../../app/theme/app_spacing.dart';
import '../../app/theme/app_text_styles.dart';

enum VoiceInputState { inactive, active, listening }

class VoiceInputButton extends StatefulWidget {
  const VoiceInputButton({
    super.key,
    required this.label,
    required this.state,
    required this.onPressed,
  });

  final String label;
  final VoiceInputState state;
  final VoidCallback onPressed;

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
    final baseColor = isInactive
        ? AppColors.surfaceMuted
        : AppColors.primaryPink;
    final foregroundColor = isInactive ? AppColors.textMuted : Colors.white;
    final labelColor = isInactive
        ? AppColors.textMuted
        : AppColors.primaryPinkDark;

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
            : 0.20;

        return Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Transform.scale(
              scale: scale,
              child: GestureDetector(
                onTap: widget.onPressed,
                child: AnimatedContainer(
                  duration: const Duration(milliseconds: 220),
                  width: 104,
                  height: 104,
                  decoration: BoxDecoration(
                    color: baseColor,
                    shape: BoxShape.circle,
                    boxShadow: [
                      BoxShadow(
                        color: baseColor.withValues(alpha: glowAlpha),
                        blurRadius: 26,
                        offset: const Offset(0, 12),
                      ),
                    ],
                  ),
                  child: Icon(
                    Icons.mic_rounded,
                    size: 44,
                    color: foregroundColor,
                  ),
                ),
              ),
            ),
            const SizedBox(height: AppSpacing.md),
            Text(
              widget.label,
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
