import 'dart:async';

import 'package:flutter/material.dart';

import '../../../app/routes.dart';
import '../../../app/theme/app_colors.dart';
import '../../../app/theme/app_radii.dart';
import '../../../app/theme/app_spacing.dart';
import '../../../app/theme/app_surface_styles.dart';
import '../../../app/theme/app_text_styles.dart';
import '../../../core/services/accessibility_automation_service.dart';
import '../../../core/services/voice_service.dart';
import '../../../shared/layout/app_layout.dart';
import '../../../shared/layout/app_responsive.dart';
import '../../../shared/layout/layout_presets.dart';
import '../../../shared/services/spoken_sentence_player.dart';
import '../../../shared/widgets/dialogue_bubble.dart';
import '../../../shared/widgets/end_conversation_button.dart';
import '../../shopping/screens/purchase_history_loading_screen.dart';
import '../services/platform_check_service.dart';

class PlatformCheckScreen extends StatefulWidget {
  const PlatformCheckScreen({
    super.key,
    this.userName,
    this.useMockFlow = false,
    this.onClosePressed,
    this.onCompleted,
    this.autoCompleteAfter = const Duration(milliseconds: 2200),
    this.nextRouteName = AppRoutes.purchaseHistoryLoading,
    this.supportedPlatforms = _defaultPlatforms,
  });

  final String? userName;
  final bool useMockFlow;
  final VoidCallback? onClosePressed;
  final VoidCallback? onCompleted;
  final Duration? autoCompleteAfter;
  final String nextRouteName;
  final List<PlatformPreviewApp> supportedPlatforms;

  static const _defaultPlatforms = <PlatformPreviewApp>[
    PlatformPreviewApp(
      id: 'naver',
      name: '네이버',
      packageName: 'com.nhn.android.search',
      assetPath: 'assets/images/platform/logo/naver.png',
    ),
    PlatformPreviewApp(
      id: 'coupang',
      name: '쿠팡',
      packageName: 'com.coupang.mobile',
      assetPath: 'assets/images/platform/logo/coupang.png',
    ),
    PlatformPreviewApp(
      id: 'kurly',
      name: '컬리',
      packageName: 'com.dbs.kurly.m2',
      assetPath: 'assets/images/platform/logo/kurly.png',
    ),
    PlatformPreviewApp(
      id: 'gmarket',
      name: '지마켓',
      packageName: 'com.ebay.kr.gmarket',
      assetPath: 'assets/images/platform/logo/gmarket.png',
    ),
    PlatformPreviewApp(
      id: 'hyundaihomeshopping',
      name: '현대홈쇼핑',
      packageName: 'com.hmallapp',
      assetPath: 'assets/images/platform/logo/hyundaihomeshopping.png',
    ),
  ];

  @override
  State<PlatformCheckScreen> createState() => _PlatformCheckScreenState();
}

