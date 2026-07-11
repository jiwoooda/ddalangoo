// 신규 가입자 온보딩 스몰토크 화면.
//
// 아직 백엔드에 스몰토크 API가 없어서(추천/자동화용 사용자 정보를 수집하기 위한
// LLM 질문 생성 + 답변 요약 엔드포인트 미구현), 프론트에서는 우선
// 고정된 목(mock) 질문 목록으로 TTS/STT 대화 흐름만 구현해둔다.
//
// TODO(backend): 아래 _mockQuestions 대신 아래와 같은 백엔드 API로 대체한다.
//   - POST /api/user/smalltalk/next-question  (직전 답변을 넘기면 다음 LLM 질문 반환)
//   - POST /api/user/smalltalk/complete        (수집한 답변들을 프로필/추천 시스템에 반영)
import 'dart:async';

import 'package:flutter/material.dart';

import '../../../core/services/gpt_voice_service.dart';
import '../models/shopping_v2_models.dart';
import '../services/voice_turn_service.dart';
import '../widgets/dallang_response_text.dart';
import '../widgets/glass_card.dart';
import '../widgets/liquid_glass_page.dart';
import '../widgets/shopping_screen_chrome.dart';
import '../widgets/voice_turn_orb.dart';

class SmallTalkScreen extends StatefulWidget {
  const SmallTalkScreen({super.key, this.userName});

  /// 미리보기/테스트용으로 사용자 이름을 주입할 수 있게 한다.
  final String? userName;

  @override
  State<SmallTalkScreen> createState() => _SmallTalkScreenState();
}

class _SmallTalkScreenState extends State<SmallTalkScreen> {
  late final VoiceTurnService _voiceTurnService = VoiceTurnService(
    voiceService: GptVoiceService.instance,
  );

  // TODO(backend): 실제로는 LLM이 이전 답변을 바탕으로 다음 질문을 동적으로 생성한다.
  List<String> get _questions => [
    widget.userName == null || widget.userName!.isEmpty
        ? '안녕하세요! 저는 앞으로 고객님의 쇼핑을 도울 딸랑구라고 해요. 몇 가지만 여쭤보고 바로 쇼핑을 도와드릴게요!'
        : '안녕하세요 ${widget.userName}님! 저는 앞으로 고객님의 쇼핑을 도울 딸랑구라고 해요. 몇 가지만 여쭤보고 바로 쇼핑을 도와드릴게요!',
    '고객님을 어떻게 부르면 좋을까요? 이름이나 별명, 닉네임 등 편한 걸로 알려주세요.',
    '구매 이력을 보니 식품을 많이 사시네요. 장 보실 때 주로 어떤 걸 중요하게 생각하시나요?',
    '알러지가 있으신가요? 혹은 피하고 싶은 재료나 성분이 있으신가요?',
    '좋아요! 이제 딸랑구가 취향에 맞춰서 잘 챙겨드릴게요 :)',
  ];

