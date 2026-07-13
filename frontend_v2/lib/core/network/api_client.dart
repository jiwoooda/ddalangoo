// 네트워크 설정

import 'dart:convert';
import 'dart:io';

import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter_dotenv/flutter_dotenv.dart';

import '../services/voice_timeline_log_service.dart';

class ApiClient {
  // Docker/Railway 빌드에서는 --dart-define 값이 우선이고,
  // 로컬 개발에서는 .env 값을 사용한다.
  static const String _definedBaseUrl = String.fromEnvironment('API_BASE_URL');

  static String get baseUrl {
    final resolved = _resolveConfiguredBaseUrl();
    if (resolved.isEmpty) {
      return resolved;
    }
    return _normalizeBaseUrlForRuntime(resolved);
  }

  static String _resolveConfiguredBaseUrl() {
    if (_definedBaseUrl.trim().isNotEmpty) {
      return _definedBaseUrl.trim();
    }
    try {
      if (dotenv.env['API_BASE_URL']?.trim().isNotEmpty == true) {
        return dotenv.env['API_BASE_URL']!.trim();
      }
    } catch (_) {
      // Widget test 등에서 dotenv가 아직 초기화되지 않은 경우 빈 baseUrl로 안전하게 진행한다.
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
          _logNetwork('REQUEST', {
            'method': options.method,
            'url': options.uri.toString(),
            'headers': options.headers,
            'queryParameters': options.queryParameters,
            'body': options.data,
          });
          handler.next(options);
        },
        onResponse: (response, handler) {
          _logNetwork('RESPONSE', {
            'statusCode': response.statusCode,
            'url': response.requestOptions.uri.toString(),
            'data': response.data,
          });
          handler.next(response);
        },
        onError: (error, handler) {
          _logNetwork('ERROR', {
            'url': error.requestOptions.uri.toString(),
            'message': error.message,
            'type': error.type.name,
            'error': error.error?.toString(),
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
  static String? _lastSuppressedWebviewStatusLogKey;

  static void _logNetwork(String phase, Map<String, dynamic> payload) {
    final summarized = _summarizeNetworkLog(phase, payload);
    if (summarized == null) return;
    const encoder = JsonEncoder.withIndent('  ');
    debugPrint('🌐 [API $phase]\n${encoder.convert(_jsonSafe(summarized))}');
    _persistVoiceTimelineNetworkEvent(phase, summarized);
  }

  static Map<String, dynamic>? _summarizeNetworkLog(
    String phase,
    Map<String, dynamic> payload,
  ) {
    final url = payload['url']?.toString() ?? '';
    if (url.contains('/static/tts/')) {
      return _summarizeStaticAudioLog(phase, payload, url);
    }
    if (url.contains('/voice/tts')) {
      return _summarizeTtsLog(phase, payload, url);
    }
    if (url.contains('/voice/stt')) {
      return _summarizeSttLog(phase, payload, url);
    }

    if (!url.contains('/webview/status')) {
      return payload;
    }

    if (phase == 'REQUEST') {
      return {'method': payload['method'], 'url': url};
    }

    if (phase == 'RESPONSE') {
      final data = payload['data'];
      final status = data is Map<String, dynamic>
          ? data['status']?.toString()
          : null;
      final step = data is Map<String, dynamic>
          ? data['step']?.toString()
          : null;
      final message = data is Map<String, dynamic>
          ? data['message']?.toString()
          : null;
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
      return {'statusCode': payload['statusCode'], 'url': url, 'data': data};
    }

    if (phase == 'ERROR') {
      _lastSuppressedWebviewStatusLogKey = null;
    }

    return payload;
  }

  static Map<String, dynamic>? _summarizeStaticAudioLog(
    String phase,
    Map<String, dynamic> payload,
    String url,
  ) {
    if (phase == 'REQUEST') {
      return {'method': payload['method'], 'url': url};
    }

    if (phase == 'RESPONSE') {
      final data = payload['data'];
      final byteLength = data is List ? data.length : null;
      return {
        'statusCode': payload['statusCode'],
        'url': url,
        'data': {'byteLength': byteLength},
      };
    }

    if (phase == 'ERROR') {
      final data = payload['data'];
      return {
        'url': url,
        'message': payload['message'],
        'type': payload['type'],
        'statusCode': payload['statusCode'],
        'dataPreview': data is List
            ? utf8.decode(data.whereType<int>().toList(), allowMalformed: true)
            : data,
      };
    }

    return payload;
  }

  static Map<String, dynamic>? _summarizeTtsLog(
    String phase,
    Map<String, dynamic> payload,
    String url,
  ) {
    if (phase == 'REQUEST') {
      final body = payload['body'];
      final text = body is Map ? body['text'] : null;
      return {
        'method': payload['method'],
        'url': url,
        'body': {'textLength': text is String ? text.runes.length : null},
      };
    }

    if (phase == 'RESPONSE') {
      final data = payload['data'];
      final audioBase64 = data is Map ? data['audioBase64'] : null;
      return {
        'statusCode': payload['statusCode'],
        'url': url,
        'data': {
          'mimeType': data is Map ? data['mimeType'] : null,
          'audioBase64Length': audioBase64 is String
              ? audioBase64.length
              : null,
          'voiceTimeline': data is Map ? data['voiceTimeline'] : null,
        },
      };
    }

    return payload;
  }

  static Map<String, dynamic>? _summarizeSttLog(
    String phase,
    Map<String, dynamic> payload,
    String url,
  ) {
    if (phase == 'REQUEST') {
      return {'method': payload['method'], 'url': url};
    }

    if (phase == 'RESPONSE') {
      final data = payload['data'];
      final transcript = data is Map ? data['transcript'] : null;
      return {
        'statusCode': payload['statusCode'],
        'url': url,
        'data': {
          'transcriptLength': transcript is String
              ? transcript.runes.length
              : null,
        },
      };
    }

    return payload;
  }

  static void _persistVoiceTimelineNetworkEvent(
    String phase,
    Map<String, dynamic> payload,
  ) {
    final url = payload['url']?.toString() ?? '';
    final event = _voiceTimelineNetworkEventName(phase, url);
    if (event == null) {
      return;
    }
    VoiceTimelineLogService.instance.logBestEffort(
      event,
      payload: Map<String, dynamic>.from(_jsonSafe(payload) as Map),
    );
  }

  static String? _voiceTimelineNetworkEventName(String phase, String url) {
    if (url.contains('/static/tts/')) {
      switch (phase) {
        case 'REQUEST':
          return 'frontend_static_tts_request_sent';
        case 'RESPONSE':
          return 'frontend_static_tts_response_received';
        case 'ERROR':
          return 'frontend_static_tts_response_error';
      }
    }

    if (url.contains('/voice/tts')) {
      switch (phase) {
        case 'REQUEST':
          return 'frontend_tts_request_sent';
        case 'RESPONSE':
          return 'frontend_tts_response_received';
        case 'ERROR':
          return 'frontend_tts_response_error';
      }
    }

    if (url.contains('/voice/stt')) {
      switch (phase) {
        case 'REQUEST':
          return 'frontend_stt_request_sent';
        case 'RESPONSE':
          return 'frontend_stt_response_received';
        case 'ERROR':
          return 'frontend_stt_response_error';
      }
    }

    return null;
  }

  static Object? _jsonSafe(Object? value) {
    if (value == null || value is num || value is bool || value is String) {
      return value;
    }

    if (value is FormData) {
      return {
        'type': 'FormData',
        'fields': [
          for (final field in value.fields)
            {'name': field.key, 'value': field.value},
        ],
        'files': [
          for (final fileEntry in value.files)
            {
              'fieldName': fileEntry.key,
              'filename': fileEntry.value.filename,
              'contentType': fileEntry.value.contentType.toString(),
              'length': fileEntry.value.length,
            },
        ],
      };
    }

    if (value is MultipartFile) {
      return {
        'type': 'MultipartFile',
        'filename': value.filename,
        'contentType': value.contentType.toString(),
        'length': value.length,
      };
    }

    if (value is Map) {
      return {
        for (final entry in value.entries)
          entry.key.toString(): _jsonSafe(entry.value),
      };
    }

    if (value is Iterable) {
      return [for (final item in value) _jsonSafe(item)];
    }

    return value.toString();
  }
}
