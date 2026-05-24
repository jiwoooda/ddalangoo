// 네트워크 설정

import 'dart:convert';

import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter_dotenv/flutter_dotenv.dart';

class ApiClient {
  static String get baseUrl =>
      dotenv.env['API_BASE_URL']?.trim().isNotEmpty == true
      ? dotenv.env['API_BASE_URL']!.trim()
      : 'https://ddalangoo-production.up.railway.app';

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

  static void _logNetwork(String phase, Map<String, dynamic> payload) {
    const encoder = JsonEncoder.withIndent('  ');
    debugPrint('🌐 [API $phase]\n${encoder.convert(payload)}');
  }
}
