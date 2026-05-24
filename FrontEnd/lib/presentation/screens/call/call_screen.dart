//통화 화면
//전화 끊기 버튼이 항상 고정되고, stage에 따라 가운데 콘텐츠가 바뀌는 구조
import 'dart:async';

import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:provider/provider.dart';
import '../../../presentation/providers/call_provider.dart';
import 'payment_webview_screen.dart';

class CallScreen extends StatefulWidget {
  const CallScreen({super.key});

  @override
  State<CallScreen> createState() => _CallScreenState();
}

class _CallScreenState extends State<CallScreen> {
  static const double _titleFontSize = 18;
  static const double _bodyFontSize = 19;
  static const double _supportFontSize = 15;
  static const double _buttonFontSize = 18;

  final TextEditingController _textController = TextEditingController();
  final ScrollController _messageScrollController = ScrollController();
  CallProvider? _provider;
  Timer? _callTimer;
  DateTime? _callStartedAt;
  String _pinInput = '';
  bool _isMicPressed = false;
  bool _isMicHovered = false;
  bool _isEndCallHovered = false;
  bool _showTextInput = false;
  int _lastMessageCount = 0;
  bool _isWebviewOpen = false;
  String? _lastWebviewCommandKey;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) return;
      _provider = context.read<CallProvider>();
      _lastMessageCount = _provider!.messages.length;
      _provider!.addListener(_handleProviderChanged);
    });

    // 전화 시작 시 첫 메시지 전송
    WidgetsBinding.instance.addPostFrameCallback((_) {
      context.read<CallProvider>().startCall();
    });
  }

  @override
  void dispose() {
    _provider?.removeListener(_handleProviderChanged);
    _callTimer?.cancel();
    _textController.dispose();
    _messageScrollController.dispose();
    super.dispose();
  }

  void _handleProviderChanged() {
    if (!mounted) return;

    final provider = _provider;
    if (provider == null) return;

    if (provider.conversationId != null) {
      _startCallTimerIfNeeded();
    } else {
      _stopCallTimer();
    }

    if (!_isPasswordInputMode(provider)) {
      if (_pinInput.isNotEmpty) {
        setState(() {
          _pinInput = '';
        });
      }
    } else if (_showTextInput) {
      setState(() {
        _showTextInput = false;
      });
    }

    _handleWebviewCommand(provider);

    final messageCount = provider.messages.length;
    if (messageCount <= _lastMessageCount) return;

    _lastMessageCount = messageCount;
    _scrollMessagesToBottom();
  }

  void _handleWebviewCommand(CallProvider provider) {
    final webviewUrl = provider.webviewUrl;
    final orderId = provider.currentOrderId;
    final paymentId = provider.currentPaymentId;
    if (webviewUrl == null || orderId == null || paymentId == null) return;

    final commandKey = '$webviewUrl|$orderId|$paymentId';
    if (_isWebviewOpen || _lastWebviewCommandKey == commandKey) return;

    _isWebviewOpen = true;
    _lastWebviewCommandKey = commandKey;

    WidgetsBinding.instance.addPostFrameCallback((_) async {
      if (!mounted) return;
      await Navigator.of(context).push(
        MaterialPageRoute<void>(
          builder: (_) => PaymentWebViewScreen(
            url: webviewUrl,
            orderId: orderId,
            paymentId: paymentId,
          ),
        ),
      );
      _isWebviewOpen = false;
      if (mounted && provider.webviewUrl != webviewUrl) {
        _lastWebviewCommandKey = null;
      }
    });
  }

  void _scrollMessagesToBottom() {
    WidgetsBinding.instance.addPostFrameCallback((_) async {
      if (!mounted || !_messageScrollController.hasClients) return;

      final target = _messageScrollController.position.maxScrollExtent;
      await _messageScrollController.animateTo(
        target,
        duration: const Duration(milliseconds: 320),
        curve: Curves.easeOutCubic,
      );
    });
  }

  void _startCallTimerIfNeeded() {
    if (_callStartedAt != null) return;

    setState(() {
      _callStartedAt = DateTime.now();
    });

    _callTimer = Timer.periodic(const Duration(seconds: 1), (timer) {
      if (!mounted || _callStartedAt == null) return;
      setState(() {});
    });
  }

  void _stopCallTimer() {
    _callTimer?.cancel();
    _callTimer = null;
    if (_callStartedAt != null) {
      setState(() {
        _callStartedAt = null;
      });
    }
  }

  String _formattedCallDuration() {
    final startedAt = _callStartedAt;
    if (startedAt == null) return '00분:00초';

    final elapsed = DateTime.now().difference(startedAt);
    final minutes = elapsed.inMinutes.remainder(60).toString().padLeft(2, '0');
    final seconds = elapsed.inSeconds.remainder(60).toString().padLeft(2, '0');
    return '$minutes분:$seconds초';
  }

  void _endCall() {
    context.read<CallProvider>().endCall();
    context.go('/home');
  }

  void _handleTextSubmit() {
    if (_textController.text.isEmpty) return;
    context.read<CallProvider>().sendTextMessage(_textController.text);
    _textController.clear();
    setState(() {
      _showTextInput = false;
    });
  }

  bool _isPasswordInputMode(CallProvider provider) =>
      provider.stage == CallStage.payment &&
      (provider.lastResponse?.assistantMessage.contains('비밀번호') ?? false);

  void _appendPinDigit(String digit) {
    if (_pinInput.length >= 6) return;
    setState(() {
      _pinInput = '$_pinInput$digit';
    });
  }

  void _removePinDigit() {
    if (_pinInput.isEmpty) return;
    setState(() {
      _pinInput = _pinInput.substring(0, _pinInput.length - 1);
    });
  }

  void _submitPin() {
    if (_pinInput.length != 6) return;
    context.read<CallProvider>().submitPaymentPassword(_pinInput);
    setState(() {
      _pinInput = '';
    });
  }

  void _handleMicTap(CallProvider provider) {
    debugPrint(
      '🎤 [Mic Tap] canUseVoice=${provider.canUseVoice}, '
      'isListening=${provider.isListening}, '
      'isSpeaking=${provider.isSpeaking}, '
      'isLoading=${provider.isLoading}, '
      'isTranscribing=${provider.isTranscribing}',
    );
    provider.toggleListening();
  }

  void _handleMicTapDown(CallProvider provider) {
    if (!(provider.canUseVoice || provider.isListening)) return;
    setState(() {
      _isMicPressed = true;
    });
  }

  void _handleMicTapEnd() {
    if (!_isMicPressed) return;
    setState(() {
      _isMicPressed = false;
    });
  }

  void _handleMicHover(bool isHovered) {
    if (_isMicHovered == isHovered) return;
    setState(() {
      _isMicHovered = isHovered;
    });
  }

  void _handleEndCallHover(bool isHovered) {
    if (_isEndCallHovered == isHovered) return;
    setState(() {
      _isEndCallHovered = isHovered;
    });
  }

  void _toggleTextInput() {
    setState(() {
      _showTextInput = !_showTextInput;
    });
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFFFDF0F3),
      body: SafeArea(
        child: Column(
          children: [
            // ── 상단 헤더 (항상 고정) ──
            _buildHeader(),

            // ── 가운데 콘텐츠 (stage에 따라 변경) ──
            Expanded(
              child: Consumer<CallProvider>(
                builder: (context, provider, _) {
                  return _buildContent(provider);
                },
              ),
            ),

            // ── 하단 전화 끊기 버튼 (항상 고정) ──
            _buildEndCallButton(),
          ],
        ),
      ),
    );
  }

  // 상단 헤더
  Widget _buildHeader() {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 16),
      child: Column(
        children: [
          Image.asset(
            'assets/images/ddalangoo_logo_text.png',
            height: 60,
            fit: BoxFit.contain,
          ),
          const SizedBox(height: 4),
          Consumer<CallProvider>(
            builder: (context, provider, _) {
              final isConnected = provider.conversationId != null;
              return Row(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  Text(
                    isConnected ? '통화 중' : '연결 중...',
                    style: TextStyle(
                      fontSize: isConnected ? 14 : _supportFontSize,
                      color: const Color(0xFF4CAF50),
                      fontWeight: isConnected
                          ? FontWeight.w700
                          : FontWeight.w500,
                    ),
                  ),
                  if (isConnected) ...[
                    const SizedBox(width: 10),
                    Text(
                      _formattedCallDuration(),
                      style: const TextStyle(
                        fontSize: 14,
                        color: Color(0xFF4CAF50),
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                  ],
                ],
              );
            },
          ),
        ],
      ),
    );
  }

  // stage에 따라 콘텐츠 변경
  Widget _buildContent(CallProvider provider) {
    switch (provider.stage) {
      case CallStage.loading:
        return _buildLoadingContent(provider);
      default:
        return _buildChatContent(provider);
    }
  }

  // 채팅 말풍선 화면 (의도파악, 플랫폼선택, 상품선택, 결제 등)
  Widget _buildChatContent(CallProvider provider) {
    return Column(
      children: [
        // 말풍선 목록
        Expanded(
          child: ListView.builder(
            controller: _messageScrollController,
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
            itemCount: provider.messages.length,
            itemBuilder: (context, index) {
              final message = provider.messages[index];
              return _buildMessageBubble(
                text: message['text'],
                isUser: message['isUser'],
              );
            },
          ),
        ),

        // 상품 추천 카드 (상품 선택 단계)
        if (provider.stage == CallStage.productSelection &&
            provider.lastResponse?.recommendations.isNotEmpty == true)
          _buildProductCard(provider),

        // 주소 확인 (결제 단계에서 deliveryAddress가 있을 때)
        if (provider.stage == CallStage.payment &&
            provider.lastResponse?.deliveryAddress != null)
          _buildAddressConfirmation(provider),

        // 장바구니 (장바구니 단계)
        if (provider.stage == CallStage.cart) _buildCartSummary(provider),

        // 로딩 인디케이터
        if (provider.isLoading)
          const Padding(
            padding: EdgeInsets.symmetric(vertical: 12),
            child: CircularProgressIndicator(color: Color(0xFFE8325A)),
          ),
      ],
    );
  }

  // 비동기 로딩 화면
  Widget _buildLoadingContent(CallProvider provider) {
    // asyncStatus에서 메시지 파싱
    final asyncStatus = provider.lastResponse?.asyncStatus;
    String loadingText = '잠시 기다려주세요';
    if (asyncStatus is Map && asyncStatus['message'] != null) {
      loadingText = asyncStatus['message'];
    }

    return Center(
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          const CircularProgressIndicator(
            color: Color(0xFFE8325A),
            strokeWidth: 3,
          ),
          const SizedBox(height: 24),
          Text(
            loadingText,
            style: const TextStyle(
              fontSize: _titleFontSize,
              color: Color(0xFFE8325A),
              fontWeight: FontWeight.w500,
            ),
          ),
          const SizedBox(height: 8),
          const Text(
            '잠시 기다려주세요',
            style: TextStyle(
              fontSize: _supportFontSize,
              color: Color(0xFF888888),
            ),
          ),
        ],
      ),
    );
  }

  // 데모용 텍스트 입력 필드
  Widget _buildDemoTextInput() {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
      child: Row(
        children: [
          Expanded(
            child: TextField(
              controller: _textController,
              decoration: InputDecoration(
                hintText: '메시지를 입력하세요 (데모에만 표시됩니다)',
                hintStyle: const TextStyle(
                  fontSize: _bodyFontSize,
                  color: Color(0xFF777777),
                ),
                fillColor: Colors.white,
                filled: true,
                border: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(20),
                  borderSide: const BorderSide(
                    color: Color(0xFFE8325A),
                    width: 1.6,
                  ),
                ),
                enabledBorder: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(20),
                  borderSide: const BorderSide(
                    color: Color(0xFFE8325A),
                    width: 1.6,
                  ),
                ),
                focusedBorder: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(20),
                  borderSide: const BorderSide(
                    color: Color(0xFFE8325A),
                    width: 2.0,
                  ),
                ),
              ),
              style: const TextStyle(
                fontSize: _bodyFontSize,
                color: Color(0xFF333333),
              ),
              onSubmitted: (_) => _handleTextSubmit(),
            ),
          ),
          IconButton(
            onPressed: _handleTextSubmit,
            icon: const Icon(Icons.send, color: Color(0xFFE8325A)),
          ),
        ],
      ),
    );
  }

  Widget _buildPinPad() {
    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 8, 16, 8),
      child: Container(
        padding: const EdgeInsets.all(16),
        decoration: BoxDecoration(
          color: Colors.white,
          borderRadius: BorderRadius.circular(24),
          border: Border.all(
            color: const Color(0xFFE8325A).withValues(alpha: 0.2),
          ),
          boxShadow: [
            BoxShadow(
              color: Colors.black.withValues(alpha: 0.06),
              blurRadius: 14,
              offset: const Offset(0, 6),
            ),
          ],
        ),
        child: Column(
          children: [
            const Text(
              '결제 비밀번호 입력',
              style: TextStyle(
                fontSize: _supportFontSize,
                fontWeight: FontWeight.w700,
                color: Color(0xFFE8325A),
              ),
            ),
            const SizedBox(height: 14),
            Row(
              mainAxisAlignment: MainAxisAlignment.center,
              children: List.generate(6, (index) {
                final isFilled = index < _pinInput.length;
                return Container(
                  width: 18,
                  height: 18,
                  margin: const EdgeInsets.symmetric(horizontal: 6),
                  decoration: BoxDecoration(
                    color: isFilled
                        ? const Color(0xFFE8325A)
                        : const Color(0xFFF7D9E1),
                    shape: BoxShape.circle,
                  ),
                );
              }),
            ),
            const SizedBox(height: 16),
            for (final row in const [
              ['1', '2', '3'],
              ['4', '5', '6'],
              ['7', '8', '9'],
              ['지우기', '0', '확인'],
            ])
              Padding(
                padding: const EdgeInsets.only(bottom: 10),
                child: Row(
                  children: row
                      .map(
                        (value) => Expanded(
                          child: Padding(
                            padding: const EdgeInsets.symmetric(horizontal: 6),
                            child: _buildPinPadKey(value),
                          ),
                        ),
                      )
                      .toList(),
                ),
              ),
          ],
        ),
      ),
    );
  }

  Widget _buildPinPadKey(String value) {
    final isAction = value == '지우기' || value == '확인';
    final isSubmit = value == '확인';
    final isEnabled = value != '확인' || _pinInput.length == 6;

    return SizedBox(
      height: 56,
      child: ElevatedButton(
        onPressed: !isEnabled
            ? null
            : () {
                if (value == '지우기') {
                  _removePinDigit();
                  return;
                }
                if (value == '확인') {
                  _submitPin();
                  return;
                }
                _appendPinDigit(value);
              },
        style: ElevatedButton.styleFrom(
          elevation: 0,
          backgroundColor: isSubmit
              ? const Color(0xFFE8325A)
              : isAction
              ? const Color(0xFFFCE4EA)
              : const Color(0xFFF7F7F7),
          foregroundColor: isSubmit ? Colors.white : const Color(0xFF333333),
          disabledBackgroundColor: const Color(0xFFF3C8D4),
          disabledForegroundColor: Colors.white,
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(18),
          ),
          textStyle: TextStyle(
            fontSize: value.length == 1 ? _bodyFontSize : _supportFontSize,
            fontWeight: FontWeight.w700,
          ),
        ),
        child: value == '지우기'
            ? const Icon(Icons.backspace_outlined, size: 22)
            : Text(value),
      ),
    );
  }

  Widget _buildProductImage(String? imageUrl, {double size = 80}) {
    final placeholder = Container(
      width: size,
      height: size,
      decoration: BoxDecoration(
        color: const Color(0xFFFCE4EA),
        borderRadius: BorderRadius.circular(8),
      ),
      child: const Icon(
        Icons.image_outlined,
        color: Color(0xFFE8325A),
        size: 28,
      ),
    );

    if (imageUrl == null || imageUrl.isEmpty) return placeholder;

    return ClipRRect(
      borderRadius: BorderRadius.circular(8),
      child: Image.network(
        imageUrl,
        width: size,
        height: size,
        fit: BoxFit.cover,
        errorBuilder: (context, error, stackTrace) => placeholder,
      ),
    );
  }

  String? _resolveProductImageUrl(CallProvider provider) {
    final selectedProduct = provider.lastResponse?.selectedProduct;
    if (selectedProduct is! Map) return null;

    // 백엔드는 추천 목록에는 imageUrl=null, 선택 상품에는 image_url을 내려줄 수 있다.
    // 화면 카드는 추천 목록을 기준으로 그리므로 선택 상품 이미지가 있으면 보조값으로 사용한다.
    final selectedImageUrl =
        selectedProduct['imageUrl'] ?? selectedProduct['image_url'];
    return selectedImageUrl is String && selectedImageUrl.isNotEmpty
        ? selectedImageUrl
        : null;
  }

  Widget _buildTextInputToggle() {
    return OutlinedButton.icon(
      onPressed: _toggleTextInput,
      icon: Icon(_showTextInput ? Icons.keyboard_hide : Icons.keyboard),
      label: Text(_showTextInput ? '텍스트 입력 닫기' : '텍스트 입력하기'),
      style: OutlinedButton.styleFrom(
        foregroundColor: const Color(0xFFE8325A),
        side: const BorderSide(color: Color(0xFFE8325A)),
        padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 12),
        textStyle: const TextStyle(
          fontSize: _supportFontSize,
          fontWeight: FontWeight.w600,
        ),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(18)),
      ),
    );
  }

  // 말풍선
  Widget _buildMessageBubble({required String text, required bool isUser}) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Row(
        mainAxisAlignment: isUser
            ? MainAxisAlignment.end
            : MainAxisAlignment.start,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Flexible(
            child: Column(
              crossAxisAlignment: isUser
                  ? CrossAxisAlignment.end
                  : CrossAxisAlignment.start,
              children: [
                if (!isUser)
                  Padding(
                    padding: const EdgeInsets.only(left: 6, bottom: 8),
                    child: Image.asset(
                      'assets/images/ddalangoo_logo_image.png',
                      height: 150,
                      fit: BoxFit.contain,
                    ),
                  ),
                Container(
                  padding: const EdgeInsets.symmetric(
                    horizontal: 16,
                    vertical: 10,
                  ),
                  decoration: BoxDecoration(
                    color: const Color(0xFFFFFFFF),
                    borderRadius: BorderRadius.only(
                      topLeft: const Radius.circular(16),
                      topRight: const Radius.circular(16),
                      bottomLeft: Radius.circular(isUser ? 16 : 4),
                      bottomRight: Radius.circular(isUser ? 4 : 16),
                    ),
                    border: Border.all(
                      color: const Color(0xFFE8325A),
                      width: 1.5,
                    ),
                    boxShadow: [
                      BoxShadow(
                        color: Colors.black.withValues(alpha: 0.05),
                        blurRadius: 4,
                        offset: const Offset(0, 2),
                      ),
                    ],
                  ),
                  child: Text(
                    text,
                    style: TextStyle(
                      fontSize: _bodyFontSize,
                      color: const Color(0xFF333333),
                      height: 1.4,
                      fontWeight: isUser ? FontWeight.w500 : FontWeight.w700,
                    ),
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  // 상품 추천 카드
  Widget _buildProductCard(CallProvider provider) {
    final item = provider.lastResponse!.recommendations.first;
    final imageUrl = item.imageUrl ?? _resolveProductImageUrl(provider);
    return Container(
      margin: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(16),
        boxShadow: [
          BoxShadow(
            color: Colors.black.withValues(alpha: 0.08),
            blurRadius: 8,
            offset: const Offset(0, 2),
          ),
        ],
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // 플랫폼 뱃지
          if (item.platform != null)
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
              decoration: BoxDecoration(
                color: const Color(0xFF4CAF50),
                borderRadius: BorderRadius.circular(8),
              ),
              child: Text(
                item.platform!,
                style: const TextStyle(color: Colors.white, fontSize: 12),
              ),
            ),
          const SizedBox(height: 8),

          // 상품명
          Text(
            item.productName,
            style: const TextStyle(fontSize: 16, fontWeight: FontWeight.bold),
          ),
          const SizedBox(height: 4),

          // 추천 사유 (과거 이력 등)
          if (item.reason != null)
            Padding(
              padding: const EdgeInsets.only(bottom: 8),
              child: Text(
                '💡 ${item.reason!}',
                style: TextStyle(
                  fontSize: 13,
                  color: Colors.blueGrey[700],
                  fontStyle: FontStyle.italic,
                ),
              ),
            ),

          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              _buildProductImage(imageUrl),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    if (item.brand != null)
                      Text(
                        item.brand!,
                        style: const TextStyle(
                          fontSize: 12,
                          color: Colors.grey,
                        ),
                      ),
                    Text(
                      item.productName,
                      style: const TextStyle(
                        fontSize: 16,
                        fontWeight: FontWeight.bold,
                      ),
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                    ),
                    const SizedBox(height: 4),
                    if (item.rating != null)
                      Row(
                        children: [
                          const Icon(
                            Icons.star,
                            size: 14,
                            color: Colors.orange,
                          ),
                          Text(
                            ' ${item.rating} (${item.reviewCount ?? 0})',
                            style: const TextStyle(fontSize: 12),
                          ),
                        ],
                      ),
                  ],
                ),
              ),
            ],
          ),
          const SizedBox(height: 12),

          // 가격
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Expanded(
                child: Text(
                  '${item.price.toString().replaceAllMapped(RegExp(r'(\d{1,3})(?=(\d{3})+(?!\d))'), (m) => '${m[1]},')}원',
                  style: const TextStyle(
                    fontSize: 20,
                    fontWeight: FontWeight.bold,
                    color: Color(0xFFE8325A),
                  ),
                ),
              ),
              if (item.deliveryInfo != null) const SizedBox(width: 12),
              if (item.deliveryInfo != null)
                Flexible(
                  child: Text(
                    item.deliveryInfo!,
                    textAlign: TextAlign.right,
                    softWrap: true,
                    style: const TextStyle(
                      fontSize: 12,
                      color: Colors.green,
                      fontWeight: FontWeight.bold,
                    ),
                  ),
                ),
            ],
          ),
        ],
      ),
    );
  }

  // 주소 확인 카드
  Widget _buildAddressConfirmation(CallProvider provider) {
    final addr = provider.lastResponse!.deliveryAddress as Map;
    return Container(
      margin: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(
          color: const Color(0xFFE8325A).withValues(alpha: 0.3),
        ),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Row(
            children: [
              Icon(Icons.location_on, size: 18, color: Color(0xFFE8325A)),
              SizedBox(width: 4),
              Text(
                '배송지 확인',
                style: TextStyle(fontSize: 16, fontWeight: FontWeight.bold),
              ),
            ],
          ),
          const SizedBox(height: 12),
          Text(
            '${addr['recipientName']} (${addr['recipientPhone']})',
            style: const TextStyle(fontWeight: FontWeight.w500),
          ),
          const SizedBox(height: 4),
          Text(
            addr['address'] ?? '',
            style: const TextStyle(fontSize: 14, color: Color(0xFF555555)),
          ),
          if (addr['deliveryRequest'] != null) ...[
            const SizedBox(height: 8),
            Text(
              '요청사항: ${addr['deliveryRequest']}',
              style: const TextStyle(fontSize: 13, color: Colors.blueGrey),
            ),
          ],
        ],
      ),
    );
  }

  // 장바구니 요약
  Widget _buildCartSummary(CallProvider provider) {
    final order = provider.lastResponse?.order;
    if (order == null) return const SizedBox.shrink();

    return Container(
      margin: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(16),
        boxShadow: [
          BoxShadow(
            color: Colors.black.withValues(alpha: 0.08),
            blurRadius: 8,
            offset: const Offset(0, 2),
          ),
        ],
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text(
            '장바구니',
            style: TextStyle(fontSize: 16, fontWeight: FontWeight.bold),
          ),
          const SizedBox(height: 8),
          const Divider(),
          // order 데이터는 dynamic이라 Map으로 캐스팅
          if (order is Map && order['items'] != null)
            ...((order['items'] as List).map(
              (item) => Padding(
                padding: const EdgeInsets.symmetric(vertical: 4),
                child: Row(
                  children: [
                    if (item['imageUrl'] != null)
                      ClipRRect(
                        borderRadius: BorderRadius.circular(4),
                        child: Image.network(
                          item['imageUrl'],
                          width: 40,
                          height: 40,
                          fit: BoxFit.cover,
                        ),
                      ),
                    const SizedBox(width: 8),
                    Expanded(
                      child: Text(
                        item['productName'] ?? '',
                        style: const TextStyle(fontSize: 14),
                      ),
                    ),
                    Column(
                      crossAxisAlignment: CrossAxisAlignment.end,
                      children: [
                        Text(
                          '${item['quantity']}개',
                          style: const TextStyle(
                            fontSize: 12,
                            color: Colors.grey,
                          ),
                        ),
                        Text(
                          '${item['totalPrice']}원',
                          style: const TextStyle(
                            color: Color(0xFFE8325A),
                            fontWeight: FontWeight.bold,
                          ),
                        ),
                      ],
                    ),
                  ],
                ),
              ),
            )),
          const Divider(),
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              const Text('총 금액', style: TextStyle(fontWeight: FontWeight.bold)),
              Text(
                '${order['totalPaymentAmount'] ?? 0}원',
                style: const TextStyle(
                  fontSize: 18,
                  fontWeight: FontWeight.bold,
                  color: Color(0xFFE8325A),
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }

  Color _micButtonColor(CallProvider provider) {
    if (_isMicPressed && provider.isListening) {
      return const Color(0xFFE53935);
    }
    if (_isMicPressed) {
      return const Color(0xFF4CAF50);
    }
    if (_isMicHovered && !provider.isListening && provider.canUseVoice) {
      return const Color(0xFFE7F6EA);
    }
    if (provider.isListening) {
      return const Color(0xFF4CAF50);
    }
    if (provider.canUseVoice) {
      return const Color(0xFFEEEEEE);
    }
    return const Color(0xFFF5D9E0);
  }

  Color _micIconColor(CallProvider provider) {
    if (_isMicPressed || provider.isListening) {
      return Colors.white;
    }
    if (_isMicHovered && provider.canUseVoice) {
      return const Color(0xFF4CAF50);
    }
    if (provider.canUseVoice) {
      return const Color(0xFFE8325A);
    }
    return const Color(0xFFE8325A);
  }

  IconData _micIcon(CallProvider provider) {
    if (provider.isTranscribing) return Icons.hourglass_top;
    if (_isMicPressed && provider.isListening) return Icons.stop_rounded;
    if (_isMicPressed || provider.isListening) return Icons.graphic_eq;
    return Icons.mic_none;
  }

  // 하단 버튼 영역 (말하기 + 전화 끊기)
  Widget _buildEndCallButton() {
    return Consumer<CallProvider>(
      builder: (context, provider, _) {
        return Padding(
          padding: const EdgeInsets.fromLTRB(20, 0, 20, 28),
          child: Column(
            children: [
              // 말하기 버튼 (통화 중일 때만 표시)
              if (provider.stage != CallStage.loading &&
                  provider.stage != CallStage.completed) ...[
                MouseRegion(
                  cursor: (provider.canUseVoice || provider.isListening)
                      ? SystemMouseCursors.click
                      : SystemMouseCursors.basic,
                  onEnter: (_) => _handleMicHover(true),
                  onExit: (_) => _handleMicHover(false),
                  child: GestureDetector(
                    behavior: HitTestBehavior.opaque,
                    onTapDown: (provider.canUseVoice || provider.isListening)
                        ? (_) => _handleMicTapDown(provider)
                        : null,
                    onTapCancel: _handleMicTapEnd,
                    onTapUp: (_) => _handleMicTapEnd(),
                    onTap: (provider.canUseVoice || provider.isListening)
                        ? () => _handleMicTap(provider)
                        : null,
                    child: Container(
                      width: 88,
                      height: 88,
                      decoration: BoxDecoration(
                        color: _micButtonColor(provider),
                        shape: BoxShape.circle,
                        border: provider.isListening
                            ? Border.all(
                                color: _isMicPressed
                                    ? const Color(0xFFE53935)
                                    : const Color(0xFF4CAF50),
                                width: 3,
                              )
                            : _isMicHovered && provider.canUseVoice
                            ? Border.all(
                                color: const Color(0xFF4CAF50),
                                width: 2,
                              )
                            : null,
                        boxShadow: provider.isListening
                            ? [
                                BoxShadow(
                                  color: const Color(
                                    0xFF4CAF50,
                                  ).withValues(alpha: 0.28),
                                  blurRadius: 16,
                                  spreadRadius: 2,
                                ),
                              ]
                            : _isMicHovered && provider.canUseVoice
                            ? [
                                BoxShadow(
                                  color: const Color(
                                    0xFF4CAF50,
                                  ).withValues(alpha: 0.16),
                                  blurRadius: 12,
                                  spreadRadius: 1,
                                ),
                              ]
                            : null,
                      ),
                      child: Icon(
                        _micIcon(provider),
                        color: _micIconColor(provider),
                        size: 34,
                      ),
                    ),
                  ),
                ),
                const SizedBox(height: 12),
                const SizedBox(height: 8),
                Text(
                  provider.voiceStatusLabel,
                  style: TextStyle(
                    fontSize: _supportFontSize,
                    color: provider.isListening
                        ? const Color(0xFF4CAF50)
                        : provider.canUseVoice
                        ? const Color(0xFF888888)
                        : const Color(0xFFE8325A),
                  ),
                  textAlign: TextAlign.center,
                ),
                if (provider.errorMessage != null) ...[
                  const SizedBox(height: 8),
                  Text(
                    provider.errorMessage!,
                    style: const TextStyle(
                      fontSize: _supportFontSize,
                      color: Color(0xFFC62828),
                    ),
                    textAlign: TextAlign.center,
                  ),
                ],
                const SizedBox(height: 18),
                if (!provider.isLoading) ...[
                  if (_isPasswordInputMode(provider)) ...[
                    _buildPinPad(),
                  ] else ...[
                    _buildTextInputToggle(),
                  ],
                  if (_showTextInput && !_isPasswordInputMode(provider)) ...[
                    const SizedBox(height: 12),
                    _buildDemoTextInput(),
                  ],
                  const SizedBox(height: 24),
                ],
              ],

              // 전화 끊기 버튼
              MouseRegion(
                cursor: SystemMouseCursors.click,
                onEnter: (_) => _handleEndCallHover(true),
                onExit: (_) => _handleEndCallHover(false),
                child: GestureDetector(
                  onTap: _endCall,
                  child: Container(
                    width: double.infinity,
                    height: 64,
                    padding: const EdgeInsets.symmetric(horizontal: 24),
                    decoration: BoxDecoration(
                      color: _isEndCallHovered
                          ? const Color(0xFFE8325A)
                          : const Color(0xFFD9D9D9),
                      borderRadius: BorderRadius.circular(24),
                      boxShadow: _isEndCallHovered
                          ? [
                              BoxShadow(
                                color: const Color(
                                  0xFFE8325A,
                                ).withValues(alpha: 0.28),
                                blurRadius: 18,
                                offset: const Offset(0, 8),
                              ),
                            ]
                          : null,
                    ),
                    child: Row(
                      mainAxisAlignment: MainAxisAlignment.center,
                      children: [
                        Icon(
                          Icons.call_end,
                          color: _isEndCallHovered
                              ? Colors.white
                              : const Color(0xFF666666),
                          size: 24,
                        ),
                        const SizedBox(width: 10),
                        Text(
                          '전화 끊기',
                          style: TextStyle(
                            fontSize: _buttonFontSize,
                            color: _isEndCallHovered
                                ? Colors.white
                                : const Color(0xFF666666),
                            fontWeight: FontWeight.w700,
                          ),
                        ),
                      ],
                    ),
                  ),
                ),
              ),
            ],
          ),
        );
      },
    );
  }
}
