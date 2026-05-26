//  API 호출 함수

import 'dart:convert';

import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart';
import '../models/agent_model.dart';
import '../models/user_model.dart';
import '../../core/network/api_client.dart';
import '../../core/utils/latency_logger.dart';

class AgentRepository {
  // Mock 데이터 사용 여부 (테스트 시 true로 변경)
  static const bool useMock = false;

  // 데모 시나리오를 위한 상태 트래킹 (백엔드 대용)
  static String _mockContext = 'idle';
  static const JsonEncoder _jsonEncoder = JsonEncoder.withIndent('  ');

  Future<AgentResponse> _mockResponse(
    String message,
    String stage, {
    int? convId,
    String? customAssistantMessage,
    List<RecommendationItemInAgent>? customRecommendations,
  }) async {
    await Future.delayed(const Duration(milliseconds: 800)); // 네트워크 지연 흉내
    final response = AgentResponse(
      conversationId: convId ?? 100,
      status: 'success',
      stage: stage,
      assistantMessage:
          customAssistantMessage ?? '[$stage 단계] 딸랑구입니다. "$message"라고 말씀하셨나요?',
      recommendations:
          customRecommendations ??
          (stage == 'product_selection'
              ? [
                  RecommendationItemInAgent(
                    recommendationItemId: 1,
                    productId: 10,
                    productName: '데모용 맛있는 사과',
                    price: 15000,
                    rank: 1,
                    platform: '네이버쇼핑',
                    imageUrl: 'https://via.placeholder.com/150',
                    brand: '청송사과농장',
                    rating: 4.8,
                    reviewCount: 1250,
                    deliveryInfo: '내일(화) 도착 보장',
                    reason: '지난주에 구매하셨던 상품과 같은 구성이에요.',
                  ),
                ]
              : []),
      order: (stage == 'cart' || stage == 'payment' || stage == 'completed')
          ? {
              'items': [
                {
                  'productName': '데모용 맛있는 사과',
                  'totalPrice': 15000,
                  'quantity': 1,
                  'imageUrl': 'https://via.placeholder.com/150',
                },
              ],
              'totalPaymentAmount': 15000,
            }
          : null,
      deliveryAddress: (stage == 'payment')
          ? {
              'recipientName': '박순자',
              'recipientPhone': '010-3456-7890',
              'address': '서울특별시 용산구 청파로 47길 100, 2층',
              'deliveryRequest': '문 앞에 놔주세요.',
            }
          : null,
    );

    if (useMock) {
      debugPrint(
        '📡 [Mock API Response] Stage: ${response.stage}, Message: ${response.assistantMessage}',
      );
    }
    return response;
  }

  final Dio _dio = ApiClient.dio;

  void _logAgentRequest(
    String label, {
    required String endpoint,
    required Map<String, dynamic> payload,
    bool redactMessage = false,
  }) {
    final sanitizedPayload = redactMessage
        ? {
            ...payload,
            if (payload.containsKey('message')) 'message': '******',
          }
        : payload;
    debugPrint(
      '📤 [$label]\n${_jsonEncoder.convert({'endpoint': endpoint, 'payload': sanitizedPayload})}',
    );
  }

  AgentResponse _parseAgentResponse(dynamic data, {required String label}) {
    final agentResponse = AgentResponse.fromJson(data);
    debugPrint(
      '📥 [$label]\n${_jsonEncoder.convert({'conversationId': agentResponse.conversationId, 'status': agentResponse.status, 'stage': agentResponse.stage, 'assistantMessage': agentResponse.assistantMessage, 'recommendationCount': agentResponse.recommendations.length, 'pendingConfirmation': agentResponse.pendingConfirmation, 'availableOptions': agentResponse.availableOptions, 'uiCommand': agentResponse.uiCommand, 'asyncStatus': agentResponse.asyncStatus, 'error': agentResponse.error})}',
    );

    if (agentResponse.stage == 'idle') {
      debugPrint(
        '🟠 [Idle Response Warning] '
        '백엔드가 stage=idle 을 반환했습니다. '
        '의도 파악 실패 또는 추가 정보 요청일 가능성이 큽니다. '
        'pendingConfirmation=${agentResponse.pendingConfirmation}, '
        'message="${agentResponse.assistantMessage}"',
      );
    }

    return agentResponse;
  }

  AgentResponse _parseAgentResponseWithLatency(
    dynamic data, {
    required String label,
    LatencyRequestContext? latencyContext,
  }) {
    final agentResponse = _parseAgentResponse(data, label: label);
    if (latencyContext != null) {
      FrontendLatencyLogger.instance.mark(
        latencyContext,
        'response_text_received',
        responseText: agentResponse.assistantMessage,
      );
    }
    return agentResponse;
  }

