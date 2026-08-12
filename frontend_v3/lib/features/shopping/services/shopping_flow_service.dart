import 'package:flutter/material.dart';
import 'package:flutter_dotenv/flutter_dotenv.dart';

import '../../../core/network/api_client.dart';
import '../../../core/services/accessibility_automation_service.dart';
import '../../../core/storage/local_storage.dart';
import '../../../data/models/agent_model.dart';
import '../../../data/models/cart_model.dart';
import '../../../data/repositories/agent_repository.dart';
import '../../../data/repositories/cart_repository.dart';
import '../../../shared/widgets/shopping_progress_stepper.dart';
import '../models/shopping_flow_models.dart';

class ShoppingPreviewAsset {
  const ShoppingPreviewAsset({
    required this.assetPath,
    required this.backgroundColor,
  });

  final String assetPath;
  final Color backgroundColor;
}

class ShoppingFlowService {
  ShoppingFlowService({
    AgentRepository? agentRepository,
    UserRepository? userRepository,
    CartRepository? cartRepository,
  }) : _agentRepository = agentRepository ?? AgentRepository(),
       _userRepository = userRepository ?? UserRepository(),
       _cartRepository = cartRepository ?? CartRepository();

  final AgentRepository _agentRepository;
  final UserRepository _userRepository;
  final CartRepository _cartRepository;

  Future<int> resolveUserId() async {
    final overriddenUserId = _resolveDevUserIdOverride();
    if (overriddenUserId != null) {
      await LocalStorage.saveUserId(overriddenUserId);
      return overriddenUserId;
    }

    return await LocalStorage.getUserId() ?? 1;
  }

  Future<String?> resolveUserName({int? userId}) async {
    final effectiveUserId = userId ?? await resolveUserId();
    try {
      final user = await _userRepository.getUser(effectiveUserId);
      final name = user.name.trim();
      return name.isEmpty ? null : name;
    } catch (error, stackTrace) {
      debugPrint(
        '[ShoppingFlowService] failed to resolve user name: $error\n$stackTrace',
      );
      return null;
    }
  }

  Future<ShoppingAddressViewData?> fetchDefaultAddress({
    required int userId,
    String? fallbackRecipientName,
    String? fallbackPhoneNumber,
  }) async {
    try {
      final response = await ApiClient.dio.get<Map<String, dynamic>>(
        '/api/users/$userId/addresses',
      );
      final addresses = _listOfMap(response.data?['addresses']);
      if (addresses.isEmpty) {
        return ShoppingAddressViewData(
          recipientName: fallbackRecipientName,
          recipientPhone: fallbackPhoneNumber,
        );
      }

      final defaultAddress = addresses.cast<Map<String, dynamic>>().firstWhere(
        (address) => address['isDefault'] == true,
        orElse: () => addresses.first,
      );
      return _addressFromMap(
        defaultAddress,
        fallbackRecipientName: fallbackRecipientName,
        fallbackPhoneNumber: fallbackPhoneNumber,
      );
    } catch (error, stackTrace) {
      debugPrint(
        '[ShoppingFlowService] failed to fetch default address: '
        '$error\n$stackTrace',
      );
      if ((fallbackRecipientName ?? fallbackPhoneNumber) == null) {
        return null;
      }
      return ShoppingAddressViewData(
        recipientName: fallbackRecipientName,
        recipientPhone: fallbackPhoneNumber,
      );
    }
  }

  Future<AgentResponse> submitMessage({
    required int userId,
    required String message,
    int? conversationId,
    bool redactMessageForLogs = false,
  }) {
    if (conversationId == null) {
      return _agentRepository.startShopping(userId: userId, message: message);
    }

    return _agentRepository.sendMessage(
      conversationId: conversationId,
      message: message,
      redactMessageForLogs: redactMessageForLogs,
    );
  }

  Future<AgentResponse> confirmProductAction({
    required AgentResponse response,
    required String action,
  }) async {
    final conversationId = response.conversationId;
    final recommendationItemId = activeRecommendationItemId(response);
    if (recommendationItemId == null) {
      throw StateError('No recommendation item available for confirmation.');
    }
    return _agentRepository.confirmAction(
      conversationId: conversationId,
      recommendationItemId: recommendationItemId,
      action: action,
    );
  }

  Future<AgentResponse> getConversation(int conversationId) {
    return _agentRepository.getConversation(conversationId);
  }

  Future<void> cancelConversation(int conversationId) {
    return _agentRepository.cancelConversation(conversationId);
  }

  Future<List<ShoppingCartItemViewData>> fetchUserCartItems({
    required int userId,
    int? conversationId,
  }) async {
    final cart = await _cartRepository.getUserCart(userId);
    return cart.items
        .map((item) => _cartItemFromResponse(item, cartId: cart.cartId))
        .toList(growable: false);
  }

