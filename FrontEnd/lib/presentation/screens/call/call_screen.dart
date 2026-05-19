//통화 화면
//전화 끊기 버튼이 항상 고정되고, stage에 따라 가운데 콘텐츠가 바뀌는 구조
import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:provider/provider.dart';
import '../../../presentation/providers/call_provider.dart';

class CallScreen extends StatefulWidget {
  const CallScreen({super.key});

  @override
  State<CallScreen> createState() => _CallScreenState();
}

class _CallScreenState extends State<CallScreen> {
  final TextEditingController _textController = TextEditingController();

  @override
  void initState() {
    super.initState();
    // 전화 시작 시 첫 메시지 전송
    WidgetsBinding.instance.addPostFrameCallback((_) {
      context.read<CallProvider>().startCall();
    });
  }

  @override
  void dispose() {
    _textController.dispose();
    super.dispose();
  }

  void _endCall() {
    context.read<CallProvider>().endCall();
    context.go('/home');
  }

  void _handleTextSubmit() {
    if (_textController.text.isEmpty) return;
    context.read<CallProvider>().sendTextMessage(_textController.text);
    _textController.clear();
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
          const Text(
            '딸랑구',
            style: TextStyle(
              fontSize: 20,
              fontWeight: FontWeight.bold,
              color: Color(0xFFE8325A),
            ),
          ),
          const SizedBox(height: 4),
          Consumer<CallProvider>(
            builder: (context, provider, _) {
              return Text(
                provider.conversationId != null ? '통화 중' : '연결 중...',
                style: const TextStyle(fontSize: 13, color: Color(0xFF4CAF50)),
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

        // 데모용 텍스트 입력창
        if (provider.stage != CallStage.completed && !provider.isLoading)
          _buildDemoTextInput(),

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

        // 음성 파형 (로딩 중 아닐 때)
        if (!provider.isLoading)
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 12),
            child: _buildVoiceWave(),
          ),

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
              fontSize: 16,
              color: Color(0xFFE8325A),
              fontWeight: FontWeight.w500,
            ),
          ),
          const SizedBox(height: 8),
          const Text(
            '잠시 기다려주세요',
            style: TextStyle(fontSize: 13, color: Color(0xFF888888)),
          ),
        ],
      ),
    );
  }

  // 데모용 텍스트 입력 필드
  Widget _buildDemoTextInput() {
    final provider = context.watch<CallProvider>();
    // 딸랑구가 비밀번호를 요구하는 상황인지 판단
    final bool isPasswordInput =
        provider.lastResponse?.assistantMessage.contains('비밀번호') ?? false;

    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
      child: Row(
        children: [
          Expanded(
            child: TextField(
              controller: _textController,
              obscureText: isPasswordInput, // 비밀번호 입력 시 마스킹 처리
              decoration: InputDecoration(
                hintText: '메시지를 입력하세요 (데모용)',
                fillColor: Colors.white,
                filled: true,
                border: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(20),
                  borderSide: BorderSide.none,
                ),
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

  // 말풍선
  Widget _buildMessageBubble({required String text, required bool isUser}) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Row(
        mainAxisAlignment: isUser
            ? MainAxisAlignment.end
            : MainAxisAlignment.start,
        crossAxisAlignment: CrossAxisAlignment.end,
        children: [
          if (!isUser) ...[
            const CircleAvatar(
              radius: 16,
              backgroundColor: Color(0xFFFFD6E0),
              child: Text('🧒', style: TextStyle(fontSize: 16)),
            ),
            const SizedBox(width: 8),
          ],
          Flexible(
            child: Container(
              padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
              decoration: BoxDecoration(
                color: isUser
                    ? const Color(0xFFE8325A)
                    : const Color(0xFFFFFFFF),
                borderRadius: BorderRadius.only(
                  topLeft: const Radius.circular(16),
                  topRight: const Radius.circular(16),
                  bottomLeft: Radius.circular(isUser ? 16 : 4),
                  bottomRight: Radius.circular(isUser ? 4 : 16),
                ),
                boxShadow: [
                  BoxShadow(
                    color: Colors.black.withOpacity(0.05),
                    blurRadius: 4,
                    offset: const Offset(0, 2),
                  ),
                ],
              ),
              child: Text(
                text,
                style: TextStyle(
                  fontSize: 15,
                  color: isUser ? Colors.white : const Color(0xFF333333),
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }

  // 상품 추천 카드
  Widget _buildProductCard(CallProvider provider) {
    final item = provider.lastResponse!.recommendations.first;
    return Container(
      margin: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(16),
        boxShadow: [
          BoxShadow(
            color: Colors.black.withOpacity(0.08),
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
              if (item.imageUrl != null)
                ClipRRect(
                  borderRadius: BorderRadius.circular(8),
                  child: Image.network(
                    item.imageUrl!,
                    width: 80,
                    height: 80,
                    fit: BoxFit.cover,
                  ),
                ),
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
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Text(
                '${item.price.toString().replaceAllMapped(RegExp(r'(\d{1,3})(?=(\d{3})+(?!\d))'), (m) => '${m[1]},')}원',
                style: const TextStyle(
                  fontSize: 20,
                  fontWeight: FontWeight.bold,
                  color: Color(0xFFE8325A),
                ),
              ),
              if (item.deliveryInfo != null)
                Text(
                  item.deliveryInfo!,
                  style: const TextStyle(
                    fontSize: 12,
                    color: Colors.green,
                    fontWeight: FontWeight.bold,
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
        border: Border.all(color: const Color(0xFFE8325A).withOpacity(0.3)),
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
            color: Colors.black.withOpacity(0.08),
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

  // 음성 파형 (더미 UI)
  Widget _buildVoiceWave() {
    return Row(
      mainAxisAlignment: MainAxisAlignment.center,
      children: List.generate(12, (index) {
        return Container(
          margin: const EdgeInsets.symmetric(horizontal: 2),
          width: 4,
          height: (index % 3 == 0)
              ? 20
              : (index % 2 == 0)
              ? 12
              : 8,
          decoration: BoxDecoration(
            color: const Color(0xFFE8325A).withOpacity(0.5),
            borderRadius: BorderRadius.circular(2),
          ),
        );
      }),
    );
  }

  // 하단 버튼 영역 (말하기 + 전화 끊기)
  Widget _buildEndCallButton() {
    return Consumer<CallProvider>(
      builder: (context, provider, _) {
        return Padding(
          padding: const EdgeInsets.only(bottom: 48),
          child: Column(
            children: [
              // 말하기 버튼 (통화 중일 때만 표시)
              if (provider.stage != CallStage.loading &&
                  provider.stage != CallStage.completed) ...[
                GestureDetector(
                  onTapDown: (_) => provider.startListening(),
                  onTapUp: (_) => provider.stopListeningAndSend(),
                  onTapCancel: () => provider.stopListeningAndSend(),
                  child: Container(
                    width: 64,
                    height: 64,
                    decoration: BoxDecoration(
                      color: provider.isListening
                          ? const Color(0xFF4CAF50)
                          : const Color(0xFFEEEEEE),
                      shape: BoxShape.circle,
                      border: provider.isListening
                          ? Border.all(color: const Color(0xFF4CAF50), width: 3)
                          : null,
                    ),
                    child: Icon(
                      provider.isListening ? Icons.mic : Icons.mic_none,
                      color: provider.isListening
                          ? Colors.white
                          : const Color(0xFF888888),
                      size: 28,
                    ),
                  ),
                ),
                const SizedBox(height: 8),
                Text(
                  provider.isListening ? '듣는 중...' : '누르고 말하기',
                  style: TextStyle(
                    fontSize: 12,
                    color: provider.isListening
                        ? const Color(0xFF4CAF50)
                        : const Color(0xFF888888),
                  ),
                ),
                const SizedBox(height: 16),
              ],

              // 전화 끊기 버튼
              GestureDetector(
                onTap: _endCall,
                child: Container(
                  width: 72,
                  height: 72,
                  decoration: const BoxDecoration(
                    color: Color(0xFFE8325A),
                    shape: BoxShape.circle,
                  ),
                  child: const Icon(
                    Icons.call_end,
                    color: Colors.white,
                    size: 32,
                  ),
                ),
              ),
              const SizedBox(height: 8),
              const Text(
                '전화 끊기',
                style: TextStyle(fontSize: 14, color: Color(0xFF555555)),
              ),
            ],
          ),
        );
      },
    );
  }
}
