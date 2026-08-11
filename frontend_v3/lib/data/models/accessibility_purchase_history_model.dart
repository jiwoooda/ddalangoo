import 'dart:convert';

class AccessibilityPurchaseHistoryItem {
  const AccessibilityPurchaseHistoryItem({
    required this.platform,
    required this.sourceType,
    required this.productName,
    required this.price,
    required this.quantity,
    required this.purchaseDate,
    required this.imageUrl,
    required this.orderNumber,
    required this.deliveryStatus,
    required this.deliveryType,
    required this.raw,
  });

  final String platform;
  final String sourceType;
  final String productName;
  final int? price;
  final int quantity;
  final String? purchaseDate;
  final String? imageUrl;
  final String? orderNumber;
  final String? deliveryStatus;
  final String? deliveryType;
  final Map<String, dynamic> raw;

  factory AccessibilityPurchaseHistoryItem.fromMap(Map<String, dynamic> map) {
    final prices = _stringListFrom(map['prices']);
    final deliveryTypes = _stringListFrom(map['deliveryTypes']);
    final productNames = _stringListFrom(map['productNames']);
    final quantities = _intListFrom(map['quantities']);

    return AccessibilityPurchaseHistoryItem(
      platform: _stringValue(map['platform']) ?? 'unknown',
      sourceType: 'android_accessibility',
      productName: productNames.isEmpty ? '상품명 확인 필요' : productNames.first,
      price: _parsePrice(prices.isEmpty ? null : prices.first),
      quantity: quantities.isEmpty ? 1 : quantities.first,
      purchaseDate: _nullableNonEmptyString(map['purchaseDate']),
      imageUrl: _nullableNonEmptyString(map['imageUrl']) ??
          _nullableNonEmptyString(map['thumbnailPath']),
      orderNumber: _nullableNonEmptyString(map['orderNumber']),
      deliveryStatus: _nullableNonEmptyString(map['deliveryStatus']),
      deliveryType: deliveryTypes.isEmpty ? null : deliveryTypes.join(', '),
      raw: Map<String, dynamic>.from(map),
    );
  }

  factory AccessibilityPurchaseHistoryItem.fromOrderProduct({
    required Map<String, dynamic> orderMap,
    required String productName,
    required int productIndex,
    required String? rawPrice,
    required int quantity,
  }) {
    final deliveryTypes = _stringListFrom(orderMap['deliveryTypes']);
    final raw = Map<String, dynamic>.from(orderMap)
      ..['sourceOrderProductIndex'] = productIndex
      ..['sourceOrderProductName'] = productName
      ..['sourceOrderProductPrice'] = rawPrice;

    return AccessibilityPurchaseHistoryItem(
      platform: _stringValue(orderMap['platform']) ?? 'unknown',
      sourceType: 'android_accessibility_order_product',
      productName: productName,
      price: _parsePrice(rawPrice),
      quantity: quantity,
      purchaseDate: _nullableNonEmptyString(orderMap['purchaseDate']),
      imageUrl: _nullableNonEmptyString(orderMap['imageUrl']) ??
          _nullableNonEmptyString(orderMap['thumbnailPath']),
      orderNumber: _nullableNonEmptyString(orderMap['orderNumber']),
      deliveryStatus: _nullableNonEmptyString(orderMap['deliveryStatus']),
      deliveryType: deliveryTypes.isEmpty ? null : deliveryTypes.join(', '),
      raw: raw,
    );
  }

  static List<AccessibilityPurchaseHistoryItem> listFromJsonString(
    String rawJson,
  ) {
    final decoded = jsonDecode(rawJson);
    if (decoded is! List) {
      return const <AccessibilityPurchaseHistoryItem>[];
    }

    return decoded
        .whereType<Map>()
        .map(
          (item) => item.map((key, value) => MapEntry(key.toString(), value)),
        )
        .map(AccessibilityPurchaseHistoryItem.fromMap)
        .toList(growable: false);
  }

  static List<AccessibilityPurchaseHistoryItem> expandedListFromJsonString(
    String rawJson,
  ) {
    final decoded = jsonDecode(rawJson);
    if (decoded is! List) {
      return const <AccessibilityPurchaseHistoryItem>[];
    }

    final expandedItems = <AccessibilityPurchaseHistoryItem>[];
    for (final rawOrder in decoded.whereType<Map>()) {
      final orderMap = rawOrder.map(
        (key, value) => MapEntry(key.toString(), value),
      );
      final productNames = _deduplicateProductNames(
        _stringListFrom(orderMap['productNames']),
      );
      final prices = _stringListFrom(orderMap['prices']);
      final quantities = _intListFrom(orderMap['quantities']);

      if (productNames.isEmpty) {
        expandedItems.add(AccessibilityPurchaseHistoryItem.fromMap(orderMap));
        continue;
      }

      for (var index = 0; index < productNames.length; index += 1) {
        expandedItems.add(
          AccessibilityPurchaseHistoryItem.fromOrderProduct(
            orderMap: orderMap,
            productName: productNames[index],
            productIndex: index,
            rawPrice: index < prices.length ? prices[index] : null,
            quantity: index < quantities.length ? quantities[index] : 1,
          ),
        );
      }
    }

    return expandedItems;
  }

  Map<String, dynamic> toBackendJson() {
    return <String, dynamic>{
      'platform': platform,
      'sourceType': sourceType,
      'productName': productName,
      'price': price,
      'quantity': quantity,
      'purchaseDate': purchaseDate,
      'imageUrl': imageUrl,
      'orderNumber': orderNumber,
      'deliveryStatus': deliveryStatus,
      'deliveryType': deliveryType,
      'raw': raw,
    };
  }

  static List<String> _stringListFrom(dynamic value) {
    if (value is List) {
      return value
          .map((item) => item?.toString().trim() ?? '')
          .where((item) => item.isNotEmpty)
          .toList(growable: false);
    }
    final text = value?.toString().trim();
    if (text == null || text.isEmpty) {
      return const <String>[];
    }
    return <String>[text];
  }

  static List<int> _intListFrom(dynamic value) {
    if (value is List) {
      return value
          .map((item) => int.tryParse(item?.toString() ?? ''))
          .whereType<int>()
          .where((item) => item > 0)
          .toList(growable: false);
    }
    final parsed = int.tryParse(value?.toString() ?? '');
    if (parsed == null || parsed <= 0) {
      return const <int>[];
    }
    return <int>[parsed];
  }

  static String? _stringValue(dynamic value) {
    final text = value?.toString().trim();
    return text == null || text.isEmpty ? null : text;
  }

  static String? _nullableNonEmptyString(dynamic value) {
    final text = _stringValue(value);
    if (text == null || text.isEmpty) {
      return null;
    }
    return text;
  }

  static List<String> _deduplicateProductNames(List<String> productNames) {
    final seen = <String>{};
    final result = <String>[];
    for (final rawName in productNames) {
      final productName = _normalizeProductName(rawName);
      if (productName == null || seen.contains(productName)) {
        continue;
      }
      seen.add(productName);
      result.add(productName);
    }
    return result;
  }

  static String? _normalizeProductName(String rawName) {
    final productName = rawName
        .replaceFirst(RegExp(r'^(품절|구매불가)\s*'), '')
        .trim();
    if (productName.isEmpty || productName == '상품명 확인 필요') {
      return null;
    }
    return productName;
  }

  static int? _parsePrice(String? rawPrice) {
    if (rawPrice == null) {
      return null;
    }
    final digits = rawPrice.replaceAll(RegExp(r'[^0-9]'), '');
    if (digits.isEmpty) {
      return null;
    }
    return int.tryParse(digits);
  }
}