  Future<List<ShoppingCartItemViewData>> updateCartItemQuantity({
    required int userId,
    int? conversationId,
    required ShoppingCartItemViewData item,
    required int quantity,
  }) async {
    final cartId = item.cartId;
    final cartItemId = item.cartItemId;
    final productId = item.product.productId;

    if (cartId == null || cartItemId == null || productId == null) {
      throw StateError('장바구니 수량 조절에 필요한 상품 정보가 부족합니다.');
    }

    final safeQuantity = quantity < 0 ? 0 : quantity;
    if (safeQuantity == item.quantity) {
      return fetchUserCartItems(userId: userId, conversationId: conversationId);
    }

    if (safeQuantity <= 0) {
      await _cartRepository.deleteCartItem(
        cartId: cartId,
        cartItemId: cartItemId,
      );
      return fetchUserCartItems(userId: userId, conversationId: conversationId);
    }

    if (safeQuantity > item.quantity) {
      await _cartRepository.addCartItem(
        cartId: cartId,
        productId: productId,
        productOptionId: item.product.productOptionId,
        quantity: safeQuantity - item.quantity,
      );
    } else {
      await _cartRepository.deleteCartItem(
        cartId: cartId,
        cartItemId: cartItemId,
      );
      await _cartRepository.addCartItem(
        cartId: cartId,
        productId: productId,
        productOptionId: item.product.productOptionId,
        quantity: safeQuantity,
      );
    }

    return fetchUserCartItems(userId: userId, conversationId: conversationId);
  }

  Future<AgentResponse> sendWebviewResult({
    required int conversationId,
    int? orderId,
    int? paymentId,
    required String result,
    Map<String, dynamic>? extraData,
  }) {
    return _agentRepository.sendWebviewResult(
      conversationId: conversationId,
      orderId: orderId,
      paymentId: paymentId,
      result: result,
      extraData: extraData,
    );
  }

  Future<void> startAutomationTask(AutomationTaskInAgent task) {
    return AccessibilityAutomationService.instance.setAutomationTask(
      AccessibilityAutomationTask(
        taskId: task.taskId,
        taskType: task.taskType,
        conversationId: task.conversationId,
        userId: task.userId,
        targetProductName: task.targetProductName ?? '',
        searchKeyword: task.searchKeyword ?? '',
        optionName: task.optionName ?? '',
        quantity: task.quantity,
        platform: task.platform ?? AccessibilityAutomationPlatform.unknown,
        packageName: task.packageName,
        currentStep:
            task.currentStep ?? AccessibilityAutomationStep.openSearch,
        cartItemId: task.cartItemId,
        orderId: task.orderId,
        paymentId: task.paymentId,
        metadata: task.metadata,
      ),
    );
  }

  Future<AgentResponse?> consumeAndSendAutomationResult({
    required int conversationId,
  }) async {
    final result =
        await AccessibilityAutomationService.instance.consumeAutomationResult();
    final taskId = result?['taskId']?.toString().trim();
    if (result == null || taskId == null || taskId.isEmpty) {
      return null;
    }
    debugPrint(
      'AutomationResult taskId=${result['taskId']} backend POST '
      'status=${result['status']}',
    );
    final request = AutomationResultRequest.fromRuntimeResult(result);
    final updatedResponse = await _agentRepository.sendAutomationResult(
      conversationId: conversationId,
      result: request.toJson(),
    );
    if (_shouldReturnAfterProductSearch(result)) {
      final returned = await AccessibilityAutomationService.instance
          .returnToDdalangooApp();
      debugPrint(
        'AutomationResult taskId=${result['taskId']} returnToDdalangoo '
        'success=$returned',
      );
    }
    return updatedResponse;
  }

  bool _shouldReturnAfterProductSearch(Map<String, dynamic> result) {
    return result['status']?.toString() == 'completed' &&
        result['taskType']?.toString() ==
            AccessibilityAutomationTaskType.productSearch &&
        result['resultType']?.toString() == 'product_search_collected';
  }

