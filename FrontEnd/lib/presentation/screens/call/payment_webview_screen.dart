import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:webview_flutter/webview_flutter.dart';

import '../../providers/call_provider.dart';
import 'kurly_webview_automation.dart';

class PaymentWebViewScreen extends StatefulWidget {
  const PaymentWebViewScreen({
    super.key,
    required this.url,
    this.task,
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
  final String? task;
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
    final initialUrl = _initialWebviewUrl();
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
      ..loadRequest(Uri.parse(initialUrl));

    WidgetsBinding.instance.addPostFrameCallback((_) => _runAutomation());
  }

  Future<void> _runAutomation() async {
    final controller = _controller;
    if (controller == null || widget.previewMode || _automationStarted) return;
    _automationStarted = true;

    if (widget.task == 'address_check') {
      await Future.delayed(const Duration(seconds: 2));
      if (!mounted) return;
      final addressData = await _collectKurlyAddressFromCart(controller);
      await _submitResult('address_checked', extraData: addressData);
      return;
    }

    if (widget.task == 'payment') {
      await Future.delayed(const Duration(seconds: 2));
      if (!mounted) return;
      final prepared = await _prepareKurlyMockPayment(controller);
      await _submitResult(prepared ? 'payment_ready_mock' : 'cancelled');
      return;
    }

    // 페이지 첫 로드 대기
    await Future.delayed(const Duration(seconds: 2));
    if (!mounted) return;

    final credentials = await KurlyCredentialStore.read();
    if (!mounted) return;

    await _runAutomationWithCredentials(controller, credentials);
  }

  Future<void> _runAutomationWithCredentials(
    WebViewController controller,
    KurlyCredentials? credentials,
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
              step == 'login_failed' ||
              step == 'login_required') {
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

    if (result == 'cart_added') {
      await _submitResult('cart_added');
      return;
    }

    if ((result == 'login_required' || result == 'login_failed') &&
        !_didRetryCredentialLogin) {
      _didRetryCredentialLogin = true;
      if (result == 'login_failed') {
        await KurlyCredentialStore.clear();
      }
      setState(() {
        _automationStep = result == 'login_failed'
            ? 'login_retry_required'
            : 'login_required';
        _automationMessage = result == 'login_failed'
            ? '저장된 로그인 정보가 맞지 않아 다시 입력이 필요해요.'
            : '로그인이 필요해요. 로그인 정보를 입력받고 있어요.';
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

  bool get _canRetryAutomation =>
      _automationStep == 'login_failed' ||
      _automationStep == 'login_required' ||
      _automationStep == 'login_retry_required' ||
      _automationStep == 'cart_failed';

  Future<void> _retryAutomation() async {
    if (_isSubmitting || _isInterrupting) return;
    setState(() {
      _automationStarted = false;
      _automationDone = false;
      _automationStep = 'opening_shop';
      _automationMessage = '컬리 페이지를 다시 준비하고 있어요.';
      _didRetryCredentialLogin = false;
      _pageLoaded = false;
      _loadingProgress = 0;
    });
    await _runAutomation();
  }

  Future<void> _submitResult(
    String result, {
    Map<String, dynamic>? extraData,
  }) async {
    if (widget.previewMode) {
      Navigator.of(context).pop();
      return;
    }
    if (_isSubmitting) return;
    setState(() => _isSubmitting = true);
    final callProvider = context.read<CallProvider>();
    final navigator = Navigator.of(context);
    try {
      await callProvider.handlePaymentResult(
        orderId: widget.orderId,
        paymentId: widget.paymentId,
        result: result,
        extraData: extraData,
        awaitAssistantPresentation: false,
      );
      if (navigator.mounted) {
        navigator.pop();
      }
    } finally {
      if (mounted) setState(() => _isSubmitting = false);
    }
  }

  String _initialWebviewUrl() {
    final canonicalUrl = widget.canonicalProductUrl?.trim();
    if (canonicalUrl != null && canonicalUrl.contains('kurly.com/goods/')) {
      return canonicalUrl;
    }

    final productName = widget.productName?.trim();
    if (productName != null && productName.isNotEmpty) {
      final safeQuery = Uri.encodeQueryComponent(productName);
      return 'https://www.kurly.com/search?sword=$safeQuery';
    }

    return widget.url;
  }

  Future<Map<String, dynamic>> _collectKurlyAddressFromCart(
    WebViewController controller,
  ) async {
    final orderSheetReady = await _openKurlyOrderSheet(controller);
    if (!orderSheetReady) {
      return const {};
    }
    await Future.delayed(const Duration(seconds: 2));
    try {
      final raw = await controller.runJavaScriptReturningResult('''
        (function() {
          function normalize(text) {
            return (text || '').replace(/\\s+/g, ' ').trim();
          }
          function visible(el) {
            if (!el) return false;
            const style = window.getComputedStyle(el);
            if (style.display === 'none' || style.visibility === 'hidden') return false;
            const rect = el.getBoundingClientRect();
            return rect.width > 0 && rect.height > 0;
          }
          const selectors = [
            '[class*="address"]',
            '[data-testid*="address"]',
            'button[aria-label*="배송지"]',
            'a[aria-label*="배송지"]',
            'section',
            'div',
            'span'
          ];
          let best = '';
          for (const selector of selectors) {
            const nodes = Array.from(document.querySelectorAll(selector));
            for (const node of nodes) {
              if (!visible(node)) continue;
              const text = normalize(node.textContent || '');
              if (!text) continue;
              if (
                text.includes('기본배송지') ||
                text.includes('배송지') ||
                text.includes('서빙고로') ||
                text.includes('동') ||
                text.includes('호')
              ) {
                if (text.length > best.length) best = text;
              }
            }
          }
          best = normalize(best.replace(/^배송지\\s*/, '').replace(/^기본배송지\\s*/, ''));
          return JSON.stringify({
            addressLine1: best || null,
            addressLine2: null,
            recipientName: null,
            recipientPhone: null,
            deliveryRequest: null
          });
        })()
      ''');
      final decoded = _decodeJavaScriptJsonObject(raw);
      if (decoded != null) {
        return decoded;
      }
    } catch (_) {}
    return const {};
  }

  Future<bool> _prepareKurlyMockPayment(WebViewController controller) async {
    final orderSheetReady = await _openKurlyOrderSheet(controller);
    if (!orderSheetReady) return false;
    await Future.delayed(const Duration(seconds: 2));
    try {
      final raw = await controller.runJavaScriptReturningResult('''
        (function() {
          function normalize(text) {
            return (text || '').replace(/\\s+/g, ' ').trim();
          }
          function visible(el) {
            if (!el) return false;
            const style = window.getComputedStyle(el);
            if (style.display === 'none' || style.visibility === 'hidden') return false;
            const rect = el.getBoundingClientRect();
            return rect.width > 0 && rect.height > 0;
          }
          function click(el) {
            el.scrollIntoView({ block: 'center', behavior: 'instant' });
            el.click();
          }
          const candidates = Array.from(document.querySelectorAll('button, a, [role="button"]'));
          const orderBtn = candidates.find((el) => {
            if (!visible(el)) return false;
            const text = normalize(el.textContent || el.value || '');
            return text.includes('결제하기');
          }) || candidates.find((el) => {
            if (!visible(el)) return false;
            const text = normalize(el.textContent || el.value || '');
            return text.includes('결제하기');
          });
          if (!orderBtn) return 'missing_order_button';
          click(orderBtn);
          return 'clicked_payment_button';
        })()
      ''');
      await Future.delayed(const Duration(seconds: 2));
      return raw.toString().contains('clicked_payment_button');
    } catch (_) {
      return false;
    }
  }

  Future<bool> _openKurlyOrderSheet(WebViewController controller) async {
    await _openKurlyCart(controller);
    await Future.delayed(const Duration(seconds: 2));

    final cartOrderClicked = await _clickPrimaryKurlyButton(
      controller,
      matchers: const ['혜택없이', '주문하기'],
      fallbackMatchers: ['주문하기'],
    );
    if (!cartOrderClicked) return false;

    await Future.delayed(const Duration(seconds: 2));

    // 장바구니 추천 바텀시트가 뜨면 한 번 더 보라색 주문하기 버튼을 누른다.
    await _clickPrimaryKurlyButton(
      controller,
      matchers: const ['주문하기'],
      fallbackMatchers: ['주문하기'],
    );

    await Future.delayed(const Duration(seconds: 2));
    return await _waitForKurlyOrderSheet(controller);
  }

  Future<void> _openKurlyCart(WebViewController controller) async {
    try {
      await controller.runJavaScriptReturningResult('''
        (function() {
          function normalize(text) {
            return (text || '').replace(/\\s+/g, ' ').trim();
          }
          function visible(el) {
            if (!el) return false;
            const style = window.getComputedStyle(el);
            if (style.display === 'none' || style.visibility === 'hidden') return false;
            const rect = el.getBoundingClientRect();
            return rect.width > 0 && rect.height > 0;
          }
          const selectors = [
            'a[href*="/cart"]',
            'a[href*="cart"]',
            'button[aria-label*="장바구니"]',
            'a[aria-label*="장바구니"]',
            '[data-testid*="cart"]',
            '[class*="cart"]'
          ];
          let target = null;
          for (const selector of selectors) {
            const found = Array.from(document.querySelectorAll(selector)).find((el) => {
              if (!visible(el)) return false;
              const text = normalize(el.textContent || '');
              const aria = normalize(el.getAttribute('aria-label') || '');
              return text.includes('장바구니') || aria.includes('장바구니') || selector.includes('/cart');
            });
            if (found) {
              target = found;
              break;
            }
          }
          if (!target) return 'missing_cart_button';
          target.scrollIntoView({ block: 'center', behavior: 'instant' });
          target.click();
          return 'clicked_cart';
        })()
      ''');
    } catch (_) {}
  }

  Future<bool> _clickPrimaryKurlyButton(
    WebViewController controller, {
    required List<String> matchers,
    List<String> fallbackMatchers = const [],
  }) async {
    try {
      final raw = await controller.runJavaScriptReturningResult('''
        (function() {
          function normalize(text) {
            return (text || '').replace(/\\s+/g, ' ').trim();
          }
          function visible(el) {
            if (!el) return false;
            const style = window.getComputedStyle(el);
            if (style.display === 'none' || style.visibility === 'hidden') return false;
            const rect = el.getBoundingClientRect();
            return rect.width > 0 && rect.height > 0;
          }
          function click(el) {
            el.scrollIntoView({ block: 'center', behavior: 'instant' });
            el.click();
          }
          const strictMatchers = ${jsonEncode(matchers)};
          const looseMatchers = ${jsonEncode(fallbackMatchers)};
          const candidates = Array.from(document.querySelectorAll('button, a, [role="button"]'));

          function matches(text, requiredParts) {
            return requiredParts.every((part) => text.includes(part));
          }

          let target = candidates.find((el) => {
            if (!visible(el)) return false;
            const text = normalize(el.textContent || el.value || '');
            return text && matches(text, strictMatchers);
          });

          if (!target && looseMatchers.length > 0) {
            target = candidates.find((el) => {
              if (!visible(el)) return false;
              const text = normalize(el.textContent || el.value || '');
              return text && looseMatchers.some((part) => text.includes(part));
            });
          }

          if (!target) return 'missing_primary_button';
          click(target);
          return normalize(target.textContent || target.value || '');
        })()
      ''');
      return !raw.toString().contains('missing_primary_button');
    } catch (_) {
      return false;
    }
  }

  Future<bool> _waitForKurlyOrderSheet(WebViewController controller) async {
    for (var attempt = 0; attempt < 8; attempt++) {
      await Future.delayed(const Duration(milliseconds: 600));
      try {
        final raw = await controller.runJavaScriptReturningResult('''
          (function() {
            const bodyText = (document.body && document.body.innerText) || '';
            return bodyText.includes('주문서') &&
              bodyText.includes('배송지') &&
              bodyText.includes('결제하기');
          })()
        ''');
        if (raw.toString() == 'true') {
          return true;
        }
      } catch (_) {}
    }
    return false;
  }

  Map<String, dynamic>? _decodeJavaScriptJsonObject(Object raw) {
    final text = raw.toString().trim();
    if (text.isEmpty) return null;
    final normalized = text.startsWith('"') && text.endsWith('"')
        ? text.substring(1, text.length - 1).replaceAll(r'\"', '"')
        : text;
    try {
      final decoded = jsonDecode(normalized);
      if (decoded is Map<String, dynamic>) return decoded;
      if (decoded is Map) return Map<String, dynamic>.from(decoded);
    } catch (_) {}
    return null;
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
        return '장바구니에 담았어요. 다음 단계를 요청하고 있어요.';
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
                child: _automationDone && _canRetryAutomation
                    ? Row(
                        children: [
                          Expanded(
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
                          const SizedBox(width: 12),
                          Expanded(
                            child: FilledButton.tonal(
                              onPressed: _canRetryAutomation
                                  ? _retryAutomation
                                  : null,
                              child: const Text('다시 시도'),
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