  // 쇼핑 시작 (전화 걸기 버튼)
  Future<AgentResponse> startShopping({
    required int userId,
    required String message,
    LatencyRequestContext? latencyContext,
  }) async {
    if (useMock) {
      if (message == 'INIT_CALL') {
        _mockContext = 'started';
        return _mockResponse(
          message,
          'clarification',
          customAssistantMessage: '안녕하세요! 무엇을 도와드릴까요?',
        );
      }
      return _mockResponse(message, 'clarification');
    }

    final payload = ShoppingRequest(userId: userId, message: message).toJson();
    _logAgentRequest(
      'Shopping Start Request',
      endpoint: '/api/agent/shopping-requests',
      payload: payload,
    );
    if (latencyContext != null) {
      FrontendLatencyLogger.instance.mark(latencyContext, 'frontend_request_sent');
    }
    final response = await _dio.post(
      '/api/agent/shopping-requests',
      data: payload,
      options: Options(headers: {...?latencyContext?.toHeaders()}),
    );
    if (latencyContext != null) {
      FrontendLatencyLogger.instance.mark(
        latencyContext,
        'frontend_response_received',
      );
    }
    return _parseAgentResponseWithLatency(
      response.data,
      label: 'Shopping Start Response',
      latencyContext: latencyContext,
    );
  }

  // 대화 상태 가져오기 (폴링용)
  Future<AgentResponse> getConversation(int conversationId) async {
    final response = await _dio.get('/api/agent/conversations/$conversationId');
    return AgentResponse.fromJson(response.data);
  }

  Future<Map<String, dynamic>?> getWebviewStatus(int conversationId) async {
    final response = await _dio.get(
      '/api/agent/conversations/$conversationId/webview/status',
    );
    final data = response.data;
    if (data is! Map<String, dynamic>) return null;
    return data;
  }

  Future<void> cancelConversation(int conversationId) async {
    debugPrint(
      '📤 [Conversation Cancel Request]\n${_jsonEncoder.convert({'endpoint': '/api/agent/conversations/$conversationId/cancel'})}',
    );
    await _dio.post('/api/agent/conversations/$conversationId/cancel');
    debugPrint(
      '📥 [Conversation Cancel Response]\n${_jsonEncoder.convert({'conversationId': conversationId, 'status': 'requested'})}',
    );
  }

  // 메시지 보내기 (STT 결과 전송)
  Future<AgentResponse> sendMessage({
    required int conversationId,
    required String message,
    LatencyRequestContext? latencyContext,
    bool redactMessageForLogs = false,
  }) async {
    if (useMock) {
      debugPrint(
        '📩 [Mock API Request] Message: "$message", Context: "$_mockContext"',
      );

      // 1단계: 딸기 구매 요청
      if (message.contains('딸기')) {
        _mockContext = 'strawberry_history';
        return _mockResponse(
          message,
          'clarification',
          customAssistantMessage:
              '저번에 네이버에서 킹스베리 왕딸기를 구매한 이력이 있어요. 다시 구매해드릴까요? 500g에 가격은 28,900원입니다.',
        );
      }

      // 2단계: 비싸다 불평
      if (message.contains('비싸다')) {
        _mockContext = 'too_expensive';
        return _mockResponse(
          message,
          'clarification',
          customAssistantMessage: '알겠습니다. 그렇다면 네이버에서 좀 더 저렴한 다른 상품을 찾아볼까요?',
        );
      }

      // 3단계: 저렴한 상품 검색 동의
      if (message == '응' && _mockContext == 'too_expensive') {
        _mockContext = 'product_searching';
        return _mockResponse(
          message,
          'product_selection',
          customAssistantMessage:
              '"상콤달콤 산직송 딸기"가 500g에 9,900원입니다. 이 상품을 구매할까요?',
          customRecommendations: [
            RecommendationItemInAgent(
              recommendationItemId: 2,
              productId: 20,
              productName: '상콤달콤 산직송 딸기',
              price: 9900,
              rank: 1,
              platform: '네이버쇼핑',
              imageUrl: 'https://via.placeholder.com/150',
            ),
          ],
        );
      }

      // 4단계: 최종 구매 결정 -> 배송지 확인
      if (message.contains('구매해줘') || message.contains('응')) {
        _mockContext = 'confirm_address';
        return _mockResponse(
          message,
          'payment',
          customAssistantMessage:
              '구매를 진행하겠습니다. 네이버스토어에 등록된 배송지인 청파로 47길로 배송해드릴까요?',
        );
      }

      // 5단계: 배송지 확인 완료 -> 비밀번호 입력 요청
      if (message == '응' && _mockContext == 'confirm_address') {
        _mockContext = 'input_password';
        return _mockResponse(
          message,
          'payment',
          customAssistantMessage: '네 알겠습니다. 이제 네이버페이 결제 비밀번호 6자리를 눌러주세요',
        );
      }

      // 6단계: 비밀번호 입력 완료 -> 결제 완료
      if (RegExp(r'^\*+$').hasMatch(message) ||
          (message.length == 6 && int.tryParse(message) != null)) {
        _mockContext = 'done';
        return _mockResponse(
          message,
          'completed',
          customAssistantMessage: '결제가 완료되었습니다!',
        );
      }

      return _mockResponse(message, 'clarification', convId: conversationId);
    }

    final payload = MessageRequest(message: message).toJson();
    _logAgentRequest(
      'Conversation Message Request',
      endpoint: '/api/agent/conversations/$conversationId/messages',
      payload: payload,
      redactMessage: redactMessageForLogs,
    );
    if (latencyContext != null) {
      FrontendLatencyLogger.instance.mark(latencyContext, 'frontend_request_sent');
    }
    final response = await _dio.post(
      '/api/agent/conversations/$conversationId/messages',
      data: payload,
      options: Options(headers: {...?latencyContext?.toHeaders()}),
    );
    if (latencyContext != null) {
      FrontendLatencyLogger.instance.mark(
        latencyContext,
        'frontend_response_received',
      );
    }
    return _parseAgentResponseWithLatency(
      response.data,
      label: 'Conversation Message Response',
      latencyContext: latencyContext,
    );
  }

