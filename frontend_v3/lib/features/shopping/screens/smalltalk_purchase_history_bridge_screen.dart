import 'dart:async';

import 'package:flutter/material.dart';

import '../../../app/theme/app_colors.dart';
import '../../../app/theme/app_spacing.dart';
import '../../../app/theme/app_text_styles.dart';
import '../../../core/services/voice_service.dart';
import '../../../shared/layout/app_responsive.dart';
import '../../../shared/layout/layout_presets.dart';
import '../../../shared/layout/screen_frame.dart';
import '../../../shared/widgets/dialogue_bubble.dart';
import '../../../shared/widgets/end_conversation_button.dart';
import '../../../shared/widgets/voice_input_button.dart';
import '../../../shared/widgets/voice_panel.dart';
import '../../platform_check/screens/platform_check_screen.dart';

/// 스몰토크가 끝난 뒤 구매 이력 수집으로 넘어가기 전에 보여주는 짧은 브릿지 화면.
/// 한 문장씩 화면에 보여주고 같은 문장을 TTS로 읽은 뒤 다음 문장으로 넘어간다.
class SmallTalkPurchaseHistoryBridgeScreen extends StatefulWidget {
  const SmallTalkPurchaseHistoryBridgeScreen({
    super.key,
    required this.userName,
    this.useMockFlow = false,
  });

  final String userName;
  final bool useMockFlow;

  @override
  State<SmallTalkPurchaseHistoryBridgeScreen> createState() =>
      _SmallTalkPurchaseHistoryBridgeScreenState();
}

class _SmallTalkPurchaseHistoryBridgeScreenState
    extends State<SmallTalkPurchaseHistoryBridgeScreen> {
  final VoiceService _voiceService = VoiceService.instance;

  int _currentMessageIndex = 0;
  bool _isSpeaking = false;
  bool _isNavigating = false;

  String get _resolvedUserName {
    final trimmed = widget.userName.trim();
    return trimmed.isEmpty ? '고객' : trimmed;
  }

  late final List<String> _messages = <String>[
    '$_resolvedUserName님이랑 대화는 너무 재밌어요.',
    '$_resolvedUserName님의 취향을 더 알아가는 시간이라 저에게 도움이 되었어요!',
    '이번에는 $_resolvedUserName님이 평소에 구매하셨던 이력을 모아볼게요.',
  ];

  String get _currentMessage => _messages[_currentMessageIndex];

  @override
  void initState() {
    super.initState();
    unawaited(_playMessagesThenContinue());
  }

  @override
  void dispose() {
    unawaited(_voiceService.stopSpeaking());
    super.dispose();
  }

  Future<void> _playMessagesThenContinue() async {
    try {
      await _voiceService.init();
    } catch (_) {
      // TTS는 진행 보조라 초기화 실패가 플로우를 막으면 안 된다.
    }

    for (var index = 0; index < _messages.length; index += 1) {
      if (!mounted) {
        return;
      }

      setState(() {
        _currentMessageIndex = index;
        _isSpeaking = true;
      });

      try {
        await _voiceService.speak(_messages[index]);
      } catch (_) {
        // TTS 재생 실패 시에도 문장 진행과 화면 전환은 계속한다.
      } finally {
        if (mounted) {
          setState(() => _isSpeaking = false);
        }
      }

      if (index < _messages.length - 1) {
        await Future<void>.delayed(const Duration(milliseconds: 280));
      }
    }

    _continueToPurchaseHistory();
  }

  void _continueToPurchaseHistory() {
    if (_isNavigating || !mounted) {
      return;
    }
    setState(() => _isNavigating = true);

    Navigator.of(context).pushReplacement(
      MaterialPageRoute<void>(
        builder: (_) => PlatformCheckScreen(
          userName: _resolvedUserName,
          useMockFlow: widget.useMockFlow,
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return ScreenFrame(
      preset: LayoutPreset.conversation,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          DialogueBubble(
            contentKey: ValueKey(_currentMessage),
            text: _currentMessage,
            // 바깥 for 루프가 이미 문장 단위로 speak()를 기다렸다 다음
            // 문장으로 넘어간다. cyclePages(내부 고정 타이머 순환)는 다른
            // 화면들과 통일해서 꺼둔다 — 안 그러면 문장이 길어졌을 때만
            // 내부적으로 또 쪼개 순환하려 들어 타이밍이 어긋날 수 있다.
            cyclePages: false,
            highlightedWords: [_resolvedUserName, '취향', '구매하셨던 이력'],
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
            label: _isNavigating
                ? '구매이력으로 이동 중...'
                : (_isSpeaking ? '딸랑구가 말하고 있어요' : '이동 중...'),
            onPressed: _continueToPurchaseHistory,
          ),
        ],
      ),
    );
  }
}
