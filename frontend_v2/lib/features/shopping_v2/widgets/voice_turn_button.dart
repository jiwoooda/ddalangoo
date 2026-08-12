import 'package:flutter/material.dart';

class VoiceTurnButton extends StatefulWidget {
  const VoiceTurnButton({
    super.key,
    required this.onTap,
    required this.isRecording,
    required this.isBusy,
  });

  final VoidCallback onTap;
  final bool isRecording;
  final bool isBusy;

  @override
  State<VoiceTurnButton> createState() => _VoiceTurnButtonState();
}

class _VoiceTurnButtonState extends State<VoiceTurnButton>
    with SingleTickerProviderStateMixin {
  late final AnimationController _controller = AnimationController(
    vsync: this,
    duration: const Duration(milliseconds: 1600),
  )..repeat();

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: widget.isBusy ? null : widget.onTap,
      child: SizedBox(
        width: 148,
        height: 148,
        child: AnimatedBuilder(
          animation: _controller,
          builder: (context, _) {
            final pulse = 1 + (_controller.value * 0.24);
            return Stack(
              alignment: Alignment.center,
              children: [
                Transform.scale(
                  scale: pulse,
                  child: Container(
                    width: 112,
                    height: 112,
                    decoration: BoxDecoration(
                      shape: BoxShape.circle,
                      color: const Color(0xFFFF9CC2).withValues(alpha: 0.12),
                    ),
                  ),
                ),
                Container(
                  width: 118,
                  height: 118,
                  decoration: BoxDecoration(
                    shape: BoxShape.circle,
                    gradient: const LinearGradient(
                      colors: [Color(0xFFFF95C0), Color(0xFFFF6FAE)],
                      begin: Alignment.topLeft,
                      end: Alignment.bottomRight,
                    ),
                    boxShadow: [
                      BoxShadow(
                        color: const Color(0xFFFF6FAE).withValues(alpha: 0.35),
                        blurRadius: 26,
                        offset: const Offset(0, 12),
                      ),
                    ],
                    border: Border.all(
                      color: Colors.white.withValues(alpha: 0.72),
                      width: 2,
                    ),
                  ),
                  child: Icon(
                    widget.isRecording ? Icons.stop_rounded : Icons.mic_rounded,
                    size: 46,
                    color: Colors.white,
                  ),
                ),
              ],
            );
          },
        ),
      ),
    );
  }
}
