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
              ),
            ),
          ),
          const SizedBox(height: 24),
          const _SectionTitle(
            title: 'Call Scenarios',
            subtitle: '통화 상태별 디자인을 실제 화면 그대로 볼 수 있어요.',
          ),
          _PreviewTile(
            title: 'Shopping Journey Storyboard',
            subtitle: '첫 인사부터 상품 추천, 웹뷰, 배송지 확인까지 예시 흐름으로 살펴봐요.',
            onTap: () => _openPage(context, const _ShoppingJourneyPreviewScreen()),
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

class _ShoppingJourneyPreviewScreen extends StatelessWidget {
  const _ShoppingJourneyPreviewScreen();

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFFFDF0F3),
      appBar: AppBar(
        title: const Text('Shopping Journey'),
        backgroundColor: const Color(0xFFFDF0F3),
      ),
      body: ListView(
        padding: const EdgeInsets.fromLTRB(20, 16, 20, 32),
        children: [
          const _SectionTitle(
            title: 'Journey Steps',
            subtitle: '실제 사용자가 겪는 흐름처럼 단계별 UI를 이어서 확인할 수 있어요.',
          ),
          for (final step in _shoppingJourneySteps)
            _PreviewTile(
              title: '${step.index}. ${step.title}',
              subtitle: step.subtitle,
              onTap: () => step.open(context),
            ),
        ],
      ),
    );
  }
}

class _ShoppingJourneyStep {
  const _ShoppingJourneyStep({
    required this.index,
    required this.title,
    required this.subtitle,
    required this.open,
  });

  final int index;
  final String title;
  final String subtitle;
  final void Function(BuildContext context) open;
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

List<Map<String, dynamic>> _messagesWithProductCard({
  required List<_PreviewMessage> items,
  RecommendationItemInAgent? recommendation,
  dynamic selectedProduct,
}) {
  final messages = _messages(items);
  if (recommendation != null) {
    messages.add({
      'type': 'product_card',
      'recommendation': recommendation,
      'selectedProduct': selectedProduct,
      'recommendationItemId': recommendation.recommendationItemId,
      'time': DateTime(2026, 5, 25, 12, 0),
    });
  }
  return messages;
}

class _PreviewMessage {
  const _PreviewMessage(this.text, {required this.isUser});

