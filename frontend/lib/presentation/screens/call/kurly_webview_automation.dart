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

    final targetUrl = canonicalProductUrl ?? executionUrl ?? 'https://www.kurly.com';
    _debug('run start targetUrl=$targetUrl, canonicalProductUrl=$canonicalProductUrl, quantity=$quantity');
    await controller.loadRequest(Uri.parse(targetUrl));

    await _waitForPageLoad();
    await _dismissAlreadyLoggedInDialogIfNeeded();

    final isLoggedIn = await _checkLoginState();
    _debug('initial login state=$isLoggedIn');
    if (!isLoggedIn) {
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
      await controller.loadRequest(Uri.parse(canonicalProductUrl));
      await _waitForPageLoad();
    } else {
      _report('searching_product', '상품을 검색하고 있어요.');
      final opened = await _searchProduct(productName);
      _debug('search/open product result=$opened');
      if (!opened) {
        _report('cart_failed', '상품 페이지를 찾지 못했어요.');
        return 'cart_failed';
      }
    }

    _report('adding_to_cart', '장바구니에 담고 있어요.');
    final cartSuccess = await _addToCart(quantity: quantity);
    _debug('add to cart result=$cartSuccess');
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
          var loginBtn = document.querySelector('a[href*="/member/login"]');
          var myBtn = document.querySelector('a[href*="/mypage"], a[href*="/member/mypage"], a[href*="/mykurly"]');
          var headerLogin = document.querySelector('.header-login');
          var logoutEl = document.querySelector('a[href*="logout"], button[data-testid="logout"]');
          if (logoutEl) return true;
          if (myBtn) return true;
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
      await _dismissAlreadyLoggedInDialogIfNeeded();

      if (await _checkLoginState()) {
        _debug('already logged in after opening login page');
        return true;
      }

      await _openIdLoginTabIfNeeded();

      final formVisible = await _waitForJavaScriptCondition(
        '''
        (function() {
          var emailInput = document.querySelector('input[name="id"], input[type="email"], input[placeholder*="아이디"]');
          var pwInput = document.querySelector('input[name="password"], input[type="password"]');
          return !!emailInput && !!pwInput;
        })()
        ''',
      );
      if (!formVisible) {
        _debug('login form not visible');
        return false;
      }

      final safeId = _escapeForJavaScript(credentials.id);
      final safePassword = _escapeForJavaScript(credentials.password);

      await controller.runJavaScript('''
        (function() {
          var emailInput = document.querySelector('input[name="id"], input[type="email"], input[placeholder*="아이디"]');
          var pwInput = document.querySelector('input[name="password"], input[type="password"]');
          if (!emailInput || !pwInput) return;

          var nativeInputValueSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
          nativeInputValueSetter.call(emailInput, '$safeId');
          emailInput.dispatchEvent(new Event('input', { bubbles: true }));
          emailInput.dispatchEvent(new Event('change', { bubbles: true }));
          emailInput.dispatchEvent(new Event('blur', { bubbles: true }));
          nativeInputValueSetter.call(pwInput, '$safePassword');
          pwInput.dispatchEvent(new Event('input', { bubbles: true }));
          pwInput.dispatchEvent(new Event('change', { bubbles: true }));
          pwInput.dispatchEvent(new Event('blur', { bubbles: true }));
        })()
      ''');

      await Future.delayed(const Duration(milliseconds: 700));
      await _dismissAlreadyLoggedInDialogIfNeeded();

      await controller.runJavaScript('''
        (function() {
          var submitBtn = document.querySelector('button[type="submit"], button[data-testid="login-submit"], .btn-login, button[class*="login"]');
          if (!submitBtn) {
            var allButtons = Array.from(document.querySelectorAll('button'));
            submitBtn = allButtons.find(function(button) {
              var text = (button.textContent || '').trim();
              return text === '로그인' || text.includes('로그인');
            });
          }
          if (submitBtn) {
            submitBtn.click();
          } else {
            var form = document.querySelector('form');
            if (form) form.submit();
          }
        })()
      ''');

      await Future.delayed(const Duration(milliseconds: 800));
      await _dismissAlreadyLoggedInDialogIfNeeded();

      final loginSucceeded = await _waitForLoginSuccess();
      _debug('login success detector result=$loginSucceeded');
      return loginSucceeded || await _checkLoginState();
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
          return text.includes('아이디 로그인') || text.includes('이메일 로그인');
        });
        if (idLoginButton) {
          idLoginButton.click();
        }
      })()
    ''');
    await Future.delayed(const Duration(milliseconds: 600));
  }

  Future<void> _dismissAlreadyLoggedInDialogIfNeeded() async {
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
      }
    } catch (_) {}
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
    await controller.loadRequest(
      Uri.parse('https://www.kurly.com/search?sword=$safeQuery'),
    );
    await _waitForPageLoad();
    final productOpened = await _waitForJavaScriptCondition(
      '''
      (function() {
        return document.querySelectorAll('a[href*="/goods/"]').length > 0;
      })()
      ''',
      timeout: const Duration(seconds: 8),
      interval: const Duration(milliseconds: 400),
    );
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
    if (href.isEmpty) return false;

    final targetHref = href.startsWith('http') ? href : 'https://www.kurly.com$href';
    await controller.loadRequest(Uri.parse(targetHref));
    await _waitForPageLoad();
    return true;
  }

  Future<bool> _addToCart({required int quantity}) async {
    try {
      final cartButtonReady = await _waitForJavaScriptCondition(
        '''
        (function() {
          var direct = document.querySelector(
            'button[data-testid="cart-button"], button[class*="cart"], button[aria-label*="장바구니"]'
          );
          if (direct) return true;
          var allBtns = Array.from(document.querySelectorAll('button'));
          return allBtns.some(function(button) {
            var text = (button.textContent || '').trim();
            return text.includes('장바구니') || text.includes('담기');
          });
        })()
        ''',
        timeout: const Duration(seconds: 8),
        interval: const Duration(milliseconds: 400),
      );
      if (!cartButtonReady) {
        _debug('cart button not ready');
        return false;
      }

      // 수량 설정
      if (quantity > 1) {
        for (var i = 1; i < quantity; i++) {
          await controller.runJavaScript('''
            (function() {
              var plusBtn = document.querySelector(
                'button[aria-label="수량 증가"], button[class*="plus"], [data-testid="quantity-plus"]'
              );
              if (plusBtn) plusBtn.click();
            })()
          ''');
          await Future.delayed(const Duration(milliseconds: 300));
        }
      }

      // 장바구니 담기 버튼 클릭
      await controller.runJavaScript('''
        (function() {
          var cartBtn = document.querySelector(
            'button[data-testid="cart-button"], button[class*="cart"], button[aria-label*="장바구니"], button[aria-label*="담기"]'
          );
          if (!cartBtn) {
            var allBtns = Array.from(document.querySelectorAll('button'));
            cartBtn = allBtns.find(function(b) {
              var text = b.textContent ? b.textContent.trim() : '';
              return text.includes('장바구니') || text.includes('담기');
            });
          }
          if (cartBtn) cartBtn.click();
        })()
      ''');

      await Future.delayed(const Duration(seconds: 2));

      // 담기 성공 여부 확인 (toast, modal, cart count 변화)
      final result = await controller.runJavaScriptReturningResult('''
        (function() {
          var toast = document.querySelector('[class*="toast"], [class*="Toast"], [role="alert"]');
          if (toast && toast.textContent && toast.textContent.includes('담')) return true;
          var cartCount = document.querySelector('[class*="cart-count"], [data-testid="cart-count"]');
          if (cartCount && parseInt(cartCount.textContent) > 0) return true;
          return false;
        })()
      ''');

      return result.toString() == 'true';
    } catch (_) {
      return false;
    }
  }

  String _normalizeJavaScriptString(Object? value) {
    final text = value?.toString() ?? '';
    if (text == 'null' || text == 'undefined') return '';
    if (text.length >= 2 && text.startsWith('"') && text.endsWith('"')) {
      return text.substring(1, text.length - 1);
    }
    return text;
  }
}
