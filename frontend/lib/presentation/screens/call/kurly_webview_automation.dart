import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:webview_flutter/webview_flutter.dart';

typedef AutomationProgressCallback = void Function(String step, String message);

class KurlyCredentials {
  const KurlyCredentials({
    required this.id,
    required this.password,
  });

  final String id;
  final String password;
}

class KurlyCredentialStore {
  static const _idKey = 'kurly_id';
  static const _passwordKey = 'kurly_password';
  static Future<KurlyCredentials?>? _activePrompt;
  static const FlutterSecureStorage _storage = FlutterSecureStorage(
    aOptions: AndroidOptions(encryptedSharedPreferences: true),
    iOptions: IOSOptions(
      accessibility: KeychainAccessibility.first_unlock_this_device,
    ),
  );

  static Future<KurlyCredentials?> read() async {
    final id = (await _storage.read(key: _idKey))?.trim();
    final password = (await _storage.read(key: _passwordKey))?.trim();
    if (id == null || id.isEmpty || password == null || password.isEmpty) {
      return null;
    }
    return KurlyCredentials(id: id, password: password);
  }

  static Future<void> save({
    required String id,
    required String password,
  }) async {
    await _storage.write(key: _idKey, value: id.trim());
    await _storage.write(key: _passwordKey, value: password.trim());
  }

  static Future<void> clear() async {
    await _storage.delete(key: _idKey);
    await _storage.delete(key: _passwordKey);
  }

  static Future<KurlyCredentials?> ensureCredentials(
    BuildContext context, {
    bool forcePrompt = false,
  }) async {
    if (!forcePrompt) {
      final cached = await read();
      if (cached != null) return cached;
    }
    if (!context.mounted) return null;
    final activePrompt = _activePrompt;
    if (activePrompt != null) {
      return activePrompt;
    }
    return _showCredentialDialog(context);
  }

  static Future<KurlyCredentials?> _showCredentialDialog(
    BuildContext context,
  ) async {
    final promptFuture = showDialog<KurlyCredentials>(
      context: context,
      barrierDismissible: false,
      builder: (_) => const _KurlyCredentialDialog(),
    );
    _activePrompt = promptFuture;
    try {
      return await promptFuture;
    } finally {
      if (identical(_activePrompt, promptFuture)) {
        _activePrompt = null;
      }
    }
  }

  static Future<KurlyCredentials?> _saveFromControllers(
    BuildContext context, {
    required TextEditingController idController,
    required TextEditingController passwordController,
  }) async {
    final id = idController.text.trim();
    final password = passwordController.text.trim();
    if (id.isEmpty || password.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('컬리 아이디와 비밀번호를 모두 입력해주세요.')),
      );
      return null;
    }
    await save(id: id, password: password);
    return KurlyCredentials(id: id, password: password);
  }
}

class _KurlyCredentialDialog extends StatefulWidget {
  const _KurlyCredentialDialog();

  @override
  State<_KurlyCredentialDialog> createState() => _KurlyCredentialDialogState();
}

class _KurlyCredentialDialogState extends State<_KurlyCredentialDialog> {
  final TextEditingController _idController = TextEditingController();
  final TextEditingController _passwordController = TextEditingController();
  bool _obscureText = true;

  @override
  void dispose() {
    _idController.dispose();
    _passwordController.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    final credentials = await KurlyCredentialStore._saveFromControllers(
      context,
      idController: _idController,
      passwordController: _passwordController,
    );
    if (!mounted || credentials == null) return;
    FocusScope.of(context).unfocus();
    Navigator.of(context).pop(credentials);
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('컬리 로그인 정보 입력'),
      content: SingleChildScrollView(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            TextField(
              controller: _idController,
              autofocus: true,
              textInputAction: TextInputAction.next,
              decoration: const InputDecoration(
                labelText: '컬리 아이디',
                hintText: '이메일 또는 아이디',
              ),
            ),
            const SizedBox(height: 12),
            TextField(
              controller: _passwordController,
              obscureText: _obscureText,
              decoration: InputDecoration(
                labelText: '컬리 비밀번호',
                suffixIcon: IconButton(
                  onPressed: () {
                    setState(() {
                      _obscureText = !_obscureText;
                    });
                  },
                  icon: Icon(
                    _obscureText ? Icons.visibility_off : Icons.visibility,
                  ),
                ),
              ),
              onSubmitted: (_) => _submit(),
            ),
          ],
        ),
      ),
      actions: [
        TextButton(
          onPressed: () {
            FocusScope.of(context).unfocus();
            Navigator.of(context).pop();
          },
          child: const Text('취소'),
        ),
        FilledButton(
          onPressed: _submit,
          child: const Text('저장'),
        ),
      ],
    );
  }
}

class KurlyWebviewAutomation {
  final WebViewController controller;
  final KurlyCredentials? credentials;
  final AutomationProgressCallback? onProgress;
  String? _lastCartFailureReason;

  KurlyWebviewAutomation({
    required this.controller,
    this.credentials,
    this.onProgress,
  });

  void _report(String step, String message) {
    onProgress?.call(step, message);
  }

  void _debug(String message) {
    debugPrint('🛒 [KurlyAutomation] $message');
  }

  Future<String> run({
    required String productName,
    required int quantity,
    String? canonicalProductUrl,
    String? executionUrl,
  }) async {
    _report('opening_shop', '컬리 페이지를 열고 있어요.');

    final targetUrl =
        _pickInitialTargetUrl(
          productName: productName,
          canonicalProductUrl: canonicalProductUrl,
          executionUrl: executionUrl,
        ) ??
        'https://www.kurly.com';
    _debug('run start targetUrl=$targetUrl, canonicalProductUrl=$canonicalProductUrl, quantity=$quantity');
    await _loadUrlIfNeeded(targetUrl);

    await _waitForPageLoad();
    await _dismissAlreadyLoggedInDialogIfNeeded();

    final isLoggedIn = await _checkLoginState();
    _debug('initial login state=$isLoggedIn');
    if (!isLoggedIn) {
      if (credentials == null) {
        _report('login_required', '로그인이 필요해요. 로그인 정보를 입력해주세요.');
        return 'login_required';
      }
      _report('logging_in', '로그인이 필요해요. 계정 정보를 입력하고 있어요.');
      final loginSuccess = await _attemptLogin();
      _debug('login attempt result=$loginSuccess');
      if (!loginSuccess) {
        _report('login_failed', '로그인에 실패했어요. 다시 시도해주세요.');
        return 'login_failed';
      }
      await _waitForPageLoad();
      await _dismissAlreadyLoggedInDialogIfNeeded();
    }

    if (canonicalProductUrl != null && canonicalProductUrl.contains('/goods/')) {
      _report('opening_product', '상품 페이지로 이동하고 있어요.');
      _debug('open canonical product page directly');
      await _loadUrlIfNeeded(canonicalProductUrl);
      await _waitForPageLoad();
    } else {
      _report('searching_product', '상품을 검색하고 있어요.');
      final searchReady = await _ensureSearchResultsReady();
      _debug('search results already ready=$searchReady');
      final opened = searchReady ? true : await _searchProduct(productName);
      _debug('search/open product result=$opened');
      if (!opened) {
        _report('cart_failed', '상품 페이지를 찾지 못했어요.');
        return 'cart_failed';
      }
    }

    final loginRecoveryResult = await _ensureLoggedInForShoppingFlow(
      fallbackUrl: targetUrl,
    );
    if (loginRecoveryResult != 'ok') {
      return loginRecoveryResult;
    }

    _report('adding_to_cart', '장바구니에 담고 있어요.');
    var cartSuccess = await _addToCart(
      quantity: quantity,
      productName: productName,
    );
    final shouldRetryCart = !_isUnsafeCartRetryReason(_lastCartFailureReason);
    if (!cartSuccess && shouldRetryCart) {
      final retryRecoveryResult = await _ensureLoggedInForShoppingFlow(
        fallbackUrl: targetUrl,
      );
      if (retryRecoveryResult == 'ok') {
        cartSuccess = await _addToCart(
          quantity: quantity,
          productName: productName,
        );
      } else {
        return retryRecoveryResult;
      }
    }
    if (!cartSuccess && !shouldRetryCart) {
      _debug('skip cart retry due to reason=$_lastCartFailureReason');
    }
    _debug('add to cart result=$cartSuccess reason=$_lastCartFailureReason');
    if (cartSuccess) {
      _report('cart_added', '장바구니에 담았어요!');
      return 'cart_added';
    } else {
      _report('cart_failed', '장바구니 담기에 실패했어요.');
      return 'cart_failed';
    }
  }

