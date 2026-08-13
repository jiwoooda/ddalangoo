import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../app/routes.dart';
import '../../../app/theme/app_colors.dart';
import '../../../app/theme/app_radii.dart';
import '../../../app/theme/app_sizes.dart';
import '../../../app/theme/app_spacing.dart';
import '../../../app/theme/app_surface_styles.dart';
import '../../../app/theme/app_text_styles.dart';
import '../../../data/models/agent_model.dart';
import '../../../shared/layout/app_responsive.dart';
import '../../../shared/layout/layout_presets.dart';
import '../../../shared/layout/screen_frame.dart';
import '../../../shared/widgets/bottom_status_banner.dart';
import '../../../shared/widgets/dialogue_bubble.dart';
import '../../../shared/widgets/end_conversation_button.dart';
import '../../../shared/widgets/primary_button.dart';
import '../../../shared/widgets/shopping_progress_stepper.dart';
import '../../../shared/widgets/voice_input_button.dart';
import '../../../shared/widgets/voice_panel.dart';
import '../controllers/shopping_flow_controller.dart';
import '../controllers/shopping_flow_state.dart';
import '../models/shopping_flow_models.dart';
import 'shopping_webview_screen.dart';
import '../services/mock_shopping_flow_service.dart';
import '../services/shopping_flow_service.dart';

const int _pinPadCrossAxisCount = 3;
const int _pinPadRowCount = 4;
const double _pinPadChildAspectRatio = 1.45;
const double _baseDialogueSectionHeight = 148.0;
// 비밀번호 화면은 안내 문구가 한 줄로 짧아서 말풍선을 기본 높이로 두면
// 아래 PIN 키패드가 남은 공간을 다 못 쓰고 스크롤이 생겼다. 이 화면에서만
// 말풍선 세로 길이를 줄여서 키패드에 공간을 더 넘겨준다.
const double _passwordDialogueSectionHeight = 104.0;
// 대화 종료 버튼을 오버레이 음성 패널 아래 하단 전체너비 버튼으로 옮기면서
// 추가된 높이. _overlayBottomInsetFor 계산에도 반영해 스테이지 콘텐츠가
// 버튼에 가려지지 않게 한다.
const double _overlayEndButtonRowHeight =
    AppSizes.compactButtonHeight + AppSpacing.sm;

class ShoppingFlowScreen extends ConsumerStatefulWidget {
  const ShoppingFlowScreen({super.key, this.userName, this.service});

  final String? userName;
  final ShoppingFlowService? service;

  @override
  ConsumerState<ShoppingFlowScreen> createState() => _ShoppingFlowScreenState();
}

class _ShoppingFlowScreenState extends ConsumerState<ShoppingFlowScreen> {
  // 상태/비즈니스 로직(응답 반영, 폴링, automation task/result, 음성 녹음·재생,
  // 카트 수량 변경, PIN 입력)은 전부 ShoppingFlowController(Riverpod
  // StateNotifier)로 옮겼다. 아래 getter들은 이름을 예전 private 필드와 똑같이
  // 맞춘 "forwarding shim"이라, 이 파일의 나머지 build 코드(위젯 트리)는 거의
  // 손대지 않고 그대로 컨트롤러 상태를 읽는다.
  late final ShoppingFlowArgs _args = ShoppingFlowArgs(
    userName: widget.userName,
    service: widget.service,
  );

  ShoppingFlowController get _controller =>
      ref.read(shoppingFlowControllerProvider(_args).notifier);

  // ref.watch가 아니라 ref.read인 이유: 이 getter는 build() 안에서도 쓰이지만
  // _handlePendingWebviewTask처럼 addPostFrameCallback/ref.listen 콜백
  // (build 바깥)에서도 쓰인다. ref.watch는 build 중에만 호출할 수 있어서,
  // 리빌드 구독은 build()에서 명시적 ref.watch 한 번으로 따로 걸어준다.
  ShoppingFlowState get _flowState =>
      ref.read(shoppingFlowControllerProvider(_args));

  ShoppingFlowService get _service => _controller.service;

  AgentResponse? get _response => _flowState.response;
  ShoppingFlowViewStage get _viewStage => _flowState.viewStage;
  String? get _inlineError => _flowState.inlineError;
  String get _pinInput => _flowState.pinInput;
  bool get _isInitializing => _flowState.isInitializing;
  bool get _isSubmitting => _flowState.isSubmitting;
  bool get _isRecording => _flowState.isRecording;
  bool get _isSpeaking => _flowState.isSpeaking;
  bool get _isUpdatingCartQuantity => _flowState.isUpdatingCartQuantity;
  String? get _resolvedUserName => _flowState.resolvedUserName;
  String? get _visibleAssistantMessage => _flowState.visibleAssistantMessage;
  ShoppingAddressViewData? get _fallbackAddress => _flowState.fallbackAddress;

  // 웹뷰 기반 결제 자동화는 이제 accessibility automationTask 경로로 대체돼서
  // 실질적으로 도달하지 않는 레거시 흐름이다. Navigator가 필요해서 컨트롤러로
  // 옮기지 않고 여기 그대로 남겨뒀다.
  bool _isWebviewOpen = false;
  String? _lastWebviewCommandKey;
  final Set<String> _completedWebviewCommandKeys = <String>{};

  List<ShoppingCartItemViewData> get _effectiveCartItems =>
      _controller.effectiveCartItems;

  Future<void> _submitMessage(
    String message, {
    bool redactMessageForLogs = false,
  }) {
    return _controller.submitMessage(
      message,
      redactMessageForLogs: redactMessageForLogs,
    );
  }

  Future<void> _confirmAction(String action) =>
      _controller.confirmAction(action);

  Future<void> _toggleVoiceInput() => _controller.toggleVoiceInput();

  void _appendPinDigit(String digit) => _controller.appendPinDigit(digit);

  void _removePinDigit() => _controller.removePinDigit();

  Future<void> _submitPin() => _controller.submitPin();

  Future<void> _changeCartItemQuantity(
    ShoppingCartItemViewData item,
    int nextQuantity,
  ) {
    return _controller.changeCartItemQuantity(item, nextQuantity);
  }

  void _handlePendingWebviewTask() {
    final response = _response;
    if (!mounted || response == null) {
      return;
    }
    if (response.automationTask != null) {
      return;
    }

    final task = _service.extractWebviewTask(
      response,
      fallbackProduct: _service.extractSelectedProduct(response),
    );
    if (task == null) {
      return;
    }
    if (_completedWebviewCommandKeys.contains(task.commandKey)) {
      return;
    }
    if (_isWebviewOpen || _lastWebviewCommandKey == task.commandKey) {
      return;
    }

    _isWebviewOpen = true;
    _lastWebviewCommandKey = task.commandKey;
    WidgetsBinding.instance.addPostFrameCallback((_) async {
      if (!mounted) {
        _isWebviewOpen = false;
        return;
      }
      await Navigator.of(context).push(
        MaterialPageRoute<void>(
          builder: (_) => ShoppingWebviewScreen(
            url: task.url,
            platform: task.platform,
            shopName: task.shopName,
            assistantMessage: response.assistantMessage,
            task: task.task,
            orderId: task.orderId,
            paymentId: task.paymentId,
            productName: task.productName,
            quantity: task.quantity,
            canonicalProductUrl: task.canonicalProductUrl,
            onResult: (result, extraData) async {
              final nextResponse = await _service.sendWebviewResult(
                conversationId: response.conversationId,
                orderId: task.orderId,
                paymentId: task.paymentId,
                result: result,
                extraData: extraData,
              );
              if (!mounted) {
                return;
              }
              _completedWebviewCommandKeys.add(task.commandKey);
              _controller.applyResponse(nextResponse);
            },
          ),
        ),
      );
      _isWebviewOpen = false;
      if (_lastWebviewCommandKey == task.commandKey) {
        _lastWebviewCommandKey = null;
      }
    });
  }

  Future<void> _handleExit() async {
    await _controller.prepareForExit();
    if (!mounted) {
      return;
    }
    Navigator.of(
      context,
    ).pushNamedAndRemoveUntil(AppRoutes.home, (route) => false);
  }

