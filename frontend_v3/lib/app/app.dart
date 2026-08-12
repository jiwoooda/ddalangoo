import 'package:flutter/material.dart';

import 'routes.dart';
import 'theme/app_theme.dart';

class DdalangooApp extends StatelessWidget {
  const DdalangooApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: '딸랑구',
      debugShowCheckedModeBanner: false,
      theme: AppTheme.light(),
      // TODO: 백엔드 없이 프론트만 확인하는 동안 임시로 mock 플로우를 시작 라우트로 사용.
      // 백엔드 붙여서 실제 플로우 테스트할 땐 AppRoutes.splash로 되돌릴 것.
      initialRoute: AppRoutes.splashMock,
      routes: AppRoutes.map,
    );
  }
}