  Future<void> _waitForPageLoad() async {
    await Future.delayed(const Duration(milliseconds: 1500));
  }

  Future<bool> _checkLoginState() async {
    try {
      final result = await controller.runJavaScriptReturningResult('''
        (function() {
          var pathname = location.pathname || '';
          var href = location.href || '';
          var loginBtn = document.querySelector('a[href*="/member/login"]');
          var myBtn = document.querySelector('a[href*="/mypage"], a[href*="/member/mypage"], a[href*="/mykurly"]');
          var headerLogin = document.querySelector('.header-login');
          var logoutEl = document.querySelector('a[href*="logout"], button[data-testid="logout"]');
          var bodyText = document.body ? (document.body.innerText || '') : '';
          var loginForm = document.querySelector(
            'input[name="id"], input[name="loginId"], input[type="email"], input[autocomplete="username"], input[inputmode="email"], input[placeholder*="아이디"], input[placeholder*="이메일"]'
          );
          if (logoutEl) return true;
          if (myBtn) return true;
          if (bodyText.includes('이미 로그인') || bodyText.includes('이미 로그인되어')) return true;
          if (!pathname.includes('/member/login') && !href.includes('/member/login') && !loginForm) {
            return true;
          }
          if (loginBtn) return false;
          if (headerLogin) return false;
          var cookieStr = document.cookie;
          return cookieStr.includes('sso_token') || cookieStr.includes('user_token');
        })()
      ''');
      return result.toString() == 'true';
    } catch (_) {
      return false;
    }
  }

  Future<bool> _attemptLogin() async {
    final credentials = this.credentials;
    if (credentials == null) return false;

    try {
      _debug('opening login page');
      await controller.loadRequest(Uri.parse('https://www.kurly.com/member/login'));
      await _waitForPageLoad();
      var dismissedAlreadyLoggedIn = await _dismissAlreadyLoggedInDialogIfNeeded();

      if (dismissedAlreadyLoggedIn || await _checkLoginState()) {
        _debug('already logged in after opening login page');
        return true;
      }

      await _openIdLoginTabIfNeeded();

      final formVisible = await _waitForJavaScriptCondition(
        '''
        (function() {
          var emailInput = document.querySelector(
            'input[name="id"], input[name="loginId"], input[type="email"], input[autocomplete="username"], input[inputmode="email"], input[placeholder*="아이디"], input[placeholder*="이메일"]'
          );
          var pwInput = document.querySelector(
            'input[name="password"], input[name="passwd"], input[type="password"], input[autocomplete="current-password"]'
          );
          return !!emailInput && !!pwInput;
        })()
        ''',
        timeout: const Duration(seconds: 10),
        interval: const Duration(milliseconds: 500),
      );
      if (!formVisible) {
        final pageSnapshot = await _safePageSnapshot();
        _debug('login form not visible snapshot=$pageSnapshot');
        if (await _checkLoginState() || await _isOutsideLoginPage()) {
          _debug('treating missing login form as already logged in');
          return true;
        }
        _debug('login form not visible');
        return false;
      }

      final safeId = _escapeForJavaScript(credentials.id);
      final safePassword = _escapeForJavaScript(credentials.password);

      final fillResult = await controller.runJavaScriptReturningResult('''
        (function() {
          var emailInput = document.querySelector(
            'input[name="id"], input[name="loginId"], input[type="email"], input[autocomplete="username"], input[inputmode="email"], input[placeholder*="아이디"], input[placeholder*="이메일"]'
          );
          var pwInput = document.querySelector(
            'input[name="password"], input[name="passwd"], input[type="password"], input[autocomplete="current-password"]'
          );
          if (!emailInput || !pwInput) return 'missing_inputs';

          var nativeInputValueSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
          emailInput.focus();
          nativeInputValueSetter.call(emailInput, '$safeId');
          emailInput.dispatchEvent(new Event('input', { bubbles: true }));
          emailInput.dispatchEvent(new Event('change', { bubbles: true }));
          emailInput.dispatchEvent(new Event('blur', { bubbles: true }));
          emailInput.dispatchEvent(new KeyboardEvent('keyup', { bubbles: true, key: 'Tab' }));
          pwInput.focus();
          nativeInputValueSetter.call(pwInput, '$safePassword');
          pwInput.dispatchEvent(new Event('input', { bubbles: true }));
          pwInput.dispatchEvent(new Event('change', { bubbles: true }));
          pwInput.dispatchEvent(new Event('blur', { bubbles: true }));
          pwInput.dispatchEvent(new KeyboardEvent('keyup', { bubbles: true, key: 'Enter', code: 'Enter' }));
          return 'filled';
        })()
      ''');
      _debug('login form fill result=$fillResult');

      await Future.delayed(const Duration(milliseconds: 700));
      dismissedAlreadyLoggedIn =
          await _dismissAlreadyLoggedInDialogIfNeeded() ||
          dismissedAlreadyLoggedIn;

      for (var attempt = 0; attempt < 3; attempt++) {
        final submitResult = await controller.runJavaScriptReturningResult('''
          (function() {
            function isVisible(element) {
              if (!element) return false;
              var style = window.getComputedStyle(element);
              if (style.display === 'none' || style.visibility === 'hidden') return false;
              var rect = element.getBoundingClientRect();
              return rect.width > 0 && rect.height > 0;
            }

            function clickElement(element) {
              element.focus();
              ['pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click'].forEach(function(type) {
                element.dispatchEvent(new MouseEvent(type, { bubbles: true, cancelable: true, view: window }));
              });
              if (typeof element.click === 'function') {
                element.click();
              }
            }

            var selectors = [
              'button[type="submit"]',
              'input[type="submit"]',
              'button[data-testid="login-submit"]',
              '[data-testid*="login"]',
              '.btn-login',
              'button[class*="login"]',
              'button[class*="submit"]'
            ];

            var candidates = [];
            selectors.forEach(function(selector) {
              document.querySelectorAll(selector).forEach(function(element) {
                candidates.push(element);
              });
            });

            if (candidates.length === 0) {
              document.querySelectorAll('button, input[type="submit"], a, [role="button"]').forEach(function(element) {
                candidates.push(element);
              });
            }

            var submitBtn = candidates.find(function(element) {
              if (!isVisible(element) || element.disabled) return false;
              var text = (element.textContent || element.value || '').trim();
              return text === '로그인' || text.includes('로그인');
            });

            if (submitBtn) {
              clickElement(submitBtn);
              return 'clicked_button';
            }

            var pwInput = document.querySelector(
              'input[name="password"], input[name="passwd"], input[type="password"], input[autocomplete="current-password"]'
            );
            if (pwInput) {
              pwInput.focus();
              ['keydown', 'keypress', 'keyup'].forEach(function(type) {
                pwInput.dispatchEvent(new KeyboardEvent(type, {
                  bubbles: true,
                  cancelable: true,
                  key: 'Enter',
                  code: 'Enter'
                }));
              });
            }

            var form = pwInput ? pwInput.form : document.querySelector('form');
            if (form) {
              if (typeof form.requestSubmit === 'function') {
                form.requestSubmit();
                return 'request_submit';
              }
              form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
              if (typeof form.submit === 'function') {
                form.submit();
              }
              return 'submitted_form';
            }

            return 'no_submit_target';
          })()
        ''');
        _debug('login submit attempt=${attempt + 1} result=$submitResult');

        await Future.delayed(const Duration(milliseconds: 1200));
        dismissedAlreadyLoggedIn =
            await _dismissAlreadyLoggedInDialogIfNeeded() ||
            dismissedAlreadyLoggedIn;

        final loginSucceeded = await _waitForLoginSuccess();
        _debug('login success detector attempt=${attempt + 1} result=$loginSucceeded');
        if (loginSucceeded ||
            dismissedAlreadyLoggedIn ||
            await _checkLoginState() ||
            await _isOutsideLoginPage()) {
          return true;
        }
      }
      return false;
    } catch (_) {
      return false;
    }
  }

