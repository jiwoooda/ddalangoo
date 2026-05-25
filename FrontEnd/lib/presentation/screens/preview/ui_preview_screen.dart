import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../../data/models/agent_model.dart';
import '../../providers/call_provider.dart';
import '../auth/splash_screen.dart';
import '../call/call_screen.dart';
import '../call/payment_webview_screen.dart';
import '../home/home_screen.dart';

class UiPreviewScreen extends StatelessWidget {
  const UiPreviewScreen({super.key});

  @override
  Widget build(BuildContext context) {
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
            title: 'Static Screens',
            subtitle: '백엔드 없이 홈과 스플래시 화면을 빠르게 확인할 수 있어요.',
          ),
          _PreviewTile(
            title: 'Splash Screen',
            subtitle: '앱 첫 진입 로딩 화면',
            onTap: () => _openPage(context, const SplashScreen()),
          ),
          _PreviewTile(
            title: 'Home Screen',
            subtitle: '김영희님이 로그인된 홈 화면',
            onTap: () => _openPage(
              context,
              const HomeScreen(
                previewUserName: '김영희',
                enableDataLoad: false,
                enableVoiceIntro: false,
              ),
            ),
          ),
          _PreviewTile(
            title: 'WebView Progress',
            subtitle: '웹뷰 연결 중 상태와 진행 카드 레이아웃',
            onTap: () => _openPage(
              context,
              const PaymentWebViewScreen(
                url: 'about:blank',
                previewMode: true,
                previewTitle: '결제 진행',
                previewStatusText: '컬리에 접속하고 있어요.',
                previewHelperText: '웹뷰 화면을 연결하는 중이에요.',
                previewStep: 'opening_shop',
                previewMessage: '컬리에 접속하고 있어요.',
              ),
            ),
          ),
          _PreviewTile(
            title: 'WebView Screenshot',
            subtitle: '실시간 스크린샷이 보이는 웹뷰 레이아웃',
            onTap: () => _openPage(
              context,
              const PaymentWebViewScreen(
                url: 'about:blank',
                previewMode: true,
                previewTitle: '장바구니 작업',
                previewStatusText: '장바구니에 담고 있어요.',
                previewHelperText: '수량과 옵션을 확인한 뒤 장바구니에 담는 중이에요.',
                previewStep: 'adding_to_cart',
                previewMessage: '장바구니에 담고 있어요.',
                previewScreenshotUrl:
                    'https://images.unsplash.com/photo-1542838132-92c53300491e?auto=format&fit=crop&w=1200&q=80',
                previewShowActionButtons: true,
              ),
            ),
          ),
          const SizedBox(height: 24),
          const _SectionTitle(
            title: 'Call Scenarios',
            subtitle: '통화 상태별 디자인을 실제 화면 그대로 볼 수 있어요.',
          ),
          for (final scenario in _callScenarios)
            _PreviewTile(
              title: scenario.title,
              subtitle: scenario.subtitle,
              onTap: () => _openCallPreview(context, scenario),
            ),
        ],
      ),
    );
  }

  static void _openPage(BuildContext context, Widget child) {
    Navigator.of(context).push(
      MaterialPageRoute<void>(builder: (_) => child),
    );
  }

  static void _openCallPreview(BuildContext context, _CallPreviewScenario scenario) {
    Navigator.of(context).push(
      MaterialPageRoute<void>(
        builder: (_) => ChangeNotifierProvider(
          create: (_) => CallProvider()..loadPreviewState(
            stage: scenario.stage,
            response: scenario.response,
            messages: scenario.messages,
            conversationId: scenario.conversationId,
            isAwaitingAssistantPresentation:
                scenario.isAwaitingAssistantPresentation,
            assistantPresentationMessage: scenario.assistantPresentationMessage,
          ),
          child: const CallScreen(
            previewMode: true,
            autoStart: false,
          ),
        ),
      ),
    );
  }
}

class _SectionTitle extends StatelessWidget {
  const _SectionTitle({
    required this.title,
    required this.subtitle,
  });

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

class _CallPreviewScenario {
  const _CallPreviewScenario({
    required this.title,
    required this.subtitle,
    required this.stage,
    required this.messages,
    this.response,
    this.conversationId,
    this.isAwaitingAssistantPresentation = false,
    this.assistantPresentationMessage,
  });

  final String title;
  final String subtitle;
  final CallStage stage;
  final AgentResponse? response;
  final List<Map<String, dynamic>> messages;
  final int? conversationId;
  final bool isAwaitingAssistantPresentation;
  final String? assistantPresentationMessage;
}

List<Map<String, dynamic>> _messages(List<_PreviewMessage> items) {
  return items
      .map(
        (item) => {
          'text': item.text,
          'isUser': item.isUser,
          'isSensitive': false,
          'time': DateTime(2026, 5, 25, 12, 0),
        },
      )
      .toList();
}

class _PreviewMessage {
  const _PreviewMessage(this.text, {required this.isUser});

