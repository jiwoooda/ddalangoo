import 'dart:async';

import 'package:flutter/material.dart';

class ShoppingSplashScreen extends StatefulWidget {
  const ShoppingSplashScreen({super.key});

  @override
  State<ShoppingSplashScreen> createState() => _ShoppingSplashScreenState();
}

class _ShoppingSplashScreenState extends State<ShoppingSplashScreen> {
  @override
  void initState() {
    super.initState();
    _navigate();
  }

  Future<void> _navigate() async {
    await Future<void>.delayed(const Duration(seconds: 2));
    if (!mounted) {
      return;
    }
    Navigator.of(context).pushReplacementNamed('/shopping-v1');
  }

  @override
  Widget build(BuildContext context) {
    final size = MediaQuery.sizeOf(context);
    final frameHeight = (size.height * 0.28).clamp(180.0, 280.0);
    final textLogoHeight = (size.height * 0.08).clamp(44.0, 82.0);

    return Scaffold(
      body: Container(
        decoration: const BoxDecoration(
          gradient: LinearGradient(
            begin: Alignment.topLeft,
            end: Alignment.bottomRight,
            colors: [Color(0xFFFCFEFD), Color(0xFFF5F9F8), Color(0xFFF9F6F8)],
          ),
        ),
        child: SafeArea(
          child: Stack(
            children: [
              Positioned(
                top: -60,
                left: -50,
                child: _SoftBlob(size: 220, color: const Color(0x11FFFFFF)),
              ),
              Positioned(
                right: -40,
                bottom: 90,
                child: _SoftBlob(size: 180, color: const Color(0x14FFFFFF)),
              ),
              Center(
                child: Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 24),
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Image.asset(
                        'assets/images/ddalangoo_top.png',
                        height: frameHeight,
                        fit: BoxFit.contain,
                        errorBuilder: (context, error, stackTrace) {
                          return Container(
                            width: frameHeight * 0.84,
                            height: frameHeight * 0.84,
                            decoration: BoxDecoration(
                              color: Colors.white.withValues(alpha: 0.86),
                              shape: BoxShape.circle,
                              boxShadow: const [
                                BoxShadow(
                                  color: Color(0x14000000),
                                  blurRadius: 24,
                                  offset: Offset(0, 10),
                                ),
                              ],
                            ),
                            child: const Icon(
                              Icons.favorite_rounded,
                              color: Color(0xFFD77B9E),
                              size: 84,
                            ),
                          );
                        },
                      ),
                      const SizedBox(height: 10),
                      Image.asset(
                        'assets/images/ddalangoo_logo_text.png',
                        height: textLogoHeight,
                        fit: BoxFit.contain,
                        errorBuilder: (context, error, stackTrace) {
                          return const Text(
                            '딸랑구',
                            style: TextStyle(
                              fontSize: 34,
                              fontWeight: FontWeight.w900,
                              color: Color(0xFF1B2B39),
                            ),
                          );
                        },
                      ),
                      const SizedBox(height: 18),
                      const Text(
                        '말로 편하게 쇼핑을 시작해보세요!',
                        textAlign: TextAlign.center,
                        style: TextStyle(
                          fontSize: 16,
                          fontWeight: FontWeight.w600,
                          color: Color(0xFF4C5A68),
                        ),
                      ),
                      const SizedBox(height: 28),
                      const SizedBox(
                        width: 30,
                        height: 30,
                        child: CircularProgressIndicator(
                          strokeWidth: 3.4,
                          valueColor: AlwaysStoppedAnimation(Color(0xFFD77B9E)),
                          backgroundColor: Color(0xFFEAEFF1),
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _SoftBlob extends StatelessWidget {
  const _SoftBlob({required this.size, required this.color});

  final double size;
  final Color color;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: size,
      height: size,
      decoration: BoxDecoration(
        shape: BoxShape.circle,
        gradient: RadialGradient(
          colors: [color, Colors.white.withValues(alpha: 0)],
        ),
      ),
    );
  }
}
