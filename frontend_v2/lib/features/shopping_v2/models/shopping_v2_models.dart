enum ShoppingStep {
  askProduct,
  searchingProduct,
  showProduct,
  askQuantity,
  addingToCart,
  cartCompleted,
  askMoreOrCheckout,
  confirmAddress,
  enterPassword,
  processingPayment,
  paymentCompleted,
  error,
}

enum VoiceTurnState {
  idle,
  agentSpeaking,
  userCanSpeak,
  userRecording,
  transcribing,
  agentThinking,
  error,
}

enum TurnDetectionStatus {
  complete,
  incomplete,
  noiseOrEmpty,
}

class TurnDetectionViewData {
  const TurnDetectionViewData({
    required this.status,
    required this.mergedTranscript,
    this.reason,
    this.shouldAskClarification = false,
  });

  final TurnDetectionStatus status;
  final String mergedTranscript;
  final String? reason;
  final bool shouldAskClarification;
}

class ProductViewData {
  const ProductViewData({
    this.platform,
    this.shopName,
    this.productUrl,
    this.imageUrl,
    required this.title,
    this.subtitle,
    this.quantityInfo,
    this.price,
    this.priceText,
    this.badgeText,
  });

  final String? platform;
  final String? shopName;
  final String? productUrl;
  final String? imageUrl;
  final String? subtitle;
  final String title;
  final String? quantityInfo;
  final int? price;
  final String? priceText;
  final String? badgeText;

  String get displayPrice =>
      priceText ?? (price != null ? '${_formatPrice(price!)}원' : '');

  String get displayTitle {
    final normalized = _ensureMarketPrefix(title, shopName);
    final extracted = _extractQuantityFromTitle(normalized);
    if (extracted == null) {
      return normalized.trim();
    }
    return normalized.replaceFirst(extracted, '').trim();
  }

  String get displayQuantityInfo =>
      (quantityInfo != null && quantityInfo!.trim().isNotEmpty)
      ? quantityInfo!.trim()
      : (_extractQuantityLabelFromTitle(title)?.trim() ?? '');

  static ProductViewData mock({String? productUrl}) {
    return ProductViewData(
      platform: 'Kurly',
      shopName: '컬리N마트',
      productUrl: productUrl,
      title: '[김재규우리떡연구소] 흑임자 쑥 인절미',
      quantityInfo: '70g x 7개',
      price: 12900,
      priceText: '12,900원',
      badgeText: '리뷰가 좋고 30일 중 가장 싼 가격이에요',
    );
  }
}

String? _extractQuantityFromTitle(String text) {
  final parenthesized = RegExp(r'\(([^()]*\d[^()]*)\)\s*$').firstMatch(text.trim());
  if (parenthesized != null) {
    return parenthesized.group(0);
  }

  final inline = _extractQuantityLabelFromTitle(text);
  if (inline == null) {
    return null;
  }
  final escaped = RegExp.escape(inline);
  final inlineMatch = RegExp('$escaped\\s*\$').firstMatch(text.trim());
  return inlineMatch?.group(0) ?? inline;
}

String? _extractQuantityLabelFromTitle(String text) {
  final normalized = text.replaceAll(RegExp(r'\s+'), ' ').trim();
  final patterns = <RegExp>[
    RegExp(r'(\d+(?:\.\d+)?\s*(?:g|kg|ml|L|개입|봉|팩|입)\s*[,xX]\s*\d+\s*개)\s*$', caseSensitive: false),
    RegExp(r'(\d+(?:\.\d+)?\s*(?:g|kg|ml|L|개입|봉|팩|입)\s*,\s*\d+\s*개)\s*$', caseSensitive: false),
    RegExp(r'(\d+(?:\.\d+)?\s*(?:g|kg|ml|L|개입|봉|팩|입))\s*[,/]\s*(\d+\s*개)\s*$', caseSensitive: false),
    RegExp(r'(\d+(?:\.\d+)?\s*(?:g|kg|ml|L|개입|봉|팩|입))\s*$', caseSensitive: false),
  ];

  for (final pattern in patterns) {
    final match = pattern.firstMatch(normalized);
    if (match == null) {
      continue;
    }
    if (match.groupCount >= 2 && match.group(2) != null) {
      return '${match.group(1)!.trim()} x ${match.group(2)!.trim()}';
    }
    return match.group(1)?.trim();
  }
  return null;
}