  // 확인/거부 (플랫폼 선택, 상품 선택)
  Future<AgentResponse> confirmAction({
    required int conversationId,
    required int recommendationItemId,
    required String action, // "accept" or "reject"
  }) async {
    if (useMock) {
      debugPrint(
        '📩 [Mock API Confirm] Action: $action, RecommendationItem: $recommendationItemId',
      );
      if (action == 'accept') {
        return _mockResponse('상품을 선택했습니다', 'cart', convId: conversationId);
      } else {
        return _mockResponse(
          '다른 상품을 찾아볼게요',
          'clarification',
          convId: conversationId,
        );
      }
    }

    final payload = ConfirmRequest(
      recommendationItemId: recommendationItemId,
      action: action,
    ).toJson();
    _logAgentRequest(
      'Confirm Request',
      endpoint: '/api/agent/conversations/$conversationId/confirm',
      payload: payload,
    );
    final response = await _dio.post(
      '/api/agent/conversations/$conversationId/confirm',
      data: payload,
    );
    return _parseAgentResponse(response.data, label: 'Confirm Response');
  }

  // 결제 웹뷰 결과 전송
  Future<AgentResponse> sendWebviewResult({
    required int conversationId,
    required int orderId,
    required int paymentId,
    required String result, // "completed" or "cancelled"
  }) async {
    if (useMock) {
      await Future.delayed(const Duration(milliseconds: 500));
      return _mockResponse(
        result,
        result == 'completed' ? 'completed' : 'payment',
        convId: conversationId,
        customAssistantMessage: result == 'completed'
            ? '결제가 완료되었습니다.'
            : '결제가 취소되었습니다.',
      );
    }
    final response = await _dio.post(
      '/api/agent/conversations/$conversationId/payments/webview-result',
      data: {'orderId': orderId, 'paymentId': paymentId, 'result': result},
    );
    return _parseAgentResponse(response.data, label: 'Webview Result Response');
  }
}

class UserRepository {
  final Dio _dio = ApiClient.dio;

  // Mock 유저 데이터 (LoginScreen과 동일하게 유지)
  static const Map<int, Map<String, dynamic>> _mockUsersById = {
    1: {'name': '김영희', 'phoneNumber': '010-1234-5678'},
    2: {'name': '이철수', 'phoneNumber': '010-2345-6789'},
    3: {'name': '박순자', 'phoneNumber': '010-3456-7890'},
  };

  // 회원가입
  Future<UserResponse> createUser({
    required String name,
    String? phoneNumber,
    String? ageGroup,
  }) async {
    if (AgentRepository.useMock) {
      await Future.delayed(const Duration(milliseconds: 800));
      // Mock 회원가입 시 새로운 userId를 부여하거나, 임의의 userId를 반환
      // 여기서는 임시로 99를 사용하지만, 실제로는 _mockUsersById의 다음 ID를 사용하는 것이 좋습니다.
      // 또는, RegisterScreen에서 생성된 유저를 _mockUsersById에 추가하는 로직이 필요합니다.
      return UserResponse(
        userId: _mockUsersById.length + 1, // 새로운 Mock User ID 부여
        name: name,
        phoneNumber: phoneNumber ?? '010-0000-0000',
      );
    }

    final response = await _dio.post(
      '/api/users',
      data: UserCreateRequest(
        name: name,
        phoneNumber: phoneNumber,
        ageGroup: ageGroup,
      ).toJson(),
    );
    return UserResponse.fromJson(response.data);
  }

  // 로그인 (전화번호/이름 기반)
  Future<UserResponse> login({
    required String name,
    required String phoneNumber,
  }) async {
    final response = await _dio.post(
      '/api/users/login',
      data: {'name': name, 'phone_number': phoneNumber},
    );
    return UserResponse.fromJson(response.data);
  }

  // 유저 정보 가져오기
  Future<UserResponse> getUser(int userId) async {
    if (AgentRepository.useMock) {
      final userData = _mockUsersById[userId];
      if (userData != null) {
        return UserResponse(
          userId: userId,
          name: userData['name']!,
          phoneNumber: userData['phoneNumber']!,
        );
      }
      // Mock 데이터에 없는 userId일 경우 기본값 반환
      return UserResponse(
        userId: userId,
        name: '알 수 없는 사용자',
        phoneNumber: '000-0000-0000',
      );
    }

    final response = await _dio.get('/api/users/$userId');
    return UserResponse.fromJson(response.data);
  }
}
