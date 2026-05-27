// Agent 관련 모델

class ShoppingRequest {
  final int userId;
  final String message;
  final String inputType;

  ShoppingRequest({
    required this.userId,
    required this.message,
    this.inputType = 'text',
  });

  Map<String, dynamic> toJson() => {
    'userId': userId,
    'message': message,
    'inputType': inputType,
  };
}

class MessageRequest {
  final String message;
  final String inputType;

  MessageRequest({required this.message, this.inputType = 'text'});

  Map<String, dynamic> toJson() => {'message': message, 'inputType': inputType};
}

class ConfirmRequest {
  final int recommendationItemId;
  final String action; // "accept" or "reject"

  ConfirmRequest({required this.recommendationItemId, required this.action});

  Map<String, dynamic> toJson() => {
    'recommendationItemId': recommendationItemId,
    'action': action,
  };
}

class RecommendationItemInAgent {
  final int recommendationItemId;
  final int productId;
  final String productName;
  final String? brand;
  final int price;
  final int rank;
  final String? optionText;
  final String? deliveryInfo;
  final int? deliveryFee;
  final double? rating;
  final int? reviewCount;
  final String? imageUrl;
  final String? productUrl;
  final String? platform;
  final String? reason;
  final bool isSelected;
  final bool isOrderable;
  final String? orderBlockReason;

  RecommendationItemInAgent({
    required this.recommendationItemId,
    required this.productId,
    required this.productName,
    this.brand,
    required this.price,
    required this.rank,
    this.optionText,
    this.deliveryInfo,
    this.deliveryFee,
    this.rating,
    this.reviewCount,
    this.imageUrl,
    this.productUrl,
    this.platform,
    this.reason,
    this.isSelected = false,
    this.isOrderable = true,
    this.orderBlockReason,
  });

  factory RecommendationItemInAgent.fromJson(Map<String, dynamic> json) =>
      RecommendationItemInAgent(
        recommendationItemId: json['recommendationItemId'],
        productId: json['productId'],
        productName: json['productName'],
        brand: json['brand'],
        price: json['price'],
        rank: json['rank'],
        optionText: json['optionText'],
        deliveryInfo: json['deliveryInfo'],
        deliveryFee: json['deliveryFee'],
        rating: json['rating']?.toDouble(),
        reviewCount: json['reviewCount'],
        imageUrl: json['imageUrl'],
        productUrl: json['productUrl'],
        platform: json['platform'],
        reason: json['reason'],
        isSelected: json['isSelected'] ?? false,
        isOrderable: json['isOrderable'] ?? true,
        orderBlockReason: json['orderBlockReason'],
      );
}

class AgentResponse {
  final int conversationId;
  final String status;
  final String stage;
  final String assistantMessage;
  final int? recommendationId;
  final List<RecommendationItemInAgent> recommendations;
  final dynamic selectedProduct;
  final dynamic pendingConfirmation;
  final dynamic availableOptions;
  final dynamic deliveryAddress;
  final dynamic order;
  final dynamic payment;
  final dynamic uiCommand;
  final dynamic asyncStatus;
  final dynamic error;

  AgentResponse({
    required this.conversationId,
    required this.status,
    required this.stage,
    required this.assistantMessage,
    this.recommendationId,
    this.recommendations = const [],
    this.selectedProduct,
    this.pendingConfirmation,
    this.availableOptions,
    this.deliveryAddress,
    this.order,
    this.payment,
    this.uiCommand,
    this.asyncStatus,
    this.error,
  });

  factory AgentResponse.fromJson(Map<String, dynamic> json) => AgentResponse(
    conversationId: json['conversationId'],
    status: json['status'],
    stage: json['stage'],
    assistantMessage: json['assistantMessage'],
    recommendationId: json['recommendationId'],
    recommendations: ((json['recommendations'] as List? ?? [])
        .map((e) => RecommendationItemInAgent.fromJson(e))
        .toList()
      ..sort((a, b) => a.rank.compareTo(b.rank))),
    selectedProduct: json['selectedProduct'],
    pendingConfirmation: json['pendingConfirmation'],
    availableOptions: json['availableOptions'],
    deliveryAddress: json['deliveryAddress'],
    order: json['order'],
    payment: json['payment'],
    uiCommand: json['uiCommand'],
    asyncStatus: json['asyncStatus'],
    error: json['error'],
  );
}
