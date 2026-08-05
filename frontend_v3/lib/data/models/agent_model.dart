class ShoppingRequest {
  ShoppingRequest({
    required this.userId,
    required this.message,
    this.inputType = 'text',
  });

  final int userId;
  final String message;
  final String inputType;

  Map<String, dynamic> toJson() => <String, dynamic>{
    'userId': userId,
    'message': message,
    'inputType': inputType,
  };
}

class MessageRequest {
  MessageRequest({required this.message, this.inputType = 'text'});

  final String message;
  final String inputType;

  Map<String, dynamic> toJson() => <String, dynamic>{
    'message': message,
    'inputType': inputType,
  };
}

class ConfirmRequest {
  ConfirmRequest({required this.recommendationItemId, required this.action});

  final int recommendationItemId;
  final String action;

  Map<String, dynamic> toJson() => <String, dynamic>{
    'recommendationItemId': recommendationItemId,
    'action': action,
  };
}

class RecommendationItemInAgent {
  RecommendationItemInAgent({
    required this.recommendationItemId,
    required this.productId,
    required this.productName,
    required this.price,
    required this.rank,
    this.brand,
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

  factory RecommendationItemInAgent.fromJson(Map<String, dynamic> json) {
    return RecommendationItemInAgent(
      recommendationItemId: json['recommendationItemId'] as int,
      productId: json['productId'] as int,
      productName: json['productName'] as String,
      brand: json['brand'] as String?,
      price: json['price'] as int,
      rank: json['rank'] as int,
      optionText: json['optionText'] as String?,
      deliveryInfo: json['deliveryInfo'] as String?,
      deliveryFee: json['deliveryFee'] as int?,
      rating: (json['rating'] as num?)?.toDouble(),
      reviewCount: json['reviewCount'] as int?,
      imageUrl: json['imageUrl'] as String?,
      productUrl: json['productUrl'] as String?,
      platform: json['platform'] as String?,
      reason: json['reason'] as String?,
      isSelected: json['isSelected'] as bool? ?? false,
      isOrderable: json['isOrderable'] as bool? ?? true,
      orderBlockReason: json['orderBlockReason'] as String?,
    );
  }
}

class AgentResponse {
  AgentResponse({
    required this.conversationId,
    required this.status,
    required this.stage,
    required this.assistantMessage,
    this.message,
    this.speechMode,
    this.speechSegments = const <SpeechSegmentModel>[],
    this.recommendationId,
    this.recommendations = const <RecommendationItemInAgent>[],
    this.selectedProduct,
    this.pendingConfirmation,
    this.availableOptions,
    this.deliveryAddress,
    this.cart,
    this.order,
    this.payment,
    this.uiCommand,
    this.asyncStatus,
    this.error,
  });

  final int conversationId;
  final String status;
  final String stage;
  final String assistantMessage;
  final String? message;
  final String? speechMode;
  final List<SpeechSegmentModel> speechSegments;
  final int? recommendationId;
  final List<RecommendationItemInAgent> recommendations;
  final dynamic selectedProduct;
  final dynamic pendingConfirmation;
  final dynamic availableOptions;
  final dynamic deliveryAddress;
  final dynamic cart;
  final dynamic order;
  final dynamic payment;
  final dynamic uiCommand;
  final dynamic asyncStatus;
  final dynamic error;

  factory AgentResponse.fromJson(Map<String, dynamic> json) {
    final speechSegments =
        (json['speechSegments'] as List<dynamic>? ?? const <dynamic>[])
            .whereType<Map>()
            .map(
              (segment) => SpeechSegmentModel.fromJson(
                Map<String, dynamic>.from(segment),
              ),
            )
            .toList()
          ..sort((a, b) => a.index.compareTo(b.index));

    final recommendations =
        (json['recommendations'] as List<dynamic>? ?? const <dynamic>[])
            .whereType<Map>()
            .map(
              (item) => RecommendationItemInAgent.fromJson(
                Map<String, dynamic>.from(item),
              ),
            )
            .toList()
          ..sort((a, b) => a.rank.compareTo(b.rank));

    return AgentResponse(
      conversationId: json['conversationId'] as int,
      status: json['status'] as String,
      stage: json['stage'] as String,
      assistantMessage:
          json['assistantMessage'] as String? ??
          json['message'] as String? ??
          '',
      message: json['message'] as String?,
      speechMode: json['speechMode'] as String?,
      speechSegments: speechSegments,
      recommendationId: json['recommendationId'] as int?,
      recommendations: recommendations,
      selectedProduct: json['selectedProduct'],
      pendingConfirmation: json['pendingConfirmation'],
      availableOptions: json['availableOptions'],
      deliveryAddress: json['deliveryAddress'],
      cart: json['cart'],
      order: json['order'],
      payment: json['payment'],
      uiCommand: json['uiCommand'],
      asyncStatus: json['asyncStatus'],
      error: json['error'],
    );
  }
}

class SpeechSegmentModel {
  const SpeechSegmentModel({
    required this.index,
    required this.text,
    this.audioUrl,
    this.durationMs,
  });

  final int index;
  final String text;
  final String? audioUrl;
  final int? durationMs;

  factory SpeechSegmentModel.fromJson(Map<String, dynamic> json) {
    return SpeechSegmentModel(
      index: json['index'] as int? ?? 0,
      text: json['text'] as String? ?? '',
      audioUrl: json['audioUrl'] as String?,
      durationMs: json['durationMs'] as int?,
    );
  }
}
