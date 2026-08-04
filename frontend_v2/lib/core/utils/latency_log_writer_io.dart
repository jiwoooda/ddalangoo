import 'dart:io';

import 'package:dio/dio.dart';
import 'package:flutter_dotenv/flutter_dotenv.dart';

const String _latencyLogDirectory =
    '/Users/synuo/Documents/GitHub/AYearApart/stt_tts_latency_test';
const String _ingestPath = '/api/dev/voice-timeline/ingest';

Future<void> appendLatencyJsonLine(String fileName, String jsonLine) async {
  final wroteLocally = await _appendLocally(fileName, jsonLine);
  if (wroteLocally) {
    return;
  }

  await _uploadRemotely(fileName, jsonLine);
}

Future<bool> _appendLocally(String fileName, String jsonLine) async {
  try {
    final directory = Directory(_latencyLogDirectory);
    if (!await directory.exists()) {
      await directory.create(recursive: true);
    }

    final file = File('${directory.path}/$fileName');
    await file.writeAsString('$jsonLine\n', mode: FileMode.append, flush: true);
    return true;
  } catch (_) {
    return false;
  }
}

Future<void> _uploadRemotely(String fileName, String jsonLine) async {
  final uploadUrl = _resolveUploadUrl();
  if (uploadUrl == null) {
    return;
  }

  try {
    await Dio(
      BaseOptions(
        connectTimeout: const Duration(seconds: 3),
        receiveTimeout: const Duration(seconds: 3),
        headers: {'Content-Type': 'application/json'},
      ),
    ).postUri(uploadUrl, data: {'fileName': fileName, 'jsonLine': jsonLine});
  } catch (_) {
    // Keep latency logging best-effort so the voice flow is never blocked.
  }
}

Uri? _resolveUploadUrl() {
  const definedBaseUrl = String.fromEnvironment('API_BASE_URL');
  String? envBaseUrl;
  try {
    envBaseUrl = dotenv.env['API_BASE_URL']?.trim();
  } catch (_) {
    envBaseUrl = null;
  }
  final rawBaseUrl = definedBaseUrl.trim().isNotEmpty
      ? definedBaseUrl.trim()
      : envBaseUrl;
  if (rawBaseUrl == null || rawBaseUrl.isEmpty) {
    return null;
  }

  final baseUri = Uri.tryParse(rawBaseUrl);
  if (baseUri == null) {
    return null;
  }

  if (!Platform.isAndroid) {
    return baseUri.resolve(_ingestPath);
  }

  final host = baseUri.host.trim();
  if (host != '127.0.0.1' && host != 'localhost') {
    return baseUri.resolve(_ingestPath);
  }

  return baseUri.replace(host: '10.0.2.2').resolve(_ingestPath);
}