  Future<void> _confirmExit() async {
    final shouldExit = await showDialog<bool>(
      context: context,
      builder: (dialogContext) {
        return AlertDialog(
          backgroundColor: Colors.white,
          surfaceTintColor: Colors.transparent,
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(AppRadii.xl),
          ),
          title: Text(
            '대화를 종료할까요?',
            style: AppTextStyles.body1.copyWith(fontWeight: FontWeight.w800),
          ),
          content: Text(
            '지금 진행 중인 쇼핑 흐름이 중단되고 홈 화면으로 돌아가요.',
            style: AppTextStyles.body2,
          ),
          // 기본 AlertDialog actions는 버튼이 다 안 들어가면 세로로
          // 쌓이면서 "계속하기"가 흐린 회색 글씨로 오른쪽 위에 작게
          // 붙어버렸다. 두 버튼을 같은 무게로 나란히 두 줄이 아니라 한
          // 줄에 배치한다.
          actions: [
            Row(
              children: [
                Expanded(
                  child: OutlinedButton(
                    onPressed: () => Navigator.of(dialogContext).pop(false),
                    style: OutlinedButton.styleFrom(
                      backgroundColor: Colors.white,
                      foregroundColor: AppColors.textPrimary,
                      side: const BorderSide(color: AppColors.border),
                      padding: const EdgeInsets.symmetric(
                        vertical: AppSpacing.sm,
                      ),
                      shape: RoundedRectangleBorder(
                        borderRadius: BorderRadius.circular(AppRadii.lg),
                      ),
                    ),
                    child: Text(
                      '계속하기',
                      style: AppTextStyles.caption.copyWith(
                        color: AppColors.textPrimary,
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                  ),
                ),
                const SizedBox(width: AppSpacing.sm),
                Expanded(
                  child: FilledButton(
                    onPressed: () => Navigator.of(dialogContext).pop(true),
                    style: FilledButton.styleFrom(
                      backgroundColor: AppColors.primaryPink,
                      foregroundColor: Colors.white,
                      padding: const EdgeInsets.symmetric(
                        vertical: AppSpacing.sm,
                      ),
                      shape: RoundedRectangleBorder(
                        borderRadius: BorderRadius.circular(AppRadii.lg),
                      ),
                    ),
                    child: Text(
                      '종료하기',
                      style: AppTextStyles.caption.copyWith(
                        color: Colors.white,
                        fontWeight: FontWeight.w800,
                      ),
                    ),
                  ),
                ),
              ],
            ),
          ],
        );
      },
    );

    if (shouldExit == true && mounted) {
      await _handleExit();
    }
  }

  bool get _supportsVoiceInput {
    switch (_viewStage) {
      case ShoppingFlowViewStage.askProduct:
      case ShoppingFlowViewStage.productSelection:
      case ShoppingFlowViewStage.quantitySelection:
      case ShoppingFlowViewStage.cartCompleted:
      case ShoppingFlowViewStage.addressConfirmation:
      case ShoppingFlowViewStage.paymentConfirmation:
      case ShoppingFlowViewStage.error:
        return true;
      case ShoppingFlowViewStage.searchingProduct:
      case ShoppingFlowViewStage.cartProcessing:
      case ShoppingFlowViewStage.paymentPassword:
      case ShoppingFlowViewStage.paymentProcessing:
      case ShoppingFlowViewStage.completed:
        return false;
    }
  }

  bool get _usesOverlayBottomSection {
    switch (_viewStage) {
      case ShoppingFlowViewStage.askProduct:
      case ShoppingFlowViewStage.searchingProduct:
      case ShoppingFlowViewStage.productSelection:
      case ShoppingFlowViewStage.quantitySelection:
      case ShoppingFlowViewStage.cartProcessing:
      case ShoppingFlowViewStage.cartCompleted:
      case ShoppingFlowViewStage.addressConfirmation:
      case ShoppingFlowViewStage.paymentConfirmation:
      case ShoppingFlowViewStage.paymentProcessing:
      case ShoppingFlowViewStage.error:
        return true;
      case ShoppingFlowViewStage.paymentPassword:
      case ShoppingFlowViewStage.completed:
        return false;
    }
  }

  double _dialogueSectionHeightFor(BuildContext context) {
    final responsive = context.responsive;
    final isPasswordStage = _viewStage == ShoppingFlowViewStage.paymentPassword;
    final baseHeight = isPasswordStage
        ? _passwordDialogueSectionHeight
        : _baseDialogueSectionHeight;
    return responsive.bound(
      responsive.heightScaled(
        baseHeight,
        minFactor: 0.82,
        maxFactor: 1.0,
      ),
      min: isPasswordStage ? 88 : 122,
      max: baseHeight,
    );
  }

  double _overlayBottomInsetFor(BuildContext context) {
    return switch (_viewStage) {
      ShoppingFlowViewStage.askProduct ||
      ShoppingFlowViewStage.productSelection ||
      ShoppingFlowViewStage.searchingProduct ||
      ShoppingFlowViewStage.quantitySelection ||
      ShoppingFlowViewStage.cartProcessing ||
      ShoppingFlowViewStage.cartCompleted ||
      ShoppingFlowViewStage.addressConfirmation ||
      ShoppingFlowViewStage.paymentConfirmation ||
      ShoppingFlowViewStage.paymentProcessing ||
      ShoppingFlowViewStage.error =>
        VoicePanel.heightFor(context) +
            AppSpacing.sm +
            _overlayEndButtonRowHeight,
      _ => 0,
    };
  }

  bool get _isAwaitingUserInput =>
      _supportsVoiceInput &&
      !_isInitializing &&
      !_isSubmitting &&
      !_isUpdatingCartQuantity &&
      !_isSpeaking;

  bool get _canTapReplyChip => _isAwaitingUserInput && !_isRecording;

  VoiceInputState get _voiceInputState {
    if (_isRecording) {
      return VoiceInputState.listening;
    }
    return _isAwaitingUserInput
        ? VoiceInputState.active
        : VoiceInputState.inactive;
  }

  List<DialogueSegment>? get _fallbackPromptSegments {
    switch (_viewStage) {
      case ShoppingFlowViewStage.askProduct:
      case ShoppingFlowViewStage.searchingProduct:
        final askProductExample = _askProductExample;
        // DialogueBubble의 cyclePages는 명시적 '\n'을 문단 경계로, 그
        // 안에서는 마침표/느낌표/물음표를 문장 경계로 써서 페이지를 나눈다.
        // "이름님"과 "어떤게 필요하세요?" 사이에 강제 줄바꿈을 넣었더니
        // 한 문장인데도 두 페이지로 쪼개지는 문제가 있었다. 아래는 정확히
        // 3페이지로 나오도록 의도적으로 맞춘 구조다:
        // 페이지1 "OOO님, 어떤게 필요하세요?" / 페이지2 ""예시" 처럼, 원하시는
        // 상품을 말해주시면" / 페이지3 "OOO님을 위한 상품을 바로 찾아드릴게요!"
        if (_resolvedUserName != null && _resolvedUserName!.trim().isNotEmpty) {
          final name = _resolvedUserName!;
          return [
            DialogueSegment(text: '$name님, ', emphasized: true),
            const DialogueSegment(text: '어떤게 필요하세요? '),
            DialogueSegment(text: '"$askProductExample" 처럼, 원하시는 상품을 말해주시면\n'),
            DialogueSegment(text: '$name님', emphasized: true),
            const DialogueSegment(text: '을 위한 상품을 바로 찾아드릴게요!'),
          ];
        }
        return [
          const DialogueSegment(text: '어떤게 필요하세요? '),
          DialogueSegment(text: '"$askProductExample" 처럼, 원하시는 상품을 말해주시면\n'),
          const DialogueSegment(text: '바로 찾아드릴게요!'),
        ];
      case ShoppingFlowViewStage.quantitySelection:
        return const [
          DialogueSegment(text: '좋아요\n'),
          DialogueSegment(text: '몇 개', emphasized: true),
          DialogueSegment(text: ' 담아드릴까요?'),
        ];
      default:
        return null;
    }
  }

  /// askProduct 단계에서 예시 답변 칩 대신 딸랑구 멘트에 녹여 넣을 예시 문구.
  /// quickRepliesFor(askProduct)의 첫 항목을 그대로 재사용해 칩 목록이
  /// 바뀌어도 이 안내 문구가 따로 겉돌지 않게 한다.
  String get _askProductExample {
    final replies = _service.quickRepliesFor(ShoppingFlowViewStage.askProduct);
    return replies.isNotEmpty ? replies.first : '신선한 완숙 토마토 사고 싶어';
  }

  String? get _assistantText {
    final message =
        _visibleAssistantMessage?.trim() ?? _response?.assistantMessage.trim();
    if (message != null && message.isNotEmpty) {
      return message;
    }
    return null;
  }

  @override
  Widget build(BuildContext context) {
    // 위 shim getter들은 ref.read라 자체적으로 리빌드를 구독하지 않는다 —
    // 그래서 여기서 한 번 ref.watch로 구독을 걸고, ref.listen으로 응답이
    // 새로 들어올 때마다(웹뷰 pending task가 남아있다면) 프레임 이후에
    // _handlePendingWebviewTask를 실행한다. 예전에는 _applyResponse가
    // 직접 _schedulePromptSpeechAfterFrame(handlePendingWebviewAfter: true)를
    // 불렀는데, 그 부분이 컨트롤러로 옮겨가면서 Navigator가 필요한 이 조각만
    // 위젯에 남았다.
    ref.watch(shoppingFlowControllerProvider(_args));
    ref.listen<ShoppingFlowState>(shoppingFlowControllerProvider(_args), (
      previous,
      next,
    ) {
      if (identical(previous?.response, next.response)) {
        return;
      }
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted) {
          _handlePendingWebviewTask();
        }
      });
    });

    final currentStep = _service.progressStepFor(_viewStage);
    final completedSteps = _service.completedStepsFor(_viewStage);

    return ScreenFrame(
      preset: LayoutPreset.conversation,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          _buildHeader(
            currentStep: currentStep,
            completedSteps: completedSteps,
          ),
          const SizedBox(height: AppSpacing.md),
          _buildDialogueSection(),
          const SizedBox(height: AppSpacing.lg),
          Expanded(child: _buildConversationViewport()),
        ],
      ),
    );
  }

  Widget _buildConversationViewport() {
    final overlayBottomInset = _overlayBottomInsetFor(context);
    final stageBody = AnimatedSwitcher(
      duration: const Duration(milliseconds: 260),
      switchInCurve: Curves.easeOutCubic,
      switchOutCurve: Curves.easeInCubic,
      child: KeyedSubtree(
        key: ValueKey<String>(
          '${_viewStage.name}:${_isInitializing ? 'init' : 'ready'}',
        ),
        child: _buildStageContent(),
      ),
    );

    if (_usesOverlayBottomSection) {
      return Stack(
        children: [
          Positioned.fill(
            child: Padding(
              padding: EdgeInsets.only(bottom: overlayBottomInset),
              child: stageBody,
            ),
          ),
          Align(
            alignment: Alignment.bottomCenter,
            child: _buildBottomSection(),
          ),
        ],
      );
    }

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Expanded(child: stageBody),
        const SizedBox(height: AppSpacing.lg),
        _buildBottomSection(),
      ],
    );
  }

  Widget _buildHeader({
    required ShoppingProgressStep currentStep,
    required Set<ShoppingProgressStep> completedSteps,
  }) {
    // 대화 종료 버튼은 더 이상 헤더(단계바 옆)에 두지 않는다. 화면마다
    // 상단 아이콘/텍스트로 제각각이던 걸 하단 전체너비 버튼으로 통일했다
    // (_buildOverlayBottomSection / _buildBottomArea 참고).
    return ShoppingProgressStepper(
      currentStep: currentStep,
      completedSteps: completedSteps,
      compact: true,
    );
  }

  Widget _wrapStagePanel(Widget child) {
    return LayoutBuilder(
      builder: (context, constraints) {
        final minHeight = constraints.maxHeight.isFinite
            ? constraints.maxHeight
            : 0.0;
        return Scrollbar(
          thumbVisibility: true,
          radius: const Radius.circular(999),
          thickness: 4,
          child: SingleChildScrollView(
            primary: true,
            physics: const ClampingScrollPhysics(),
            child: ConstrainedBox(
              constraints: BoxConstraints(minHeight: minHeight),
              child: child,
            ),
          ),
        );
      },
    );
  }

  Widget _buildDialogueSection() {
    final dialogueSectionHeight = _dialogueSectionHeightFor(context);

    return SizedBox(
      height: dialogueSectionHeight,
      child: DialogueBubble(
        contentKey: ValueKey(
          '${_response?.conversationId ?? 0}-${_response?.stage}-${_assistantText ?? _viewStage.name}',
        ),
        animateTextChanges: true,
        // 문구를 한 번에 다 보여주지 않고 문장 단위로 하나씩 순서대로
        // 보여준다. 실제 백엔드 응답처럼 문장이 길어져도 말풍선 높이를
        // 고정으로 유지하면서 잘리지 않게 하고, 딸랑구가 실제로 한 문장씩
        // 말하는 듯한 느낌도 준다.
        cyclePages: false,
        borderColor: AppSurfaceStyles.emphasisOutlineColor,
        minHeight: dialogueSectionHeight - 8,
        scrollableContent: true,
        contentAlignment: Alignment.topLeft,
        text: _assistantText,
        segments: _assistantText == null ? _fallbackPromptSegments : null,
        style: AppTextStyles.title2.copyWith(
          color: AppColors.textStrong,
          height: 1.32,
        ),
        emphasizedStyle: AppTextStyles.title2.copyWith(
          color: AppColors.primaryPinkDark,
          fontWeight: FontWeight.w800,
          height: 1.32,
        ),
      ),
    );
  }

  Widget _buildBottomSection() {
    if (_isInitializing) {
      return const SizedBox.shrink();
    }

    if (_usesOverlayBottomSection) {
      return _buildOverlayBottomSection();
    }

    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        if (_inlineError != null) ...[
          _InlineErrorBanner(message: _inlineError!),
          const SizedBox(height: AppSpacing.md),
        ],
        _buildBottomArea(),
      ],
    );
  }

  Widget _buildOverlayBottomSection() {
    final replyOptions = _buildOverlayReplyOptions();
    final splitIndex = (replyOptions.length / 2).ceil();
    final leadingReplyContent = _buildOverlayReplyColumn(
      replyOptions.take(splitIndex).toList(growable: false),
      crossAxisAlignment: CrossAxisAlignment.end,
      textAlign: TextAlign.right,
    );
    final trailingReplyContent = _buildOverlayReplyColumn(
      replyOptions.skip(splitIndex).toList(growable: false),
      crossAxisAlignment: CrossAxisAlignment.start,
      textAlign: TextAlign.left,
    );

    return Padding(
      padding: EdgeInsets.zero,
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          if (_inlineError != null) ...[
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: AppSpacing.xs),
              child: _InlineErrorBanner(message: _inlineError!),
            ),
            const SizedBox(height: AppSpacing.sm),
          ],
          // 스몰토크/에이전트 인사 화면과 동일한 공용 VoicePanel을 써서
          // 메인 쇼핑 흐름의 음성 패널도 같은 모양/크기로 통일했다.
          VoicePanel(
            state: _voiceInputState,
            onPressed: _toggleVoiceInput,
            leadingReply: leadingReplyContent,
            trailingReply: trailingReplyContent,
          ),
          const SizedBox(height: AppSpacing.sm),
          EndConversationButton(
            fullWidth: true,
            variant: EndConversationButtonVariant.dark,
            onPressed: _confirmExit,
          ),
        ],
      ),
    );
  }

  List<_OverlayReplyOption> _buildOverlayReplyOptions() {
    switch (_viewStage) {
      case ShoppingFlowViewStage.askProduct:
        // 실제 서비스에서는 예시 답변 칩을 제거하고 같은 예시를 딸랑구
        // 멘트(_fallbackPromptSegments/컨트롤러 TTS prompt)로 옮겼다. 다만
        // 에뮬레이터에서 빠르게 흐름을 테스트할 수 있도록 mock flow에서는
        // 예시 답변 칩을 그대로 유지한다.
        if (_service is! MockShoppingFlowService) {
          return const <_OverlayReplyOption>[];
        }
        return _service
            .quickRepliesFor(_viewStage)
            .map(
              (reply) => _OverlayReplyOption(
                label: reply,
                onTap: _canTapReplyChip ? () => _submitMessage(reply) : null,
              ),
            )
            .toList(growable: false);
      case ShoppingFlowViewStage.productSelection:
        final pending = _response?.pendingConfirmation;
        final payload = pending is Map && pending['payload'] is Map
            ? Map<String, dynamic>.from(pending['payload'] as Map)
            : const <String, dynamic>{};
        final actions =
            (payload['actions'] as List<dynamic>? ?? const <dynamic>[])
                .map((action) => action.toString())
                .where((action) => action.trim().isNotEmpty)
                .toList(growable: false);

        return <_OverlayReplyOption>[
          if (actions.contains('order_now'))
            _OverlayReplyOption(
              label: '이 상품으로 주문하기',
              onTap: _canTapReplyChip
                  ? () => unawaited(_confirmAction('order_now'))
                  : null,
            ),
          if (actions.contains('add_to_cart'))
            _OverlayReplyOption(
              label: '장바구니에 담기',
              onTap: _canTapReplyChip
                  ? () => unawaited(_confirmAction('add_to_cart'))
                  : null,
            ),
          if (actions.contains('reject'))
            _OverlayReplyOption(
              label: '다른 상품 보기',
              onTap: _canTapReplyChip
                  ? () => unawaited(_confirmAction('reject'))
                  : null,
            ),
        ];
      case ShoppingFlowViewStage.cartCompleted:
        final replies = _effectiveCartItems.isEmpty
            ? const ['더 구매할래요']
            : _service.quickRepliesFor(_viewStage);
        return replies
            .map(
              (reply) => _OverlayReplyOption(
                label: reply,
                onTap: _canTapReplyChip ? () => _submitMessage(reply) : null,
              ),
            )
            .toList(growable: false);
      case ShoppingFlowViewStage.quantitySelection:
      case ShoppingFlowViewStage.addressConfirmation:
      case ShoppingFlowViewStage.paymentConfirmation:
      case ShoppingFlowViewStage.error:
        return _service
            .quickRepliesFor(_viewStage)
            .map(
              (reply) => _OverlayReplyOption(
                label: reply,
                onTap: _canTapReplyChip ? () => _submitMessage(reply) : null,
              ),
            )
            .toList(growable: false);
      case ShoppingFlowViewStage.searchingProduct:
      case ShoppingFlowViewStage.cartProcessing:
      case ShoppingFlowViewStage.paymentProcessing:
      case ShoppingFlowViewStage.paymentPassword:
      case ShoppingFlowViewStage.completed:
        return const <_OverlayReplyOption>[];
    }
  }

  Widget? _buildOverlayReplyColumn(
    List<_OverlayReplyOption> options, {
    required CrossAxisAlignment crossAxisAlignment,
    required TextAlign textAlign,
  }) {
    if (options.isEmpty) {
      return null;
    }

    return Column(
      mainAxisSize: MainAxisSize.min,
      crossAxisAlignment: crossAxisAlignment,
      children: options
          .map(
            (option) => _QuickReplyChip(
              label: option.label,
              onTap: option.onTap,
              textAlign: textAlign,
            ),
          )
          .toList(growable: false),
    );
  }

  Widget _buildStageContent() {
    if (_isInitializing) {
      return const _EmptyStatePanel(
        key: ValueKey('initializing'),
        assetPath: 'assets/images/character/full/ddalangoo_curious.png',
        title: '쇼핑 화면을 준비하고 있어요.',
        caption: '사용자 정보와 기본 설정을 불러오는 중이에요.',
      );
    }

    final selectedProduct = _response == null
        ? null
        : _service.extractSelectedProduct(_response!);
    final cartItems = _effectiveCartItems;
    final address = _response == null
        ? _fallbackAddress
        : _service.extractAddress(
            _response!,
            fallback: _fallbackAddress,
            fallbackRecipientName: _resolvedUserName,
          );

    switch (_viewStage) {
      case ShoppingFlowViewStage.askProduct:
        return const _EmptyStatePanel(
          key: ValueKey('ask-product'),
          assetPath: 'assets/images/character/top/ddalangoo_standing_top.png',
        );
      case ShoppingFlowViewStage.searchingProduct:
        // _StatusPanel이 내부적으로 남는 높이에 맞춰 스스로 크기를
        // 조정하므로(_wrapStagePanel의 획일적인 스크롤 래핑 대신), 여기서는
        // 더 이상 _wrapStagePanel로 감싸지 않는다.
        return _StatusPanel(
          key: const ValueKey('searching-product'),
          title: _service.statusTitleFor(_viewStage),
          message: _service.statusMessageFor(
            _viewStage,
            response: _response,
            product: selectedProduct,
          ),
          progress: _service.progressValueFor(_viewStage),
          assetPath: 'assets/images/character/full/ddalangoo_curious.png',
          helperText: '추천 상품과 이유를 정리해서 보여드릴게요.',
        );
      case ShoppingFlowViewStage.productSelection:
        return _ProductSelectionPanel(
          key: const ValueKey('product-selection'),
          service: _service,
          primaryProduct: selectedProduct,
          secondaryProducts: _response == null
              ? const <RecommendationItemInAgent>[]
              : _service.secondaryRecommendations(_response!),
        );
      case ShoppingFlowViewStage.quantitySelection:
        return _wrapStagePanel(
          _QuantitySelectionPanel(
            key: const ValueKey('quantity-selection'),
            service: _service,
            product: selectedProduct,
          ),
        );
      case ShoppingFlowViewStage.cartProcessing:
        // 상품이 이미 정해진 상태라, 상품 확인/선택 화면과 같은 히어로
        // 카드(배경 이미지 + 그라디언트) 스타일로 보여준다. 화면마다
        // 스타일이 다르던 걸 통일했다.
        if (selectedProduct != null) {
          return _CartProcessingHeroPanel(
            key: const ValueKey('cart-processing'),
            title: _service.statusTitleFor(_viewStage),
            message: _service.statusMessageFor(
              _viewStage,
              response: _response,
              product: selectedProduct,
              quantity: cartItems.firstOrNull?.quantity,
            ),
            progress: _service.progressValueFor(_viewStage),
            product: selectedProduct!,
            service: _service,
          );
        }
        return _StatusPanel(
          key: const ValueKey('cart-processing'),
          title: _service.statusTitleFor(_viewStage),
          message: _service.statusMessageFor(
            _viewStage,
            response: _response,
            product: selectedProduct,
            quantity: cartItems.firstOrNull?.quantity,
          ),
          progress: _service.progressValueFor(_viewStage),
          product: selectedProduct,
          service: _service,
          helperText: '옵션과 수량을 확인한 뒤 주문서에 반영하고 있어요.',
        );
      case ShoppingFlowViewStage.cartCompleted:
        return _wrapStagePanel(
          _CartSummaryPanel(
            key: const ValueKey('cart-completed'),
            service: _service,
            userName: _resolvedUserName,
            items: cartItems,
            isUpdatingQuantity: _isUpdatingCartQuantity,
            onQuantityChanged: _changeCartItemQuantity,
          ),
        );
      case ShoppingFlowViewStage.addressConfirmation:
        return _wrapStagePanel(
          _AddressPanel(
            key: const ValueKey('address-confirmation'),
            address: address,
          ),
        );
      case ShoppingFlowViewStage.paymentConfirmation:
        return _wrapStagePanel(
          _PaymentSummaryPanel(
            key: const ValueKey('payment-confirmation'),
            service: _service,
            items: cartItems,
            address: address,
          ),
        );
      case ShoppingFlowViewStage.paymentPassword:
        return _wrapStagePanel(
          _PasswordStagePanel(
            pinInput: _pinInput,
            enabled: !_isSubmitting,
            onDigitPressed: _appendPinDigit,
            onBackspacePressed: _removePinDigit,
          ),
        );
      case ShoppingFlowViewStage.paymentProcessing:
        return _StatusPanel(
          key: const ValueKey('payment-processing'),
          title: _service.statusTitleFor(_viewStage),
          message: _service.statusMessageFor(
            _viewStage,
            response: _response,
            product: selectedProduct,
          ),
          progress: _service.progressValueFor(_viewStage),
          assetPath: 'assets/images/character/full/ddalangoo_calling.png',
          helperText: '결제 자동화가 진행되는 동안 이 화면에서 상태를 이어서 보여드릴게요.',
        );
      case ShoppingFlowViewStage.completed:
        return const _CompletionPanel(key: ValueKey('completed'));
      case ShoppingFlowViewStage.error:
        return _EmptyStatePanel(
          key: const ValueKey('error'),
          assetPath: 'assets/images/character/full/ddalangoo_curious.png',
          title: '조금만 다시 말씀해주시면 이어서 도와드릴게요.',
          caption: '상품명, 수량, 결제 의사처럼 짧게 다시 말씀해주세요.',
        );
    }
  }

  Widget _buildBottomArea() {
    if (_isInitializing) {
      return const SizedBox.shrink();
    }

    switch (_viewStage) {
      case ShoppingFlowViewStage.askProduct:
        // 이 stage는 _usesOverlayBottomSection에서 항상 true라 실제로는
        // _buildOverlayBottomSection()이 쓰이지만, 방어적으로 이 분기도
        // 예시 답변 칩 없이 음성 버튼만 두도록 맞춰둔다.
        return Column(
          children: [
            VoiceInputButton(
              state: _voiceInputState,
              onPressed: _toggleVoiceInput,
            ),
          ],
        );
      case ShoppingFlowViewStage.searchingProduct:
      case ShoppingFlowViewStage.cartProcessing:
      case ShoppingFlowViewStage.paymentProcessing:
        return Column(
          children: [
            BottomStatusBanner(
              message: _service.statusMessageFor(
                _viewStage,
                response: _response,
                product: _response == null
                    ? null
                    : _service.extractSelectedProduct(_response!),
              ),
              characterAssetPath:
                  'assets/images/character/top/ddalangoo_greeting_top.png',
            ),
            const SizedBox(height: AppSpacing.md),
            VoiceInputButton(
              state: _voiceInputState,
              onPressed: _toggleVoiceInput,
            ),
          ],
        );
      case ShoppingFlowViewStage.productSelection:
        return Column(
          children: [
            _ProductActionArea(
              response: _response,
              canTapReplies: _canTapReplyChip,
              onActionSelected: _confirmAction,
            ),
            const SizedBox(height: AppSpacing.md),
            VoiceInputButton(
              state: _voiceInputState,
              onPressed: _toggleVoiceInput,
            ),
          ],
        );
      case ShoppingFlowViewStage.cartCompleted:
        final replies = _effectiveCartItems.isEmpty
            ? const ['더 구매할래요']
            : _service.quickRepliesFor(_viewStage);
        return Column(
          children: [
            if (replies.isNotEmpty)
              Wrap(
                spacing: AppSpacing.xs,
                runSpacing: AppSpacing.xs,
                alignment: WrapAlignment.center,
                children: replies
                    .map((reply) {
                      return _QuickReplyChip(
                        label: reply,
                        onTap: _canTapReplyChip
                            ? () => _submitMessage(reply)
                            : null,
                      );
                    })
                    .toList(growable: false),
              ),
            if (replies.isNotEmpty) const SizedBox(height: AppSpacing.md),
            VoiceInputButton(
              state: _voiceInputState,
              onPressed: _toggleVoiceInput,
            ),
          ],
        );
      case ShoppingFlowViewStage.quantitySelection:
      case ShoppingFlowViewStage.addressConfirmation:
      case ShoppingFlowViewStage.paymentConfirmation:
      case ShoppingFlowViewStage.error:
        final replies = _service.quickRepliesFor(_viewStage);
        return Column(
          children: [
            if (replies.isNotEmpty)
              Wrap(
                spacing: AppSpacing.xs,
                runSpacing: AppSpacing.xs,
                alignment: WrapAlignment.center,
                children: replies
                    .map((reply) {
                      return _QuickReplyChip(
                        label: reply,
                        onTap: _canTapReplyChip
                            ? () => _submitMessage(reply)
                            : null,
                      );
                    })
                    .toList(growable: false),
              ),
            if (replies.isNotEmpty) const SizedBox(height: AppSpacing.md),
            VoiceInputButton(
              state: _voiceInputState,
              onPressed: _toggleVoiceInput,
            ),
          ],
        );
      case ShoppingFlowViewStage.paymentPassword:
        return Column(
          children: [
            PrimaryButton(
              label: _isSubmitting ? '확인 중...' : '비밀번호 확인',
              onPressed: _isSubmitting || _pinInput.isEmpty ? null : _submitPin,
            ),
            const SizedBox(height: AppSpacing.sm),
            EndConversationButton(
              fullWidth: true,
              variant: EndConversationButtonVariant.dark,
              onPressed: _confirmExit,
            ),
          ],
        );
      case ShoppingFlowViewStage.completed:
        return Column(
          children: [
            PrimaryButton(
              label: '홈 화면으로 돌아가기',
              icon: Icons.home_rounded,
              onPressed: () {
                Navigator.of(
                  context,
                ).pushNamedAndRemoveUntil(AppRoutes.home, (route) => false);
              },
            ),
          ],
        );
    }
  }
}

