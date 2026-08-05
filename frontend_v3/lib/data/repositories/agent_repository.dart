import 'dart:convert';

import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart';

import '../../core/network/api_client.dart';
import '../../core/utils/latency_logger.dart';
import '../models/agent_model.dart';
import '../models/user_model.dart';

class AgentRepository {
  static const bool useMock = false;
  static const JsonEncoder _jsonEncoder = JsonEncoder.withIndent('  ');

  final Dio _dio = ApiClient.dio;

  void _logRequest(
    String label, {
    required String endpoint,
    required Map<String, dynamic> payload,
    bool redactMessage = false,
  }) {
    final sanitizedPayload = redactMessage
        ? <String, dynamic>{
            ...payload,
            if (payload.containsKey('message')) 'message': '******',
          }
        : payload;
    debugPrint(
      '[$label]\n${_jsonEncoder.convert(<String, dynamic>{'endpoint': endpoint, 'payload': sanitizedPayload})}',
    );
  }

  AgentResponse _parseAgentResponse(dynamic data, {required String label}) {
    final response = AgentResponse.fromJson(
      Map<String, dynamic>.from(data as Map),
    );
    debugPrint(
      '[$label]\n${_jsonEncoder.convert(<String, dynamic>{'conversationId': response.conversationId, 'status': response.status, 'stage': response.stage, 'assistantMessage': response.assistantMessage})}',
    );
    return response;
  }

  AgentResponse _parseAgentResponseWithLatency(
    dynamic data, {
    required String label,
    LatencyRequestContext? latencyContext,
  }) {
    final response = _parseAgentResponse(data, label: label);
    if (latencyContext != null) {
      FrontendLatencyLogger.instance.mark(
        latencyContext,
        'response_text_received',
        responseText: response.assistantMessage,
      );
    }
    return response;
  }

