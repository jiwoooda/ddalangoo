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
}
