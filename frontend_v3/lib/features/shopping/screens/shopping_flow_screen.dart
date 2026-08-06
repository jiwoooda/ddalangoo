import 'dart:async';

import 'package:flutter/material.dart';

import '../../../app/routes.dart';
import '../../../app/theme/app_colors.dart';
import '../../../app/theme/app_radii.dart';
import '../../../app/theme/app_spacing.dart';
import '../../../app/theme/app_text_styles.dart';
import '../../../core/services/voice_service.dart';
import '../../../data/models/agent_model.dart';
import '../../../shared/layout/layout_presets.dart';
import '../../../shared/layout/screen_frame.dart';
import '../../../shared/widgets/bottom_status_banner.dart';
import '../../../shared/widgets/dialogue_bubble.dart';
import '../../../shared/widgets/end_conversation_button.dart';
import '../../../shared/widgets/primary_button.dart';
import '../../../shared/widgets/shopping_progress_stepper.dart';
import '../../../shared/widgets/voice_input_button.dart';
import '../models/shopping_flow_models.dart';
import 'shopping_webview_screen.dart';
import '../services/shopping_flow_service.dart';

class ShoppingFlowScreen extends StatefulWidget {
  const ShoppingFlowScreen({super.key, this.userName, this.service});

  final String? userName;
  final ShoppingFlowService? service;

  @override
  State<ShoppingFlowScreen> createState() => _ShoppingFlowScreenState();
}

class _ShoppingFlowScreenState extends State<ShoppingFlowScreen> {
  late final ShoppingFlowService _service;
  final VoiceService _voiceService = VoiceService.instance;

  Timer? _pollTimer;
  bool _isInitializing = true;
  bool _isSubmitting = false;
  bool _isRefreshingConversation = false;
  bool _isWebviewOpen = false;
  bool _isRecording = false;
  bool _isSpeaking = false;
  int? _userId;
  String? _resolvedUserName;
  AgentResponse? _response;
  ShoppingAddressViewData? _fallbackAddress;
  ShoppingFlowViewStage _viewStage = ShoppingFlowViewStage.askProduct;
  String? _inlineError;
  String _pinInput = '';
  String? _lastWebviewCommandKey;
  String? _lastSpokenPromptKey;
  final Set<String> _completedWebviewCommandKeys = <String>{};

  @override
  void initState() {
    super.initState();
    _service = widget.service ?? ShoppingFlowService();
    _resolvedUserName = widget.userName?.trim();
    unawaited(_bootstrapVoice());
    unawaited(_bootstrap());
  }

  @override
  void dispose() {
    _pollTimer?.cancel();
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
  }

  Future<void> _bootstrap() async {
    setState(() {
      _isInitializing = true;
      _inlineError = null;
    });

    try {
      final userId = await _service.resolveUserId();
      final resolvedUserName = _resolvedUserName?.isNotEmpty == true
          ? _resolvedUserName
          : await _service.resolveUserName(userId: userId);
      final fallbackAddress = await _service.fetchDefaultAddress(
        userId: userId,
        fallbackRecipientName: resolvedUserName,
      );

      if (!mounted) {
        return;
      }

      setState(() {
        _userId = userId;
        _resolvedUserName = resolvedUserName;
        _fallbackAddress = fallbackAddress;
        _isInitializing = false;
      });
      unawaited(_speakPromptIfNeeded(force: true));
    } catch (error) {
      if (!mounted) {
        return;
      }
      setState(() {
        _isInitializing = false;
        _inlineError = '쇼핑 준비 중 문제가 생겼어요. 잠시 후 다시 시도해주세요.';
      });
    }
  }

  Future<void> _refreshFallbackAddress() async {
    final userId = _userId;
    if (userId == null) {
      return;
    }

    final fallbackAddress = await _service.fetchDefaultAddress(
      userId: userId,
      fallbackRecipientName: _resolvedUserName,
    );
    if (!mounted || fallbackAddress == null) {
      return;
    }

    setState(() {
      _fallbackAddress = fallbackAddress;
    });
  }

  void _applyResponse(AgentResponse response) {
    final nextStage = _service.inferViewStage(response);
    setState(() {
      _response = response;
      _viewStage = nextStage;
      _inlineError = null;
      if (nextStage != ShoppingFlowViewStage.paymentPassword) {
        _pinInput = '';
      }
    });
    _syncPolling();
    _handlePendingWebviewTask();
    unawaited(_speakPromptIfNeeded());

    if (_fallbackAddress == null &&
        (nextStage == ShoppingFlowViewStage.addressConfirmation ||
            nextStage == ShoppingFlowViewStage.paymentConfirmation ||
            nextStage == ShoppingFlowViewStage.paymentPassword ||
            nextStage == ShoppingFlowViewStage.paymentProcessing)) {
      unawaited(_refreshFallbackAddress());
    }
  }

