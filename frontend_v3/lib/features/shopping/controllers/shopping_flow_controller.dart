import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter/widgets.dart' show WidgetsBinding;
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/services/voice_service.dart';
import '../../../data/models/agent_model.dart';
import '../models/shopping_flow_models.dart';
import '../services/shopping_flow_service.dart';
import 'shopping_flow_state.dart';

/// [ShoppingFlowScreen] 하나의 인스턴스에 어떤 서비스/초기 사용자명을 쓸지
/// 지정하는 provider 키. 위젯은 이 값을 `late final`로 한 번만 만들어서
/// 넘겨야 한다 — 매 build마다 새 인스턴스를 만들면 컨트롤러가 계속
/// 재생성된다(그래서 service는 값이 아니라 identity로 비교한다).
@immutable
class ShoppingFlowArgs {
  const ShoppingFlowArgs({this.userName, this.service});

  final String? userName;
  final ShoppingFlowService? service;

  @override
  bool operator ==(Object other) {
    return other is ShoppingFlowArgs &&
        other.userName == userName &&
        identical(other.service, service);
  }

  @override
  int get hashCode => Object.hash(userName, identityHashCode(service));
}

/// 화면이 사라지면(마지막 구독자가 없어지면) 자동으로 dispose되는 화면 스코프
/// 컨트롤러. `.family`라 [ShoppingFlowScreen] 인스턴스마다(즉 args별로)
/// 독립된 컨트롤러를 갖는다.
final shoppingFlowControllerProvider = StateNotifierProvider.autoDispose
    .family<ShoppingFlowController, ShoppingFlowState, ShoppingFlowArgs>(
      (ref, args) => ShoppingFlowController(
        service: args.service ?? ShoppingFlowService(),
        userName: args.userName,
      ),
    );

/// `ShoppingFlowScreen`(구 `_ShoppingFlowScreenState`)에 있던 상태/비즈니스
/// 로직을 옮겨놓은 컨트롤러.
///
/// 여기 없는 것: BuildContext가 필요한 동작(웹뷰 화면 push, 종료 확인
/// 다이얼로그). 그건 여전히 위젯(State) 쪽 책임이다. 그 외 응답 반영, 폴링,
/// automation task/result 처리, 음성 녹음·재생, 카트 수량 변경, PIN 입력
/// 같은 로직은 전부 여기 있다.
class ShoppingFlowController extends StateNotifier<ShoppingFlowState> {
  ShoppingFlowController({
    required ShoppingFlowService service,
    String? userName,
  }) : _service = service,
       super(ShoppingFlowState(resolvedUserName: userName?.trim())) {
    unawaited(_bootstrapVoice());
    unawaited(_bootstrap());
  }

  final ShoppingFlowService _service;
  final VoiceService _voiceService = VoiceService.instance;

  Timer? _pollTimer;
  Timer? _automationResultPollTimer;
  String? _lastAutomationTaskId;
  String? _automationResultPollingTaskId;
  String? _lastSpokenPromptKey;
  final Set<String> _startedAutomationTaskIds = <String>{};

  ShoppingFlowService get service => _service;

  @override
  void dispose() {
    _pollTimer?.cancel();
    _automationResultPollTimer?.cancel();
    unawaited(_voiceService.stopSpeaking());
    if (state.isRecording) {
      unawaited(_voiceService.cancelRecording());
    }
    super.dispose();
  }

  Future<void> _bootstrapVoice() async {
    try {
      await _voiceService.init();
    } catch (_) {
      // Voice init is best-effort; STT/TTS 버튼을 눌렀을 때 다시 시도된다.
    }
  }

