import 'package:flutter/material.dart';

import '../../../app/theme/app_text_styles.dart';

class SplashMessageBlock extends StatelessWidget {
  const SplashMessageBlock({super.key});

  @override
  Widget build(BuildContext context) {
    return Column(
      children: const [
        Text(
          '말로 편하게 쇼핑을 시작해보세요!',
          textAlign: TextAlign.center,
          style: AppTextStyles.body1,
        ),
        SizedBox(height: 8),
        Text(
          '복잡한 과정 없이, 딸랑구가 도와드릴게요.',
          textAlign: TextAlign.center,
          style: AppTextStyles.caption,
        ),
      ],
    );
  }
}