  final String text;
  final bool isUser;
}

void _openScenarioPreview(BuildContext context, _CallPreviewScenario scenario) {
  Navigator.of(context).push(
    MaterialPageRoute<void>(
      builder: (_) => ChangeNotifierProvider(
        create: (_) => CallProvider()
          ..loadPreviewState(
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

final AgentResponse _watermelonRecommendationResponse = AgentResponse.fromJson({
  'conversationId': 2003,
  'status': 'waiting_user_confirmation',
  'stage': 'product_confirming',
  'assistantMessage':
      'CJ 신선한 고당도 수박 1kg, 가격은 9,900원이에요. 구매할까요?',
  'recommendations': [
    {
      'recommendationItemId': 701,
      'productId': 301,
      'productName': 'CJ 신선한 고당도 수박 1kg',
      'brand': 'CJ Fresh',
      'price': 9900,
      'rank': 1,
      'deliveryInfo': '일반배송',
      'deliveryFee': 0,
      'rating': 4.7,
      'reviewCount': 182,
      'imageUrl':
          'https://images.unsplash.com/photo-1563114773-84221bd62daa?auto=format&fit=crop&w=800&q=80',
      'productUrl': 'https://example.com/products/watermelon-1kg',
      'platform': 'naver',
      'reason': '가격이 좋고 후기 평점이 높아서 추천드려요.',
      'isSelected': true,
      'isOrderable': true,
    },
  ],
  'selectedProduct': {
    'image_url':
        'https://images.unsplash.com/photo-1563114773-84221bd62daa?auto=format&fit=crop&w=800&q=80',
  },
  'pendingConfirmation': {
    'type': 'product',
    'message': 'CJ 신선한 고당도 수박 1kg, 가격은 9,900원이에요. 구매할까요?',
  },
});

final _CallPreviewScenario _journeyGreetingScenario = _CallPreviewScenario(
  title: '딸랑구 첫 인사',
  subtitle: '첫 고정 인사',
  stage: CallStage.idle,
  conversationId: 2001,
  messages: _messages([
    const _PreviewMessage('김영희님, 무엇을 구매하고 싶으신가요?', isUser: false),
  ]),
);

final _CallPreviewScenario _journeySearchLoadingScenario = _CallPreviewScenario(
  title: '상품 검색 중',
  subtitle: '사용자 요청 직후 로딩 말풍선',
  stage: CallStage.productSelection,
  conversationId: 2002,
  isAwaitingAssistantPresentation: true,
  assistantPresentationMessage: '김영희님을 위한 맞춤 상품을 정리하고 있어요.',
  messages: _messages([
    const _PreviewMessage('김영희님, 무엇을 구매하고 싶으신가요?', isUser: false),
    const _PreviewMessage('신선한 수박 좀 사고 싶어', isUser: true),
  ]),
);

final _CallPreviewScenario _journeyRecommendationScenario = _CallPreviewScenario(
  title: '상품 추천',
  subtitle: '추천 멘트와 상품 카드가 함께 보이는 상태',
  stage: CallStage.productSelection,
  conversationId: 2003,
  response: _watermelonRecommendationResponse,
  messages: _messagesWithProductCard(
    items: [
      const _PreviewMessage('김영희님, 무엇을 구매하고 싶으신가요?', isUser: false),
      const _PreviewMessage('신선한 수박 좀 사고 싶어', isUser: true),
      const _PreviewMessage(
        'CJ 신선한 고당도 수박 1kg, 가격은 9,900원이에요. 구매할까요?',
        isUser: false,
      ),
    ],
    recommendation: _watermelonRecommendationResponse.recommendations.first,
    selectedProduct: _watermelonRecommendationResponse.selectedProduct,
  ),
);

final _CallPreviewScenario _journeyQuantityQuestionScenario = _CallPreviewScenario(
  title: '수량 질문',
  subtitle: '구매 확정 후 몇 개 살지 묻는 상태',
  stage: CallStage.productSelection,
  conversationId: 2004,
  response: AgentResponse.fromJson({
    'conversationId': 2004,
    'status': 'waiting_user_confirmation',
    'stage': 'product_confirming',
    'assistantMessage': '몇 개 구매할까요?',
    'recommendations': _watermelonRecommendationResponse.recommendations
        .map((item) => {
              'recommendationItemId': item.recommendationItemId,
              'productId': item.productId,
              'productName': item.productName,
              'brand': item.brand,
              'price': item.price,
              'rank': item.rank,
              'deliveryInfo': item.deliveryInfo,
              'deliveryFee': item.deliveryFee,
              'rating': item.rating,
              'reviewCount': item.reviewCount,
              'imageUrl': item.imageUrl,
              'productUrl': item.productUrl,
              'platform': item.platform,
              'reason': item.reason,
              'isSelected': item.isSelected,
              'isOrderable': item.isOrderable,
            })
        .toList(),
    'selectedProduct': _watermelonRecommendationResponse.selectedProduct,
    'pendingConfirmation': {
      'type': 'quantity',
      'message': '몇 개 구매할까요?',
    },
  }),
  messages: _messagesWithProductCard(
    items: [
      const _PreviewMessage('김영희님, 무엇을 구매하고 싶으신가요?', isUser: false),
      const _PreviewMessage('신선한 수박 좀 사고 싶어', isUser: true),
      const _PreviewMessage(
        'CJ 신선한 고당도 수박 1kg, 가격은 9,900원이에요. 구매할까요?',
        isUser: false,
      ),
      const _PreviewMessage('그래 구매할래', isUser: true),
      const _PreviewMessage('몇 개 구매할까요?', isUser: false),
    ],
    recommendation: _watermelonRecommendationResponse.recommendations.first,
    selectedProduct: _watermelonRecommendationResponse.selectedProduct,
  ),
);

final _CallPreviewScenario _journeyCartLoadingScenario = _CallPreviewScenario(
  title: '장바구니 담기 준비',
  subtitle: '수량 응답 직후 웹뷰로 넘어가기 전 상태',
  stage: CallStage.productSelection,
  conversationId: 2005,
  isAwaitingAssistantPresentation: true,
  assistantPresentationMessage: '선택하신 상품을 장바구니에 담는 중입니다.',
  messages: _messagesWithProductCard(
    items: [
      const _PreviewMessage('김영희님, 무엇을 구매하고 싶으신가요?', isUser: false),
      const _PreviewMessage('신선한 수박 좀 사고 싶어', isUser: true),
      const _PreviewMessage(
        'CJ 신선한 고당도 수박 1kg, 가격은 9,900원이에요. 구매할까요?',
        isUser: false,
      ),
      const _PreviewMessage('그래 구매할래', isUser: true),
      const _PreviewMessage('몇 개 구매할까요?', isUser: false),
      const _PreviewMessage('1개만 구매할래', isUser: true),
    ],
    recommendation: _watermelonRecommendationResponse.recommendations.first,
    selectedProduct: _watermelonRecommendationResponse.selectedProduct,
  ),
);

final _CallPreviewScenario _journeyAddressConfirmScenario = _CallPreviewScenario(
  title: '배송지 확인',
  subtitle: '장바구니 담기 후 배송지를 확인하는 상태',
  stage: CallStage.payment,
  conversationId: 2006,
  response: AgentResponse.fromJson({
    'conversationId': 2006,
    'status': 'waiting_user_confirmation',
    'stage': 'address_confirming',
    'assistantMessage': '장바구니 담기가 완료되었어요. 배송지는 청파로 100길 맞으시죠?',
    'recommendations': [],
    'pendingConfirmation': {
      'type': 'address',
      'message': '장바구니 담기가 완료되었어요. 배송지는 청파로 100길 맞으시죠?',
    },
  }),
  messages: _messagesWithProductCard(
    items: [
      const _PreviewMessage('김영희님, 무엇을 구매하고 싶으신가요?', isUser: false),
      const _PreviewMessage('신선한 수박 좀 사고 싶어', isUser: true),
      const _PreviewMessage(
        'CJ 신선한 고당도 수박 1kg, 가격은 9,900원이에요. 구매할까요?',
        isUser: false,
      ),
      const _PreviewMessage('그래 구매할래', isUser: true),
      const _PreviewMessage('몇 개 구매할까요?', isUser: false),
      const _PreviewMessage('1개만 구매할래', isUser: true),
      const _PreviewMessage(
        '장바구니 담기가 완료되었어요. 배송지는 청파로 100길 맞으시죠?',
        isUser: false,
      ),
    ],
    recommendation: _watermelonRecommendationResponse.recommendations.first,
    selectedProduct: _watermelonRecommendationResponse.selectedProduct,
  ),
);

final _CallPreviewScenario _journeyAddressYesScenario = _CallPreviewScenario(
  title: '배송지 확인 응답',
  subtitle: '사용자가 배송지를 확인한 다음 단계 직전 상태',
  stage: CallStage.payment,
  conversationId: 2007,
  isAwaitingAssistantPresentation: true,
  assistantPresentationMessage: '결제에 필요한 내용을 천천히 안내하고 있어요.',
  messages: _messagesWithProductCard(
    items: [
      const _PreviewMessage('김영희님, 무엇을 구매하고 싶으신가요?', isUser: false),
      const _PreviewMessage('신선한 수박 좀 사고 싶어', isUser: true),
      const _PreviewMessage(
        'CJ 신선한 고당도 수박 1kg, 가격은 9,900원이에요. 구매할까요?',
        isUser: false,
      ),
      const _PreviewMessage('그래 구매할래', isUser: true),
      const _PreviewMessage('몇 개 구매할까요?', isUser: false),
      const _PreviewMessage('1개만 구매할래', isUser: true),
      const _PreviewMessage(
        '장바구니 담기가 완료되었어요. 배송지는 청파로 100길 맞으시죠?',
        isUser: false,
      ),
      const _PreviewMessage('응 맞아', isUser: true),
    ],
    recommendation: _watermelonRecommendationResponse.recommendations.first,
    selectedProduct: _watermelonRecommendationResponse.selectedProduct,
  ),
);

final List<_ShoppingJourneyStep> _shoppingJourneySteps = [
  _ShoppingJourneyStep(
    index: 1,
    title: '딸랑구 첫 고정 메시지',
    subtitle: '통화가 연결된 뒤 첫 인사',
    open: (context) => _openScenarioPreview(context, _journeyGreetingScenario),
  ),
  _ShoppingJourneyStep(
    index: 2,
    title: '사용자 요청 후 상품 검색',
    subtitle: '“신선한 수박 좀 사고 싶어” 이후 로딩 말풍선',
    open: (context) =>
        _openScenarioPreview(context, _journeySearchLoadingScenario),
  ),
  _ShoppingJourneyStep(
    index: 3,
    title: '상품 추천 카드와 멘트',
    subtitle: '추천 멘트 아래에 상품 카드가 이어지는 상태',
    open: (context) =>
        _openScenarioPreview(context, _journeyRecommendationScenario),
  ),
  _ShoppingJourneyStep(
    index: 4,
    title: '구매 확정 후 수량 질문',
    subtitle: '“그래 구매할래” 이후 “몇 개 구매할까요?”',
    open: (context) =>
        _openScenarioPreview(context, _journeyQuantityQuestionScenario),
  ),
  _ShoppingJourneyStep(
    index: 5,
    title: '수량 응답 후 장바구니 준비',
    subtitle: '“1개만 구매할래” 이후 웹뷰 직전 상태',
    open: (context) =>
        _openScenarioPreview(context, _journeyCartLoadingScenario),
  ),
  _ShoppingJourneyStep(
    index: 6,
    title: '웹뷰와 상태 메시지',
    subtitle: '장바구니 담기 진행 화면',
    open: (context) => UiPreviewScreen._openPage(
      context,
      const PaymentWebViewScreen(
        url: 'about:blank',
        previewMode: true,
        previewTitle: '장바구니 작업',
        previewStatusText: 'CJ 신선한 고당도 수박을 장바구니에 담고 있어요.',
        previewHelperText: '수량과 배송 조건을 확인한 뒤 장바구니에 담는 중이에요.',
        previewStep: 'adding_to_cart',
        previewMessage: '장바구니에 담고 있어요.',
      ),
    ),
  ),
  _ShoppingJourneyStep(
    index: 7,
    title: '배송지 확인',
    subtitle: '장바구니 담기 완료 후 배송지를 묻는 상태',
    open: (context) =>
        _openScenarioPreview(context, _journeyAddressConfirmScenario),
  ),
  _ShoppingJourneyStep(
    index: 8,
    title: '배송지 확인 응답',
    subtitle: '“응 맞아” 이후 다음 안내 전 상태',
    open: (context) =>
        _openScenarioPreview(context, _journeyAddressYesScenario),
  ),
];

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
