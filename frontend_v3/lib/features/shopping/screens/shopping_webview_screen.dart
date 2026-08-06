import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:webview_flutter/webview_flutter.dart';

import '../../../app/theme/app_colors.dart';
import '../../../app/theme/app_radii.dart';
import '../../../app/theme/app_spacing.dart';
import '../../../app/theme/app_text_styles.dart';
import '../../../shared/widgets/bottom_status_banner.dart';
import '../../../shared/widgets/dialogue_bubble.dart';
import '../../../shared/widgets/end_conversation_button.dart';
import '../../../shared/widgets/primary_button.dart';
import '../../../shared/widgets/shopping_progress_stepper.dart';
import '../services/kurly_webview_automation.dart';

class ShoppingWebviewScreen extends StatefulWidget {
  const ShoppingWebviewScreen({
    super.key,
    required this.url,
    this.platform,
    this.shopName,
    this.assistantMessage,
    this.task,
    this.orderId,
    this.paymentId,
    this.productName,
    this.quantity = 1,
    this.canonicalProductUrl,
    this.onResult,
  });

  final String url;
  final String? platform;
  final String? shopName;
  final String? assistantMessage;
  final String? task;
  final int? orderId;
  final int? paymentId;
  final String? productName;
  final int quantity;
  final String? canonicalProductUrl;
  final Future<void> Function(String result, Map<String, dynamic>? extraData)?
  onResult;

  @override
  State<ShoppingWebviewScreen> createState() => _ShoppingWebviewScreenState();
}

class _ShoppingWebviewScreenState extends State<ShoppingWebviewScreen> {
  WebViewController? _controller;
  bool _pageLoaded = false;
  bool _isSubmitting = false;
  bool _isInterrupting = false;
  bool _automationDone = false;
  bool _didRetryCredentialLogin = false;
  bool _automationStarted = false;
  String _automationStep = 'opening_shop';
  String _statusText = '웹 화면을 준비하고 있어요.';
  String? _pendingSubmitResult;
  Map<String, dynamic>? _pendingSubmitExtraData;
  String? _lastAutomationFailureReason;

  bool get _supportsKurlyAutomation {
    final normalizedTask = widget.task?.trim().toLowerCase();
    if (normalizedTask == 'add_to_cart' ||
        normalizedTask == 'address_check' ||
        normalizedTask == 'payment') {
      return true;
    }

    final normalizedPlatform = widget.platform?.trim().toLowerCase();
    final normalizedShopName = widget.shopName?.trim().toLowerCase() ?? '';
    if (_isKurlyUrl(widget.canonicalProductUrl) ||
        _isKurlyUrl(widget.url) ||
        normalizedPlatform == 'kurly' ||
        normalizedPlatform == 'kurlynmart' ||
        normalizedShopName.contains('컬리') ||
        normalizedShopName.contains('kurly')) {
      return true;
    }
    return false;
  }

  bool get _canRetryAutomation =>
      _automationStep == 'login_failed' ||
      _automationStep == 'login_required' ||
      _automationStep == 'login_retry_required' ||
      _automationStep == 'cart_failed' ||
      _automationStep == 'sync_failed';

  bool get _showManualCompletion =>
      !_supportsKurlyAutomation || _automationStep == 'manual_required';

  @override
  void initState() {
    super.initState();
    _automationStep = 'opening_shop';
    _statusText = _initialStatusText();
    _initWebView();
  }

  void _initWebView() {
    _controller = WebViewController()
      ..setJavaScriptMode(JavaScriptMode.unrestricted)
      ..addJavaScriptChannel(
        'KurlyChannel',
        onMessageReceived: (message) {
          debugPrint('🛒 [KurlyChannel] ${message.message}');
        },
      )
      ..setNavigationDelegate(
        NavigationDelegate(
          onPageStarted: (_) {
            if (!mounted) {
              return;
            }
            setState(() => _pageLoaded = false);
          },
          onPageFinished: (_) {
            if (!mounted) {
              return;
            }
            setState(() => _pageLoaded = true);
          },
        ),
      )
      ..loadRequest(Uri.parse(_initialWebviewUrl()));

    WidgetsBinding.instance.addPostFrameCallback((_) => _runAutomation());
  }

  String _initialStatusText() {
    switch (widget.task) {
      case 'address_check':
        return '배송지 화면을 함께 확인하고 있어요.';
      case 'payment':
        return '결제 화면을 준비하고 있어요.';
      case 'add_to_cart':
      default:
        return '상품을 장바구니에 담는 화면을 열었어요.';
    }
  }

