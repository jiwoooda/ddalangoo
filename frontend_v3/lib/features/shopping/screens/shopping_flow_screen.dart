import 'dart:async';

import 'package:flutter/material.dart';

import '../../../app/routes.dart';
import '../../../app/theme/app_colors.dart';
import '../../../app/theme/app_radii.dart';
import '../../../app/theme/app_spacing.dart';
import '../../../app/theme/app_surface_styles.dart';
import '../../../app/theme/app_text_styles.dart';
import '../../../core/services/voice_service.dart';
import '../../../data/models/agent_model.dart';
import '../../../shared/layout/layout_presets.dart';
import '../../../shared/layout/screen_frame.dart';
import '../../../shared/widgets/bottom_status_banner.dart';
import '../../../shared/widgets/dialogue_bubble.dart';
import '../../../shared/widgets/primary_button.dart';
import '../../../shared/widgets/shopping_progress_stepper.dart';
import '../../../shared/widgets/voice_input_button.dart';
import '../models/shopping_flow_models.dart';
import 'shopping_webview_screen.dart';
import '../services/shopping_flow_service.dart';

const int _pinPadCrossAxisCount = 3;
const int _pinPadRowCount = 4;
const double _pinPadChildAspectRatio = 1.45;
const double _dialogueSectionHeight = 148.0;
const double _overlayControlBarHeight = 132.0;

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
  bool _isRefreshingCart = false;
  bool _isWebviewOpen = false;
  bool _isRecording = false;
  bool _isSpeaking = false;
  bool _isUpdatingCartQuantity = false;
  int? _userId;
  String? _resolvedUserName;
  AgentResponse? _response;
  ShoppingAddressViewData? _fallbackAddress;
  ShoppingFlowViewStage _viewStage = ShoppingFlowViewStage.askProduct;
  String? _inlineError;
  String _pinInput = '';
  String? _lastWebviewCommandKey;
  String? _lastSpokenPromptKey;
  List<ShoppingCartItemViewData>? _cartItemsOverride;
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
      _schedulePromptSpeechAfterFrame(force: true);
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

  List<ShoppingCartItemViewData> get _effectiveCartItems {
    final override = _cartItemsOverride;
    if (override != null) {
      return override;
    }

    final response = _response;
    if (response == null) {
      return const <ShoppingCartItemViewData>[];
    }
    return _service.extractCartItems(response);
  }

  bool _shouldShowLiveCart(ShoppingFlowViewStage stage) {
    switch (stage) {
      case ShoppingFlowViewStage.cartCompleted:
      case ShoppingFlowViewStage.addressConfirmation:
      case ShoppingFlowViewStage.paymentConfirmation:
      case ShoppingFlowViewStage.paymentPassword:
      case ShoppingFlowViewStage.paymentProcessing:
      case ShoppingFlowViewStage.completed:
        return true;
      case ShoppingFlowViewStage.askProduct:
      case ShoppingFlowViewStage.searchingProduct:
      case ShoppingFlowViewStage.productSelection:
      case ShoppingFlowViewStage.quantitySelection:
      case ShoppingFlowViewStage.cartProcessing:
      case ShoppingFlowViewStage.error:
        return false;
    }
  }

  Future<void> _refreshLiveCartItems({int? conversationId}) async {
    final userId = _userId;
    if (userId == null || _isRefreshingCart) {
      return;
    }

    _isRefreshingCart = true;
    try {
      final items = await _service.fetchUserCartItems(
        userId: userId,
        conversationId: conversationId ?? _response?.conversationId,
      );
      if (!mounted) {
        return;
      }
      setState(() {
        _cartItemsOverride = items;
      });
    } catch (_) {
      // Live cart sync is best-effort.
    } finally {
      _isRefreshingCart = false;
    }
  }

  Future<void> _changeCartItemQuantity(
    ShoppingCartItemViewData item,
    int nextQuantity,
  ) async {
    final userId = _userId;
    final conversationId = _response?.conversationId;
    if (userId == null ||
        conversationId == null ||
        _isSubmitting ||
        _isUpdatingCartQuantity) {
      return;
    }

    setState(() {
      _isUpdatingCartQuantity = true;
      _inlineError = null;
    });

    try {
      final items = await _service.updateCartItemQuantity(
        userId: userId,
        conversationId: conversationId,
        item: item,
        quantity: nextQuantity,
      );
      if (!mounted) {
        return;
      }
      setState(() {
        _cartItemsOverride = items;
      });
    } catch (_) {
      if (!mounted) {
        return;
      }
      setState(() {
        _inlineError = '장바구니 수량을 바꾸지 못했어요. 다시 시도해주세요.';
      });
    } finally {
      if (mounted) {
        setState(() {
          _isUpdatingCartQuantity = false;
        });
      }
    }
  }

  bool _containsExplicitQuantity(String message) {
    final normalized = message.replaceAll(' ', '');
    if (RegExp(r'\d+\s*(개|근|팩|박스|봉|송이|상자)?').hasMatch(normalized)) {
      return true;
    }

    const exactQuantityWords = <String>{
      '하나',
      '둘',
      '셋',
      '넷',
      '다섯',
      '한개',
      '두개',
      '세개',
      '네개',
      '다섯개',
    };
    if (exactQuantityWords.contains(normalized)) {
      return true;
    }

    final wordPatterns = <RegExp>[
      RegExp(r'(한|하나)\s*(개|근|팩|박스|봉|송이|상자)'),
      RegExp(r'(두|둘)\s*(개|근|팩|박스|봉|송이|상자)'),
      RegExp(r'(세|셋)\s*(개|근|팩|박스|봉|송이|상자)'),
      RegExp(r'(네|넷)\s*(개|근|팩|박스|봉|송이|상자)'),
      RegExp(r'다섯\s*(개|근|팩|박스|봉|송이|상자)'),
    ];
    return wordPatterns.any((pattern) => pattern.hasMatch(message));
  }

  bool _shouldAutoDefaultQuantityForMessage(String message) {
    if (_viewStage != ShoppingFlowViewStage.productSelection) {
      return false;
    }

    final normalized = message.trim().toLowerCase();
    if (normalized.isEmpty || _containsExplicitQuantity(normalized)) {
      return false;
    }

    return normalized.contains('담') ||
        normalized.contains('주문') ||
        normalized.contains('이걸로') ||
        normalized.contains('좋아') ||
        normalized.contains('괜찮') ||
        normalized == '응' ||
        normalized == '네';
  }

  Future<AgentResponse> _resolveAutoDefaultQuantityResponse(
    AgentResponse response, {
    required bool shouldAutoDefaultQuantity,
  }) async {
    final userId = _userId;
    if (!shouldAutoDefaultQuantity ||
        userId == null ||
        _service.inferViewStage(response) !=
            ShoppingFlowViewStage.quantitySelection) {
      return response;
    }

    return _service.submitMessage(
      userId: userId,
      message: '1개',
      conversationId: response.conversationId,
    );
  }

  void _applyResponse(AgentResponse response) {
    final nextStage = _service.inferViewStage(response);
    final previousConversationId = _response?.conversationId;
    setState(() {
      if (previousConversationId != response.conversationId) {
        _cartItemsOverride = null;
      }
      _response = response;
      _viewStage = nextStage;
      _inlineError = null;
      if (nextStage != ShoppingFlowViewStage.paymentPassword) {
        _pinInput = '';
      }
    });
    _syncPolling();
    _schedulePromptSpeechAfterFrame(handlePendingWebviewAfter: true);
    if (_shouldShowLiveCart(nextStage)) {
      unawaited(_refreshLiveCartItems(conversationId: response.conversationId));
    }

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
    final shouldAutoDefaultQuantity = _shouldAutoDefaultQuantityForMessage(
      trimmed,
    );
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
      var response = await _service.submitMessage(
        userId: userId,
        message: trimmed,
        conversationId: conversationId,
        redactMessageForLogs: redactMessageForLogs,
      );
      response = await _resolveAutoDefaultQuantityResponse(
        response,
        shouldAutoDefaultQuantity: shouldAutoDefaultQuantity,
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
      var nextResponse = await _service.confirmProductAction(
        response: response,
        action: action,
      );
      nextResponse = await _resolveAutoDefaultQuantityResponse(
        nextResponse,
        shouldAutoDefaultQuantity:
            action == 'add_to_cart' || action == 'order_now',
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
          actions: [
            TextButton(
              onPressed: () => Navigator.of(dialogContext).pop(false),
              child: Text(
                '계속하기',
                style: AppTextStyles.caption.copyWith(
                  color: AppColors.textSecondary,
                  fontWeight: FontWeight.w700,
                ),
              ),
            ),
            FilledButton(
              onPressed: () => Navigator.of(dialogContext).pop(true),
              style: FilledButton.styleFrom(
                backgroundColor: AppColors.primaryPink,
                foregroundColor: Colors.white,
              ),
              child: Text(
                '종료하기',
                style: AppTextStyles.caption.copyWith(
                  color: Colors.white,
                  fontWeight: FontWeight.w800,
                ),
              ),
            ),
          ],
        );
      },
    );

    if (shouldExit == true && mounted) {
      await _handleExit();
    }
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

  double get _overlayBottomInset {
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
      ShoppingFlowViewStage.error => _overlayControlBarHeight + AppSpacing.sm,
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

  void _schedulePromptSpeechAfterFrame({
    bool force = false,
    bool handlePendingWebviewAfter = false,
  }) {
    WidgetsBinding.instance.addPostFrameCallback((_) async {
      if (!mounted) {
        return;
      }
      await _speakPromptIfNeeded(force: force);
      if (!mounted || !handlePendingWebviewAfter) {
        return;
      }
      _handlePendingWebviewTask();
    });
  }

  Future<void> _toggleVoiceInput() async {
    if (_isRecording) {
      await _stopRecordingAndSubmit();
      return;
    }

    if (!_isAwaitingUserInput) {
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
              padding: EdgeInsets.only(bottom: _overlayBottomInset),
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
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Expanded(
          child: ShoppingProgressStepper(
            currentStep: currentStep,
            completedSteps: completedSteps,
            compact: true,
          ),
        ),
        const SizedBox(width: AppSpacing.xs),
        _ExitIconButton(onPressed: _confirmExit),
      ],
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
    return SizedBox(
      height: _dialogueSectionHeight,
      child: DialogueBubble(
        contentKey: ValueKey(
          '${_response?.conversationId ?? 0}-${_response?.stage}-${_assistantText ?? _viewStage.name}',
        ),
        animateTextChanges: true,
        borderColor: AppSurfaceStyles.emphasisOutlineColor,
        minHeight: _dialogueSectionHeight - 8,
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
    final overlayBackgroundColor = _voiceInputState == VoiceInputState.inactive
        ? const Color(0xFFF7F7FA)
        : AppColors.pastelPinkSoft;
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
          _OverlayControlBar(
            backgroundColor: overlayBackgroundColor,
            leadingReplyContent: leadingReplyContent,
            trailingReplyContent: trailingReplyContent,
            voiceButton: VoiceInputButton(
              state: _voiceInputState,
              onPressed: _toggleVoiceInput,
              diameter: 62,
              iconSize: 28,
              labelSpacing: 2,
            ),
          ),
        ],
      ),
    );
  }

  List<_OverlayReplyOption> _buildOverlayReplyOptions() {
    switch (_viewStage) {
      case ShoppingFlowViewStage.askProduct:
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
        return _EmptyStatePanel(
          key: const ValueKey('ask-product'),
          assetPath: 'assets/images/character/top/ddalangoo_standing_top.png',
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
                      onTap: _canTapReplyChip
                          ? () => _submitMessage(reply)
                          : null,
                    );
                  })
                  .toList(growable: false),
            ),
            const SizedBox(height: AppSpacing.lg),
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

