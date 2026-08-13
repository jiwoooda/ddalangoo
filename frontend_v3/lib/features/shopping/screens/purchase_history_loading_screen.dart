import 'dart:async';

import 'package:flutter/material.dart';

import '../../../app/routes.dart';
import '../../../app/theme/app_colors.dart';
import '../../../app/theme/app_radii.dart';
import '../../../app/theme/app_spacing.dart';
import '../../../app/theme/app_surface_styles.dart';
import '../../../app/theme/app_text_styles.dart';
import '../../../core/services/voice_service.dart';
import '../../../data/models/accessibility_purchase_history_model.dart';
import '../../../data/models/purchase_history_model.dart';
import '../../../shared/layout/app_layout.dart';
import '../../../shared/layout/app_responsive.dart';
import '../../../shared/layout/layout_presets.dart';
import '../../../shared/widgets/dialogue_bubble.dart';
import '../../../shared/widgets/primary_button.dart';
import 'analysis_intro_screen.dart';
import '../services/purchase_history_loading_service.dart';
import '../widgets/purchase_history_thumbnail_card.dart';

class PurchaseHistoryLoadingScreen extends StatefulWidget {
  const PurchaseHistoryLoadingScreen({
    super.key,
    this.userName,
    this.useMockFlow = false,
    this.onCompleted,
    this.nextRouteName = AppRoutes.home,
    this.postLoadDelay = const Duration(milliseconds: 1500),
  });

  final String? userName;
  final bool useMockFlow;
  final VoidCallback? onCompleted;
  final String nextRouteName;
  final Duration postLoadDelay;

  @override
  State<PurchaseHistoryLoadingScreen> createState() =>
      _PurchaseHistoryLoadingScreenState();
}