class _InlineErrorBanner extends StatelessWidget {
  const _InlineErrorBanner({required this.message});

  final String message;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(AppSpacing.md),
      decoration: BoxDecoration(
        color: const Color(0xFFFFF1F5),
        borderRadius: BorderRadius.circular(AppRadii.lg),
        border: Border.all(color: const Color(0xFFFFC7D9)),
      ),
      child: Text(
        message,
        style: AppTextStyles.body2.copyWith(
          color: AppColors.primaryPinkDark,
          fontWeight: FontWeight.w700,
        ),
      ),
    );
  }
}

class _EmptyStatePanel extends StatelessWidget {
  const _EmptyStatePanel({
    super.key,
    required this.assetPath,
    this.title,
    this.caption,
  });

  final String assetPath;
  final String? title;
  final String? caption;

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (context, constraints) {
        final availableHeight = constraints.maxHeight.isFinite
            ? constraints.maxHeight
            : 420.0;
        final compact = availableHeight < 300;
        final imageHeight = (availableHeight * 0.56)
            .clamp(108.0, 230.0)
            .toDouble();
        final titleSpacing = compact ? AppSpacing.md : AppSpacing.lg;
        final captionSpacing = compact ? AppSpacing.xs : AppSpacing.sm;
        final title = this.title;
        final caption = this.caption;

        return Scrollbar(
          thumbVisibility: true,
          radius: const Radius.circular(999),
          thickness: 4,
          child: SingleChildScrollView(
            primary: true,
            physics: const ClampingScrollPhysics(),
            child: ConstrainedBox(
              constraints: BoxConstraints(minHeight: availableHeight),
              child: Column(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  Image.asset(
                    assetPath,
                    height: imageHeight,
                    fit: BoxFit.contain,
                  ),
                  if (title != null) ...[
                    SizedBox(height: titleSpacing),
                    Text(
                      title,
                      textAlign: TextAlign.center,
                      style: AppTextStyles.body1.copyWith(
                        fontWeight: FontWeight.w800,
                      ),
                    ),
                  ],
                  if (caption != null) ...[
                    SizedBox(height: captionSpacing),
                    Text(
                      caption,
                      textAlign: TextAlign.center,
                      style: AppTextStyles.body2,
                    ),
                  ],
                ],
              ),
            ),
          ),
        );
      },
    );
  }
}

