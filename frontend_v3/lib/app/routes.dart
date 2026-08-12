import 'package:flutter/widgets.dart';

import '../features/auth/screens/login_screen.dart';
import '../features/auth/screens/register_screen.dart';
import '../features/cart/screens/cart_screen.dart';
import '../features/onboarding/screens/onboarding_screen.dart';
import '../features/home/screens/home_screen.dart';
import '../features/platform_check/screens/platform_check_screen.dart';
import '../features/profile/screens/preference_report_screen.dart';
import '../features/shopping/screens/purchase_history_loading_screen.dart';
import '../features/shopping/screens/shopping_flow_screen.dart';
import '../features/shopping/screens/smalltalk_screen.dart';
import '../features/shopping/screens/splash_screen.dart';
import '../features/shopping/services/mock_shopping_flow_service.dart';

abstract final class AppRoutes {
  static const splash = '/';
  static const splashMock = '/splash-mock';
  static const onboarding = '/onboarding';
  static const onboardingMock = '/onboarding-mock';
  static const login = '/login';
  static const register = '/register';
  static const home = '/home';
  static const cart = '/cart';
  static const smallTalk = '/smalltalk';
  static const platformCheck = '/platform-check';
  static const purchaseHistoryLoading = '/purchase-history-loading';
  static const flowEntry = '/flow-entry';
  static const flowEntryMock = '/flow-entry-mock';
  static const preferenceReport = '/preference-report';

  static final map = <String, WidgetBuilder>{
    splash: (_) => const SplashScreen(),
    splashMock: (_) => const SplashScreen(useMockFlow: true),
    onboarding: (_) => const OnboardingScreen(),
    onboardingMock: (_) => const OnboardingScreen(useMockFlow: true),
    login: (_) => const LoginScreen(),
    register: (_) => const RegisterScreen(),
    home: (_) => const HomeScreen(),
    cart: (_) => const CartScreen(),
    smallTalk: (_) => const SmallTalkScreen(),
    platformCheck: (_) => const PlatformCheckScreen(),
    purchaseHistoryLoading: (_) => const PurchaseHistoryLoadingScreen(),
    flowEntry: (_) => const ShoppingFlowScreen(),
    flowEntryMock: (_) =>
        ShoppingFlowScreen(service: MockShoppingFlowService()),
    preferenceReport: (_) => const PreferenceReportScreen(),
  };
}