  ShoppingFlowViewStage inferViewStage(AgentResponse? response) {
    if (response == null) {
      return ShoppingFlowViewStage.askProduct;
    }

    final pendingType = pendingTypeOf(response);
    final pendingSubType = pendingSubTypeOf(response);
    final stage = response.stage.toLowerCase();
    final message = response.assistantMessage.trim();

    if (stage == 'completed' || message.contains('결제가 완료')) {
      return ShoppingFlowViewStage.completed;
    }
    if (stage == 'failed' || response.error != null) {
      return ShoppingFlowViewStage.error;
    }
    if (pendingType == 'payment' && pendingSubType == 'continue_shopping') {
      return ShoppingFlowViewStage.cartCompleted;
    }
    if (pendingType == 'address' || stage.contains('address')) {
      return ShoppingFlowViewStage.addressConfirmation;
    }
    if (pendingType == 'payment' &&
        (pendingSubType == 'payment_password' || message.contains('비밀번호'))) {
      return ShoppingFlowViewStage.paymentPassword;
    }
    if (pendingType == 'payment') {
      return stage.contains('payment_processing')
          ? ShoppingFlowViewStage.paymentProcessing
          : ShoppingFlowViewStage.paymentConfirmation;
    }
    if (pendingType == 'automation_task' ||
        pendingType == 'webview_task' ||
        response.automationTask != null ||
        (response.uiCommand is Map &&
            (response.uiCommand as Map)['type'] == 'open_webview') ||
        stage.contains('cart_processing') ||
        stage.contains('webview_cart')) {
      return ShoppingFlowViewStage.cartProcessing;
    }
    if (stage.contains('payment_processing')) {
      return ShoppingFlowViewStage.paymentProcessing;
    }
    if (pendingType == 'quantity' || message.contains('몇 개')) {
      return ShoppingFlowViewStage.quantitySelection;
    }
    if (pendingType == 'product' ||
        response.recommendations.isNotEmpty ||
        _mapOf(response.selectedProduct) != null) {
      return ShoppingFlowViewStage.productSelection;
    }
    if (stage.contains('searching')) {
      return ShoppingFlowViewStage.searchingProduct;
    }
    if (_isRestartPrompt(response)) {
      return ShoppingFlowViewStage.askProduct;
    }
    return ShoppingFlowViewStage.askProduct;
  }

  ShoppingProgressStep progressStepFor(ShoppingFlowViewStage stage) {
    return switch (stage) {
      ShoppingFlowViewStage.askProduct ||
      ShoppingFlowViewStage.searchingProduct =>
        ShoppingProgressStep.productCheck,
      ShoppingFlowViewStage.productSelection ||
      ShoppingFlowViewStage.quantitySelection =>
        ShoppingProgressStep.productSelection,
      ShoppingFlowViewStage.cartProcessing ||
      ShoppingFlowViewStage.cartCompleted => ShoppingProgressStep.addToCart,
      ShoppingFlowViewStage.addressConfirmation ||
      ShoppingFlowViewStage.paymentConfirmation ||
      ShoppingFlowViewStage.paymentPassword ||
      ShoppingFlowViewStage.paymentProcessing ||
      ShoppingFlowViewStage.completed => ShoppingProgressStep.payment,
      ShoppingFlowViewStage.error => ShoppingProgressStep.productCheck,
    };
  }

  Set<ShoppingProgressStep> completedStepsFor(ShoppingFlowViewStage stage) {
    return switch (stage) {
      ShoppingFlowViewStage.askProduct ||
      ShoppingFlowViewStage.searchingProduct => const <ShoppingProgressStep>{},
      ShoppingFlowViewStage.productSelection ||
      ShoppingFlowViewStage.quantitySelection => const {
        ShoppingProgressStep.productCheck,
      },
      ShoppingFlowViewStage.cartProcessing ||
      ShoppingFlowViewStage.cartCompleted => const {
        ShoppingProgressStep.productCheck,
        ShoppingProgressStep.productSelection,
      },
      ShoppingFlowViewStage.addressConfirmation ||
      ShoppingFlowViewStage.paymentConfirmation ||
      ShoppingFlowViewStage.paymentPassword ||
      ShoppingFlowViewStage.paymentProcessing => const {
        ShoppingProgressStep.productCheck,
        ShoppingProgressStep.productSelection,
        ShoppingProgressStep.addToCart,
      },
      ShoppingFlowViewStage.completed => const {
        ShoppingProgressStep.productCheck,
        ShoppingProgressStep.productSelection,
        ShoppingProgressStep.addToCart,
        ShoppingProgressStep.payment,
      },
      ShoppingFlowViewStage.error => const <ShoppingProgressStep>{},
    };
  }

  String? pendingTypeOf(AgentResponse response) =>
      _mapOf(response.pendingConfirmation)?['type']?.toString();

  String? pendingSubTypeOf(AgentResponse response) {
    final payload = pendingPayload(response);
    return payload?['subType']?.toString();
  }

  Map<String, dynamic>? pendingPayload(AgentResponse response) {
    final pending = _mapOf(response.pendingConfirmation);
    if (pending == null) {
      return null;
    }
    return _mapOf(pending['payload']);
  }

  bool requiresPolling(AgentResponse? response) {
    if (response == null) {
      return false;
    }

    final viewStage = inferViewStage(response);
    if (viewStage != ShoppingFlowViewStage.cartProcessing &&
        viewStage != ShoppingFlowViewStage.paymentProcessing &&
        viewStage != ShoppingFlowViewStage.searchingProduct) {
      return false;
    }

    return true;
  }

