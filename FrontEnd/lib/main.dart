import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:go_router/go_router.dart';
import 'core/storage/local_storage.dart';
import 'presentation/providers/call_provider.dart';
import 'presentation/screens/auth/splash_screen.dart';
import 'presentation/screens/auth/login_screen.dart';
import 'presentation/screens/auth/register_screen.dart';
import 'presentation/screens/home/home_screen.dart';
import 'presentation/screens/call/call_screen.dart';
import 'package:flutter_dotenv/flutter_dotenv.dart';
import 'core/services/gemini_voice_service.dart';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await dotenv.load(fileName: '.env');
  debugPrint(
    '🚀 [App Start] .env loaded, GEMINI_API_KEY='
    '${dotenv.env['GEMINI_API_KEY']?.isNotEmpty == true ? 'configured' : 'missing'}',
  );
  await GeminiVoiceService.instance.init(); // TTS 초기화
  runApp(const DdalangooApp());
}

class DdalangooApp extends StatelessWidget {
  const DdalangooApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MultiProvider(
      providers: [ChangeNotifierProvider(create: (_) => CallProvider())],
      child: MaterialApp.router(
        title: '딸랑구',
        debugShowCheckedModeBanner: false,
        theme: ThemeData(
          colorScheme: ColorScheme.fromSeed(
            seedColor: const Color(0xFFE8325A), // 딸랑구 핑크
          ),
          useMaterial3: true,
        ),
        routerConfig: _router,
      ),
    );
  }
}

final GoRouter _router = GoRouter(
  initialLocation: '/splash',
  debugLogDiagnostics: true,
  observers: [_RouteLoggingObserver()],
  routes: [
    GoRoute(
      name: 'splash',
      path: '/splash',
      builder: (context, state) => const SplashScreen(),
    ),
    GoRoute(
      name: 'home',
      path: '/home',
      builder: (context, state) => const HomeScreen(),
    ),
    GoRoute(
      name: 'login',
      path: '/login',
      builder: (context, state) => const LoginScreen(),
    ),
    GoRoute(
      name: 'register',
      path: '/register',
      builder: (context, state) => const RegisterScreen(),
    ),
    GoRoute(
      name: 'call',
      path: '/call',
      builder: (context, state) => const CallScreen(),
    ),
  ],
);

class _RouteLoggingObserver extends NavigatorObserver {
  String _describe(Route<dynamic>? route) {
    if (route == null) return 'unknown';
    final name = route.settings.name;
    if (name != null && name.isNotEmpty) return name;
    return route.settings.toString();
  }

  @override
  void didPush(Route<dynamic> route, Route<dynamic>? previousRoute) {
    debugPrint(
      '📍 [Route Push] current=${_describe(route)}, previous=${_describe(previousRoute)}',
    );
    super.didPush(route, previousRoute);
  }

  @override
  void didPop(Route<dynamic> route, Route<dynamic>? previousRoute) {
    debugPrint(
      '↩️ [Route Pop] from=${_describe(route)}, backTo=${_describe(previousRoute)}',
    );
    super.didPop(route, previousRoute);
  }

  @override
  void didReplace({Route<dynamic>? newRoute, Route<dynamic>? oldRoute}) {
    debugPrint(
      '🔁 [Route Replace] old=${_describe(oldRoute)}, new=${_describe(newRoute)}',
    );
    super.didReplace(newRoute: newRoute, oldRoute: oldRoute);
  }
}
