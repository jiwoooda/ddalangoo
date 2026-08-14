import '../../../data/models/agent_model.dart';
import '../models/shopping_flow_models.dart';
import 'shopping_flow_service.dart';

class MockShoppingFlowService extends ShoppingFlowService {
  MockShoppingFlowService();

  static const int _mockUserId = 999;
  static const String _mockUserName = '김영희';
  static const ShoppingAddressViewData _mockAddress = ShoppingAddressViewData(
    label: '기본 배송지',
    recipientName: _mockUserName,
    recipientPhone: '010-1234-5678',
    zipCode: '06236',
    addressLine1: '서울 강남구 테헤란로 123',
    addressLine2: '101동 1203호',
    deliveryRequest: '문 앞에 놓아주세요',
    isDefault: true,
  );

  final Map<int, _MockConversation> _conversations = <int, _MockConversation>{};
  int _nextConversationId = 7000;
  int _nextCartItemId = 40000;

  // 실제 백엔드(LLM) 응답은 "상품명+가격" 한 문장, "추천 이유+담아볼까요?" 한
  // 문장으로 정확히 2문장을 말하고 추천 이유는 절대 생략하지 않는다
  // (response_prompt.py 참고). mock 서비스도 STT/접근성만 대체할 뿐 나머지
  // 흐름은 실제와 동일하게 보여야 해서, 카드에만 있고 말풍선/TTS에는 없던
  // 추천 이유를 여기서도 넣어 실제 응답 형식과 맞춘다.
  String _productPitchMessage(_MockProduct product) {
    return '${product.title}, ${formatPrice(product.price)}원이에요. '
        '${product.reason} 담아볼까요?';
  }

  @override
  Future<int> resolveUserId() async => _mockUserId;

  @override
  Future<String?> resolveUserName({int? userId}) async => _mockUserName;

  @override
  Future<ShoppingAddressViewData?> fetchDefaultAddress({
    required int userId,
    String? fallbackRecipientName,
    String? fallbackPhoneNumber,
  }) async {
    return _mockAddress;
  }

  @override
  Future<AgentResponse> submitMessage({
    required int userId,
    required String message,
    int? conversationId,
    bool redactMessageForLogs = false,
  }) async {
    final trimmed = message.trim();
    if (trimmed.isEmpty) {
      return _idleResponse(conversationId ?? _nextConversationId);
    }

    if (conversationId == null) {
      return _startConversation(userId: userId, message: trimmed);
    }

    final conversation = _conversations[conversationId];
    if (conversation == null) {
      return _startConversation(userId: userId, message: trimmed);
    }

    _advanceIfNeeded(conversation);

    final currentStage = inferViewStage(conversation.response);
    switch (currentStage) {
      case ShoppingFlowViewStage.askProduct:
      case ShoppingFlowViewStage.error:
      case ShoppingFlowViewStage.completed:
        return _beginSearch(conversation, trimmed);
      case ShoppingFlowViewStage.searchingProduct:
      case ShoppingFlowViewStage.cartProcessing:
      case ShoppingFlowViewStage.paymentProcessing:
        _advanceIfNeeded(conversation, force: true);
        return conversation.response;
      case ShoppingFlowViewStage.productSelection:
        return _handleProductSelectionText(conversation, trimmed);
      case ShoppingFlowViewStage.quantitySelection:
        return _handleQuantity(conversation, trimmed);
      case ShoppingFlowViewStage.cartCompleted:
        return _handleCartDecision(conversation, trimmed);
      case ShoppingFlowViewStage.addressConfirmation:
        return _handleAddressDecision(conversation, trimmed);
      case ShoppingFlowViewStage.paymentConfirmation:
        return _handlePaymentDecision(conversation, trimmed);
      case ShoppingFlowViewStage.paymentPassword:
        return _handlePasswordSubmission(conversation, trimmed);
    }
  }

