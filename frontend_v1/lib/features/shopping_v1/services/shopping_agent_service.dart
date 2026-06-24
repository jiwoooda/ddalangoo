import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart';

import '../../../core/network/api_client.dart';
import '../../../core/storage/local_storage.dart';
import '../models/shopping_v1_models.dart';

class ShoppingAgentService {
  ShoppingAgentService({Dio? dio}) : _dio = dio ?? ApiClient.dio;

  final Dio _dio;
  WebSocket? _progressSocket;
  StreamController<ShoppingAgentResponse>? _progressController;

  Future<int> resolveUserId() async {
    final userId = await LocalStorage.getUserId() ?? 1;
    debugPrint('ℹ️ [ShoppingAgentService] resolved userId=$userId');
    return userId;
  }

  Future<String?> resolveUserName({int? userId}) async {
    final effectiveUserId = userId ?? await resolveUserId();
    try {
      final response = await _dio.get<Map<String, dynamic>>(
        '/api/users/$effectiveUserId',
      );
      final user = response.data ?? const <String, dynamic>{};
      final name = _stringOf(user['name'])?.trim();
      if (name != null && name.isNotEmpty) {
        debugPrint(
          'ℹ️ [ShoppingAgentService] resolved userName="$name" userId=$effectiveUserId',
        );
        return name;
      }
    } catch (error, stackTrace) {
      debugPrint(
        '⚠️ [ShoppingAgentService] resolve user name fallback: $error\n$stackTrace',
      );
    }
    return null;
  }

  Future<ShoppingAgentResponse> startShopping({
    required int userId,
    required String message,
    String inputType = 'voice',
    String? progressChannelId,
  }) async {
    final response = await _dio.post<Map<String, dynamic>>(
      '/api/agent/shopping-requests',
      data: {
        'userId': userId,
        'message': message,
        'inputType': inputType,
        'progressChannelId': progressChannelId,
      },
    );
    return _parseAgentResponse(response.data ?? const {});
  }

  Future<ShoppingAgentResponse> sendMessage({
    required int conversationId,
    required String message,
    String inputType = 'voice',
    String? progressChannelId,
  }) async {
    final response = await _dio.post<Map<String, dynamic>>(
      '/api/agent/conversations/$conversationId/messages',
      data: {
        'message': message,
        'inputType': inputType,
        'progressChannelId': progressChannelId,
      },
    );
    return _parseAgentResponse(response.data ?? const {});
  }

  Future<Stream<ShoppingAgentResponse>> connectProgress(
    String channelId,
  ) async {
    await disconnectProgress();
    final uri = _progressUri(channelId);
    debugPrint('ℹ️ [ShoppingAgentService] connect progress websocket: $uri');
    final socket = await WebSocket.connect(uri.toString());
    final controller = StreamController<ShoppingAgentResponse>.broadcast();
    socket.listen(
      (event) {
        try {
          final decoded = jsonDecode(event.toString());
          if (decoded is Map<String, dynamic>) {
            controller.add(_parseAgentResponse(decoded));
          } else if (decoded is Map) {
            controller.add(
              _parseAgentResponse(Map<String, dynamic>.from(decoded)),
            );
          }
        } catch (error, stackTrace) {
          debugPrint(
            '⚠️ [ShoppingAgentService] progress websocket decode failed: '
            '$error\n$stackTrace',
          );
        }
      },
      onDone: () {
        controller.close();
      },
      onError: (Object error, StackTrace stackTrace) {
        debugPrint(
          '⚠️ [ShoppingAgentService] progress websocket error: '
          '$error\n$stackTrace',
        );
        controller.addError(error, stackTrace);
      },
      cancelOnError: false,
    );
    _progressSocket = socket;
    _progressController = controller;
    return controller.stream;
  }

  Future<void> disconnectProgress() async {
    final socket = _progressSocket;
    final controller = _progressController;
    _progressSocket = null;
    _progressController = null;
    if (socket != null) {
      try {
        await socket.close();
      } catch (_) {}
    }
    if (controller != null && !controller.isClosed) {
      await controller.close();
    }
  }

  Future<ShoppingAgentResponse> fetchPrompt({
    required String kind,
    int? conversationId,
    Map<String, dynamic>? payload,
  }) async {
    final response = await _dio.post<Map<String, dynamic>>(
      '/api/agent/prompts',
      data: {
        'kind': kind,
        'conversationId': conversationId,
        'payload': payload,
      },
    );
    return _parseAgentResponse(response.data ?? const {});
  }

