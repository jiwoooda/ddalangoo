import 'dart:async';

import 'package:flutter/material.dart';

import '../../../app/routes.dart';
import '../../../app/theme/app_colors.dart';
import '../../../app/theme/app_radii.dart';
import '../../../app/theme/app_spacing.dart';
import '../../../app/theme/app_text_styles.dart';
import '../../../core/services/accessibility_automation_service.dart';
import '../../../shared/layout/app_layout.dart';
import '../../../shared/layout/layout_presets.dart';
import '../../../shared/widgets/bottom_status_banner.dart';
import '../../../shared/widgets/end_conversation_button.dart';
import '../services/platform_check_service.dart';

class PlatformCheckScreen extends StatefulWidget {
  const PlatformCheckScreen({
    super.key,
    this.userName,
    this.onClosePressed,
    this.onCompleted,
    this.autoCompleteAfter = const Duration(milliseconds: 2200),
    this.nextRouteName = AppRoutes.purchaseHistoryLoading,
    this.supportedPlatforms = _defaultPlatforms,
  });

  final String? userName;
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
      assetPath: 'assets/images/naver.png',
    ),
    PlatformPreviewApp(
      id: 'coupang',
      name: '쿠팡',
      packageName: 'com.coupang.mobile',
      assetPath: 'assets/images/coupang.png',
    ),
    PlatformPreviewApp(
      id: 'kurly',
      name: '컬리',
      packageName: 'com.dbs.kurly.m2',
      assetPath: 'assets/images/kurly.png',
    ),
    PlatformPreviewApp(
      id: 'gmarket',
      name: '지마켓',
      packageName: 'com.ebay.kr.gmarket',
      assetPath: 'assets/images/gmarket.png',
    ),
    PlatformPreviewApp(
      id: 'hyundaihomeshopping',
      name: '현대홈쇼핑',
      packageName: 'com.hmallapp',
      assetPath: 'assets/images/hyundaihomeshopping.png',
    ),
  ];

  @override
  State<PlatformCheckScreen> createState() => _PlatformCheckScreenState();
}

class _PlatformCheckScreenState extends State<PlatformCheckScreen>
    with SingleTickerProviderStateMixin {
  final PlatformCheckService _platformCheckService = PlatformCheckService();

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
  bool _isAccessibilityConnected = false;
  bool _isScanning = true;
  bool _didScheduleCompletion = false;

  String get _resolvedUserName {
    final trimmed = _resolvedUserNameValue?.trim() ?? widget.userName?.trim();
    return trimmed == null || trimmed.isEmpty ? '고객' : trimmed;
  }

  @override
  void initState() {
    super.initState();
    _startedAt = DateTime.now();
    _controller.forward();
    unawaited(_loadPlatformCheckData());
    _startStatusPolling();
  }

  @override
  void dispose() {
    _statusPollTimer?.cancel();
    _completionTimer?.cancel();
    _controller.dispose();
    super.dispose();
  }

  void _handleClosePressed() {
    _statusPollTimer?.cancel();
    _completionTimer?.cancel();

    if (widget.onClosePressed != null) {
      widget.onClosePressed!();
      return;
    }

    Navigator.of(
      context,
    ).pushNamedAndRemoveUntil(AppRoutes.home, (route) => false);
  }

  void _handleCompleted() {
    if (!mounted) {
      return;
    }

    if (widget.onCompleted != null) {
      widget.onCompleted!();
      return;
    }

    Navigator.of(context).pushReplacementNamed(widget.nextRouteName);
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
      _isScanning = false;
      _statusHint = installedCount > 0
          ? '$installedCount개의 쇼핑 앱을 확인했어요.'
          : '확인된 쇼핑 앱이 없어요.';
    });

    _scheduleCompletionWithMinimumDisplay();
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

    setState(() {
      _isAccessibilityConnected = serviceConnected;
      _automationLastMessage = lastMessage == null || lastMessage.isEmpty
          ? null
          : lastMessage;
      _lastDetectedPlatformLabel = _labelForPackageName(lastPackageName);
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

    final elapsed = DateTime.now().difference(startedAt);
    final remaining = minimumDisplayDuration - elapsed;
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
                    statusHint: _statusHint,
                    isAccessibilityConnected: _isAccessibilityConnected,
                    automationLastMessage: _automationLastMessage,
                    lastDetectedPlatformLabel: _lastDetectedPlatformLabel,
                    isScanning: _isScanning,
                  ),
                  Positioned(
                    top: 0,
                    right: 0,
                    child: EndConversationButton(
                      compact: true,
                      onPressed: _handleClosePressed,
                    ),
                  ),
                  Align(
                    alignment: Alignment.bottomCenter,
                    child: SlideTransition(
                      position: _bannerOffset,
                      child: BottomStatusBanner(
                        characterAssetPath: 'assets/images/ddalangoo_top.png',
                        message: '$_resolvedUserName님이 사용중인 쇼핑 플랫폼을\n확인하고 있어요!',
                        messageStyle: AppTextStyles.body1.copyWith(
                          color: AppColors.textStrong,
                          fontWeight: FontWeight.w800,
                          height: 1.4,
                        ),
                        padding: const EdgeInsets.fromLTRB(
                          AppSpacing.md,
                          AppSpacing.md,
                          AppSpacing.md,
                          AppSpacing.md,
                        ),
                        avatarSize: 56,
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
    required this.statusHint,
    required this.isAccessibilityConnected,
    required this.automationLastMessage,
    required this.lastDetectedPlatformLabel,
    required this.isScanning,
  });

  final List<PlatformPreviewApp> platforms;
  final String userName;
  final String statusHint;
  final bool isAccessibilityConnected;
  final String? automationLastMessage;
  final String? lastDetectedPlatformLabel;
  final bool isScanning;

  @override
  Widget build(BuildContext context) {
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
        padding: const EdgeInsets.only(bottom: 148),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            const _MockStatusStrip(),
            const SizedBox(height: AppSpacing.lg),
            _MockSearchCard(userName: userName, statusHint: statusHint),
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
  const _MockSearchCard({required this.userName, required this.statusHint});

  final String userName;
  final String statusHint;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(AppSpacing.lg),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(AppRadii.xl),
        border: Border.all(color: AppColors.border),
        boxShadow: const [
          BoxShadow(
            color: AppColors.shadow,
            blurRadius: 18,
            offset: Offset(0, 10),
          ),
        ],
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            '$userName님, 어떤 쇼핑 앱을 쓰시는지 확인할게요',
            style: AppTextStyles.title2.copyWith(fontSize: 22),
          ),
          const SizedBox(height: AppSpacing.sm),
          Text(
            statusHint,
            style: AppTextStyles.body2.copyWith(color: AppColors.textSecondary),
          ),
        ],
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
    return SizedBox(
      width: 96,
      child: Column(
        children: [
          Container(
            width: 84,
            height: 84,
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
    return Expanded(
      child: Container(
        padding: const EdgeInsets.all(AppSpacing.lg),
        decoration: BoxDecoration(
          color: Colors.white.withValues(alpha: 0.94),
          borderRadius: BorderRadius.circular(AppRadii.xl),
          border: Border.all(color: AppColors.border),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
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
            const Spacer(),
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
