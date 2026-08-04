import 'package:flutter/material.dart';
import 'package:flutter_dotenv/flutter_dotenv.dart';

import 'core/services/app_log_service.dart';
import 'features/shopping_v2/screens/shopping_splash_screen.dart';
import 'features/shopping_v2/screens/shopping_voice_screen.dart';
import 'presentation/screens/preview/ui_preview_screen.dart';
import 'presentation/widgets/accessibility_debug_panel.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await dotenv.load(fileName: '.env', isOptional: true);
  await AppLogService.instance.init();
  debugPrint(
    '[AppLaunch] SHOPPING_DEV_INITIAL_ROUTE='
    '${dotenv.env['SHOPPING_DEV_INITIAL_ROUTE'] ?? '(null)'}',
  );
  runApp(const DdalangooV1App());
}

class DdalangooV1App extends StatelessWidget {
  const DdalangooV1App({super.key});

  static String? get _configuredInitialRoute {
    final configured = dotenv.env['SHOPPING_DEV_INITIAL_ROUTE']?.trim();
    return configured?.isEmpty == true ? null : configured;
  }

  static Widget _initialScreenFor(String? configuredInitialRoute) {
    return switch (configuredInitialRoute) {
      '/preview' => const UiPreviewScreen(),
      '/a11y-debug' => const AccessibilityDebugPanel(),
      _ => const ShoppingSplashScreen(),
    };
  }

  @override
  Widget build(BuildContext context) {
    final configuredInitialRoute = _configuredInitialRoute;
    debugPrint(
      '[AppLaunch] initialScreen='
      '${configuredInitialRoute ?? '/shopping-splash'}',
    );
    return MaterialApp(
      title: '딸랑구 V1',
      debugShowCheckedModeBanner: false,
      navigatorObservers: [_DebugNavigatorObserver()],
      theme: ThemeData(
        useMaterial3: true,
        scaffoldBackgroundColor: const Color(0xFFF5FFFB),
        colorScheme: ColorScheme.fromSeed(
          seedColor: const Color(0xFFFF6FAE),
          brightness: Brightness.light,
        ),
      ),
      home: _initialScreenFor(configuredInitialRoute),
      routes: {
        '/shopping-v2': (_) {
          debugPrint('[RouteBuild] /shopping-v2 -> ShoppingVoiceScreen');
          return const ShoppingVoiceScreen();
        },
        '/preview': (_) {
          debugPrint('[RouteBuild] /preview -> UiPreviewScreen');
          return const UiPreviewScreen();
        },
        '/a11y-debug': (_) {
          debugPrint('[RouteBuild] /a11y-debug -> AccessibilityDebugPanel');
          return const AccessibilityDebugPanel();
        },
      },
    );
  }
}

class _DebugNavigatorObserver extends NavigatorObserver {
  @override
  void didPush(Route<dynamic> route, Route<dynamic>? previousRoute) {
    debugPrint(
      '[Navigator] push current=${route.settings.name ?? route.runtimeType} '
      'previous=${previousRoute?.settings.name ?? previousRoute?.runtimeType}',
    );
    super.didPush(route, previousRoute);
  }

  @override
  void didReplace({Route<dynamic>? newRoute, Route<dynamic>? oldRoute}) {
    debugPrint(
      '[Navigator] replace new=${newRoute?.settings.name ?? newRoute?.runtimeType} '
      'old=${oldRoute?.settings.name ?? oldRoute?.runtimeType}',
    );
    super.didReplace(newRoute: newRoute, oldRoute: oldRoute);
  }

  @override
  void didPop(Route<dynamic> route, Route<dynamic>? previousRoute) {
    debugPrint(
      '[Navigator] pop current=${route.settings.name ?? route.runtimeType} '
      'revealed=${previousRoute?.settings.name ?? previousRoute?.runtimeType}',
    );
    super.didPop(route, previousRoute);
  }
}
