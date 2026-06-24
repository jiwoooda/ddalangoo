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

class ProductViewData {
  const ProductViewData({
    this.platform,
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

  static ProductViewData mock({String? productUrl}) {
    return ProductViewData(
      platform: 'Kurly',
      productUrl: productUrl,
      title: '[김재규우리떡연구소] 흑임자 쑥 인절미',
      quantityInfo: '70g x 7개',
      price: 12900,
      priceText: '12,900원',
      badgeText: '리뷰가 좋고 30일 중 가장 싼 가격이에요',
    );
  }
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
  });

  final String userName;
  final String phone;
  final String address;
  final List<CartItemViewData> items;
  final int totalPrice;

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

class ShoppingAgentResponse {
  const ShoppingAgentResponse({
    this.conversationId,
    required this.assistantMessage,
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
