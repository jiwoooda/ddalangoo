// 네트워크 설정

import 'dart:convert';

import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter_dotenv/flutter_dotenv.dart';

class ApiClient {
  // Docker/Railway 빌드에서는 --dart-define 값이 우선이고,
  // 로컬 개발에서는 .env 값을 사용한다.
  static const String _definedBaseUrl = String.fromEnvironment('API_BASE_URL');

  static String get baseUrl {
    if (_definedBaseUrl.trim().isNotEmpty) {
      return _definedBaseUrl.trim();
    }
    if (dotenv.env['API_BASE_URL']?.trim().isNotEmpty == true) {
      return dotenv.env['API_BASE_URL']!.trim();
    }
    return 'https://ddalangoo-production.up.railway.app';
  }

  static Dio createDio() {
    final dio = Dio(
      BaseOptions(
        baseUrl: baseUrl,
        connectTimeout: const Duration(seconds: 120),
        receiveTimeout: const Duration(seconds: 120),
        headers: {'Content-Type': 'application/json'},
      ),
    );

    dio.interceptors.add(
      InterceptorsWrapper(
        onRequest: (options, handler) {
          _logNetwork(
            'REQUEST',
            {
              'method': options.method,
              'url': options.uri.toString(),
              'headers': options.headers,
              'queryParameters': options.queryParameters,
              'body': options.data,
            },
          );
          handler.next(options);
        },
        onResponse: (response, handler) {
          _logNetwork(
            'RESPONSE',
            {
              'statusCode': response.statusCode,
              'url': response.requestOptions.uri.toString(),
              'data': response.data,
            },
          );
          handler.next(response);
        },
        onError: (error, handler) {
          _logNetwork(
            'ERROR',
            {
              'url': error.requestOptions.uri.toString(),
              'message': error.message,
              'statusCode': error.response?.statusCode,
              'data': error.response?.data,
            },
          );
          handler.next(error);
        },
      ),
    );

    return dio;
  }

  static final Dio dio = createDio();
  static String? _lastSuppressedWebviewStatusLogKey;

  static void _logNetwork(String phase, Map<String, dynamic> payload) {
    final summarized = _summarizeNetworkLog(phase, payload);
    if (summarized == null) return;
    const encoder = JsonEncoder.withIndent('  ');
    debugPrint('🌐 [API $phase]\n${encoder.convert(summarized)}');
  }

  static Map<String, dynamic>? _summarizeNetworkLog(
    String phase,
    Map<String, dynamic> payload,
  ) {
    final url = payload['url']?.toString() ?? '';
    if (!url.contains('/webview/status')) {
      return payload;
    }

    if (phase == 'REQUEST') {
      return {
        'method': payload['method'],
        'url': url,
      };
    }

    if (phase == 'RESPONSE') {
      final data = payload['data'];
      final status = data is Map<String, dynamic> ? data['status']?.toString() : null;
      final step = data is Map<String, dynamic> ? data['step']?.toString() : null;
      final message = data is Map<String, dynamic> ? data['message']?.toString() : null;
      final signature = '$url|$status|$step|$message';

      if (status == 'idle') {
        if (_lastSuppressedWebviewStatusLogKey == signature) {
          return null;
        }
        _lastSuppressedWebviewStatusLogKey = signature;
        return {
          'statusCode': payload['statusCode'],
          'url': url,
          'data': {
            'type': data is Map<String, dynamic> ? data['type'] : null,
            'conversationId': data is Map<String, dynamic>
                ? data['conversationId']
                : null,
            'status': status,
          },
        };
      }

      _lastSuppressedWebviewStatusLogKey = null;
      return {
        'statusCode': payload['statusCode'],
        'url': url,
        'data': data,
      };
    }

    if (phase == 'ERROR') {
      _lastSuppressedWebviewStatusLogKey = null;
    }

    return payload;
  }
}