class _StatusPanel extends StatelessWidget {
  const _StatusPanel({
    super.key,
    required this.title,
    required this.message,
    required this.progress,
    this.helperText,
    this.assetPath,
    this.product,
    this.service,
  });

  final String title;
  final String message;
  final double progress;
  final String? helperText;
  final String? assetPath;
  final ShoppingProductViewData? product;
  final ShoppingFlowService? service;

  @override
  Widget build(BuildContext context) {
    // _EmptyStatePanel/_ProductSelectionPanel과 같은 패턴: 이 화면(예:
    // 상품 검색 중)에서 남는 세로 공간에 맞춰 캐릭터 이미지 높이를 줄여서,
    // 실제로 스크롤이 필요한 상황이 거의 생기지 않게 한다. Scrollbar는
    // 아주 작은 화면에서만 동작하는 안전망일 뿐, 평소엔 보이지 않는다.
    // 테두리도 다른 바디 패널들처럼 무거운 검정 테두리 대신 은은한
    // 그림자로 통일했다.
    return LayoutBuilder(
      builder: (context, constraints) {
        final availableHeight = constraints.maxHeight.isFinite
            ? constraints.maxHeight
            : 420.0;
        final compact = availableHeight < 300;
        final imageHeight = (availableHeight * 0.34)
            .clamp(96.0, 176.0)
            .toDouble();
        final sectionSpacing = compact ? AppSpacing.sm : AppSpacing.md;

        return Scrollbar(
          thumbVisibility: true,
          radius: const Radius.circular(999),
          thickness: 4,
          child: SingleChildScrollView(
            primary: true,
            physics: const ClampingScrollPhysics(),
            child: ConstrainedBox(
              constraints: BoxConstraints(minHeight: availableHeight),
              child: Container(
                width: double.infinity,
                padding: const EdgeInsets.all(AppSpacing.cardPadding),
                decoration: AppSurfaceStyles.floatingCard(
                  radius: AppRadii.xl,
                  boxShadow: AppSurfaceStyles.raisedShadow,
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  mainAxisAlignment: MainAxisAlignment.center,
                  children: [
                    Text(
                      title,
                      style: AppTextStyles.caption.copyWith(
                        fontSize: 14,
                        color: AppColors.textMuted,
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                    const SizedBox(height: AppSpacing.sm),
                    Text(
                      message,
                      style: AppTextStyles.title2.copyWith(
                        fontSize: 26,
                        height: 1.3,
                      ),
                    ),
                    SizedBox(height: sectionSpacing),
                    if (product != null && service != null) ...[
                      _CompactProductRow(product: product!, service: service!),
                      SizedBox(height: sectionSpacing),
                    ] else if (assetPath != null) ...[
                      Center(
                        child: Image.asset(
                          assetPath!,
                          height: imageHeight,
                          fit: BoxFit.contain,
                        ),
                      ),
                      SizedBox(height: sectionSpacing),
                    ],
                    ClipRRect(
                      borderRadius: BorderRadius.circular(999),
                      child: LinearProgressIndicator(
                        value: progress.clamp(0, 1),
                        minHeight: 12,
                        backgroundColor: AppColors.surfaceMuted,
                        color: AppColors.primaryPink,
                      ),
                    ),
                    if (helperText != null) ...[
                      const SizedBox(height: AppSpacing.md),
                      Text(helperText!, style: AppTextStyles.body2),
                    ],
                  ],
                ),
              ),
            ),
          ),
        );
      },
    );
  }
}

/// cartProcessing 단계에서 상품이 이미 정해진 경우 쓰는 패널.
/// _HeroProductPanel과 같은 배경 이미지+그라디언트 스타일이라, 상품을
/// 보여주는 다른 단계(상품 확인/선택)와 화면이 자연스럽게 이어진다.
/// _StatusPanel처럼 스크롤 안전망(Scrollbar)에 기대는 대신, 이 화면도
/// 히어로 카드와 동일하게 남는 높이를 그대로 채워서 스크롤 없이 항상 한
/// 화면에 다 보이게 한다.
class _CartProcessingHeroPanel extends StatelessWidget {
  const _CartProcessingHeroPanel({
    super.key,
    required this.title,
    required this.message,
    required this.progress,
    required this.product,
    required this.service,
  });

  final String title;
  final String message;
  final double progress;
  final ShoppingProductViewData product;
  final ShoppingFlowService service;

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (context, constraints) {
        final panelHeight = constraints.maxHeight.isFinite
            ? constraints.maxHeight
            : constraints.minHeight > 0
            ? constraints.minHeight
            : 420.0;

        return SizedBox(
          width: double.infinity,
          height: panelHeight,
          child: Container(
            decoration: AppSurfaceStyles.floatingCard(
              radius: AppRadii.xl,
              boxShadow: AppSurfaceStyles.featuredProductShadow,
            ),
            child: ClipRRect(
              borderRadius: BorderRadius.circular(AppRadii.xl),
              child: Stack(
                children: [
                  const Positioned.fill(child: ColoredBox(color: Colors.white)),
                  Positioned.fill(
                    child: _ProductArtwork(
                      product: product,
                      service: service,
                      height: panelHeight,
                      fit: BoxFit.cover,
                    ),
                  ),
                  Positioned.fill(
                    child: DecoratedBox(
                      decoration: BoxDecoration(
                        gradient: LinearGradient(
                          begin: Alignment.topCenter,
                          end: Alignment.bottomCenter,
                          colors: [
                            Colors.white.withValues(alpha: 0.94),
                            Colors.white.withValues(alpha: 0.64),
                            Colors.white.withValues(alpha: 0.2),
                            Colors.white.withValues(alpha: 0.6),
                            Colors.white.withValues(alpha: 0.92),
                          ],
                          stops: const [0, 0.24, 0.5, 0.78, 1],
                        ),
                      ),
                    ),
                  ),
                  Padding(
                    padding: const EdgeInsets.all(AppSpacing.cardPadding),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          title,
                          style: AppTextStyles.caption.copyWith(
                            fontSize: 14,
                            color: AppColors.textMuted,
                            fontWeight: FontWeight.w700,
                          ),
                        ),
                        const SizedBox(height: AppSpacing.sm),
                        Text(
                          message,
                          style: AppTextStyles.title2.copyWith(
                            fontSize: 24,
                            height: 1.3,
                          ),
                        ),
                        const Spacer(),
                        Text(
                          product.title,
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: AppTextStyles.body1.copyWith(
                            fontWeight: FontWeight.w800,
                            color: AppColors.textStrong,
                          ),
                        ),
                        const SizedBox(height: AppSpacing.sm),
                        ClipRRect(
                          borderRadius: BorderRadius.circular(999),
                          child: LinearProgressIndicator(
                            value: progress.clamp(0, 1),
                            minHeight: 12,
                            backgroundColor: AppColors.surfaceMuted,
                            color: AppColors.primaryPink,
                          ),
                        ),
                      ],
                    ),
                  ),
                ],
              ),
            ),
          ),
        );
      },
    );
  }
}