class _PlatformCheckScreenState extends State<PlatformCheckScreen>
    with SingleTickerProviderStateMixin {
  final PlatformCheckService _platformCheckService = PlatformCheckService();
  final VoiceService _voiceService = VoiceService.instance;

  late final AnimationController _controller = AnimationController(
    vsync: this,
    duration: const Duration(milliseconds: 420),
  );
  late final Animation<Offset> _bannerOffset = Tween<Offset>(
    begin: const Offset(0, 1.15),
    end: Offset.zero,
  ).animate(CurvedAnimation(parent: _controller, curve: Curves.easeInOutCubic));

  late List<PlatformPreviewApp> _platforms = widget.supportedPlatforms;

  Timer? _statusPollTimer;
  Timer? _completionTimer;
  DateTime? _startedAt;
  String? _resolvedUserNameValue;
  String _statusHint = '설치된 쇼핑 앱을 확인하고 있어요.';
  String? _automationLastMessage;
  String? _lastDetectedPlatformLabel;
  int? _totalInstalledAppCount;
  int? _scannedAppCount;
  int? _detectedShoppingAppCount;
  bool _isAccessibilityConnected = false;
  bool _isScanning = true;
  bool _didScheduleCompletion = false;
  Future<void> _speechQueue = Future<void>.value();
  String? _lastSpokenMessage;
  final SpokenSentencePlayer _sentencePlayer = SpokenSentencePlayer();
  String? _currentSpokenSentence;

  String get _resolvedUserName {
    final trimmed = _resolvedUserNameValue?.trim() ?? widget.userName?.trim();
    return trimmed == null || trimmed.isEmpty ? '고객' : trimmed;
  }

  // 말풍선에 표시할 문구. 아직 TTS가 한 번도 시작되지 않은 첫 프레임에는
  // 기본 인사말을 보여주고, 이후로는 실제로 지금 말하고 있는 문장
  // (_currentSpokenSentence)을 그대로 보여줘서 화면 텍스트와 TTS 내용이
  // 항상 일치하게 한다. 메시지가 여러 문장이면(예: "확인이 끝났어요. 다음
  // 화면으로 넘어갈게요.") 한 문장씩 순서대로 갱신된다.
  String get _bubbleText =>
      _currentSpokenSentence ??
      _lastSpokenMessage ??
      '$_resolvedUserName님, 어떤 쇼핑 앱을 쓰시는지 확인할게요';

  int get _installedPlatformCount =>
      _platforms.where((platform) => platform.isInstalled).length;

  int get _platformCandidateCount => widget.supportedPlatforms.length;

  String get _progressSummary {
    if (_totalInstalledAppCount != null && _totalInstalledAppCount! > 0) {
      if (_isScanning) {
        if ((_detectedShoppingAppCount ?? 0) > 0) {
          return '$_totalInstalledAppCount개 앱 중 '
              '${_detectedShoppingAppCount ?? 0}개의 쇼핑 앱이 확인되었어요.';
        }
        return '$_resolvedUserName님의 폰에 깔린 앱이 '
            '총 $_totalInstalledAppCount개예요.';
      }

      return '$_totalInstalledAppCount개 앱을 살펴본 결과 '
          '${_detectedShoppingAppCount ?? _installedPlatformCount}개의 쇼핑 앱이 확인되었어요.';
    }

    if (_isScanning) {
      if (_installedPlatformCount > 0) {
        return '$_platformCandidateCount개 후보 중 '
            '$_installedPlatformCount개의 쇼핑 앱이 확인되었어요.';
      }
      return '쇼핑 앱 후보 $_platformCandidateCount개를 살펴보고 있어요.';
    }

    if (_installedPlatformCount > 0) {
      return '쇼핑 앱 후보 $_platformCandidateCount개 중 '
          '$_installedPlatformCount개가 확인되었어요.';
    }

    return '쇼핑 앱 후보 확인이 끝났어요.';
  }

  String get _progressDetail {
    if (_totalInstalledAppCount != null && _totalInstalledAppCount! > 0) {
      if (_scannedAppCount != null &&
          _scannedAppCount! > 0 &&
          _scannedAppCount! < _totalInstalledAppCount!) {
        return '$_totalInstalledAppCount개 앱 중 '
            '$_scannedAppCount개를 살펴보고 있어요.';
      }
      if (_isScanning) {
        return '앱을 하나씩 살펴보는 중이에요.';
      }
    }

    if (!_isAccessibilityConnected) {
      return '접근성 서비스 연결 상태를 확인하고 있어요.';
    }

    if (_lastDetectedPlatformLabel != null &&
        _lastDetectedPlatformLabel != '대기 중') {
      return '마지막으로 $_lastDetectedPlatformLabel 앱을 확인했어요.';
    }

    if (_isScanning) {
      return '앱을 하나씩 살펴보는 중이에요.';
    }

    return '확인이 끝나면 다음 화면으로 바로 넘어갈게요.';
  }

  String get _progressChipLabel => _isScanning
      ? (_scannedAppCount != null && _totalInstalledAppCount != null
            ? '$_scannedAppCount/$_totalInstalledAppCount'
            : '앱 확인 중')
      : '${_detectedShoppingAppCount ?? _installedPlatformCount}개 확인';

  Color get _progressChipColor {
    if (_isScanning) {
      return AppColors.primaryPinkDark;
    }
    return _installedPlatformCount > 0
        ? AppColors.success
        : AppColors.textMuted;
  }

  @override
  void initState() {
    super.initState();
    _startedAt = DateTime.now();
    _controller.forward();
    unawaited(_voiceService.init());
    unawaited(_announcePlatformCheckStart());
    if (widget.useMockFlow) {
      unawaited(_runMockFlow());
    } else {
      unawaited(_loadPlatformCheckData());
      _startStatusPolling();
    }
  }

  @override
  void dispose() {
    _statusPollTimer?.cancel();
    _completionTimer?.cancel();
    _sentencePlayer.cancel();
    unawaited(_voiceService.stopSpeaking());
    _controller.dispose();
    super.dispose();
  }

  void _handleClosePressed() {
    _statusPollTimer?.cancel();
    _completionTimer?.cancel();
    unawaited(_voiceService.stopSpeaking());

    if (widget.onClosePressed != null) {
      widget.onClosePressed!();
      return;
    }

    Navigator.of(
      context,
    ).pushNamedAndRemoveUntil(AppRoutes.home, (route) => false);
  }

  Future<void> _announcePlatformCheckStart() async {
    try {
      await _voiceService.init();
    } catch (_) {
      // TTS는 화면 진행 보조라 초기화 실패가 플로우를 막으면 안 된다.
    }
    await _speakMessage('$_resolvedUserName님, 어떤 쇼핑 앱을 쓰시는지 확인할게요.');
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

    if (widget.userName?.trim().isNotEmpty == true || widget.useMockFlow) {
      // 쇼핑 앱 확인이 끝나면 바로 구매 이력 로딩 화면으로 들어간다.
      // 취향 분석 안내는 구매 이력 저장/불러오기가 끝난 뒤에 들려준다.
      Navigator.of(context).pushReplacement(
        MaterialPageRoute<void>(
          builder: (_) => PurchaseHistoryLoadingScreen(
            userName: _resolvedUserName,
            useMockFlow: widget.useMockFlow,
          ),
        ),
      );
      return;
    }

    Navigator.of(context).pushReplacementNamed(widget.nextRouteName);
  }

  Future<void> _runMockFlow() async {
    final resolvedPlatforms = widget.supportedPlatforms
        .map((platform) => platform.copyWith(isInstalled: false))
        .toList(growable: false);

    setState(() {
      _resolvedUserNameValue = widget.userName?.trim();
      _platforms = resolvedPlatforms;
      _isAccessibilityConnected = true;
      _automationLastMessage = '앱 목록을 불러왔어요.';
      _lastDetectedPlatformLabel = null;
      _totalInstalledAppCount = 34;
      _scannedAppCount = 0;
      _detectedShoppingAppCount = 0;
      _isScanning = true;
      _statusHint = '설치된 쇼핑 앱을 확인하고 있어요.';
    });
    await _speakMessage('$_resolvedUserName님의 폰에 깔린 앱이 총 34개예요.');

    await Future<void>.delayed(const Duration(milliseconds: 250));
    if (!mounted) {
      return;
    }

    setState(() {
      _platforms = resolvedPlatforms
          .map(
            (platform) => platform.id == 'naver'
                ? platform.copyWith(isInstalled: true)
                : platform,
          )
          .toList(growable: false);
      _automationLastMessage = '앱을 살펴보고 있어요.';
      _lastDetectedPlatformLabel = '네이버';
      _scannedAppCount = 12;
      _detectedShoppingAppCount = 1;
      _statusHint = '쇼핑 앱을 하나씩 확인하고 있어요.';
    });
    await _speakMessage('앱을 살펴보고 있어요.');

    await Future<void>.delayed(const Duration(milliseconds: 250));
    if (!mounted) {
      return;
    }

    setState(() {
      _platforms = resolvedPlatforms
          .map(
            (platform) => const {'naver', 'coupang'}.contains(platform.id)
                ? platform.copyWith(isInstalled: true)
                : platform,
          )
          .toList(growable: false);
      _lastDetectedPlatformLabel = '쿠팡';
      _scannedAppCount = 23;
      _detectedShoppingAppCount = 2;
    });
    await _speakMessage('34개 앱 중 2개의 쇼핑 앱이 확인되었어요.');

    await Future<void>.delayed(const Duration(milliseconds: 250));
    if (!mounted) {
      return;
    }

    setState(() {
      _platforms = resolvedPlatforms
          .map(
            (platform) =>
                const {'naver', 'coupang', 'kurly'}.contains(platform.id)
                ? platform.copyWith(isInstalled: true)
                : platform,
          )
          .toList(growable: false);
      _automationLastMessage = '쇼핑 앱 확인이 거의 끝났어요.';
      _lastDetectedPlatformLabel = '컬리';
      _scannedAppCount = 34;
      _detectedShoppingAppCount = 3;
      _isScanning = false;
      _statusHint = '3개의 쇼핑 앱이 확인되었어요.';
    });
    await _speakMessage('34개 앱 중 3개의 쇼핑 앱이 확인되었어요.');

    _scheduleCompletionWithMinimumDisplay();
  }

  Future<void> _loadPlatformCheckData() async {
    final resolvedUserNameFuture = widget.userName?.trim().isNotEmpty == true
        ? Future<String?>.value(widget.userName!.trim())
        : _platformCheckService.resolveUserName();
    final installedPlatformsFuture = _platformCheckService
        .getInstalledPlatforms();

    final results = await Future.wait<Object?>([
      resolvedUserNameFuture,
      installedPlatformsFuture,
    ]);

    if (!mounted) {
      return;
    }

    final resolvedUserName = results[0] as String?;
    final installedPlatforms = results[1] as List<InstalledShoppingPlatform>;
    final installedById = <String, InstalledShoppingPlatform>{
      for (final platform in installedPlatforms) platform.platform: platform,
    };
    final resolvedPlatforms = widget.supportedPlatforms
        .map(
          (platform) => platform.copyWith(
            isInstalled: installedById[platform.id]?.isInstalled ?? false,
          ),
        )
        .toList(growable: false);

    final installedCount = resolvedPlatforms
        .where((platform) => platform.isInstalled)
        .length;

    setState(() {
      _resolvedUserNameValue = resolvedUserName;
      _platforms = resolvedPlatforms;
      _detectedShoppingAppCount = installedCount;
      _isScanning = false;
      _statusHint = installedCount > 0
          ? '$installedCount개의 쇼핑 앱을 확인했어요.'
          : '확인된 쇼핑 앱이 없어요.';
    });
    unawaited(
      _speakMessage(
        installedCount > 0
            ? _installedAppCountSpeech(installedCount)
            : '확인된 쇼핑 앱은 아직 없어요.',
      ),
    );

    _scheduleCompletionWithMinimumDisplay();
  }

  String _installedAppCountSpeech(int installedCount) {
    final totalInstalledAppCount = _totalInstalledAppCount;
    if (totalInstalledAppCount != null && totalInstalledAppCount > 0) {
      return '$totalInstalledAppCount개 앱 중 $installedCount개의 쇼핑 앱이 확인되었어요.';
    }
    return '$installedCount개의 쇼핑 앱이 확인되었어요.';
  }

  void _startStatusPolling() {
    unawaited(_refreshAutomationStatus());
    _statusPollTimer = Timer.periodic(
      const Duration(seconds: 1),
      (_) => unawaited(_refreshAutomationStatus()),
    );
  }

  Future<void> _refreshAutomationStatus() async {
    final status = await _platformCheckService.getAutomationStatus();
    if (!mounted) {
      return;
    }

    final serviceConnected = status['serviceConnected'] == true;
    final lastMessage = status['lastMessage']?.toString().trim();
    final lastPackageName = status['lastPackageName']?.toString().trim();
    final totalInstalledAppCount = _toInt(status['totalInstalledAppCount']);
    final scannedAppCount =
        _toInt(status['scannedAppCount']) ??
        _toInt(status['inspectedAppCount']);
    final detectedShoppingAppCount = _toInt(status['detectedShoppingAppCount']);

    setState(() {
      _isAccessibilityConnected = serviceConnected;
      _automationLastMessage = lastMessage == null || lastMessage.isEmpty
          ? null
          : lastMessage;
      _lastDetectedPlatformLabel = _labelForPackageName(lastPackageName);
      _totalInstalledAppCount =
          totalInstalledAppCount ?? _totalInstalledAppCount;
      _scannedAppCount = scannedAppCount ?? _scannedAppCount;
      _detectedShoppingAppCount =
          detectedShoppingAppCount ?? _detectedShoppingAppCount;
    });
  }

  void _scheduleCompletionWithMinimumDisplay() {
    if (_didScheduleCompletion) {
      return;
    }
    _didScheduleCompletion = true;

    final minimumDisplayDuration = widget.autoCompleteAfter;
    final startedAt = _startedAt;
    if (minimumDisplayDuration == null || startedAt == null) {
      _handleCompleted();
      return;
    }

    final effectiveMinimumDisplayDuration =
        widget.useMockFlow &&
            minimumDisplayDuration < const Duration(milliseconds: 3200)
        ? const Duration(milliseconds: 3200)
        : minimumDisplayDuration;

    final elapsed = DateTime.now().difference(startedAt);
    final remaining = effectiveMinimumDisplayDuration - elapsed;
    final delay = remaining.isNegative ? Duration.zero : remaining;
    _completionTimer = Timer(delay, _handleCompleted);
  }

  String _labelForPackageName(String? packageName) {
    if (packageName == null || packageName.isEmpty) {
      return '대기 중';
    }

    for (final platform in _platforms) {
      if (platform.packageName == packageName) {
        return platform.name;
      }
    }

    return packageName;
  }

  int? _toInt(Object? value) {
    if (value is int) {
      return value;
    }
    if (value is num) {
      return value.toInt();
    }
    return int.tryParse(value?.toString() ?? '');
  }

  Future<void> _speakMessage(String? message, {bool dedupe = true}) {
    final normalized = message?.trim() ?? '';
    if (normalized.isEmpty) {
      return _speechQueue;
    }
    if (dedupe && normalized == _lastSpokenMessage) {
      return _speechQueue;
    }

    // dedupe 판단은 전체 문구 기준으로 그대로 두되(같은 안내를 중복
    // 재생하지 않기 위함), 화면에 보이는 텍스트(_currentSpokenSentence)는
    // 이 문구가 실제로 재생을 시작하는 시점에 한 문장씩 갱신한다. 예전엔
    // 여러 문장을 한 번에 speak()로 넘기면서 DialogueBubble의
    // cyclePages(고정 타이머)가 따로 문장을 순환해 화면과 음성 타이밍이
    // 어긋났다.
    _lastSpokenMessage = normalized;
    final sentences = SpokenSentencePlayer.splitSentences(normalized);
    _speechQueue = _speechQueue.then((_) async {
      if (!mounted) {
        return;
      }
      await _sentencePlayer.play(
        sentences,
        isMounted: () => mounted,
        onSentence: (sentence) {
          if (mounted) {
            setState(() => _currentSpokenSentence = sentence);
          }
        },
      );
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

  @override
  Widget build(BuildContext context) {
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
                  _PlatformCheckBackground(
                    platforms: _platforms,
                    userName: _resolvedUserName,
                    bubbleText: _bubbleText,
                    isAccessibilityConnected: _isAccessibilityConnected,
                    automationLastMessage: _automationLastMessage,
                    lastDetectedPlatformLabel: _lastDetectedPlatformLabel,
                    isScanning: _isScanning,
                  ),
                  Align(
                    alignment: Alignment.bottomCenter,
                    child: SlideTransition(
                      position: _bannerOffset,
                      child: Column(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          // 캐릭터를 말풍선 옆이 아니라 하단 패널 쪽으로 옮겨
                          // 다른 화면들과 비율/배치를 통일했다.
                          Image.asset(
                            'assets/images/character/full/ddalangoo_searching.png',
                            height: 108,
                            fit: BoxFit.contain,
                          ),
                          const SizedBox(height: AppSpacing.sm),
                          _PlatformProgressBanner(
                            summary: _progressSummary,
                            detail: _progressDetail,
                            chipLabel: _progressChipLabel,
                            chipColor: _progressChipColor,
                          ),
                          const SizedBox(height: AppSpacing.sm),
                          EndConversationButton(
                            fullWidth: true,
                            variant: EndConversationButtonVariant.dark,
                            onPressed: _handleClosePressed,
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

class PlatformPreviewApp {
  const PlatformPreviewApp({
    required this.id,
    required this.name,
    required this.packageName,
    required this.assetPath,
    this.isInstalled = false,
  });

  final String id;
  final String name;
  final String packageName;
  final String assetPath;
  final bool isInstalled;

  PlatformPreviewApp copyWith({bool? isInstalled}) {
    return PlatformPreviewApp(
      id: id,
      name: name,
      packageName: packageName,
      assetPath: assetPath,
      isInstalled: isInstalled ?? this.isInstalled,
    );
  }
}

class _PlatformCheckBackground extends StatelessWidget {
  const _PlatformCheckBackground({
    required this.platforms,
    required this.userName,
    required this.bubbleText,
    required this.isAccessibilityConnected,
    required this.automationLastMessage,
    required this.lastDetectedPlatformLabel,
    required this.isScanning,
  });

  final List<PlatformPreviewApp> platforms;
  final String userName;
  final String bubbleText;
  final bool isAccessibilityConnected;
  final String? automationLastMessage;
  final String? lastDetectedPlatformLabel;
  final bool isScanning;

  @override
  Widget build(BuildContext context) {
    final responsive = context.responsive;

    return DecoratedBox(
      decoration: BoxDecoration(
        gradient: LinearGradient(
          begin: Alignment.topCenter,
          end: Alignment.bottomCenter,
          colors: [
            Colors.white,
            const Color(0xFFF9F2F6),
            const Color(0xFFF3F4F8),
          ],
        ),
      ),
      child: Padding(
        padding: EdgeInsets.only(
          // 하단 패널에 캐릭터 이미지가 추가되면서 패널 높이가 늘어난 만큼
          // 여백도 함께 늘려 배경 콘텐츠가 패널에 가리지 않게 한다.
          bottom: responsive.bound(
            responsive.heightScaled(268, minFactor: 0.72, maxFactor: 1.0),
            min: 220,
            max: 268,
          ),
        ),
        // 플랫폼 아이콘 개수가 많아 Wrap이 2줄 이상으로 넘어가면 고정 Column
        // 높이를 초과해 아래쪽이 오버플로우될 수 있었다(예: 후보 5개가 3+2로
        // 줄바꿈되는 경우). 전체를 스크롤 가능하게 바꿔 아이콘 개수와 무관하게
        // 항상 안전하게 표시되도록 한다.
        child: SingleChildScrollView(
          physics: const ClampingScrollPhysics(),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              const _MockStatusStrip(),
              const SizedBox(height: AppSpacing.lg),
              _MockSearchCard(userName: userName, bubbleText: bubbleText),
              const SizedBox(height: AppSpacing.lg),
              Wrap(
                spacing: AppSpacing.md,
                runSpacing: AppSpacing.md,
                children: [
                  for (final platform in platforms)
                    _PlatformTile(
                      name: platform.name,
                      assetPath: platform.assetPath,
                      isInstalled: platform.isInstalled,
                    ),
                ],
              ),
              const SizedBox(height: AppSpacing.xl),
              _RecentActivityCard(
                isAccessibilityConnected: isAccessibilityConnected,
                installedPlatformCount: platforms
                    .where((platform) => platform.isInstalled)
                    .length,
                automationLastMessage: automationLastMessage,
                lastDetectedPlatformLabel: lastDetectedPlatformLabel,
                isScanning: isScanning,
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _MockStatusStrip extends StatelessWidget {
  const _MockStatusStrip();

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        Text(
          '9:41',
          style: AppTextStyles.body2.copyWith(
            color: AppColors.textStrong,
            fontWeight: FontWeight.w800,
          ),
        ),
        const Spacer(),
        const Icon(Icons.signal_cellular_alt_rounded, size: 18),
        const SizedBox(width: AppSpacing.xs),
        const Icon(Icons.wifi_rounded, size: 18),
        const SizedBox(width: AppSpacing.xs),
        const Icon(Icons.battery_full_rounded, size: 18),
      ],
    );
  }
}

class _MockSearchCard extends StatelessWidget {
  const _MockSearchCard({required this.userName, required this.bubbleText});

  final String userName;
  final String bubbleText;

  @override
  Widget build(BuildContext context) {
    // 다른 대화형 화면(스몰토크/에이전트 인사/메인 쇼핑 흐름)과 같은
    // 말풍선(DialogueBubble)을 써서 딸랑구가 말하는 부분의 모양을 통일했다.
    // 캐릭터는 더 이상 이 말풍선 옆에 두지 않는다(다른 화면과 비율이 달라
    // 통일감이 떨어져서 하단 패널 쪽으로 옮겼다 — 아래 _PlatformCheckScreen
    // 참고). 텍스트도 고정 문구가 아니라 실제 TTS로 말하는 내용을 그대로
    // 보여줘서 화면과 음성이 항상 일치하게 했다.
    return DialogueBubble(
      text: bubbleText,
      contentKey: ValueKey(bubbleText),
      animateTextChanges: true,
      cyclePages: false,
      highlightedWords: [userName],
      minHeight: 96,
      style: AppTextStyles.title2.copyWith(
        fontSize: 22,
        color: AppColors.textStrong,
        fontWeight: FontWeight.w700,
      ),
      emphasizedStyle: AppTextStyles.title2.copyWith(
        fontSize: 22,
        color: AppColors.primaryPinkDark,
        fontWeight: FontWeight.w800,
      ),
    );
  }
}

class _PlatformTile extends StatelessWidget {
  const _PlatformTile({
    required this.name,
    required this.assetPath,
    required this.isInstalled,
  });

  final String name;
  final String assetPath;
  final bool isInstalled;

  @override
  Widget build(BuildContext context) {
    final responsive = context.responsive;
    final tileWidth = responsive.bound(
      responsive.widthScaled(96, minFactor: 0.82, maxFactor: 1.0),
      min: 82,
      max: 96,
    );
    final iconBoxSize = responsive.bound(
      responsive.scale(84, minFactor: 0.82, maxFactor: 1.0),
      min: 70,
      max: 84,
    );

    return SizedBox(
      width: tileWidth,
      child: Column(
        children: [
          Container(
            width: iconBoxSize,
            height: iconBoxSize,
            padding: const EdgeInsets.all(AppSpacing.sm),
            decoration: BoxDecoration(
              color: isInstalled ? Colors.white : AppColors.surfaceMuted,
              borderRadius: BorderRadius.circular(AppRadii.lg),
              border: Border.all(
                color: isInstalled ? AppColors.primaryPink : AppColors.border,
                width: isInstalled ? 1.5 : 1,
              ),
              boxShadow: const [
                BoxShadow(
                  color: AppColors.shadow,
                  blurRadius: 16,
                  offset: Offset(0, 8),
                ),
              ],
            ),
            child: Opacity(
              opacity: isInstalled ? 1 : 0.38,
              child: Image.asset(assetPath, fit: BoxFit.contain),
            ),
          ),
          const SizedBox(height: AppSpacing.sm),
          Text(
            name,
            maxLines: 2,
            textAlign: TextAlign.center,
            overflow: TextOverflow.ellipsis,
            style: AppTextStyles.body2.copyWith(
              color: isInstalled ? AppColors.textStrong : AppColors.textMuted,
              fontWeight: FontWeight.w700,
            ),
          ),
          const SizedBox(height: AppSpacing.xs),
          Text(
            isInstalled ? '확인됨' : '미설치',
            style: AppTextStyles.caption.copyWith(
              color: isInstalled
                  ? AppColors.primaryPinkDark
                  : AppColors.textMuted,
              fontWeight: FontWeight.w800,
            ),
          ),
        ],
      ),
    );
  }
}

class _RecentActivityCard extends StatelessWidget {
  const _RecentActivityCard({
    required this.isAccessibilityConnected,
    required this.installedPlatformCount,
    required this.automationLastMessage,
    required this.lastDetectedPlatformLabel,
    required this.isScanning,
  });

  final bool isAccessibilityConnected;
  final int installedPlatformCount;
  final String? automationLastMessage;
  final String? lastDetectedPlatformLabel;
  final bool isScanning;

  @override
  Widget build(BuildContext context) {
    // 이 카드는 이제 상위 SingleChildScrollView 안에 있어 높이가 무한대로
    // 열려 있다. 예전처럼 Expanded/LayoutBuilder(constraints.maxHeight)로
    // "남은 공간 채우기"를 시도하면 무한 높이 제약과 충돌하므로, 콘텐츠
    // 크기에 맞춰 자연스럽게 표시되도록 단순화한다.
    return Container(
      padding: const EdgeInsets.all(AppSpacing.lg),
      decoration: BoxDecoration(
        color: Colors.white.withValues(alpha: 0.94),
        borderRadius: BorderRadius.circular(AppRadii.xl),
        border: Border.all(color: AppColors.border),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: [
          Text(
            '확인 중인 항목',
            style: AppTextStyles.body1.copyWith(fontWeight: FontWeight.w800),
          ),
          const SizedBox(height: AppSpacing.md),
          _StatusRow(
            title: '설치된 쇼핑 앱',
            status: isScanning ? '확인 중' : '$installedPlatformCount개 확인',
            accentColor: isScanning
                ? AppColors.primaryPinkDark
                : (installedPlatformCount > 0
                      ? AppColors.success
                      : AppColors.textMuted),
          ),
          const SizedBox(height: AppSpacing.md),
          _StatusRow(
            title: '접근성 서비스',
            status: isAccessibilityConnected ? '연결됨' : '확인 필요',
            accentColor: isAccessibilityConnected
                ? AppColors.success
                : AppColors.primaryPinkDark,
          ),
          const SizedBox(height: AppSpacing.md),
          _StatusRow(
            title: '마지막 감지',
            status: lastDetectedPlatformLabel ?? '대기 중',
            accentColor: lastDetectedPlatformLabel == null
                ? AppColors.textMuted
                : AppColors.primaryPinkDark,
          ),
          const SizedBox(height: AppSpacing.md),
          Container(
            width: double.infinity,
            padding: const EdgeInsets.symmetric(
              horizontal: AppSpacing.md,
              vertical: AppSpacing.sm,
            ),
            decoration: BoxDecoration(
              color: AppColors.secondaryPink,
              borderRadius: BorderRadius.circular(AppRadii.md),
            ),
            child: Text(
              automationLastMessage ??
                  (isAccessibilityConnected
                      ? '설치된 플랫폼 확인이 끝나면 바로 다음 화면으로 넘어가요.'
                      : '접근성 서비스가 아직 연결되지 않았다면 이후 자동화 단계에서 켜주시면 돼요.'),
              style: AppTextStyles.body2.copyWith(
                color: AppColors.primaryPinkDark,
                fontWeight: FontWeight.w700,
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _StatusRow extends StatelessWidget {
  const _StatusRow({
    required this.title,
    required this.status,
    required this.accentColor,
  });

  final String title;
  final String status;
  final Color accentColor;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(
        horizontal: AppSpacing.md,
        vertical: AppSpacing.md,
      ),
      decoration: BoxDecoration(
        color: AppColors.surface,
        borderRadius: BorderRadius.circular(AppRadii.md),
      ),
      child: Row(
        children: [
          Expanded(
            child: Text(
              title,
              style: AppTextStyles.body2.copyWith(
                color: AppColors.textStrong,
                fontWeight: FontWeight.w700,
              ),
            ),
          ),
          Container(
            padding: const EdgeInsets.symmetric(
              horizontal: AppSpacing.sm,
              vertical: AppSpacing.xs,
            ),
            decoration: BoxDecoration(
              color: accentColor.withValues(alpha: 0.12),
              borderRadius: BorderRadius.circular(AppRadii.pill),
            ),
            child: Text(
              status,
              style: AppTextStyles.caption.copyWith(
                color: accentColor,
                fontWeight: FontWeight.w800,
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _PlatformProgressBanner extends StatelessWidget {
  const _PlatformProgressBanner({
    required this.summary,
    required this.detail,
    required this.chipLabel,
    required this.chipColor,
  });

  final String summary;
  final String detail;
  final String chipLabel;
  final Color chipColor;

  @override
  Widget build(BuildContext context) {
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
            child: Icon(
              Icons.manage_search_rounded,
              color: chipColor,
              size: 24,
            ),
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
                        chipLabel,
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
                  summary,
                  style: AppTextStyles.body2.copyWith(
                    color: AppColors.textStrong,
                    fontWeight: FontWeight.w800,
                    height: 1.35,
                  ),
                ),
                const SizedBox(height: AppSpacing.xxs),
                Text(
                  detail,
                  style: AppTextStyles.caption.copyWith(
                    color: AppColors.textSecondary,
                    fontWeight: FontWeight.w600,
                    height: 1.35,
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