  String? asyncStatusMessage(AgentResponse? response) {
    final asyncStatus = _mapOf(response?.asyncStatus);
    final message = asyncStatus?['message']?.toString().trim();
    if (message == null || message.isEmpty) {
      return null;
    }
    return message;
  }

  String statusTitleFor(ShoppingFlowViewStage stage) {
    return switch (stage) {
      ShoppingFlowViewStage.searchingProduct => '상품을 찾고 있어요',
      ShoppingFlowViewStage.cartProcessing => '장바구니 작업',
      ShoppingFlowViewStage.paymentProcessing => '결제 진행',
      _ => '진행 상황',
    };
  }

  String statusMessageFor(
    ShoppingFlowViewStage stage, {
    AgentResponse? response,
    ShoppingProductViewData? product,
    int? quantity,
  }) {
    final asyncMessage = asyncStatusMessage(response);
    if (asyncMessage != null) {
      return asyncMessage;
    }

    final productName = product?.title.trim();
    final safeQuantity = quantity ?? 1;
    return switch (stage) {
      ShoppingFlowViewStage.searchingProduct =>
        response?.assistantMessage.trim().isNotEmpty == true
            ? response!.assistantMessage.trim()
            : '말씀하신 상품을 찾고 있어요.',
      ShoppingFlowViewStage.cartProcessing =>
        productName == null || productName.isEmpty
            ? '상품을 장바구니에 담고 있어요.'
            : '$productName $safeQuantity개를 장바구니에 담고 있어요.',
      ShoppingFlowViewStage.paymentProcessing =>
        response?.assistantMessage.trim().isNotEmpty == true
            ? response!.assistantMessage.trim()
            : '결제해볼게요!',
      _ =>
        response?.assistantMessage.trim().isNotEmpty == true
            ? response!.assistantMessage.trim()
            : '진행 상태를 확인하고 있어요.',
    };
  }

  double progressValueFor(ShoppingFlowViewStage stage) {
    return switch (stage) {
      ShoppingFlowViewStage.searchingProduct => 0.28,
      ShoppingFlowViewStage.cartProcessing => 0.64,
      ShoppingFlowViewStage.paymentProcessing => 0.88,
      ShoppingFlowViewStage.completed => 1,
      _ => 0.2,
    };
  }

  List<String> quickRepliesFor(ShoppingFlowViewStage stage) {
    return switch (stage) {
      ShoppingFlowViewStage.askProduct => const [
        '신선한 완숙 토마토 사고 싶어',
        '삼겹살 1근 구매해줘',
      ],
      ShoppingFlowViewStage.quantitySelection => const ['1개', '2개', '3개', '4개'],
      ShoppingFlowViewStage.cartCompleted => const ['더 구매할래요', '결제할래요'],
      ShoppingFlowViewStage.addressConfirmation => const [
        '네, 맞아요',
        '아니요, 수정할래요',
      ],
      ShoppingFlowViewStage.paymentConfirmation => const [
        '네, 진행해줘',
        '다시 확인할래요',
      ],
      ShoppingFlowViewStage.error => const ['다시 말할게요'],
      _ => const <String>[],
    };
  }

  RecommendationItemInAgent? primaryRecommendation(AgentResponse response) {
    if (response.recommendations.isEmpty) {
      return null;
    }

    final activeRecommendationId = activeRecommendationItemId(response);
    for (final recommendation in response.recommendations) {
      if (activeRecommendationId != null &&
          recommendation.recommendationItemId == activeRecommendationId) {
        return recommendation;
      }
    }
    return response.recommendations.first;
  }

  List<RecommendationItemInAgent> secondaryRecommendations(
    AgentResponse response,
  ) {
    final primary = primaryRecommendation(response);
    if (primary == null) {
      return response.recommendations;
    }
    return response.recommendations
        .where(
          (recommendation) =>
              recommendation.recommendationItemId !=
              primary.recommendationItemId,
        )
        .toList(growable: false);
  }

  int? activeRecommendationItemId(AgentResponse response) {
    final payload = pendingPayload(response);
    final payloadId = _intOf(payload?['recommendationItemId']);
    if (payloadId != null) {
      return payloadId;
    }

    final selectedProduct = _mapOf(response.selectedProduct);
    final selectedId =
        _intOf(selectedProduct?['recommendationItemId']) ??
        _intOf(selectedProduct?['recommendation_item_id']);
    if (selectedId != null) {
      return selectedId;
    }

    return response.recommendations.firstOrNull?.recommendationItemId;
  }

