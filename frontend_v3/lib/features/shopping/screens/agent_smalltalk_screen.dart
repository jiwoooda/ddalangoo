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
import 'smalltalk_purchase_history_bridge_screen.dart';

/// 이름 입력 이후 LangGraph smalltalk_agent와 이어서 대화하는 화면.
/// 구매이력 자동화는 백엔드가 uiCommand로 명시적으로 요청할 때만 시작한다.
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
  int? _conversationId;
  bool _isLoading = true;
  bool _isSpeaking = false;
  bool _isRecording = false;
  bool _isSubmitting = false;
  bool _isNavigatingToPurchaseHistory = false;
  int _mockReplyCount = 0;
  String? _errorMessage;
  String? _transcriptPreview;
  String? _visibleAssistantMessage;

  @override
  void initState() {
    super.initState();
    unawaited(_startAgentSmallTalk());
  }

  @override
  void dispose() {
    unawaited(_voiceService.cancelRecording());
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

      await _handleAgentResponse(response);
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
          '${widget.userName}님 반가워요. 바로 구매이력부터 보기 전에, 어제는 어떤 음식 드셨어요?',
    );
  }

  AgentResponse _mockSmallTalkReply(String userMessage) {
    _mockReplyCount += 1;
    final shouldStartPurchaseHistory = _mockReplyCount >= 1;
    final assistantMessage = shouldStartPurchaseHistory
        ? '좋아요. ${widget.userName}님의 취향을 조금 알았어요. 이제 쇼핑 앱과 구매 이력을 확인해볼게요.'
        : '좋아요. 조금만 더 물어볼게요. 요즘 자주 먹고 싶은 메뉴가 있어요?';

    return AgentResponse(
      conversationId: -1,
      status: 'smalltalk',
      stage: shouldStartPurchaseHistory ? 'purchase_history_ready' : 'idle',
      assistantMessage: assistantMessage,
      uiCommand: shouldStartPurchaseHistory
          ? <String, dynamic>{
              'type': 'start_purchase_history_collection',
              'reason': 'mock_onboarding_complete',
              'lastUserMessage': userMessage,
            }
          : null,
    );
  }

  Future<void> _handleAgentResponse(AgentResponse response) async {
    if (!mounted) {
      return;
    }
    final responseSentences = _sentencesForResponse(response);
    setState(() {
      _response = response;
      _conversationId = response.conversationId;
      _visibleAssistantMessage = responseSentences.isNotEmpty
          ? responseSentences.first
          : response.assistantMessage.trim();
      _isLoading = false;
      _isSubmitting = false;
      _errorMessage = null;
    });
    await _speakSentences(responseSentences);
    if (_shouldStartPurchaseHistory(response)) {
      _continueToPurchaseHistory();
    }
  }

  List<String> _sentencesForResponse(AgentResponse response) {
    if (response.messageSentences.isNotEmpty) {
      return response.messageSentences;
    }

    final segmentSentences = response.speechSegments
        .map((segment) => segment.text.trim())
        .where((sentence) => sentence.isNotEmpty)
        .toList(growable: false);
    if (segmentSentences.isNotEmpty) {
      return segmentSentences;
    }

    return _fallbackSplitSentences(response.assistantMessage);
  }

  List<String> _fallbackSplitSentences(String message) {
    final normalized = message.trim();
    if (normalized.isEmpty) {
      return const <String>[];
    }

    final matches = RegExp(r'[^.!?。？！]+[.!?。？！]?').allMatches(normalized);
    final sentences = matches
        .map((match) => match.group(0)?.trim() ?? '')
        .where((sentence) => sentence.isNotEmpty)
        .toList(growable: false);
    return sentences.isEmpty ? <String>[normalized] : sentences;
  }

  Future<void> _speakSentences(List<String> sentences) async {
    final queue = sentences
        .map((sentence) => sentence.trim())
        .where((sentence) => sentence.isNotEmpty)
        .toList(growable: false);
    if (queue.isEmpty) {
      return;
    }

    setState(() => _isSpeaking = true);
    try {
      for (final sentence in queue) {
        if (!mounted) {
          return;
        }
        setState(() => _visibleAssistantMessage = sentence);
        try {
          await _voiceService.speak(sentence);
        } catch (_) {
          // TTS는 진행 보조 기능이라 실패해도 다음 문장/단계 이동은 막지 않는다.
        }
      }
    } finally {
      if (mounted) {
        setState(() => _isSpeaking = false);
      }
    }
  }

  bool _shouldStartPurchaseHistory(AgentResponse response) {
    final uiCommand = response.uiCommand;
    if (uiCommand is! Map) {
      return false;
    }
    return uiCommand['type']?.toString() == 'start_purchase_history_collection';
  }

  VoiceInputState get _voiceInputState {
    if (_isRecording) {
      return VoiceInputState.listening;
    }
    if (_isLoading ||
        _isSpeaking ||
        _isSubmitting ||
        _isNavigatingToPurchaseHistory) {
      return VoiceInputState.inactive;
    }
    return VoiceInputState.active;
  }

  Future<void> _toggleRecording() async {
    if (_isLoading ||
        _isSpeaking ||
        _isSubmitting ||
        _isNavigatingToPurchaseHistory) {
      return;
    }

    if (_isRecording) {
      await _stopRecordingAndSendMessage();
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

  Future<void> _stopRecordingAndSendMessage() async {
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
          _errorMessage = '말씀을 잘 듣지 못했어요. 한 번 더 말해줄래요?';
        });
        return;
      }

      setState(() => _transcriptPreview = trimmed);
      await _sendSmallTalkMessage(trimmed);
    } catch (_) {
      if (!mounted) {
        return;
      }
      setState(() {
        _errorMessage = '음성 인식 중 문제가 생겼어요. 다시 한 번 말씀해주세요.';
      });
    }
  }

  Future<void> _sendSmallTalkMessage(String message) async {
    final conversationId = _conversationId;
    if (conversationId == null && !widget.useMockFlow) {
      setState(() {
        _errorMessage = '대화 정보를 찾지 못했어요. 처음부터 다시 시작해주세요.';
      });
      return;
    }

    setState(() {
      _isSubmitting = true;
      _errorMessage = null;
    });

    try {
      final response = widget.useMockFlow
          ? _mockSmallTalkReply(message)
          : await _agentRepository.sendMessage(
              conversationId: conversationId!,
              message: message,
            );
      await _handleAgentResponse(response);
    } catch (_) {
      if (!mounted) {
        return;
      }
      setState(() {
        _isSubmitting = false;
        _errorMessage = '딸랑구에게 답변을 전달하지 못했어요. 다시 한 번 말씀해주세요.';
      });
    }
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
        builder: (_) => SmallTalkPurchaseHistoryBridgeScreen(
          userName: widget.userName,
          useMockFlow: widget.useMockFlow,
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final message =
        _visibleAssistantMessage?.trim() ?? _response?.assistantMessage.trim();
    final transcriptPreview = _transcriptPreview?.trim();

    return ScreenFrame(
      preset: LayoutPreset.conversation,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          DialogueBubble(
            contentKey: ValueKey('$_isLoading-${message ?? ''}'),
            cyclePages: false,
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
          if (transcriptPreview != null && transcriptPreview.isNotEmpty) ...[
            Text(
              '내 답변: $transcriptPreview',
              textAlign: TextAlign.center,
              style: AppTextStyles.body2.copyWith(
                color: AppColors.textMuted,
                fontWeight: FontWeight.w700,
              ),
            ),
            const SizedBox(height: AppSpacing.md),
          ],
          VoicePanel(state: _voiceInputState, onPressed: _toggleRecording),
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
