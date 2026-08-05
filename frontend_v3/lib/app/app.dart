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
      initialRoute: AppRoutes.splash,
      routes: AppRoutes.map,
    );
  }
}
