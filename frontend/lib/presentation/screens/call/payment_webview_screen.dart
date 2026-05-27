import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:webview_flutter/webview_flutter.dart';

import '../../providers/call_provider.dart';
import 'kurly_webview_automation.dart';

class PaymentWebViewScreen extends StatefulWidget {
  const PaymentWebViewScreen({
    super.key,
    required this.url,
    this.orderId,
    this.paymentId,
    this.productName,
    this.quantity = 1,
    this.canonicalProductUrl,
    this.previewMode = false,
    this.previewTitle,
    this.previewStatusText,
    this.previewHelperText,
    this.previewStep,
    this.previewMessage,
  });

  final String url;
  final int? orderId;
  final int? paymentId;
  final String? productName;
  final int quantity;
  final String? canonicalProductUrl;
  final bool previewMode;
  final String? previewTitle;
  final String? previewStatusText;
  final String? previewHelperText;
  final String? previewStep;
  final String? previewMessage;

  @override
  State<PaymentWebViewScreen> createState() => _PaymentWebViewScreenState();
}

class _PaymentWebViewScreenState extends State<PaymentWebViewScreen> {
  WebViewController? _controller;
  bool _isSubmitting = false;
  bool _isInterrupting = false;
  bool _pageLoaded = false;
  int _loadingProgress = 0;
  String _automationStep = 'opening_shop';
  String _automationMessage = '컬리 페이지를 열고 있어요.';
  bool _automationDone = false;
  bool _didRetryCredentialLogin = false;
  bool _automationStarted = false;

  @override
  void initState() {
    super.initState();
    if (widget.previewMode) {
      _pageLoaded = true;
      _loadingProgress = 100;
      _automationStep = widget.previewStep ?? 'opening_shop';
      _automationMessage = widget.previewMessage ?? '미리보기 모드입니다.';
      return;
    }
    _initWebView();
  }