  Future<void> _bootstrap() async {
    state = state.copyWith(isInitializing: true, inlineError: null);

    try {
      final userId = await _service.resolveUserId();

      // userName이 이미 있으면(홈 화면에서 넘겨준 경우) 이름 조회 네트워크
      // 호출 자체를 건너뛴다. userName/주소 조회는 서로 의존하지 않는
      // 독립적인 요청이라 순서대로 기다리지 않고 병렬로 실행해서, 초기화
      // 화면이 필요 이상으로 오래 보이는 걸 줄인다.
      final hasResolvedUserName = state.resolvedUserName?.isNotEmpty ?? false;
      final userNameFuture = hasResolvedUserName
          ? Future.value(state.resolvedUserName)
          : _service.resolveUserName(userId: userId);
      final addressFuture = _service.fetchDefaultAddress(
        userId: userId,
        fallbackRecipientName: hasResolvedUserName
            ? state.resolvedUserName
            : null,
      );

      final resolvedUserName = await userNameFuture;
      var fallbackAddress = await addressFuture;
      // 이름 조회가 주소 조회보다 늦게 끝났고, 주소 응답에는 아직 수신인
      // 이름이 채워지지 않았을 수 있으니 그 경우에만 보정한다.
      if (!hasResolvedUserName &&
          fallbackAddress != null &&
          fallbackAddress.recipientName == null &&
          resolvedUserName != null) {
        fallbackAddress = fallbackAddress.copyWith(
          recipientName: resolvedUserName,
        );
      }

      if (!mounted) {
        return;
      }

      state = state.copyWith(
        userId: userId,
        resolvedUserName: resolvedUserName,
        fallbackAddress: fallbackAddress,
        isInitializing: false,
      );
      _schedulePromptSpeechAfterFrame(force: true);
    } catch (error) {
      if (!mounted) {
        return;
      }
      state = state.copyWith(
        isInitializing: false,
        inlineError: '쇼핑 준비 중 문제가 생겼어요. 잠시 후 다시 시도해주세요.',
      );
    }
  }

  Future<void> refreshFallbackAddress() async {
    final userId = state.userId;
    if (userId == null) {
      return;
    }

    final fallbackAddress = await _service.fetchDefaultAddress(
      userId: userId,
      fallbackRecipientName: state.resolvedUserName,
    );
    if (!mounted || fallbackAddress == null) {
      return;
    }

    state = state.copyWith(fallbackAddress: fallbackAddress);
  }

  /// 위젯의 `_effectiveCartItems` getter가 그대로 쓰는 계산값.
  List<ShoppingCartItemViewData> get effectiveCartItems {
    final override = state.cartItemsOverride;
    if (override != null) {
      return override;
    }

    final response = state.response;
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
    final userId = state.userId;
    if (userId == null || state.isRefreshingCart) {
      return;
    }

    state = state.copyWith(isRefreshingCart: true);
    try {
      final items = await _service.fetchUserCartItems(
        userId: userId,
        conversationId: conversationId ?? state.response?.conversationId,
      );
      if (!mounted) {
        return;
      }
      state = state.copyWith(cartItemsOverride: items);
    } catch (_) {
      // Live cart sync is best-effort.
    } finally {
      if (mounted) {
        state = state.copyWith(isRefreshingCart: false);
      }
    }
  }

