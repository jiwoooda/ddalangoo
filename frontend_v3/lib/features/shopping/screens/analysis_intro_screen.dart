import 'dart:async';

import 'package:flutter/material.dart';

import '../../../app/routes.dart';
import '../../../app/theme/app_colors.dart';
import '../../../app/theme/app_spacing.dart';
import '../../../app/theme/app_text_styles.dart';
import '../../../core/services/voice_service.dart';
import '../../../shared/layout/app_responsive.dart';
import '../../../shared/layout/layout_presets.dart';
import '../../../shared/layout/screen_frame.dart';
import '../../../shared/services/spoken_sentence_player.dart';
import '../../../shared/widgets/dialogue_bubble.dart';
import '../../../shared/widgets/end_conversation_button.dart';
import '../../../shared/widgets/voice_input_button.dart';
import '../../../shared/widgets/voice_panel.dart';

/// 구매 이력 저장/불러오기가 끝난 뒤, 취향 분석이 이어진다고 안내하는
/// 일방향 화면. 사용자 응답은 받지 않고 TTS가 끝나면 다음 화면으로 간다.
class AnalysisIntroScreen extends StatefulWidget {
  const AnalysisIntroScreen({
    super.key,
    this.userName,
    this.useMockFlow = false,
    this.nextRouteName = AppRoutes.home,
  });

  final String? userName;
  final bool useMockFlow;
  final String nextRouteName;

  @override
  State<AnalysisIntroScreen> createState() => _AnalysisIntroScreenState();
}

class _AnalysisIntroScreenState extends State<AnalysisIntroScreen> {
  final VoiceService _voiceService = VoiceService.instance;
  final SpokenSentencePlayer _sentencePlayer = SpokenSentencePlayer();

  bool _isSpeaking = false;
  bool _isNavigating = false;
  String? _currentSentence;

  static const String _message = '이제 분석을 해볼게요! 분석이 완료되면 바로가기에서 확인하실 수 있어요.';
  static final List<String> _sentences = SpokenSentencePlayer.splitSentences(
    _message,
  );

  @override
  void initState() {
    super.initState();
    _currentSentence = _sentences.isEmpty ? _message : _sentences.first;
    unawaited(_speakThenContinue());
  }

  @override
  void dispose() {
    _sentencePlayer.cancel();
    unawaited(_voiceService.stopSpeaking());
    super.dispose();
  }

  Future<void> _speakThenContinue() async {
    try {
      await _voiceService.init();
    } catch (_) {
      // TTS는 진행 보조 기능이라 초기화 실패가 플로우를 막으면 안 된다.
    }
    setState(() => _isSpeaking = true);
    try {
      // 예전엔 두 문장을 한 번에 speak()로 넘기면서 DialogueBubble의
      // cyclePages(고정 타이머)가 따로 문장을 순환해 화면 텍스트와 실제
      // TTS 재생 타이밍이 서로 어긋났다. 이제 SpokenSentencePlayer가 문장
      // 표시와 TTS 재생 완료를 같이 맞춘다.
      await _sentencePlayer.play(
        _sentences,
        isMounted: () => mounted,
        onSentence: (sentence) {
          if (mounted) {
            setState(() => _currentSentence = sentence);
          }
        },
      );
    } catch (_) {
      // TTS 재생이 실패해도 다음 단계 이동은 막지 않는다.
    } finally {
      if (mounted) {
        setState(() => _isSpeaking = false);
      }
    }
    _continueToNextScreen();
  }

  void _continueToNextScreen() {
    if (_isNavigating || !mounted) {
      return;
    }
    setState(() => _isNavigating = true);

    Navigator.of(context).pushReplacementNamed(widget.nextRouteName);
  }

  @override
  Widget build(BuildContext context) {
    return ScreenFrame(
      preset: LayoutPreset.conversation,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          DialogueBubble(
            contentKey: ValueKey(_currentSentence ?? _message),
            animateTextChanges: true,
            text: _currentSentence ?? _message,
            cyclePages: false,
            highlightedWords: const ['분석', '바로가기'],
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
                'assets/images/character/full/ddalangoo_curious.png',
                height: context.responsive.conversationCharacterHeight(),
                fit: BoxFit.contain,
              ),
            ),
          ),
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
            label: _isNavigating
                ? '홈으로 이동 중...'
                : (_isSpeaking ? '딸랑구가 말하고 있어요' : '대화 종료'),
            onPressed: _continueToNextScreen,
          ),
        ],
      ),
    );
  }
}
