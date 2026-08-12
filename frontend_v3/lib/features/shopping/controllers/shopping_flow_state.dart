import '../../../data/models/agent_model.dart';
import '../models/shopping_flow_models.dart';

/// [ShoppingFlowController]가 소유하는 화면 상태.
///
/// 예전에는 이 필드들이 전부 `_ShoppingFlowScreenState`의 뮤터블 인스턴스
/// 필드였다. 컨트롤러 분리 이후에도 위젯 쪽 코드는 그대로 두기 위해,
/// 필드 이름/타입은 예전 `_response`, `_viewStage` 같은 private 필드와 최대한
/// 1:1로 맞춰뒀다 — 위젯은 이 값들을 forwarding getter로만 노출한다.
class ShoppingFlowState {
  const ShoppingFlowState({
    this.isInitializing = true,
    this.isSubmitting = false,
    this.isRefreshingConversation = false,
    this.isRefreshingCart = false,
    this.isUpdatingCartQuantity = false,
    this.isSendingAutomationResult = false,
    this.isRecording = false,
    this.isSpeaking = false,
    this.userId,
    this.resolvedUserName,
    this.response,
    this.fallbackAddress,
    this.viewStage = ShoppingFlowViewStage.askProduct,
    this.inlineError,
    this.pinInput = '',
    this.cartItemsOverride,
  });

  final bool isInitializing;
  final bool isSubmitting;
  final bool isRefreshingConversation;
  final bool isRefreshingCart;
  final bool isUpdatingCartQuantity;
  final bool isSendingAutomationResult;
  final bool isRecording;
  final bool isSpeaking;
  final int? userId;
  final String? resolvedUserName;
  final AgentResponse? response;
  final ShoppingAddressViewData? fallbackAddress;
  final ShoppingFlowViewStage viewStage;
  final String? inlineError;
  final String pinInput;
  final List<ShoppingCartItemViewData>? cartItemsOverride;

  static const Object _sentinel = Object();

  ShoppingFlowState copyWith({
    bool? isInitializing,
    bool? isSubmitting,
    bool? isRefreshingConversation,
    bool? isRefreshingCart,
    bool? isUpdatingCartQuantity,
    bool? isSendingAutomationResult,
    bool? isRecording,
    bool? isSpeaking,
    Object? userId = _sentinel,
    Object? resolvedUserName = _sentinel,
    Object? response = _sentinel,
    Object? fallbackAddress = _sentinel,
    ShoppingFlowViewStage? viewStage,
    Object? inlineError = _sentinel,
    String? pinInput,
    Object? cartItemsOverride = _sentinel,
  }) {
    return ShoppingFlowState(
      isInitializing: isInitializing ?? this.isInitializing,
      isSubmitting: isSubmitting ?? this.isSubmitting,
      isRefreshingConversation:
          isRefreshingConversation ?? this.isRefreshingConversation,
      isRefreshingCart: isRefreshingCart ?? this.isRefreshingCart,
      isUpdatingCartQuantity:
          isUpdatingCartQuantity ?? this.isUpdatingCartQuantity,
      isSendingAutomationResult:
          isSendingAutomationResult ?? this.isSendingAutomationResult,
      isRecording: isRecording ?? this.isRecording,
      isSpeaking: isSpeaking ?? this.isSpeaking,
      userId: identical(userId, _sentinel) ? this.userId : userId as int?,
      resolvedUserName: identical(resolvedUserName, _sentinel)
          ? this.resolvedUserName
          : resolvedUserName as String?,
      response: identical(response, _sentinel)
          ? this.response
          : response as AgentResponse?,
      fallbackAddress: identical(fallbackAddress, _sentinel)
          ? this.fallbackAddress
          : fallbackAddress as ShoppingAddressViewData?,
      viewStage: viewStage ?? this.viewStage,
      inlineError: identical(inlineError, _sentinel)
          ? this.inlineError
          : inlineError as String?,
      pinInput: pinInput ?? this.pinInput,
      cartItemsOverride: identical(cartItemsOverride, _sentinel)
          ? this.cartItemsOverride
          : cartItemsOverride as List<ShoppingCartItemViewData>?,
    );
  }
}