  @override
  Future<AgentResponse> confirmProductAction({
    required AgentResponse response,
    required String action,
  }) async {
    final conversation = _conversations[response.conversationId];
    if (conversation == null) {
      return _idleResponse(response.conversationId);
    }

    _advanceIfNeeded(conversation);

    switch (action) {
      case 'reject':
        conversation.selectedIndex =
            (conversation.selectedIndex + 1) %
            conversation.recommendations.length;
        return _showProductSelection(
          conversation,
          assistantMessage: _productPitchMessage(conversation.selectedProduct),
        );
      case 'add_to_cart':
      case 'order_now':
        return _addSelectedProductToCart(conversation, quantity: 1);
      default:
        return conversation.response;
    }
  }

  @override
  Future<AgentResponse> getConversation(int conversationId) async {
    final conversation = _conversations[conversationId];
    if (conversation == null) {
      return _idleResponse(conversationId);
    }
    _advanceIfNeeded(conversation, force: true);
    return conversation.response;
  }

  @override
  Future<void> cancelConversation(int conversationId) async {
    _conversations.remove(conversationId);
  }

  @override
  Future<List<ShoppingCartItemViewData>> fetchUserCartItems({
    required int userId,
    int? conversationId,
  }) async {
    final conversation = _resolveConversation(
      userId: userId,
      conversationId: conversationId,
    );
    if (conversation == null) {
      return const <ShoppingCartItemViewData>[];
    }
    return _viewCartItems(conversation);
  }

  @override
  Future<List<ShoppingCartItemViewData>> updateCartItemQuantity({
    required int userId,
    int? conversationId,
    required ShoppingCartItemViewData item,
    required int quantity,
  }) async {
    final conversation = _resolveConversation(
      userId: userId,
      conversationId: conversationId,
    );
    if (conversation == null) {
      return const <ShoppingCartItemViewData>[];
    }

    final safeQuantity = quantity < 0 ? 0 : quantity;
    final itemIndex = conversation.cartItems.indexWhere(
      (cartItem) => cartItem.id == item.cartItemId,
    );
    if (itemIndex < 0) {
      return _viewCartItems(conversation);
    }

    if (safeQuantity <= 0) {
      conversation.cartItems.removeAt(itemIndex);
    } else {
      conversation.cartItems[itemIndex] = conversation.cartItems[itemIndex]
          .copyWith(quantity: safeQuantity);
    }

    return _viewCartItems(conversation);
  }

  @override
  Future<AgentResponse> sendWebviewResult({
    required int conversationId,
    int? orderId,
    int? paymentId,
    required String result,
    Map<String, dynamic>? extraData,
  }) async {
    return getConversation(conversationId);
  }

  Future<AgentResponse> _startConversation({
    required int userId,
    required String message,
  }) async {
    final conversationId = _nextConversationId++;
    final conversation = _MockConversation(
      conversationId: conversationId,
      userId: userId,
      cartId: conversationId * 100,
      recommendations: const <_MockProduct>[],
      response: _idleResponse(conversationId),
      cartItems: <_MockCartItem>[],
    );
    _conversations[conversationId] = conversation;
    return _beginSearch(conversation, message);
  }

  AgentResponse _beginSearch(_MockConversation conversation, String message) {
    final normalizedQuery = message.trim();
    final recommendations = _recommendationsForQuery(normalizedQuery);
    conversation
      ..query = normalizedQuery
      ..recommendations = recommendations
      ..selectedIndex = 0;

    final searchingResponse = AgentResponse(
      conversationId: conversation.conversationId,
      status: 'success',
      stage: 'searching_products',
      assistantMessage: '"$normalizedQuery" 상품을 찾고 있어요.',
      asyncStatus: const <String, dynamic>{'message': '딸랑구가 추천 상품을 정리하고 있어요.'},
    );

    final recommendedResponse = _productSelectionResponse(
      conversation,
      assistantMessage: _productPitchMessage(conversation.selectedProduct),
    );

    return _setResponse(
      conversation,
      searchingResponse,
      nextResponse: recommendedResponse,
      delay: const Duration(milliseconds: 900),
    );
  }