  ShoppingProductViewData? extractSelectedProduct(AgentResponse response) {
    final selectedProduct = _mapOf(response.selectedProduct);
    if (selectedProduct != null) {
      return _productFromMap(selectedProduct);
    }

    final primary = primaryRecommendation(response);
    if (primary != null) {
      return productFromRecommendation(primary);
    }
    return null;
  }

  ShoppingWebviewTaskViewData? extractWebviewTask(
    AgentResponse response, {
    ShoppingProductViewData? fallbackProduct,
    int defaultQuantity = 1,
  }) {
    final pending = _mapOf(response.pendingConfirmation);
    if (pending?['type']?.toString() != 'webview_task') {
      return null;
    }

    final payload = pendingPayload(response) ?? const <String, dynamic>{};
    final selectedProduct =
        _mapOf(response.selectedProduct) ?? const <String, dynamic>{};
    final rawSource =
        _mapOf(selectedProduct['raw']) ?? const <String, dynamic>{};

    String? url = _firstNonEmptyString([
      payload['startUrl'],
      payload['webviewUrl'],
      payload['url'],
      payload['executionUrl'],
      selectedProduct['execution_url'],
      selectedProduct['executionUrl'],
      selectedProduct['source_url'],
      selectedProduct['sourceUrl'],
      selectedProduct['product_url'],
      selectedProduct['productUrl'],
      rawSource['source_url'],
      rawSource['sourceUrl'],
      fallbackProduct?.productUrl,
    ]);

    if (url == null || url.trim().isEmpty) {
      return null;
    }
    url = url.trim();

    final task = _stringOf(payload['task']);
    final rawPlatform = _firstNonEmptyString([
      payload['platform'],
      selectedProduct['platform'],
      fallbackProduct?.platform,
    ]);
    final shopName = _firstNonEmptyString([
      payload['shopName'],
      payload['shop_name'],
      selectedProduct['shop_name'],
      selectedProduct['shopName'],
      rawSource['shop_name'],
      rawSource['shopName'],
      fallbackProduct?.platform,
    ]);
    final sourceUrl = _firstNonEmptyString([
      payload['sourceUrl'],
      payload['source_url'],
      selectedProduct['source_url'],
      selectedProduct['sourceUrl'],
      rawSource['source_url'],
      rawSource['sourceUrl'],
    ]);
    final orderId =
        _intOf(_mapOf(response.order)?['orderId']) ??
        _intOf(payload['orderId']);
    final paymentId =
        _intOf(_mapOf(response.payment)?['paymentId']) ??
        _intOf(payload['paymentId']);
    final productName = _firstNonEmptyString([
      payload['targetProductName'],
      selectedProduct['product_name'],
      selectedProduct['productName'],
      fallbackProduct?.title,
    ]);
    final quantity =
        _intOf(payload['quantity']) ??
        _intOf(_mapOf(response.order)?['quantity']) ??
        defaultQuantity;
    final canonicalProductUrl = _firstNonEmptyString([
      payload['canonicalProductUrl'],
      sourceUrl,
      selectedProduct['product_url'],
      selectedProduct['productUrl'],
      selectedProduct['execution_url'],
      selectedProduct['executionUrl'],
      fallbackProduct?.productUrl,
    ]);
    final inferredPlatform = _normalizeWebviewPlatform(
      platform: rawPlatform,
      shopName: shopName,
      url: url,
      canonicalProductUrl: canonicalProductUrl,
      sourceUrl: sourceUrl,
    );
    final commandKey =
        'pending|${response.conversationId}|${task ?? 'webview'}|${orderId ?? 0}|${paymentId ?? 0}|$url';

    return ShoppingWebviewTaskViewData(
      commandKey: commandKey,
      url: url,
      platform: inferredPlatform,
      shopName: shopName,
      task: task,
      orderId: orderId,
      paymentId: paymentId,
      productName: productName,
      quantity: quantity > 0 ? quantity : 1,
      canonicalProductUrl:
          canonicalProductUrl != null &&
              canonicalProductUrl.contains('kurly.com/goods/')
          ? canonicalProductUrl
          : null,
    );
  }

  ShoppingProductViewData productFromRecommendation(
    RecommendationItemInAgent item,
  ) {
    return ShoppingProductViewData(
      recommendationItemId: item.recommendationItemId,
      productId: item.productId,
      title: item.productName,
      brand: item.brand,
      optionText: item.optionText,
      deliveryInfo: item.deliveryInfo,
      reason: item.reason,
      imageUrl: item.imageUrl,
      productUrl: item.productUrl,
      platform: item.platform,
      price: item.price,
      rank: item.rank,
      isOrderable: item.isOrderable,
      orderBlockReason: item.orderBlockReason,
    );
  }

