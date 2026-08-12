import 'dart:async';

import 'package:flutter/material.dart';

import '../../../app/theme/app_colors.dart';
import '../../../app/theme/app_spacing.dart';
import '../../../app/theme/app_text_styles.dart';
import '../../../core/services/voice_service.dart';
import '../../../core/storage/local_storage.dart';
import '../../../data/models/agent_model.dart';
import '../../../data/repositories/agent_repository.dart';
import '../../../shared/layout/app_responsive.dart';
import '../../../shared/layout/layout_presets.dart';
import '../../../shared/layout/screen_frame.dart';
import '../../../shared/widgets/dialogue_bubble.dart';
import '../../../shared/widgets/end_conversation_button.dart';
import '../../../shared/widgets/voice_input_button.dart';
import '../../../shared/widgets/voice_panel.dart';
import '../../platform_check/screens/platform_check_screen.dart';

/// 딸랑구가 인사말을 건네는 화면. 이 화면은 사용자 응답이 필요 없는
/// 일방향 안내 구간이라, 딸랑구의 TTS가 끝나면 곧바로 다음 화면(플랫폼
/// 확인)으로 자동 전환한다. 그래서 하단 음성 패널은 항상 비활성(회색)
/// 상태로만 보여주고 마이크 입력을 받지 않는다.
class AgentSmallTalkScreen extends StatefulWidget {
  const AgentSmallTalkScreen({
    super.key,
    required this.userName,
    this.useMockFlow = false,
  });

  final String userName;
  final bool useMockFlow;

  @override
  State<AgentSmallTalkScreen> createState() => _AgentSmallTalkScreenState();
}

class _AgentSmallTalkScreenState extends State<AgentSmallTalkScreen> {
  final AgentRepository _agentRepository = AgentRepository();
  final VoiceService _voiceService = VoiceService.instance;

  AgentResponse? _response;
  bool _isLoading = true;
  bool _isSpeaking = false;
  bool _isNavigatingToPurchaseHistory = false;
  String? _errorMessage;

  @override
  void initState() {
    super.initState();
    unawaited(_startAgentSmallTalk());
  }

  @override
  void dispose() {
    unawaited(_voiceService.stopSpeaking());
    super.dispose();
  }

  Future<void> _startAgentSmallTalk() async {
    setState(() {
      _isLoading = true;
      _errorMessage = null;
    });

    try {
      await _voiceService.init();
      // mock 플로우에서는 smalltalk_screen이 userId를 일부러 비워두고
      // (LocalStorage.clearUserId) 실제 회원가입 API도 타지 않으므로,
      // userId 존재 여부 체크는 실제 백엔드 호출 경로에서만 의미가 있다.
      final userId = await LocalStorage.getUserId();
      if (userId == null && !widget.useMockFlow) {
        throw StateError('사용자 정보를 찾지 못했어요.');
      }

      final response = widget.useMockFlow
          ? _mockSmallTalkResponse()
          : await _agentRepository.startShopping(
              userId: userId!,
              message: '안녕하세요, 제 이름은 ${widget.userName}이에요.',
            );

      if (!mounted) {
        return;
      }

      setState(() {
        _response = response;
        _isLoading = false;
      });
      await _speakThenContinue(response);
    } catch (error) {
      if (!mounted) {
        return;
      }
      setState(() {
        _isLoading = false;
        _errorMessage = '딸랑구와 대화를 시작하지 못했어요. 잠시 후 다시 진행할게요.';
      });
    }
  }

  AgentResponse _mockSmallTalkResponse() {
    return AgentResponse(
      conversationId: -1,
      status: 'smalltalk',
      stage: 'idle',
      assistantMessage:
          '${widget.userName}님 반가워요. 오늘 편하게 쇼핑하실 수 있게 먼저 구매 이력을 살펴볼게요.',
    );
  }

  Future<void> _speak(String message) async {
    final trimmed = message.trim();
    if (trimmed.isEmpty) {
      return;
    }
    setState(() => _isSpeaking = true);
    try {
      await _voiceService.speak(trimmed);
    } catch (_) {
      // TTS는 진행 보조 기능이라 실패해도 다음 단계 이동은 막지 않는다.
    } finally {
      if (mounted) {
        setState(() => _isSpeaking = false);
      }
    }
  }

  // 이 화면은 사용자 응답을 받지 않는 일방향 안내라, 딸랑구가 말을 끝내면
  // (uiCommand 여부와 상관없이) 항상 바로 다음 화면으로 넘어간다.
  Future<void> _speakThenContinue(AgentResponse response) async {
    await _speak(response.assistantMessage);
    _continueToPurchaseHistory();
  }

  void _continueToPurchaseHistory() {
    if (_isNavigatingToPurchaseHistory) {
      return;
    }
    setState(() {
      _isNavigatingToPurchaseHistory = true;
      _errorMessage = null;
    });

    Navigator.of(context).pushReplacement(
      MaterialPageRoute<void>(
        builder: (_) => PlatformCheckScreen(
          userName: widget.userName,
          useMockFlow: widget.useMockFlow,
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final message = _response?.assistantMessage.trim();

    return ScreenFrame(
      preset: LayoutPreset.conversation,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          DialogueBubble(
            contentKey: ValueKey('$_isLoading-${message ?? ''}'),
            cyclePages: true,
            text: _isLoading
                ? '잠시만요. 딸랑구가 ${widget.userName}님과 인사하고 있어요.'
                : (message == null || message.isEmpty
                      ? '${widget.userName}님 반가워요.'
                      : message),
            highlightedWords: [widget.userName, '딸랑구'],
            minHeight: 172,
            padding: const EdgeInsets.symmetric(
              horizontal: AppSpacing.lg,
              vertical: AppSpacing.xl,
            ),
            style: AppTextStyles.title2.copyWith(
              color: AppColors.textStrong,
              height: 1.35,
              fontWeight: FontWeight.w700,
            ),
            emphasizedStyle: AppTextStyles.title2.copyWith(
              color: AppColors.primaryPinkDark,
              height: 1.35,
              fontWeight: FontWeight.w800,
            ),
          ),
          const SizedBox(height: AppSpacing.lg),
          Expanded(
            child: Center(
              child: Image.asset(
                'assets/images/character/full/ddalangoo_smalltalk.png',
                height: context.responsive.conversationCharacterHeight(),
                fit: BoxFit.contain,
              ),
            ),
          ),
          if (_errorMessage != null) ...[
            Text(
              _errorMessage!,
              textAlign: TextAlign.center,
              style: AppTextStyles.body2.copyWith(
                color: AppColors.primaryPinkDark,
                fontWeight: FontWeight.w700,
              ),
            ),
            const SizedBox(height: AppSpacing.md),
          ],
          // 사용자 응답이 필요 없는 구간이라 음성 패널은 항상 비활성(회색)
          // 상태로만 보여준다. 딸랑구 TTS가 끝나면 자동으로 다음 화면으로
          // 넘어간다.
          IgnorePointer(
            child: VoicePanel(
              state: VoiceInputState.inactive,
              onPressed: () {},
            ),
          ),
          const SizedBox(height: AppSpacing.md),
          EndConversationButton(
            fullWidth: true,
            variant: EndConversationButtonVariant.dark,
            label: _isNavigatingToPurchaseHistory ? '구매이력으로 이동 중...' : '대화 종료',
            onPressed: _continueToPurchaseHistory,
          ),
        ],
      ),
    );
  }
}