class _PurchaseHistoryLoadingScreenState
    extends State<PurchaseHistoryLoadingScreen>
    with SingleTickerProviderStateMixin {
  final PurchaseHistoryLoadingService _service =
      PurchaseHistoryLoadingService();
  final VoiceService _voiceService = VoiceService.instance;

  // platform_check_screen과 같은 오버레이 패널 등장 애니메이션. 배경(진행 중인
  // 구매 이력 카드들)은 항상 보이고, 하단 캐릭터+진행 상황 패널만 아래에서
  // 위로 슬라이드해 올라오게 해서 "실시간 상황을 알려주는 오버레이 패널"
  // 느낌을 다른 화면들과 통일했다.
  late final AnimationController _controller = AnimationController(
    vsync: this,
    duration: const Duration(milliseconds: 420),
  );
  late final Animation<Offset> _bannerOffset = Tween<Offset>(
    begin: const Offset(0, 1.15),
    end: Offset.zero,
  ).animate(CurvedAnimation(parent: _controller, curve: Curves.easeInOutCubic));

  Timer? _statusPollTimer;
  Timer? _completionTimer;

  String? _resolvedUserNameValue;
  String _statusMessage = '구매 이력을 확인할 준비를 하고 있어요.';
  String _progressLabel = '대기 중';
  String? _helperMessage;
  bool _isLoading = true;
  bool _hasCompletedFlow = false;
  bool _isImportingCurrentPlatform = false;
  bool _isAccessibilityConnected = false;
  Future<void> _speechQueue = Future<void>.value();
  String? _lastSpokenMessage;
  List<PurchaseHistoryAutomationPlan> _automationPlans =
      const <PurchaseHistoryAutomationPlan>[];
  int _currentAutomationPlanIndex = 0;
  int _totalImportedPurchaseHistoryCount = 0;

  List<PurchaseHistoryPreviewItem> _previewItems =
      const <PurchaseHistoryPreviewItem>[];

  String get _resolvedUserName {
    final trimmed = _resolvedUserNameValue?.trim() ?? widget.userName?.trim();
    return trimmed == null || trimmed.isEmpty ? '고객' : trimmed;
  }

  @override
  void initState() {
    super.initState();
    _controller.forward();
    unawaited(_voiceService.init());
    if (_service.hasCompletedAutomationFlowThisSession) {
      unawaited(_restoreCompletedAutomationFlow());
    } else if (widget.useMockFlow) {
      unawaited(_runMockLoadFlow());
    } else {
      unawaited(_runLoadFlow());
    }
  }

  @override
  void dispose() {
    _statusPollTimer?.cancel();
    _completionTimer?.cancel();
    unawaited(_voiceService.stopSpeaking());
    _controller.dispose();
    super.dispose();
  }

  Future<void> _runLoadFlow() async {
    try {
      final userId = await _service.resolveUserId();
      final resolvedUserName = widget.userName?.trim().isNotEmpty == true
          ? widget.userName!.trim()
          : await _service.resolveUserName(userId: userId);
      final installedPlatforms = await _service.getInstalledPlatforms();
      final automationPlans = _service.createAutomationPlans(
        installedPlatforms,
      );
      final initialStatus = await _service.getAutomationStatus();
      final serviceConnected = initialStatus['serviceConnected'] == true;
      final firstAutomationPlan = automationPlans.firstOrNull;

      if (!mounted) {
        return;
      }

      setState(() {
        _resolvedUserNameValue = resolvedUserName;
        _isAccessibilityConnected = serviceConnected;
        _automationPlans = automationPlans;
        _currentAutomationPlanIndex = 0;
        _totalImportedPurchaseHistoryCount = 0;
        _statusMessage = firstAutomationPlan != null
            ? '${firstAutomationPlan.displayName} 앱에서 지난 주문 내역을 불러오고 있어요.'
            : '저장된 구매 이력을 불러오고 있어요.';
        _helperMessage = automationPlans.isEmpty
            ? _service.unsupportedAutomationReason(installedPlatforms)
            : _service.skippedAutomationMessage(installedPlatforms);
        _progressLabel = firstAutomationPlan != null
            ? '자동 추출 준비 중'
            : '저장된 이력 확인 중';
      });
      unawaited(_speakMessage(_statusMessage));

      if (automationPlans.isNotEmpty && serviceConnected) {
        await _startCurrentAutomationPlan(userId: userId);
        _startAutomationPolling(userId: userId);
        return;
      }

      if (automationPlans.isNotEmpty && !serviceConnected && mounted) {
        setState(() {
          _helperMessage = '접근성 서비스가 아직 연결되지 않아 저장된 구매 이력만 먼저 불러오고 있어요.';
        });
      }

      await _loadStoredHistoriesAndFinish(userId: userId);
    } catch (error) {
      if (!mounted) {
        return;
      }

      setState(() {
        _isLoading = false;
        _statusMessage = '구매 이력을 불러오는 중 문제가 생겼어요.';
        _helperMessage = '네트워크 연결을 확인한 뒤 다시 시도해주세요.';
        _progressLabel = '다시 확인 필요';
      });
    }
  }

  Future<void> _restoreCompletedAutomationFlow() async {
    try {
      final userId = await _service.resolveUserId();
      _hasCompletedFlow = true;
      await _loadStoredHistoriesAndFinish(userId: userId);
    } catch (error) {
      if (!mounted) {
        return;
      }

      setState(() {
        _isLoading = false;
        _statusMessage = '저장된 구매 이력을 불러오는 중 문제가 생겼어요.';
        _helperMessage = '네트워크 연결을 확인한 뒤 다시 시도해주세요.';
        _progressLabel = '다시 확인 필요';
      });
    }
  }

  Future<void> _runMockLoadFlow() async {
    setState(() {
      _resolvedUserNameValue = widget.userName?.trim();
      _isAccessibilityConnected = true;
      _statusMessage = '지난 주문 내역을 불러오고 있어요.';
      _helperMessage = '최근 구매한 상품을 정리해서 보여드릴게요.';
      _progressLabel = '불러오는 중';
      _isLoading = true;
    });
    await _speakMessage('지난 주문 내역을 불러오고 있어요.');

    await Future<void>.delayed(const Duration(milliseconds: 250));
    if (!mounted) {
      return;
    }

    setState(() {
      _isLoading = false;
      _progressLabel = '3개 항목 준비 완료';
      _statusMessage = '저장된 구매 이력을 불러왔어요.';
      _helperMessage = '이전 주문 내역을 홈 화면에서 다시 확인할 수 있어요.';
      _previewItems = [
        _buildPreview(
          productName: '대추방울토마토 750g',
          subtitle: '컬리 8,900원',
          caption: '최근 주문',
        ),
        _buildPreview(
          productName: '국내산 삼겹살 1kg',
          subtitle: '쿠팡 27,900원',
          caption: '다시 구매 가능',
        ),
        _buildPreview(
          productName: '유기농 찰토마토 900g',
          subtitle: '네이버 12,900원',
          caption: '자주 본 상품',
        ),
      ];
    });
    await _speakMessage('저장된 구매 이력을 불러왔어요. 홈 화면에서 다시 확인할 수 있어요.');

    _scheduleCompletion();
  }

  void _startAutomationPolling({required int userId}) {
    _statusPollTimer?.cancel();
    _statusPollTimer = Timer.periodic(
      const Duration(seconds: 1),
      (_) => unawaited(_pollAutomation(userId: userId)),
    );
    unawaited(_pollAutomation(userId: userId));
  }

  Future<void> _startCurrentAutomationPlan({required int userId}) async {
    if (_currentAutomationPlanIndex >= _automationPlans.length) {
      await _finishAutomationSequence(userId: userId);
      return;
    }

    final plan = _automationPlans[_currentAutomationPlanIndex];
    await _service.prepareForExtraction();
    await _service.startExtraction(plan);
    if (!mounted) {
      return;
    }

    setState(() {
      _isLoading = true;
      _statusMessage = '${plan.displayName} 앱에서 지난 주문 내역을 불러오고 있어요.';
      _progressLabel =
          '${_currentAutomationPlanIndex + 1}/${_automationPlans.length} ${plan.displayName} 확인 중';
      _helperMessage = _automationPlans.length > 1
          ? '플랫폼별로 순서대로 구매 이력을 확인하고 있어요.'
          : _helperMessage;
    });
  }

  Future<void> _pollAutomation({required int userId}) async {
    if (_hasCompletedFlow || _isImportingCurrentPlatform) {
      return;
    }

    final status = await _service.getAutomationStatus();
    final accumulatedItems = await _service.getAccumulatedItems();
    if (!mounted) {
      return;
    }

    final taskCompleted = status['taskCompleted'] == true;
    final currentStep = status['currentStep']?.toString();
    final accumulatedCount = accumulatedItems.length;
    final lastMessage = status['lastMessage']?.toString().trim();

    setState(() {
      _isAccessibilityConnected = status['serviceConnected'] == true;
      _statusMessage = (lastMessage != null && lastMessage.isNotEmpty)
          ? lastMessage
          : '구매 이력을 불러오고 있어요.';
      _progressLabel = accumulatedCount > 0
          ? '$accumulatedCount개 항목 확인됨'
          : (currentStep == null ? '확인 중' : _stepLabelFor(currentStep));
      if (accumulatedItems.isNotEmpty) {
        _previewItems = _previewsFromAccumulated(accumulatedItems);
      }
    });

    if (taskCompleted || currentStep == 'completed') {
      _statusPollTimer?.cancel();
      await _importCurrentPlatformAndContinue(userId: userId);
    }
  }

  Future<void> _importCurrentPlatformAndContinue({required int userId}) async {
    if (_hasCompletedFlow || _isImportingCurrentPlatform) {
      return;
    }

    _isImportingCurrentPlatform = true;
    final plan = _currentAutomationPlanIndex < _automationPlans.length
        ? _automationPlans[_currentAutomationPlanIndex]
        : null;
    try {
      final importResponse = await _service.importAccumulatedPurchaseHistory();
      _totalImportedPurchaseHistoryCount += importResponse.count;
      final histories = await _service.fetchUserHistories(userId: userId);
      if (!mounted) {
        return;
      }

      final previews = histories.histories.isNotEmpty
          ? _previewsFromHistories(histories.histories)
          : _previewItems;

      setState(() {
        _previewItems = previews;
        _statusMessage = _platformImportMessage(plan, importResponse.count);
        _progressLabel = histories.histories.isEmpty
            ? '표시할 이력이 아직 없어요'
            : '${histories.histories.length}개 항목 준비 완료';
        if (importResponse.skippedCount > 0) {
          _helperMessage =
              '${importResponse.skippedCount}개 항목은 저장 조건이 맞지 않아 건너뛰었어요.';
        }
      });
      unawaited(_speakMessage(_statusMessage));
    } catch (error) {
      if (!mounted) {
        return;
      }

      setState(() {
        _isLoading = false;
        _statusMessage = '저장된 구매 이력을 불러왔어요.';
        _helperMessage = '자동 저장 중 일부 문제가 있어 기존 이력만 먼저 보여드릴게요.';
      });
      unawaited(_speakMessage(_statusMessage));
      await _loadStoredHistoriesAndFinish(
        userId: userId,
        scheduleAfterFetch: false,
      );
    } finally {
      _isImportingCurrentPlatform = false;
    }

    await _service.prepareForExtraction();
    _currentAutomationPlanIndex += 1;

    if (_currentAutomationPlanIndex < _automationPlans.length) {
      await _startCurrentAutomationPlan(userId: userId);
      _startAutomationPolling(userId: userId);
      return;
    }

    await _finishAutomationSequence(userId: userId);
  }

  Future<void> _finishAutomationSequence({required int userId}) async {
    if (_hasCompletedFlow) {
      return;
    }

    _hasCompletedFlow = true;
    _service.markCompletedAutomationFlowThisSession();
    final histories = await _service.fetchUserHistories(userId: userId);
    if (!mounted) {
      return;
    }

    setState(() {
      _isLoading = false;
      _previewItems = _previewsFromHistories(histories.histories);
      _statusMessage = _totalImportedPurchaseHistoryCount > 0
          ? '구매 이력 $_totalImportedPurchaseHistoryCount개를 저장했어요.'
          : '저장된 구매 이력을 불러왔어요.';
      _progressLabel = histories.histories.isEmpty
          ? '표시할 이력이 아직 없어요'
          : '${histories.histories.length}개 항목 준비 완료';
      if (_automationPlans.length > 1) {
        _helperMessage = '연결된 쇼핑 앱의 구매 이력 확인을 마쳤어요.';
      }
    });
    await _service.returnToDdalangooApp();
    if (!mounted) {
      return;
    }
    unawaited(_speakMessage(_statusMessage));
    _scheduleCompletion();
  }

  String _platformImportMessage(
    PurchaseHistoryAutomationPlan? plan,
    int importedCount,
  ) {
    final platformName = plan?.displayName ?? '쇼핑 앱';
    if (importedCount > 0) {
      return '$platformName 구매 이력 $importedCount개를 저장했어요.';
    }
    return '$platformName에서 새로 저장할 구매 이력을 찾지 못했어요.';
  }

  Future<void> _loadStoredHistoriesAndFinish({
    required int userId,
    bool scheduleAfterFetch = true,
  }) async {
    final histories = await _service.fetchUserHistories(userId: userId);
    if (!mounted) {
      return;
    }

    setState(() {
      _isLoading = false;
      _previewItems = _previewsFromHistories(histories.histories);
      _progressLabel = histories.histories.isEmpty
          ? '표시할 이력이 아직 없어요'
          : '${histories.histories.length}개 항목 준비 완료';
      _statusMessage = histories.histories.isEmpty
          ? '아직 저장된 구매 이력이 없어요.'
          : '저장된 구매 이력을 불러왔어요.';
    });
    unawaited(_speakMessage(_statusMessage));

    if (scheduleAfterFetch) {
      _scheduleCompletion();
    }
  }

  void _scheduleCompletion() {
    _completionTimer?.cancel();
    _completionTimer = Timer(widget.postLoadDelay, _handleCompleted);
  }

  void _handleCompleted() {
    unawaited(_completeAfterSpeech());
  }

  Future<void> _completeAfterSpeech() async {
    await _waitForSpeechQueue();
    if (!mounted) {
      return;
    }

    if (widget.onCompleted != null) {
      widget.onCompleted!();
      return;
    }

    Navigator.of(context).pushReplacement(
      MaterialPageRoute<void>(
        builder: (_) => AnalysisIntroScreen(
          userName: _resolvedUserName,
          useMockFlow: widget.useMockFlow,
          nextRouteName: widget.nextRouteName,
        ),
      ),
    );
  }

  List<PurchaseHistoryPreviewItem> _previewsFromAccumulated(
    List<AccessibilityPurchaseHistoryItem> items,
  ) {
    return items
        .take(6)
        .map(
          (item) => _buildPreview(
            productName: item.productName,
            subtitle:
                '${_platformLabel(item.platform)} ${_formatPrice(item.price)}',
            caption: item.purchaseDate ?? '구매일 확인 중',
            imagePath: item.imageUrl,
          ),
        )
        .toList(growable: false);
  }

  List<PurchaseHistoryPreviewItem> _previewsFromHistories(
    List<PurchaseHistoryItemModel> histories,
  ) {
    return histories
        .take(6)
        .map(
          (history) => _buildPreview(
            productName: history.productName,
            subtitle:
                '${_platformLabel(history.platform)} ${_formatPrice(history.priceAtPurchase)}',
            caption: _formatPurchasedAt(history.purchasedAt),
          ),
        )
        .toList(growable: false);
  }

  Future<void> _speakMessage(String? message, {bool dedupe = true}) {
    final normalized = message?.trim() ?? '';
    if (normalized.isEmpty) {
      return _speechQueue;
    }
    if (dedupe && normalized == _lastSpokenMessage) {
      return _speechQueue;
    }

    // 화면에 보이는 말풍선/배너 텍스트가 실제 TTS로 말하는 내용과 항상
    // 일치하게 setState로 갱신한다.
    setState(() {
      _lastSpokenMessage = normalized;
    });
    _speechQueue = _speechQueue.then((_) async {
      if (!mounted) {
        return;
      }
      try {
        await _voiceService.speak(normalized);
      } catch (_) {
        // TTS playback is best-effort.
      }
    });
    return _speechQueue;
  }

  Future<void> _waitForSpeechQueue() async {
    try {
      await _speechQueue;
    } catch (_) {
      // Ignore speech failures during navigation gating.
    }
  }

  PurchaseHistoryPreviewItem _buildPreview({
    required String productName,
    required String subtitle,
    required String caption,
    String? imagePath,
  }) {
    final asset = _assetForProductName(productName);
    return PurchaseHistoryPreviewItem(
      title: productName,
      subtitle: subtitle,
      caption: caption,
      assetPath: asset.assetPath,
      imagePath: imagePath,
    );
  }

  _PreviewAsset _assetForProductName(String productName) {
    final normalized = productName.toLowerCase();
    final candidates = <_PreviewAsset>[
      const _PreviewAsset(
        keywords: ['딸기', 'strawberry'],
        assetPath: 'assets/mock_productimages/strawberry.jpg',
      ),
      const _PreviewAsset(
        keywords: ['바나나', 'banana'],
        assetPath: 'assets/mock_productimages/banana.png',
      ),
      const _PreviewAsset(
        keywords: ['계란', '달걀', 'egg'],
        assetPath: 'assets/mock_productimages/eggs.png',
      ),
      const _PreviewAsset(
        keywords: ['수박', 'watermelon'],
        assetPath: 'assets/mock_productimages/watermelon.png',
      ),
      const _PreviewAsset(
        keywords: ['콩국수', '면', '국수'],
        assetPath: 'assets/mock_productimages/beannoodle.png',
      ),
      const _PreviewAsset(
        keywords: ['고구마', '말랭이'],
        assetPath: 'assets/mock_productimages/sweetpotato.png',
      ),
      const _PreviewAsset(
        keywords: ['한라봉', '감귤', 'orange'],
        assetPath: 'assets/mock_productimages/hallabong.png',
      ),
      const _PreviewAsset(
        keywords: ['토레타', '음료', 'drink'],
        assetPath: 'assets/mock_productimages/toreta.png',
      ),
      const _PreviewAsset(
        keywords: ['시루콧토', '타올', '화장솜'],
        assetPath: 'assets/mock_productimages/sirukotto.png',
      ),
    ];

    for (final candidate in candidates) {
      if (candidate.keywords.any(normalized.contains)) {
        return candidate;
      }
    }

    return candidates[productName.hashCode.abs() % candidates.length];
  }

  String _platformLabel(String? platform) {
    return switch (platform?.toLowerCase()) {
      'kurly' => '컬리',
      'coupang' => '쿠팡',
      'naver' => '네이버',
      'gmarket' => '지마켓',
      _ => '구매 이력',
    };
  }

  String _formatPrice(int? price) {
    if (price == null || price <= 0) {
      return '가격 확인 중';
    }
    final digits = price.toString();
    final buffer = StringBuffer();
    for (var index = 0; index < digits.length; index += 1) {
      final reverseIndex = digits.length - index;
      buffer.write(digits[index]);
      if (reverseIndex > 1 && reverseIndex % 3 == 1) {
        buffer.write(',');
      }
    }
    return '$buffer원';
  }

  String _formatPurchasedAt(String purchasedAt) {
    if (purchasedAt.isEmpty) {
      return '구매일 확인 중';
    }
    final parts = purchasedAt.split('T');
    return parts.first;
  }

  String _stepLabelFor(String step) {
    return switch (step) {
      'open_my_kurly' => '컬리 앱 여는 중',
      'open_order_history' => '주문 내역 여는 중',
      'dump_purchase_history' => '주문 내역 읽는 중',
      'extract_purchase_history' => '상품명 정리 중',
      'scroll_purchase_history' => '더 많은 이력 찾는 중',
      'finish_purchase_history' => '마무리 중',
      _ => '확인 중',
    };
  }

  @override
  Widget build(BuildContext context) {
    // platform_check_screen과 동일한 Stack 오버레이 구조: 배경에는 진행 중인
    // 구매 이력 카드들이 스크롤 가능한 형태로 항상 보이고, 그 위에 캐릭터 +
    // 실시간 진행 상황 배너 + CTA 버튼이 담긴 패널이 하단에 떠서 겹쳐진다.
    final layout = AppLayout.of(context, LayoutPreset.loading);

    return Scaffold(
      backgroundColor: const Color(0xFFF7F7FA),
      body: SafeArea(
        child: Padding(
          padding: layout.padding,
          child: Align(
            alignment: Alignment.topCenter,
            child: ConstrainedBox(
              constraints: BoxConstraints(maxWidth: layout.maxWidth),
              child: Stack(
                fit: StackFit.expand,
                children: [
                  _PurchaseHistoryBackground(
                    resolvedUserName: _resolvedUserName,
                    previewItems: _previewItems,
                  ),
                  Align(
                    alignment: Alignment.bottomCenter,
                    child: SlideTransition(
                      position: _bannerOffset,
                      child: Column(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          // 다른 오버레이 화면들(platform_check 등)과 같은
                          // 위치·비율로 캐릭터를 하단 패널 쪽에 둬서 레이아웃
                          // 통일감을 맞췄다.
                          Image.asset(
                            'assets/images/character/full/ddalangoo_searching.png',
                            height: 108,
                            fit: BoxFit.contain,
                          ),
                          const SizedBox(height: AppSpacing.sm),
                          PurchaseHistoryProgressBanner(
                            statusMessage: _statusMessage,
                            helperMessage: _helperMessage,
                            progressLabel: _progressLabel,
                            isLoading: _isLoading,
                          ),
                          const SizedBox(height: AppSpacing.sm),
                          PrimaryButton(
                            label: _isLoading ? '불러오는 중...' : '홈으로 돌아가기',
                            icon: _isLoading
                                ? Icons.hourglass_top_rounded
                                : Icons.home_rounded,
                            onPressed: _isLoading ? null : _handleCompleted,
                          ),
                        ],
                      ),
                    ),
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class PurchaseHistoryPreviewItem {
  const PurchaseHistoryPreviewItem({
    required this.title,
    required this.subtitle,
    required this.caption,
    required this.assetPath,
    this.imagePath,
  });

  final String title;
  final String subtitle;
  final String caption;
  final String assetPath;
  final String? imagePath;
}

class _PreviewAsset {
  const _PreviewAsset({required this.keywords, required this.assetPath});

  final List<String> keywords;
  final String assetPath;
}

/// platform_check_screen의 _PlatformCheckBackground와 같은 역할: 화면
/// 배경 전체를 채우는 스크롤 가능한 콘텐츠. 말풍선 + 구매 이력 미리보기
/// 카드들을 보여주고, 하단은 오버레이 패널에 가리지 않도록 여백을 둔다.
class _PurchaseHistoryBackground extends StatelessWidget {
  const _PurchaseHistoryBackground({
    required this.resolvedUserName,
    required this.previewItems,
  });

  final String resolvedUserName;
  final List<PurchaseHistoryPreviewItem> previewItems;

  @override
  Widget build(BuildContext context) {
    final responsive = context.responsive;

    return DecoratedBox(
      decoration: const BoxDecoration(
        gradient: LinearGradient(
          begin: Alignment.topCenter,
          end: Alignment.bottomCenter,
          colors: [Colors.white, Color(0xFFF9F2F6), Color(0xFFF3F4F8)],
        ),
      ),
      child: Padding(
        padding: EdgeInsets.only(
          // 하단 패널(캐릭터+배너+버튼)에 배경 콘텐츠가 가려지지 않도록 그
          // 높이만큼 여백을 둔다. platform_check_screen과 같은 계산식.
          bottom: responsive.bound(
            responsive.heightScaled(268, minFactor: 0.72, maxFactor: 1.0),
            min: 220,
            max: 268,
          ),
        ),
        child: SingleChildScrollView(
          physics: const ClampingScrollPhysics(),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              // 다른 대화형 화면(스몰토크/에이전트 인사/메인 쇼핑 흐름)과 같은
              // 말풍선(DialogueBubble)을 써서 딸랑구가 말하는 부분의 모양을
              // 통일했다.
              DialogueBubble(
                text: '$resolvedUserName님의 지난 구매 이력을\n불러오는 중이에요',
                cyclePages: true,
                highlightedWords: [resolvedUserName],
                minHeight: 96,
                style: AppTextStyles.title2.copyWith(
                  color: AppColors.textStrong,
                  height: 1.32,
                  fontWeight: FontWeight.w700,
                ),
                emphasizedStyle: AppTextStyles.title2.copyWith(
                  color: AppColors.primaryPinkDark,
                  height: 1.32,
                  fontWeight: FontWeight.w800,
                ),
              ),
              const SizedBox(height: AppSpacing.lg),
              previewItems.isEmpty
                  ? const _LoadingPlaceholder()
                  : _PreviewGrid(items: previewItems),
            ],
          ),
        ),
      ),
    );
  }
}

class _PreviewGrid extends StatelessWidget {
  const _PreviewGrid({required this.items});

  final List<PurchaseHistoryPreviewItem> items;

  @override
  Widget build(BuildContext context) {
    final responsive = context.responsive;

    return LayoutBuilder(
      builder: (context, constraints) {
        final singleColumn = constraints.maxWidth < 340;
        final crossAxisCount = singleColumn ? 1 : 2;
        final childAspectRatio = singleColumn
            ? 1.62
            : (responsive.isShortHeight ? 0.84 : 0.78);

        return GridView.builder(
          padding: EdgeInsets.zero,
          shrinkWrap: true,
          physics: const NeverScrollableScrollPhysics(),
          gridDelegate: SliverGridDelegateWithFixedCrossAxisCount(
            crossAxisCount: crossAxisCount,
            mainAxisSpacing: AppSpacing.md,
            crossAxisSpacing: AppSpacing.md,
            childAspectRatio: childAspectRatio,
          ),
          itemCount: items.length,
          itemBuilder: (context, index) {
            final preview = items[index];
            return PurchaseHistoryThumbnailCard(
              title: preview.title,
              subtitle: preview.subtitle,
              caption: preview.caption,
              assetPath: preview.assetPath,
              imagePath: preview.imagePath,
            );
          },
        );
      },
    );
  }
}

/// platform_check_screen의 _PlatformProgressBanner와 같은 모양의 실시간
/// 진행 상황 카드. 하단 오버레이 패널 안에서 statusMessage/helperMessage/
/// progressLabel을 그대로 보여줘 백그라운드 자동화 진행 상황과 항상
/// 일치하게 한다.
class PurchaseHistoryProgressBanner extends StatelessWidget {
  const PurchaseHistoryProgressBanner({
    super.key,
    required this.statusMessage,
    required this.helperMessage,
    required this.progressLabel,
    required this.isLoading,
  });

  final String statusMessage;
  final String? helperMessage;
  final String progressLabel;
  final bool isLoading;

  @override
  Widget build(BuildContext context) {
    final chipColor = isLoading ? AppColors.primaryPinkDark : AppColors.success;

    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(AppSpacing.md),
      decoration: AppSurfaceStyles.elevatedCard(
        radius: AppRadii.xl,
        color: Colors.white,
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Container(
            width: 44,
            height: 44,
            decoration: BoxDecoration(
              color: chipColor.withValues(alpha: 0.12),
              shape: BoxShape.circle,
            ),
            child: Icon(Icons.receipt_long_rounded, color: chipColor, size: 24),
          ),
          const SizedBox(width: AppSpacing.md),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              mainAxisSize: MainAxisSize.min,
              children: [
                Row(
                  children: [
                    Text(
                      '진행 상황',
                      style: AppTextStyles.caption.copyWith(
                        color: AppColors.textMuted,
                        fontWeight: FontWeight.w800,
                      ),
                    ),
                    const Spacer(),
                    Container(
                      padding: const EdgeInsets.symmetric(
                        horizontal: AppSpacing.sm,
                        vertical: AppSpacing.xs,
                      ),
                      decoration: BoxDecoration(
                        color: chipColor.withValues(alpha: 0.12),
                        borderRadius: BorderRadius.circular(AppRadii.pill),
                      ),
                      child: Text(
                        progressLabel,
                        style: AppTextStyles.caption.copyWith(
                          color: chipColor,
                          fontWeight: FontWeight.w800,
                        ),
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: AppSpacing.xs),
                Text(
                  statusMessage,
                  style: AppTextStyles.body2.copyWith(
                    color: AppColors.textStrong,
                    fontWeight: FontWeight.w800,
                    height: 1.35,
                  ),
                ),
                if (helperMessage != null) ...[
                  const SizedBox(height: AppSpacing.xxs),
                  Text(
                    helperMessage!,
                    style: AppTextStyles.caption.copyWith(
                      color: AppColors.textSecondary,
                      fontWeight: FontWeight.w600,
                      height: 1.35,
                    ),
                  ),
                ],
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _LoadingPlaceholder extends StatefulWidget {
  const _LoadingPlaceholder();

  @override
  State<_LoadingPlaceholder> createState() => _LoadingPlaceholderState();
}

class _LoadingPlaceholderState extends State<_LoadingPlaceholder> {
  int _dotCount = 0;
  Timer? _timer;

  @override
  void initState() {
    super.initState();
    _timer = Timer.periodic(const Duration(milliseconds: 420), (_) {
      if (!mounted) {
        return;
      }
      setState(() => _dotCount = (_dotCount + 1) % 4);
    });
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final dots = '.' * _dotCount;
    // 이 위젯은 이제 배경의 SingleChildScrollView 안(Expanded로 눌리지
    // 않는 자연스러운 높이)에 놓이기 때문에, 예전처럼 남는 세로 공간이
    // 좁아져 오버플로우를 걱정할 필요 없이 콘텐츠 크기 그대로 표시하면
    // 된다.
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(AppSpacing.xl),
      decoration: BoxDecoration(
        color: Colors.white.withValues(alpha: 0.9),
        borderRadius: BorderRadius.circular(AppRadii.xl),
        border: Border.all(color: AppColors.border),
      ),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Image.asset(
            'assets/images/character/full/ddalangoo_searching.png',
            height: 132,
            fit: BoxFit.contain,
          ),
          const SizedBox(height: AppSpacing.lg),
          Text(
            '지난 주문 내역을 차근차근 살펴보고 있어요$dots',
            textAlign: TextAlign.center,
            style: AppTextStyles.body1.copyWith(
              color: AppColors.textStrong,
              fontWeight: FontWeight.w800,
            ),
          ),
        ],
      ),
    );
  }
}