  List<ShoppingCartItemViewData> extractCartItems(AgentResponse response) {
    final cart = _mapOf(response.cart);
    if (cart == null) {
      final selectedProduct = extractSelectedProduct(response);
      final quantity = _intOf(_mapOf(response.order)?['quantity']) ?? 1;
      if (selectedProduct == null) {
        return const <ShoppingCartItemViewData>[];
      }
      return [
        ShoppingCartItemViewData(
          product: selectedProduct,
          quantity: quantity,
          totalPrice: selectedProduct.price == null
              ? null
              : selectedProduct.price! * quantity,
        ),
      ];
    }

    final items = _listOfMap(cart['items']);
    final cartId = _intOf(cart['cartId']) ?? _intOf(cart['cart_id']);
    if (items.isEmpty) {
      final lastCartItem = _mapOf(cart['lastCartItem']);
      if (lastCartItem == null) {
        return const <ShoppingCartItemViewData>[];
      }
      return [
        _cartItemFromMap(<String, dynamic>{'cartId': cartId, ...lastCartItem}),
      ];
    }

    return items
        .map(
          (item) =>
              _cartItemFromMap(<String, dynamic>{'cartId': cartId, ...item}),
        )
        .toList(growable: false);
  }

  ShoppingAddressViewData? extractAddress(
    AgentResponse response, {
    ShoppingAddressViewData? fallback,
    String? fallbackRecipientName,
    String? fallbackPhoneNumber,
  }) {
    final rawAddress = _mapOf(response.deliveryAddress);
    if (rawAddress == null) {
      return fallback ??
          (fallbackRecipientName == null && fallbackPhoneNumber == null
              ? null
              : ShoppingAddressViewData(
                  recipientName: fallbackRecipientName,
                  recipientPhone: fallbackPhoneNumber,
                ));
    }

    final mapped = _addressFromMap(
      rawAddress,
      fallbackRecipientName: fallbackRecipientName,
      fallbackPhoneNumber: fallbackPhoneNumber,
    );
    if (fallback == null) {
      return mapped;
    }

    return ShoppingAddressViewData(
      label: mapped.label ?? fallback.label,
      recipientName: mapped.recipientName ?? fallback.recipientName,
      recipientPhone: mapped.recipientPhone ?? fallback.recipientPhone,
      zipCode: mapped.zipCode ?? fallback.zipCode,
      addressLine1: mapped.addressLine1 ?? fallback.addressLine1,
      addressLine2: mapped.addressLine2 ?? fallback.addressLine2,
      deliveryRequest: mapped.deliveryRequest ?? fallback.deliveryRequest,
      isDefault: mapped.isDefault || fallback.isDefault,
    );
  }

  ShoppingPreviewAsset assetForProductName(String productName) {
    final normalized = productName.toLowerCase();
    final candidates = <(List<String>, ShoppingPreviewAsset)>[
      (
        ['딸기', 'strawberry'],
        const ShoppingPreviewAsset(
          assetPath: 'assets/mock_productimages/strawberry.jpg',
          backgroundColor: Color(0xFFFFE5EE),
        ),
      ),
      (
        ['바나나', 'banana'],
        const ShoppingPreviewAsset(
          assetPath: 'assets/mock_productimages/banana.png',
          backgroundColor: Color(0xFFFFF2CC),
        ),
      ),
      (
        ['계란', '달걀', 'egg'],
        const ShoppingPreviewAsset(
          assetPath: 'assets/mock_productimages/eggs.png',
          backgroundColor: Color(0xFFF4F0D8),
        ),
      ),
      (
        ['수박', 'watermelon'],
        const ShoppingPreviewAsset(
          assetPath: 'assets/mock_productimages/watermelon.png',
          backgroundColor: Color(0xFFEAF7EB),
        ),
      ),
      (
        ['콩국수', '면', '국수'],
        const ShoppingPreviewAsset(
          assetPath: 'assets/mock_productimages/beannoodle.png',
          backgroundColor: Color(0xFFEFF4FF),
        ),
      ),
      (
        ['고구마', '말랭이'],
        const ShoppingPreviewAsset(
          assetPath: 'assets/mock_productimages/sweetpotato.png',
          backgroundColor: Color(0xFFFFECE3),
        ),
      ),
      (
        ['한라봉', '감귤', 'orange'],
        const ShoppingPreviewAsset(
          assetPath: 'assets/mock_productimages/hallabong.png',
          backgroundColor: Color(0xFFFFF3D9),
        ),
      ),
      (
        ['토레타', '음료', 'drink'],
        const ShoppingPreviewAsset(
          assetPath: 'assets/mock_productimages/toreta.png',
          backgroundColor: Color(0xFFE5F8F5),
        ),
      ),
      (
        ['시루콧토', '타올', '화장솜'],
        const ShoppingPreviewAsset(
          assetPath: 'assets/mock_productimages/sirukotto.png',
          backgroundColor: Color(0xFFEAEFFF),
        ),
      ),
    ];

    for (final candidate in candidates) {
      if (candidate.$1.any(normalized.contains)) {
        return candidate.$2;
      }
    }

    return candidates[productName.hashCode.abs() % candidates.length].$2;
  }

