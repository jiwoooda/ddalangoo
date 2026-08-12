import 'package:dio/dio.dart';

import '../../core/network/api_client.dart';
import '../models/cart_model.dart';

class CartRepository {
  final Dio _dio = ApiClient.dio;

  Future<CartResponse> getUserCart(int userId) async {
    final response = await _dio.get('/api/users/$userId/cart');
    return CartResponse.fromJson(
      Map<String, dynamic>.from(response.data as Map),
    );
  }

  Future<CartItemResponse> addCartItem({
    required int cartId,
    required int productId,
    int? productOptionId,
    int quantity = 1,
  }) async {
    final response = await _dio.post(
      '/api/carts/$cartId/items',
      data: <String, dynamic>{
        'productId': productId,
        'productOptionId': productOptionId,
        'quantity': quantity,
      },
    );
    return CartItemResponse.fromJson(
      Map<String, dynamic>.from(response.data as Map),
    );
  }

  Future<void> deleteCartItem({
    required int cartId,
    required int cartItemId,
  }) async {
    await _dio.delete('/api/carts/$cartId/items/$cartItemId');
  }
}