class _ProductSelectionPanel extends StatelessWidget {
  const _ProductSelectionPanel({
    super.key,
    required this.service,
    required this.primaryProduct,
    required this.secondaryProducts,
  });

  final ShoppingFlowService service;
  final ShoppingProductViewData? primaryProduct;
  final List<RecommendationItemInAgent> secondaryProducts;

  @override
  Widget build(BuildContext context) {
    if (primaryProduct == null) {
      return const _EmptyStatePanel(
        assetPath: 'assets/images/character/full/ddalangoo_curious.png',
        title: '추천 상품을 정리하는 중이에요.',
        caption: '잠시 후 다시 한 번 확인해주세요.',
      );
    }

    // 예전에는 남은 높이가 420px 미만이면 카드를 스크롤 가능한 고정
    // 420px짜리로 바꿨는데, 이 화면 구성(단계바+말풍선+하단 음성 패널)
    // 예산을 계산해보면 일반적인 휴대폰 화면에서도 남는 높이가 420px보다
    // 작은 경우가 흔해서 사실상 항상 스크롤이 뜨고 있었다. 여기 도달할 때
    // 이 영역은 이미 Stack의 Positioned.fill로 높이가 확정돼 있으니,
    // 스크롤 대신 그냥 남는 높이만큼 카드를 채워서 항상 한 화면에 다
    // 보이게 한다.
    return _HeroProductPanel(product: primaryProduct!, service: service);
  }
}

class _QuantitySelectionPanel extends StatelessWidget {
  const _QuantitySelectionPanel({
    super.key,
    required this.service,
    required this.product,
  });

  final ShoppingFlowService service;
  final ShoppingProductViewData? product;

  @override
  Widget build(BuildContext context) {
    if (product == null) {
      return const _EmptyStatePanel(
        assetPath: 'assets/images/character/full/ddalangoo_curious.png',
        title: '수량을 정하기 전에 상품을 다시 확인하고 있어요.',
        caption: '잠시만 기다리면 이어서 선택할 수 있어요.',
      );
    }

    return _HeroProductPanel(product: product!, service: service);
  }
}

class _HeroProductPanel extends StatelessWidget {
  const _HeroProductPanel({required this.product, required this.service});