  Future<void> changeCartItemQuantity(
    ShoppingCartItemViewData item,
    int nextQuantity,
  ) async {
    final userId = state.userId;
    final conversationId = state.response?.conversationId;
    if (userId == null ||
        conversationId == null ||
        state.isSubmitting ||
        state.isUpdatingCartQuantity) {
      return;
    }

    state = state.copyWith(isUpdatingCartQuantity: true, inlineError: null);

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
      state = state.copyWith(cartItemsOverride: items);
    } catch (_) {
      if (!mounted) {
        return;
      }
      state = state.copyWith(inlineError: '장바구니 수량을 바꾸지 못했어요. 다시 시도해주세요.');
    } finally {
      if (mounted) {
        state = state.copyWith(isUpdatingCartQuantity: false);
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
    if (state.viewStage != ShoppingFlowViewStage.productSelection) {
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
    final userId = state.userId;
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

  /// 새 [AgentResponse]를 상태에 반영한다. 웹뷰 로직에서도(레거시 경로) 호출하므로
  /// public이다.
  void applyResponse(AgentResponse response) {
    final nextStage = _service.inferViewStage(response);
    final previousConversationId = state.response?.conversationId;
    final responseSentences = _sentencesForResponse(response);
    state = state.copyWith(
      response: response,
      visibleAssistantMessage: responseSentences.isNotEmpty
          ? responseSentences.first
          : response.assistantMessage.trim(),
      viewStage: nextStage,
      inlineError: null,
      cartItemsOverride: previousConversationId != response.conversationId
          ? null
          : state.cartItemsOverride,
      pinInput: nextStage == ShoppingFlowViewStage.paymentPassword
          ? state.pinInput
          : '',
    );
    _syncPolling();
    _handlePendingAutomationTask(response);
    _schedulePromptSpeechAfterFrame();
    if (_shouldShowLiveCart(nextStage)) {
      unawaited(_refreshLiveCartItems(conversationId: response.conversationId));
    }

    if (state.fallbackAddress == null &&
        (nextStage == ShoppingFlowViewStage.addressConfirmation ||
            nextStage == ShoppingFlowViewStage.paymentConfirmation ||
            nextStage == ShoppingFlowViewStage.paymentPassword ||
            nextStage == ShoppingFlowViewStage.paymentProcessing)) {
      unawaited(refreshFallbackAddress());
    }
  }

  void _handlePendingAutomationTask(AgentResponse response) {
    final task = response.automationTask;
    if (task == null || task.taskId.trim().isEmpty) {
      return;
    }
    if (_startedAutomationTaskIds.contains(task.taskId) ||
        _lastAutomationTaskId == task.taskId) {
      return;
    }

    debugPrint(
      'automationTask taskId=${task.taskId} 수신 '
      'taskType=${task.taskType} platform=${task.platform}',
    );
    _lastAutomationTaskId = task.taskId;
    _startedAutomationTaskIds.add(task.taskId);
    unawaited(
      _service
          .startAutomationTask(task)
          .then((_) {
            _startAutomationResultPolling(
              conversationId: response.conversationId,
              taskId: task.taskId,
            );
          })
          .catchError((Object error) {
            if (!mounted) {
              return;
            }
            state = state.copyWith(
              inlineError: '쇼핑 앱 자동화를 시작하지 못했어요. 잠시 후 다시 시도해주세요.',
            );
          }),
    );
  }

  void _startAutomationResultPolling({
    required int conversationId,
    required String taskId,
  }) {
    if (_automationResultPollingTaskId == taskId &&
        _automationResultPollTimer?.isActive == true) {
      return;
    }

    _automationResultPollingTaskId = taskId;
    _automationResultPollTimer?.cancel();
    _automationResultPollTimer = Timer.periodic(const Duration(seconds: 2), (
      _,
    ) {
      unawaited(_consumeAutomationResult(conversationId: conversationId));
    });
  }

  Future<void> _consumeAutomationResult({required int conversationId}) async {
    if (state.isSendingAutomationResult) {
      return;
    }

    state = state.copyWith(isSendingAutomationResult: true);
    try {
      final updatedResponse = await _service.consumeAndSendAutomationResult(
        conversationId: conversationId,
      );
      if (!mounted || updatedResponse == null) {
        return;
      }
      _automationResultPollTimer?.cancel();
      _automationResultPollingTaskId = null;
      applyResponse(updatedResponse);
    } catch (error, stackTrace) {
      debugPrint(
        '[ShoppingFlowController] failed to send automation result: '
        '$error\n$stackTrace',
      );
    } finally {
      if (mounted) {
        state = state.copyWith(isSendingAutomationResult: false);
      }
    }
  }

  void _syncPolling() {
    _pollTimer?.cancel();
    final response = state.response;
    if (response == null || !_service.requiresPolling(response)) {
      return;
    }

    _pollTimer = Timer.periodic(const Duration(seconds: 2), (_) {
      unawaited(_refreshConversation());
    });
  }

  Future<void> _refreshConversation() async {
    final response = state.response;
    if (state.isRefreshingConversation || response == null) {
      return;
    }

    state = state.copyWith(isRefreshingConversation: true);
    try {
      final refreshed = await _service.getConversation(response.conversationId);
      if (!mounted) {
        return;
      }
      applyResponse(refreshed);
    } catch (_) {
      // Ignore silent polling failures and keep the current UI.
    } finally {
      if (mounted) {
        state = state.copyWith(isRefreshingConversation: false);
      }
    }
  }

  bool _shouldStartFreshConversation({required String nextMessage}) {
    final response = state.response;
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
        response.automationTask != null ||
        response.automationResult != null ||
        response.uiCommand != null ||
        response.asyncStatus != null;

    if (hasFlowProgress) {
      return false;
    }

    final isRetryPrompt =
        assistantMessage.contains('다시 한번 말씀해 주세요') ||
        assistantMessage.contains('다시 말씀');
    final isEarlyStage =
        state.viewStage == ShoppingFlowViewStage.askProduct ||
        state.viewStage == ShoppingFlowViewStage.error;
    final isExampleMessage = _service
        .quickRepliesFor(ShoppingFlowViewStage.askProduct)
        .contains(nextMessage);

    return isEarlyStage &&
        (stage == 'idle' || isRetryPrompt || isExampleMessage);
  }

  Future<void> submitMessage(
    String message, {
    bool redactMessageForLogs = false,
  }) async {
    final trimmed = message.trim();
    if (trimmed.isEmpty || state.isSubmitting) {
      return;
    }

    final userId = state.userId;
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
        : state.response?.conversationId;

    state = state.copyWith(
      isSubmitting: true,
      inlineError: null,
      viewStage: conversationId == null
          ? ShoppingFlowViewStage.searchingProduct
          : state.viewStage,
    );

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
      applyResponse(response);
    } catch (error) {
      if (!mounted) {
        return;
      }
      state = state.copyWith(inlineError: '메시지를 보내지 못했어요. 다시 한 번 시도해주세요.');
    } finally {
      if (mounted) {
        state = state.copyWith(isSubmitting: false);
      }
    }
  }

  Future<void> confirmAction(String action) async {
    final response = state.response;
    if (response == null || state.isSubmitting) {
      return;
    }

    state = state.copyWith(isSubmitting: true, inlineError: null);

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
      applyResponse(nextResponse);
    } catch (_) {
      if (action == 'reject') {
        await submitMessage('다른 상품 보여줘');
      } else if (mounted) {
        state = state.copyWith(inlineError: '선택을 처리하지 못했어요. 다시 시도해주세요.');
      }
    } finally {
      if (mounted) {
        state = state.copyWith(isSubmitting: false);
      }
    }
  }

  /// 대화 종료 확인 후 위젯이 호출한다 — 음성 정리 + 서버 conversation 취소까지만
  /// 여기서 하고, 실제 화면 이동(Navigator)은 위젯이 한다.
  Future<void> prepareForExit() async {
    await _voiceService.stopSpeaking();
    if (state.isRecording) {
      await _voiceService.cancelRecording();
    }
    final conversationId = state.response?.conversationId;
    if (conversationId != null) {
      try {
        await _service.cancelConversation(conversationId);
      } catch (_) {}
    }
  }

  void appendPinDigit(String digit) {
    if (state.pinInput.length >= 6) {
      return;
    }
    state = state.copyWith(pinInput: '${state.pinInput}$digit');
  }

  void removePinDigit() {
    if (state.pinInput.isEmpty) {
      return;
    }
    state = state.copyWith(
      pinInput: state.pinInput.substring(0, state.pinInput.length - 1),
    );
  }

  Future<void> submitPin() async {
    if (state.pinInput.isEmpty) {
      return;
    }
    await submitMessage(state.pinInput, redactMessageForLogs: true);
  }

  /// 위젯의 `_spokenPromptText`와 동일한 분기 로직이지만, 컨트롤러 내부에서
  /// TTS를 실제로 재생할 문구를 고르는 데만 쓴다(대화창 텍스트 렌더링은
  /// 위젯이 자기 getter로 따로 한다).
  String? get _promptToSpeak {
    final assistantText = state.response?.assistantMessage.trim();
    if (assistantText != null && assistantText.isNotEmpty) {
      return assistantText;
    }

    switch (state.viewStage) {
      case ShoppingFlowViewStage.askProduct:
      case ShoppingFlowViewStage.searchingProduct:
        final name = state.resolvedUserName;
        if (name != null && name.trim().isNotEmpty) {
          return '$name님, 뭐가 필요하세요?';
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

  List<String> _promptSentencesToSpeak(String prompt) {
    final response = state.response;
    if (response != null && response.assistantMessage.trim() == prompt) {
      return _sentencesForResponse(response);
    }
    return _fallbackSplitSentences(prompt);
  }

  Future<void> _speakPromptIfNeeded({bool force = false}) async {
    final prompt = _promptToSpeak?.trim();
    if (prompt == null || prompt.isEmpty || state.isRecording) {
      return;
    }
    final promptSentences = _promptSentencesToSpeak(prompt);

    final promptKey =
        '${state.response?.conversationId ?? 0}:${state.viewStage.name}:$prompt';
    if (!force && _lastSpokenPromptKey == promptKey) {
      return;
    }
    _lastSpokenPromptKey = promptKey;

    if (mounted) {
      state = state.copyWith(isSpeaking: true);
    }

    try {
      for (final sentence in promptSentences) {
        if (!mounted) {
          return;
        }
        final normalizedSentence = sentence.trim();
        if (normalizedSentence.isEmpty) {
          continue;
        }
        if (state.response?.assistantMessage.trim() == prompt) {
          state = state.copyWith(visibleAssistantMessage: normalizedSentence);
        }
        await _voiceService.speak(normalizedSentence);
      }
    } catch (_) {
      // Voice playback is best-effort.
    } finally {
      if (mounted) {
        state = state.copyWith(isSpeaking: false);
      }
    }
  }

  void _schedulePromptSpeechAfterFrame({bool force = false}) {
    WidgetsBinding.instance.addPostFrameCallback((_) async {
      if (!mounted) {
        return;
      }
      await _speakPromptIfNeeded(force: force);
    });
  }

  Future<void> toggleVoiceInput() async {
    debugPrint(
      '[ShoppingFlowController] voice toggle requested '
      'isRecording=${state.isRecording} '
      'isInitializing=${state.isInitializing} '
      'isSubmitting=${state.isSubmitting} '
      'isUpdatingCartQuantity=${state.isUpdatingCartQuantity} '
      'isSpeaking=${state.isSpeaking} '
      'viewStage=${state.viewStage.name}',
    );
    if (state.isRecording) {
      await stopRecordingAndSubmit();
      return;
    }

    final isAwaitingUserInput =
        !state.isInitializing &&
        !state.isSubmitting &&
        !state.isUpdatingCartQuantity &&
        !state.isSpeaking;
    if (!isAwaitingUserInput) {
      debugPrint(
        '[ShoppingFlowController] voice toggle ignored: not awaiting user input',
      );
      return;
    }

    await _voiceService.stopSpeaking();
    if (mounted) {
      state = state.copyWith(
        isSpeaking: false,
        inlineError: null,
        isRecording: true,
      );
    }

    try {
      await _voiceService.startRecording();
      debugPrint('[ShoppingFlowController] voice recording started');
    } catch (error, stackTrace) {
      debugPrint(
        '[ShoppingFlowController] voice recording start failed error=$error',
      );
      debugPrintStack(
        stackTrace: stackTrace,
        label: '[ShoppingFlowController] startRecording stack',
      );
      if (!mounted) {
        return;
      }
      state = state.copyWith(
        isRecording: false,
        inlineError: '마이크를 시작하지 못했어요. 잠시 후 다시 시도해주세요.',
      );
    }
  }

  Future<void> stopRecordingAndSubmit() async {
    debugPrint(
      '[ShoppingFlowController] stopRecordingAndSubmit requested '
      'isRecording=${state.isRecording}',
    );
    if (!state.isRecording) {
      debugPrint(
        '[ShoppingFlowController] stopRecordingAndSubmit ignored: not recording',
      );
      return;
    }

    state = state.copyWith(isRecording: false, inlineError: null);

    try {
      final transcript = await _voiceService.stopRecordingAndTranscribe();
      final trimmed = transcript.trim();
      debugPrint(
        '[ShoppingFlowController] STT transcript received '
        'rawLength=${transcript.length} trimmedLength=${trimmed.length} '
        'transcript="$trimmed"',
      );
      if (!mounted) {
        return;
      }
      if (trimmed.isEmpty) {
        debugPrint(
          '[ShoppingFlowController] STT transcript empty; showing retry message',
        );
        state = state.copyWith(inlineError: '잘 듣지 못했어요. 한 번 더 말씀해주세요.');
        return;
      }

      debugPrint('[ShoppingFlowController] submitting STT transcript to agent');
      await submitMessage(trimmed);
    } catch (error, stackTrace) {
      debugPrint(
        '[ShoppingFlowController] stopRecordingAndSubmit failed error=$error',
      );
      debugPrintStack(
        stackTrace: stackTrace,
        label: '[ShoppingFlowController] stopRecordingAndSubmit stack',
      );
      if (!mounted) {
        return;
      }
      state = state.copyWith(inlineError: '음성 인식 중 문제가 생겼어요. 한 번 더 말씀해주세요.');
    }
  }
}
