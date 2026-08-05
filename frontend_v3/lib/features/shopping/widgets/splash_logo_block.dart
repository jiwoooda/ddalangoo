import 'package:flutter/material.dart';

import '../../../app/theme/app_sizes.dart';

class SplashLogoBlock extends StatelessWidget {
  const SplashLogoBlock({super.key});

  @override
  Widget build(BuildContext context) {
    final size = MediaQuery.sizeOf(context);
    final characterHeight = (size.height * 0.28).clamp(
      AppSizes.splashCharacterMinHeight,
      AppSizes.splashCharacterMaxHeight,
    );
    final logoHeight = (size.height * 0.08).clamp(48.0, 84.0);

    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        Image.asset(
          'assets/images/ddalangoo_top.png',
          height: characterHeight,
          fit: BoxFit.contain,
        ),
        const SizedBox(height: 10),
        Image.asset(
          'assets/images/ddalangoo_logo_text.png',
          height: logoHeight,
          fit: BoxFit.contain,
        ),
      ],
    );
  }
}
