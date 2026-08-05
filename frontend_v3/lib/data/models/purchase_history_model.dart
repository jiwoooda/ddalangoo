class AccessibilityPurchaseHistoryImportResponse {
  const AccessibilityPurchaseHistoryImportResponse({
    required this.success,
    required this.count,
    required this.historyIds,
    required this.skippedCount,
    required this.skippedItems,
  });

  final bool success;
  final int count;
  final List<int> historyIds;
  final int skippedCount;
  final List<Map<String, dynamic>> skippedItems;

  factory AccessibilityPurchaseHistoryImportResponse.fromJson(
    Map<String, dynamic> json,
  ) {
    return AccessibilityPurchaseHistoryImportResponse(
      success: json['success'] == true,
      count: json['count'] as int? ?? 0,
      historyIds: (json['historyIds'] as List<dynamic>? ?? const <dynamic>[])
          .whereType<int>()
          .toList(growable: false),
      skippedCount: json['skippedCount'] as int? ?? 0,
      skippedItems:
          (json['skippedItems'] as List<dynamic>? ?? const <dynamic>[])
              .whereType<Map>()
              .map(
                (item) =>
                    item.map((key, value) => MapEntry(key.toString(), value)),
              )
              .toList(growable: false),
    );
  }
}

class PurchaseHistoryItemModel {
  const PurchaseHistoryItemModel({
    required this.purchaseHistoryId,
    required this.productName,
    required this.priceAtPurchase,
    required this.quantity,
    required this.totalPrice,
    required this.purchasedAt,
    this.brand,
    this.category,
    this.optionText,
    this.selectedOptions,
    this.productUrl,
    this.platform,
    this.satisfaction,
    this.memo,
  });

  final int purchaseHistoryId;
  final String productName;
  final String? brand;
  final String? category;
  final String? optionText;
  final Map<String, dynamic>? selectedOptions;
  final String? productUrl;
  final int priceAtPurchase;
  final int quantity;
  final int totalPrice;
  final String? platform;
  final String purchasedAt;
  final int? satisfaction;
  final String? memo;

  factory PurchaseHistoryItemModel.fromJson(Map<String, dynamic> json) {
    return PurchaseHistoryItemModel(
      purchaseHistoryId: json['purchaseHistoryId'] as int,
      productName: json['productName'] as String? ?? '',
      brand: json['brand'] as String?,
      category: json['category'] as String?,
      optionText: json['optionText'] as String?,
      selectedOptions: json['selectedOptions'] is Map
          ? Map<String, dynamic>.from(json['selectedOptions'] as Map)
          : null,
      productUrl: json['productUrl'] as String?,
      priceAtPurchase: json['priceAtPurchase'] as int? ?? 0,
      quantity: json['quantity'] as int? ?? 1,
      totalPrice: json['totalPrice'] as int? ?? 0,
      platform: json['platform'] as String?,
      purchasedAt: json['purchasedAt'] as String? ?? '',
      satisfaction: json['satisfaction'] as int?,
      memo: json['memo'] as String?,
    );
  }
}

class PurchaseHistoryListResponse {
  const PurchaseHistoryListResponse({
    required this.userId,
    required this.histories,
  });

  final int userId;
  final List<PurchaseHistoryItemModel> histories;

  factory PurchaseHistoryListResponse.fromJson(Map<String, dynamic> json) {
    return PurchaseHistoryListResponse(
      userId: json['userId'] as int,
      histories: (json['histories'] as List<dynamic>? ?? const <dynamic>[])
          .whereType<Map>()
          .map(
            (item) => PurchaseHistoryItemModel.fromJson(
              item.map((key, value) => MapEntry(key.toString(), value)),
            ),
          )
          .toList(growable: false),
    );
  }
}
