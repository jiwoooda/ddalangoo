import 'latency_log_writer_stub.dart'
    if (dart.library.io) 'latency_log_writer_io.dart'
    as impl;

Future<void> appendLatencyJsonLine(String fileName, String jsonLine) {
  return impl.appendLatencyJsonLine(fileName, jsonLine);
}
