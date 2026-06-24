import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart';

import '../../../core/network/api_client.dart';
import '../../../core/storage/local_storage.dart';
import '../models/shopping_v1_models.dart';

class ShoppingAgentService {
  ShoppingAgentService({Dio? dio}) : _dio = dio ?? ApiClient.dio;

  final Dio _dio;

  Future<int> resolveUserId() async {
    return await LocalStorage.getUserId() ?? 1;
  }

  Future<ShoppingAgentResponse> startShopping({
    required int userId,
    required String message,
    String inputType = 'voice',
  }) async {
    final response = await _dio.post<Map<String, dynamic>>(
      '/api/agent/shopping-requests',
      data: {'userId': userId, 'message': message, 'inputType': inputType},
    );
    return _parseAgentResponse(response.data ?? const {});
  }

  Future<ShoppingAgentResponse> sendMessage({
    required int conversationId,
    required String message,
    String inputType = 'voice',
  }) async {
    final response = await _dio.post<Map<String, dynamic>>(
      '/api/agent/conversations/$conversationId/messages',
      data: {'message': message, 'inputType': inputType},
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

    // TODO: 백엔드 상품 필드가 확장되면 여기서 snake_case/camelCase 키를 추가 매핑한다.
    final productUrl =
        _stringOf(raw['productUrl']) ??
        _stringOf(raw['product_url']) ??
        _stringOf(raw['url']);
    final title =
        _stringOf(raw['productName']) ??
        _stringOf(raw['product_name']) ??
        _stringOf(raw['name']);
    if (title == null || title.trim().isEmpty) {
      return ProductViewData.mock(productUrl: productUrl);
    }

    final priceValue = _intOf(raw['price']) ?? _intOf(raw['unitPrice']);
    final optionText =
        _stringOf(raw['optionText']) ?? _stringOf(raw['option_text']);
    return ProductViewData(
      platform: _stringOf(raw['platform']),
      productUrl: productUrl,
      imageUrl: _stringOf(raw['imageUrl']) ?? _stringOf(raw['image_url']),
      title: title,
      subtitle: _stringOf(raw['brand']),
      quantityInfo:
          optionText ??
          _stringOf(raw['deliveryInfo']) ??
          _stringOf(raw['delivery_info']),
      price: priceValue,
      priceText: priceValue != null ? '${_formatPrice(priceValue)}원' : null,
      badgeText: _stringOf(raw['reason']) ?? _stringOf(raw['explanation']),
    );
  }

  Map<String, dynamic>? pendingPayload(ShoppingAgentResponse response) =>
      response.pendingConfirmation?['payload'] is Map
      ? Map<String, dynamic>.from(
          response.pendingConfirmation!['payload'] as Map,
        )
      : null;

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
          _stringOf(json['assistantMessage']) ?? '잠시만요. 다시 확인해볼게요.',
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
