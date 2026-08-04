import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart';

import '../network/api_client.dart';
import '../storage/local_storage.dart';

/// API 연결 확인용 테스트 서비스.
/// 로그인/회원가입은 LoginScreen / RegisterScreen이 직접 처리한다.
class ApiTestService {
  final Dio _dio = Dio(
    BaseOptions(
      baseUrl: ApiClient.baseUrl,
      connectTimeout: const Duration(seconds: 5),
      receiveTimeout: const Duration(seconds: 3),
      validateStatus: (status) => true,
    ),
  );

  /// 쇼핑 요청 보내기 테스트 (POST)
  /// LocalStorage에 저장된 userId를 사용한다.
  Future<Map<String, dynamic>?> sendShoppingRequest() async {
    final userId = await LocalStorage.getUserId();
    if (userId == null) {
      debugPrint('❌ [Shopping Request] 로그인 후 이용해주세요 (userId 없음)');
      return null;
    }

    try {
      final res = await _dio.post(
        '/api/agent/shopping-requests',
        data: {
          'userId': userId,
          'message': '저번에 먹었던 딸기 다시 사줘',
          'inputType': 'text',
        },
      );

      debugPrint('✅ [Shopping Request] 성공: ${res.statusCode}');
      debugPrint('응답 데이터: ${res.data}');
      return res.data;
    } catch (e) {
      debugPrint('❌ [Shopping Request] 에러 발생: $e');
      return null;
    }
  }

  // 상품(Products) 연결 확인
  Future<void> checkProducts() async {
    final res = await _dio.get('/api/products', queryParameters: {'limit': 1});
    debugPrint('[Products API] GET /api/products: Status ${res.statusCode}');
  }

  // 유저(Users) 연결 확인
  Future<void> checkUser() async {
    final userId = await LocalStorage.getUserId();
    if (userId == null) return;
    final res = await _dio.get('/api/users/$userId');
    debugPrint('[Users API] GET /api/users/$userId: Status ${res.statusCode}');
  }

  // 장바구니 연결 확인
  Future<void> checkCart() async {
    final userId = await LocalStorage.getUserId();
    if (userId == null) return;
    final res = await _dio.get('/api/users/$userId/cart');
    debugPrint(
      '[Cart API] GET /api/users/$userId/cart: Status ${res.statusCode}',
    );
  }

  // 주문 연결 확인
  Future<void> checkOrders() async {
    final userId = await LocalStorage.getUserId();
    if (userId == null) return;
    final res = await _dio.get(
      '/api/users/$userId/orders',
      queryParameters: {'limit': 1},
    );
    debugPrint(
      '[Orders API] GET /api/users/$userId/orders: Status ${res.statusCode}',
    );
  }

  // 주소록 연결 확인
  Future<void> checkAddresses() async {
    final userId = await LocalStorage.getUserId();
    if (userId == null) return;
    final res = await _dio.get('/api/users/$userId/addresses');
    debugPrint(
      '[Addresses API] GET /api/users/$userId/addresses: Status ${res.statusCode}',
    );
  }

  // 구매 이력 연결 확인
  Future<void> checkHistory() async {
    final userId = await LocalStorage.getUserId();
    if (userId == null) return;
    final res = await _dio.get('/api/users/$userId/purchase-histories');
    debugPrint(
      '[History API] GET /api/users/$userId/purchase-histories: Status ${res.statusCode}',
    );
  }

  /// 통합 테스트 실행
  Future<void> runAllConnectivityTests() async {
    debugPrint('🚀 --- API 연결 테스트 시작 ---');
    await checkProducts();
    await sendShoppingRequest();
    await checkUser();
    await checkCart();
    await checkOrders();
    await checkAddresses();
    await checkHistory();
    debugPrint('🏁 --- API 연결 테스트 종료 ---');
  }
}
