import 'dart:async';

import 'package:flutter/material.dart';

import '../../../app/routes.dart';
import '../../../app/theme/app_colors.dart';
import '../../../app/theme/app_spacing.dart';
import '../../../app/theme/app_text_styles.dart';
import '../../../core/services/voice_service.dart';
import '../../../core/storage/local_storage.dart';
import '../../../data/repositories/agent_repository.dart';
import '../../../shared/layout/app_responsive.dart';
import '../../../shared/layout/layout_presets.dart';
import '../../../shared/layout/screen_frame.dart';
import '../../../shared/services/spoken_sentence_player.dart';
import '../../../shared/widgets/dialogue_bubble.dart';
import '../../../shared/widgets/end_conversation_button.dart';
import '../../../shared/widgets/voice_input_button.dart';
import '../../../shared/widgets/voice_panel.dart';
import 'agent_smalltalk_screen.dart';

class SmallTalkScreen extends StatefulWidget {
  const SmallTalkScreen({
    super.key,
    this.messages = _defaultMessages,
    this.useMockFlow = false,
  });

  final List<SmallTalkMessage> messages;
  final bool useMockFlow;

  static const _defaultMessages = <SmallTalkMessage>[
    SmallTalkMessage(
      text: '안녕하세요! 저는 딸랑구예요 :)\n오늘도 반갑게 인사하러 왔어요!',
      highlightWords: ['딸랑구'],
    ),
    SmallTalkMessage(
      text: '성함이 어떻게 되세요?\n예를 들어 "내 이름은 딸랑구"처럼 말해보세요.',
      highlightWords: ['성함'],
    ),
  ];

  @override
  State<SmallTalkScreen> createState() => _SmallTalkScreenState();
}

class _SmallTalkScreenState extends State<SmallTalkScreen> {
  final VoiceService _voiceService = VoiceService.instance;
  final UserRepository _userRepository = UserRepository();
  final SpokenSentencePlayer _sentencePlayer = SpokenSentencePlayer();

  int _currentIndex = 0;
  bool _isRecording = false;
  bool _isSubmitting = false;
  bool _isSpeaking = false;
  bool _didAutoAdvanceGreeting = false;
  String? _errorMessage;
  String? _transcriptPreview;
  String? _currentSpokenSentence;

  bool get _isLastMessage => _currentIndex == widget.messages.length - 1;
  VoiceInputState get _voiceInputState => _isRecording
      ? VoiceInputState.listening
      : (_isSubmitting || _isSpeaking
            ? VoiceInputState.inactive
            : VoiceInputState.active);

  @override
  void initState() {
    super.initState();
    unawaited(_bootstrapVoice());
  }

  @override
  void dispose() {
    _sentencePlayer.cancel();
    unawaited(_voiceService.stopSpeaking());
    if (_isRecording) {
      unawaited(_voiceService.cancelRecording());
    }
    super.dispose();
  }

  Future<void> _bootstrapVoice() async {
    try {
      await _voiceService.init();
    } catch (_) {}
    _scheduleCurrentMessageSpeech();
  }

  Future<void> _speakCurrentMessage() async {
    final message = widget.messages[_currentIndex].text.trim();
    if (message.isEmpty) {
      return;
    }

    // 메시지 안의 '\n'이 이미 문장 경계다(예: 인사 두 문장). 예전엔 전체
    // 문구를 한 번에 speak()로 넘기면서 화면(DialogueBubble의 cyclePages,
    // 고정 타이머)만 따로 문장을 순환해서 화면과 음성이 서로 다른
    // 타이밍으로 진행됐다. 이제 SpokenSentencePlayer가 "문장 표시 → 그
    // 문장 TTS 완료까지 대기 → 다음 문장" 순서를 직접 맞춘다.
    final sentences = message
        .split('\n')
        .map((sentence) => sentence.trim())
        .where((sentence) => sentence.isNotEmpty)
        .toList(growable: false);

    setState(() {
      _isSpeaking = true;
      _currentSpokenSentence = sentences.isEmpty ? message : sentences.first;
    });
    try {
      await _sentencePlayer.play(
        sentences.isEmpty ? [message] : sentences,
        isMounted: () => mounted,
        onSentence: (sentence) {
          if (mounted) {
            setState(() => _currentSpokenSentence = sentence);
          }
        },
      );
    } catch (_) {
      // Voice playback is best-effort.
    } finally {
      if (mounted) {
        setState(() => _isSpeaking = false);
      }
    }

    if (!_didAutoAdvanceGreeting && !_isLastMessage && mounted) {
      _didAutoAdvanceGreeting = true;
      await Future<void>.delayed(const Duration(milliseconds: 500));
      if (!mounted) {
        return;
      }
      setState(() => _currentIndex = widget.messages.length - 1);
      _scheduleCurrentMessageSpeech();
    }
  }

