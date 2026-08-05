import 'package:dio/dio.dart';

import '../../core/network/api_client.dart';
import '../models/purchase_history_model.dart';

class PurchaseHistoryRepository {
  PurchaseHistoryRepository({Dio? dio}) : _dio = dio ?? ApiClient.dio;

  final Dio _dio;

  Future<PurchaseHistoryListResponse> getUserHistories({
    required int userId,
    String? keyword,
    String? category,
    int? limit,
  }) async {
    final queryParameters = <String, dynamic>{
      if (keyword?.trim().isNotEmpty ?? false) 'keyword': keyword,
      if (category?.trim().isNotEmpty ?? false) 'category': category,
    };
    if (limit != null) {
      queryParameters['limit'] = limit;
    }

    final response = await _dio.get(
      '/api/users/$userId/purchase-histories',
      queryParameters: queryParameters,
    );
    return PurchaseHistoryListResponse.fromJson(
      Map<String, dynamic>.from(response.data as Map),
    );
  }
}