  Future<void> cancelConversation(int conversationId) async {
    await _dio.post<void>('/api/agent/conversations/$conversationId/cancel');
  }

  Future<ShoppingAgentResponse> sendWebviewResult({
    required int conversationId,
    int? orderId,
    int? paymentId,
    required String result,
    Map<String, dynamic>? extraData,
  }) async {
    final payload = <String, dynamic>{
      'orderId': orderId,
      'paymentId': paymentId,
      'result': result,
      ...?extraData,
    };
    final response = await _dio.post<Map<String, dynamic>>(
      '/api/agent/conversations/$conversationId/payments/webview-result',
      data: payload,
    );
    return _parseAgentResponse(response.data ?? const {});
  }

  Future<CheckoutSummary> fetchCheckoutSummary({
    required int userId,
    required List<CartItemViewData> items,
    Map<String, dynamic>? deliveryAddress,
  }) async {
    try {
      final userResponse = await _dio.get<Map<String, dynamic>>(
        '/api/users/$userId',
      );
      final user = userResponse.data ?? const <String, dynamic>{};
      final defaultAddress =
          deliveryAddress ?? await _fetchDefaultAddress(userId);
      return CheckoutSummary(
        userName: _stringOf(user['name']) ?? '김영희',
        phone: _stringOf(user['phoneNumber']) ?? '010-1234-5678',
        address: _fullAddress(defaultAddress),
        items: _effectiveItems(items),
        totalPrice: _effectiveItems(
          items,
        ).fold<int>(0, (sum, item) => sum + _lineTotal(item)),
      );
    } catch (error, stackTrace) {
      debugPrint(
        '⚠️ [ShoppingAgentService] checkout summary fallback: $error\n$stackTrace',
      );
      return CheckoutSummary.mock(items);
    }
  }

  CheckoutSummary checkoutSummaryFromResponse(
    ShoppingAgentResponse response, {
    required List<CartItemViewData> fallbackItems,
  }) {
    final cartItems = extractCartItems(response);
    final effectiveItems = cartItems.isEmpty
        ? _effectiveItems(fallbackItems)
        : cartItems;
    final address = _fullAddress(response.deliveryAddress);
    final rawAddress = response.deliveryAddress ?? const <String, dynamic>{};
    return CheckoutSummary(
      userName:
          _stringOf(rawAddress['recipientName']) ??
          _stringOf(rawAddress['recipient_name']) ??
          '김영희',
      phone:
          _stringOf(rawAddress['recipientPhone']) ??
          _stringOf(rawAddress['recipient_phone']) ??
          '010-1234-5678',
      address: address,
      items: effectiveItems,
      totalPrice:
          _intOf(response.order?['totalPaymentAmount']) ??
          effectiveItems.fold<int>(0, (sum, item) => sum + _lineTotal(item)),
    );
  }

  ProductViewData? extractProduct(ShoppingAgentResponse response) {
    final raw =
        response.selectedProduct ??
        (response.recommendations.isNotEmpty
            ? response.recommendations.first
            : null);
    if (raw == null) {
      return null;
    }
    final rawSource = _mapOf(raw['raw']) ?? const <String, dynamic>{};

    // TODO: 백엔드 상품 필드가 확장되면 여기서 snake_case/camelCase 키를 추가 매핑한다.
    final productUrl =
        _stringOf(raw['productUrl']) ??
        _stringOf(raw['product_url']) ??
        _stringOf(raw['url']) ??
        _stringOf(rawSource['url']);
    final title =
        _stringOf(raw['productName']) ??
        _stringOf(raw['product_name']) ??
        _stringOf(raw['name']) ??
        _stringOf(rawSource['name']);
    if (title == null || title.trim().isEmpty) {
      return ProductViewData.mock(productUrl: productUrl);
    }

    final priceValue =
        _intOf(raw['price']) ??
        _intOf(raw['unitPrice']) ??
        _intOf(rawSource['price']);
    final optionText =
        _stringOf(raw['optionText']) ?? _stringOf(raw['option_text']);
    return ProductViewData(
      platform: _stringOf(raw['platform']) ?? _stringOf(rawSource['platform']),
      shopName:
          _stringOf(raw['shopName']) ??
          _stringOf(raw['shop_name']) ??
          _stringOf(rawSource['shop_name']) ??
          _stringOf(rawSource['shopName']),
      productUrl: productUrl,
      imageUrl:
          _stringOf(raw['imageUrl']) ??
          _stringOf(raw['image_url']) ??
          _stringOf(rawSource['image_url']) ??
          _stringOf(rawSource['imageUrl']),
      title: title,
      subtitle: _stringOf(raw['brand']),
      quantityInfo:
          optionText ??
          _stringOf(raw['deliveryInfo']) ??
          _stringOf(raw['delivery_info']),
      price: priceValue,
      priceText:
          _stringOf(raw['price_formatted']) ??
          _stringOf(rawSource['price_formatted']) ??
          (priceValue != null ? '${_formatPrice(priceValue)}원' : null),
      badgeText: _stringOf(raw['reason']) ?? _stringOf(raw['explanation']),
    );
  }

