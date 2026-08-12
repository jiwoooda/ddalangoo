import 'dart:convert';
import 'dart:io';

import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter_dotenv/flutter_dotenv.dart';

abstract final class ApiClient {
  static const String _definedBaseUrl = String.fromEnvironment('API_BASE_URL');

  static String get baseUrl {
    final resolved = _resolveConfiguredBaseUrl();
    if (resolved.isEmpty) {
      return resolved;
    }
    return _normalizeBaseUrlForRuntime(resolved);
  }

  static Dio createDio() {
    final dio = Dio(
      BaseOptions(
        baseUrl: baseUrl,
        // connectTimeout은 "TCP 연결 자체가 되는지"만 보는 시간이라 서버가 응답을
        // 만드는 시간(LLM 추론 등)과는 무관하다. 원래 120초로 잡혀 있어서 백엔드가
        // 아예 안 떠 있을 때도 2분을 기다린 뒤에야 실패로 판정됐다(그동안 TTS는
        // flutter_tts 폴백으로 못 넘어가고, 사용자 턴도 그만큼 늦게 옴). 로컬
        // 네트워크에서 연결 자체는 정상이면 수백ms 안에 되므로 8초면 충분히
        // 여유 있다.
        connectTimeout: const Duration(seconds: 8),
        // receiveTimeout은 연결된 뒤 응답(에이전트 답변 등)을 기다리는 시간이라
        // LLM 추론 시간을 감안해 넉넉하게 유지한다.
        receiveTimeout: const Duration(seconds: 120),
        headers: const {'Content-Type': 'application/json'},
      ),
    );

    dio.interceptors.add(
      InterceptorsWrapper(
        onRequest: (options, handler) {
          _logNetwork('REQUEST', <String, dynamic>{
            'method': options.method,
            'url': options.uri.toString(),
            'headers': options.headers,
            'queryParameters': options.queryParameters,
            'body': options.data,
          });
          handler.next(options);
        },
        onResponse: (response, handler) {
          _logNetwork('RESPONSE', <String, dynamic>{
            'statusCode': response.statusCode,
            'url': response.requestOptions.uri.toString(),
            'data': response.data,
          });
          handler.next(response);
        },
        onError: (error, handler) {
          _logNetwork('ERROR', <String, dynamic>{
            'url': error.requestOptions.uri.toString(),
            'message': error.message,
            'type': error.type.name,
            'statusCode': error.response?.statusCode,
            'data': error.response?.data,
          });
          handler.next(error);
        },
      ),
    );

    return dio;
  }

  static final Dio dio = createDio();

  static String _resolveConfiguredBaseUrl() {
    if (_definedBaseUrl.trim().isNotEmpty) {
      return _definedBaseUrl.trim();
    }

    try {
      final envBaseUrl = dotenv.env['API_BASE_URL']?.trim();
      if (envBaseUrl != null && envBaseUrl.isNotEmpty) {
        return envBaseUrl;
      }
    } catch (_) {
      // Dotenv is optional during tests and early startup.
    }

    return '';
  }

  static String _normalizeBaseUrlForRuntime(String rawUrl) {
    if (kIsWeb || !Platform.isAndroid) {
      return rawUrl;
    }

    final uri = Uri.tryParse(rawUrl);
    if (uri == null) {
      return rawUrl;
    }

    final host = uri.host.trim();
    if (host != '127.0.0.1' && host != 'localhost') {
      return rawUrl;
    }

    return uri.replace(host: '10.0.2.2').toString();
  }

  static void _logNetwork(String phase, Map<String, dynamic> payload) {
    const encoder = JsonEncoder.withIndent('  ');
    debugPrint('[API $phase]\n${encoder.convert(_jsonSafe(payload))}');
  }

  static Object? _jsonSafe(Object? value) {
    if (value == null || value is num || value is bool || value is String) {
      return value;
    }

    if (value is Map) {
      return value.map(
        (key, nestedValue) => MapEntry(key.toString(), _jsonSafe(nestedValue)),
      );
    }

    if (value is Iterable) {
      return value.map(_jsonSafe).toList(growable: false);
    }

    return value.toString();
  }
}