  Future<AgentResponse> startShopping({
    required int userId,
    required String message,
    String inputType = 'text',
    LatencyRequestContext? latencyContext,
  }) async {
    final payload = ShoppingRequest(
      userId: userId,
      message: message,
      inputType: inputType,
    ).toJson();
    _logRequest(
      'Shopping Start Request',
      endpoint: '/api/agent/shopping-requests',
      payload: payload,
    );
    if (latencyContext != null) {
      FrontendLatencyLogger.instance.mark(
        latencyContext,
        'frontend_request_sent',
      );
    }
    final response = await _dio.post(
      '/api/agent/shopping-requests',
      data: payload,
      options: Options(
        headers: <String, String>{...?latencyContext?.toHeaders()},
      ),
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

  Future<AgentResponse> getConversation(int conversationId) async {
    final response = await _dio.get('/api/agent/conversations/$conversationId');
    return AgentResponse.fromJson(
      Map<String, dynamic>.from(response.data as Map),
    );
  }

  Future<void> cancelConversation(int conversationId) async {
    debugPrint(
      '[Conversation Cancel Request]\n${_jsonEncoder.convert(<String, dynamic>{'endpoint': '/api/agent/conversations/$conversationId/cancel'})}',
    );
    await _dio.post('/api/agent/conversations/$conversationId/cancel');
  }

  Future<AgentResponse> sendMessage({
    required int conversationId,
    required String message,
    String inputType = 'text',
    LatencyRequestContext? latencyContext,
    bool redactMessageForLogs = false,
  }) async {
    final payload = MessageRequest(
      message: message,
      inputType: inputType,
    ).toJson();
    _logRequest(
      'Conversation Message Request',
      endpoint: '/api/agent/conversations/$conversationId/messages',
      payload: payload,
      redactMessage: redactMessageForLogs,
    );
    if (latencyContext != null) {
      FrontendLatencyLogger.instance.mark(
        latencyContext,
        'frontend_request_sent',
      );
    }
    final response = await _dio.post(
      '/api/agent/conversations/$conversationId/messages',
      data: payload,
      options: Options(
        headers: <String, String>{...?latencyContext?.toHeaders()},
      ),
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

  Future<AgentResponse> confirmAction({
    required int conversationId,
    required int recommendationItemId,
    required String action,
  }) async {
    final payload = ConfirmRequest(
      recommendationItemId: recommendationItemId,
      action: action,
    ).toJson();
    _logRequest(
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

  Future<AgentResponse> sendWebviewResult({
    required int conversationId,
    int? orderId,
    int? paymentId,
    required String result,
    Map<String, dynamic>? extraData,
  }) async {
    final payload = <String, dynamic>{
      'orderId': orderId,
      'paymentId': paymentId,
      'result': result,
      ...?extraData,
    };
    final response = await _dio.post(
      '/api/agent/conversations/$conversationId/payments/webview-result',
      data: payload,
    );
    return _parseAgentResponse(response.data, label: 'Webview Result Response');
  }

  Future<Map<String, dynamic>> getWebviewStatus(int conversationId) async {
    final response = await _dio.get(
      '/api/agent/conversations/$conversationId/webview/status',
    );
    return Map<String, dynamic>.from(response.data as Map);
  }
}

class UserRepository {
  final Dio _dio = ApiClient.dio;

  String _normalizeName(String name) => name.trim();

  String? _normalizePhoneNumber(String? phoneNumber) {
    if (phoneNumber == null) {
      return null;
    }
    final digitsOnly = phoneNumber.replaceAll(RegExp(r'[^0-9]'), '');
    if (digitsOnly.isEmpty) {
      return null;
    }
    final match = RegExp(
      r'^(01[016789])(\d{3,4})(\d{4})$',
    ).firstMatch(digitsOnly);
    if (match == null) {
      return null;
    }
    return '${match.group(1)}-${match.group(2)}-${match.group(3)}';
  }

  String _extractErrorMessage(Object error, {required String fallback}) {
    if (error is DioException) {
      final data = error.response?.data;
      if (data is Map) {
        final detail = data['detail'];
        if (detail is Map) {
          final message = detail['message'];
          if (message is String && message.trim().isNotEmpty) {
            return message.trim();
          }
          final nestedError = detail['error'];
          if (nestedError is Map) {
            final nestedMessage = nestedError['message'];
            if (nestedMessage is String && nestedMessage.trim().isNotEmpty) {
              return nestedMessage.trim();
            }
          }
        }
        final message = data['message'];
        if (message is String && message.trim().isNotEmpty) {
          return message.trim();
        }
      }
      if (error.message != null && error.message!.trim().isNotEmpty) {
        return error.message!.trim();
      }
    }
    return fallback;
  }

  Future<UserResponse> createUser({
    required String name,
    String? phoneNumber,
    String? ageGroup,
    String? gender,
  }) async {
    final normalizedName = _normalizeName(name);
    final normalizedPhoneNumber = _normalizePhoneNumber(phoneNumber);

    try {
      final response = await _dio.post(
        '/api/users',
        data: UserCreateRequest(
          name: normalizedName,
          phoneNumber: normalizedPhoneNumber,
          ageGroup: ageGroup,
          gender: gender,
        ).toJson(),
      );
      return UserResponse.fromJson(
        Map<String, dynamic>.from(response.data as Map),
      );
    } catch (error) {
      throw Exception(_extractErrorMessage(error, fallback: '회원가입에 실패했습니다.'));
    }
  }

  Future<UserResponse> login({
    required String name,
    required String phoneNumber,
  }) async {
    final normalizedName = _normalizeName(name);
    final normalizedPhoneNumber = _normalizePhoneNumber(phoneNumber) ?? '';

    try {
      final response = await _dio.post(
        '/api/users/login',
        data: <String, dynamic>{
          'name': normalizedName,
          'phone_number': normalizedPhoneNumber,
        },
      );
      return UserResponse.fromJson(
        Map<String, dynamic>.from(response.data as Map),
      );
    } catch (error) {
      throw Exception(_extractErrorMessage(error, fallback: '로그인에 실패했습니다.'));
    }
  }

  Future<UserResponse> getUser(int userId) async {
    final response = await _dio.get('/api/users/$userId');
    return UserResponse.fromJson(
      Map<String, dynamic>.from(response.data as Map),
    );
  }
}
