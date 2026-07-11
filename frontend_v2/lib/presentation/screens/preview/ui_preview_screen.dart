import 'package:flutter/material.dart';

import '../../../features/shopping_v2/controllers/shopping_flow_controller.dart';
import '../../../features/shopping_v2/screens/platform_scan_screen.dart';
import '../../../features/shopping_v2/screens/purchase_history_loading_screen.dart';
import '../../../features/shopping_v2/screens/shopping_splash_screen.dart';
import '../../../features/shopping_v2/screens/shopping_voice_screen.dart';
import '../../../features/shopping_v2/screens/smalltalk_screen.dart';

class UiPreviewScreen extends StatefulWidget {
  const UiPreviewScreen({super.key});

  static void openPage(BuildContext context, Widget child) {
    _UiPreviewScreenState._openPage(context, child);
  }

  @override
  State<UiPreviewScreen> createState() => _UiPreviewScreenState();
}

class _UiPreviewScreenState extends State<UiPreviewScreen> {
  @override
  void initState() {
    super.initState();
    debugPrint('[UiPreviewScreen] initState');
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) return;
      final routeName = ModalRoute.of(context)?.settings.name;
      debugPrint(
        '[UiPreviewScreen] firstFrame route=${routeName ?? '(unnamed)'}',
      );
    });
  }

  @override
  void dispose() {
    debugPrint('[UiPreviewScreen] dispose');
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    debugPrint('[UiPreviewScreen] build');
    return Scaffold(
      backgroundColor: const Color(0xFFFDF0F3),
      appBar: AppBar(
        title: const Text('UI Preview'),
        backgroundColor: const Color(0xFFFDF0F3),
      ),
      body: ListView(
        padding: const EdgeInsets.fromLTRB(20, 16, 20, 32),
        children: [
          const _SectionTitle(
            title: 'Shopping V2 Screens',
            subtitle: 'shopping_v2 폴더에서 현재 확인해야 하는 화면들만 모아뒀어요.',
          ),
          _PreviewTile(
            title: 'Small Talk',
            subtitle: '신규 사용자와 딸랑구가 대화하는 온보딩 화면',
            onTap: () =>
                _openPage(context, const SmallTalkScreen(userName: '김영희')),
          ),
          _PreviewTile(
            title: 'Platform Radar Scan',
            subtitle: '사용 중인 쇼핑 플랫폼을 스캔하는 레이더 화면',
            onTap: () =>
                _openPage(context, const PlatformScanScreen(userName: '김영희')),
          ),
          _PreviewTile(
            title: 'Purchase History Loading',
            subtitle: '플랫폼별 구매 이력을 모으는 로딩 화면',
            onTap: () => _openPage(
              context,
              const PurchaseHistoryLoadingScreen(userName: '김영희'),
            ),
          ),
          _PreviewTile(
            title: 'Shopping Splash',
            subtitle: '실제 앱 진입 시 보이는 스플래시 화면, 잠시 후 메인으로 이동해요.',
            onTap: () => _openPage(context, const ShoppingSplashScreen()),
          ),
          _PreviewTile(
            title: 'Shopping Voice',
            subtitle: '현재 /shopping-v2 라우트에서 사용하는 메인 쇼핑 화면, 백엔드가 필요해요.',
            onTap: () => _openPage(context, const ShoppingVoiceScreen()),
          ),
          _PreviewTile(
            title: 'Shopping Voice Step Mocks',
            subtitle: '백엔드 없이도 단계별 대화 상세 화면을 mock 데이터로 볼 수 있어요.',
            onTap: () =>
                _openPage(context, const _ShoppingVoiceFlowPreviewScreen()),
          ),
        ],
      ),
    );
  }

  static void _openPage(BuildContext context, Widget child) {
    Navigator.of(context).push(MaterialPageRoute<void>(builder: (_) => child));
  }
}

class _ShoppingVoiceFlowPreviewScreen extends StatelessWidget {
  const _ShoppingVoiceFlowPreviewScreen();

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFFFDF0F3),
      appBar: AppBar(
        title: const Text('Shopping Voice Mock Steps'),
        backgroundColor: const Color(0xFFFDF0F3),
      ),
      body: ListView(
        padding: const EdgeInsets.fromLTRB(20, 16, 20, 32),
        children: [
          const _SectionTitle(
            title: 'Conversation Steps',
            subtitle: '실제 shopping_v2 플로우를 기준으로 각 단계 화면을 바로 열어볼 수 있어요.',
          ),
          for (final entry in _shoppingVoicePreviewEntries)
            _PreviewTile(
              title: entry.title,
              subtitle: entry.subtitle,
              onTap: () => UiPreviewScreen.openPage(
                context,
                _ShoppingVoicePreviewPage(preset: entry.preset),
              ),
            ),
        ],
      ),
    );
  }
}

class _ShoppingVoicePreviewPage extends StatefulWidget {
  const _ShoppingVoicePreviewPage({required this.preset});

  final ShoppingVoicePreviewPreset preset;

  @override
  State<_ShoppingVoicePreviewPage> createState() =>
      _ShoppingVoicePreviewPageState();
}