class _ExitIconButton extends StatelessWidget {
  const _ExitIconButton({required this.onPressed});

  final VoidCallback onPressed;

  @override
  Widget build(BuildContext context) {
    return Semantics(
      button: true,
      label: '대화 종료',
      child: Material(
        color: Colors.transparent,
        child: InkWell(
          onTap: onPressed,
          borderRadius: BorderRadius.circular(AppRadii.pill),
          child: Container(
            width: 42,
            height: 42,
            decoration: BoxDecoration(
              color: Colors.white,
              borderRadius: BorderRadius.circular(AppRadii.pill),
              border: Border.all(
                color: AppSurfaceStyles.standardOutlineColor,
                width: AppSurfaceStyles.thinOutlineWidth,
              ),
            ),
            child: const Icon(
              Icons.pause_rounded,
              color: AppColors.textPrimary,
              size: 20,
            ),
          ),
        ),
      ),
    );
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
      decoration: AppSurfaceStyles.emphasizedPanel(
        radius: AppRadii.xl,
        boxShadow: AppSurfaceStyles.raisedShadow,
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

    return LayoutBuilder(
      builder: (context, constraints) {
        final canStretchCard =
            constraints.maxHeight.isFinite && constraints.maxHeight >= 420;

        if (canStretchCard) {
          return Column(
            children: [
              Expanded(
                child: _HeroProductPanel(
                  product: primaryProduct!,
                  service: service,
                ),
              ),
            ],
          );
        }

        return Scrollbar(
          thumbVisibility: true,
          radius: const Radius.circular(999),
          thickness: 4,
          child: SingleChildScrollView(
            primary: true,
            child: _HeroProductPanel(
              product: primaryProduct!,
              service: service,
            ),
          ),
        );
      },
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
      decoration: AppSurfaceStyles.emphasizedPanel(
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
      decoration: AppSurfaceStyles.emphasizedPanel(
        radius: AppRadii.xl,
        color: AppColors.surfaceMuted,
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
        final freeSpace = (availableHeight - panelHeight - keypadHeight).clamp(
          0.0,
          double.infinity,
        );
        final sectionGap = freeSpace / 3;

        return SizedBox(
          width: double.infinity,
          height: availableHeight,
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
      decoration: AppSurfaceStyles.emphasizedPanel(
        radius: AppRadii.xl,
        boxShadow: AppSurfaceStyles.raisedShadow,
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

class _OverlayControlBar extends StatelessWidget {
  const _OverlayControlBar({
    required this.voiceButton,
    required this.backgroundColor,
    this.leadingReplyContent,
    this.trailingReplyContent,
  });

  final Widget voiceButton;
  final Color backgroundColor;
  final Widget? leadingReplyContent;
  final Widget? trailingReplyContent;

  @override
  Widget build(BuildContext context) {
    final hasReplies =
        leadingReplyContent != null || trailingReplyContent != null;

    return SizedBox(
      width: double.infinity,
      height: _overlayControlBarHeight,
      child: AnimatedContainer(
        duration: const Duration(milliseconds: 220),
        padding: const EdgeInsets.symmetric(horizontal: AppSpacing.md),
        decoration: AppSurfaceStyles.elevatedCard(
          radius: AppRadii.xl,
          color: backgroundColor,
        ),
        child: hasReplies
            ? Row(
                children: [
                  Expanded(
                    child: Align(
                      alignment: Alignment.centerRight,
                      child: leadingReplyContent ?? const SizedBox.shrink(),
                    ),
                  ),
                  const SizedBox(width: AppSpacing.xs),
                  Center(child: voiceButton),
                  const SizedBox(width: AppSpacing.xs),
                  Expanded(
                    child: Align(
                      alignment: Alignment.centerLeft,
                      child: trailingReplyContent ?? const SizedBox.shrink(),
                    ),
                  ),
                ],
              )
            : Center(child: voiceButton),
      ),
    );
  }
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
    return Container(
      padding: EdgeInsets.all(compact ? AppSpacing.sm : AppSpacing.md),
      decoration: BoxDecoration(
        color: AppColors.surface,
        borderRadius: BorderRadius.circular(AppRadii.lg),
        border: Border.all(
          color: AppSurfaceStyles.emphasisOutlineColor,
          width: AppSurfaceStyles.emphasisOutlineWidth,
        ),
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
              if (!compact && (onDecrease != null || onIncrease != null))
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
