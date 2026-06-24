import 'dart:io';

const String _latencyLogDirectory =
    '/Users/synuo/Documents/GitHub/AYearApart/stt_tts_latency_test';

Future<void> appendLatencyJsonLine(String fileName, String jsonLine) async {
  try {
    final directory = Directory(_latencyLogDirectory);
    if (!await directory.exists()) {
      await directory.create(recursive: true);
    }

    final file = File('${directory.path}/$fileName');
    await file.writeAsString('$jsonLine\n', mode: FileMode.append, flush: true);
  } catch (_) {
    // Keep latency logging best-effort so the voice flow is never blocked.
  }
}
