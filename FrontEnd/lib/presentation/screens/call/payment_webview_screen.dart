import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:webview_flutter/webview_flutter.dart';

import '../../../core/network/api_client.dart';
import '../../providers/call_provider.dart';

class PaymentWebViewScreen extends StatefulWidget {
  const PaymentWebViewScreen({
    super.key,
    required this.url,
    this.streamUrl,
    this.orderId,
    this.paymentId,
    this.previewMode = false,
    this.previewTitle,
    this.previewStatusText,
    this.previewHelperText,
    this.previewStep,
    this.previewMessage,
    this.previewScreenshotUrl,
    this.previewShowActionButtons = false,
  });

  final String url;
  final String? streamUrl;
  final int? orderId;
  final int? paymentId;
  final bool previewMode;
  final String? previewTitle;
  final String? previewStatusText;
  final String? previewHelperText;
  final String? previewStep;
  final String? previewMessage;
  final String? previewScreenshotUrl;
  final bool previewShowActionButtons;

  @override
  State<PaymentWebViewScreen> createState() => _PaymentWebViewScreenState();
}

class _PaymentWebViewScreenState extends State<PaymentWebViewScreen> {
  WebViewController? _controller;
  WebSocket? _socket;
  bool _isSubmitting = false;
  bool _pageLoaded = false;
  int _loadingProgress = 0;
  bool _isConnectingStream = false;
  String? _streamStep;
  String? _streamMessage;
  String? _latestScreenshotUrl;
  int _latestScreenshotVersion = 0;
  bool _streamClosed = false;

  @override
  void initState() {
    super.initState();
    if (widget.previewMode) {
      _pageLoaded =
          widget.previewScreenshotUrl != null &&
          widget.previewScreenshotUrl!.isNotEmpty;
      _loadingProgress = _pageLoaded ? 100 : 45;
      _streamStep = widget.previewStep;
      _streamMessage = widget.previewMessage;
      _latestScreenshotUrl = widget.previewScreenshotUrl;
      return;
    }
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

    debugPrint('🖥️ [WebView Stream] connecting: $streamUrl');
    setState(() {
      _isConnectingStream = true;
      _streamClosed = false;
      _streamStep = 'connecting';
      _streamMessage = '브라우저 화면 스트림에 연결하는 중이에요.';
    });

    try {
      final socket = await WebSocket.connect(streamUrl);
      _socket = socket;
      debugPrint('🖥️ [WebView Stream] connected: $streamUrl');
      if (!mounted) return;
      setState(() {
        _isConnectingStream = false;
      });

      socket.listen(
        _handleStreamMessage,
        onDone: () {
          debugPrint('🖥️ [WebView Stream] closed');
          if (!mounted) return;
          setState(() {
            _streamClosed = true;
            _isConnectingStream = false;
          });
        },
        onError: (Object error) {
          debugPrint('🖥️ [WebView Stream] error: $error');
          if (!mounted) return;
          setState(() {
            _isConnectingStream = false;
            _streamClosed = true;
            _streamMessage = '스트림 연결 중 오류가 발생했어요: $error';
          });
        },
      );
    } catch (error) {
      debugPrint('🖥️ [WebView Stream] connect failed: $error');
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
    final screenshotUrl = _resolveScreenshotUrl(
      decoded['screenshotUrl'] as String?,
    );
    final imageBase64 = decoded['imageBase64'] as String?;
    debugPrint(
      '🖥️ [WebView Stream] event: '
      'step=${decoded['step']}, '
      'status=${decoded['status']}, '
      'message=${decoded['message']}, '
      'hasScreenshotUrl=${screenshotUrl != null}, '
      'hasInlineImage=${imageBase64 != null && imageBase64.isNotEmpty}',
    );

    if (!mounted) return;
    setState(() {
      _streamStep = decoded['step'] as String?;
      _streamMessage = decoded['message'] as String? ?? _streamMessage;
      if (screenshotUrl != null) {
        _latestScreenshotVersion += 1;
        _latestScreenshotUrl = _appendCacheBust(
          screenshotUrl,
          decoded['updatedAt'] as String?,
          _latestScreenshotVersion,
        );
        debugPrint(
          '🖥️ [WebView Stream] screenshot updated: $_latestScreenshotUrl',
        );
      } else if (imageBase64 != null && imageBase64.isNotEmpty) {
        _latestScreenshotVersion += 1;
        _latestScreenshotUrl =
            'data:image/jpeg;base64,$imageBase64#$_latestScreenshotVersion';
        debugPrint('🖥️ [WebView Stream] inline screenshot updated');
      }
      _pageLoaded = _latestScreenshotUrl != null;
      _loadingProgress = _latestScreenshotUrl != null ? 100 : _loadingProgress;
      if (decoded['final'] == true) {
        debugPrint('🖥️ [WebView Stream] final event received');
        _streamClosed = true;
      }
    });
  }

  String? _resolveScreenshotUrl(String? rawUrl) {
    if (rawUrl == null || rawUrl.isEmpty) return null;

    final parsed = Uri.tryParse(rawUrl);
    if (parsed != null && parsed.hasScheme) {
      return parsed.toString();
    }

    final streamUri = widget.streamUrl != null && widget.streamUrl!.isNotEmpty
        ? Uri.tryParse(widget.streamUrl!)
        : null;
    if (streamUri != null) {
      final httpScheme = streamUri.scheme == 'wss' ? 'https' : 'http';
      return streamUri
          .replace(
            scheme: httpScheme,
            path: rawUrl,
            query: null,
            fragment: null,
          )
          .toString();
    }

    return Uri.parse(ApiClient.baseUrl).resolve(rawUrl).toString();
  }

  String _appendCacheBust(String url, String? updatedAt, int version) {
    final uri = Uri.parse(url);
    final query = Map<String, String>.from(uri.queryParameters);
    query['t'] = updatedAt ?? '$version';
    return uri.replace(queryParameters: query).toString();
  }

  String _helperTextForStep() {
    switch (_streamStep) {
      case 'connecting':
        return '웹뷰 화면을 연결하는 중이에요.';
      case 'opening_shop':
        return '쇼핑 화면을 준비하고 있어요.';
      case 'logging_in':
        return '로그인이 필요할 때만 계정 정보를 입력하고 있어요.';
      case 'searching_product':
        return '검색 결과에서 요청하신 상품을 찾고 있어요.';
      case 'opening_product':
        return '이전에 구매한 상품 페이지로 바로 이동하고 있어요.';
      case 'fallback_searching':
        return '재구매 페이지 경로가 맞지 않아 검색으로 다시 찾고 있어요.';
      case 'adding_to_cart':
        return '수량과 옵션을 확인한 뒤 장바구니에 담는 중이에요.';
      default:
        if (_isConnectingStream) {
          return '브라우저 화면 스트림을 기다리는 중이에요.';
        }
        if (_streamClosed) {
          return '브라우저 화면 스트림이 종료되었어요.';
        }
        return '실시간 진행 상황과 화면을 이곳에서 보여드리고 있어요.';
    }
  }

  Future<void> _submitResult(String result) async {
    if (widget.previewMode) {
      Navigator.of(context).pop();
      return;
    }
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
    debugPrint('🖥️ [WebView Stream] dispose');
    _socket?.close();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final canSubmitPaymentResult =
        !widget.previewMode &&
        widget.orderId != null &&
        widget.paymentId != null;

    return Scaffold(
      appBar: AppBar(
        title: Text(
          widget.previewTitle ??
              (widget.previewMode
                  ? '웹 진행 상황'
                  : context.read<CallProvider>().webviewTargetLabel),
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
          _buildStatusCard(context),
          Expanded(
            child: Stack(
              children: [
                if (widget.previewMode || _usesStreamPreview)
                  _buildStreamPreview()
                else
                  WebViewWidget(controller: _controller!),
                if (!_pageLoaded && !_usesStreamPreview)
                  const Center(child: CircularProgressIndicator()),
              ],
            ),
          ),
          if (canSubmitPaymentResult || widget.previewShowActionButtons)
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

  Widget _buildStatusCard(BuildContext context) {
    final targetLabel = widget.previewTitle ?? _resolveTargetLabel(context);
    final statusText = widget.previewStatusText ?? _resolveStatusText(context);
    final helperText = widget.previewHelperText ?? _resolveHelperText();

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
            targetLabel,
            style: const TextStyle(
              fontSize: 14,
              fontWeight: FontWeight.w700,
              color: Color(0xFFE8325A),
            ),
          ),
          const SizedBox(height: 8),
          Text(
            _streamMessage ?? statusText,
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
                  : (_loadingProgress <= 0 ? null : _loadingProgress / 100),
              backgroundColor: const Color(0xFFF8DCE5),
              valueColor: const AlwaysStoppedAnimation<Color>(
                Color(0xFFE8325A),
              ),
            ),
          ),
        ],
      ),
    );
  }

