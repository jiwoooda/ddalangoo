import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:go_router/go_router.dart';
import 'package:google_fonts/google_fonts.dart';
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
        theme: _buildTheme(),
        routerConfig: _router,
      ),
    );
  }

  ThemeData _buildTheme() {
    final fontFamily = GoogleFonts.nanumGothic().fontFamily;
    final baseTheme = ThemeData(
      colorScheme: ColorScheme.fromSeed(
        seedColor: const Color(0xFFE8325A), // 딸랑구 핑크
      ),
      useMaterial3: true,
      fontFamily: fontFamily,
    );

    final cuteTextTheme = GoogleFonts.nanumGothicTextTheme(
      baseTheme.textTheme,
    ).copyWith(
      displayLarge: GoogleFonts.nanumGothic(
        textStyle: baseTheme.textTheme.displayLarge,
        color: const Color(0xFF333333),
        fontWeight: FontWeight.w800,
      ),
      displayMedium: GoogleFonts.nanumGothic(
        textStyle: baseTheme.textTheme.displayMedium,
        color: const Color(0xFF333333),
        fontWeight: FontWeight.w800,
      ),
      displaySmall: GoogleFonts.nanumGothic(
        textStyle: baseTheme.textTheme.displaySmall,
        color: const Color(0xFF333333),
        fontWeight: FontWeight.w700,
      ),
      headlineLarge: GoogleFonts.nanumGothic(
        textStyle: baseTheme.textTheme.headlineLarge,
        color: const Color(0xFF333333),
        fontWeight: FontWeight.w800,
      ),
      headlineMedium: GoogleFonts.nanumGothic(
        textStyle: baseTheme.textTheme.headlineMedium,
        color: const Color(0xFF333333),
        fontWeight: FontWeight.w700,
      ),
      headlineSmall: GoogleFonts.nanumGothic(
        textStyle: baseTheme.textTheme.headlineSmall,
        color: const Color(0xFF333333),
        fontWeight: FontWeight.w700,
      ),
      titleLarge: GoogleFonts.nanumGothic(
        textStyle: baseTheme.textTheme.titleLarge,
        color: const Color(0xFF333333),
        fontWeight: FontWeight.w800,
      ),
      titleMedium: GoogleFonts.nanumGothic(
        textStyle: baseTheme.textTheme.titleMedium,
        color: const Color(0xFF333333),
        fontWeight: FontWeight.w700,
      ),
      titleSmall: GoogleFonts.nanumGothic(
        textStyle: baseTheme.textTheme.titleSmall,
        color: const Color(0xFF333333),
        fontWeight: FontWeight.w700,
      ),
      bodyLarge: GoogleFonts.nanumGothic(
        textStyle: baseTheme.textTheme.bodyLarge,
        color: const Color(0xFF333333),
        fontWeight: FontWeight.w600,
      ),
      bodyMedium: GoogleFonts.nanumGothic(
        textStyle: baseTheme.textTheme.bodyMedium,
        color: const Color(0xFF333333),
        fontWeight: FontWeight.w500,
      ),
      bodySmall: GoogleFonts.nanumGothic(
        textStyle: baseTheme.textTheme.bodySmall,
        color: const Color(0xFF333333),
        fontWeight: FontWeight.w500,
      ),
      labelLarge: GoogleFonts.nanumGothic(
        textStyle: baseTheme.textTheme.labelLarge,
        color: const Color(0xFF333333),
        fontWeight: FontWeight.w700,
      ),
      labelMedium: GoogleFonts.nanumGothic(
        textStyle: baseTheme.textTheme.labelMedium,
        color: const Color(0xFF333333),
        fontWeight: FontWeight.w600,
      ),
      labelSmall: GoogleFonts.nanumGothic(
        textStyle: baseTheme.textTheme.labelSmall,
        color: const Color(0xFF333333),
        fontWeight: FontWeight.w600,
      ),
    );

    return baseTheme.copyWith(
      textTheme: cuteTextTheme,
      primaryTextTheme: cuteTextTheme,
      appBarTheme: AppBarTheme(
        titleTextStyle: cuteTextTheme.titleLarge?.copyWith(
          fontWeight: FontWeight.w700,
        ),
      ),
      elevatedButtonTheme: ElevatedButtonThemeData(
        style: ElevatedButton.styleFrom(
          textStyle: cuteTextTheme.titleMedium?.copyWith(
            fontWeight: FontWeight.w700,
          ),
        ),
      ),
      outlinedButtonTheme: OutlinedButtonThemeData(
        style: OutlinedButton.styleFrom(
          textStyle: cuteTextTheme.titleSmall?.copyWith(
            fontWeight: FontWeight.w700,
          ),
        ),
      ),
      textButtonTheme: TextButtonThemeData(
        style: TextButton.styleFrom(
          textStyle: cuteTextTheme.titleSmall?.copyWith(
            fontWeight: FontWeight.w700,
          ),
        ),
      ),
      filledButtonTheme: FilledButtonThemeData(
        style: FilledButton.styleFrom(
          textStyle: cuteTextTheme.titleMedium?.copyWith(
            fontWeight: FontWeight.w700,
          ),
        ),
      ),
      inputDecorationTheme: InputDecorationTheme(
        labelStyle: cuteTextTheme.bodyMedium?.copyWith(
          color: const Color(0xFF666666),
        ),
        hintStyle: cuteTextTheme.bodyMedium?.copyWith(
          color: const Color(0xFF888888),
        ),
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
