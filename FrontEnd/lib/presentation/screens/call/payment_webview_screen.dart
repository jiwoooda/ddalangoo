import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:webview_flutter/webview_flutter.dart';

import '../../providers/call_provider.dart';

class PaymentWebViewScreen extends StatefulWidget {
  const PaymentWebViewScreen({
    super.key,
    required this.url,
    this.streamUrl,
    this.orderId,
    this.paymentId,
  });

  final String url;
  final String? streamUrl;
  final int? orderId;
  final int? paymentId;

  @override
  State<PaymentWebViewScreen> createState() => _PaymentWebViewScreenState();
}

class _PaymentWebViewScreenState extends State<PaymentWebViewScreen> {
  late final WebViewController _controller;
  WebSocket? _socket;
  bool _isSubmitting = false;
  bool _pageLoaded = false;
  int _loadingProgress = 0;
  bool _isConnectingStream = false;
  String? _streamStatus;
  String? _streamMessage;
  Uint8List? _latestFrameBytes;
  bool _streamClosed = false;

  @override
  void initState() {
    super.initState();
    if (_usesStreamPreview) {
      _connectStream();
    } else {
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
  }

  bool get _usesStreamPreview =>
      widget.streamUrl != null && widget.streamUrl!.isNotEmpty;

  Future<void> _connectStream() async {
    final streamUrl = widget.streamUrl;
    if (streamUrl == null || streamUrl.isEmpty) return;

    setState(() {
      _isConnectingStream = true;
      _streamClosed = false;
      _streamMessage = '브라우저 화면 스트림에 연결하는 중이에요.';
    });

    try {
      final socket = await WebSocket.connect(streamUrl);
      _socket = socket;
      if (!mounted) return;
      setState(() {
        _isConnectingStream = false;
      });

      socket.listen(
        _handleStreamMessage,
        onDone: () {
          if (!mounted) return;
          setState(() {
            _streamClosed = true;
            _isConnectingStream = false;
          });
        },
        onError: (Object error) {
          if (!mounted) return;
          setState(() {
            _isConnectingStream = false;
            _streamClosed = true;
            _streamMessage = '스트림 연결 중 오류가 발생했어요: $error';
          });
        },
      );
    } catch (error) {
      if (!mounted) return;
      setState(() {
        _isConnectingStream = false;
        _streamClosed = true;
        _streamMessage = '스트림에 연결하지 못했어요: $error';
      });
    }
  }

  void _handleStreamMessage(dynamic rawMessage) {
    if (rawMessage is! String) return;

    final decoded = jsonDecode(rawMessage);
    if (decoded is! Map<String, dynamic>) return;

    final imageBase64 = decoded['imageBase64'];
    Uint8List? imageBytes;
    if (imageBase64 is String && imageBase64.isNotEmpty) {
      imageBytes = base64Decode(imageBase64);
    }

    if (!mounted) return;
    setState(() {
      _streamStatus = decoded['status'] as String?;
      _streamMessage = decoded['message'] as String?;
      if (imageBytes != null) {
        _latestFrameBytes = imageBytes;
      }
      _pageLoaded = imageBytes != null;
      _loadingProgress = imageBytes != null ? 100 : _loadingProgress;
      if (decoded['final'] == true) {
        _streamClosed = true;
      }
    });
  }

  Future<void> _submitResult(String result) async {
    final orderId = widget.orderId;
    final paymentId = widget.paymentId;
    if (orderId == null || paymentId == null) {
      Navigator.of(context).pop();
      return;
    }

    if (_isSubmitting) return;
    setState(() {
      _isSubmitting = true;
    });

    try {
      await context.read<CallProvider>().handlePaymentResult(
        orderId: orderId,
        paymentId: paymentId,
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
  void dispose() {
    _socket?.close();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final canSubmitPaymentResult =
        widget.orderId != null && widget.paymentId != null;

    return Scaffold(
      appBar: AppBar(
        title: Consumer<CallProvider>(
          builder: (context, provider, _) =>
              Text(provider.webviewTargetLabel),
        ),
        actions: [
          TextButton(
            onPressed: _isSubmitting
                ? null
                : () => _submitResult(
                    canSubmitPaymentResult ? 'cancelled' : 'close',
                  ),
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
                  : _usesStreamPreview
                  ? (_streamMessage ??
                        (_isConnectingStream
                            ? '브라우저 화면 스트림을 기다리는 중이에요.'
                            : 'Playwright가 보내는 화면을 보여드리고 있어요.'))
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
                      _streamStatus ?? statusText,
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
                if (_usesStreamPreview)
                  _buildStreamPreview()
                else
                  WebViewWidget(controller: _controller),
                if (!_pageLoaded && !_usesStreamPreview)
                  const Center(child: CircularProgressIndicator()),
              ],
            ),
          ),
          if (canSubmitPaymentResult)
            SafeArea(
              top: false,
              child: Padding(
                padding: const EdgeInsets.fromLTRB(16, 12, 16, 16),
                child: Row(
                  children: [
                    Expanded(
                      child: OutlinedButton(
                        onPressed: _isSubmitting
                            ? null
                            : () => _submitResult('cancelled'),
                        child: const Text('취소'),
                      ),
                    ),
                    const SizedBox(width: 12),
                    Expanded(
                      child: FilledButton(
                        onPressed: _isSubmitting
                            ? null
                            : () => _submitResult('completed'),
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

  Widget _buildStreamPreview() {
    if (_latestFrameBytes != null) {
      return Container(
        color: Colors.black,
        alignment: Alignment.center,
        child: InteractiveViewer(
          minScale: 1,
          maxScale: 4,
          child: Image.memory(
            _latestFrameBytes!,
            fit: BoxFit.contain,
            gaplessPlayback: true,
          ),
        ),
      );
    }

    final message = _streamMessage ??
        (_isConnectingStream
            ? '브라우저 화면 스트림을 연결하는 중이에요.'
            : _streamClosed
            ? '브라우저 화면 스트림이 종료되었어요.'
            : '브라우저 화면을 기다리는 중이에요.');

    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            if (_isConnectingStream)
              const CircularProgressIndicator()
            else
              const Icon(Icons.desktop_windows_outlined, size: 48),
            const SizedBox(height: 16),
            Text(
              message,
              textAlign: TextAlign.center,
              style: const TextStyle(fontSize: 15, color: Color(0xFF555555)),
            ),
          ],
        ),
      ),
    );
  }
}
