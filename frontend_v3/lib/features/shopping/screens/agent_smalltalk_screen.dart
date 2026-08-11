import 'dart:async';

import 'package:flutter/material.dart';

import '../../../app/theme/app_colors.dart';
import '../../../app/theme/app_spacing.dart';
import '../../../app/theme/app_text_styles.dart';
import '../../../core/services/voice_service.dart';
import '../../../core/storage/local_storage.dart';
import '../../../data/models/agent_model.dart';
import '../../../data/repositories/agent_repository.dart';
import '../../../shared/layout/layout_presets.dart';
import '../../../shared/layout/screen_frame.dart';
import '../../../shared/widgets/dialogue_bubble.dart';
import '../../../shared/widgets/end_conversation_button.dart';
import '../../../shared/widgets/primary_button.dart';
import '../../../shared/widgets/voice_input_button.dart';
import '../../platform_check/screens/platform_check_screen.dart';

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
  bool _isRecording = false;
  bool _isSubmitting = false;
  bool _isSpeaking = false;
  bool _isNavigatingToPurchaseHistory = false;
  String? _errorMessage;
  String? _transcriptPreview;

  VoiceInputState get _voiceInputState => _isRecording
      ? VoiceInputState.listening
      : (_isLoading ||
                _isSubmitting ||
                _isSpeaking ||
                _isNavigatingToPurchaseHistory
            ? VoiceInputState.inactive
            : VoiceInputState.active);

  @override
  void initState() {
    super.initState();
    unawaited(_startAgentSmallTalk());
  }

  @override
  void dispose() {
    unawaited(_voiceService.stopSpeaking());
    if (_isRecording) {
      unawaited(_voiceService.cancelRecording());
    }
    super.dispose();
  }

  Future<void> _startAgentSmallTalk() async {
    setState(() {
      _isLoading = true;
      _errorMessage = null;
    });

    try {
      await _voiceService.init();
      final userId = await LocalStorage.getUserId();
      if (userId == null) {
        throw StateError('사용자 정보를 찾지 못했어요.');
      }

      final response = widget.useMockFlow
          ? _mockSmallTalkResponse()
          : await _agentRepository.startShopping(
              userId: userId,
              message: '안녕하세요, 제 이름은 ${widget.userName}이에요.',
            );

      if (!mounted) {
        return;
      }

      setState(() {
        _response = response;
        _isLoading = false;
      });
      await _speakAndHandleUiCommand(response);
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

  Future<void> _toggleRecording() async {
    if (_isLoading || _isSubmitting || _isSpeaking) {
      return;
    }

    if (_isRecording) {
      await _stopRecordingAndSubmitReply();
      return;
    }

    setState(() {
      _errorMessage = null;
      _transcriptPreview = null;
      _isRecording = true;
    });

    try {
      await _voiceService.startRecording();
    } catch (_) {
      if (!mounted) {
        return;
      }
      setState(() {
        _isRecording = false;
        _errorMessage = '마이크를 시작하지 못했어요. 다시 한 번 말씀해주세요.';
      });
    }
  }

  Future<void> _stopRecordingAndSubmitReply() async {
    setState(() {
      _isRecording = false;
      _errorMessage = null;
    });

    try {
      final transcript = await _voiceService.stopRecordingAndTranscribe();
      final trimmed = transcript.trim();
      if (!mounted) {
        return;
      }
      if (trimmed.isEmpty) {
        setState(() {
          _errorMessage = '잘 듣지 못했어요. 한 번 더 말씀해주세요.';
        });
        return;
      }

      setState(() => _transcriptPreview = trimmed);
      await _submitSmallTalkReply(trimmed);
    } catch (_) {
      if (!mounted) {
        return;
      }
      setState(() {
        _errorMessage = '음성 인식 중 문제가 생겼어요. 다시 한 번 말씀해주세요.';
      });
    }
  }

  Future<void> _submitSmallTalkReply(String message) async {
    final conversationId = _response?.conversationId;
    if (conversationId == null || conversationId < 0 || _isSubmitting) {
      return;
    }

    setState(() {
      _isSubmitting = true;
      _errorMessage = null;
    });

    try {
      final response = await _agentRepository.sendMessage(
        conversationId: conversationId,
        message: message,
      );
      if (!mounted) {
        return;
      }
      setState(() {
        _response = response;
      });
      await _speakAndHandleUiCommand(response);
    } catch (_) {
      if (!mounted) {
        return;
      }
      setState(() {
        _errorMessage = '대화를 이어가지 못했어요. 잠시 후 다시 말씀해주세요.';
      });
    } finally {
      if (mounted) {
        setState(() => _isSubmitting = false);
      }
    }
  }

  Future<void> _speakAndHandleUiCommand(AgentResponse response) async {
    await _speak(response.assistantMessage);
    if (_shouldStartPurchaseHistoryCollection(response)) {
      _continueToPurchaseHistory();
    }
  }

  bool _shouldStartPurchaseHistoryCollection(AgentResponse response) {
    final command = response.uiCommand;
    if (command is! Map) {
      return false;
    }
    return command['type']?.toString() == 'start_purchase_history_collection';
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
          Align(
            alignment: Alignment.topRight,
            child: EndConversationButton(
              compact: true,
              onPressed: _continueToPurchaseHistory,
            ),
          ),
          const SizedBox(height: AppSpacing.md),
          DialogueBubble(
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
                height: 330,
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
          if (_transcriptPreview != null &&
              _transcriptPreview!.isNotEmpty) ...[
            Text(
              '방금 말씀: $_transcriptPreview',
              textAlign: TextAlign.center,
              style: AppTextStyles.caption.copyWith(
                color: AppColors.primaryPinkDark,
                fontWeight: FontWeight.w700,
              ),
            ),
            const SizedBox(height: AppSpacing.md),
          ],
          VoiceInputButton(
            state: _voiceInputState,
            onPressed: _toggleRecording,
            activeLabel: '답장하기',
            inactiveLabel: _isNavigatingToPurchaseHistory
                ? '구매이력으로 넘어가고 있어요'
                : (_isSubmitting ? '답장을 보내고 있어요' : '딸랑구가 말하고 있어요'),
            diameter: 88,
            iconSize: 38,
            labelSpacing: AppSpacing.sm,
          ),
          const SizedBox(height: AppSpacing.md),
          PrimaryButton(
            label: _isNavigatingToPurchaseHistory
                ? '구매이력으로 이동 중...'
                : '스몰토크가 끝나면 자동으로 넘어갈게요',
            icon: Icons.shopping_bag_rounded,
            onPressed: null,
          ),
        ],
      ),
    );
  }
}