  String platformLabel(String? platform) {
    return switch (platform?.toLowerCase()) {
      'kurly' || 'kurlynmart' => '컬리',
      'coupang' => '쿠팡',
      'naver' => '네이버',
      'gmarket' => '지마켓',
      'hmall' || 'hyundai' => '현대홈쇼핑',
      _ => '쇼핑 추천',
    };
  }

  bool _isRestartPrompt(AgentResponse response) {
    final pendingType = pendingTypeOf(response);
    final stage = response.stage.toLowerCase();
    final message = response.assistantMessage.trim();
    if (pendingType == 'clarification') {
      return true;
    }
    if (stage.contains('clarification') || stage == 'idle') {
      if (message.contains('다시 말씀') ||
          message.contains('어떤 상품') ||
          message.contains('잘 못 들었') ||
          message.contains('무슨 말씀인지') ||
          message.contains('찾지 못했') ||
          message.contains('죄송')) {
        return true;
      }
    }
    return message.contains('다시 말씀') ||
        message.contains('어떤 상품을') ||
        message.contains('무슨 말씀인지') ||
        message.contains('무슨 뜻인지');
  }

  ShoppingProductViewData _productFromMap(Map<String, dynamic> raw) {
    final rawSource = _mapOf(raw['raw']) ?? const <String, dynamic>{};
    return ShoppingProductViewData(
      recommendationItemId:
          _intOf(raw['recommendationItemId']) ??
          _intOf(raw['recommendation_item_id']),
      productId:
          _intOf(raw['productId']) ??
          _intOf(raw['product_id']) ??
          _intOf(rawSource['product_id']),
      productOptionId:
          _intOf(raw['productOptionId']) ??
          _intOf(raw['product_option_id']) ??
          _intOf(rawSource['product_option_id']),
      title:
          _stringOf(raw['productName']) ??
          _stringOf(raw['product_name']) ??
          _stringOf(raw['name']) ??
          _stringOf(rawSource['name']) ??
          '추천 상품',
      brand: _stringOf(raw['brand']),
      optionText: _stringOf(raw['optionText']) ?? _stringOf(raw['option_text']),
      deliveryInfo:
          _stringOf(raw['deliveryInfo']) ?? _stringOf(raw['delivery_info']),
      reason: _stringOf(raw['reason']) ?? _stringOf(raw['explanation']),
      imageUrl:
          _stringOf(raw['imageUrl']) ??
          _stringOf(raw['image_url']) ??
          _stringOf(rawSource['image_url']) ??
          _stringOf(rawSource['imageUrl']),
      productUrl:
          _stringOf(raw['productUrl']) ??
          _stringOf(raw['product_url']) ??
          _stringOf(raw['url']) ??
          _stringOf(rawSource['url']),
      platform: _stringOf(raw['platform']) ?? _stringOf(rawSource['platform']),
      price:
          _intOf(raw['price']) ??
          _intOf(raw['unitPrice']) ??
          _intOf(rawSource['price']),
      rank: _intOf(raw['rank']),
      isOrderable: raw['isOrderable'] as bool? ?? true,
      orderBlockReason:
          _stringOf(raw['orderBlockReason']) ??
          _stringOf(raw['order_block_reason']),
    );
  }

  ShoppingCartItemViewData _cartItemFromMap(Map<String, dynamic> raw) {
    final price =
        _intOf(raw['unitPrice']) ??
        _intOf(raw['unit_price']) ??
        _intOf(raw['price']);
    final quantity = _intOf(raw['quantity']) ?? 1;

    return ShoppingCartItemViewData(
      cartId: _intOf(raw['cartId']) ?? _intOf(raw['cart_id']),
      cartItemId: _intOf(raw['cartItemId']) ?? _intOf(raw['cart_item_id']),
      product: ShoppingProductViewData(
        productId: _intOf(raw['productId']) ?? _intOf(raw['product_id']),
        productOptionId:
            _intOf(raw['productOptionId']) ?? _intOf(raw['product_option_id']),
        title:
            _stringOf(raw['productName']) ??
            _stringOf(raw['product_name']) ??
            '담긴 상품',
        brand: _stringOf(raw['brand']),
        optionText:
            _stringOf(raw['optionText']) ?? _stringOf(raw['option_text']),
        reason: _stringOf(raw['reason']),
        imageUrl: _stringOf(raw['imageUrl']) ?? _stringOf(raw['image_url']),
        platform: _stringOf(raw['platform']),
        price: price,
      ),
      quantity: quantity,
      totalPrice:
          _intOf(raw['totalPrice']) ??
          _intOf(raw['total_price']) ??
          (price == null ? null : price * quantity),
    );
  }