  String _resolveTargetLabel(BuildContext context) {
    if (widget.previewMode) {
      return widget.previewTitle ?? '웹 진행 상황';
    }
    return context.read<CallProvider>().webviewTargetLabel;
  }

  String _resolveStatusText(BuildContext context) {
    if (widget.previewMode) {
      return widget.previewStatusText ?? '실시간 진행 상황을 보여드리고 있어요.';
    }
    return context.read<CallProvider>().webviewStatusText;
  }

  String _resolveHelperText() {
    if (_isSubmitting) {
      return '백엔드에 완료 여부를 전달하는 중이에요.';
    }
    if (widget.previewMode) {
      return widget.previewHelperText ?? _helperTextForStep();
    }
    if (_usesStreamPreview) {
      return _helperTextForStep();
    }
    if (_pageLoaded) {
      return '화면이 열렸어요. 진행 상황을 확인해주세요.';
    }
    return '웹 화면을 불러오는 중이에요. 잠시만 기다려주세요.';
  }

  Widget _buildStreamPreview() {
    if (_latestScreenshotUrl != null) {
      return Container(
        color: Colors.black,
        alignment: Alignment.center,
        child: InteractiveViewer(
          minScale: 1,
          maxScale: 4,
          child: Image.network(
            _latestScreenshotUrl!,
            fit: BoxFit.contain,
            gaplessPlayback: true,
            errorBuilder: (context, error, stackTrace) {
              debugPrint('🖥️ [WebView Stream] image load error: $error');
              return _buildPreviewPlaceholder(
                '화면 이미지를 불러오지 못했어요. 다음 업데이트를 기다리는 중이에요.',
              );
            },
            loadingBuilder: (context, child, progress) {
              if (progress == null) return child;
              return _buildPreviewPlaceholder('최신 웹뷰 화면을 불러오는 중이에요.');
            },
          ),
        ),
      );
    }

    final message =
        _streamMessage ??
        (_isConnectingStream
            ? '브라우저 화면 스트림을 연결하는 중이에요.'
            : _streamClosed
            ? '브라우저 화면 스트림이 종료되었어요.'
            : '브라우저 화면을 기다리는 중이에요.');

    return _buildPreviewPlaceholder(message);
  }

  Widget _buildPreviewPlaceholder(String message) {
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
