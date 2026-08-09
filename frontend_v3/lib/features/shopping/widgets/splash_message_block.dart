import 'package:flutter/material.dart';

import '../../../app/theme/app_text_styles.dart';
import '../../../shared/layout/app_responsive.dart';

class SplashMessageBlock extends StatelessWidget {
  const SplashMessageBlock({super.key});

  @override
  Widget build(BuildContext context) {
    final responsive = context.responsive;

    return Column(
      children: [
        Text(
          '말로 편하게 쇼핑을 시작해보세요!',
          textAlign: TextAlign.center,
          style: AppTextStyles.body1.copyWith(
            fontSize: responsive.bound(
              responsive.font(18, minFactor: 0.94, maxFactor: 1.0),
              min: 16,
              max: 18,
            ),
          ),
        ),
        SizedBox(
          height: responsive.bound(
            responsive.heightScaled(8, minFactor: 0.72, maxFactor: 1.0),
            min: 4,
            max: 8,
          ),
        ),
        Text(
          '복잡한 과정 없이, 딸랑구가 도와드릴게요.',
          textAlign: TextAlign.center,
          style: AppTextStyles.caption.copyWith(
            fontSize: responsive.bound(
              responsive.font(13, minFactor: 0.94, maxFactor: 1.0),
              min: 12,
              max: 13,
            ),
          ),
        ),
      ],
    );
  }
}