  void _scheduleCurrentMessageSpeech() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) {
        return;
      }
      unawaited(_speakCurrentMessage());
    });
  }

  Future<void> _toggleRecording() async {
    if (_isSubmitting) {
      return;
    }

    if (!_isLastMessage) {
      setState(() => _currentIndex = widget.messages.length - 1);
      _scheduleCurrentMessageSpeech();
      return;
    }

    if (_isRecording) {
      await _stopRecordingAndUseTranscript();
      return;
    }

    setState(() {
      _errorMessage = null;
      _transcriptPreview = null;
      _isRecording = true;
    });

    try {
      await _voiceService.startRecording();
    } catch (error) {
      if (!mounted) {
        return;
      }
      setState(() {
        _isRecording = false;
        _errorMessage = '마이크를 시작하지 못했어요. 다시 한 번 말씀해주세요.';
      });
    }
  }

  Future<void> _stopRecordingAndUseTranscript() async {
    setState(() {
      _errorMessage = null;
      _isRecording = false;
    });

    try {
      final transcript = await _voiceService.stopRecordingAndTranscribe();
      final trimmed = transcript.trim();
      if (!mounted) {
        return;
      }
      if (trimmed.isEmpty) {
        setState(() {
          _errorMessage = '이름을 잘 듣지 못했어요. 한 번 더 말씀해주세요.';
        });
        return;
      }

      setState(() => _transcriptPreview = trimmed);
      await _submitName(trimmed);
    } catch (_) {
      if (!mounted) {
        return;
      }
      setState(() {
        _errorMessage = '음성 인식 중 문제가 생겼어요. 다시 한 번 말씀해주세요.';
      });
    }
  }

  String _normalizeSubmittedName(String rawName) {
    var normalized = rawName.trim();
    if (normalized.isEmpty) {
      return normalized;
    }

    normalized = normalized.replaceAll(RegExp(r'[\"“”‘’]'), '');
    normalized = normalized.replaceAll(RegExp(r'[.!?,]'), '').trim();

    final patterns = <RegExp>[
      RegExp(r'^(?:제|저|내)\s*이름은\s*(.+)$'),
      RegExp(r'^이름은\s*(.+)$'),
      RegExp(r'^(?:저는|나는|전)\s*(.+)$'),
    ];

    for (final pattern in patterns) {
      final match = pattern.firstMatch(normalized);
      if (match != null) {
        normalized = match.group(1)?.trim() ?? normalized;
        break;
      }
    }

    normalized = normalized.replaceFirst(RegExp(r'(?:입니다|이에요|예요)$'), '');

    if (rawName.contains('나는') ||
        rawName.contains('저는') ||
        rawName.contains('이름은')) {
      normalized = normalized.replaceFirst(RegExp(r'(?:이야|야)$'), '');
    }

    return normalized.trim();
  }

  Future<void> _submitExampleReply(String utterance) async {
    if (_isSubmitting || _isRecording || _isSpeaking) {
      return;
    }

    setState(() {
      _errorMessage = null;
      _transcriptPreview = utterance;
    });

    await _submitName(utterance);
  }

  Future<void> _submitName(String rawName) async {
    final name = _normalizeSubmittedName(rawName);
    if (name.isEmpty || _isSubmitting) {
      return;
    }

    setState(() {
      _isSubmitting = true;
      _errorMessage = null;
    });

    try {
      if (widget.useMockFlow) {
        await LocalStorage.clearUserId();
        await LocalStorage.saveUserName(name);
      } else {
        final user = await _userRepository.createUser(name: name);
        await LocalStorage.saveUserId(user.userId);
        await LocalStorage.saveUserName(user.name);
      }

      if (!mounted) {
        return;
      }

      Navigator.of(context).pushReplacement(
        MaterialPageRoute<void>(
          builder: (_) => AgentSmallTalkScreen(
            userName: name,
            useMockFlow: widget.useMockFlow,
          ),
        ),
      );
    } catch (error) {
      if (!mounted) {
        return;
      }
      setState(() {
        _errorMessage = error.toString().replaceFirst('Exception: ', '');
      });
    } finally {
      if (mounted) {
        setState(() => _isSubmitting = false);
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final currentMessage = widget.messages[_currentIndex];
    final canTapExampleReplies =
        !_isSubmitting && !_isSpeaking && !_isRecording;
    final responsive = context.responsive;

    return ScreenFrame(
      preset: LayoutPreset.conversation,
      child: LayoutBuilder(
        builder: (context, constraints) {
          final compact =
              constraints.maxHeight < 820 || responsive.usesCondensedLayout;
          // 예전엔 마지막 메시지(이름 입력) 상태와 첫 인사 상태의 캐릭터
          // 크기가 서로 다른 공식을 썼고, agent_smalltalk_screen 등 다른
          // 대화형 화면과도 계산식이 달라 같은 그림인데도 화면마다 크기가
          // 달라 보였다. 이제 모든 대화형 화면이 공유하는
          // conversationCharacterHeight()로 통일한다.
          final characterHeight = responsive.conversationCharacterHeight();
          final bubbleMinHeight = responsive.bound(
            responsive.heightScaled(
              compact ? 150 : 172,
              minFactor: 0.84,
              maxFactor: 1.0,
            ),
            min: 136,
            max: 172,
          );
          final bubbleVerticalPadding = responsive.bound(
            responsive.heightScaled(
              compact ? AppSpacing.lg : AppSpacing.xl,
              minFactor: 0.74,
              maxFactor: 1.0,
            ),
            min: AppSpacing.md,
            max: AppSpacing.xl,
          );
          final titleSize = responsive.bound(
            responsive.font(compact ? 24 : 26, minFactor: 0.94, maxFactor: 1.0),
            min: 22,
            max: 26,
          );

          return Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              DialogueBubble(
                contentKey: ValueKey(
                  'message-$_currentIndex-${_currentSpokenSentence ?? ''}',
                ),
                animateTextChanges: true,
                cyclePages: false,
                text: _currentSpokenSentence ?? currentMessage.text,
                highlightedWords: currentMessage.highlightWords,
                minHeight: bubbleMinHeight,
                padding: EdgeInsets.symmetric(
                  horizontal: AppSpacing.lg,
                  vertical: bubbleVerticalPadding,
                ),
                style: AppTextStyles.title2.copyWith(
                  color: AppColors.textStrong,
                  height: 1.35,
                  fontSize: titleSize,
                  fontWeight: FontWeight.w700,
                ),
                emphasizedStyle: AppTextStyles.title2.copyWith(
                  color: AppColors.primaryPinkDark,
                  height: 1.35,
                  fontSize: titleSize,
                  fontWeight: FontWeight.w800,
                ),
              ),
              const SizedBox(height: AppSpacing.lg),
              Expanded(
                child: LayoutBuilder(
                  builder: (context, bodyConstraints) {
                    return SingleChildScrollView(
                      keyboardDismissBehavior:
                          ScrollViewKeyboardDismissBehavior.onDrag,
                      physics: const ClampingScrollPhysics(),
                      child: ConstrainedBox(
                        constraints: BoxConstraints(
                          minHeight: bodyConstraints.maxHeight,
                        ),
                        child: Column(
                          mainAxisAlignment: _isLastMessage
                              ? MainAxisAlignment.start
                              : MainAxisAlignment.end,
                          children: [
                            Center(
                              child: Image.asset(
                                'assets/images/character/full/ddalangoo_smalltalk.png',
                                height: characterHeight,
                                fit: BoxFit.contain,
                              ),
                            ),
                            if (_isLastMessage) ...[
                              // "성함을 말씀해주세요." 회색 안내 텍스트는 삭제했다.
                              // 같은 안내는 이미 위쪽 말풍선(현재 메시지)이
                              // 전달하고 있다.
                              if (_transcriptPreview != null &&
                                  _transcriptPreview!.isNotEmpty) ...[
                                const SizedBox(height: AppSpacing.sm),
                                Text(
                                  '듣고 있는 이름: ${_transcriptPreview!}',
                                  textAlign: TextAlign.center,
                                  style: AppTextStyles.caption.copyWith(
                                    color: AppColors.primaryPinkDark,
                                    fontWeight: FontWeight.w700,
                                  ),
                                ),
                              ],
                              const SizedBox(height: AppSpacing.md),
                            ],
                          ],
                        ),
                      ),
                    );
                  },
                ),
              ),
              if (_errorMessage != null) ...[
                _ErrorText(message: _errorMessage!),
                const SizedBox(height: AppSpacing.md),
              ],
              VoicePanel(
                state: _voiceInputState,
                onPressed: _toggleRecording,
                // 실제 서비스에서는 예시 답변 칩을 없애고 같은 예시를 딸랑구
                // 멘트("예를 들어 ...처럼 말해보세요")에 녹였다. 에뮬레이터에서
                // 빠르게 테스트할 수 있도록 mock flow에서는 칩을 유지한다.
                leadingReply: !widget.useMockFlow
                    ? null
                    : VoiceExampleReplyChip(
                        label: '내 이름은\n딸랑구',
                        textAlign: TextAlign.right,
                        onTap: canTapExampleReplies
                            ? () => _submitExampleReply('내 이름은 딸랑구')
                            : null,
                      ),
                trailingReply: !widget.useMockFlow
                    ? null
                    : VoiceExampleReplyChip(
                        label: '나는\n딸랑구야',
                        textAlign: TextAlign.left,
                        onTap: canTapExampleReplies
                            ? () => _submitExampleReply('나는 딸랑구야')
                            : null,
                      ),
              ),
              const SizedBox(height: AppSpacing.md),
              EndConversationButton(
                fullWidth: true,
                variant: EndConversationButtonVariant.dark,
                onPressed: () {
                  Navigator.of(
                    context,
                  ).pushNamedAndRemoveUntil(AppRoutes.home, (route) => false);
                },
              ),
            ],
          );
        },
      ),
    );
  }
}

class SmallTalkMessage {
  const SmallTalkMessage({
    required this.text,
    this.highlightWords = const <String>[],
  });

  final String text;
  final List<String> highlightWords;
}

class _ErrorText extends StatelessWidget {
  const _ErrorText({required this.message});

  final String message;

  @override
  Widget build(BuildContext context) {
    return Text(
      message,
      textAlign: TextAlign.center,
      style: AppTextStyles.body2.copyWith(
        color: AppColors.primaryPinkDark,
        fontWeight: FontWeight.w700,
      ),
    );
  }
}