String _ensureMarketPrefix(String title, String? shopName) {
  final trimmedTitle = title.trim();
  final trimmedShopName = shopName?.trim();
  if (trimmedShopName == null || trimmedShopName.isEmpty) {
    return trimmedTitle;
  }
  if (RegExp(r'^\[[^\]]+\]').hasMatch(trimmedTitle)) {
    return trimmedTitle;
  }
  return '[$trimmedShopName] $trimmedTitle';
}

class CartItemViewData {
  const CartItemViewData({
    required this.product,
    required this.quantity,
    this.totalPrice,
    this.totalPriceText,
  });

  final ProductViewData product;
  final int quantity;
  final int? totalPrice;
  final String? totalPriceText;

  String get displayTotalPrice =>
      totalPriceText ??
      (totalPrice != null
          ? '${_formatPrice(totalPrice!)}원'
          : product.displayPrice);
}

class CheckoutSummary {
  const CheckoutSummary({
    required this.userName,
    required this.phone,
    required this.address,
    required this.items,
    required this.totalPrice,
    this.deliveryRequest = '',
  });

  final String userName;
  final String phone;
  final String address;
  final List<CartItemViewData> items;
  final int totalPrice;
  final String deliveryRequest;

  String get totalPriceText => '${_formatPrice(totalPrice)}원';

  static CheckoutSummary mock(List<CartItemViewData> items) {
    final effectiveItems = items.isEmpty
        ? [
            CartItemViewData(
              product: ProductViewData.mock(),
              quantity: 1,
              totalPrice: 12900,
              totalPriceText: '12,900원',
            ),
          ]
        : items;
    final total = effectiveItems.fold<int>(
      0,
      (sum, item) =>
          sum + (item.totalPrice ?? (item.product.price ?? 0) * item.quantity),
    );
    return CheckoutSummary(
      userName: '김영희',
      phone: '010-1234-5678',
      address: '서울 용산구 청파로 47길 100 명신관 1층 코딩라운지',
      items: effectiveItems,
      totalPrice: total,
    );
  }
}

class SpeechSegmentViewData {
  const SpeechSegmentViewData({
    required this.index,
    required this.text,
    this.audioUrl,
    this.durationMs,
  });

  final int index;
  final String text;
  final String? audioUrl;
  final int? durationMs;
}

class WebviewTaskViewData {
  const WebviewTaskViewData({
    required this.commandKey,
    required this.url,
    this.platform,
    this.shopName,
    this.task,
    this.orderId,
    this.paymentId,
    this.productName,
    this.quantity = 1,
    this.canonicalProductUrl,
  });

  final String commandKey;
  final String url;
  final String? platform;
  final String? shopName;
  final String? task;
  final int? orderId;
  final int? paymentId;
  final String? productName;
  final int quantity;
  final String? canonicalProductUrl;
}

class ShoppingAgentResponse {
  const ShoppingAgentResponse({
    this.conversationId,
    required this.assistantMessage,
    this.message,
    this.speechMode,
    this.speechSegments = const [],
    this.status,
    this.stage,
    this.pendingConfirmation,
    this.selectedProduct,
    this.recommendations = const [],
    this.deliveryAddress,
    this.cart,
    this.order,
    this.payment,
    this.uiCommand,
    this.asyncStatus,
    this.error,
    this.raw = const {},
  });

  final int? conversationId;
  final String assistantMessage;
  final String? message;
  final String? speechMode;
  final List<SpeechSegmentViewData> speechSegments;
  final String? status;
  final String? stage;
  final Map<String, dynamic>? pendingConfirmation;
  final Map<String, dynamic>? selectedProduct;
  final List<Map<String, dynamic>> recommendations;
  final Map<String, dynamic>? deliveryAddress;
  final Map<String, dynamic>? cart;
  final Map<String, dynamic>? order;
  final Map<String, dynamic>? payment;
  final Map<String, dynamic>? uiCommand;
  final Map<String, dynamic>? asyncStatus;
  final Object? error;
  final Map<String, dynamic> raw;
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
