import 'package:flutter/material.dart';
import 'package:flutter_dotenv/flutter_dotenv.dart';

import 'core/services/app_log_service.dart';
import 'features/shopping_v1/screens/shopping_splash_screen.dart';
import 'features/shopping_v1/screens/shopping_voice_screen.dart';
import 'presentation/screens/preview/ui_preview_screen.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await dotenv.load(fileName: '.env', isOptional: true);
  await AppLogService.instance.init();
  runApp(const DdalangooV1App());
}

class DdalangooV1App extends StatelessWidget {
  const DdalangooV1App({super.key});

  static bool get _shouldOpenPreview {
    final configured = dotenv.env['SHOPPING_DEV_INITIAL_ROUTE']?.trim();
    return configured == '/preview';
  }

  @override
  Widget build(BuildContext context) {
    final initialRoute = _shouldOpenPreview ? '/preview' : '/';
    return MaterialApp(
      title: '딸랑구 V1',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        useMaterial3: true,
        scaffoldBackgroundColor: const Color(0xFFF5FFFB),
        colorScheme: ColorScheme.fromSeed(
          seedColor: const Color(0xFFFF6FAE),
          brightness: Brightness.light,
        ),
      ),
      routes: {
        '/': (_) => const ShoppingSplashScreen(),
        '/shopping-v1': (_) => const ShoppingVoiceScreen(),
        '/preview': (_) => const UiPreviewScreen(),
      },
      initialRoute: initialRoute,
    );
  }
}