  final ShoppingProductViewData product;
  final ShoppingFlowService service;

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (context, constraints) {
        final panelHeight = constraints.maxHeight.isFinite
            ? constraints.maxHeight
            : constraints.minHeight > 0
            ? constraints.minHeight
            : 420.0;

        return SizedBox(
          width: double.infinity,
          height: panelHeight,
          child: Container(
            decoration: AppSurfaceStyles.floatingCard(
              radius: AppRadii.xl,
              boxShadow: AppSurfaceStyles.featuredProductShadow,
            ),
            child: ClipRRect(
              borderRadius: BorderRadius.circular(AppRadii.xl),
              child: Stack(
                children: [
                  const Positioned.fill(child: ColoredBox(color: Colors.white)),
                  Positioned.fill(
                    child: _ProductArtwork(
                      product: product,
                      service: service,
                      height: panelHeight,
                      fit: BoxFit.cover,
                    ),
                  ),
                  Positioned.fill(
                    child: DecoratedBox(
                      decoration: BoxDecoration(
                        gradient: LinearGradient(
                          begin: Alignment.topCenter,
                          end: Alignment.bottomCenter,
                          colors: [
                            Colors.white.withValues(alpha: 0.92),
                            Colors.white.withValues(alpha: 0.56),
                            Colors.white.withValues(alpha: 0.16),
                            Colors.white.withValues(alpha: 0.52),
                            Colors.white.withValues(alpha: 0.88),
                          ],
                          stops: const [0, 0.24, 0.55, 0.8, 1],
                        ),
                      ),
                    ),
                  ),
                  Padding(
                    padding: const EdgeInsets.all(AppSpacing.cardPadding),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          product.title,
                          style: AppTextStyles.title2.copyWith(
                            fontSize: 26,
                            color: AppColors.textStrong,
                          ),
                        ),
                        if (product.detailLine.isNotEmpty) ...[
                          const SizedBox(height: AppSpacing.sm),
                          Text(
                            product.detailLine,
                            style: AppTextStyles.body1.copyWith(
                              fontSize: 19,
                              height: 1.35,
                              color: AppColors.textSecondary,
                              fontWeight: FontWeight.w600,
                            ),
                          ),
                        ],
                        const SizedBox(height: AppSpacing.sm),
                        Text(
                          product.displayPrice,
                          style: AppTextStyles.title1.copyWith(
                            color: AppColors.textStrong,
                            fontWeight: FontWeight.w800,
                          ),
                        ),
                        // 추천 이유는 계산은 되고 있었는데 화면 어디에도 노출이
                        // 안 되고 있었다. 왜 이 상품을 골랐는지 짧게 보여준다.
                        if (product.reason != null &&
                            product.reason!.trim().isNotEmpty) ...[
                          const SizedBox(height: AppSpacing.sm),
                          _RecommendationReasonNote(reason: product.reason!),
                        ],
                        const Spacer(),
                        Align(
                          alignment: Alignment.bottomLeft,
                          child: _PlatformPill(
                            label: service.platformLabel(product.platform),
                            backgroundColor: Colors.white.withValues(
                              alpha: 0.94,
                            ),
                            bannerHeight: 29,
                          ),
                        ),
                      ],
                    ),
                  ),
                ],
              ),
            ),
          ),
        );
      },
    );
  }
}

class _CartSummaryPanel extends StatelessWidget {
  const _CartSummaryPanel({
    super.key,
    required this.service,
    required this.userName,
    required this.items,
    required this.isUpdatingQuantity,
    required this.onQuantityChanged,
  });

  final ShoppingFlowService service;
  final String? userName;
  final List<ShoppingCartItemViewData> items;
  final bool isUpdatingQuantity;
  final Future<void> Function(ShoppingCartItemViewData item, int quantity)
  onQuantityChanged;

  @override
  Widget build(BuildContext context) {
    final totalPrice = items.fold<int>(
      0,
      (sum, item) =>
          sum + (item.totalPrice ?? (item.product.price ?? 0) * item.quantity),
    );

    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(AppSpacing.cardPadding),
      // 진한 검정 테두리(emphasizedPanel) 대신, 카드가 배경에서 살짝 뜨는
      // 그림자로 대비를 준다. 안쪽 상품 카드/searchingProduct 상태 패널과
      // 같은 스타일로 통일했다.
      decoration: AppSurfaceStyles.floatingCard(
        radius: AppRadii.xl,
        boxShadow: AppSurfaceStyles.raisedShadow,
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            userName == null || userName!.trim().isEmpty
                ? '장바구니'
                : '${userName!.trim()} 님의 장바구니',
            style: AppTextStyles.title2.copyWith(fontSize: 23),
          ),
          const SizedBox(height: AppSpacing.lg),
          if (items.isEmpty)
            const Text('담긴 상품을 아직 확인하는 중이에요.', style: AppTextStyles.body2)
          else
            Column(
              children: [
                for (var index = 0; index < items.length; index++) ...[
                  _CartItemTile(
                    item: items[index],
                    service: service,
                    isUpdatingQuantity: isUpdatingQuantity,
                    onDecrease:
                        items[index].canAdjustQuantity && !isUpdatingQuantity
                        ? () => onQuantityChanged(
                            items[index],
                            items[index].quantity - 1,
                          )
                        : null,
                    onIncrease:
                        items[index].canAdjustQuantity && !isUpdatingQuantity
                        ? () => onQuantityChanged(
                            items[index],
                            items[index].quantity + 1,
                          )
                        : null,
                  ),
                  if (index != items.length - 1)
                    const SizedBox(height: AppSpacing.md),
                ],
              ],
            ),
          const SizedBox(height: AppSpacing.lg),
          Container(
            width: double.infinity,
            padding: const EdgeInsets.all(AppSpacing.md),
            decoration: BoxDecoration(
              color: AppColors.surface,
              borderRadius: BorderRadius.circular(AppRadii.lg),
            ),
            child: Row(
              children: [
                Text(
                  '총 금액',
                  style: AppTextStyles.body1.copyWith(
                    fontWeight: FontWeight.w700,
                  ),
                ),
                const Spacer(),
                Text(
                  '${formatPrice(totalPrice)}원',
                  style: AppTextStyles.title2.copyWith(
                    color: AppColors.primaryPinkDark,
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _AddressPanel extends StatelessWidget {
  const _AddressPanel({super.key, required this.address});

  final ShoppingAddressViewData? address;

  @override
  Widget build(BuildContext context) {
    if (address == null) {
      return const _EmptyStatePanel(
        assetPath: 'assets/images/character/full/ddalangoo_curious.png',
        title: '배송지 정보를 확인하고 있어요.',
        caption: '기본 배송지가 연결되면 바로 보여드릴게요.',
      );
    }

    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(AppSpacing.cardPadding),
      // 진한 검정 테두리 + 회색 배경 대신, 장바구니 카드와 같은 흰 배경 +
      // 은은한 그림자 스타일로 통일했다.
      decoration: AppSurfaceStyles.floatingCard(
        radius: AppRadii.xl,
        boxShadow: AppSurfaceStyles.raisedShadow,
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            address!.label?.trim().isNotEmpty == true
                ? address!.label!.trim()
                : (address!.isDefault ? '기본 배송지' : '배송지'),
            style: AppTextStyles.caption.copyWith(
              fontSize: 14,
              fontWeight: FontWeight.w700,
              color: AppColors.textMuted,
            ),
          ),
          const SizedBox(height: AppSpacing.sm),
          Text(address!.displayAddress, style: AppTextStyles.title2),
          const SizedBox(height: AppSpacing.md),
          _InfoRow(label: '주문자', value: address!.displayRecipient),
          const SizedBox(height: AppSpacing.sm),
          _InfoRow(label: '배송 요청', value: address!.displayDeliveryRequest),
          if (address!.zipCode?.trim().isNotEmpty == true) ...[
            const SizedBox(height: AppSpacing.sm),
            _InfoRow(label: '우편번호', value: address!.zipCode!.trim()),
          ],
        ],
      ),
    );
  }
}

class _PasswordStagePanel extends StatelessWidget {
  const _PasswordStagePanel({
    required this.pinInput,
    required this.enabled,
    required this.onDigitPressed,
    required this.onBackspacePressed,
  });

  final String pinInput;
  final bool enabled;
  final ValueChanged<String> onDigitPressed;
  final VoidCallback onBackspacePressed;

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (context, constraints) {
        final availableHeight = constraints.maxHeight.isFinite
            ? constraints.maxHeight
            : constraints.minHeight > 0
            ? constraints.minHeight
            : 520.0;
        final itemWidth =
            (constraints.maxWidth -
                (AppSpacing.sm * (_pinPadCrossAxisCount - 1))) /
            _pinPadCrossAxisCount;
        final itemHeight = itemWidth / _pinPadChildAspectRatio;
        final panelHeight = itemHeight;
        final keypadHeight =
            (itemHeight * _pinPadRowCount) +
            (AppSpacing.sm * (_pinPadRowCount - 1));
        // 예전엔 freeSpace를 0으로까지 clamp하고 바깥 SizedBox는 항상
        // availableHeight로 고정해서, 점 표시판+키패드가 필요한 높이가
        // availableHeight보다 큰(작은 화면 등) 경우 Column 실제 콘텐츠가
        // 고정 박스보다 커져 RenderFlex 오버플로우가 났다. 최소 여백은
        // 유지하되, 콘텐츠가 실제로 필요로 하는 만큼 박스 높이 자체를
        // 늘려서(그 초과분은 상위 _wrapStagePanel의 스크롤이 안전망으로
        // 처리) 어떤 화면 크기에서도 오버플로우 없이 다 보이게 한다.
        final freeSpace = (availableHeight - panelHeight - keypadHeight).clamp(
          AppSpacing.sm * 2,
          double.infinity,
        );
        final sectionGap = freeSpace / 3;
        final columnHeight = panelHeight + keypadHeight + freeSpace;

        return SizedBox(
          width: double.infinity,
          height: columnHeight,
          child: Column(
            children: [
              SizedBox(height: sectionGap),
              _PasswordEntryPanel(pinInput: pinInput),
              SizedBox(height: sectionGap),
              SizedBox(
                height: keypadHeight,
                child: _PinPad(
                  enabled: enabled,
                  onDigitPressed: onDigitPressed,
                  onBackspacePressed: onBackspacePressed,
                ),
              ),
              SizedBox(height: sectionGap),
            ],
          ),
        );
      },
    );
  }
}

class _PaymentSummaryPanel extends StatelessWidget {
  const _PaymentSummaryPanel({
    super.key,
    required this.service,
    required this.items,
    required this.address,
  });

  final ShoppingFlowService service;
  final List<ShoppingCartItemViewData> items;
  final ShoppingAddressViewData? address;

  @override
  Widget build(BuildContext context) {
    final totalPrice = items.fold<int>(
      0,
      (sum, item) =>
          sum + (item.totalPrice ?? (item.product.price ?? 0) * item.quantity),
    );

    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(AppSpacing.cardPadding),
      // 다른 화면의 장바구니/배송지 카드와 통일: 검정 테두리 대신 그림자로만
      // 대비를 준다. '결제 전 확인' 타이틀은 굳이 없어도 아래 요약 문구로
      // 맥락이 충분히 전달돼서 뺐다.
      decoration: AppSurfaceStyles.floatingCard(
        radius: AppRadii.xl,
        boxShadow: AppSurfaceStyles.raisedShadow,
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            items.isEmpty
                ? '주문 금액을 확인하는 중이에요.'
                : '총 상품 ${items.length}개, 총 금액 ${formatPrice(totalPrice)}원',
            style: AppTextStyles.body1.copyWith(fontWeight: FontWeight.w800),
          ),
          const SizedBox(height: AppSpacing.md),
          // cartCompleted의 장바구니 카드와 동일하게 상품을 전부 보여준다
          // (예전엔 take(2)로 2개만 남기고 나머지를 그냥 숨겼는데, 총 금액엔
          // 전체가 반영되면서 화면엔 안 보이니 오히려 헷갈렸다). 카드가
          // 길어지면 이 패널을 감싸는 _wrapStagePanel의 항상-보이는
          // 스크롤바가 스크롤 가능함을 알려준다.
          if (items.isNotEmpty)
            for (var index = 0; index < items.length; index++)
              Padding(
                padding: EdgeInsets.only(
                  bottom: index == items.length - 1 ? 0 : AppSpacing.sm,
                ),
                child: _CartItemTile(
                  item: items[index],
                  service: service,
                  compact: true,
                ),
              ),
          if (address != null) ...[
            const SizedBox(height: AppSpacing.md),
            Container(
              width: double.infinity,
              padding: const EdgeInsets.all(AppSpacing.md),
              decoration: BoxDecoration(
                color: AppColors.surface,
                borderRadius: BorderRadius.circular(AppRadii.lg),
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    '배송지',
                    style: AppTextStyles.caption.copyWith(
                      fontSize: 14,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                  const SizedBox(height: AppSpacing.xs),
                  Text(address!.displayAddress, style: AppTextStyles.body1),
                  const SizedBox(height: AppSpacing.xs),
                  Text(address!.displayRecipient, style: AppTextStyles.body2),
                ],
              ),
            ),
          ],
        ],
      ),
    );
  }
}