  AgentResponse _handleProductSelectionText(
    _MockConversation conversation,
    String message,
  ) {
    final normalized = message.toLowerCase();
    if (normalized.contains('다른')) {
      conversation.selectedIndex =
          (conversation.selectedIndex + 1) %
          conversation.recommendations.length;
      return _showProductSelection(
        conversation,
        assistantMessage: _productPitchMessage(conversation.selectedProduct),
      );
    }
    if (normalized.contains('담') ||
        normalized.contains('주문') ||
        normalized.contains('이걸로') ||
        normalized.contains('좋아')) {
      return _addSelectedProductToCart(
        conversation,
        quantity: _quantityFromMessage(message) ?? 1,
      );
    }
    return _showProductSelection(
      conversation,
      assistantMessage: '버튼으로 고르거나 "장바구니에 담아줘"라고 말해보세요.',
    );
  }

  AgentResponse _handleQuantity(
    _MockConversation conversation,
    String message,
  ) {
    final quantity = _quantityFromMessage(message);
    if (quantity == null || quantity <= 0) {
      return _setResponse(
        conversation,
        AgentResponse(
          conversationId: conversation.conversationId,
          status: 'success',
          stage: 'awaiting_quantity',
          assistantMessage: '수량을 한 번 더 말씀해주세요. 예를 들면 2개처럼요.',
          selectedProduct: conversation.selectedProduct.toSelectedProductMap(),
          pendingConfirmation: <String, dynamic>{
            'type': 'quantity',
            'payload': <String, dynamic>{
              'productName': conversation.selectedProduct.title,
            },
          },
        ),
      );
    }

    return _addSelectedProductToCart(conversation, quantity: quantity);
  }

  AgentResponse _addSelectedProductToCart(
    _MockConversation conversation, {
    required int quantity,
  }) {
    final selectedProduct = conversation.selectedProduct;
    final cartItem = _MockCartItem(
      id: _nextCartItemId++,
      product: selectedProduct,
      quantity: quantity,
    );
    final existingIndex = conversation.cartItems.indexWhere(
      (item) =>
          item.product.recommendationItemId ==
          selectedProduct.recommendationItemId,
    );
    if (existingIndex >= 0) {
      conversation.cartItems[existingIndex] = cartItem.copyWith(
        id: conversation.cartItems[existingIndex].id,
      );
    } else {
      conversation.cartItems.add(cartItem);
    }

    final processingResponse = AgentResponse(
      conversationId: conversation.conversationId,
      status: 'success',
      stage: 'cart_processing',
      assistantMessage: '${selectedProduct.title} $quantity개를 장바구니에 담는 중이에요.',
      selectedProduct: selectedProduct.toSelectedProductMap(),
      order: <String, dynamic>{
        'orderId': conversation.conversationId * 10 + 1,
        'quantity': quantity,
      },
      asyncStatus: <String, dynamic>{
        'message': '${selectedProduct.title} $quantity개를 장바구니에 담고 있어요.',
      },
    );

    final completedResponse = AgentResponse(
      conversationId: conversation.conversationId,
      status: 'success',
      stage: 'cart_ready',
      assistantMessage: '장바구니에 담았어요. 더 구매하시겠어요, 아니면 결제할까요?',
      selectedProduct: selectedProduct.toSelectedProductMap(),
      cart: _cartMap(conversation.cartItems),
      pendingConfirmation: const <String, dynamic>{
        'type': 'payment',
        'payload': <String, dynamic>{'subType': 'continue_shopping'},
      },
    );

    return _setResponse(
      conversation,
      processingResponse,
      nextResponse: completedResponse,
      delay: const Duration(milliseconds: 900),
    );
  }