  String _title() {
    switch (widget.task) {
      case 'address_check':
        return '배송지 확인';
      case 'payment':
        return '결제 진행';
      case 'add_to_cart':
      default:
        return '장바구니 작업';
    }
  }

  ShoppingProgressStep get _currentStep {
    switch (widget.task) {
      case 'payment':
      case 'address_check':
        return ShoppingProgressStep.payment;
      case 'add_to_cart':
      default:
        return ShoppingProgressStep.addToCart;
    }
  }

  Set<ShoppingProgressStep> get _completedSteps {
    switch (widget.task) {
      case 'payment':
      case 'address_check':
        return const {
          ShoppingProgressStep.productCheck,
          ShoppingProgressStep.productSelection,
          ShoppingProgressStep.addToCart,
        };
      case 'add_to_cart':
      default:
        return const {
          ShoppingProgressStep.productCheck,
          ShoppingProgressStep.productSelection,
        };
    }
  }

  Future<void> _runAutomation() async {
    final controller = _controller;
    if (controller == null || _automationStarted) {
      return;
    }
    _automationStarted = true;

    if (!_supportsKurlyAutomation) {
      if (!mounted) {
        return;
      }
      setState(() {
        _automationStep = 'manual_required';
        _statusText =
            '${_manualPlatformLabel()} 화면은 자동 장바구니 담기를 아직 지원하지 않아요. 직접 확인한 뒤 완료할 수 있어요.';
        _automationDone = true;
      });
      return;
    }

    if (widget.task == 'address_check') {
      await Future<void>.delayed(const Duration(seconds: 2));
      if (!mounted) {
        return;
      }
      final addressData = await _collectKurlyAddressFromCart(controller);
      if (addressData.isEmpty) {
        setState(() {
          _automationStep = 'manual_required';
          _statusText = '배송지 화면까지는 열었어요. 주소 확인은 화면에서 한 번만 확인해주세요.';
          _automationDone = true;
        });
        return;
      }
      await _submitResult('address_checked', extraData: addressData);
      return;
    }

    if (widget.task == 'payment') {
      await Future<void>.delayed(const Duration(seconds: 2));
      if (!mounted) {
        return;
      }
      final prepared = await _prepareKurlyMockPayment(controller);
      if (!prepared) {
        setState(() {
          _automationStep = 'manual_required';
          _statusText = '결제 직전 화면까지 자동으로 열지 못했어요. 화면에서 직접 확인한 뒤 완료해주세요.';
          _automationDone = true;
        });
        return;
      }
      await _submitResult('payment_ready_mock');
      return;
    }

    await Future<void>.delayed(const Duration(seconds: 2));
    if (!mounted) {
      return;
    }

    final credentials = await KurlyCredentialStore.read();
    if (!mounted) {
      return;
    }

    await _runAutomationWithCredentials(controller, credentials);
  }

