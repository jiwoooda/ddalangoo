import 'package:dio/dio.dart';
import 'package:flutter_dotenv/flutter_dotenv.dart';

const String _ingestPath = '/api/dev/voice-timeline/ingest';

Future<void> appendLatencyJsonLine(String fileName, String jsonLine) async {
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

  return baseUri.resolve(_ingestPath);
}
