import 'dart:async';

import 'package:flutter/material.dart';

import '../../../app/routes.dart';
import '../../../app/theme/app_colors.dart';
import '../../../app/theme/app_radii.dart';
import '../../../app/theme/app_spacing.dart';
import '../../../app/theme/app_text_styles.dart';
import '../../../core/services/voice_service.dart';
import '../../../data/models/accessibility_purchase_history_model.dart';
import '../../../data/models/purchase_history_model.dart';
import '../../../shared/layout/bottom_cta_layout.dart';
import '../../../shared/layout/layout_presets.dart';
import '../../../shared/layout/screen_frame.dart';
import '../../../shared/widgets/end_conversation_button.dart';
import '../../../shared/widgets/primary_button.dart';
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
    extends State<PurchaseHistoryLoadingScreen> {
  final PurchaseHistoryLoadingService _service =
      PurchaseHistoryLoadingService();
  final VoiceService _voiceService = VoiceService.instance;

  Timer? _statusPollTimer;
  Timer? _completionTimer;

  String? _resolvedUserNameValue;
  String _statusMessage = '구매 이력을 확인할 준비를 하고 있어요.';
  String _progressLabel = '대기 중';
  String? _helperMessage;
  bool _isLoading = true;
  bool _hasCompletedFlow = false;
  bool _isAccessibilityConnected = false;
  Future<void> _speechQueue = Future<void>.value();
  String? _lastSpokenMessage;

  List<PurchaseHistoryPreviewItem> _previewItems =
      const <PurchaseHistoryPreviewItem>[];

  String get _resolvedUserName {
    final trimmed = _resolvedUserNameValue?.trim() ?? widget.userName?.trim();
    return trimmed == null || trimmed.isEmpty ? '고객' : trimmed;
  }

  @override
  void initState() {
    super.initState();
    unawaited(_voiceService.init());
    if (widget.useMockFlow) {
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
    super.dispose();
  }

  Future<void> _runLoadFlow() async {
    try {
      final userId = await _service.resolveUserId();
      final resolvedUserName = widget.userName?.trim().isNotEmpty == true
          ? widget.userName!.trim()
          : await _service.resolveUserName(userId: userId);
      final installedPlatforms = await _service.getInstalledPlatforms();
      final automationPlan = _service.createAutomationPlan(installedPlatforms);
      final initialStatus = await _service.getAutomationStatus();
      final serviceConnected = initialStatus['serviceConnected'] == true;

      if (!mounted) {
        return;
      }

      setState(() {
        _resolvedUserNameValue = resolvedUserName;
        _isAccessibilityConnected = serviceConnected;
        _statusMessage = automationPlan.canAutomate
            ? '${automationPlan.displayName} 앱에서 지난 주문 내역을 불러오고 있어요.'
            : '저장된 구매 이력을 불러오고 있어요.';
        _helperMessage = automationPlan.reason;
        _progressLabel = automationPlan.canAutomate
            ? '자동 추출 준비 중'
            : '저장된 이력 확인 중';
      });
      unawaited(_speakMessage(_statusMessage));

      if (automationPlan.canAutomate && serviceConnected) {
        await _service.prepareForExtraction();
        await _service.startExtraction(automationPlan);
        _startAutomationPolling(userId: userId);
        return;
      }

      if (automationPlan.canAutomate && !serviceConnected && mounted) {
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
        _helperMessage = error.toString();
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

  Future<void> _pollAutomation({required int userId}) async {
    if (_hasCompletedFlow) {
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
      await _importAndFinish(userId: userId);
    }
  }

  Future<void> _importAndFinish({required int userId}) async {
    if (_hasCompletedFlow) {
      return;
    }

    _hasCompletedFlow = true;
    try {
      final importResponse = await _service.importAccumulatedPurchaseHistory();
      final histories = await _service.fetchUserHistories(userId: userId);
      if (!mounted) {
        return;
      }

      final previews = histories.histories.isNotEmpty
          ? _previewsFromHistories(histories.histories)
          : _previewItems;

      setState(() {
        _isLoading = false;
        _previewItems = previews;
        _statusMessage = importResponse.count > 0
            ? '구매 이력 ${importResponse.count}개를 저장했어요.'
            : '저장된 구매 이력을 불러왔어요.';
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
    }

    _scheduleCompletion();
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

    Navigator.of(context).pushReplacementNamed(widget.nextRouteName);
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

    _lastSpokenMessage = normalized;
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
  }) {
    final asset = _assetForProductName(productName);
    return PurchaseHistoryPreviewItem(
      title: productName,
      subtitle: subtitle,
      caption: caption,
      assetPath: asset.assetPath,
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
    return ScreenFrame(
      preset: LayoutPreset.standard,
      child: BottomCtaLayout(
        content: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Align(
              alignment: Alignment.centerRight,
              child: EndConversationButton(
                compact: true,
                label: '대화 종료',
                onPressed: _handleCompleted,
              ),
            ),
            const SizedBox(height: AppSpacing.md),
            _TopPill(
              icon: Icons.history_rounded,
              label: _isAccessibilityConnected ? '접근성 연결됨' : '구매 이력 불러오기',
            ),
            const SizedBox(height: AppSpacing.lg),
            Text(
              '$_resolvedUserName님의 지난 구매 이력을\n불러오는 중이에요',
              style: AppTextStyles.title1.copyWith(height: 1.32),
            ),
            const SizedBox(height: AppSpacing.sm),
            Text(
              _statusMessage,
              style: AppTextStyles.body2.copyWith(
                color: AppColors.textSecondary,
                fontWeight: FontWeight.w700,
              ),
            ),
            if (_helperMessage != null) ...[
              const SizedBox(height: AppSpacing.sm),
              Container(
                width: double.infinity,
                padding: const EdgeInsets.symmetric(
                  horizontal: AppSpacing.md,
                  vertical: AppSpacing.sm,
                ),
                decoration: BoxDecoration(
                  color: AppColors.surfaceMuted,
                  borderRadius: BorderRadius.circular(AppRadii.md),
                ),
                child: Text(
                  _helperMessage!,
                  style: AppTextStyles.caption.copyWith(
                    color: AppColors.textSecondary,
                    fontWeight: FontWeight.w700,
                  ),
                ),
              ),
            ],
            const SizedBox(height: AppSpacing.lg),
            Row(
              children: [
                _InfoChip(
                  label: _progressLabel,
                  backgroundColor: AppColors.secondaryPink,
                  textColor: AppColors.primaryPinkDark,
                ),
                const SizedBox(width: AppSpacing.sm),
                _InfoChip(
                  label: _previewItems.isEmpty
                      ? '0개 준비'
                      : '${_previewItems.length}개 미리보기',
                  backgroundColor: AppColors.surfaceMuted,
                  textColor: AppColors.textSecondary,
                ),
              ],
            ),
            const SizedBox(height: AppSpacing.lg),
            Expanded(
              child: _previewItems.isEmpty
                  ? const _LoadingPlaceholder()
                  : GridView.builder(
                      padding: EdgeInsets.zero,
                      gridDelegate:
                          const SliverGridDelegateWithFixedCrossAxisCount(
                            crossAxisCount: 2,
                            mainAxisSpacing: AppSpacing.md,
                            crossAxisSpacing: AppSpacing.md,
                            childAspectRatio: 0.76,
                          ),
                      itemCount: _previewItems.length,
                      itemBuilder: (context, index) {
                        final preview = _previewItems[index];
                        return PurchaseHistoryThumbnailCard(
                          title: preview.title,
                          subtitle: preview.subtitle,
                          caption: preview.caption,
                          assetPath: preview.assetPath,
                        );
                      },
                    ),
            ),
          ],
        ),
        cta: _isLoading
            ? const PrimaryButton(
                label: '불러오는 중...',
                icon: Icons.hourglass_top_rounded,
              )
            : PrimaryButton(
                label: '홈으로 돌아가기',
                icon: Icons.home_rounded,
                onPressed: _handleCompleted,
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
  });

  final String title;
  final String subtitle;
  final String caption;
  final String assetPath;
}

class _PreviewAsset {
  const _PreviewAsset({required this.keywords, required this.assetPath});

  final List<String> keywords;
  final String assetPath;
}

class _TopPill extends StatelessWidget {
  const _TopPill({required this.icon, required this.label});

  final IconData icon;
  final String label;

  @override
  Widget build(BuildContext context) {
    return Container(
      height: 44,
      padding: const EdgeInsets.symmetric(horizontal: AppSpacing.md),
      decoration: BoxDecoration(
        color: AppColors.surfaceMuted,
        borderRadius: BorderRadius.circular(AppRadii.pill),
        border: Border.all(color: AppColors.border),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, size: 18, color: AppColors.textSecondary),
          const SizedBox(width: AppSpacing.xs),
          Text(
            label,
            style: AppTextStyles.body2.copyWith(
              color: AppColors.textSecondary,
              fontWeight: FontWeight.w800,
            ),
          ),
        ],
      ),
    );
  }
}

class _InfoChip extends StatelessWidget {
  const _InfoChip({
    required this.label,
    required this.backgroundColor,
    required this.textColor,
  });

  final String label;
  final Color backgroundColor;
  final Color textColor;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(
        horizontal: AppSpacing.md,
        vertical: AppSpacing.sm,
      ),
      decoration: BoxDecoration(
        color: backgroundColor,
        borderRadius: BorderRadius.circular(AppRadii.pill),
      ),
      child: Text(
        label,
        style: AppTextStyles.caption.copyWith(
          color: textColor,
          fontWeight: FontWeight.w800,
        ),
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
    return Container(
      width: double.infinity,
      decoration: BoxDecoration(
        color: AppColors.surface,
        borderRadius: BorderRadius.circular(AppRadii.xl),
        border: Border.all(color: AppColors.border),
      ),
      child: Center(
        child: Padding(
          padding: const EdgeInsets.all(AppSpacing.xl),
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
        ),
      ),
    );
  }
}