  String _escapeForJavaScript(String value) {
    return value
        .replaceAll(r'\', r'\\')
        .replaceAll("'", r"\'")
        .replaceAll('\n', r'\n')
        .replaceAll('\r', r'\r');
  }

  Future<void> _openIdLoginTabIfNeeded() async {
    await controller.runJavaScript('''
      (function() {
        var clickable = Array.from(document.querySelectorAll('button, a, [role="button"]'));
        var idLoginButton = clickable.find(function(element) {
          var text = (element.textContent || '').trim();
          return text.includes('아이디 로그인') || text.includes('이메일 로그인') || text.includes('이메일로 로그인');
        });
        if (idLoginButton) {
          idLoginButton.click();
        }
      })()
    ''');
    await Future.delayed(const Duration(milliseconds: 600));
  }

  Future<bool> _dismissAlreadyLoggedInDialogIfNeeded() async {
    try {
      final dismissed = await controller.runJavaScriptReturningResult('''
        (function() {
          var bodyText = document.body ? (document.body.innerText || '') : '';
          var looksLikeLoggedInPopup =
            bodyText.includes('이미 로그인') ||
            bodyText.includes('이미 로그인되어') ||
            bodyText.includes('다른 기기에서 로그인');
          if (!looksLikeLoggedInPopup) return false;

          var candidates = Array.from(document.querySelectorAll('button, a'));
          var confirmButton = candidates.find(function(element) {
            var text = (element.textContent || '').trim();
            return text === '확인' || text === '닫기' || text.includes('확인');
          });
          if (confirmButton) {
            confirmButton.click();
            return true;
          }
          return false;
        })()
      ''');
      if (dismissed.toString() == 'true') {
        _debug('dismissed already-logged-in popup');
        await Future.delayed(const Duration(milliseconds: 600));
        return true;
      }
    } catch (_) {}
    return false;
  }

  Future<bool> _waitForLoginSuccess() async {
    return _waitForJavaScriptCondition(
      '''
      (function() {
        var logoutEl = document.querySelector('a[href*="logout"], button[data-testid="logout"]');
        var myBtn = document.querySelector('a[href*="/mypage"], a[href*="/member/mypage"], a[href*="/mykurly"]');
        var cookieStr = document.cookie || '';
        var onLoginPage = location.pathname.includes('/member/login');
        var bodyText = document.body ? (document.body.innerText || '') : '';
        var loggedInPopup = bodyText.includes('이미 로그인') || bodyText.includes('이미 로그인되어');
        return !!logoutEl || !!myBtn || loggedInPopup || (!onLoginPage && (cookieStr.includes('sso_token') || cookieStr.includes('user_token')));
      })()
      ''',
      timeout: const Duration(seconds: 10),
      interval: const Duration(milliseconds: 500),
    );
  }

  Future<bool> _isOutsideLoginPage() async {
    try {
      final result = await controller.runJavaScriptReturningResult('''
        (function() {
          var pathname = location.pathname || '';
          var href = location.href || '';
          return !pathname.includes('/member/login') && !href.includes('/member/login');
        })()
      ''');
      return result.toString() == 'true';
    } catch (_) {
      return false;
    }
  }

  Future<bool> _waitForJavaScriptCondition(
    String script, {
    Duration timeout = const Duration(seconds: 5),
    Duration interval = const Duration(milliseconds: 300),
  }) async {
    final deadline = DateTime.now().add(timeout);
    while (DateTime.now().isBefore(deadline)) {
      try {
        final result = await controller.runJavaScriptReturningResult(script);
        if (result.toString() == 'true') return true;
      } catch (_) {}
      await Future.delayed(interval);
    }
    return false;
  }

  Future<bool> _searchProduct(String productName) async {
    final safeQuery = Uri.encodeComponent(productName);
    _debug('search query=$productName');
    await _loadUrlIfNeeded('https://www.kurly.com/search?sword=$safeQuery');
    await _waitForPageLoad();
    final productOpened = await _ensureSearchResultsReady();
    if (!productOpened) {
      _debug('search results did not render goods links');
      return false;
    }

    final firstProductHref = await controller.runJavaScriptReturningResult('''
      (function() {
        var productLinks = Array.from(document.querySelectorAll('a[href*="/goods/"]'));
        if (productLinks.length === 0) return '';
        var firstLink = productLinks[0];
        return firstLink.href || firstLink.getAttribute('href') || '';
      })()
    ''');
    final href = _normalizeJavaScriptString(firstProductHref);
    _debug('first search result href=$href');
    return href.isNotEmpty;
  }

  Future<String> _ensureLoggedInForShoppingFlow({
    required String fallbackUrl,
  }) async {
    final loggedIn = await _checkLoginState();
    if (loggedIn) return 'ok';

    _debug('login state lost during shopping flow');
    if (credentials == null) {
      _report('login_required', '로그인이 풀려 다시 로그인이 필요해요.');
      return 'login_required';
    }

    _report('logging_in', '로그인이 풀려 다시 로그인하고 있어요.');
    final loginSuccess = await _attemptLogin();
    _debug('re-login attempt result=$loginSuccess');
    if (!loginSuccess) {
      _report('login_failed', '로그인이 풀려 다시 로그인하지 못했어요.');
      return 'login_failed';
    }

    await _waitForPageLoad();
    await _dismissAlreadyLoggedInDialogIfNeeded();
    await _loadUrlIfNeeded(fallbackUrl);
    await _waitForPageLoad();

    final recovered = await _checkLoginState();
    _debug('login recovered after retry=$recovered');
    if (!recovered) {
      _report('login_failed', '다시 로그인했지만 쇼핑 화면으로 복귀하지 못했어요.');
      return 'login_failed';
    }
    return 'ok';
  }

  Future<void> _loadUrlIfNeeded(String url) async {
    final target = url.trim();
    if (target.isEmpty) return;
    try {
      final currentUrlRaw = await controller.runJavaScriptReturningResult(
        'location.href',
      );
      final currentUrl = _normalizeJavaScriptString(currentUrlRaw).trim();
      if (_urlsMatch(currentUrl, target)) {
        _debug('skip loadRequest for same url=$target');
        return;
      }
    } catch (_) {
      // Ignore and proceed with navigation.
    }
    await controller.loadRequest(Uri.parse(target));
  }

  bool _urlsMatch(String currentUrl, String targetUrl) {
    if (currentUrl.isEmpty || targetUrl.isEmpty) return false;
    return currentUrl == targetUrl;
  }

  Future<bool> _ensureSearchResultsReady() async {
    return _waitForJavaScriptCondition(
      '''
      (function() {
        return document.querySelectorAll('a[href*="/goods/"]').length > 0;
      })()
      ''',
      timeout: const Duration(seconds: 8),
      interval: const Duration(milliseconds: 400),
    );
  }

  Future<bool> _addToCart({
    required int quantity,
    required String productName,
  }) async {
    _lastCartFailureReason = null;
    final searchPageCartAdded = await _addToCartFromSearchResults(
      quantity: quantity,
      productName: productName,
    );
    if (searchPageCartAdded) {
      return true;
    }
    if (_isUnsafeCartRetryReason(_lastCartFailureReason)) {
      return false;
    }

    try {
      final cartButtonReady = await _waitForJavaScriptCondition(
        '''
        (function() {
          function isVisible(element) {
            if (!element) return false;
            var style = window.getComputedStyle(element);
            if (style.display === 'none' || style.visibility === 'hidden') return false;
            var rect = element.getBoundingClientRect();
            return rect.width > 0 && rect.height > 0;
          }

          function normalizeText(element) {
            return ((element.textContent || '') + ' ' + (element.getAttribute('aria-label') || ''))
              .replace(/\\s+/g, ' ')
              .trim();
          }

          function isPurchaseSection(section) {
            if (!isVisible(section)) return false;
            var text = normalizeText(section);
            if (!text) return false;
            if (text.includes('컬리멤버스')) return false;
            if (text.includes('추천')) return false;
            if (text.includes('다른 고객')) return false;
            if (text.includes('연관 상품')) return false;
            return text.includes('장바구니') || text.includes('구매하기') || text.includes('수량');
          }

          var sections = Array.from(document.querySelectorAll('main section, main div, section, div'))
            .filter(isPurchaseSection);
          var scopedButtons = sections.flatMap(function(section) {
            return Array.from(section.querySelectorAll('button, a, [role="button"]'));
          });
          return scopedButtons.some(function(button) {
            if (!isVisible(button)) return false;
            var text = normalizeText(button);
            if (text.includes('멤버스') || text.includes('구독')) return false;
            return text.includes('장바구니') || text.includes('담기');
          });
        })()
        ''',
        timeout: const Duration(seconds: 8),
        interval: const Duration(milliseconds: 400),
      );
      if (!cartButtonReady) {
        final snapshot = await _cartDebugSnapshot();
        _debug('cart button not ready snapshot=$snapshot');
        return false;
      }

      // 수량 설정
      if (quantity > 1) {
        for (var i = 1; i < quantity; i++) {
          final quantityResult = await controller.runJavaScriptReturningResult('''
            (function() {
              function isVisible(element) {
                if (!element) return false;
                var style = window.getComputedStyle(element);
                if (style.display === 'none' || style.visibility === 'hidden') return false;
                var rect = element.getBoundingClientRect();
                return rect.width > 0 && rect.height > 0;
              }

              function clickElement(element) {
                element.focus();
                ['pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click'].forEach(function(type) {
                  element.dispatchEvent(new MouseEvent(type, { bubbles: true, cancelable: true, view: window }));
                });
                if (typeof element.click === 'function') {
                  element.click();
                }
              }

              function normalizeText(element) {
                return ((element.textContent || '') + ' ' + (element.getAttribute('aria-label') || ''))
                  .replace(/\\s+/g, ' ')
                  .trim();
              }

              function findPurchaseSection() {
                var sections = Array.from(document.querySelectorAll('main section, main div, section, div'));
                return sections.find(function(section) {
                  if (!isVisible(section)) return false;
                  var text = normalizeText(section);
                  if (!text) return false;
                  if (text.includes('컬리멤버스') || text.includes('추천') || text.includes('연관 상품')) return false;
                  return text.includes('장바구니') || text.includes('구매하기') || text.includes('수량');
                }) || document;
              }

              var root = findPurchaseSection();
              var plusBtn = root.querySelector(
                'button[aria-label="수량 증가"], button[class*="plus"], [data-testid="quantity-plus"], button[aria-label*="increase"], button[class*="QuantityButton"]'
              );
              if (!isVisible(plusBtn)) {
                plusBtn = Array.from(root.querySelectorAll('button, [role="button"]')).find(function(element) {
                  if (!isVisible(element)) return false;
                  var text = normalizeText(element);
                  var label = (element.getAttribute('aria-label') || '').trim().toLowerCase();
                  return text === '+' || label.includes('수량 증가') || label.includes('increase');
                });
              }
              if (!plusBtn) return 'missing_plus';
              clickElement(plusBtn);
              return 'clicked_plus';
            })()
          ''');
          _debug('quantity increment attempt=${i + 1} result=$quantityResult');
          if (quantityResult.toString().contains('missing_plus')) {
            _lastCartFailureReason = 'product_quantity_adjust_failed';
            return false;
          }
          await Future.delayed(const Duration(milliseconds: 300));
        }
      }

      // 장바구니 담기 버튼 클릭
      final clickResult = await controller.runJavaScriptReturningResult('''
        (function() {
          function isVisible(element) {
            if (!element) return false;
            var style = window.getComputedStyle(element);
            if (style.display === 'none' || style.visibility === 'hidden') return false;
            var rect = element.getBoundingClientRect();
            return rect.width > 0 && rect.height > 0;
          }

          function clickElement(element) {
            element.focus();
            ['pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click'].forEach(function(type) {
              element.dispatchEvent(new MouseEvent(type, { bubbles: true, cancelable: true, view: window }));
            });
            if (typeof element.click === 'function') {
              element.click();
            }
          }

          function normalizeText(element) {
            return ((element.textContent || '') + ' ' + (element.getAttribute('aria-label') || ''))
              .replace(/\\s+/g, ' ')
              .trim();
          }

          function findPurchaseSection() {
            var sections = Array.from(document.querySelectorAll('main section, main div, section, div'));
            var bestSection = null;
            var bestScore = -1;
            sections.forEach(function(section) {
              if (!isVisible(section)) return;
              var text = normalizeText(section);
              if (!text) return;
              if (text.includes('컬리멤버스') || text.includes('추천') || text.includes('연관 상품')) return;
              var score = 0;
              if (text.includes('장바구니')) score += 3;
              if (text.includes('구매하기')) score += 2;
              if (text.includes('수량')) score += 2;
              if (text.includes('담기')) score += 1;
              if (score > bestScore) {
                bestScore = score;
                bestSection = section;
              }
            });
            return bestSection;
          }

          function isCartActionText(text) {
            if (!text) return false;
            if (text.includes('멤버스')) return false;
            if (text.includes('구독')) return false;
            if (text.includes('구매하기')) return false;
            if (text.includes('바로구매')) return false;
            if (text.includes('추천') || text.includes('연관')) return false;
            return text.includes('장바구니') || text === '담기';
          }

          var purchaseSection = findPurchaseSection();
          var visibleButtons = Array.from((purchaseSection || document).querySelectorAll('button, a, [role="button"]'))
            .filter(function(element) { return isVisible(element); });

          var candidates = visibleButtons.map(function(element) {
            return {
              element: element,
              text: normalizeText(element)
            };
          }).filter(function(candidate) {
            return isCartActionText(candidate.text);
          });

          var cartBtnCandidate = candidates.find(function(candidate) {
            return candidate.text.includes('장바구니');
          });
          if (!cartBtnCandidate && candidates.length > 0) {
            cartBtnCandidate = candidates[0];
          }
          var cartBtn = cartBtnCandidate ? cartBtnCandidate.element : null;

          if (!cartBtn) {
            return JSON.stringify({
              error: 'missing_cart_button',
              section: purchaseSection ? normalizeText(purchaseSection).slice(0, 160) : '',
              visibleButtons: visibleButtons.slice(0, 12).map(function(element) {
                return normalizeText(element).slice(0, 60);
              })
            });
          }

          clickElement(cartBtn);
          return JSON.stringify({
            clicked: normalizeText(cartBtn).slice(0, 80),
            section: purchaseSection ? normalizeText(purchaseSection).slice(0, 160) : '',
            candidates: candidates.slice(0, 8).map(function(candidate) {
              return candidate.text.slice(0, 60);
            })
          });
        })()
      ''');
      _debug('cart click result=$clickResult');

      await Future.delayed(const Duration(seconds: 2));

      // 담기 성공 여부 확인 (toast, modal, cart count 변화)
      final result = await controller.runJavaScriptReturningResult('''
        (function() {
          function normalize(value) {
            return (value || '').replace(/\\s+/g, ' ').trim();
          }

          function includesProduct(text, productName) {
            var normalizedText = normalize(text);
            var normalizedProductName = normalize(productName);
            if (!normalizedText || !normalizedProductName) return false;
            if (normalizedText.includes(normalizedProductName)) return true;
            var compactProductName = normalizedProductName.replace(/[\\[\\]]/g, '');
            return compactProductName && normalizedText.includes(compactProductName);
          }

          var productName = ${jsonEncode(productName)};
          var toast = document.querySelector('[class*="toast"], [class*="Toast"], [role="alert"]');
          if (toast && includesProduct(toast.textContent, productName) && toast.textContent.includes('담')) {
            return true;
          }
          var modal = document.querySelector('[role="dialog"], [class*="modal"], [class*="Modal"]');
          if (modal &&
              modal.textContent &&
              includesProduct(modal.textContent, productName) &&
              (modal.textContent.includes('장바구니') || modal.textContent.includes('담겼'))) {
            return true;
          }
          var bodyText = document.body ? normalize(document.body.innerText || '') : '';
          if (includesProduct(bodyText, productName) &&
              (bodyText.includes('장바구니에 담겼') || bodyText.includes('장바구니 담기'))) {
            return true;
          }
          return false;
        })()
      ''');

      final clickLooksSuccessful = _cartClickLooksSuccessful(clickResult);
      final success = result.toString() == 'true' || clickLooksSuccessful;
      if (!success) {
        _lastCartFailureReason = 'product_cart_verification_inconclusive';
        final snapshot = await _cartDebugSnapshot();
        _debug('cart verification failed snapshot=$snapshot');
      } else if (clickLooksSuccessful && result.toString() != 'true') {
        _lastCartFailureReason = null;
        _debug('cart verification accepted by click result');
      }
      return success;
    } catch (_) {
      _lastCartFailureReason = 'product_add_exception';
      return false;
    }
  }

  Future<bool> _addToCartFromSearchResults({
    required int quantity,
    required String productName,
  }) async {
    final onSearchPage = await _waitForJavaScriptCondition(
      '''
      (function() {
        return location.pathname.includes('/search');
      })()
      ''',
      timeout: const Duration(milliseconds: 500),
      interval: const Duration(milliseconds: 200),
    );
    if (!onSearchPage) return false;
    final initialCartCount = await _readCartBadgeCount();

    final openSheetResult = await controller.runJavaScriptReturningResult('''
      (function() {
        function isVisible(element) {
          if (!element) return false;
          var style = window.getComputedStyle(element);
          if (style.display === 'none' || style.visibility === 'hidden') return false;
          var rect = element.getBoundingClientRect();
          return rect.width > 0 && rect.height > 0;
        }

        function normalize(value) {
          return (value || '')
            .replace(/\\s+/g, ' ')
            .replace(/[\\[\\]']/g, '')
            .trim()
            .toLowerCase();
        }

        function clickElement(element) {
          element.focus();
          ['pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click'].forEach(function(type) {
            element.dispatchEvent(new MouseEvent(type, { bubbles: true, cancelable: true, view: window }));
          });
          if (typeof element.click === 'function') {
            element.click();
          }
        }

        var productName = normalize(${jsonEncode(productName)});
        var productLinks = Array.from(document.querySelectorAll('a[href*="/goods/"]'))
          .filter(function(link) { return isVisible(link); });

        var matchedLink = productLinks.find(function(link) {
          var text = normalize(link.textContent || '');
          return text.includes(productName) || productName.includes(text);
        });

        if (!matchedLink) {
          return JSON.stringify({
            error: 'missing_search_product',
            candidates: productLinks.slice(0, 8).map(function(link) {
              return normalize(link.textContent || '').slice(0, 80);
            })
          });
        }

        var card = matchedLink.closest('li, article, section, div') || matchedLink.parentElement;
        var depth = 0;
        while (card && depth < 6) {
          var buttons = Array.from(card.querySelectorAll('button, a, [role="button"]')).filter(function(element) {
            if (!isVisible(element)) return false;
            var text = normalize((element.textContent || '') + ' ' + (element.getAttribute('aria-label') || ''));
            return text === '담기' || text.includes('장바구니');
          });
          if (buttons.length > 0) {
            clickElement(buttons[0]);
            return JSON.stringify({
              clicked: normalize(buttons[0].textContent || buttons[0].getAttribute('aria-label') || ''),
              matchedProduct: normalize(matchedLink.textContent || '').slice(0, 80)
            });
          }
          card = card.parentElement;
          depth += 1;
        }

        return JSON.stringify({
          error: 'missing_search_card_button',
          matchedProduct: normalize(matchedLink.textContent || '').slice(0, 80)
        });
      })()
    ''');
    _debug('search card click attempt=1 result=$openSheetResult');
    final openSheetResultText = _normalizeJavaScriptString(openSheetResult);
    if (openSheetResultText.contains('missing_search_product')) {
      _lastCartFailureReason = 'search_product_missing';
      return false;
    }
    if (openSheetResultText.contains('missing_search_card_button')) {
      _lastCartFailureReason = 'search_card_button_missing';
      return false;
    }

    final sheetReady = await _waitForJavaScriptCondition(
      '''
      (function() {
        function isVisible(element) {
          if (!element) return false;
          var style = window.getComputedStyle(element);
          if (style.display === 'none' || style.visibility === 'hidden') return false;
          var rect = element.getBoundingClientRect();
          return rect.width > 0 && rect.height > 0;
        }

        function normalize(value) {
          return (value || '')
            .replace(/\\s+/g, ' ')
            .replace(/[\\[\\]']/g, '')
            .trim()
            .toLowerCase();
        }

        var productName = normalize(${jsonEncode(productName)});
        var sections = Array.from(document.querySelectorAll('div, section, article')).filter(function(element) {
          if (!isVisible(element)) return false;
          var text = normalize(element.textContent || '');
          return text.includes(productName) && text.includes('장바구니 담기');
        });
        return sections.length > 0;
      })()
      ''',
      timeout: const Duration(seconds: 5),
      interval: const Duration(milliseconds: 250),
    );
    if (!sheetReady) {
      final handledByDirectAdd = await _handleDirectSearchAddFlow(
        productName: productName,
        quantity: quantity,
        initialCartCount: initialCartCount,
      );
      if (handledByDirectAdd) {
        _lastCartFailureReason = null;
        return true;
      }
      _lastCartFailureReason = 'search_sheet_not_ready_after_add';
      final snapshot = await _cartDebugSnapshot();
      _debug('search bottom sheet not ready snapshot=$snapshot');
      return false;
    }

    if (quantity > 1) {
      for (var i = 1; i < quantity; i++) {
        final quantityResult = await controller.runJavaScriptReturningResult('''
          (function() {
            function isVisible(element) {
              if (!element) return false;
              var style = window.getComputedStyle(element);
              if (style.display === 'none' || style.visibility === 'hidden') return false;
              var rect = element.getBoundingClientRect();
              return rect.width > 0 && rect.height > 0;
            }

            function normalize(value) {
              return (value || '')
                .replace(/\\s+/g, ' ')
                .replace(/[\\[\\]']/g, '')
                .trim()
                .toLowerCase();
            }

            function clickElement(element) {
              element.focus();
              ['pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click'].forEach(function(type) {
                element.dispatchEvent(new MouseEvent(type, { bubbles: true, cancelable: true, view: window }));
              });
              if (typeof element.click === 'function') {
                element.click();
              }
            }

            var productName = normalize(${jsonEncode(productName)});
            var sheet = Array.from(document.querySelectorAll('div, section, article')).find(function(element) {
              if (!isVisible(element)) return false;
              var text = normalize(element.textContent || '');
              return text.includes(productName) && text.includes('장바구니 담기');
            });
            if (!sheet) return 'missing_sheet';

            var buttons = Array.from(sheet.querySelectorAll('button, [role="button"]')).filter(function(element) {
              if (!isVisible(element)) return false;
              var text = normalize(element.textContent || '');
              var label = normalize(element.getAttribute('aria-label') || '');
              return !(text.includes('장바구니 담기') || label.includes('장바구니 담기'));
            });
            var plusBtn = buttons.find(function(element) {
              var text = normalize(element.textContent || '');
              var label = normalize(element.getAttribute('aria-label') || '');
              return text === '+' ||
                label.includes('수량 증가') ||
                label.includes('increase') ||
                label.includes('plus');
            });
            if (!plusBtn) {
              var quantityRow = buttons
                .map(function(element) {
                  var rect = element.getBoundingClientRect();
                  var text = normalize(element.textContent || '');
                  var label = normalize(element.getAttribute('aria-label') || '');
                  var parentText = normalize((element.parentElement && element.parentElement.textContent) || '');
                  return {
                    element: element,
                    rect: rect,
                    text: text,
                    label: label,
                    parentText: parentText,
                  };
                })
                .filter(function(item) {
                  if (item.rect.width <= 0 || item.rect.height <= 0) return false;
                  if (item.text.includes('앱 열기') || item.label.includes('앱 열기')) return false;
                  return /\\d+/.test(item.parentText) ||
                    item.parentText.includes('-') ||
                    item.parentText.includes('+');
                })
                .sort(function(a, b) {
                  if (Math.abs(a.rect.top - b.rect.top) > 12) {
                    return b.rect.top - a.rect.top;
                  }
                  return b.rect.right - a.rect.right;
                });
              if (quantityRow.length > 0) {
                plusBtn = quantityRow[0].element;
              }
            }
            if (!plusBtn) {
              var debugButtons = buttons.map(function(element) {
                var rect = element.getBoundingClientRect();
                return {
                  text: normalize(element.textContent || ''),
                  label: normalize(element.getAttribute('aria-label') || ''),
                  cls: element.className || '',
                  left: Math.round(rect.left),
                  top: Math.round(rect.top),
                  width: Math.round(rect.width),
                  height: Math.round(rect.height),
                  parentText: normalize((element.parentElement && element.parentElement.textContent) || '').slice(0, 80),
                };
              });
              return JSON.stringify({ error: 'missing_plus', buttons: debugButtons });
            }
            clickElement(plusBtn);
            return JSON.stringify({
              clicked_plus: normalize(plusBtn.textContent || plusBtn.getAttribute('aria-label') || ''),
            });
          })()
        ''');
        _debug('search sheet quantity increment attempt=${i + 1} result=$quantityResult');
        final quantityResultText = _normalizeJavaScriptString(quantityResult);
        if (quantityResultText.contains('missing_plus') ||
            quantityResultText.contains('missing_sheet')) {
          _lastCartFailureReason = 'search_quantity_adjust_failed';
          return false;
        }
        await Future.delayed(const Duration(milliseconds: 300));
      }
    }

    final confirmResult = await controller.runJavaScriptReturningResult('''
      (function() {
        function isVisible(element) {
          if (!element) return false;
          var style = window.getComputedStyle(element);
          if (style.display === 'none' || style.visibility === 'hidden') return false;
          var rect = element.getBoundingClientRect();
          return rect.width > 0 && rect.height > 0;
        }

        function normalize(value) {
          return (value || '')
            .replace(/\\s+/g, ' ')
            .replace(/[\\[\\]']/g, '')
            .trim()
            .toLowerCase();
        }

        function clickElement(element) {
          element.focus();
          ['pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click'].forEach(function(type) {
            element.dispatchEvent(new MouseEvent(type, { bubbles: true, cancelable: true, view: window }));
          });
          if (typeof element.click === 'function') {
            element.click();
          }
        }

        var productName = normalize(${jsonEncode(productName)});
        var sheet = Array.from(document.querySelectorAll('div, section, article')).find(function(element) {
          if (!isVisible(element)) return false;
          var text = normalize(element.textContent || '');
          return text.includes(productName) && text.includes('장바구니 담기');
        });
        if (!sheet) return JSON.stringify({ error: 'missing_sheet' });

        var confirmBtn = Array.from(sheet.querySelectorAll('button, [role="button"], a')).find(function(element) {
          if (!isVisible(element)) return false;
          var text = normalize((element.textContent || '') + ' ' + (element.getAttribute('aria-label') || ''));
          return text.includes('장바구니 담기');
        });
        if (!confirmBtn) {
          return JSON.stringify({
            error: 'missing_confirm_button',
            buttons: Array.from(sheet.querySelectorAll('button, [role="button"], a')).map(function(element) {
              return normalize((element.textContent || '') + ' ' + (element.getAttribute('aria-label') || '')).slice(0, 80);
            }).slice(0, 10)
          });
        }
        clickElement(confirmBtn);
        return JSON.stringify({
          clicked: normalize(confirmBtn.textContent || confirmBtn.getAttribute('aria-label') || '')
        });
      })()
    ''');
    _debug('search sheet confirm result=$confirmResult');
    final confirmResultText = _normalizeJavaScriptString(confirmResult);
    if (confirmResultText.contains('missing_sheet') ||
        confirmResultText.contains('missing_confirm_button')) {
      _lastCartFailureReason = 'search_confirm_button_missing';
      return false;
    }

    await Future.delayed(const Duration(seconds: 2));

    final result = await controller.runJavaScriptReturningResult('''
      (function() {
        function normalize(value) {
          return (value || '')
            .replace(/\\s+/g, ' ')
            .replace(/[\\[\\]']/g, '')
            .trim()
            .toLowerCase();
        }

        function includesProduct(text, productName) {
          var normalizedText = normalize(text);
          var normalizedProductName = normalize(productName);
          if (!normalizedText || !normalizedProductName) return false;
          return normalizedText.includes(normalizedProductName);
        }

        var productName = ${jsonEncode(productName)};
        var bodyText = document.body ? (document.body.innerText || '') : '';
        var toast = document.querySelector('[class*="toast"], [class*="Toast"], [role="alert"]');
        if (toast && includesProduct(toast.textContent, productName) && normalize(toast.textContent).includes('담')) {
          return true;
        }
        var modal = document.querySelector('[role="dialog"], [class*="modal"], [class*="Modal"]');
        if (modal && includesProduct(modal.textContent, productName) && normalize(modal.textContent).includes('장바구니')) {
          return true;
        }
        if (includesProduct(bodyText, productName) && normalize(bodyText).includes('담기')) {
          return true;
        }
        return false;
      })()
    ''');

    final success = result.toString() == 'true';
    if (!success) {
      _lastCartFailureReason = 'search_cart_verification_inconclusive';
      final snapshot = await _cartDebugSnapshot();
      _debug('search page cart verification failed snapshot=$snapshot');
    }
    return success;
  }

  Future<bool> _handleDirectSearchAddFlow({
    required String productName,
    required int quantity,
    required int? initialCartCount,
  }) async {
    await Future.delayed(const Duration(milliseconds: 900));

    final currentCartCount = await _readCartBadgeCount();
    final directAddConfirmed =
        initialCartCount != null &&
        currentCartCount != null &&
        currentCartCount > initialCartCount;

    if (!directAddConfirmed) {
      return false;
    }

    _debug(
      'search direct add confirmed initialCartCount=$initialCartCount currentCartCount=$currentCartCount',
    );

    if (quantity <= 1) {
      return true;
    }

    var expectedCartCount = currentCartCount;
    for (var i = 1; i < quantity; i++) {
      final clicked = await _clickSearchResultAddButton(productName);
      if (!clicked) {
        _lastCartFailureReason = 'search_direct_add_repeat_click_failed';
        return false;
      }
      await Future.delayed(const Duration(milliseconds: 900));
      final nextCartCount = await _readCartBadgeCount();
      _debug(
        'search direct add repeat attempt=${i + 1} nextCartCount=$nextCartCount expected>$expectedCartCount',
      );
      if (nextCartCount == null || nextCartCount <= expectedCartCount) {
        _lastCartFailureReason = 'search_direct_add_repeat_unverified';
        return false;
      }
      expectedCartCount = nextCartCount;
    }

    return true;
  }

  Future<bool> _clickSearchResultAddButton(String productName) async {
    try {
      final result = await controller.runJavaScriptReturningResult('''
        (function() {
          function isVisible(element) {
            if (!element) return false;
            var style = window.getComputedStyle(element);
            if (style.display === 'none' || style.visibility === 'hidden') return false;
            var rect = element.getBoundingClientRect();
            return rect.width > 0 && rect.height > 0;
          }

          function normalize(value) {
            return (value || '')
              .replace(/\\s+/g, ' ')
              .replace(/[\\[\\]']/g, '')
              .trim()
              .toLowerCase();
          }

          function clickElement(element) {
            element.focus();
            ['pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click'].forEach(function(type) {
              element.dispatchEvent(new MouseEvent(type, { bubbles: true, cancelable: true, view: window }));
            });
            if (typeof element.click === 'function') {
              element.click();
            }
          }

          var targetName = normalize(${jsonEncode(productName)});
          var productLinks = Array.from(document.querySelectorAll('a[href*="/goods/"]'))
            .filter(function(link) { return isVisible(link); });
          var matchedLink = productLinks.find(function(link) {
            var text = normalize(link.textContent || '');
            return text.includes(targetName) || targetName.includes(text);
          });
          if (!matchedLink) return 'missing_search_product';

          var card = matchedLink.closest('li, article, section, div') || matchedLink.parentElement;
          var depth = 0;
          while (card && depth < 6) {
            var buttons = Array.from(card.querySelectorAll('button, a, [role="button"]')).filter(function(element) {
              if (!isVisible(element)) return false;
              var text = normalize((element.textContent || '') + ' ' + (element.getAttribute('aria-label') || ''));
              return text === '담기' || text.includes('장바구니');
            });
            if (buttons.length > 0) {
              clickElement(buttons[0]);
              return 'clicked';
            }
            card = card.parentElement;
            depth += 1;
          }
          return 'missing_search_card_button';
        })()
      ''');
      return _normalizeJavaScriptString(result).contains('clicked');
    } catch (_) {
      return false;
    }
  }

  Future<int?> _readCartBadgeCount() async {
    try {
      final result = await controller.runJavaScriptReturningResult('''
        (function() {
          function isVisible(element) {
            if (!element) return false;
            var style = window.getComputedStyle(element);
            if (style.display === 'none' || style.visibility === 'hidden') return false;
            var rect = element.getBoundingClientRect();
            return rect.width > 0 && rect.height > 0;
          }

          function extractCount(text) {
            var matches = (text || '').match(/\\d+/g);
            if (!matches || matches.length === 0) return null;
            var values = matches
              .map(function(value) { return parseInt(value, 10); })
              .filter(function(value) { return !isNaN(value) && value >= 0 && value < 1000; });
            if (values.length === 0) return null;
            return Math.max.apply(null, values);
          }

          var selectors = [
            'a[href*="/cart"]',
            'a[href*="cart"]',
            'button[aria-label*="장바구니"]',
            'a[aria-label*="장바구니"]',
            '[data-testid*="cart"]',
            '[class*="cart"]'
          ];

          var candidates = Array.from(document.querySelectorAll(selectors.join(','))).filter(isVisible);
          for (var i = 0; i < candidates.length; i++) {
            var element = candidates[i];
            var texts = [
              element.textContent || '',
              element.getAttribute('aria-label') || '',
              element.getAttribute('title') || ''
            ];
            var count = extractCount(texts.join(' '));
            if (count != null) return String(count);

            var descendants = Array.from(element.querySelectorAll('*')).slice(0, 12);
            for (var j = 0; j < descendants.length; j++) {
              var childCount = extractCount(
                (descendants[j].textContent || '') + ' ' + (descendants[j].getAttribute('aria-label') || ''),
              );
              if (childCount != null) return String(childCount);
            }
          }

          return 'null';
        })()
      ''');
      final text = _normalizeJavaScriptString(result).trim();
      return int.tryParse(text);
    } catch (_) {
      return null;
    }
  }

  bool _isUnsafeCartRetryReason(String? reason) {
    switch (reason) {
      case 'search_sheet_not_ready_after_add':
      case 'search_quantity_adjust_failed':
      case 'search_confirm_button_missing':
      case 'search_cart_verification_inconclusive':
      case 'search_direct_add_repeat_unverified':
      case 'product_quantity_adjust_failed':
      case 'product_cart_verification_inconclusive':
        return true;
      default:
        return false;
    }
  }

  String _normalizeJavaScriptString(Object? value) {
    var text = value?.toString() ?? '';
    if (text == 'null' || text == 'undefined') return '';

    // WebView의 runJavaScriptReturningResult는 플랫폼에 따라
    // JSON 문자열을 한 번 더 따옴표로 감싸거나 이스케이프해서 돌려준다.
    // 여기서 최대 두 번만 풀어 클릭 결과 JSON을 안정적으로 읽는다.
    for (var decodeCount = 0; decodeCount < 2; decodeCount += 1) {
      final trimmedText = text.trim();
      if (trimmedText.length < 2 ||
          !trimmedText.startsWith('"') ||
          !trimmedText.endsWith('"')) {
        break;
      }
      try {
        final decoded = jsonDecode(trimmedText);
        if (decoded is! String) {
          return decoded.toString();
        }
        text = decoded;
      } catch (_) {
        return trimmedText.substring(1, trimmedText.length - 1);
      }
    }
    return text;
  }

  bool _cartClickLooksSuccessful(Object? clickResult) {
    final text = _normalizeJavaScriptString(clickResult);
    if (text.isEmpty || text.contains('missing_cart_button')) return false;
    try {
      final decoded = jsonDecode(text);
      if (decoded is Map<String, dynamic>) {
        final clicked = decoded['clicked']?.toString() ?? '';
        final candidates = decoded['candidates'];
        final candidateText = candidates is List
            ? candidates.map((value) => value.toString()).join(' ')
            : candidates?.toString() ?? '';
        final combined = '$clicked $candidateText';
        return combined.contains('장바구니 담기') || combined.contains('담기');
      }
    } catch (_) {
      // 아래 문자열 fallback으로 한 번 더 확인한다.
    }
    final clickedCartAction =
        text.contains('clicked') &&
        (text.contains('장바구니 담기') || text.contains('담기'));
    final hasCartCandidate =
        text.contains('candidates') &&
        (text.contains('장바구니 담기') || text.contains('담기'));
    return clickedCartAction || hasCartCandidate;
  }

  String? _pickInitialTargetUrl({
    required String productName,
    String? canonicalProductUrl,
    String? executionUrl,
  }) {
    if (_isKurlyGoodsUrl(canonicalProductUrl)) {
      return canonicalProductUrl;
    }
    final normalizedProductName = productName.trim();
    if (normalizedProductName.isNotEmpty) {
      return 'https://www.kurly.com/search?sword=${Uri.encodeQueryComponent(normalizedProductName)}';
    }
    if (executionUrl != null && executionUrl.trim().isNotEmpty) {
      return executionUrl.trim();
    }
    return null;
  }

  bool _isKurlyGoodsUrl(String? url) {
    if (url == null) return false;
    final normalized = url.trim();
    return normalized.contains('kurly.com/goods/');
  }

  Future<String> _safePageSnapshot() async {
    try {
      final result = await controller.runJavaScriptReturningResult('''
        (function() {
          var bodyText = document.body ? (document.body.innerText || '') : '';
          return JSON.stringify({
            href: location.href,
            title: document.title,
            bodyPreview: bodyText.replace(/\\s+/g, ' ').trim().slice(0, 160)
          });
        })()
      ''');
      return _normalizeJavaScriptString(result);
    } catch (_) {
      return 'snapshot_unavailable';
    }
  }

  Future<String> _cartDebugSnapshot() async {
    try {
      final result = await controller.runJavaScriptReturningResult('''
        (function() {
          function summarize(elements) {
            return Array.from(elements).slice(0, 8).map(function(element) {
              return {
                tag: element.tagName,
                text: (element.textContent || '').replace(/\\s+/g, ' ').trim().slice(0, 40),
                aria: (element.getAttribute('aria-label') || '').trim(),
                cls: (element.className || '').toString().slice(0, 80)
              };
            });
          }

          return JSON.stringify({
            href: location.href,
            title: document.title,
            bodyPreview: ((document.body ? document.body.innerText : '') || '').replace(/\\s+/g, ' ').trim().slice(0, 200),
            buttons: summarize(document.querySelectorAll('button, a, [role="button"]')),
            quantityControls: summarize(document.querySelectorAll('button[aria-label*="수량"], button[class*="plus"], [data-testid*="quantity"]'))
          });
        })()
      ''');
      return _normalizeJavaScriptString(result);
    } catch (_) {
      return 'cart_snapshot_unavailable';
    }
  }
}
