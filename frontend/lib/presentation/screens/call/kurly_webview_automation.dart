import 'package:webview_flutter/webview_flutter.dart';

typedef AutomationProgressCallback = void Function(String step, String message);

class KurlyWebviewAutomation {
  final WebViewController controller;
  final String? kurlyEmail;
  final String? kurlyPassword;
  final AutomationProgressCallback? onProgress;

  KurlyWebviewAutomation({
    required this.controller,
    this.kurlyEmail,
    this.kurlyPassword,
    this.onProgress,
  });

  void _report(String step, String message) {
    onProgress?.call(step, message);
  }

  Future<void> run({
    required String productName,
    required int quantity,
    String? canonicalProductUrl,
    String? executionUrl,
  }) async {
    _report('opening_shop', '컬리 페이지를 열고 있어요.');

    await controller.loadRequest(Uri.parse('https://www.kurly.com'));
    await _waitForPageLoad();

    final isLoggedIn = await _checkLoginState();
    if (!isLoggedIn) {
      _report('logging_in', '로그인이 필요해요. 계정 정보를 입력하고 있어요.');
      final loginSuccess = await _attemptLogin();
      if (!loginSuccess) {
        _report('login_failed', '로그인에 실패했어요. 다시 시도해주세요.');
        return;
      }
      await _waitForPageLoad();
    }

    if (canonicalProductUrl != null && canonicalProductUrl.contains('/goods/')) {
      _report('opening_product', '상품 페이지로 이동하고 있어요.');
      await controller.loadRequest(Uri.parse(canonicalProductUrl));
      await _waitForPageLoad();
    } else {
      _report('searching_product', '상품을 검색하고 있어요.');
      await _searchProduct(productName);
      await _waitForPageLoad();
    }

    _report('adding_to_cart', '장바구니에 담고 있어요.');
    final cartSuccess = await _addToCart(quantity: quantity);
    if (cartSuccess) {
      _report('cart_added', '장바구니에 담았어요!');
    } else {
      _report('cart_failed', '장바구니 담기에 실패했어요.');
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
          var myBtn = document.querySelector('a[href*="/mypage"]');
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
    if (kurlyEmail == null || kurlyPassword == null) return false;

    try {
      await controller.loadRequest(Uri.parse('https://www.kurly.com/member/login'));
      await _waitForPageLoad();
      await Future.delayed(const Duration(milliseconds: 500));

      final safeEmail = kurlyEmail!.replaceAll("'", "\\'");
      final safePassword = kurlyPassword!.replaceAll("'", "\\'");

      await controller.runJavaScript('''
        (function() {
          var emailInput = document.querySelector('input[name="id"], input[type="email"], input[placeholder*="아이디"]');
          var pwInput = document.querySelector('input[name="password"], input[type="password"]');
          if (!emailInput || !pwInput) return;

          var nativeInputValueSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
          nativeInputValueSetter.call(emailInput, '$safeEmail');
          emailInput.dispatchEvent(new Event('input', { bubbles: true }));
          nativeInputValueSetter.call(pwInput, '$safePassword');
          pwInput.dispatchEvent(new Event('input', { bubbles: true }));
        })()
      ''');

      await Future.delayed(const Duration(milliseconds: 400));

      await controller.runJavaScript('''
        (function() {
          var submitBtn = document.querySelector('button[type="submit"], button[data-testid="login-submit"], .btn-login');
          if (submitBtn) {
            submitBtn.click();
          } else {
            var form = document.querySelector('form');
            if (form) form.submit();
          }
        })()
      ''');

      await Future.delayed(const Duration(seconds: 3));
      return await _checkLoginState();
    } catch (_) {
      return false;
    }
  }

  Future<void> _searchProduct(String productName) async {
    final safeQuery = Uri.encodeComponent(productName);
    await controller.loadRequest(
      Uri.parse('https://www.kurly.com/search?sword=$safeQuery'),
    );
    await _waitForPageLoad();
    await Future.delayed(const Duration(milliseconds: 500));

    // 첫 번째 상품 클릭
    await controller.runJavaScript('''
      (function() {
        var productLinks = document.querySelectorAll('a[href*="/goods/"]');
        if (productLinks.length > 0) productLinks[0].click();
      })()
    ''');
    await _waitForPageLoad();
  }

  Future<bool> _addToCart({required int quantity}) async {
    try {
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
            'button[data-testid="cart-button"], button[class*="cart"], button[aria-label*="장바구니"]'
          );
          if (!cartBtn) {
            var allBtns = Array.from(document.querySelectorAll('button'));
            cartBtn = allBtns.find(function(b) {
              return b.textContent && b.textContent.trim().includes('장바구니');
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
}