  int _questionIndex = 0;
  VoiceTurnState _voiceTurnState = VoiceTurnState.idle;
  String? _lastAnswer;
  bool _isFinished = false;
  int _epoch = 0;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _init());
  }

  Future<void> _init() async {
    await _voiceTurnService.init();
    await _speakCurrentQuestion();
  }

  bool get _isLastQuestion => _questionIndex >= _questions.length - 1;

  Future<void> _speakCurrentQuestion() async {
    final epoch = ++_epoch;
    if (!mounted) return;
    setState(() {
      _voiceTurnState = VoiceTurnState.agentSpeaking;
      _lastAnswer = null;
    });

    try {
      await _voiceTurnService.speak(_questions[_questionIndex]);
    } catch (_) {
      // TTS 실패해도 대화 흐름은 계속 진행한다.
    }

    if (!mounted || epoch != _epoch) return;

    if (_isLastQuestion) {
      setState(() {
        _voiceTurnState = VoiceTurnState.idle;
        _isFinished = true;
      });
      return;
    }

    setState(() => _voiceTurnState = VoiceTurnState.userCanSpeak);
  }

  Future<void> _onOrbTap() async {
    if (_voiceTurnState == VoiceTurnState.userCanSpeak) {
      await _startRecording();
    } else if (_voiceTurnState == VoiceTurnState.userRecording) {
      await _stopRecordingAndAdvance();
    }
  }

  Future<void> _startRecording() async {
    final epoch = _epoch;
    try {
      await _voiceTurnService.playStartListeningCue();
      await _voiceTurnService.startRecording();
      if (!mounted || epoch != _epoch) return;
      setState(() => _voiceTurnState = VoiceTurnState.userRecording);
    } catch (e) {
      debugPrint('⚠️ [SmallTalk] recording start failed: $e');
    }
  }

  Future<void> _stopRecordingAndAdvance() async {
    final epoch = _epoch;
    setState(() => _voiceTurnState = VoiceTurnState.transcribing);
    try {
      final transcriptFuture = _voiceTurnService.stopRecordingAndTranscribe();
      unawaited(_voiceTurnService.playStopListeningCue());
      final transcript = await transcriptFuture;
      if (!mounted || epoch != _epoch) return;

      setState(() {
        _lastAnswer = transcript.trim().isEmpty
            ? '(답변을 듣지 못했어요)'
            : transcript.trim();
      });

      // TODO(backend): transcript를 /api/user/smalltalk/next-question 에 넘겨
      // 다음 질문과 프로필 추출 결과를 받아온다. 지금은 목 질문 리스트를 순서대로 진행.
      await Future<void>.delayed(const Duration(milliseconds: 900));
      if (!mounted || epoch != _epoch) return;

      setState(() => _questionIndex += 1);
      await _speakCurrentQuestion();
    } catch (e) {
      debugPrint('⚠️ [SmallTalk] transcribe failed: $e');
      if (!mounted || epoch != _epoch) return;
      setState(() => _voiceTurnState = VoiceTurnState.userCanSpeak);
    }
  }

  @override
  void dispose() {
    _epoch++;
    unawaited(_voiceTurnService.dispose());
    super.dispose();
  }

  String get _characterAsset {
    switch (_voiceTurnState) {
      case VoiceTurnState.agentSpeaking:
        return 'assets/images/ddalangoo_cheerful.png';
      case VoiceTurnState.userRecording:
        return 'assets/images/ddalangoo_curious.png';
      case VoiceTurnState.transcribing:
      case VoiceTurnState.agentThinking:
        return 'assets/images/ddalangoo_curious.png';
      case VoiceTurnState.error:
        return 'assets/images/ddalangoo_calling.png';
      case VoiceTurnState.idle:
      case VoiceTurnState.userCanSpeak:
        return _isFinished
            ? 'assets/images/ddalangoo_happy.png'
            : 'assets/images/ddalangoo_cheerful.png';
    }
  }

  @override
  Widget build(BuildContext context) {
    final bottomInset = MediaQuery.of(context).padding.bottom;

    return LiquidGlassPage(
      child: Scaffold(
        backgroundColor: const Color(0xFFF9FCFB),
        body: SafeArea(
          child: Stack(
            children: [
              const Positioned.fill(child: ShoppingScreenBackground()),
              Padding(
                padding: const EdgeInsets.fromLTRB(24, 12, 24, 24),
                child: Column(
                  children: [
                    const Align(
                      alignment: Alignment.centerLeft,
                      child: ShoppingScreenBackButton(),
                    ),
                    const SizedBox(height: 14),
                    _buildProgressDots(),
                    const SizedBox(height: 24),
                    // 딸랑구 캐릭터 - 말하는 느낌을 주기 위해 상태에 따라 표정/자세 이미지를 바꾸고
                    // agentSpeaking일 때 살짝 위아래로 흔들어 "말하는 듯한" 모션을 준다.
                    Expanded(
                      flex: 3,
                      child: Center(
                        child: _TalkingCharacter(
                          assetPath: _characterAsset,
                          isTalking:
                              _voiceTurnState == VoiceTurnState.agentSpeaking,
                        ),
                      ),
                    ),
                    const SizedBox(height: 12),
                    Expanded(
                      flex: 2,
                      child: GlassCard(
                        padding: const EdgeInsets.symmetric(
                          horizontal: 22,
                          vertical: 20,
                        ),
                        child: SingleChildScrollView(
                          physics: const BouncingScrollPhysics(),
                          child: Column(
                            mainAxisSize: MainAxisSize.min,
                            children: [
                              DallangResponseText(
                                key: ValueKey('question-$_questionIndex'),
                                text: _questions[_questionIndex],
                                fontSize: 22,
                                maxLines: 4,
                              ),
                              if (_lastAnswer != null) ...[
                                const SizedBox(height: 14),
                                Container(
                                  padding: const EdgeInsets.symmetric(
                                    horizontal: 14,
                                    vertical: 10,
                                  ),
                                  decoration: BoxDecoration(
                                    color: const Color(
                                      0xFFFF6FAE,
                                    ).withValues(alpha: 0.10),
                                    borderRadius: BorderRadius.circular(16),
                                  ),
                                  child: Text(
                                    '“$_lastAnswer”',
                                    style: const TextStyle(
                                      fontFamily: 'Pretendard',
                                      fontSize: 15,
                                      fontWeight: FontWeight.w600,
                                      color: Color(0xFF7A4A5C),
                                    ),
                                  ),
                                ),
                              ],
                            ],
                          ),
                        ),
                      ),
                    ),
                    const SizedBox(height: 20),
                    SizedBox(
                      height: 128,
                      child: Center(
                        child: _isFinished
                            ? const Text(
                                '취향 파악이 끝났어요',
                                textAlign: TextAlign.center,
                                style: TextStyle(
                                  fontFamily: 'Pretendard',
                                  fontSize: 17,
                                  fontWeight: FontWeight.w700,
                                  color: Color(0xFF51606E),
                                ),
                              )
                            : GestureDetector(
                                behavior: HitTestBehavior.translucent,
                                onTap: _onOrbTap,
                                child: VoiceTurnOrb(
                                  state: _voiceTurnState,
                                  level: 0.4,
                                ),
                              ),
                      ),
                    ),
                    Text(
                      _isFinished
                          ? '아래 버튼으로 미리보기에서 나갈 수 있어요'
                          : _hintTextForState(_voiceTurnState),
                      textAlign: TextAlign.center,
                      style: const TextStyle(
                        fontFamily: 'Pretendard',
                        fontSize: 13,
                        color: Color(0xFF7C8A90),
                      ),
                    ),
                    const SizedBox(height: 16),
                    ShoppingScreenBottomButton(
                      label: '대화 종료',
                      bottomInset: bottomInset,
                      onPressed: () => Navigator.of(context).maybePop(),
                    ),
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  String _hintTextForState(VoiceTurnState state) {
    switch (state) {
      case VoiceTurnState.agentSpeaking:
        return '딸랑구가 이야기하고 있어요';
      case VoiceTurnState.userCanSpeak:
        return '오브를 눌러 답변해주세요';
      case VoiceTurnState.userRecording:
        return '듣고 있어요... 다시 누르면 답변 완료!';
      case VoiceTurnState.transcribing:
        return '답변을 확인하고 있어요';
      case VoiceTurnState.agentThinking:
        return '잠시만 기다려주세요';
      case VoiceTurnState.error:
        return '다시 한번 시도해주세요';
      case VoiceTurnState.idle:
        return '';
    }
  }

  Widget _buildProgressDots() {
    return Row(
      mainAxisAlignment: MainAxisAlignment.center,
      children: List.generate(_questions.length, (index) {
        final isActive = index <= _questionIndex;
        return AnimatedContainer(
          duration: const Duration(milliseconds: 240),
          margin: const EdgeInsets.symmetric(horizontal: 4),
          width: isActive ? 22 : 8,
          height: 8,
          decoration: BoxDecoration(
            color: isActive ? const Color(0xFFFF6FAE) : const Color(0xFFE3E8EA),
            borderRadius: BorderRadius.circular(6),
          ),
        );
      }),
    );
  }
}

class _TalkingCharacter extends StatefulWidget {
  const _TalkingCharacter({required this.assetPath, required this.isTalking});

  final String assetPath;
  final bool isTalking;

  @override
  State<_TalkingCharacter> createState() => _TalkingCharacterState();
}

class _TalkingCharacterState extends State<_TalkingCharacter>
    with SingleTickerProviderStateMixin {
  late final AnimationController _controller = AnimationController(
    vsync: this,
    duration: const Duration(milliseconds: 620),
  )..repeat(reverse: true);

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AnimatedBuilder(
      animation: _controller,
      builder: (context, child) {
        final bob = widget.isTalking ? _controller.value * 8 : 0.0;
        return Transform.translate(offset: Offset(0, -bob), child: child);
      },
      child: AnimatedSwitcher(
        duration: const Duration(milliseconds: 260),
        child: Image.asset(
          widget.assetPath,
          key: ValueKey(widget.assetPath),
          height: 220,
          fit: BoxFit.contain,
          errorBuilder: (context, error, stackTrace) => const Icon(
            Icons.favorite_rounded,
            size: 120,
            color: Color(0xFFD77B9E),
          ),
        ),
      ),
    );
  }
}
