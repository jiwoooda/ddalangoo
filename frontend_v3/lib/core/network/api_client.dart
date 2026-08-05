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
        connectTimeout: const Duration(seconds: 120),
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
