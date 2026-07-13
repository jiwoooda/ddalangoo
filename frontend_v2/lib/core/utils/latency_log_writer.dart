import 'latency_log_writer_stub.dart'
    if (dart.library.io) 'latency_log_writer_io.dart'
    if (dart.library.js_interop) 'latency_log_writer_web.dart'
    as impl;

Future<void> appendLatencyJsonLine(String fileName, String jsonLine) {
  return impl.appendLatencyJsonLine(fileName, jsonLine);
}