class _PasswordEntryPanel extends StatelessWidget {
  const _PasswordEntryPanel({required this.pinInput});

  final String pinInput;

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (context, constraints) {
        final itemWidth =
            (constraints.maxWidth -
                (AppSpacing.sm * (_pinPadCrossAxisCount - 1))) /
            _pinPadCrossAxisCount;
        final panelHeight = itemWidth / _pinPadChildAspectRatio;

        return SizedBox(
          width: double.infinity,
          height: panelHeight,
          child: Container(
            padding: const EdgeInsets.symmetric(
              horizontal: AppSpacing.cardPadding,
            ),
            decoration: BoxDecoration(
              color: AppColors.surfaceMuted,
              borderRadius: BorderRadius.circular(AppRadii.xl),
            ),
            child: Center(
              child: Row(
                mainAxisSize: MainAxisSize.min,
                mainAxisAlignment: MainAxisAlignment.center,
                children: List.generate(6, (index) {
                  final isFilled = index < pinInput.length;
                  return Container(
                    width: 16,
                    height: 16,
                    margin: const EdgeInsets.symmetric(
                      horizontal: AppSpacing.xs,
                    ),
                    decoration: BoxDecoration(
                      color: isFilled ? AppColors.primaryPink : Colors.white,
                      shape: BoxShape.circle,
                      border: Border.all(
                        color: isFilled
                            ? AppColors.primaryPink
                            : AppColors.border,
                        width: 2,
                      ),
                    ),
                  );
                }),
              ),
            ),
          ),
        );
      },
    );
  }
}

class _CompletionPanel extends StatelessWidget {
  const _CompletionPanel({super.key});

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          SizedBox(
            width: 168,
            height: 168,
            child: Image.asset(
              'assets/images/character/full/ddalangoo_happy.png',
              fit: BoxFit.contain,
            ),
          ),
          const SizedBox(height: AppSpacing.xl),
          Text('쇼핑 완료!', style: AppTextStyles.display),
          const SizedBox(height: AppSpacing.sm),
          Text(
            '주문이 성공적으로 완료되었어요.\n이제 안심하고 기다리시면 돼요.',
            style: AppTextStyles.body1,
            textAlign: TextAlign.center,
          ),
        ],
      ),
    );
  }
}

class _ProductActionArea extends StatelessWidget {
  const _ProductActionArea({
    required this.response,
    required this.canTapReplies,
    required this.onActionSelected,
  });

  final AgentResponse? response;
  final bool canTapReplies;
  final Future<void> Function(String action) onActionSelected;

  @override
  Widget build(BuildContext context) {
    final pending = response?.pendingConfirmation;
    final payload = pending is Map && pending['payload'] is Map
        ? Map<String, dynamic>.from(pending['payload'] as Map)
        : const <String, dynamic>{};
    final actions = (payload['actions'] as List<dynamic>? ?? const <dynamic>[])
        .map((action) => action.toString())
        .where((action) => action.trim().isNotEmpty)
        .toList(growable: false);
    final orderBlockReason = payload['orderBlockReason']?.toString();
    final replyActions = <({String action, String label})>[
      if (actions.contains('order_now'))
        (action: 'order_now', label: '이 상품으로 주문하기'),
      if (actions.contains('add_to_cart'))
        (action: 'add_to_cart', label: '장바구니에 담기'),
      if (actions.contains('reject')) (action: 'reject', label: '다른 상품 보기'),
    ];

    return Column(
      children: [
        if (orderBlockReason != null && orderBlockReason.trim().isNotEmpty) ...[
          _InlineErrorBanner(message: orderBlockReason.trim()),
          const SizedBox(height: AppSpacing.md),
        ],
        if (replyActions.isNotEmpty)
          Wrap(
            spacing: AppSpacing.xs,
            runSpacing: AppSpacing.xs,
            alignment: WrapAlignment.center,
            children: replyActions
                .map((reply) {
                  return _QuickReplyChip(
                    label: reply.label,
                    onTap: canTapReplies
                        ? () => onActionSelected(reply.action)
                        : null,
                  );
                })
                .toList(growable: false),
          ),
      ],
    );
  }
}

class _OverlayReplyOption {
  const _OverlayReplyOption({required this.label, this.onTap});

  final String label;
  final VoidCallback? onTap;
}

class _QuickReplyChip extends StatelessWidget {
  const _QuickReplyChip({
    required this.label,
    this.onTap,
    this.textAlign = TextAlign.center,
  });

  final String label;
  final VoidCallback? onTap;
  final TextAlign textAlign;

  @override
  Widget build(BuildContext context) {
    final isEnabled = onTap != null;
    return Material(
      color: Colors.transparent,
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(AppRadii.pill),
        child: Padding(
          padding: const EdgeInsets.symmetric(vertical: AppSpacing.xxs),
          child: Text(
            '"$label"',
            style: AppTextStyles.caption.copyWith(
              color: isEnabled
                  ? AppColors.primaryPinkDark
                  : AppColors.primaryPinkDark.withValues(alpha: 0.45),
              fontWeight: FontWeight.w400,
            ),
            textAlign: textAlign,
          ),
        ),
      ),
    );
  }
}

class _CompactProductRow extends StatelessWidget {
  const _CompactProductRow({required this.product, required this.service});

  final ShoppingProductViewData product;
  final ShoppingFlowService service;

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        ClipRRect(
          borderRadius: BorderRadius.circular(AppRadii.lg),
          child: SizedBox(
            width: 84,
            height: 84,
            child: _ProductArtwork(product: product, service: service),
          ),
        ),
        const SizedBox(width: AppSpacing.md),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                product.title,
                style: AppTextStyles.body1.copyWith(
                  fontWeight: FontWeight.w800,
                  color: AppColors.textStrong,
                ),
              ),
              if (product.detailLine.isNotEmpty) ...[
                const SizedBox(height: AppSpacing.xs),
                Text(product.detailLine, style: AppTextStyles.body2),
              ],
              const SizedBox(height: AppSpacing.xs),
              Text(
                product.displayPrice,
                style: AppTextStyles.body1.copyWith(
                  color: AppColors.primaryPinkDark,
                  fontWeight: FontWeight.w800,
                ),
              ),
            ],
          ),
        ),
      ],
    );
  }
}

class _CartItemTile extends StatelessWidget {
  const _CartItemTile({
    required this.item,
    required this.service,
    this.compact = false,
    this.isUpdatingQuantity = false,
    this.onDecrease,
    this.onIncrease,
  });

  final ShoppingCartItemViewData item;
  final ShoppingFlowService service;
  final bool compact;
  final bool isUpdatingQuantity;
  final VoidCallback? onDecrease;
  final VoidCallback? onIncrease;