  void _handlePendingWebviewTask() {
    final response = _response;
    if (!mounted || response == null) {
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
              _applyResponse(nextResponse);
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

  void _syncPolling() {
    _pollTimer?.cancel();
    final response = _response;
    if (response == null || !_service.requiresPolling(response)) {
      return;
    }

    _pollTimer = Timer.periodic(const Duration(seconds: 2), (_) {
      unawaited(_refreshConversation());
    });
  }

  Future<void> _refreshConversation() async {
    final response = _response;
    if (_isRefreshingConversation || response == null) {
      return;
    }

    _isRefreshingConversation = true;
    try {
      final refreshed = await _service.getConversation(response.conversationId);
      if (!mounted) {
        return;
      }
      _applyResponse(refreshed);
    } catch (_) {
      // Ignore silent polling failures and keep the current UI.
    } finally {
      _isRefreshingConversation = false;
    }
  }

  Future<void> _submitMessage(
    String message, {
    bool redactMessageForLogs = false,
  }) async {
    final trimmed = message.trim();
    if (trimmed.isEmpty || _isSubmitting) {
      return;
    }

    final userId = _userId;
    if (userId == null) {
      return;
    }
    final shouldStartFreshConversation = _shouldStartFreshConversation(
      nextMessage: trimmed,
    );
    final conversationId = shouldStartFreshConversation
        ? null
        : _response?.conversationId;

    setState(() {
      _isSubmitting = true;
      _inlineError = null;
      if (conversationId == null) {
        _viewStage = ShoppingFlowViewStage.searchingProduct;
      }
    });

    try {
      final response = await _service.submitMessage(
        userId: userId,
        message: trimmed,
        conversationId: conversationId,
        redactMessageForLogs: redactMessageForLogs,
      );
      if (!mounted) {
        return;
      }
      _applyResponse(response);
    } catch (error) {
      if (!mounted) {
        return;
      }
      setState(() {
        _inlineError = '메시지를 보내지 못했어요. 다시 한 번 시도해주세요.';
      });
    } finally {
      if (mounted) {
        setState(() {
          _isSubmitting = false;
        });
      }
    }
  }

  Future<void> _confirmAction(String action) async {
    final response = _response;
    if (response == null || _isSubmitting) {
      return;
    }

    setState(() {
      _isSubmitting = true;
      _inlineError = null;
    });

    try {
      final nextResponse = await _service.confirmProductAction(
        response: response,
        action: action,
      );
      if (!mounted) {
        return;
      }
      _applyResponse(nextResponse);
    } catch (_) {
      if (action == 'reject') {
        await _submitMessage('다른 상품 보여줘');
      } else if (mounted) {
        setState(() {
          _inlineError = '선택을 처리하지 못했어요. 다시 시도해주세요.';
        });
      }
    } finally {
      if (mounted) {
        setState(() {
          _isSubmitting = false;
        });
      }
    }
  }

  Future<void> _handleExit() async {
    await _voiceService.stopSpeaking();
    if (_isRecording) {
      await _voiceService.cancelRecording();
    }
    final conversationId = _response?.conversationId;
    if (conversationId != null) {
      try {
        await _service.cancelConversation(conversationId);
      } catch (_) {}
    }
    if (!mounted) {
      return;
    }
    Navigator.of(
      context,
    ).pushNamedAndRemoveUntil(AppRoutes.home, (route) => false);
  }

  void _appendPinDigit(String digit) {
    if (_pinInput.length >= 6) {
      return;
    }
    setState(() {
      _pinInput = '$_pinInput$digit';
    });
  }

  void _removePinDigit() {
    if (_pinInput.isEmpty) {
      return;
    }
    setState(() {
      _pinInput = _pinInput.substring(0, _pinInput.length - 1);
    });
  }

  Future<void> _submitPin() async {
    if (_pinInput.isEmpty) {
      return;
    }
    await _submitMessage(_pinInput, redactMessageForLogs: true);
  }

  bool get _supportsVoiceInput {
    switch (_viewStage) {
      case ShoppingFlowViewStage.askProduct:
      case ShoppingFlowViewStage.quantitySelection:
      case ShoppingFlowViewStage.cartCompleted:
      case ShoppingFlowViewStage.addressConfirmation:
      case ShoppingFlowViewStage.paymentConfirmation:
      case ShoppingFlowViewStage.error:
        return true;
      case ShoppingFlowViewStage.searchingProduct:
      case ShoppingFlowViewStage.productSelection:
      case ShoppingFlowViewStage.cartProcessing:
      case ShoppingFlowViewStage.paymentPassword:
      case ShoppingFlowViewStage.paymentProcessing:
      case ShoppingFlowViewStage.completed:
        return false;
    }
  }

  String get _voiceButtonLabel {
    if (_isRecording) {
      return '듣고 있어요. 다시 누르면 전송';
    }
    if (_isSpeaking) {
      return '딸랑구가 안내 중이에요';
    }

    return switch (_viewStage) {
      ShoppingFlowViewStage.askProduct => '눌러서 쇼핑 요청하기',
      ShoppingFlowViewStage.quantitySelection => '수량 말씀하기',
      ShoppingFlowViewStage.cartCompleted => '다음 단계 말씀하기',
      ShoppingFlowViewStage.addressConfirmation => '배송지 답변하기',
      ShoppingFlowViewStage.paymentConfirmation => '결제 의사 말씀하기',
      ShoppingFlowViewStage.error => '다시 말씀하기',
      _ => '눌러서 말하기',
    };
  }

  String? get _spokenPromptText {
    final assistantText = _assistantText;
    if (assistantText != null && assistantText.isNotEmpty) {
      return assistantText;
    }

    switch (_viewStage) {
      case ShoppingFlowViewStage.askProduct:
      case ShoppingFlowViewStage.searchingProduct:
        if (_resolvedUserName != null && _resolvedUserName!.trim().isNotEmpty) {
          return '${_resolvedUserName!}님, 뭐가 필요하세요?';
        }
        return '뭐가 필요하세요?';
      case ShoppingFlowViewStage.quantitySelection:
        return '좋아요. 몇 개 담아드릴까요?';
      case ShoppingFlowViewStage.cartCompleted:
        return '장바구니에 담았어요. 이제 결제를 진행할까요?';
      case ShoppingFlowViewStage.addressConfirmation:
        return '배송지를 확인해주세요. 맞으면 네, 맞아요 라고 말씀해주세요.';
      case ShoppingFlowViewStage.paymentConfirmation:
        return '결제를 진행할까요? 맞으면 네, 진행해줘 라고 말씀해주세요.';
      case ShoppingFlowViewStage.error:
        return '조금만 다시 말씀해주시면 이어서 도와드릴게요.';
      case ShoppingFlowViewStage.productSelection:
      case ShoppingFlowViewStage.cartProcessing:
      case ShoppingFlowViewStage.paymentPassword:
      case ShoppingFlowViewStage.paymentProcessing:
      case ShoppingFlowViewStage.completed:
        return null;
    }
  }

  Future<void> _speakPromptIfNeeded({bool force = false}) async {
    final prompt = _spokenPromptText?.trim();
    if (prompt == null || prompt.isEmpty || _isRecording) {
      return;
    }

    final promptKey =
        '${_response?.conversationId ?? 0}:${_viewStage.name}:$prompt';
    if (!force && _lastSpokenPromptKey == promptKey) {
      return;
    }
    _lastSpokenPromptKey = promptKey;

    if (mounted) {
      setState(() => _isSpeaking = true);
    }

    try {
      await _voiceService.speak(prompt);
    } catch (_) {
      // Voice playback is best-effort.
    } finally {
      if (mounted) {
        setState(() => _isSpeaking = false);
      }
    }
  }

  Future<void> _toggleVoiceInput() async {
    if (!_supportsVoiceInput || _isInitializing || _isSubmitting) {
      return;
    }

    if (_isRecording) {
      await _stopRecordingAndSubmit();
      return;
    }

    await _voiceService.stopSpeaking();
    if (mounted) {
      setState(() {
        _isSpeaking = false;
        _inlineError = null;
        _isRecording = true;
      });
    }

    try {
      await _voiceService.startRecording();
    } catch (_) {
      if (!mounted) {
        return;
      }
      setState(() {
        _isRecording = false;
        _inlineError = '마이크를 시작하지 못했어요. 잠시 후 다시 시도해주세요.';
      });
    }
  }

  bool _shouldStartFreshConversation({required String nextMessage}) {
    final response = _response;
    if (response == null) {
      return true;
    }

    final stage = response.stage.trim().toLowerCase();
    final assistantMessage = response.assistantMessage.trim();
    final hasFlowProgress =
        response.recommendations.isNotEmpty ||
        response.selectedProduct != null ||
        response.pendingConfirmation != null ||
        response.availableOptions != null ||
        response.deliveryAddress != null ||
        response.cart != null ||
        response.order != null ||
        response.payment != null ||
        response.uiCommand != null ||
        response.asyncStatus != null;

    if (hasFlowProgress) {
      return false;
    }

    final isRetryPrompt =
        assistantMessage.contains('다시 한번 말씀해 주세요') ||
        assistantMessage.contains('다시 말씀');
    final isEarlyStage =
        _viewStage == ShoppingFlowViewStage.askProduct ||
        _viewStage == ShoppingFlowViewStage.error;
    final isExampleMessage = _service
        .quickRepliesFor(ShoppingFlowViewStage.askProduct)
        .contains(nextMessage);

    return isEarlyStage &&
        (stage == 'idle' || isRetryPrompt || isExampleMessage);
  }

  Future<void> _stopRecordingAndSubmit() async {
    if (!_isRecording) {
      return;
    }

    setState(() {
      _isRecording = false;
      _inlineError = null;
    });

    try {
      final transcript = await _voiceService.stopRecordingAndTranscribe();
      final trimmed = transcript.trim();
      if (!mounted) {
        return;
      }
      if (trimmed.isEmpty) {
        setState(() {
          _inlineError = '잘 듣지 못했어요. 한 번 더 말씀해주세요.';
        });
        return;
      }

      await _submitMessage(trimmed);
    } catch (_) {
      if (!mounted) {
        return;
      }
      setState(() {
        _inlineError = '음성 인식 중 문제가 생겼어요. 한 번 더 말씀해주세요.';
      });
    }
  }

  List<DialogueSegment>? get _fallbackPromptSegments {
    switch (_viewStage) {
      case ShoppingFlowViewStage.askProduct:
      case ShoppingFlowViewStage.searchingProduct:
        if (_resolvedUserName != null && _resolvedUserName!.trim().isNotEmpty) {
          return [
            DialogueSegment(text: '${_resolvedUserName!}님\n', emphasized: true),
            const DialogueSegment(text: '뭐가 필요하세요?'),
          ];
        }
        return const [DialogueSegment(text: '뭐가 필요하세요?')];
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

  String? get _assistantText {
    final message = _response?.assistantMessage.trim();
    if (message != null && message.isNotEmpty) {
      return message;
    }
    return null;
  }

  @override
  Widget build(BuildContext context) {
    final currentStep = _service.progressStepFor(_viewStage);
    final completedSteps = _service.completedStepsFor(_viewStage);

    return ScreenFrame(
      preset: LayoutPreset.conversation,
      child: Column(
        children: [
          _buildHeader(),
          const SizedBox(height: AppSpacing.sm),
          ShoppingProgressStepper(
            currentStep: currentStep,
            completedSteps: completedSteps,
          ),
          const SizedBox(height: AppSpacing.md),
          DialogueBubble(
            contentKey: ValueKey(
              '${_response?.conversationId ?? 0}-${_response?.stage}-${_assistantText ?? _viewStage.name}',
            ),
            animateTextChanges: true,
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
          const SizedBox(height: AppSpacing.lg),
          Expanded(
            child: AnimatedSwitcher(
              duration: const Duration(milliseconds: 260),
              switchInCurve: Curves.easeOutCubic,
              switchOutCurve: Curves.easeInCubic,
              child: KeyedSubtree(
                key: ValueKey<String>(
                  '${_viewStage.name}:${_isInitializing ? 'init' : 'ready'}',
                ),
                child: _buildStageScene(),
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildHeader() {
    return Row(
      children: [
        const Spacer(),
        EndConversationButton(compact: true, onPressed: _handleExit),
      ],
    );
  }

  Widget _wrapStagePanel(Widget child) {
    return LayoutBuilder(
      builder: (context, constraints) {
        final minHeight = constraints.maxHeight.isFinite
            ? constraints.maxHeight
            : 0.0;
        return SingleChildScrollView(
          physics: const ClampingScrollPhysics(),
          child: ConstrainedBox(
            constraints: BoxConstraints(minHeight: minHeight),
            child: child,
          ),
        );
      },
    );
  }

  Widget _buildStageScene() {
    return Column(
      children: [
        Expanded(child: _buildStageContent()),
        const SizedBox(height: AppSpacing.lg),
        if (_inlineError != null) ...[
          _InlineErrorBanner(message: _inlineError!),
          const SizedBox(height: AppSpacing.md),
        ],
        _buildBottomArea(),
      ],
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
    final cartItems = _response == null
        ? const <ShoppingCartItemViewData>[]
        : _service.extractCartItems(_response!);
    final address = _response == null
        ? _fallbackAddress
        : _service.extractAddress(
            _response!,
            fallback: _fallbackAddress,
            fallbackRecipientName: _resolvedUserName,
          );

    switch (_viewStage) {
      case ShoppingFlowViewStage.askProduct:
        return _EmptyStatePanel(
          key: const ValueKey('ask-product'),
          assetPath: 'assets/images/character/full/ddalangoo_standing.png',
          title: '예시 문장을 눌러 바로 시작할 수도 있어요.',
          caption: '예시 문장과 음성 요청은 같은 쇼핑 대화로 이어집니다.',
        );
      case ShoppingFlowViewStage.searchingProduct:
        return _wrapStagePanel(
          _StatusPanel(
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
          ),
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
        return _wrapStagePanel(
          _StatusPanel(
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
          ),
        );
      case ShoppingFlowViewStage.cartCompleted:
        return _wrapStagePanel(
          _CartSummaryPanel(
            key: const ValueKey('cart-completed'),
            service: _service,
            userName: _resolvedUserName,
            items: cartItems,
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
          _PasswordEntryPanel(
            key: const ValueKey('payment-password'),
            pinInput: _pinInput,
          ),
        );
      case ShoppingFlowViewStage.paymentProcessing:
        return _wrapStagePanel(
          _StatusPanel(
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
          ),
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
        return Column(
          children: [
            Wrap(
              spacing: AppSpacing.xs,
              runSpacing: AppSpacing.xs,
              alignment: WrapAlignment.center,
              children: _service
                  .quickRepliesFor(_viewStage)
                  .map((reply) {
                    return _QuickReplyChip(
                      label: reply,
                      onTap: _isSubmitting ? null : () => _submitMessage(reply),
                    );
                  })
                  .toList(growable: false),
            ),
            const SizedBox(height: AppSpacing.lg),
            VoiceInputButton(
              label: _voiceButtonLabel,
              state: _isInitializing
                  ? VoiceInputState.inactive
                  : _isRecording
                  ? VoiceInputState.listening
                  : VoiceInputState.active,
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
                  'assets/images/character/top/ddalangoo_top.png',
            ),
          ],
        );
      case ShoppingFlowViewStage.productSelection:
        return _ProductActionArea(
          response: _response,
          isSubmitting: _isSubmitting,
          onActionSelected: _confirmAction,
        );
      case ShoppingFlowViewStage.quantitySelection:
      case ShoppingFlowViewStage.cartCompleted:
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
                        onTap: _isSubmitting
                            ? null
                            : () => _submitMessage(reply),
                      );
                    })
                    .toList(growable: false),
              ),
            if (replies.isNotEmpty) const SizedBox(height: AppSpacing.md),
            VoiceInputButton(
              label: _voiceButtonLabel,
              state: !_supportsVoiceInput
                  ? VoiceInputState.inactive
                  : _isRecording
                  ? VoiceInputState.listening
                  : VoiceInputState.active,
              onPressed: _toggleVoiceInput,
            ),
          ],
        );
      case ShoppingFlowViewStage.paymentPassword:
        return Column(
          children: [
            _PinPad(
              enabled: !_isSubmitting,
              onDigitPressed: _appendPinDigit,
              onBackspacePressed: _removePinDigit,
            ),
            const SizedBox(height: AppSpacing.lg),
            PrimaryButton(
              label: _isSubmitting ? '확인 중...' : '비밀번호 확인',
              onPressed: _isSubmitting || _pinInput.isEmpty ? null : _submitPin,
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
    required this.title,
    required this.caption,
  });

  final String assetPath;
  final String title;
  final String caption;

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

        return SingleChildScrollView(
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
                SizedBox(height: titleSpacing),
                Text(
                  title,
                  textAlign: TextAlign.center,
                  style: AppTextStyles.body1.copyWith(
                    fontWeight: FontWeight.w800,
                  ),
                ),
                SizedBox(height: captionSpacing),
                Text(
                  caption,
                  textAlign: TextAlign.center,
                  style: AppTextStyles.body2,
                ),
              ],
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
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(AppSpacing.cardPadding),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(AppRadii.xl),
        border: Border.all(color: AppColors.border),
      ),
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
            style: AppTextStyles.title2.copyWith(fontSize: 26, height: 1.3),
          ),
          const SizedBox(height: AppSpacing.md),
          if (product != null && service != null) ...[
            _CompactProductRow(product: product!, service: service!),
            const SizedBox(height: AppSpacing.lg),
          ] else if (assetPath != null) ...[
            Center(child: Image.asset(assetPath!, height: 180)),
            const SizedBox(height: AppSpacing.lg),
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

    return SingleChildScrollView(
      child: Column(
        children: [
          _ProductRecommendationCard(
            product: primaryProduct!,
            service: service,
          ),
          if (secondaryProducts.isNotEmpty) ...[
            const SizedBox(height: AppSpacing.lg),
            Align(
              alignment: Alignment.centerLeft,
              child: Text(
                '다른 후보',
                style: AppTextStyles.body1.copyWith(
                  fontWeight: FontWeight.w800,
                ),
              ),
            ),
            const SizedBox(height: AppSpacing.sm),
            for (final recommendation in secondaryProducts) ...[
              _SecondaryRecommendationTile(
                product: service.productFromRecommendation(recommendation),
                service: service,
              ),
              const SizedBox(height: AppSpacing.sm),
            ],
          ],
        ],
      ),
    );
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

    final previewAsset = service.assetForProductName(product!.title);
    return Container(
      width: double.infinity,
      decoration: BoxDecoration(
        color: previewAsset.backgroundColor,
        borderRadius: BorderRadius.circular(AppRadii.xl),
        border: Border.all(color: AppColors.border),
      ),
      clipBehavior: Clip.antiAlias,
      child: Stack(
        children: [
          Positioned.fill(
            child: _ProductArtwork(
              product: product!,
              service: service,
              height: 320,
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
                    Colors.white.withValues(alpha: 0.02),
                    Colors.white.withValues(alpha: 0.18),
                    Colors.white.withValues(alpha: 0.94),
                  ],
                  stops: const [0, 0.52, 1],
                ),
              ),
            ),
          ),
          Padding(
            padding: const EdgeInsets.all(AppSpacing.cardPadding),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              mainAxisAlignment: MainAxisAlignment.end,
              children: [
                _PlatformPill(
                  label: service.platformLabel(product!.platform),
                  backgroundColor: Colors.white.withValues(alpha: 0.92),
                ),
                const SizedBox(height: AppSpacing.md),
                Text(
                  product!.title,
                  style: AppTextStyles.title2.copyWith(
                    fontSize: 26,
                    color: AppColors.textStrong,
                  ),
                ),
                if (product!.detailLine.isNotEmpty) ...[
                  const SizedBox(height: AppSpacing.sm),
                  Text(product!.detailLine, style: AppTextStyles.body2),
                ],
                const SizedBox(height: AppSpacing.sm),
                Text(
                  product!.displayPrice,
                  style: AppTextStyles.title1.copyWith(
                    color: AppColors.textStrong,
                    fontWeight: FontWeight.w800,
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

class _CartSummaryPanel extends StatelessWidget {
  const _CartSummaryPanel({
    super.key,
    required this.service,
    required this.userName,
    required this.items,
  });

  final ShoppingFlowService service;
  final String? userName;
  final List<ShoppingCartItemViewData> items;

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
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(AppRadii.xl),
        border: Border.all(color: AppColors.border),
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
          const SizedBox(height: AppSpacing.sm),
          Text(
            '지금 담긴 상품과 금액을 확인해보세요.',
            style: AppTextStyles.body2.copyWith(height: 1.45),
          ),
          const SizedBox(height: AppSpacing.lg),
          if (items.isEmpty)
            const Text('담긴 상품을 아직 확인하는 중이에요.', style: AppTextStyles.body2)
          else
            Column(
              children: [
                for (var index = 0; index < items.length; index++) ...[
                  _CartItemTile(item: items[index], service: service),
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
      decoration: BoxDecoration(
        color: AppColors.surfaceMuted,
        borderRadius: BorderRadius.circular(AppRadii.xl),
        border: Border.all(color: AppColors.border),
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
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(AppRadii.xl),
        border: Border.all(color: AppColors.border),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('결제 전 확인', style: AppTextStyles.title2),
          const SizedBox(height: AppSpacing.md),
          Text(
            items.isEmpty
                ? '주문 금액을 확인하는 중이에요.'
                : '${items.length}개 상품 · ${formatPrice(totalPrice)}원',
            style: AppTextStyles.body1.copyWith(fontWeight: FontWeight.w800),
          ),
          const SizedBox(height: AppSpacing.md),
          if (items.isNotEmpty)
            ...items.take(2).map((item) {
              return Padding(
                padding: const EdgeInsets.only(bottom: AppSpacing.sm),
                child: _CartItemTile(
                  item: item,
                  service: service,
                  compact: true,
                ),
              );
            }),
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
  const _PasswordEntryPanel({super.key, required this.pinInput});

  final String pinInput;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.symmetric(
        horizontal: AppSpacing.cardPadding,
        vertical: AppSpacing.md,
      ),
      decoration: BoxDecoration(
        color: AppColors.surfaceMuted,
        borderRadius: BorderRadius.circular(AppRadii.xl),
        border: Border.all(color: AppColors.border),
      ),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Text(
            '6자리 비밀번호',
            style: AppTextStyles.body2.copyWith(
              color: AppColors.textMuted,
              fontWeight: FontWeight.w700,
            ),
            textAlign: TextAlign.center,
          ),
          const SizedBox(height: AppSpacing.sm),
          Row(
            mainAxisSize: MainAxisSize.min,
            mainAxisAlignment: MainAxisAlignment.center,
            children: List.generate(6, (index) {
              final isFilled = index < pinInput.length;
              return Container(
                width: 16,
                height: 16,
                margin: const EdgeInsets.symmetric(horizontal: AppSpacing.xs),
                decoration: BoxDecoration(
                  color: isFilled ? AppColors.primaryPink : Colors.white,
                  shape: BoxShape.circle,
                  border: Border.all(
                    color: isFilled ? AppColors.primaryPink : AppColors.border,
                    width: 2,
                  ),
                ),
              );
            }),
          ),
          const SizedBox(height: AppSpacing.sm),
          Text(
            pinInput.isEmpty
                ? '숫자를 눌러 입력을 시작해주세요.'
                : '${pinInput.length}자리 입력됨',
            style: AppTextStyles.body2,
          ),
        ],
      ),
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
    required this.isSubmitting,
    required this.onActionSelected,
  });

  final AgentResponse? response;
  final bool isSubmitting;
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

    return Column(
      children: [
        if (orderBlockReason != null && orderBlockReason.trim().isNotEmpty) ...[
          _InlineErrorBanner(message: orderBlockReason.trim()),
          const SizedBox(height: AppSpacing.md),
        ],
        if (actions.contains('order_now'))
          PrimaryButton(
            label: '이 상품으로 주문하기',
            icon: Icons.shopping_bag_rounded,
            onPressed: isSubmitting
                ? null
                : () => onActionSelected('order_now'),
          ),
        if (actions.contains('order_now'))
          const SizedBox(height: AppSpacing.sm),
        if (actions.contains('add_to_cart'))
          SizedBox(
            width: double.infinity,
            height: AppSpacing.buttonHeight,
            child: OutlinedButton(
              onPressed: isSubmitting
                  ? null
                  : () => onActionSelected('add_to_cart'),
              child: const Text('장바구니에 담기'),
            ),
          ),
        if (actions.contains('add_to_cart'))
          const SizedBox(height: AppSpacing.sm),
        SizedBox(
          width: double.infinity,
          height: AppSpacing.buttonHeight,
          child: OutlinedButton(
            onPressed: isSubmitting ? null : () => onActionSelected('reject'),
            child: const Text('다른 상품 보기'),
          ),
        ),
      ],
    );
  }
}

class _QuickReplyChip extends StatelessWidget {
  const _QuickReplyChip({required this.label, this.onTap});

  final String label;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    final isEnabled = onTap != null;
    return Material(
      color: Colors.transparent,
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(AppRadii.pill),
        child: Container(
          padding: const EdgeInsets.symmetric(
            horizontal: AppSpacing.sm,
            vertical: AppSpacing.xs,
          ),
          decoration: BoxDecoration(
            color: isEnabled ? AppColors.surface : AppColors.surfaceMuted,
            borderRadius: BorderRadius.circular(AppRadii.pill),
            border: Border.all(color: AppColors.border),
          ),
          child: Text(
            label,
            style: AppTextStyles.caption.copyWith(
              color: isEnabled ? AppColors.textPrimary : AppColors.textMuted,
              fontWeight: FontWeight.w700,
            ),
          ),
        ),
      ),
    );
  }
}

class _ProductRecommendationCard extends StatelessWidget {
  const _ProductRecommendationCard({
    required this.product,
    required this.service,
  });

  final ShoppingProductViewData product;
  final ShoppingFlowService service;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(AppSpacing.cardPadding),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(AppRadii.xl),
        border: Border.all(color: AppColors.border),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              _PlatformPill(label: service.platformLabel(product.platform)),
              const Spacer(),
              if (product.rank != null)
                Text(
                  '추천 ${product.rank}순위',
                  style: AppTextStyles.caption.copyWith(
                    color: AppColors.primaryPinkDark,
                    fontWeight: FontWeight.w700,
                  ),
                ),
            ],
          ),
          const SizedBox(height: AppSpacing.md),
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              ClipRRect(
                borderRadius: BorderRadius.circular(AppRadii.lg),
                child: SizedBox(
                  width: 108,
                  height: 108,
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
                        fontSize: 20,
                        color: AppColors.textStrong,
                        fontWeight: FontWeight.w800,
                        height: 1.4,
                      ),
                    ),
                    if (product.detailLine.isNotEmpty) ...[
                      const SizedBox(height: AppSpacing.sm),
                      Text(product.detailLine, style: AppTextStyles.body2),
                    ],
                    const SizedBox(height: AppSpacing.md),
                    Text(
                      product.displayPrice,
                      style: AppTextStyles.title2.copyWith(
                        color: AppColors.textStrong,
                        fontWeight: FontWeight.w800,
                      ),
                    ),
                  ],
                ),
              ),
            ],
          ),
          if (product.reason != null && product.reason!.trim().isNotEmpty) ...[
            const SizedBox(height: AppSpacing.lg),
            Container(
              width: double.infinity,
              padding: const EdgeInsets.all(AppSpacing.md),
              decoration: BoxDecoration(
                color: AppColors.surface,
                borderRadius: BorderRadius.circular(AppRadii.lg),
              ),
              child: Text(
                product.reason!.trim(),
                style: AppTextStyles.body2.copyWith(
                  color: AppColors.textPrimary,
                  fontWeight: FontWeight.w700,
                ),
              ),
            ),
          ],
        ],
      ),
    );
  }
}

class _SecondaryRecommendationTile extends StatelessWidget {
  const _SecondaryRecommendationTile({
    required this.product,
    required this.service,
  });

  final ShoppingProductViewData product;
  final ShoppingFlowService service;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(AppSpacing.md),
      decoration: BoxDecoration(
        color: AppColors.surface,
        borderRadius: BorderRadius.circular(AppRadii.lg),
        border: Border.all(color: AppColors.border),
      ),
      child: Row(
        children: [
          ClipRRect(
            borderRadius: BorderRadius.circular(AppRadii.md),
            child: SizedBox(
              width: 58,
              height: 58,
              child: _ProductArtwork(
                product: product,
                service: service,
                fit: BoxFit.cover,
              ),
            ),
          ),
          const SizedBox(width: AppSpacing.md),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  product.title,
                  style: AppTextStyles.body2.copyWith(
                    color: AppColors.textPrimary,
                    fontWeight: FontWeight.w700,
                  ),
                ),
                const SizedBox(height: AppSpacing.xs),
                Text(
                  product.displayPrice,
                  style: AppTextStyles.caption.copyWith(
                    color: AppColors.textMuted,
                    fontWeight: FontWeight.w700,
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
  });

  final ShoppingCartItemViewData item;
  final ShoppingFlowService service;
  final bool compact;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: EdgeInsets.all(compact ? AppSpacing.sm : AppSpacing.md),
      decoration: BoxDecoration(
        color: AppColors.surface,
        borderRadius: BorderRadius.circular(AppRadii.lg),
        border: Border.all(color: AppColors.border),
      ),
      child: Row(
        children: [
          ClipRRect(
            borderRadius: BorderRadius.circular(AppRadii.md),
            child: SizedBox(
              width: compact ? 48 : 56,
              height: compact ? 48 : 56,
              child: _ProductArtwork(
                product: item.product,
                service: service,
                fit: BoxFit.cover,
              ),
            ),
          ),
          const SizedBox(width: AppSpacing.md),
          Expanded(
            child: Column(
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
                if (item.product.optionText?.trim().isNotEmpty == true) ...[
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
            crossAxisAlignment: CrossAxisAlignment.end,
            children: [
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

class _PlatformPill extends StatelessWidget {
  const _PlatformPill({
    required this.label,
    this.backgroundColor = AppColors.secondaryPink,
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

  @override
  Widget build(BuildContext context) {
    final trimmedLabel = label.trim();
    final bannerAssetPath = _bannerAssetsByLabel[trimmedLabel];
    if (bannerAssetPath != null) {
      return SizedBox(
        height: 24,
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
        crossAxisCount: 3,
        mainAxisSpacing: AppSpacing.sm,
        crossAxisSpacing: AppSpacing.sm,
        childAspectRatio: 1.45,
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
              border: Border.all(color: AppColors.border),
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
