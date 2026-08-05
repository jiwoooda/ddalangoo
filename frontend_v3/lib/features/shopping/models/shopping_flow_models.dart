enum ShoppingFlowViewStage {
  askProduct,
  searchingProduct,
  productSelection,
  quantitySelection,
  cartProcessing,
  cartCompleted,
  addressConfirmation,
  paymentConfirmation,
  paymentPassword,
  paymentProcessing,
  completed,
  error,
}

class ShoppingProductViewData {
  const ShoppingProductViewData({
    this.recommendationItemId,
    required this.title,
    this.brand,
    this.optionText,
    this.deliveryInfo,
    this.reason,
    this.imageUrl,
    this.productUrl,
    this.platform,
    this.price,
    this.rank,
    this.isOrderable = true,
    this.orderBlockReason,
  });

  final int? recommendationItemId;
  final String title;
  final String? brand;
  final String? optionText;
  final String? deliveryInfo;
  final String? reason;
  final String? imageUrl;
  final String? productUrl;
  final String? platform;
  final int? price;
  final int? rank;
  final bool isOrderable;
  final String? orderBlockReason;

  String get displayPrice {
    if (price == null || price! <= 0) {
      return '가격 확인 중';
    }
    return '${formatPrice(price!)}원';
  }

  String get detailLine {
    final parts = [
      if (brand != null && brand!.trim().isNotEmpty) brand!.trim(),
      if (optionText != null && optionText!.trim().isNotEmpty)
        optionText!.trim(),
      if (deliveryInfo != null && deliveryInfo!.trim().isNotEmpty)
        deliveryInfo!.trim(),
    ];
    return parts.join(' · ');
  }
}

class ShoppingCartItemViewData {
  const ShoppingCartItemViewData({
    required this.product,
    required this.quantity,
    this.totalPrice,
  });

  final ShoppingProductViewData product;
  final int quantity;
  final int? totalPrice;

  String get displayTotalPrice {
    final effectivePrice =
        totalPrice ??
        ((product.price == null || quantity <= 0)
            ? null
            : product.price! * quantity);
    if (effectivePrice == null || effectivePrice <= 0) {
      return product.displayPrice;
    }
    return '${formatPrice(effectivePrice)}원';
  }
}

class ShoppingAddressViewData {
  const ShoppingAddressViewData({
    this.label,
    this.recipientName,
    this.recipientPhone,
    this.zipCode,
    this.addressLine1,
    this.addressLine2,
    this.deliveryRequest,
    this.isDefault = false,
  });

  final String? label;
  final String? recipientName;
  final String? recipientPhone;
  final String? zipCode;
  final String? addressLine1;
  final String? addressLine2;
  final String? deliveryRequest;
  final bool isDefault;

  String get displayAddress {
    final parts = <String>[
      if (addressLine1 != null && addressLine1!.trim().isNotEmpty)
        addressLine1!.trim(),
      if (addressLine2 != null && addressLine2!.trim().isNotEmpty)
        addressLine2!.trim(),
    ];
    return parts.isEmpty ? '배송지 정보를 확인하고 있어요.' : parts.join(' ');
  }

  String get displayRecipient {
    final name = recipientName?.trim();
    final phone = recipientPhone?.trim();
    if (name == null || name.isEmpty) {
      return phone == null || phone.isEmpty ? '주문자 정보 확인 중' : phone;
    }
    if (phone == null || phone.isEmpty) {
      return name;
    }
    return '$name · $phone';
  }

  String get displayDeliveryRequest {
    final request = deliveryRequest?.trim();
    if (request == null || request.isEmpty) {
      return '배송 요청사항 없음';
    }
    return request;
  }
}

class ShoppingWebviewTaskViewData {
  const ShoppingWebviewTaskViewData({
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

String formatPrice(int value) {
  final digits = value.toString();
  final buffer = StringBuffer();
  for (var index = 0; index < digits.length; index += 1) {
    buffer.write(digits[index]);
    final remaining = digits.length - index - 1;
    if (remaining > 0 && remaining % 3 == 0) {
      buffer.write(',');
    }
  }
  return buffer.toString();
}