  AgentResponse _handleCartDecision(
    _MockConversation conversation,
    String message,
  ) {
    final normalized = message.toLowerCase();
    if (normalized.contains('결제') || normalized.contains('주문')) {
      final response = AgentResponse(
        conversationId: conversation.conversationId,
        status: 'success',
        stage: 'address_confirmation',
        assistantMessage: '배송지를 확인해주세요. 맞으면 "네, 맞아요"라고 말씀해주세요.',
        cart: _cartMap(conversation.cartItems),
        deliveryAddress: _addressMap(),
        pendingConfirmation: const <String, dynamic>{
          'type': 'address',
          'payload': <String, dynamic>{'addressId': 1},
        },
      );
      return _setResponse(conversation, response);
    }

    if (normalized.contains('더') && normalized.contains('구매')) {
      return _setResponse(
        conversation,
        AgentResponse(
          conversationId: conversation.conversationId,
          status: 'success',
          stage: 'idle',
          assistantMessage: '좋아요. 또 어떤 상품이 필요하세요? 예를 들어 "삼겹살 1근 구매해줘"처럼 말해보세요.',
          cart: _cartMap(conversation.cartItems),
        ),
      );
    }

    return _beginSearch(conversation, message);
  }

  AgentResponse _handleAddressDecision(
    _MockConversation conversation,
    String message,
  ) {
    final normalized = message.toLowerCase();
    if (normalized.contains('네') || normalized.contains('맞')) {
      final totalPrice = conversation.cartItems.fold<int>(
        0,
        (sum, item) => sum + item.totalPrice,
      );
      final response = AgentResponse(
        conversationId: conversation.conversationId,
        status: 'success',
        stage: 'payment_confirmation',
        assistantMessage: '총 ${formatPrice(totalPrice)}원이에요. 결제를 진행할까요?',
        cart: _cartMap(conversation.cartItems),
        deliveryAddress: _addressMap(),
        pendingConfirmation: const <String, dynamic>{
          'type': 'payment',
          'payload': <String, dynamic>{'subType': 'confirm'},
        },
      );
      return _setResponse(conversation, response);
    }

    return _setResponse(
      conversation,
      AgentResponse(
        conversationId: conversation.conversationId,
        status: 'success',
        stage: 'address_confirmation',
        assistantMessage: '지금 mock demo에서는 기본 배송지만 보여드리고 있어요. 이 주소로 진행할까요?',
        cart: _cartMap(conversation.cartItems),
        deliveryAddress: _addressMap(),
        pendingConfirmation: const <String, dynamic>{
          'type': 'address',
          'payload': <String, dynamic>{'addressId': 1},
        },
      ),
    );
  }

  AgentResponse _handlePaymentDecision(
    _MockConversation conversation,
    String message,
  ) {
    final normalized = message.toLowerCase();
    if (normalized.contains('네') ||
        normalized.contains('진행') ||
        normalized.contains('결제')) {
      final response = AgentResponse(
        conversationId: conversation.conversationId,
        status: 'success',
        stage: 'payment_password',
        assistantMessage: '비밀번호를 입력해주세요.',
        cart: _cartMap(conversation.cartItems),
        deliveryAddress: _addressMap(),
        pendingConfirmation: const <String, dynamic>{
          'type': 'payment',
          'payload': <String, dynamic>{'subType': 'payment_password'},
        },
      );
      return _setResponse(conversation, response);
    }

    return _setResponse(
      conversation,
      AgentResponse(
        conversationId: conversation.conversationId,
        status: 'success',
        stage: 'payment_confirmation',
        assistantMessage: '상품과 배송지를 다시 보고 있어요. 준비되면 "네, 진행해줘"라고 말씀해주세요.',
        cart: _cartMap(conversation.cartItems),
        deliveryAddress: _addressMap(),
        pendingConfirmation: const <String, dynamic>{
          'type': 'payment',
          'payload': <String, dynamic>{'subType': 'confirm'},
        },
      ),
    );
  }