class _ShoppingVoicePreviewPageState extends State<_ShoppingVoicePreviewPage> {
  late final ShoppingFlowController _controller =
      ShoppingFlowController.preview(widget.preset);

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return ShoppingVoiceScreen(
      controller: _controller,
      autoInitialize: false,
      onExit: () => Navigator.of(context).maybePop(),
    );
  }
}

class _ShoppingVoicePreviewEntry {
  const _ShoppingVoicePreviewEntry({
    required this.title,
    required this.subtitle,
    required this.preset,
  });

  final String title;
  final String subtitle;
  final ShoppingVoicePreviewPreset preset;
}

const _shoppingVoicePreviewEntries = <_ShoppingVoicePreviewEntry>[
  _ShoppingVoicePreviewEntry(
    title: '1. 첫 안내',
    subtitle: '무엇을 사고 싶은지 묻는 시작 화면',
    preset: ShoppingVoicePreviewPreset.askProduct,
  ),
  _ShoppingVoicePreviewEntry(
    title: '2. 상품 검색 중',
    subtitle: '키워드를 받아 상품을 찾는 중간 상태',
    preset: ShoppingVoicePreviewPreset.searchingProduct,
  ),
  _ShoppingVoicePreviewEntry(
    title: '3. 상품 추천',
    subtitle: '추천 멘트와 상품 카드가 함께 보이는 단계',
    preset: ShoppingVoicePreviewPreset.showProduct,
  ),
  _ShoppingVoicePreviewEntry(
    title: '4. 수량 확인',
    subtitle: '몇 개 구매할지 묻는 화면',
    preset: ShoppingVoicePreviewPreset.askQuantity,
  ),
  _ShoppingVoicePreviewEntry(
    title: '5. 장바구니 작업',
    subtitle: '장바구니에 담는 중인 진행 상태',
    preset: ShoppingVoicePreviewPreset.addingToCart,
  ),
  _ShoppingVoicePreviewEntry(
    title: '6. 추가 구매/결제',
    subtitle: '장바구니 요약과 다음 행동 선택 화면',
    preset: ShoppingVoicePreviewPreset.askMoreOrCheckout,
  ),
  _ShoppingVoicePreviewEntry(
    title: '7. 배송지 확인',
    subtitle: '주문자 정보와 배송지를 확인하는 단계',
    preset: ShoppingVoicePreviewPreset.confirmAddress,
  ),
  _ShoppingVoicePreviewEntry(
    title: '8. 비밀번호 입력',
    subtitle: '결제 비밀번호를 입력하는 화면',
    preset: ShoppingVoicePreviewPreset.enterPassword,
  ),
  _ShoppingVoicePreviewEntry(
    title: '9. 결제 진행 중',
    subtitle: '결제 로딩 상태 화면',
    preset: ShoppingVoicePreviewPreset.processingPayment,
  ),
  _ShoppingVoicePreviewEntry(
    title: '10. 결제 완료',
    subtitle: '주문 완료 안내 화면',
    preset: ShoppingVoicePreviewPreset.paymentCompleted,
  ),
  _ShoppingVoicePreviewEntry(
    title: '11. 오류/재시도',
    subtitle: '잘 못 들었을 때 다시 말해달라고 안내하는 상태',
    preset: ShoppingVoicePreviewPreset.error,
  ),
];

class _SectionTitle extends StatelessWidget {
  const _SectionTitle({required this.title, required this.subtitle});

  final String title;
  final String subtitle;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            title,
            style: const TextStyle(
              fontSize: 22,
              fontWeight: FontWeight.w900,
              color: Color(0xFF2D2431),
            ),
          ),
          const SizedBox(height: 6),
          Text(
            subtitle,
            style: const TextStyle(
              fontSize: 14,
              color: Color(0xFF756B73),
              height: 1.45,
            ),
          ),
        ],
      ),
    );
  }
}

class _PreviewTile extends StatelessWidget {
  const _PreviewTile({
    required this.title,
    required this.subtitle,
    required this.onTap,
  });

  final String title;
  final String subtitle;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: Material(
        color: Colors.white,
        borderRadius: BorderRadius.circular(22),
        child: InkWell(
          borderRadius: BorderRadius.circular(22),
          onTap: onTap,
          child: Container(
            padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 18),
            decoration: BoxDecoration(
              borderRadius: BorderRadius.circular(22),
              border: Border.all(color: const Color(0xFFF1CFD8)),
              boxShadow: [
                BoxShadow(
                  color: const Color(0xFFE8325A).withValues(alpha: 0.05),
                  blurRadius: 12,
                  offset: const Offset(0, 5),
                ),
              ],
            ),
            child: Row(
              children: [
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        title,
                        style: const TextStyle(
                          fontSize: 17,
                          fontWeight: FontWeight.w800,
                          color: Color(0xFF2C2C2C),
                        ),
                      ),
                      const SizedBox(height: 6),
                      Text(
                        subtitle,
                        style: const TextStyle(
                          fontSize: 13,
                          color: Color(0xFF6C6C6C),
                          height: 1.4,
                        ),
                      ),
                    ],
                  ),
                ),
                const SizedBox(width: 12),
                Container(
                  width: 42,
                  height: 42,
                  decoration: BoxDecoration(
                    color: const Color(0xFFFFEEF3),
                    borderRadius: BorderRadius.circular(14),
                  ),
                  child: const Icon(
                    Icons.open_in_new_rounded,
                    color: Color(0xFFE8325A),
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
