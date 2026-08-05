class CartItemResponse {
  CartItemResponse({
    required this.cartItemId,
    required this.productId,
    required this.productName,
    required this.unitPrice,
    required this.quantity,
    required this.totalPrice,
    this.productOptionId,
    this.optionText,
  });

  final int cartItemId;
  final int productId;
  final int? productOptionId;
  final String productName;
  final String? optionText;
  final int unitPrice;
  final int quantity;
  final int totalPrice;

  factory CartItemResponse.fromJson(Map<String, dynamic> json) {
    return CartItemResponse(
      cartItemId: json['cartItemId'] as int,
      productId: json['productId'] as int,
      productOptionId: json['productOptionId'] as int?,
      productName: json['productName'] as String,
      optionText: json['optionText'] as String?,
      unitPrice: json['unitPrice'] as int,
      quantity: json['quantity'] as int,
      totalPrice: json['totalPrice'] as int,
    );
  }
}

class CartResponse {
  CartResponse({
    required this.cartId,
    required this.userId,
    required this.status,
    required this.items,
  });

  final int? cartId;
  final int userId;
  final String status;
  final List<CartItemResponse> items;

  factory CartResponse.fromJson(Map<String, dynamic> json) {
    final items = (json['items'] as List<dynamic>? ?? const <dynamic>[])
        .whereType<Map>()
        .map(
          (item) => CartItemResponse.fromJson(Map<String, dynamic>.from(item)),
        )
        .toList(growable: false);

    return CartResponse(
      cartId: json['cartId'] as int?,
      userId: json['userId'] as int,
      status: json['status'] as String? ?? 'active',
      items: items,
    );
  }
}