  AgentResponse _handlePasswordSubmission(
    _MockConversation conversation,
    String message,
  ) {
    final normalized = message.replaceAll(RegExp(r'[^0-9]'), '');
    if (normalized.isEmpty) {
      return _setResponse(
        conversation,
        AgentResponse(
          conversationId: conversation.conversationId,
          status: 'success',
          stage: 'payment_password',
          assistantMessage: '숫자로 된 비밀번호를 입력해주세요.',
          cart: _cartMap(conversation.cartItems),
          deliveryAddress: _addressMap(),
          pendingConfirmation: const <String, dynamic>{
            'type': 'payment',
            'payload': <String, dynamic>{'subType': 'payment_password'},
          },
        ),
      );
    }

    final processingResponse = AgentResponse(
      conversationId: conversation.conversationId,
      status: 'success',
      stage: 'payment_processing',
      assistantMessage: '결제를 진행하고 있어요.',
      cart: _cartMap(conversation.cartItems),
      deliveryAddress: _addressMap(),
      payment: <String, dynamic>{
        'paymentId': conversation.conversationId * 10 + 2,
        'status': 'processing',
      },
      asyncStatus: const <String, dynamic>{
        'message': '주문서를 확인하고 결제를 승인하고 있어요.',
      },
    );

    final completedResponse = AgentResponse(
      conversationId: conversation.conversationId,
      status: 'success',
      stage: 'completed',
      assistantMessage: '결제가 완료되었어요. 주문이 접수되었어요.',
      cart: _cartMap(conversation.cartItems),
      deliveryAddress: _addressMap(),
      order: <String, dynamic>{
        'orderId': conversation.conversationId * 10 + 1,
        'status': 'placed',
      },
      payment: <String, dynamic>{
        'paymentId': conversation.conversationId * 10 + 2,
        'status': 'completed',
      },
    );

    return _setResponse(
      conversation,
      processingResponse,
      nextResponse: completedResponse,
      delay: const Duration(milliseconds: 1200),
    );
  }

  AgentResponse _showProductSelection(
    _MockConversation conversation, {
    required String assistantMessage,
  }) {
    return _setResponse(
      conversation,
      _productSelectionResponse(
        conversation,
        assistantMessage: assistantMessage,
      ),
    );
  }

  AgentResponse _productSelectionResponse(
    _MockConversation conversation, {
    required String assistantMessage,
  }) {
    final selectedProduct = conversation.selectedProduct;
    return AgentResponse(
      conversationId: conversation.conversationId,
      status: 'success',
      stage: 'product_selection',
      assistantMessage: assistantMessage,
      recommendations: conversation.recommendations
          .map((product) => product.toRecommendation())
          .toList(growable: false),
      selectedProduct: selectedProduct.toSelectedProductMap(),
      pendingConfirmation: <String, dynamic>{
        'type': 'product',
        'payload': <String, dynamic>{
          'recommendationItemId': selectedProduct.recommendationItemId,
          'actions': <String>['add_to_cart', 'reject'],
        },
      },
    );
  }

  AgentResponse _setResponse(
    _MockConversation conversation,
    AgentResponse response, {
    AgentResponse? nextResponse,
    Duration? delay,
  }) {
    conversation.response = response;
    conversation.nextResponse = nextResponse;
    conversation.autoAdvanceAt = nextResponse == null || delay == null
        ? null
        : DateTime.now().add(delay);
    return response;
  }

  void _advanceIfNeeded(_MockConversation conversation, {bool force = false}) {
    if (conversation.nextResponse == null) {
      return;
    }
    if (!force &&
        conversation.autoAdvanceAt != null &&
        DateTime.now().isBefore(conversation.autoAdvanceAt!)) {
      return;
    }
    conversation.response = conversation.nextResponse!;
    conversation.nextResponse = null;
    conversation.autoAdvanceAt = null;
  }

  AgentResponse _idleResponse(int conversationId) {
    return AgentResponse(
      conversationId: conversationId,
      status: 'success',
      stage: 'idle',
      // 예시 답변 칩을 없앤 대신, 같은 예시를 멘트에 그대로 녹였다.
      assistantMessage: '어떤 상품이 필요하세요? 예를 들어 "토마토 사고 싶어"처럼 말해보세요.',
    );
  }