  WebviewTaskViewData? extractWebviewTask(
    ShoppingAgentResponse response, {
    ProductViewData? fallbackProduct,
    int defaultQuantity = 1,
  }) {
    final pending = response.pendingConfirmation;
    final payload = pending?['payload'] is Map
        ? Map<String, dynamic>.from(pending!['payload'] as Map)
        : const <String, dynamic>{};
    final selectedProduct =
        response.selectedProduct ?? const <String, dynamic>{};

    final rawSource = selectedProduct['raw'] is Map
        ? Map<String, dynamic>.from(selectedProduct['raw'] as Map)
        : const <String, dynamic>{};

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
      (selectedProduct['raw'] is Map)
          ? (selectedProduct['raw'] as Map)['shop_name']
          : null,
      fallbackProduct?.shopName,
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
        _intOf(response.order?['orderId']) ?? _intOf(payload['orderId']);
    final paymentId =
        _intOf(response.payment?['paymentId']) ?? _intOf(payload['paymentId']);
    final productName = _firstNonEmptyString([
      payload['targetProductName'],
      selectedProduct['product_name'],
      selectedProduct['productName'],
      fallbackProduct?.title,
    ]);
    final quantity =
        _intOf(payload['quantity']) ??
        _intOf(response.order?['quantity']) ??
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
    final conversationId = response.conversationId ?? 0;
    final commandKey =
        'pending|$conversationId|${task ?? 'webview'}|${orderId ?? 0}|${paymentId ?? 0}|$url';

    return WebviewTaskViewData(
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

  Map<String, dynamic>? pendingPayload(ShoppingAgentResponse response) =>
      response.pendingConfirmation?['payload'] is Map
      ? Map<String, dynamic>.from(
          response.pendingConfirmation!['payload'] as Map,
        )
      : null;

  String? _firstNonEmptyString(List<Object?> values) {
    for (final value in values) {
      final parsed = _stringOf(value);
      if (parsed != null && parsed.trim().isNotEmpty) {
        return parsed.trim();
      }
    }
    return null;
  }

  List<CartItemViewData> extractCartItems(ShoppingAgentResponse response) {
    final cart = response.cart;
    if (cart == null) {
      return const [];
    }
    final items = _listOfMap(cart['items']);
    if (items.isEmpty) {
      final lastCartItem = _mapOf(cart['lastCartItem']);
      if (lastCartItem == null) {
        return const [];
      }
      return [_cartItemFrom(lastCartItem)];
    }
    return items.map(_cartItemFrom).toList();
  }

  ShoppingAgentResponse _parseAgentResponse(Map<String, dynamic> json) {
    return ShoppingAgentResponse(
      conversationId: _intOf(json['conversationId']),
      assistantMessage:
          _stringOf(json['assistantMessage']) ??
          _stringOf(json['message']) ??
          '잠시만요. 다시 확인해볼게요.',
      message: _stringOf(json['message']),
      speechMode: _stringOf(json['speechMode']),
      speechSegments: _parseSpeechSegments(json['speechSegments']),
      status: _stringOf(json['status']),
      stage: _stringOf(json['stage']),
      pendingConfirmation: _mapOf(json['pendingConfirmation']),
      selectedProduct: _mapOf(json['selectedProduct']),
      recommendations: _listOfMap(json['recommendations']),
      deliveryAddress: _mapOf(json['deliveryAddress']),
      cart: _mapOf(json['cart']),
      order: _mapOf(json['order']),
      payment: _mapOf(json['payment']),
      uiCommand: _mapOf(json['uiCommand']),
      asyncStatus: _mapOf(json['asyncStatus']),
      error: json['error'],
      raw: json,
    );
  }

  Uri _progressUri(String channelId) {
    final base = Uri.parse(ApiClient.baseUrl);
    final scheme = base.scheme == 'https' ? 'wss' : 'ws';
    var basePath = base.path;
    if (basePath.endsWith('/')) {
      basePath = basePath.substring(0, basePath.length - 1);
    }
    final path =
        '${basePath.isEmpty ? '' : basePath}/api/agent/progress/$channelId';
    return base.replace(
      scheme: scheme,
      path: path,
      queryParameters: null,
      fragment: null,
    );
  }

  List<SpeechSegmentViewData> _parseSpeechSegments(Object? raw) {
    final items = _listOfMap(raw);
    return items
        .map(
          (item) => SpeechSegmentViewData(
            index: _intOf(item['index']) ?? 0,
            text: _stringOf(item['text']) ?? '',
            audioUrl: _stringOf(item['audioUrl']),
            durationMs: _intOf(item['durationMs']),
          ),
        )
        .where((item) => item.text.trim().isNotEmpty)
        .toList()
      ..sort((a, b) => a.index.compareTo(b.index));
  }

  Future<Map<String, dynamic>?> _fetchDefaultAddress(int userId) async {
    final addressResponse = await _dio.get<Map<String, dynamic>>(
      '/api/users/$userId/addresses',
    );
    final addresses = _listOfMap(addressResponse.data?['addresses']);
    if (addresses.isEmpty) {
      return null;
    }
    for (final address in addresses) {
      if (address['isDefault'] == true) {
        return address;
      }
    }
    return addresses.first;
  }

  String _fullAddress(Map<String, dynamic>? address) {
    if (address == null) {
      return '서울 용산구 청파로 47길 100 명신관 1층 코딩라운지';
    }
    final line1 =
        _stringOf(address['address']) ??
        _stringOf(address['addressLine1']) ??
        _stringOf(address['address_line1']) ??
        '';
    final line2 =
        _stringOf(address['addressLine2']) ??
        _stringOf(address['address_line2']) ??
        '';
    final merged = [
      line1,
      line2,
    ].where((value) => value.trim().isNotEmpty).join(' ');
    return merged.isEmpty ? '서울 용산구 청파로 47길 100 명신관 1층 코딩라운지' : merged;
  }

  List<CartItemViewData> _effectiveItems(List<CartItemViewData> items) {
    return items.isEmpty
        ? [
            CartItemViewData(
              product: ProductViewData.mock(),
              quantity: 1,
              totalPrice: 12900,
              totalPriceText: '12,900원',
            ),
          ]
        : items;
  }

  int _lineTotal(CartItemViewData item) =>
      item.totalPrice ?? (item.product.price ?? 0) * item.quantity;

  CartItemViewData _cartItemFrom(Map<String, dynamic> raw) {
    final price =
        _intOf(raw['unitPrice']) ?? _intOf(raw['unit_price']) ?? 12900;
    final quantity = _intOf(raw['quantity']) ?? 1;
    return CartItemViewData(
      product: ProductViewData(
        platform: _stringOf(raw['platform']) ?? 'Kurly',
        productUrl:
            _stringOf(raw['productUrl']) ?? _stringOf(raw['product_url']),
        imageUrl: _stringOf(raw['imageUrl']) ?? _stringOf(raw['image_url']),
        title:
            _stringOf(raw['productName']) ??
            _stringOf(raw['product_name']) ??
            ProductViewData.mock().title,
        quantityInfo:
            _stringOf(raw['optionText']) ??
            _stringOf(raw['option_text']) ??
            ProductViewData.mock().quantityInfo,
        price: price,
        priceText: '${_formatPrice(price)}원',
        badgeText: _stringOf(raw['reason']),
      ),
      quantity: quantity,
      totalPrice:
          _intOf(raw['totalPrice']) ??
          _intOf(raw['total_price']) ??
          price * quantity,
      totalPriceText:
          '${_formatPrice(_intOf(raw['totalPrice']) ?? _intOf(raw['total_price']) ?? price * quantity)}원',
    );
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
      .toList();
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

String _formatPrice(int value) {
  final source = value.toString();
  final buffer = StringBuffer();
  for (var i = 0; i < source.length; i++) {
    final reversedIndex = source.length - i;
    buffer.write(source[i]);
    if (reversedIndex > 1 && reversedIndex % 3 == 1) {
      buffer.write(',');
    }
  }
  return buffer.toString();
}
