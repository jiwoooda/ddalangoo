import 'package:flutter/material.dart';

import '../../../app/theme/app_sizes.dart';
import '../../../shared/layout/app_responsive.dart';

class SplashLogoBlock extends StatelessWidget {
  const SplashLogoBlock({super.key});

  @override
  Widget build(BuildContext context) {
    final responsive = context.responsive;
    final size = MediaQuery.sizeOf(context);
    final characterHeight = responsive.bound(
      size.height * 0.28,
      min: AppSizes.splashCharacterMinHeight,
      max: AppSizes.splashCharacterMaxHeight,
    );
    final logoHeight = responsive.bound(size.height * 0.08, min: 48, max: 84);
    final gap = responsive.bound(
      responsive.heightScaled(10, minFactor: 0.72, maxFactor: 1.0),
      min: 6,
      max: 10,
    );

    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        Image.asset(
          'assets/images/character/top/ddalangoo_top.png',
          height: characterHeight,
          fit: BoxFit.contain,
        ),
        SizedBox(height: gap),
        Image.asset(
          'assets/images/textlogo/ddalangoo_logo_text.png',
          height: logoHeight,
          fit: BoxFit.contain,
        ),
      ],
    );
  }
}
