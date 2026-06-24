import 'package:flutter/material.dart';
import 'package:flutter_dotenv/flutter_dotenv.dart';

import 'features/shopping_v1/screens/shopping_splash_screen.dart';
import 'features/shopping_v1/screens/shopping_voice_screen.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await dotenv.load(fileName: '.env', isOptional: true);
  runApp(const DdalangooV1App());
}

class DdalangooV1App extends StatelessWidget {
  const DdalangooV1App({super.key});

  @override
  Widget build(BuildContext context) {
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
      },
      initialRoute: '/',
    );
  }
}
