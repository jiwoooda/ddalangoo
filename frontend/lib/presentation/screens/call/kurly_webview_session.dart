import 'package:flutter/material.dart';
import 'package:webview_flutter/webview_flutter.dart';

class KurlyWebviewSession {
  KurlyWebviewSession()
    : controller = WebViewController()
        ..setJavaScriptMode(JavaScriptMode.unrestricted)
        ..addJavaScriptChannel(
          'KurlyChannel',
          onMessageReceived: (JavaScriptMessage msg) {
            debugPrint('🛒 [KurlyChannel] ${msg.message}');
          },
        );

  final WebViewController controller;

  bool _hasLoadedInitialUrl = false;
  String? _lastRequestedUrl;
  bool _disposed = false;

  String? get lastRequestedUrl => _lastRequestedUrl;
  bool get hasLoadedInitialUrl => _hasLoadedInitialUrl;

  Future<void> attach({
    required NavigationDelegate navigationDelegate,
    required String initialUrl,
  }) async {
    if (_disposed) return;

    controller.setNavigationDelegate(navigationDelegate);

    final normalizedInitialUrl = initialUrl.trim();
    if (!_hasLoadedInitialUrl &&
        normalizedInitialUrl.isNotEmpty &&
        normalizedInitialUrl != 'about:blank') {
      _hasLoadedInitialUrl = true;
      _lastRequestedUrl = normalizedInitialUrl;
      await controller.loadRequest(Uri.parse(normalizedInitialUrl));
    }
  }

  Future<void> loadIfNeeded(String url) async {
    if (_disposed) return;

    final normalizedUrl = url.trim();
    if (normalizedUrl.isEmpty || normalizedUrl == 'about:blank') return;

    _lastRequestedUrl = normalizedUrl;
    try {
      final currentUrl = await controller.currentUrl();
      if (currentUrl == normalizedUrl) {
        return;
      }
    } catch (_) {
      // Ignore and attempt navigation.
    }
    await controller.loadRequest(Uri.parse(normalizedUrl));
  }

  void dispose() {
    _disposed = true;
  }
}
