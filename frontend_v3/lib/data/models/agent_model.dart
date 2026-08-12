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

class AutomationTaskInAgent {
  AutomationTaskInAgent({
    this.contractVersion = 1,
    required this.taskId,
    required this.taskType,
    this.conversationId,
    this.userId,
    this.platform,
    this.packageName,
    this.currentStep,
    this.targetProductName,
    this.searchKeyword,
    this.optionName,
    this.quantity = 1,
    this.cartItemId,
    this.orderId,
    this.paymentId,
    this.metadata = const <String, dynamic>{},
  });

  final int contractVersion;
  final String taskId;
  final String taskType;
  final int? conversationId;
  final int? userId;
  final String? platform;
  final String? packageName;
  final String? currentStep;
  final String? targetProductName;
  final String? searchKeyword;
  final String? optionName;
  final int quantity;
  final String? cartItemId;
  final int? orderId;
  final int? paymentId;
  final Map<String, dynamic> metadata;

  factory AutomationTaskInAgent.fromJson(Map<String, dynamic> json) {
    return AutomationTaskInAgent(
      contractVersion: _intOf(json['contractVersion']) ?? 1,
      taskId: json['taskId']?.toString() ?? '',
      taskType: json['taskType']?.toString() ?? '',
      conversationId: _intOf(json['conversationId']),
      userId: _intOf(json['userId']),
      platform: json['platform']?.toString(),
      packageName: json['packageName']?.toString(),
      currentStep: json['currentStep']?.toString(),
      targetProductName: json['targetProductName']?.toString(),
      searchKeyword: json['searchKeyword']?.toString(),
      optionName: json['optionName']?.toString(),
      quantity: _intOf(json['quantity']) ?? 1,
      cartItemId: json['cartItemId']?.toString(),
      orderId: _intOf(json['orderId']),
      paymentId: _intOf(json['paymentId']),
      metadata: json['metadata'] is Map
          ? Map<String, dynamic>.from(json['metadata'] as Map)
          : const <String, dynamic>{},
    );
  }
}

class AutomationResultInAgent {
  AutomationResultInAgent({
    this.contractVersion = 1,
    required this.taskId,
    required this.status,
    this.taskType,
    this.platform,
    this.packageName,
    this.currentStep,
    this.resultType,
    this.payload = const <String, dynamic>{},
    this.errorCode,
    this.errorMessage,
    this.message,
    this.metadata = const <String, dynamic>{},
  });

  final int contractVersion;
  final String taskId;
  final String status;
  final String? taskType;
  final String? platform;
  final String? packageName;
  final String? currentStep;
  final String? resultType;
  final Map<String, dynamic> payload;
  final String? errorCode;
  final String? errorMessage;
  final String? message;
  final Map<String, dynamic> metadata;

  factory AutomationResultInAgent.fromJson(Map<String, dynamic> json) {
    return AutomationResultInAgent(
      contractVersion: _intOf(json['contractVersion']) ?? 1,
      taskId: json['taskId']?.toString() ?? '',
      status: json['status']?.toString() ?? '',
      taskType: json['taskType']?.toString(),
      platform: json['platform']?.toString(),
      packageName: json['packageName']?.toString(),
      currentStep: json['currentStep']?.toString(),
      resultType: json['resultType']?.toString(),
      payload: json['payload'] is Map
          ? Map<String, dynamic>.from(json['payload'] as Map)
          : const <String, dynamic>{},
      errorCode: json['errorCode']?.toString(),
      errorMessage: json['errorMessage']?.toString(),
      message: json['message']?.toString(),
      metadata: json['metadata'] is Map
          ? Map<String, dynamic>.from(json['metadata'] as Map)
          : const <String, dynamic>{},
    );
  }
}

class AutomationResultRequest {
  AutomationResultRequest({
    this.contractVersion = 1,
    required this.taskId,
    required this.status,
    this.taskType,
    this.currentStep,
    this.platform,
    this.packageName,
    this.resultType,
    this.errorCode,
    this.errorMessage,
    this.payload = const <String, dynamic>{},
    this.metadata = const <String, dynamic>{},
  });