  void _initWebView() {
    _controller = WebViewController()
      ..setJavaScriptMode(JavaScriptMode.unrestricted)
      ..addJavaScriptChannel(
        'KurlyChannel',
        onMessageReceived: (JavaScriptMessage msg) {
          debugPrint('🛒 [KurlyChannel] ${msg.message}');
        },
      )
      ..setNavigationDelegate(
        NavigationDelegate(
          onProgress: (progress) {
            if (!mounted) return;
            setState(() => _loadingProgress = progress);
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

    WidgetsBinding.instance.addPostFrameCallback((_) => _runAutomation());
  }

  Future<void> _runAutomation() async {
    final controller = _controller;
    if (controller == null || widget.previewMode || _automationStarted) return;
    _automationStarted = true;

    // 페이지 첫 로드 대기
    await Future.delayed(const Duration(seconds: 2));
    if (!mounted) return;

    final credentials = await KurlyCredentialStore.ensureCredentials(context);
    if (!mounted || credentials == null) {
      setState(() {
        _automationStep = 'login_required';
        _automationMessage = '컬리 로그인 정보가 필요해요. 다시 시도해주세요.';
        _automationDone = true;
      });
      return;
    }

    await _runAutomationWithCredentials(controller, credentials);
  }

  Future<void> _runAutomationWithCredentials(
    WebViewController controller,
    KurlyCredentials credentials,
  ) async {
    if (!mounted) return;

    final automation = KurlyWebviewAutomation(
      controller: controller,
      credentials: credentials,
      onProgress: (step, message) {
        if (!mounted) return;
        setState(() {
          _automationStep = step;
          _automationMessage = message;
          if (step == 'cart_added' ||
              step == 'cart_failed' ||
              step == 'login_failed') {
            _automationDone = true;
          }
        });
      },
    );

    final result = await automation.run(
      productName: widget.productName ?? '상품',
      quantity: widget.quantity,
      canonicalProductUrl: widget.canonicalProductUrl,
      executionUrl: widget.url,
    );
    if (!mounted) return;

    if (result == 'login_failed' && !_didRetryCredentialLogin) {
      _didRetryCredentialLogin = true;
      await KurlyCredentialStore.clear();
      setState(() {
        _automationStep = 'login_retry_required';
        _automationMessage = '저장된 로그인 정보가 맞지 않아 다시 입력이 필요해요.';
        _automationDone = false;
      });

      if (!mounted) return;
      final refreshedCredentials = await KurlyCredentialStore.ensureCredentials(
        context,
        forcePrompt: true,
      );
      if (!mounted || refreshedCredentials == null) {
        setState(() {
          _automationStep = 'login_required';
          _automationMessage = '컬리 로그인 정보 입력이 취소되었어요.';
          _automationDone = true;
        });
        return;
      }

      await _runAutomationWithCredentials(controller, refreshedCredentials);
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
    setState(() => _isSubmitting = true);
    try {
      await context.read<CallProvider>().handlePaymentResult(
        orderId: orderId,
        paymentId: paymentId,
        result: result,
      );
      if (mounted) Navigator.of(context).pop();
    } finally {
      if (mounted) setState(() => _isSubmitting = false);
    }
  }

  Future<void> _interruptWebviewProgress() async {
    if (widget.previewMode || _isInterrupting) return;
    setState(() => _isInterrupting = true);
    try {
      await context.read<CallProvider>().interruptWebviewProgress();
      if (mounted) Navigator.of(context).pop();
    } catch (_) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('중단 요청에 실패했어요. 다시 시도해주세요.')),
      );
    } finally {
      if (mounted) setState(() => _isInterrupting = false);
    }
  }

  String _helperTextForStep() {
    switch (_automationStep) {
      case 'opening_shop':
        return '쇼핑 화면을 준비하고 있어요.';
      case 'logging_in':
        return '로그인이 필요할 때만 계정 정보를 입력하고 있어요.';
      case 'searching_product':
        return '검색 결과에서 요청하신 상품을 찾고 있어요.';
      case 'opening_product':
        return '이전에 구매한 상품 페이지로 바로 이동하고 있어요.';
      case 'adding_to_cart':
        return '수량과 옵션을 확인한 뒤 장바구니에 담는 중이에요.';
      case 'cart_added':
        return '장바구니에 담았어요! 아래 버튼으로 완료 또는 취소해주세요.';
      case 'cart_failed':
        return '장바구니 담기에 실패했어요. 직접 화면에서 확인해주세요.';
      case 'login_failed':
        return '로그인에 실패했어요. 직접 로그인 후 진행해주세요.';
      case 'login_retry_required':
        return '저장된 로그인 정보가 맞지 않아 새 로그인 정보를 입력받고 있어요.';
      case 'login_required':
        return '앱 안에서 컬리 로그인 정보를 한 번 저장하면 다음부터 자동으로 사용해요.';
      default:
        return '실시간 진행 상황을 이곳에서 보여드리고 있어요.';
    }
  }

  @override
  Widget build(BuildContext context) {
    final canSubmitResult =
        !widget.previewMode && widget.orderId != null && widget.paymentId != null;

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
                : () => _submitResult(canSubmitResult ? 'cancelled' : 'close'),
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
                if (_controller != null)
                  WebViewWidget(controller: _controller!)
                else
                  const Center(child: CircularProgressIndicator()),
                if (!_pageLoaded)
                  const Center(child: CircularProgressIndicator()),
              ],
            ),
          ),
          if (canSubmitResult || widget.previewMode)
            SafeArea(
              top: false,
              child: Padding(
                padding: const EdgeInsets.fromLTRB(16, 12, 16, 16),
                child: _automationDone
                    ? Row(
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
                      )
                    : SizedBox(
                        width: double.infinity,
                        child: FilledButton.tonal(
                          onPressed: _isSubmitting || _isInterrupting
                              ? null
                              : _interruptWebviewProgress,
                          style: FilledButton.styleFrom(
                            minimumSize: const Size.fromHeight(54),
                            foregroundColor: const Color(0xFFE8325A),
                          ),
                          child: Text(
                            _isInterrupting ? '중단 요청 중...' : '중단하기',
                          ),
                        ),
                      ),
              ),
            ),
        ],
      ),
    );
  }

  Widget _buildStatusCard(BuildContext context) {
    final targetLabel = widget.previewTitle ??
        (widget.previewMode
            ? '웹 진행 상황'
            : context.read<CallProvider>().webviewTargetLabel);
    final statusText = widget.previewStatusText ?? _automationMessage;
    final helperText = widget.previewHelperText ?? _helperTextForStep();

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
              value: _automationDone
                  ? 1.0
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
}