  List<_MockProduct> _recommendationsForQuery(String query) {
    final normalized = query.toLowerCase();
    if (normalized.contains('토마토')) {
      return const <_MockProduct>[
        _MockProduct(
          recommendationItemId: 101,
          title: '대추방울토마토 750g',
          brand: '프레시팜',
          price: 8900,
          platform: 'kurly',
          optionText: '1팩',
          deliveryInfo: '새벽배송',
          reason: '가볍게 먹기 좋아서 첫 후보로 골랐어요.',
        ),
        _MockProduct(
          recommendationItemId: 102,
          title: '완숙 토마토 1kg',
          brand: '산지직송',
          price: 11900,
          platform: 'coupang',
          optionText: '1박스',
          deliveryInfo: '로켓배송',
          reason: '양이 넉넉해서 가족용으로 좋아요.',
        ),
        _MockProduct(
          recommendationItemId: 103,
          title: '유기농 찰토마토 900g',
          brand: '오늘농장',
          price: 12900,
          platform: 'naver',
          optionText: '900g',
          deliveryInfo: '일반배송',
          reason: '유기농 선호가 있을 때 잘 맞는 후보예요.',
        ),
      ];
    }
    if (normalized.contains('삼겹살')) {
      return const <_MockProduct>[
        _MockProduct(
          recommendationItemId: 201,
          title: '한돈 삼겹살 구이용 600g',
          brand: '정육각',
          price: 18900,
          platform: 'kurly',
          optionText: '냉장',
          deliveryInfo: '새벽배송',
          reason: '구이용으로 바로 쓰기 좋은 두께예요.',
        ),
        _MockProduct(
          recommendationItemId: 202,
          title: '국내산 삼겹살 1kg',
          brand: '미트하우스',
          price: 27900,
          platform: 'coupang',
          optionText: '대용량',
          deliveryInfo: '로켓배송',
          reason: '양을 넉넉히 보고 고른 후보예요.',
        ),
        _MockProduct(
          recommendationItemId: 203,
          title: '숙성 삼겹살 보쌈용 800g',
          brand: '푸드셀렉트',
          price: 23900,
          platform: 'naver',
          optionText: '숙성육',
          deliveryInfo: '일반배송',
          reason: '풍미를 중요하게 볼 때 어울리는 후보예요.',
        ),
      ];
    }
    if (normalized.contains('딸기')) {
      return const <_MockProduct>[
        _MockProduct(
          recommendationItemId: 301,
          title: '설향 딸기 500g',
          brand: '달콤농원',
          price: 9900,
          platform: 'kurly',
          optionText: '1팩',
          deliveryInfo: '새벽배송',
          reason: '가장 인기가 많고 바로 먹기 좋아요.',
        ),
        _MockProduct(
          recommendationItemId: 302,
          title: '프리미엄 딸기 750g',
          brand: '베리마켓',
          price: 14900,
          platform: 'coupang',
          optionText: '대용량',
          deliveryInfo: '로켓배송',
          reason: '넉넉하게 담고 싶을 때 좋은 후보예요.',
        ),
        _MockProduct(
          recommendationItemId: 303,
          title: '유기농 딸기 450g',
          brand: '그린베리',
          price: 13900,
          platform: 'naver',
          optionText: '친환경',
          deliveryInfo: '일반배송',
          reason: '친환경 옵션을 선호할 때 잘 맞아요.',
        ),
      ];
    }
    if (normalized.contains('우유')) {
      return const <_MockProduct>[
        _MockProduct(
          recommendationItemId: 501,
          title: '서울우유 락토프리 1L',
          brand: '서울우유',
          price: 3900,
          platform: 'kurly',
          optionText: '1개',
          deliveryInfo: '새벽배송',
          reason: '유당불내증에도 편하게 드실 수 있는 제품이라 추천해요.',
        ),
        _MockProduct(
          recommendationItemId: 502,
          title: '일반 우유 1L',
          brand: '매일유업',
          price: 2900,
          platform: 'coupang',
          optionText: '1개',
          deliveryInfo: '로켓배송',
          reason: '가격이 가장 저렴한 후보예요.',
        ),
        _MockProduct(
          recommendationItemId: 503,
          title: '저지방 락토프리 900ml',
          brand: '매일유업',
          price: 3500,
          platform: 'naver',
          optionText: '900ml',
          deliveryInfo: '일반배송',
          reason: '저지방을 선호하실 때 잘 맞는 후보예요.',
        ),
      ];
    }
    // 재구매 데모(김열무 페르소나)용: "대파 다시 사줘"처럼 상품명이 그대로
    // 들어오는 경우를 위한 항목. 첫 후보를 가장 저렴하게 배치해서 "저가
    // 선호" 추천 시나리오와 맞아떨어지게 했다.
    if (normalized.contains('대파')) {
      return const <_MockProduct>[
        _MockProduct(
          recommendationItemId: 601,
          title: '대파 1단',
          brand: '산지직송',
          price: 1980,
          platform: 'coupang',
          optionText: '1단',
          deliveryInfo: '로켓배송',
          reason: '지난번과 같은 상품 중 가장 저렴한 곳으로 골랐어요.',
        ),
        _MockProduct(
          recommendationItemId: 602,
          title: '국내산 대파 1단',
          brand: '자연마켓',
          price: 2900,
          platform: 'kurly',
          optionText: '1단',
          deliveryInfo: '새벽배송',
          reason: '신선도를 더 중요하게 볼 때 좋은 후보예요.',
        ),
        _MockProduct(
          recommendationItemId: 603,
          title: '프리미엄 대파 2단',
          brand: '그린팜',
          price: 4900,
          platform: 'naver',
          optionText: '2단',
          deliveryInfo: '일반배송',
          reason: '넉넉하게 담고 싶을 때 좋은 후보예요.',
        ),
      ];
    }
    return const <_MockProduct>[
      _MockProduct(
        recommendationItemId: 401,
        title: '계란 10구',
        brand: '신선란',
        price: 4900,
        platform: 'coupang',
        optionText: '특란',
        deliveryInfo: '로켓배송',
        reason: '자주 찾는 기본 장보기 품목이라 먼저 보여드려요.',
      ),
      _MockProduct(
        recommendationItemId: 402,
        title: '바나나 한 송이',
        brand: '후레쉬',
        price: 3900,
        platform: 'kurly',
        optionText: '1송이',
        deliveryInfo: '새벽배송',
        reason: '부담 없이 담기 좋아서 함께 추천해요.',
      ),
      _MockProduct(
        recommendationItemId: 403,
        title: '두부 300g',
        brand: '풀무원',
        price: 2300,
        platform: 'naver',
        optionText: '부침용',
        deliveryInfo: '일반배송',
        reason: '간단한 장보기 데모용으로 보기 쉬운 상품이에요.',
      ),
    ];
  }

