import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:liquid_glass_renderer/liquid_glass_renderer.dart';

import '../models/shopping_v2_models.dart';

class VoiceTurnOrb extends StatefulWidget {
  const VoiceTurnOrb({super.key, required this.state, required this.level});

  final VoiceTurnState state;
  final double level;

  @override
  State<VoiceTurnOrb> createState() => _VoiceTurnOrbState();
}

class _VoiceTurnOrbState extends State<VoiceTurnOrb>
    with TickerProviderStateMixin {
  late final AnimationController _pulseController = AnimationController(
    vsync: this,
    duration: const Duration(milliseconds: 1900),
  )..repeat();
  late final AnimationController _rotationController = AnimationController(
    vsync: this,
    duration: const Duration(milliseconds: 3200),
  )..repeat();
  late final AnimationController _shakeController = AnimationController(
    vsync: this,
    duration: const Duration(milliseconds: 520),
  );

  @override
  void didUpdateWidget(covariant VoiceTurnOrb oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (widget.state == VoiceTurnState.error &&
        oldWidget.state != VoiceTurnState.error) {
      _shakeController
        ..reset()
        ..forward();
    }
  }

  @override
  void dispose() {
    _pulseController.dispose();
    _rotationController.dispose();
    _shakeController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final baseSize = switch (widget.state) {
      VoiceTurnState.transcribing => 104.0,
      VoiceTurnState.agentThinking => 108.0,
      VoiceTurnState.error => 112.0,
      _ => 118.0,
    };

    return AnimatedOpacity(
      opacity:
          widget.state == VoiceTurnState.idle ||
              widget.state == VoiceTurnState.agentSpeaking
          ? 0
          : 1,
      duration: const Duration(milliseconds: 280),
      child: AnimatedBuilder(
        animation: Listenable.merge([
          _pulseController,
          _rotationController,
          _shakeController,
        ]),
        builder: (context, _) {
          final pulse = 1 + (_pulseController.value * 0.12 * widget.level);
          final shake = widget.state == VoiceTurnState.error
              ? math.sin(_shakeController.value * math.pi * 5) * 8
              : 0.0;
          final glowColor = _glowColor();
          return Transform.translate(
            offset: Offset(shake, 0),
            child: SizedBox(
              width: 168,
              height: 168,
              child: Stack(
                alignment: Alignment.center,
                children: [
                  if (widget.state == VoiceTurnState.userRecording)
                    ...List.generate(3, (index) {
                      final localValue =
                          (_pulseController.value + index * 0.22) % 1.0;
                      final ringScale = 0.8 + localValue * 0.85;
                      return Transform.scale(
                        scale: ringScale,
                        child: Opacity(
                          opacity: (1 - localValue).clamp(0.0, 1.0) * 0.34,
                          child: Container(
                            width: baseSize + 18,
                            height: baseSize + 18,
                            decoration: BoxDecoration(
                              shape: BoxShape.circle,
                              border: Border.all(
                                color: glowColor.withValues(alpha: 0.42),
                                width: 2.2,
                              ),
                            ),
                          ),
                        ),
                      );
                    }),
                  if (widget.state == VoiceTurnState.transcribing ||
                      widget.state == VoiceTurnState.agentThinking)
                    Transform.rotate(
                      angle: _rotationController.value * math.pi * 2,
                      child: CustomPaint(
                        painter: _OrbArcPainter(color: glowColor),
                        child: SizedBox(
                          width: baseSize + 24,
                          height: baseSize + 24,
                        ),
                      ),
                    ),
                  Transform.scale(
                    scale: pulse,
                    child: Container(
                      width: baseSize + 24,
                      height: baseSize + 24,
                      decoration: BoxDecoration(
                        shape: BoxShape.circle,
                        gradient: RadialGradient(
                          colors: [
                            glowColor.withValues(alpha: 0.26),
                            glowColor.withValues(alpha: 0.03),
                          ],
                        ),
                      ),
                    ),
                  ),
                  Container(
                    width: baseSize + 10,
                    height: baseSize + 10,
                    decoration: BoxDecoration(
                      shape: BoxShape.circle,
                      boxShadow: [
                        BoxShadow(
                          color: Colors.white.withValues(alpha: 0.36),
                          blurRadius: 28,
                          offset: const Offset(0, 10),
                        ),
                        BoxShadow(
                          color: glowColor.withValues(alpha: 0.16),
                          blurRadius: 34,
                          offset: const Offset(0, 16),
                        ),
                      ],
                    ),
                    child: LiquidGlass.grouped(
                      shape: const LiquidOval(),
                      clipBehavior: Clip.antiAlias,
                      child: Container(
                        width: baseSize,
                        height: baseSize,
                        decoration: BoxDecoration(
                          shape: BoxShape.circle,
                          gradient: LinearGradient(
                            colors: [
                              const Color(0xFFFFFFFF).withValues(alpha: 0.88),
                              _coreColor().withValues(alpha: 0.42),
                            ],
                            begin: Alignment.topLeft,
                            end: Alignment.bottomRight,
                          ),
                          border: Border.all(
                            color: Colors.white.withValues(alpha: 0.9),
                            width: 1.4,
                          ),
                        ),
                        child: widget.state == VoiceTurnState.userCanSpeak ||
                                widget.state == VoiceTurnState.userRecording
                            ? Center(
                                child: Transform.scale(
                                  scale: 1.0 + _pulseController.value * 0.08,
                                  child: Opacity(
                                    opacity: 0.6 + _pulseController.value * 0.4,
                                    child: Text(
                                      '말씀해주세요',
                                      style: TextStyle(
                                        fontFamily: 'Pretendard',
                                        fontSize: baseSize * 0.175,
                                        fontWeight: FontWeight.w700,
                                        color: const Color(0xFFD77B9E),
                                        letterSpacing: -0.3,
                                      ),
                                    ),
                                  ),
                                ),
                              )
                            : CustomPaint(
                                painter: _OrbPainter(
                                  state: widget.state,
                                  level: widget.level,
                                  rotationValue: _rotationController.value,
                                ),
                              ),
                      ),
                    ),
                  ),
                ],
              ),
            ),
          );
        },
      ),
    );
  }

  Color _glowColor() {
    return switch (widget.state) {
      VoiceTurnState.error => const Color(0xFFDE8C9E),
      VoiceTurnState.transcribing => const Color(0xFFD993B0),
      VoiceTurnState.agentThinking => const Color(0xFFD487A7),
      _ => const Color(0xFFD77B9E),
    };
  }

  Color _coreColor() {
    return switch (widget.state) {
      VoiceTurnState.error => const Color(0xFFF7E2E8),
      VoiceTurnState.transcribing => const Color(0xFFF6EAF1),
      VoiceTurnState.agentThinking => const Color(0xFFF6E8F0),
      _ => const Color(0xFFF8EEF4),
    };
  }
}