  final int contractVersion;
  final String taskId;
  final String status;
  final String? taskType;
  final String? currentStep;
  final String? platform;
  final String? packageName;
  final String? resultType;
  final String? errorCode;
  final String? errorMessage;
  final Map<String, dynamic> payload;
  final Map<String, dynamic> metadata;

  factory AutomationResultRequest.fromRuntimeResult(
    Map<String, dynamic> result,
  ) {
    final metadata = result['metadata'] is Map
        ? Map<String, dynamic>.from(result['metadata'] as Map)
        : const <String, dynamic>{};
    final payload = result['payload'] is Map
        ? Map<String, dynamic>.from(result['payload'] as Map)
        : const <String, dynamic>{};

    return AutomationResultRequest(
      contractVersion: _intOf(result['contractVersion']) ?? 1,
      taskId: result['taskId']?.toString() ?? '',
      status: result['status']?.toString() ?? 'failed',
      taskType: result['taskType']?.toString(),
      currentStep: result['currentStep']?.toString(),
      platform: result['platform']?.toString(),
      packageName: result['packageName']?.toString(),
      resultType: result['resultType']?.toString(),
      errorCode: result['errorCode']?.toString(),
      errorMessage:
          result['errorMessage']?.toString() ?? result['message']?.toString(),
      payload: payload,
      metadata: metadata,
    );
  }

  Map<String, dynamic> toJson() {
    return <String, dynamic>{
      'contractVersion': contractVersion,
      'taskId': taskId,
      'status': status,
      'taskType': taskType,
      'currentStep': currentStep,
      'platform': platform,
      'packageName': packageName,
      'resultType': resultType,
      'errorCode': errorCode,
      'errorMessage': errorMessage,
      'payload': payload,
      'metadata': metadata,
    }..removeWhere((_, value) => value == null);
  }
}

abstract final class AutomationContract {
  static const version = 1;

  static const statusCompleted = 'completed';
  static const statusFailed = 'failed';
  static const statusRequiresUserAction = 'requires_user_action';
  static const statusNeedsUserConfirmation = 'needs_user_confirmation';

  static const taskSearchAndAddToCart = 'search_and_add_to_cart';
  static const taskPurchaseHistory = 'purchase_history';
  static const taskCheckoutPlatformCart = 'checkout_platform_cart';
}

class AgentResponse {
  AgentResponse({
    required this.conversationId,
    required this.status,
    required this.stage,
    required this.assistantMessage,
    this.message,
    this.messageSentences = const <String>[],
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
    this.automationTask,
    this.automationResult,
    this.asyncStatus,
    this.error,
  });

  final int conversationId;
  final String status;
  final String stage;
  final String assistantMessage;
  final String? message;
  final List<String> messageSentences;
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
  final AutomationTaskInAgent? automationTask;
  final AutomationResultInAgent? automationResult;
  final dynamic asyncStatus;
  final dynamic error;

  factory AgentResponse.fromJson(Map<String, dynamic> json) {
    final messageSentences =
        (json['messageSentences'] as List<dynamic>? ?? const <dynamic>[])
            .map((sentence) => sentence.toString().trim())
            .where((sentence) => sentence.isNotEmpty)
            .toList(growable: false);

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
      messageSentences: messageSentences,
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
      automationTask: json['automationTask'] is Map
          ? AutomationTaskInAgent.fromJson(
              Map<String, dynamic>.from(json['automationTask'] as Map),
            )
          : null,
      automationResult: json['automationResult'] is Map
          ? AutomationResultInAgent.fromJson(
              Map<String, dynamic>.from(json['automationResult'] as Map),
            )
          : null,
      asyncStatus: json['asyncStatus'],
      error: json['error'],
    );
  }
}

int? _intOf(Object? value) {
  if (value is int) {
    return value;
  }
  if (value is num) {
    return value.toInt();
  }
  if (value is String) {
    return int.tryParse(value);
  }
  return null;
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
