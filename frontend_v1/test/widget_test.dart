import 'package:ddalangoo/features/shopping_v1/screens/shopping_voice_screen.dart';
import 'package:ddalangoo/features/shopping_v1/widgets/dallang_response_text.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  testWidgets('shows initial shopping prompt', (tester) async {
    await tester.pumpWidget(
      const MaterialApp(home: ShoppingVoiceScreen(autoInitialize: false)),
    );
    await tester.pump();

    expect(
      find.byWidgetPredicate(
        (widget) =>
            widget is DallangResponseText &&
            widget.text == '어떤 상품을 구매하고 싶으신가요?',
      ),
      findsOneWidget,
    );
  });
}