  Map<String, dynamic> _cartMap(List<_MockCartItem> items) {
    return <String, dynamic>{
      'cartId': items.isEmpty ? null : items.first.cartId,
      'items': items
          .map(
            (item) => <String, dynamic>{
              'cartId': item.cartId,
              'cartItemId': item.id,
              'productId': item.product.recommendationItemId,
              'productOptionId': null,
              'productName': item.product.title,
              'brand': item.product.brand,
              'optionText': item.product.optionText,
              'platform': item.product.platform,
              'unitPrice': item.product.price,
              'quantity': item.quantity,
              'totalPrice': item.totalPrice,
            },
          )
          .toList(growable: false),
    };
  }

  Map<String, dynamic> _addressMap() {
    return const <String, dynamic>{
      'addressLabel': '기본 배송지',
      'recipientName': _mockUserName,
      'recipientPhone': '010-1234-5678',
      'zipCode': '06236',
      'addressLine1': '서울 강남구 테헤란로 123',
      'addressLine2': '101동 1203호',
      'deliveryRequest': '문 앞에 놓아주세요',
      'isDefault': true,
    };
  }

  int? _quantityFromMessage(String message) {
    final digitMatch = RegExp(r'(\d+)').firstMatch(message);
    if (digitMatch != null) {
      return int.tryParse(digitMatch.group(1)!);
    }

    const wordToNumber = <String, int>{
      '한': 1,
      '하나': 1,
      '두': 2,
      '둘': 2,
      '세': 3,
      '셋': 3,
      '네': 4,
      '넷': 4,
      '다섯': 5,
    };
    for (final entry in wordToNumber.entries) {
      if (message.contains(entry.key)) {
        return entry.value;
      }
    }
    return null;
  }

