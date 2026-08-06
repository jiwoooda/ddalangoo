import 'dart:async';

import 'package:flutter/material.dart';

import '../../../app/theme/app_colors.dart';
import '../../../app/theme/app_radii.dart';
import '../../../app/theme/app_spacing.dart';
import '../../../app/theme/app_text_styles.dart';
import '../../../core/services/voice_service.dart';
import '../../../core/storage/local_storage.dart';
import '../../../data/repositories/agent_repository.dart';
import '../../../shared/layout/layout_presets.dart';
import '../../../shared/layout/screen_frame.dart';
import '../../../shared/widgets/dialogue_bubble.dart';
import '../../../shared/widgets/end_conversation_button.dart';
import '../../../shared/widgets/primary_button.dart';
import '../../../shared/widgets/voice_input_button.dart';
import '../../platform_check/screens/platform_check_screen.dart';

class SmallTalkScreen extends StatefulWidget {
  const SmallTalkScreen({super.key, this.messages = _defaultMessages});

  final List<SmallTalkMessage> messages;

  static const _defaultMessages = <SmallTalkMessage>[
    SmallTalkMessage(
      text: '안녕하세요! 저는 딸랑구예요 :)\n오늘도 반갑게 인사하러 왔어요!',
      highlightWords: ['딸랑구'],
    ),
    SmallTalkMessage(text: '성함이 어떻게 되세요?', highlightWords: ['성함']),
  ];

  @override
  State<SmallTalkScreen> createState() => _SmallTalkScreenState();
}

class _SmallTalkScreenState extends State<SmallTalkScreen> {
  final VoiceService _voiceService = VoiceService.instance;
  final UserRepository _userRepository = UserRepository();
  final TextEditingController _nameController = TextEditingController();
  final FocusNode _nameFocusNode = FocusNode();

  int _currentIndex = 0;
  bool _isRecording = false;
  bool _isSubmitting = false;
  bool _isSpeaking = false;
  bool _didAutoAdvanceGreeting = false;
  String? _errorMessage;
  String? _transcriptPreview;

  bool get _isLastMessage => _currentIndex == widget.messages.length - 1;

  @override
  void initState() {
    super.initState();
    unawaited(_bootstrapVoice());
  }