  Future<void> _runAutomationWithCredentials(
    WebViewController controller,
    KurlyCredentials? credentials,
  ) async {
    if (!mounted) {
      return;
    }

    final automation = KurlyWebviewAutomation(
      controller: controller,
      credentials: credentials,
      onProgress: (step, message) {
        if (!mounted) {
          return;
        }
        setState(() {
          _automationStep = step;
          _statusText = message;
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
    if (!mounted) {
      return;
    }

    if (result == 'cart_added') {
      await _submitResult('cart_added');
      return;
    }

    if (result == 'cart_failed') {
      _lastAutomationFailureReason = automation.lastCartFailureReason;
      await _submitResult(
        'cart_failed',
        extraData: <String, dynamic>{
          if (_lastAutomationFailureReason != null)
            'failureReason': _lastAutomationFailureReason,
        },
      );
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
        _statusText = result == 'login_failed'
            ? '저장된 로그인 정보가 맞지 않아 다시 입력이 필요해요.'
            : '로그인이 필요해요. 로그인 정보를 입력받고 있어요.';
        _automationDone = false;
      });

      if (!mounted) {
        return;
      }
      final refreshedCredentials = await KurlyCredentialStore.ensureCredentials(
        context,
        forcePrompt: true,
      );
      if (!mounted || refreshedCredentials == null) {
        if (!mounted) {
          return;
        }
        setState(() {
          _automationStep = 'login_required';
          _statusText = '컬리 로그인 정보 입력이 취소되었어요.';
          _automationDone = true;
        });
        return;
      }

      await _runAutomationWithCredentials(controller, refreshedCredentials);
    }
  }

  Future<void> _retryAutomation() async {
    if (_isSubmitting || _isInterrupting) {
      return;
    }
    if (_automationStep == 'sync_failed' && _pendingSubmitResult != null) {
      await _submitResult(
        _pendingSubmitResult!,
        extraData: _pendingSubmitExtraData,
      );
      return;
    }

    setState(() {
      _automationStarted = false;
      _automationDone = false;
      _automationStep = 'opening_shop';
      _statusText = '컬리 페이지를 다시 준비하고 있어요.';
      _didRetryCredentialLogin = false;
      _pageLoaded = false;
    });
    await _runAutomation();
  }

  Future<void> _submitResult(
    String result, {
    Map<String, dynamic>? extraData,
  }) async {
    if (_isSubmitting) {
      return;
    }
    setState(() => _isSubmitting = true);
    final navigator = Navigator.of(context);
    final onResult = widget.onResult;

    try {
      _pendingSubmitResult = result;
      _pendingSubmitExtraData = extraData;
      if (navigator.mounted) {
        navigator.pop();
      }
      if (onResult != null) {
        await onResult(result, extraData);
      }
      _pendingSubmitResult = null;
      _pendingSubmitExtraData = null;
    } catch (_) {
      if (!mounted) {
        rethrow;
      }
      setState(() {
        _automationDone = true;
        _automationStep = 'sync_failed';
        _statusText = _syncFailureMessage();
      });
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(SnackBar(content: Text(_syncFailureMessage())));
    } finally {
      if (mounted) {
        setState(() => _isSubmitting = false);
      }
    }
  }

  Future<void> _handleCompletePressed() async {
    switch (widget.task) {
      case 'address_check':
        final addressData = await _collectVisibleAddress();
        await _submitResult('address_checked', extraData: addressData);
        return;
      case 'payment':
        await _submitResult('payment_ready_mock');
        return;
      case 'add_to_cart':
      default:
        await _submitResult('cart_added');
        return;
    }
  }

  Future<void> _interruptWebviewProgress() async {
    if (_isInterrupting) {
      return;
    }
    setState(() => _isInterrupting = true);
    try {
      if (_automationStep == 'cart_failed') {
        await _submitResult(
          'cart_failed',
          extraData: <String, dynamic>{
            if (_lastAutomationFailureReason != null)
              'failureReason': _lastAutomationFailureReason,
          },
        );
        return;
      }
      await _submitResult('cancelled');
    } catch (_) {
      if (!mounted) {
        return;
      }
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(const SnackBar(content: Text('중단 요청에 실패했어요. 다시 시도해주세요.')));
    } finally {
      if (mounted) {
        setState(() => _isInterrupting = false);
      }
    }
  }

  String _syncFailureMessage() {
    switch (widget.task) {
      case 'address_check':
        return '배송지 확인 결과를 서버에 전달하지 못했어요. 다시 시도해주세요.';
      case 'payment':
        return '결제 준비 결과를 서버에 전달하지 못했어요. 다시 시도해주세요.';
      case 'add_to_cart':
      default:
        return '장바구니 진행 결과를 서버에 전달하지 못했어요. 다시 시도해주세요.';
    }
  }

  String _initialWebviewUrl() {
    final task = widget.task?.trim();
    final requestedUrl = widget.url.trim();

    if (task == 'address_check' || task == 'payment') {
      if (requestedUrl.isNotEmpty && requestedUrl != 'about:blank') {
        return requestedUrl;
      }
      return 'https://www.kurly.com/cart';
    }

    final canonicalUrl = widget.canonicalProductUrl?.trim();
    if (canonicalUrl != null && canonicalUrl.contains('kurly.com/goods/')) {
      return canonicalUrl;
    }

    final productName = widget.productName?.trim();
    if (task == 'add_to_cart' &&
        productName != null &&
        productName.isNotEmpty) {
      final safeQuery = Uri.encodeQueryComponent(productName);
      return 'https://www.kurly.com/search?sword=$safeQuery';
    }

    final normalizedPlatform = widget.platform?.trim().toLowerCase();
    final normalizedShopName = widget.shopName?.trim().toLowerCase() ?? '';
    final prefersKurlySearch =
        normalizedPlatform == 'kurly' ||
        normalizedPlatform == 'kurlynmart' ||
        normalizedShopName.contains('컬리') ||
        normalizedShopName.contains('kurly');

    if (prefersKurlySearch && productName != null && productName.isNotEmpty) {
      final safeQuery = Uri.encodeQueryComponent(productName);
      return 'https://www.kurly.com/search?sword=$safeQuery';
    }

    if (requestedUrl.isNotEmpty && requestedUrl != 'about:blank') {
      return requestedUrl;
    }

    if (productName != null && productName.isNotEmpty) {
      final safeQuery = Uri.encodeQueryComponent(productName);
      return 'https://www.kurly.com/search?sword=$safeQuery';
    }

    return 'about:blank';
  }

  Future<Map<String, dynamic>> _collectKurlyAddressFromCart(
    WebViewController controller,
  ) async {
    final orderSheetReady = await _openKurlyOrderSheet(controller);
    if (!orderSheetReady) {
      return const <String, dynamic>{};
    }
    await Future<void>.delayed(const Duration(seconds: 2));

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
      return decoded ?? const <String, dynamic>{};
    } catch (_) {
      return const <String, dynamic>{};
    }
  }

  Future<bool> _prepareKurlyMockPayment(WebViewController controller) async {
    final orderSheetReady = await _openKurlyOrderSheet(controller);
    if (!orderSheetReady) {
      return false;
    }
    await Future<void>.delayed(const Duration(seconds: 2));

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
          });
          if (!orderBtn) return 'missing_order_button';
          click(orderBtn);
          return 'clicked_payment_button';
        })()
      ''');
      await Future<void>.delayed(const Duration(seconds: 2));
      return raw.toString().contains('clicked_payment_button');
    } catch (_) {
      return false;
    }
  }

  Future<bool> _openKurlyOrderSheet(WebViewController controller) async {
    await _openKurlyCart(controller);
    await Future<void>.delayed(const Duration(seconds: 2));

    final cartOrderClicked = await _clickPrimaryKurlyButton(
      controller,
      matchers: const <String>['혜택없이', '주문하기'],
      fallbackMatchers: const <String>['주문하기'],
    );
    if (!cartOrderClicked) {
      return false;
    }

    await Future<void>.delayed(const Duration(seconds: 2));

    await _clickPrimaryKurlyButton(
      controller,
      matchers: const <String>['주문하기'],
      fallbackMatchers: const <String>['주문하기'],
    );

    await Future<void>.delayed(const Duration(seconds: 2));
    return _waitForKurlyOrderSheet(controller);
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
    List<String> fallbackMatchers = const <String>[],
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
      await Future<void>.delayed(const Duration(milliseconds: 600));
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

  Future<Map<String, dynamic>> _collectVisibleAddress() async {
    final controller = _controller;
    if (controller == null) {
      return const <String, dynamic>{};
    }

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
      return decoded ?? const <String, dynamic>{};
    } catch (_) {
      return const <String, dynamic>{};
    }
  }

  Map<String, dynamic>? _decodeJavaScriptJsonObject(Object raw) {
    final text = raw.toString().trim();
    if (text.isEmpty) {
      return null;
    }
    final normalized = text.startsWith('"') && text.endsWith('"')
        ? text.substring(1, text.length - 1).replaceAll(r'\"', '"')
        : text;
    try {
      final decoded = jsonDecode(normalized);
      if (decoded is Map<String, dynamic>) {
        return decoded;
      }
      if (decoded is Map) {
        return Map<String, dynamic>.from(decoded);
      }
    } catch (_) {}
    return null;
  }

  String _platformLabel(String? platform) {
    switch (platform?.trim().toLowerCase()) {
      case 'naver':
      case '네이버':
        return '네이버';
      case 'coupang':
        return '쿠팡';
      case 'kurly':
        return '컬리';
      case 'kurlynmart':
        return '컬리N마트';
      default:
        return '현재';
    }
  }

  String _manualPlatformLabel() {
    final shopName = widget.shopName?.trim();
    if (shopName != null && shopName.isNotEmpty) {
      return shopName;
    }
    return _platformLabel(widget.platform);
  }

  bool _isKurlyUrl(String? url) {
    final normalized = url?.trim().toLowerCase();
    if (normalized == null || normalized.isEmpty) {
      return false;
    }
    return normalized.contains('kurly.com/');
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AppColors.background,
      appBar: AppBar(
        backgroundColor: AppColors.background,
        surfaceTintColor: Colors.transparent,
        title: Text(_title(), style: AppTextStyles.body1),
        actions: [
          Padding(
            padding: const EdgeInsets.only(right: AppSpacing.screenHorizontal),
            child: Center(
              child: EndConversationButton(
                compact: true,
                label: _isInterrupting ? '중단 중...' : '중단하기',
                onPressed: _isSubmitting || _isInterrupting
                    ? () {}
                    : _interruptWebviewProgress,
              ),
            ),
          ),
        ],
      ),
      body: SafeArea(
        child: Column(
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(
                AppSpacing.screenHorizontal,
                0,
                AppSpacing.screenHorizontal,
                AppSpacing.md,
              ),
              child: ShoppingProgressStepper(
                currentStep: _currentStep,
                completedSteps: _completedSteps,
              ),
            ),
            if (widget.assistantMessage?.trim().isNotEmpty == true)
              Padding(
                padding: const EdgeInsets.fromLTRB(
                  AppSpacing.screenHorizontal,
                  0,
                  AppSpacing.screenHorizontal,
                  AppSpacing.md,
                ),
                child: DialogueBubble(
                  text: widget.assistantMessage!.trim(),
                  style: AppTextStyles.body1,
                  tail: DialogueBubbleTail.left,
                ),
              ),
            Padding(
              padding: const EdgeInsets.symmetric(
                horizontal: AppSpacing.screenHorizontal,
              ),
              child: BottomStatusBanner(
                message: _statusText,
                characterAssetPath:
                    'assets/images/character/top/ddalangoo_top.png',
              ),
            ),
            const SizedBox(height: AppSpacing.md),
            Expanded(
              child: Stack(
                children: [
                  Positioned.fill(
                    child: Container(
                      margin: const EdgeInsets.symmetric(
                        horizontal: AppSpacing.screenHorizontal,
                      ),
                      decoration: BoxDecoration(
                        color: Colors.white,
                        borderRadius: BorderRadius.circular(AppRadii.xl),
                        border: Border.all(color: AppColors.border),
                      ),
                      clipBehavior: Clip.antiAlias,
                      child: _controller == null
                          ? const Center(child: CircularProgressIndicator())
                          : WebViewWidget(controller: _controller!),
                    ),
                  ),
                  if (!_pageLoaded)
                    const Positioned.fill(
                      child: Center(child: CircularProgressIndicator()),
                    ),
                ],
              ),
            ),
            Padding(
              padding: const EdgeInsets.fromLTRB(
                AppSpacing.screenHorizontal,
                AppSpacing.lg,
                AppSpacing.screenHorizontal,
                AppSpacing.screenBottom,
              ),
              child: _buildBottomActions(),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildBottomActions() {
    if (_showManualCompletion) {
      return Column(
        children: [
          PrimaryButton(
            label: _isSubmitting ? '처리 중...' : _completeButtonLabel(),
            onPressed: _isSubmitting ? null : _handleCompletePressed,
          ),
        ],
      );
    }

    if (_automationDone && _canRetryAutomation) {
      return Row(
        children: [
          Expanded(
            child: _SecondaryActionButton(
              label: _isInterrupting ? '중단 중...' : '중단하기',
              onPressed: _isSubmitting || _isInterrupting
                  ? null
                  : _interruptWebviewProgress,
            ),
          ),
          const SizedBox(width: AppSpacing.md),
          Expanded(
            child: PrimaryButton(label: '다시 시도', onPressed: _retryAutomation),
          ),
        ],
      );
    }

    return Column(
      children: [
        PrimaryButton(
          label: _isSubmitting ? '처리 중...' : '자동으로 진행 중이에요',
          onPressed: null,
        ),
      ],
    );
  }

  String _completeButtonLabel() {
    switch (widget.task) {
      case 'address_check':
        return '배송지 확인했어요';
      case 'payment':
        return '결제 화면 준비됐어요';
      case 'add_to_cart':
      default:
        return '장바구니에 담았어요';
    }
  }
}

class _SecondaryActionButton extends StatelessWidget {
  const _SecondaryActionButton({required this.label, this.onPressed});

  final String label;
  final VoidCallback? onPressed;

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      width: double.infinity,
      height: 52,
      child: OutlinedButton(
        onPressed: onPressed,
        style: OutlinedButton.styleFrom(
          backgroundColor: Colors.white,
          foregroundColor: AppColors.textPrimary,
          side: const BorderSide(color: AppColors.border),
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(AppRadii.pill),
          ),
        ),
        child: Text(
          label,
          style: AppTextStyles.body2.copyWith(fontWeight: FontWeight.w800),
        ),
      ),
    );
  }
}