  final String text;
  final bool isUser;
}

final List<_CallPreviewScenario> _callScenarios = [
  _CallPreviewScenario(
    title: 'Call Greeting',
    subtitle: '통화가 막 연결된 첫 인사 상태',
    stage: CallStage.idle,
    conversationId: 1001,
    messages: _messages([
      const _PreviewMessage('김영희님, 무엇을 구매하고 싶으신가요?', isUser: false),
    ]),
  ),
  _CallPreviewScenario(
    title: 'Assistant Loading Bubble',
    subtitle: 'TTS를 준비하는 동안 말풍선 위치에 표시되는 상태',
    stage: CallStage.productSelection,
    conversationId: 1002,
    isAwaitingAssistantPresentation: true,
    assistantPresentationMessage: '김영희님을 위한 맞춤 상품을 정리하고 있어요.',
    messages: _messages([
      const _PreviewMessage('달콤한 수박을 찾고 싶어', isUser: true),
    ]),
  ),
  _CallPreviewScenario(
    title: 'Product Recommendation',
    subtitle: '상품 카드가 펼쳐진 추천 상태',
    stage: CallStage.productSelection,
    conversationId: 1003,
    response: AgentResponse.fromJson({
      'conversationId': 1003,
      'status': 'waiting_user_confirmation',
      'stage': 'product_confirming',
      'assistantMessage':
          '고당도 망고수박으로, 가격은 24,900원입니다. 여름철 간식으로 인기가 많은 상품이에요. 이 상품으로 주문할까요?',
      'recommendations': [
        {
          'recommendationItemId': 501,
          'productId': 0,
          'productName': '산지직송 고당도 망고수박 4kg 5kg 프리미엄 선물용',
          'brand': '싱싱농장',
          'price': 24900,
          'rank': 0,
          'deliveryInfo': '새벽배송 가능',
          'deliveryFee': 0,
          'rating': 4.8,
          'reviewCount': 231,
          'imageUrl':
              'https://images.unsplash.com/photo-1563114773-84221bd62daa?auto=format&fit=crop&w=800&q=80',
          'productUrl': 'https://example.com/product/501',
          'platform': 'naver',
          'reason': '후기가 많고 당도가 높다고 평가된 상품이에요.',
          'isSelected': false,
          'isOrderable': true,
        },
      ],
      'selectedProduct': {
        'image_url':
            'https://images.unsplash.com/photo-1563114773-84221bd62daa?auto=format&fit=crop&w=800&q=80',
      },
    }),
    messages: _messages([
      const _PreviewMessage('달콤한 수박을 찾고 싶어', isUser: true),
      const _PreviewMessage(
        '고당도 망고수박으로, 가격은 24,900원입니다. 여름철 간식으로 인기가 많은 상품이에요. 이 상품으로 주문할까요?',
        isUser: false,
      ),
    ]),
  ),
  _CallPreviewScenario(
    title: 'Payment Password',
    subtitle: '결제 비밀번호 입력 패드가 보이는 상태',
    stage: CallStage.payment,
    conversationId: 1004,
    response: AgentResponse.fromJson({
      'conversationId': 1004,
      'status': 'payment_in_progress',
      'stage': 'payment_processing',
      'assistantMessage': '비밀번호를 입력해주세요!',
      'recommendations': [],
      'pendingConfirmation': {
        'type': 'payment',
        'message': '비밀번호를 입력해주세요!',
        'payload': {'subType': 'payment_password'},
      },
    }),
    messages: _messages([
      const _PreviewMessage('응, 결제해줘', isUser: true),
      const _PreviewMessage('비밀번호를 입력해주세요!', isUser: false),
    ]),
  ),
  _CallPreviewScenario(
    title: 'Completed',
    subtitle: '결제 완료 후 마지막 안내 상태',
    stage: CallStage.completed,
    conversationId: 1005,
    response: AgentResponse.fromJson({
      'conversationId': 1005,
      'status': 'order_completed',
      'stage': 'completed',
      'assistantMessage': '구매 완료되었습니다!',
      'recommendations': [],
      'pendingConfirmation': {
        'type': 'payment',
        'message': '구매 완료되었습니다!',
        'payload': {'subType': 'payment_confirm'},
      },
    }),
    messages: _messages([
      const _PreviewMessage('좋아, 진행해줘', isUser: true),
      const _PreviewMessage('구매 완료되었습니다!', isUser: false),
    ]),
  ),
];
