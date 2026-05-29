//통화 화면
//전화 끊기 버튼이 항상 고정되고, stage에 따라 가운데 콘텐츠가 바뀌는 구조
import 'dart:async';

import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:provider/provider.dart';
import '../../../data/models/agent_model.dart';
import '../../../presentation/providers/call_provider.dart';
import 'payment_webview_screen.dart';

class CallScreen extends StatefulWidget {
  const CallScreen({
    super.key,
    this.previewMode = false,
    this.autoStart = true,
  });

  final bool previewMode;
  final bool autoStart;

  @override
  State<CallScreen> createState() => _CallScreenState();
}

class _CallScreenState extends State<CallScreen> {
  static const double _bodyFontSize = 22;
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
  bool _hasStartedVoiceInteraction = false;
  bool _isProductCardExpanded = false;
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
      if (!widget.autoStart) return;
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

    if (!widget.previewMode) {
      _handleWebviewCommand(provider);
    }

    final messageCount = provider.messages.length;
    if (messageCount <= _lastMessageCount) return;

    _lastMessageCount = messageCount;
    _scrollMessagesToBottom();
  }

  void _handleWebviewCommand(CallProvider provider) {
    final payload = provider.webviewTaskPayload;
    if (payload == null) {
      return;
    }
    debugPrint(
      '🪟 [CallScreen WebView Check] '
      'stage=${provider.stage.name}, '
      'url=${provider.webviewUrl}, '
      'orderId=${provider.currentOrderId}, '
      'paymentId=${provider.currentPaymentId}, '
      'productName=${provider.currentWebviewProductName}, '
      'quantity=${provider.currentWebviewQuantity}',
    );
    final commandKey =
        'pending|${provider.conversationId}|${provider.currentOrderId}|${provider.currentPaymentId}';
    _openWebview(
      provider,
      commandKey: commandKey,
      url: provider.webviewUrl,
    );
  }

  void _openWebview(
    CallProvider provider, {
    required String commandKey,
    required String url,
  }) {
    if (_isWebviewOpen || _lastWebviewCommandKey == commandKey) {
      debugPrint(
        '🪟 [CallScreen WebView Check] already handled. '
        '_isWebviewOpen=$_isWebviewOpen, commandKey=$commandKey',
      );
      return;
    }

    _isWebviewOpen = true;
    _lastWebviewCommandKey = commandKey;
    debugPrint(
      '🪟 [CallScreen WebView Open] commandKey=$commandKey, '
      'url=$url, '
      'canonicalProductUrl=${provider.currentCanonicalProductUrl}',
    );

    WidgetsBinding.instance.addPostFrameCallback((_) async {
      if (!mounted) return;
      await Navigator.of(context).push(
        MaterialPageRoute<void>(
          builder: (_) => PaymentWebViewScreen(
            url: url,
            orderId: provider.currentOrderId,
            paymentId: provider.currentPaymentId,
            productName: provider.currentWebviewProductName,
            quantity: provider.currentWebviewQuantity,
            canonicalProductUrl: provider.currentCanonicalProductUrl,
            task: provider.currentWebviewTask,
          ),
        ),
      );
      debugPrint('🪟 [CallScreen WebView Close] commandKey=$commandKey');
      _isWebviewOpen = false;
      if (mounted && _lastWebviewCommandKey == commandKey) {
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
    if (widget.previewMode) {
      Navigator.of(context).maybePop();
      return;
    }
    context.go('/home');
  }

  void _handleTextSubmit() {
    if (widget.previewMode || _textController.text.isEmpty) return;
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
    if (widget.previewMode || _pinInput.length != 6) return;
    context.read<CallProvider>().submitPaymentPassword(_pinInput);
    setState(() {
      _pinInput = '';
    });
  }

  void _handleMicTap(CallProvider provider) {
    if (widget.previewMode) return;
    if (!_hasStartedVoiceInteraction) {
      setState(() {
        _hasStartedVoiceInteraction = true;
      });
    }
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
      padding: const EdgeInsets.fromLTRB(16, 4, 16, 2),
      child: Consumer<CallProvider>(
        builder: (context, provider, _) {
          final isConnected = provider.conversationId != null;
          return Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Row(
                crossAxisAlignment: CrossAxisAlignment.center,
                children: [
                  Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      SizedBox(
                        width: 50,
                        height: 50,
                        child: Image.asset(
                          'assets/images/ddalangoo_logo_image.png',
                          fit: BoxFit.contain,
                        ),
                      ),
                      const SizedBox(width: 1),
                      Image.asset(
                        'assets/images/ddalangoo_logo_text.png',
                        height: 28,
                        fit: BoxFit.contain,
                      ),
                    ],
                  ),
                  const Spacer(),
                  Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Text(
                        isConnected ? '통화 중' : '연결 중...',
                        style: TextStyle(
                          fontSize: 14,
                          color: const Color(0xFF4CAF50),
                          fontWeight: isConnected
                              ? FontWeight.w800
                              : FontWeight.w600,
                        ),
                      ),
                      if (isConnected) ...[
                        const SizedBox(width: 8),
                        Text(
                          _formattedCallDuration(),
                          style: const TextStyle(
                            fontSize: 14,
                            color: Color(0xFF4CAF50),
                            fontWeight: FontWeight.w700,
                          ),
                        ),
                      ],
                    ],
                  ),
                ],
              ),
              const SizedBox(height: 4),
              Container(
                width: double.infinity,
                height: 1,
                color: const Color(0xFFEFD8DF),
              ),
            ],
          );
        },
      ),
    );
  }

  // stage에 따라 콘텐츠 변경
  Widget _buildContent(CallProvider provider) {
    return _buildChatContent(provider);
  }

  // 채팅 말풍선 화면 (의도파악, 플랫폼선택, 상품선택, 결제 등)
  Widget _buildChatContent(CallProvider provider) {
    final hasAddressCard =
        provider.stage == CallStage.payment &&
        provider.lastResponse?.deliveryAddress != null;
    final hasCartSummary = provider.stage == CallStage.cart;
    final shouldShowAssistantLoadingBubble =
        provider.isAwaitingAssistantPresentation ||
        (provider.isLoading &&
            provider.messages.isNotEmpty &&
            provider.messages.last['isUser'] == true);

    return LayoutBuilder(
      builder: (context, constraints) {
        return Column(
          children: [
            // 말풍선 목록
            Expanded(
              child: ListView(
                controller: _messageScrollController,
                padding: const EdgeInsets.symmetric(
                  horizontal: 16,
                  vertical: 8,
                ),
                children: [
                  for (var index = 0; index < provider.messages.length; index++)
                    _buildConversationItem(provider.messages[index], index),
                  if (shouldShowAssistantLoadingBubble)
                    Padding(
                      padding: const EdgeInsets.only(top: 4, bottom: 8),
                      child: _buildAssistantLoadingBubble(provider),
                    ),
                  if (hasAddressCard)
                    Padding(
                      padding: const EdgeInsets.only(top: 8, bottom: 8),
                      child: _buildAddressConfirmation(provider),
                    ),
                  if (hasCartSummary)
                    Padding(
                      padding: const EdgeInsets.only(top: 8, bottom: 8),
                      child: _buildCartSummary(provider),
                    ),
                ],
              ),
            ),
          ],
        );
      },
    );
  }

  Widget _buildConversationItem(Map<String, dynamic> message, int index) {
    final type = message['type'] as String?;
    if (type == 'product_card') {
      return Padding(
        padding: const EdgeInsets.only(top: 8, bottom: 8),
        child: _buildProductCardFromMessage(
          recommendation: message['recommendation'] as RecommendationItemInAgent,
          selectedProduct: message['selectedProduct'],
        ),
      );
    }

    final isUser = message['isUser'] as bool? ?? false;
    return _buildMessageBubble(
      text: message['text'],
      isUser: isUser,
      showHeroAvatar: !isUser && index == 0,
    );
  }

  Widget _buildAssistantLoadingBubble(CallProvider provider) {
    final loadingText = provider.assistantLoadingMessage;

    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Flexible(
          child: Container(
            padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 16),
            decoration: BoxDecoration(
              color: const Color(0xFFFFFFFF),
              borderRadius: const BorderRadius.only(
                topLeft: Radius.circular(16),
                topRight: Radius.circular(16),
                bottomLeft: Radius.circular(4),
                bottomRight: Radius.circular(16),
              ),
              border: Border.all(color: const Color(0xFFE8325A), width: 1.5),
              boxShadow: [
                BoxShadow(
                  color: Colors.black.withValues(alpha: 0.05),
                  blurRadius: 4,
                  offset: const Offset(0, 2),
                ),
              ],
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Container(
                      width: 28,
                      height: 28,
                      padding: const EdgeInsets.all(5),
                      decoration: BoxDecoration(
                        color: const Color(0xFFFFEEF3),
                        borderRadius: BorderRadius.circular(10),
                      ),
                      child: Image.asset(
                        'assets/images/ddalangoo_logo_image.png',
                        fit: BoxFit.contain,
                      ),
                    ),
                    const SizedBox(width: 10),
                    const SizedBox(
                      width: 18,
                      height: 18,
                      child: CircularProgressIndicator(
                        color: Color(0xFFE8325A),
                        strokeWidth: 2.4,
                      ),
                    ),
                    const SizedBox(width: 10),
                    Expanded(
                      child: Text(
                        loadingText,
                        style: const TextStyle(
                          fontSize: _bodyFontSize,
                          color: Color(0xFF333333),
                          height: 1.45,
                          fontWeight: FontWeight.w700,
                        ),
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 10),
                const Padding(
                  padding: EdgeInsets.only(left: 48),
                  child: Text(
                    '딸랑구가 음성으로 차근차근 설명드릴게요.',
                    style: TextStyle(
                      fontSize: _supportFontSize,
                      color: Color(0xFF888888),
                      height: 1.45,
                    ),
                  ),
                ),
              ],
            ),
          ),
        ),
      ],
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
        color: const Color(0xFFFFF1F4),
        borderRadius: BorderRadius.circular(20),
        border: Border.all(color: const Color(0xFFF6C9D6)),
      ),
      child: const Icon(
        Icons.image_outlined,
        color: Color(0xFFE8325A),
        size: 32,
      ),
    );

    if (imageUrl == null || imageUrl.isEmpty) return placeholder;

    return ClipRRect(
      borderRadius: BorderRadius.circular(20),
      child: Container(
        decoration: BoxDecoration(
          border: Border.all(color: const Color(0xFFF3CBD7)),
          borderRadius: BorderRadius.circular(20),
        ),
        child: Image.network(
          imageUrl,
          width: size,
          height: size,
          fit: BoxFit.cover,
          errorBuilder: (context, error, stackTrace) => placeholder,
        ),
      ),
    );
  }

  String? _resolveProductImageUrl(dynamic selectedProduct) {
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
      icon: Icon(_showTextInput ? Icons.keyboard_hide : Icons.keyboard, size: 18),
      label: Text(_showTextInput ? '텍스트 닫기' : '텍스트 입력'),
      style: OutlinedButton.styleFrom(
        foregroundColor: const Color(0xFFE8325A),
        side: const BorderSide(color: Color(0xFFE8325A)),
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
        textStyle: const TextStyle(
          fontSize: 14,
          fontWeight: FontWeight.w600,
        ),
        minimumSize: const Size(0, 44),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
      ),
    );
  }

  // 말풍선
  Widget _buildMessageBubble({
    required String text,
    required bool isUser,
    bool showHeroAvatar = false,
  }) {
    final messageTextStyle = TextStyle(
      fontSize: _bodyFontSize,
      color: const Color(0xFF333333),
      height: 1.5,
      fontWeight: isUser ? FontWeight.w500 : FontWeight.w700,
    );

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
                  if (showHeroAvatar)
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
                    horizontal: 18,
                    vertical: 14,
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
                  child: Row(
                    mainAxisSize: MainAxisSize.min,
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      if (!isUser && !showHeroAvatar) ...[
                        Container(
                          width: 24,
                          height: 24,
                          padding: const EdgeInsets.all(4),
                          decoration: BoxDecoration(
                            color: const Color(0xFFFFEEF3),
                            borderRadius: BorderRadius.circular(8),
                          ),
                          child: Image.asset(
                            'assets/images/ddalangoo_logo_image.png',
                            fit: BoxFit.contain,
                          ),
                        ),
                        const SizedBox(width: 10),
                      ],
                      Flexible(
                        child: isUser
                            ? Text(text, style: messageTextStyle)
                            : RichText(
                                text: TextSpan(
                                  style: messageTextStyle,
                                  children: _buildAssistantMessageSpans(
                                    text,
                                    messageTextStyle,
                                  ),
                                ),
                              ),
                      ),
                    ],
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildCollapsedProductSummary({
    required String title,
    required String priceText,
    required String? imageUrl,
  }) {
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        _buildProductImage(imageUrl, size: 96),
        const SizedBox(width: 16),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                title,
                style: const TextStyle(
                  fontSize: 19,
                  fontWeight: FontWeight.w800,
                  color: Color(0xFF222222),
                  height: 1.35,
                ),
                maxLines: 3,
                overflow: TextOverflow.ellipsis,
              ),
              const SizedBox(height: 14),
              Text(
                '$priceText원',
                style: const TextStyle(
                  fontSize: 27,
                  color: Color(0xFFE8325A),
                  fontWeight: FontWeight.w900,
                ),
              ),
            ],
          ),
        ),
      ],
    );
  }

  List<TextSpan> _buildAssistantMessageSpans(
    String text,
    TextStyle baseStyle,
  ) {
    final sentences = _splitAssistantMessage(text);
    final spans = <TextSpan>[];

    for (var i = 0; i < sentences.length; i++) {
      spans.addAll(_buildSentenceHighlightSpans(sentences[i], baseStyle));
      if (i < sentences.length - 1) {
        spans.add(const TextSpan(text: '\n'));
      }
    }

    return spans;
  }

  List<String> _splitAssistantMessage(String text) {
    final normalized = text.replaceAll(RegExp(r'\s+'), ' ').trim();
    if (normalized.isEmpty) return const [''];

    final matches = RegExp(r'[^.!?]+[.!?]?').allMatches(normalized);
    final sentences = matches
        .map((match) => match.group(0)?.trim() ?? '')
        .where((sentence) => sentence.isNotEmpty)
        .toList();

    return sentences.isEmpty ? [normalized] : sentences;
  }

  List<TextSpan> _buildSentenceHighlightSpans(
    String sentence,
    TextStyle baseStyle,
  ) {
    final productQuestionMatch = RegExp(r'^(.*?)(\s*어떠세요\?)$').firstMatch(sentence);
    if (productQuestionMatch != null) {
      final productText = productQuestionMatch.group(1)?.trim() ?? '';
      final suffix = productQuestionMatch.group(2) ?? '';
      if (productText.isNotEmpty) {
        return [
          TextSpan(
            text: productText,
            style: baseStyle.copyWith(fontWeight: FontWeight.w900),
          ),
          TextSpan(text: suffix, style: baseStyle),
        ];
      }
    }

    final pattern = RegExp(
      r'''('[^']+'|"[^"]+"|\[[^\]]+\][^\n.!?]*?(?=(?:\s\d+개|\s가격은|이에요|입니다|어떠세요|\?|\.|,|$))|\d{1,3}(?:,\d{3})*원)''',
    );
    final spans = <TextSpan>[];
    var lastIndex = 0;

    for (final match in pattern.allMatches(sentence)) {
      if (match.start > lastIndex) {
        spans.add(TextSpan(text: sentence.substring(lastIndex, match.start)));
      }

      final matchedText = match.group(0) ?? '';
      final highlightWeight = matchedText.endsWith('원')
          ? FontWeight.w900
          : FontWeight.w800;
      spans.add(
        TextSpan(
          text: matchedText,
          style: baseStyle.copyWith(fontWeight: highlightWeight),
        ),
      );
      lastIndex = match.end;
    }

    if (lastIndex < sentence.length) {
      spans.add(TextSpan(text: sentence.substring(lastIndex)));
    }

    return spans.isEmpty ? [TextSpan(text: sentence, style: baseStyle)] : spans;
  }

  // 상품 추천 카드
  Widget _buildProductCardFromMessage({
    required RecommendationItemInAgent recommendation,
    required dynamic selectedProduct,
  }) {
    final item = recommendation;
    final imageUrl = item.imageUrl ?? _resolveProductImageUrl(selectedProduct);
    final formattedPrice = _formatPrice(item.price);
    final hasBrand = item.brand != null && item.brand!.trim().isNotEmpty;
    return Container(
      margin: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
      padding: const EdgeInsets.all(18),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(24),
        border: Border.all(color: const Color(0xFFF4CFD9)),
        boxShadow: [
          BoxShadow(
            color: const Color(0xFFE8325A).withValues(alpha: 0.08),
            blurRadius: 18,
            offset: const Offset(0, 8),
          ),
        ],
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Container(
                padding: const EdgeInsets.symmetric(
                  horizontal: 10,
                  vertical: 6,
                ),
                decoration: BoxDecoration(
                  color: const Color(0xFFFFEEF3),
                  borderRadius: BorderRadius.circular(999),
                ),
                child: const Text(
                  '딸랑구 추천',
                  style: TextStyle(
                    color: Color(0xFFE8325A),
                    fontSize: 12,
                    fontWeight: FontWeight.w800,
                  ),
                ),
              ),
              const Spacer(),
              if (item.platform != null)
                Container(
                  padding: const EdgeInsets.symmetric(
                    horizontal: 10,
                    vertical: 6,
                  ),
                  decoration: BoxDecoration(
                    color: const Color(0xFFEDF8F0),
                    borderRadius: BorderRadius.circular(999),
                  ),
                  child: Text(
                    item.platform!,
                    style: const TextStyle(
                      color: Color(0xFF2E7D32),
                      fontSize: 12,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                ),
            ],
          ),
          const SizedBox(height: 16),
          InkWell(
            borderRadius: BorderRadius.circular(18),
            onTap: () {
              setState(() {
                _isProductCardExpanded = !_isProductCardExpanded;
              });
            },
            child: Padding(
              padding: const EdgeInsets.only(bottom: 12),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Expanded(
                    child: _isProductCardExpanded
                        ? Text(
                            item.productName,
                            style: const TextStyle(
                              fontSize: 18,
                              fontWeight: FontWeight.w800,
                              color: Color(0xFF222222),
                              height: 1.35,
                            ),
                            maxLines: 3,
                            overflow: TextOverflow.ellipsis,
                          )
                        : _buildCollapsedProductSummary(
                            title: item.productName,
                            priceText: formattedPrice,
                            imageUrl: imageUrl,
                          ),
                  ),
                  const SizedBox(width: 12),
                  Container(
                    width: 34,
                    height: 34,
                    decoration: BoxDecoration(
                      color: const Color(0xFFFFEEF3),
                      borderRadius: BorderRadius.circular(12),
                    ),
                    child: Icon(
                      _isProductCardExpanded
                          ? Icons.keyboard_arrow_up_rounded
                          : Icons.keyboard_arrow_down_rounded,
                      color: const Color(0xFFE8325A),
                    ),
                  ),
                ],
              ),
            ),
          ),

          if (_isProductCardExpanded) ...[
            Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                _buildProductImage(imageUrl, size: 124),
                const SizedBox(width: 16),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      if (hasBrand)
                        Padding(
                          padding: const EdgeInsets.only(bottom: 8),
                          child: RichText(
                            text: TextSpan(
                              style: const TextStyle(
                                fontSize: 13,
                                color: Color(0xFF666666),
                                height: 1.4,
                              ),
                              children: [
                                const TextSpan(
                                  text: '브랜드 ',
                                  style: TextStyle(fontWeight: FontWeight.w700),
                                ),
                                TextSpan(
                                  text: item.brand!,
                                  style: const TextStyle(
                                    fontWeight: FontWeight.w900,
                                    color: Color(0xFF333333),
                                  ),
                                ),
                              ],
                            ),
                          ),
                        ),
                      if (item.reason != null)
                        Container(
                          width: double.infinity,
                          padding: const EdgeInsets.symmetric(
                            horizontal: 10,
                            vertical: 8,
                          ),
                          decoration: BoxDecoration(
                            color: const Color(0xFFFFF5DA),
                            borderRadius: BorderRadius.circular(14),
                          ),
                          child: Text(
                            item.reason!,
                            style: const TextStyle(
                              fontSize: 12,
                              color: Color(0xFF6E5A11),
                              fontWeight: FontWeight.w600,
                              height: 1.4,
                            ),
                            maxLines: 3,
                            overflow: TextOverflow.ellipsis,
                          ),
                        ),
                      if (item.reason != null) const SizedBox(height: 10),
                      Wrap(
                        spacing: 8,
                        runSpacing: 8,
                        children: [
                          if (item.rating != null)
                            _buildInfoChip(
                              icon: Icons.star_rounded,
                              iconColor: const Color(0xFFFF9800),
                              label:
                                  '${item.rating} · 후기 ${item.reviewCount ?? 0}',
                            ),
                          if (item.deliveryInfo != null)
                            _buildInfoChip(
                              icon: Icons.local_shipping_outlined,
                              iconColor: const Color(0xFF2E7D32),
                              label: item.deliveryInfo!,
                            ),
                        ],
                      ),
                    ],
                  ),
                ),
              ],
            ),
            const SizedBox(height: 16),
            Container(
              width: double.infinity,
              padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
              decoration: BoxDecoration(
                color: const Color(0xFFFFF3F6),
                borderRadius: BorderRadius.circular(18),
              ),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.end,
                children: [
                  const Expanded(
                    child: Text(
                      '가격',
                      style: TextStyle(
                        fontSize: 13,
                        color: Color(0xFF7A7A7A),
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                  ),
                  Flexible(
                    child: RichText(
                      textAlign: TextAlign.right,
                      text: TextSpan(
                        children: [
                          TextSpan(
                            text: formattedPrice,
                            style: const TextStyle(
                              fontSize: 26,
                              fontWeight: FontWeight.w900,
                              color: Color(0xFFE8325A),
                              height: 1.0,
                            ),
                          ),
                          const TextSpan(
                            text: '원',
                            style: TextStyle(
                              fontSize: 16,
                              fontWeight: FontWeight.w800,
                              color: Color(0xFFE8325A),
                            ),
                          ),
                        ],
                      ),
                    ),
                  ),
                ],
              ),
            ),
          ],
        ],
      ),
    );
  }

  Widget _buildInfoChip({
    required IconData icon,
    required Color iconColor,
    required String label,
  }) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 7),
      decoration: BoxDecoration(
        color: const Color(0xFFF8F8F8),
        borderRadius: BorderRadius.circular(999),
        border: Border.all(color: const Color(0xFFECECEC)),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, size: 14, color: iconColor),
          const SizedBox(width: 5),
          Text(
            label,
            style: const TextStyle(
              fontSize: 12,
              color: Color(0xFF555555),
              fontWeight: FontWeight.w700,
            ),
          ),
        ],
      ),
    );
  }

  String _formatPrice(int price) {
    return price.toString().replaceAllMapped(
      RegExp(r'(\d{1,3})(?=(\d{3})+(?!\d))'),
      (m) => '${m[1]},',
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
        final canInteractWithMic =
            !widget.previewMode &&
            (provider.canUseVoice || provider.isListening);
        final isCompactBottomBar =
            provider.isLoading ||
            provider.isSpeaking ||
            provider.stage == CallStage.productSelection ||
            provider.stage == CallStage.cart ||
            provider.stage == CallStage.payment;
        final shouldShowVoiceStatus =
            !_hasStartedVoiceInteraction ||
            provider.isListening ||
            provider.isTranscribing ||
            provider.isSpeaking ||
            provider.isLoading ||
            provider.errorMessage != null;
        return Padding(
          padding: EdgeInsets.fromLTRB(
            16,
            0,
            16,
            isCompactBottomBar ? 10 : 20,
          ),
          child: Column(
            children: [
              if (widget.previewMode) ...[
                Container(
                  width: double.infinity,
                  margin: const EdgeInsets.only(bottom: 14),
                  padding: const EdgeInsets.symmetric(
                    horizontal: 16,
                    vertical: 12,
                  ),
                  decoration: BoxDecoration(
                    color: const Color(0xFFFFEEF3),
                    borderRadius: BorderRadius.circular(18),
                    border: Border.all(color: const Color(0xFFF4CFD9)),
                  ),
                  child: const Text(
                    '미리보기 모드예요. 이 화면에서는 백엔드 호출과 음성 입출력이 실행되지 않아요.',
                    textAlign: TextAlign.center,
                    style: TextStyle(
                      fontSize: _supportFontSize,
                      color: Color(0xFF9C3D57),
                      fontWeight: FontWeight.w700,
                      height: 1.4,
                    ),
                  ),
                ),
              ],
              // 말하기 버튼 (통화 중일 때만 표시)
              if (provider.stage != CallStage.loading &&
                  provider.stage != CallStage.completed) ...[
                Row(
                  mainAxisAlignment: MainAxisAlignment.center,
                  crossAxisAlignment: CrossAxisAlignment.center,
                  children: [
                    MouseRegion(
                      cursor: canInteractWithMic
                          ? SystemMouseCursors.click
                          : SystemMouseCursors.basic,
                      onEnter: (_) => _handleMicHover(true),
                      onExit: (_) => _handleMicHover(false),
                      child: GestureDetector(
                        behavior: HitTestBehavior.opaque,
                        onTapDown: canInteractWithMic
                            ? (_) => _handleMicTapDown(provider)
                            : null,
                        onTapCancel: _handleMicTapEnd,
                        onTapUp: (_) => _handleMicTapEnd(),
                        onTap: canInteractWithMic
                            ? () => _handleMicTap(provider)
                            : null,
                        child: Container(
                          width: isCompactBottomBar ? 64 : 82,
                          height: isCompactBottomBar ? 64 : 82,
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
                            size: isCompactBottomBar ? 28 : 32,
                          ),
                        ),
                      ),
                    ),
                    if (!_isPasswordInputMode(provider) &&
                        !provider.isLoading) ...[
                      SizedBox(width: isCompactBottomBar ? 10 : 14),
                      Flexible(child: _buildTextInputToggle()),
                    ],
                  ],
                ),
                SizedBox(height: isCompactBottomBar ? 4 : 10),
                if (shouldShowVoiceStatus) ...[
                  SizedBox(height: isCompactBottomBar ? 2 : 6),
                  Text(
                    provider.voiceStatusLabel,
                    style: TextStyle(
                      fontSize: isCompactBottomBar ? 13 : _supportFontSize,
                      color: provider.isListening
                          ? const Color(0xFF4CAF50)
                          : provider.canUseVoice
                          ? const Color(0xFF888888)
                          : const Color(0xFFE8325A),
                    ),
                    textAlign: TextAlign.center,
                  ),
                ],
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
                SizedBox(height: isCompactBottomBar ? 6 : 14),
                if (!provider.isLoading) ...[
                  if (_isPasswordInputMode(provider)) ...[_buildPinPad()],
                  if (_showTextInput && !_isPasswordInputMode(provider)) ...[
                    SizedBox(height: isCompactBottomBar ? 8 : 12),
                    _buildDemoTextInput(),
                  ],
                  SizedBox(height: isCompactBottomBar ? 6 : 16),
                ],
              ],

              // 전화 끊기 버튼
              Container(
                width: double.infinity,
                height: 1,
                margin: EdgeInsets.only(bottom: isCompactBottomBar ? 8 : 12),
                color: const Color(0xFFEFD8DF),
              ),
              MouseRegion(
                cursor: SystemMouseCursors.click,
                onEnter: (_) => _handleEndCallHover(true),
                onExit: (_) => _handleEndCallHover(false),
                child: GestureDetector(
                  onTap: _endCall,
                  child: Container(
                    width: double.infinity,
                    height: isCompactBottomBar ? 50 : 60,
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
                          size: isCompactBottomBar ? 21 : 24,
                        ),
                        SizedBox(width: isCompactBottomBar ? 8 : 10),
                        Text(
                          '전화 끊기',
                          style: TextStyle(
                            fontSize: isCompactBottomBar ? 16 : _buttonFontSize,
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
