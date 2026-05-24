import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:webview_flutter/webview_flutter.dart';

import '../../providers/call_provider.dart';

class PaymentWebViewScreen extends StatefulWidget {
  const PaymentWebViewScreen({
    super.key,
    required this.url,
    required this.orderId,
    required this.paymentId,
  });

  final String url;
  final int orderId;
  final int paymentId;

  @override
  State<PaymentWebViewScreen> createState() => _PaymentWebViewScreenState();
}

class _PaymentWebViewScreenState extends State<PaymentWebViewScreen> {
  late final WebViewController _controller;
  bool _isSubmitting = false;
  bool _pageLoaded = false;
  int _loadingProgress = 0;

  @override
  void initState() {
    super.initState();
    _controller = WebViewController()
      ..setJavaScriptMode(JavaScriptMode.unrestricted)
      ..setNavigationDelegate(
        NavigationDelegate(
          onProgress: (progress) {
            if (!mounted) return;
            setState(() {
              _loadingProgress = progress;
            });
          },
          onPageFinished: (_) {
            if (!mounted) return;
            setState(() {
              _pageLoaded = true;
              _loadingProgress = 100;
            });
          },
        ),
      )
      ..loadRequest(Uri.parse(widget.url));
  }

  Future<void> _submitResult(String result) async {
    if (_isSubmitting) return;
    setState(() {
      _isSubmitting = true;
    });

    try {
      await context.read<CallProvider>().handlePaymentResult(
        orderId: widget.orderId,
        paymentId: widget.paymentId,
        result: result,
      );
      if (mounted) {
        Navigator.of(context).pop();
      }
    } finally {
      if (mounted) {
        setState(() {
          _isSubmitting = false;
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Consumer<CallProvider>(
          builder: (context, provider, _) =>
              Text(provider.webviewTargetLabel),
        ),
        actions: [
          TextButton(
            onPressed: _isSubmitting ? null : () => _submitResult('fail'),
            child: const Text('닫기'),
          ),
        ],
      ),
      body: Column(
        children: [
          Consumer<CallProvider>(
            builder: (context, provider, _) {
              final statusText = provider.webviewStatusText;
              final helperText = _isSubmitting
                  ? '백엔드에 완료 여부를 전달하는 중이에요.'
                  : _pageLoaded
                  ? '화면이 열렸어요. 진행 상황을 확인해주세요.'
                  : '웹 화면을 불러오는 중이에요. 잠시만 기다려주세요.';

              return Container(
                width: double.infinity,
                margin: const EdgeInsets.fromLTRB(16, 12, 16, 8),
                padding: const EdgeInsets.all(16),
                decoration: BoxDecoration(
                  color: const Color(0xFFFFF6F8),
                  borderRadius: BorderRadius.circular(20),
                  border: Border.all(color: const Color(0xFFF1C8D4)),
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      provider.webviewTargetLabel,
                      style: const TextStyle(
                        fontSize: 14,
                        fontWeight: FontWeight.w700,
                        color: Color(0xFFE8325A),
                      ),
                    ),
                    const SizedBox(height: 8),
                    Text(
                      statusText,
                      style: const TextStyle(
                        fontSize: 19,
                        fontWeight: FontWeight.w700,
                        color: Color(0xFF333333),
                      ),
                    ),
                    const SizedBox(height: 8),
                    Text(
                      helperText,
                      style: const TextStyle(
                        fontSize: 14,
                        color: Color(0xFF666666),
                        height: 1.4,
                      ),
                    ),
                    const SizedBox(height: 12),
                    ClipRRect(
                      borderRadius: BorderRadius.circular(999),
                      child: LinearProgressIndicator(
                        minHeight: 8,
                        value: _pageLoaded
                            ? 1
                            : (_loadingProgress <= 0
                                  ? null
                                  : _loadingProgress / 100),
                        backgroundColor: const Color(0xFFF8DCE5),
                        valueColor: const AlwaysStoppedAnimation<Color>(
                          Color(0xFFE8325A),
                        ),
                      ),
                    ),
                  ],
                ),
              );
            },
          ),
          Expanded(
            child: Stack(
              children: [
                WebViewWidget(controller: _controller),
                if (!_pageLoaded)
                  const Center(child: CircularProgressIndicator()),
              ],
            ),
          ),
          SafeArea(
            top: false,
            child: Padding(
              padding: const EdgeInsets.fromLTRB(16, 12, 16, 16),
              child: Row(
                children: [
                  Expanded(
                    child: OutlinedButton(
                      onPressed: _isSubmitting ? null : () => _submitResult('fail'),
                      child: const Text('취소'),
                    ),
                  ),
                  const SizedBox(width: 12),
                  Expanded(
                    child: FilledButton(
                      onPressed: _isSubmitting
                          ? null
                          : () => _submitResult('success'),
                      child: Text(_isSubmitting ? '처리 중...' : '완료했어요'),
                    ),
                  ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
}