class _OrbPainter extends CustomPainter {
  const _OrbPainter({
    required this.state,
    required this.level,
    required this.rotationValue,
  });

  final VoiceTurnState state;
  final double level;
  final double rotationValue;

  @override
  void paint(Canvas canvas, Size size) {
    final center = Offset(size.width / 2, size.height / 2);
    final radius = size.width / 2;
    final linePaint = Paint()
      ..style = PaintingStyle.stroke
      ..strokeCap = StrokeCap.round
      ..strokeWidth = state == VoiceTurnState.userRecording ? 3.6 : 2.6
      ..color = const Color(0xFFD77B9E);

    if (state == VoiceTurnState.userRecording) {
      final path = Path();
      for (var i = 0; i <= 48; i++) {
        final x = (i / 48) * size.width;
        final wave =
            math.sin((i / 48 * math.pi * 4) + rotationValue * math.pi * 2) *
            (10 + level * 10);
        final y = center.dy + wave;
        if (i == 0) {
          path.moveTo(x, y);
        } else {
          path.lineTo(x, y);
        }
      }
      canvas.drawPath(path, linePaint);
      return;
    }

    final ringPaint = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = 3
      ..color = const Color(0xFFD77B9E).withValues(alpha: 0.34);

    if (state == VoiceTurnState.transcribing ||
        state == VoiceTurnState.agentThinking) {
      for (var i = 0; i < 8; i++) {
        final angle = ((math.pi * 2) / 8 * i) + (rotationValue * math.pi * 2);
        final point = Offset(
          center.dx + math.cos(angle) * (radius - 18),
          center.dy + math.sin(angle) * (radius - 18),
        );
        final dotPaint = Paint()
          ..color = const Color(0xFFD77B9E).withValues(
            alpha: 0.18 + (((i + rotationValue * 8) % 8) / 8) * 0.62,
          );
        canvas.drawCircle(point, 4.5, dotPaint);
      }
      canvas.drawCircle(center, radius - 22, ringPaint);
      return;
    }

    canvas.drawCircle(center, radius - 22, ringPaint);
  }

  @override
  bool shouldRepaint(covariant _OrbPainter oldDelegate) {
    return oldDelegate.state != state ||
        oldDelegate.level != level ||
        oldDelegate.rotationValue != rotationValue;
  }
}

class _OrbArcPainter extends CustomPainter {
  const _OrbArcPainter({required this.color});

  final Color color;

  @override
  void paint(Canvas canvas, Size size) {
    final rect = Offset.zero & size;
    final basePaint = Paint()
      ..style = PaintingStyle.stroke
      ..strokeCap = StrokeCap.round
      ..strokeWidth = 3.2
      ..color = color.withValues(alpha: 0.12);
    final accentPaint = Paint()
      ..style = PaintingStyle.stroke
      ..strokeCap = StrokeCap.round
      ..strokeWidth = 3.2
      ..color = color.withValues(alpha: 0.82);

    canvas.drawArc(rect.deflate(2), 0, math.pi * 2, false, basePaint);
    canvas.drawArc(
      rect.deflate(2),
      -math.pi / 2,
      math.pi * 0.95,
      false,
      accentPaint,
    );
  }

  @override
  bool shouldRepaint(covariant _OrbArcPainter oldDelegate) {
    return oldDelegate.color != color;
  }
}
