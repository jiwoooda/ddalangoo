import 'package:flutter/material.dart';
import 'package:flutter_dotenv/flutter_dotenv.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'app/app.dart';
import 'features/shopping/overlays/shopping_automation_overlay_app.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await dotenv.load(fileName: '.env', isOptional: true);
  // ProviderScope는 앱 전체에서 하나만 있으면 되고, 화면별 컨트롤러(예:
  // ShoppingFlowController)는 각자 autoDispose provider로 스코프를 스스로 관리한다.
  runApp(const ProviderScope(child: DdalangooApp()));
}

@pragma('vm:entry-point')
void shoppingAutomationOverlayMain() {
  WidgetsFlutterBinding.ensureInitialized();
  runApp(const ShoppingAutomationOverlayApp());
}
