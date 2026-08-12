import 'package:flutter_test/flutter_test.dart';

import 'package:ddalangoo_v3/app/app.dart';

void main() {
  testWidgets('shows splash title assets area', (tester) async {
    await tester.pumpWidget(const DdalangooApp());

    expect(find.text('말로 편하게 쇼핑을 시작해보세요!'), findsOneWidget);
  });
}