  _MockConversation? _resolveConversation({
    required int userId,
    int? conversationId,
  }) {
    if (conversationId != null) {
      return _conversations[conversationId];
    }

    for (final conversation in _conversations.values.toList().reversed) {
      if (conversation.userId == userId) {
        return conversation;
      }
    }
    return null;
  }

  List<ShoppingCartItemViewData> _viewCartItems(
    _MockConversation conversation,
  ) {
    return conversation.cartItems
        .map(
          (item) => ShoppingCartItemViewData(
            cartId: conversation.cartId,
            cartItemId: item.id,
            product: ShoppingProductViewData(
              recommendationItemId: item.product.recommendationItemId,
              productId: item.product.recommendationItemId,
              title: item.product.title,
              brand: item.product.brand,
              optionText: item.product.optionText,
              deliveryInfo: item.product.deliveryInfo,
              reason: item.product.reason,
              platform: item.product.platform,
              price: item.product.price,
            ),
            quantity: item.quantity,
            totalPrice: item.totalPrice,
          ),
        )
        .toList(growable: false);
  }
}

class _MockConversation {
  _MockConversation({
    required this.conversationId,
    required this.userId,
    required this.cartId,
    required this.recommendations,
    required this.response,
    required this.cartItems,
  });

  final int conversationId;
  final int userId;
  final int cartId;
  String? query;
  List<_MockProduct> recommendations;
  int selectedIndex = 0;
  List<_MockCartItem> cartItems;
  AgentResponse response;
  DateTime? autoAdvanceAt;
  AgentResponse? nextResponse;

  _MockProduct get selectedProduct => recommendations[selectedIndex];
}

class _MockProduct {
  const _MockProduct({
    required this.recommendationItemId,
    required this.title,
    required this.brand,
    required this.price,
    required this.platform,
    required this.optionText,
    required this.deliveryInfo,
    required this.reason,
  });

  final int recommendationItemId;
  final String title;
  final String brand;
  final int price;
  final String platform;
  final String optionText;
  final String deliveryInfo;
  final String reason;

  RecommendationItemInAgent toRecommendation() {
    return RecommendationItemInAgent(
      recommendationItemId: recommendationItemId,
      productId: recommendationItemId,
      productName: title,
      brand: brand,
      price: price,
      rank: recommendationItemId,
      optionText: optionText,
      deliveryInfo: deliveryInfo,
      platform: platform,
      reason: reason,
    );
  }

  Map<String, dynamic> toSelectedProductMap() {
    return <String, dynamic>{
      'recommendationItemId': recommendationItemId,
      'productId': recommendationItemId,
      'productName': title,
      'brand': brand,
      'price': price,
      'platform': platform,
      'optionText': optionText,
      'deliveryInfo': deliveryInfo,
      'reason': reason,
    };
  }
}

class _MockCartItem {
  const _MockCartItem({
    required this.id,
    required this.product,
    required this.quantity,
  });

  final int id;
  final _MockProduct product;
  final int quantity;
  int get cartId => product.recommendationItemId * 100;

  int get totalPrice => product.price * quantity;

  _MockCartItem copyWith({int? id, _MockProduct? product, int? quantity}) {
    return _MockCartItem(
      id: id ?? this.id,
      product: product ?? this.product,
      quantity: quantity ?? this.quantity,
    );
  }
}