  @override
  void dispose() {
    unawaited(_voiceService.stopSpeaking());
    if (_isRecording) {
      unawaited(_voiceService.cancelRecording());
    }
    _nameController.dispose();
    _nameFocusNode.dispose();
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

    setState(() => _isSpeaking = true);
    try {
      await _voiceService.speak(message);
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
        _errorMessage = '마이크를 시작하지 못했어요. 입력창으로 이름을 적어주세요.';
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
          _errorMessage = '이름을 잘 듣지 못했어요. 한 번 더 말씀하시거나 입력창에 적어주세요.';
        });
        return;
      }

      _nameController.text = trimmed;
      _nameController.selection = TextSelection.fromPosition(
        TextPosition(offset: _nameController.text.length),
      );
      setState(() => _transcriptPreview = trimmed);
      await _submitName(trimmed);
    } catch (_) {
      if (!mounted) {
        return;
      }
      setState(() {
        _errorMessage = '음성 인식 중 문제가 생겼어요. 입력창으로 이름을 적어주세요.';
      });
    }
  }

  Future<void> _submitTypedName() async {
    await _submitName(_nameController.text.trim());
  }

  Future<void> _submitName(String rawName) async {
    final name = rawName.trim();
    if (name.isEmpty || _isSubmitting) {
      return;
    }

    setState(() {
      _isSubmitting = true;
      _errorMessage = null;
    });

    try {
      final user = await _userRepository.createUser(name: name);
      await LocalStorage.saveUserId(user.userId);

      if (!mounted) {
        return;
      }

      setState(() => _isSpeaking = true);
      try {
        await _voiceService.speak('$name님 반가워요. 어떤 쇼핑 앱을 쓰시는지 확인할게요.');
      } catch (_) {
        // Voice playback is best-effort.
      } finally {
        if (mounted) {
          setState(() => _isSpeaking = false);
        }
      }
      if (!mounted) {
        return;
      }
      Navigator.of(context).pushReplacement(
        MaterialPageRoute<void>(
          builder: (_) => PlatformCheckScreen(userName: name),
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

    return ScreenFrame(
      preset: LayoutPreset.conversation,
      child: Column(
        children: [
          Row(
            children: [
              _BackButton(onPressed: () => Navigator.of(context).maybePop()),
              const Spacer(),
              EndConversationButton(
                compact: true,
                onPressed: () => Navigator.of(context).maybePop(),
              ),
            ],
          ),
          const SizedBox(height: AppSpacing.lg),
          Expanded(
            child: Column(
              children: [
                DialogueBubble(
                  contentKey: ValueKey('message-$_currentIndex'),
                  animateTextChanges: true,
                  text: currentMessage.text,
                  highlightedWords: currentMessage.highlightWords,
                  style: AppTextStyles.title2.copyWith(
                    color: AppColors.textStrong,
                    height: 1.35,
                  ),
                ),
                const SizedBox(height: AppSpacing.xxl),
                Expanded(
                  child: Center(
                    child: Image.asset(
                      'assets/images/character/full/ddalangoo_smalltalk.png',
                      height: 280,
                      fit: BoxFit.contain,
                    ),
                  ),
                ),
              ],
            ),
          ),
          if (_isLastMessage) ...[
            if (_transcriptPreview != null &&
                _transcriptPreview!.isNotEmpty) ...[
              Container(
                width: double.infinity,
                padding: const EdgeInsets.all(AppSpacing.md),
                decoration: BoxDecoration(
                  color: AppColors.surface,
                  borderRadius: BorderRadius.circular(AppRadii.lg),
                  border: Border.all(color: AppColors.border),
                ),
                child: Text(
                  '음성 인식: ${_transcriptPreview!}',
                  style: AppTextStyles.body2.copyWith(
                    color: AppColors.textPrimary,
                    fontWeight: FontWeight.w700,
                  ),
                ),
              ),
              const SizedBox(height: AppSpacing.md),
            ],
            _NameComposer(
              controller: _nameController,
              focusNode: _nameFocusNode,
              enabled: !_isSubmitting && !_isRecording,
              onSubmitted: _submitTypedName,
            ),
            const SizedBox(height: AppSpacing.lg),
            PrimaryButton(
              label: _isSubmitting ? '확인 중...' : '이 이름으로 시작하기',
              onPressed: _isSubmitting || _isRecording
                  ? null
                  : _submitTypedName,
            ),
            const SizedBox(height: AppSpacing.md),
          ],
          if (_errorMessage != null) ...[
            _ErrorText(message: _errorMessage!),
            const SizedBox(height: AppSpacing.md),
          ],
          VoiceInputButton(
            state: _isRecording
                ? VoiceInputState.listening
                : (_isSubmitting || _isSpeaking
                      ? VoiceInputState.inactive
                      : VoiceInputState.active),
            onPressed: _toggleRecording,
          ),
        ],
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

class _BackButton extends StatelessWidget {
  const _BackButton({required this.onPressed});

  final VoidCallback onPressed;

  @override
  Widget build(BuildContext context) {
    return InkWell(
      onTap: onPressed,
      borderRadius: BorderRadius.circular(AppRadii.pill),
      child: Container(
        width: 44,
        height: 44,
        decoration: BoxDecoration(
          color: AppColors.surfaceMuted,
          borderRadius: BorderRadius.circular(AppRadii.pill),
          border: Border.all(color: AppColors.border),
        ),
        child: const Icon(
          Icons.arrow_back_ios_new_rounded,
          size: 18,
          color: AppColors.textPrimary,
        ),
      ),
    );
  }
}

class _NameComposer extends StatelessWidget {
  const _NameComposer({
    required this.controller,
    required this.focusNode,
    required this.enabled,
    required this.onSubmitted,
  });

  final TextEditingController controller;
  final FocusNode focusNode;
  final bool enabled;
  final VoidCallback onSubmitted;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: AppSpacing.md),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(AppRadii.pill),
        border: Border.all(color: AppColors.border),
      ),
      child: Row(
        children: [
          const Icon(Icons.edit_rounded, color: AppColors.textMuted),
          const SizedBox(width: AppSpacing.sm),
          Expanded(
            child: TextField(
              controller: controller,
              focusNode: focusNode,
              enabled: enabled,
              textInputAction: TextInputAction.done,
              onSubmitted: (_) => onSubmitted(),
              decoration: InputDecoration(
                hintText: '이름을 입력해주세요',
                border: InputBorder.none,
                hintStyle: AppTextStyles.body2,
              ),
              style: AppTextStyles.body1.copyWith(color: AppColors.textStrong),
            ),
          ),
          const SizedBox(width: AppSpacing.sm),
          InkWell(
            onTap: enabled ? onSubmitted : null,
            borderRadius: BorderRadius.circular(AppRadii.pill),
            child: Container(
              width: 42,
              height: 42,
              decoration: const BoxDecoration(
                shape: BoxShape.circle,
                color: AppColors.primaryPink,
              ),
              child: const Icon(
                Icons.arrow_forward_rounded,
                color: Colors.white,
              ),
            ),
          ),
        ],
      ),
    );
  }
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
