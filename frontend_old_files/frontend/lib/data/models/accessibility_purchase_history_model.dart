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

    return AccessibilityPurchaseHistoryItem(
      platform: _stringValue(map['platform']) ?? 'unknown',
      sourceType: 'android_accessibility',
      productName: '상품명 확인 필요',
      price: _parsePrice(prices.isEmpty ? null : prices.first),
      quantity: 1,
      purchaseDate: null,
      imageUrl: null,
      orderNumber: _nullableNonEmptyString(map['orderNumber']),
      deliveryStatus: _nullableNonEmptyString(map['deliveryStatus']),
      deliveryType: deliveryTypes.isEmpty ? null : deliveryTypes.join(', '),
      raw: Map<String, dynamic>.from(map),
    );
  }

  static List<AccessibilityPurchaseHistoryItem> listFromJsonString(
    String rawJson,
  ) {
    final decoded = jsonDecode(rawJson);
    if (decoded is! List) return const [];

    return decoded
        .whereType<Map>()
        .map(
          (item) => item.map((key, value) => MapEntry(key.toString(), value)),
        )
        .map(AccessibilityPurchaseHistoryItem.fromMap)
        .toList(growable: false);
  }

  static List<String> _stringListFrom(dynamic value) {
    if (value is List) {
      return value
          .map((item) => item?.toString().trim() ?? '')
          .where((item) => item.isNotEmpty)
          .toList(growable: false);
    }
    final text = value?.toString().trim();
    if (text == null || text.isEmpty) return const [];
    return [text];
  }

  static String? _stringValue(dynamic value) {
    final text = value?.toString().trim();
    return text == null || text.isEmpty ? null : text;
  }

  static String? _nullableNonEmptyString(dynamic value) {
    final text = _stringValue(value);
    if (text == null || text.isEmpty) return null;
    return text;
  }

  static int? _parsePrice(String? rawPrice) {
    if (rawPrice == null) return null;
    final digits = rawPrice.replaceAll(RegExp(r'[^0-9]'), '');
    if (digits.isEmpty) return null;
    return int.tryParse(digits);
  }
}
