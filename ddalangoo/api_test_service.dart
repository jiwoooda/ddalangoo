import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:ddalangoo/core/storage/local_storage.dart';
import 'package:flutter_dotenv/flutter_dotenv.dart';

/// API 연결 확인 및 가상 로그인을 담당하는 테스트 서비스
class ApiTestService {
  final Dio _dio = Dio(
    BaseOptions(
      baseUrl:
          dotenv.env['API_BASE_URL']?.trim().isNotEmpty == true
          ? dotenv.env['API_BASE_URL']!.trim()
          : 'https://ddalangoo-production.up.railway.app',
      connectTimeout: const Duration(seconds: 5),
      receiveTimeout: const Duration(seconds: 3),
      // 404나 405 상태 코드도 에러로 던지지 않고 로그를 확인하기 위해 설정
      validateStatus: (status) => true,
    ),
  );

  /// 1. 가상 로그인 (Mock Login)
  /// 서버 통신 없이 로컬 저장소에 userId 1을 저장합니다.
  /// 반환된 true를 확인하여 Navigator나 GoRouter로 메인 화면으로 이동시키면 됩니다.
  Future<bool> performMockLogin() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      await LocalStorage.saveDemoUserId();
      await prefs.setString('accessToken', 'mock_token_for_development');

      debugPrint('✅ [Mock Login] userId: 1 저장 완료. 메인 화면으로 진입 가능.');
      return true;
    } catch (e) {
      debugPrint('❌ [Mock Login] 로컬 저장 실패: $e');
      return false;
    }
  }

  /// 2. 쇼핑 요청 보내기 테스트 (POST)
  /// 가상 로그인 후 userId 1을 사용하여 서버에 메시지를 보냅니다.
  Future<Map<String, dynamic>?> sendShoppingRequest() async {
    try {
      // 로컬에 저장된 userId가 있는지 확인, 없으면 기본값 1 사용
      final userId = await LocalStorage.getUserId() ?? 1;

      final res = await _dio.post(
        '/api/agent/shopping-requests',
        data: {
          'userId': userId,
          'message': "저번에 먹었던 딸기 다시 사줘",
          'inputType': "text",
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

  /// 2. OpenAPI 태그별 연결 확인용 코드

  // 상품(Products) 관련 연결 확인
  Future<void> checkProducts() async {
    final res = await _dio.get('/api/products', queryParameters: {'limit': 1});
    debugPrint('[Products API] GET /api/products: Status ${res.statusCode}');
  }

  // 유저(Users) 관련 연결 확인 (userId 1 기준)
  Future<void> checkUser() async {
    final res = await _dio.get('/api/users/1');
    debugPrint('[Users API] GET /api/users/1: Status ${res.statusCode}');
  }

  // 장바구니(Cart) 관련 연결 확인
  Future<void> checkCart() async {
    final res = await _dio.get('/api/users/1/cart');
    debugPrint('[Cart API] GET /api/users/1/cart: Status ${res.statusCode}');
  }

  // 주문(Orders) 관련 연결 확인
  Future<void> checkOrders() async {
    final res = await _dio.get(
      '/api/users/1/orders',
      queryParameters: {'limit': 1},
    );
    debugPrint('[Orders API] GET /api/users/1/orders: Status ${res.statusCode}');
  }

  // 주소록(Addresses) 관련 연결 확인
  Future<void> checkAddresses() async {
    final res = await _dio.get('/api/users/1/addresses');
    debugPrint(
      '[Addresses API] GET /api/users/1/addresses: Status ${res.statusCode}',
    );
  }

  // 구매 이력(Purchase Histories) 관련 연결 확인
  Future<void> checkHistory() async {
    final res = await _dio.get('/api/users/1/purchase-histories');
    debugPrint(
      '[History API] GET /api/users/1/purchase-histories: Status ${res.statusCode}',
    );
  }

  /// 통합 테스트 실행: 앱 시작 시나 설정 화면에서 호출하여 연결 상태를 한눈에 확인 가능
  Future<void> runAllConnectivityTests() async {
    debugPrint('🚀 --- API 연결 테스트 시작 ---');
    await checkProducts();
    await sendShoppingRequest(); // 쇼핑 요청 테스트 추가
    await checkUser();
    await checkCart();
    await checkOrders();
    await checkAddresses();
    await checkHistory();
    debugPrint('🏁 --- API 연결 테스트 종료 ---');
  }
}