  @override
  Widget build(BuildContext context) {
    // 작은 정사각 썸네일 + 텍스트 대신, 상품 확인/선택 화면의 히어로
    // 카드처럼 상품 이미지를 타일 배경 전체에 깔고 그 위에 이름/수량/
    // 가격을 얹는다. 화면 간 상품 카드 스타일을 통일하고, 이름이 들어가는
    // 영역도 더 넓고 깔끔해진다.
    final tileHeight = compact ? 76.0 : 96.0;
    return Container(
      height: tileHeight,
      clipBehavior: Clip.antiAlias,
      // 진한 검정 테두리 대신, 카드가 배경에서 살짝 뜨는 느낌의 그림자로
      // 대비를 준다. Container가 boxShadow는 clip 밖에, 배경 이미지는
      // clipBehavior로 안쪽에서 잘리게 그려서 모서리가 깔끔하게 유지된다.
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(AppRadii.lg),
        boxShadow: AppSurfaceStyles.raisedShadow,
      ),
      child: Stack(
        children: [
          Positioned.fill(
            child: _ProductArtwork(
              product: item.product,
              service: service,
              fit: BoxFit.cover,
            ),
          ),
          Positioned.fill(
            child: DecoratedBox(
              decoration: BoxDecoration(
                gradient: LinearGradient(
                  begin: Alignment.centerLeft,
                  end: Alignment.centerRight,
                  colors: [
                    Colors.white.withValues(alpha: 0.95),
                    Colors.white.withValues(alpha: 0.86),
                    Colors.white.withValues(alpha: 0.55),
                  ],
                  stops: const [0, 0.55, 1],
                ),
              ),
            ),
          ),
          // 예전엔 이 Padding이 Positioned.fill이 아니라서 Stack이 내용
          // 높이만큼만 차지하고 카드 맨 위(top-left)에 붙어버렸다. 그래서
          // 수량 스테퍼/가격이 카드 위쪽 테두리에 거의 닿을 듯 겹쳐
          // 보였다. Positioned.fill로 카드 전체 높이를 채우게 하면 Row의
          // 기본 세로 정렬(가운데)이 그대로 적용돼 항상 카드 한가운데에
          // 온다.
          Positioned.fill(
            child: Padding(
              padding: EdgeInsets.symmetric(
                horizontal: compact ? AppSpacing.sm : AppSpacing.md,
              ),
              child: Row(
                children: [
                  Expanded(
                    child: Column(
                      mainAxisSize: MainAxisSize.min,
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          item.product.title,
                          maxLines: compact ? 1 : 2,
                          overflow: TextOverflow.ellipsis,
                          style: AppTextStyles.body2.copyWith(
                            color: AppColors.textStrong,
                            fontWeight: FontWeight.w700,
                          ),
                        ),
                        if (item.product.optionText?.trim().isNotEmpty ==
                            true) ...[
                          const SizedBox(height: AppSpacing.xs),
                          Text(
                            item.product.optionText!.trim(),
                            style: AppTextStyles.caption,
                          ),
                        ],
                      ],
                    ),
                  ),
                  const SizedBox(width: AppSpacing.sm),
                  Column(
                    mainAxisSize: MainAxisSize.min,
                    crossAxisAlignment: CrossAxisAlignment.end,
                    children: [
                      if (!compact &&
                          (onDecrease != null || onIncrease != null))
                        _CartQuantityStepper(
                          quantity: item.quantity,
                          isUpdating: isUpdatingQuantity,
                          onDecrease: onDecrease,
                          onIncrease: onIncrease,
                        )
                      else
                        Text(
                          '${item.quantity}개',
                          style: AppTextStyles.body2.copyWith(
                            fontWeight: FontWeight.w800,
                          ),
                        ),
                      const SizedBox(height: AppSpacing.xs),
                      Text(
                        item.displayTotalPrice,
                        textAlign: TextAlign.right,
                        style: AppTextStyles.caption.copyWith(
                          color: AppColors.primaryPinkDark,
                          fontWeight: FontWeight.w700,
                        ),
                      ),
                    ],
                  ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _CartQuantityStepper extends StatelessWidget {
  const _CartQuantityStepper({
    required this.quantity,
    required this.isUpdating,
    this.onDecrease,
    this.onIncrease,
  });

  final int quantity;
  final bool isUpdating;
  final VoidCallback? onDecrease;
  final VoidCallback? onIncrease;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(
        horizontal: AppSpacing.xs,
        vertical: 4,
      ),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(AppRadii.pill),
        border: Border.all(
          color: AppSurfaceStyles.standardOutlineColor,
          width: AppSurfaceStyles.thinOutlineWidth,
        ),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          _CartQuantityButton(
            icon: Icons.remove_rounded,
            onPressed: isUpdating ? null : onDecrease,
          ),
          SizedBox(
            width: 34,
            child: Text(
              '$quantity',
              textAlign: TextAlign.center,
              style: AppTextStyles.caption.copyWith(
                color: AppColors.textStrong,
                fontWeight: FontWeight.w800,
              ),
            ),
          ),
          _CartQuantityButton(
            icon: Icons.add_rounded,
            onPressed: isUpdating ? null : onIncrease,
          ),
        ],
      ),
    );
  }
}

class _CartQuantityButton extends StatelessWidget {
  const _CartQuantityButton({required this.icon, this.onPressed});

  final IconData icon;
  final VoidCallback? onPressed;

  @override
  Widget build(BuildContext context) {
    return InkWell(
      onTap: onPressed,
      borderRadius: BorderRadius.circular(AppRadii.pill),
      child: SizedBox(
        width: 24,
        height: 24,
        child: Icon(
          icon,
          size: 18,
          color: onPressed == null ? AppColors.textMuted : AppColors.textStrong,
        ),
      ),
    );
  }
}

class _ProductArtwork extends StatelessWidget {
  const _ProductArtwork({
    required this.product,
    required this.service,
    this.height,
    this.fit = BoxFit.cover,
  });

  final ShoppingProductViewData product;
  final ShoppingFlowService service;
  final double? height;
  final BoxFit fit;

  @override
  Widget build(BuildContext context) {
    final fallback = service.assetForProductName(product.title);
    final imageUrl = product.imageUrl?.trim();

    if (imageUrl != null && imageUrl.isNotEmpty) {
      return Image.network(
        imageUrl,
        height: height,
        fit: fit,
        errorBuilder: (_, _, _) => Image.asset(fallback.assetPath, fit: fit),
      );
    }

    return Image.asset(fallback.assetPath, height: height, fit: fit);
  }
}

class _RecommendationReasonNote extends StatelessWidget {
  const _RecommendationReasonNote({required this.reason});

  final String reason;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(
        horizontal: AppSpacing.sm,
        vertical: AppSpacing.xs,
      ),
      decoration: BoxDecoration(
        color: Colors.white.withValues(alpha: 0.72),
        borderRadius: BorderRadius.circular(AppRadii.md),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: [
          const Icon(
            Icons.auto_awesome_rounded,
            size: 16,
            color: AppColors.primaryPinkDark,
          ),
          const SizedBox(width: AppSpacing.xs),
          Flexible(
            child: Text(
              reason,
              maxLines: 2,
              overflow: TextOverflow.ellipsis,
              style: AppTextStyles.caption.copyWith(
                color: AppColors.primaryPinkDark,
                fontWeight: FontWeight.w700,
                height: 1.3,
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _PlatformPill extends StatelessWidget {
  const _PlatformPill({
    required this.label,
    this.backgroundColor = AppColors.secondaryPink,
    this.bannerHeight = 24,
  });

  static const Map<String, String> _bannerAssetsByLabel = <String, String>{
    '컬리': 'assets/images/platform/banner/kurly_banner.png',
    '네이버': 'assets/images/platform/banner/naver_banner.png',
    '지마켓': 'assets/images/platform/banner/gmarket_banner.png',
    '쿠팡': 'assets/images/platform/banner/coupang_banner.png',
    '현대홈쇼핑': 'assets/images/platform/banner/hyundaihomeshopping_banner.png',
  };

  final String label;
  final Color backgroundColor;
  final double bannerHeight;

  @override
  Widget build(BuildContext context) {
    final trimmedLabel = label.trim();
    final bannerAssetPath = _bannerAssetsByLabel[trimmedLabel];
    if (bannerAssetPath != null) {
      return SizedBox(
        height: bannerHeight,
        child: Image.asset(
          bannerAssetPath,
          fit: BoxFit.contain,
          errorBuilder: (_, _, _) => _buildTextFallback(),
        ),
      );
    }

    return _buildTextFallback();
  }

  Widget _buildTextFallback() {
    return Container(
      padding: const EdgeInsets.symmetric(
        horizontal: AppSpacing.sm,
        vertical: AppSpacing.xs,
      ),
      decoration: BoxDecoration(
        color: backgroundColor,
        borderRadius: BorderRadius.circular(AppRadii.pill),
      ),
      child: Text(
        label,
        style: AppTextStyles.caption.copyWith(
          color: AppColors.primaryPinkDark,
          fontWeight: FontWeight.w700,
        ),
      ),
    );
  }
}

class _InfoRow extends StatelessWidget {
  const _InfoRow({required this.label, required this.value});

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        SizedBox(
          width: 72,
          child: Text(
            label,
            style: AppTextStyles.body2.copyWith(
              fontWeight: FontWeight.w700,
              color: AppColors.textMuted,
            ),
          ),
        ),
        const SizedBox(width: AppSpacing.sm),
        Expanded(child: Text(value, style: AppTextStyles.body1)),
      ],
    );
  }
}

class _PinPad extends StatelessWidget {
  const _PinPad({
    required this.enabled,
    required this.onDigitPressed,
    required this.onBackspacePressed,
  });

  final bool enabled;
  final ValueChanged<String> onDigitPressed;
  final VoidCallback onBackspacePressed;

  @override
  Widget build(BuildContext context) {
    final keys = const <String>[
      '1',
      '2',
      '3',
      '4',
      '5',
      '6',
      '7',
      '8',
      '9',
      '',
      '0',
      'back',
    ];

    return GridView.builder(
      shrinkWrap: true,
      physics: const NeverScrollableScrollPhysics(),
      itemCount: keys.length,
      gridDelegate: const SliverGridDelegateWithFixedCrossAxisCount(
        crossAxisCount: _pinPadCrossAxisCount,
        mainAxisSpacing: AppSpacing.sm,
        crossAxisSpacing: AppSpacing.sm,
        childAspectRatio: _pinPadChildAspectRatio,
      ),
      itemBuilder: (context, index) {
        final key = keys[index];
        if (key.isEmpty) {
          return const SizedBox.shrink();
        }

        final isBackspace = key == 'back';
        return InkWell(
          onTap: !enabled
              ? null
              : isBackspace
              ? onBackspacePressed
              : () => onDigitPressed(key),
          borderRadius: BorderRadius.circular(AppRadii.lg),
          child: Container(
            decoration: BoxDecoration(
              color: Colors.white,
              borderRadius: BorderRadius.circular(AppRadii.lg),
              border: Border.all(
                color: AppSurfaceStyles.standardOutlineColor,
                width: AppSurfaceStyles.pinPadOutlineWidth,
              ),
            ),
            alignment: Alignment.center,
            child: isBackspace
                ? const Icon(
                    Icons.backspace_outlined,
                    color: AppColors.textPrimary,
                  )
                : Text(
                    key,
                    style: AppTextStyles.title1.copyWith(
                      fontSize: 30,
                      fontWeight: FontWeight.w800,
                    ),
                  ),
          ),
        );
      },
    );
  }
}

extension<T> on List<T> {
  T? get firstOrNull => isEmpty ? null : first;
}