  ShoppingCartItemViewData _cartItemFromResponse(
    CartItemResponse item, {
    required int? cartId,
  }) {
    return ShoppingCartItemViewData(
      cartId: cartId,
      cartItemId: item.cartItemId,
      product: ShoppingProductViewData(
        productId: item.productId,
        productOptionId: item.productOptionId,
        title: item.productName,
        optionText: item.optionText,
        price: item.unitPrice,
      ),
      quantity: item.quantity,
      totalPrice: item.totalPrice,
    );
  }

  ShoppingAddressViewData _addressFromMap(
    Map<String, dynamic> raw, {
    String? fallbackRecipientName,
    String? fallbackPhoneNumber,
  }) {
    return ShoppingAddressViewData(
      label: _stringOf(raw['addressLabel']) ?? _stringOf(raw['address_label']),
      recipientName:
          _stringOf(raw['recipientName']) ??
          _stringOf(raw['recipient_name']) ??
          _stringOf(raw['userName']) ??
          _stringOf(raw['name']) ??
          fallbackRecipientName,
      recipientPhone:
          _stringOf(raw['recipientPhone']) ??
          _stringOf(raw['recipient_phone']) ??
          _stringOf(raw['phoneNumber']) ??
          _stringOf(raw['phone_number']) ??
          fallbackPhoneNumber,
      zipCode: _stringOf(raw['zipCode']) ?? _stringOf(raw['zip_code']),
      addressLine1:
          _stringOf(raw['addressLine1']) ??
          _stringOf(raw['address_line1']) ??
          _stringOf(raw['address']),
      addressLine2:
          _stringOf(raw['addressLine2']) ?? _stringOf(raw['address_line2']),
      deliveryRequest:
          _stringOf(raw['deliveryRequest']) ??
          _stringOf(raw['delivery_request']) ??
          _stringOf(raw['requestMessage']),
      isDefault: raw['isDefault'] == true,
    );
  }

  String? _normalizeWebviewPlatform({
    String? platform,
    String? shopName,
    String? url,
    String? canonicalProductUrl,
    String? sourceUrl,
  }) {
    final normalizedPlatform = platform?.trim().toLowerCase();
    final normalizedShopName = shopName?.trim().toLowerCase() ?? '';
    final urlCandidates = [
      url,
      canonicalProductUrl,
      sourceUrl,
    ].whereType<String>().map((value) => value.trim().toLowerCase()).toList();

    final looksKurly =
        normalizedPlatform == 'kurly' ||
        normalizedPlatform == 'kurlynmart' ||
        normalizedShopName.contains('컬리') ||
        normalizedShopName.contains('kurly') ||
        urlCandidates.any((value) => value.contains('kurly.com/'));

    if (looksKurly) {
      return normalizedShopName.contains('n마트') ||
              normalizedShopName.contains('nmart')
          ? 'kurlynmart'
          : 'kurly';
    }
    return normalizedPlatform;
  }

  int? _resolveDevUserIdOverride() {
    try {
      final raw = dotenv.env['SHOPPING_DEV_USER_ID']?.trim();
      if (raw == null || raw.isEmpty) {
        return null;
      }
      return int.tryParse(raw);
    } catch (_) {
      return null;
    }
  }

  String? _firstNonEmptyString(List<Object?> values) {
    for (final value in values) {
      final parsed = _stringOf(value);
      if (parsed != null && parsed.trim().isNotEmpty) {
        return parsed.trim();
      }
    }
    return null;
  }
}

Map<String, dynamic>? _mapOf(dynamic value) {
  if (value is Map<String, dynamic>) {
    return value;
  }
  if (value is Map) {
    return Map<String, dynamic>.from(value);
  }
  return null;
}

List<Map<String, dynamic>> _listOfMap(dynamic value) {
  if (value is! List) {
    return const [];
  }
  return value
      .whereType<Map>()
      .map((item) => Map<String, dynamic>.from(item))
      .toList(growable: false);
}

String? _stringOf(dynamic value) {
  if (value == null) {
    return null;
  }
  final result = value.toString().trim();
  return result.isEmpty ? null : result;
}

int? _intOf(dynamic value) {
  if (value is int) {
    return value;
  }
  if (value is num) {
    return value.toInt();
  }
  if (value is String) {
    return int.tryParse(value.replaceAll(',', '').trim());
  }
  return null;
}

extension<T> on List<T> {
  T? get firstOrNull => isEmpty ? null : first;
}
