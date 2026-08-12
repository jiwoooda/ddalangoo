import 'package:flutter/foundation.dart';
import 'package:flutter_dotenv/flutter_dotenv.dart';

import '../../../core/services/accessibility_automation_service.dart';
import '../../../core/storage/local_storage.dart';
import '../../../data/models/accessibility_purchase_history_model.dart';
import '../../../data/models/purchase_history_model.dart';
import '../../../data/repositories/agent_repository.dart';
import '../../../data/repositories/purchase_history_repository.dart';

class PurchaseHistoryAutomationPlan {
  const PurchaseHistoryAutomationPlan({
    required this.canAutomate,
    this.platform,
    this.displayName,
    this.packageName,
    this.startStep,
    this.reason,
  });

  final bool canAutomate;
  final String? platform;
  final String? displayName;
  final String? packageName;
  final String? startStep;
  final String? reason;
}

class _PurchaseHistoryAutomationDefinition {
  const _PurchaseHistoryAutomationDefinition({
    required this.platform,
    required this.displayName,
    required this.packageName,
    required this.startStep,
  });

  final String platform;
  final String displayName;
  final String packageName;
  final String startStep;
}

const _supportedPurchaseHistoryAutomations =
    <String, _PurchaseHistoryAutomationDefinition>{
      'kurly': _PurchaseHistoryAutomationDefinition(
        platform: 'kurly',
        displayName: '컬리',
        packageName: 'com.dbs.kurly.m2',
        startStep: AccessibilityAutomationStep.openMyKurly,
      ),
      'coupang': _PurchaseHistoryAutomationDefinition(
        platform: 'coupang',
        displayName: '쿠팡',
        packageName: 'com.coupang.mobile',
        startStep: AccessibilityAutomationStep.openMyCoupang,
      ),
    };

class PurchaseHistoryLoadingService {
  PurchaseHistoryLoadingService({
    AccessibilityAutomationService? automationService,
    PurchaseHistoryRepository? purchaseHistoryRepository,
    UserRepository? userRepository,
  }) : _automationService =
           automationService ?? AccessibilityAutomationService.instance,
       _purchaseHistoryRepository =
           purchaseHistoryRepository ?? PurchaseHistoryRepository(),
       _userRepository = userRepository ?? UserRepository();

  final AccessibilityAutomationService _automationService;
  final PurchaseHistoryRepository _purchaseHistoryRepository;
  final UserRepository _userRepository;

  // 앱 복귀 과정에서 PurchaseHistoryLoadingScreen이 다시 생성되어도
  // 같은 세션 안에서는 구매이력 자동화를 중복 실행하지 않기 위한 가드다.
  static bool _completedAutomationFlowThisSession = false;

  bool get hasCompletedAutomationFlowThisSession =>
      _completedAutomationFlowThisSession;

  void markCompletedAutomationFlowThisSession() {
    _completedAutomationFlowThisSession = true;
  }

  Future<int> resolveUserId() async {
    final overriddenUserId = _resolveDevUserIdOverride();
    if (overriddenUserId != null) {
      await LocalStorage.saveUserId(overriddenUserId);
      return overriddenUserId;
    }

    return await LocalStorage.getUserId() ?? 1;
  }

  Future<String?> resolveUserName({int? userId}) async {
    final effectiveUserId = userId ?? await resolveUserId();
    try {
      final user = await _userRepository.getUser(effectiveUserId);
      final name = user.name.trim();
      return name.isEmpty ? null : name;
    } catch (error, stackTrace) {
      debugPrint(
        '[PurchaseHistoryLoadingService] failed to resolve user name: '
        '$error\n$stackTrace',
      );
      return null;
    }
  }

  Future<List<InstalledShoppingPlatform>> getInstalledPlatforms() {
    return _automationService.getInstalledShoppingPlatforms();
  }

  List<PurchaseHistoryAutomationPlan> createAutomationPlans(
    List<InstalledShoppingPlatform> platforms,
  ) {
    final plans = <PurchaseHistoryAutomationPlan>[];

    for (final installedPlatform in platforms) {
      if (!installedPlatform.isInstalled) {
        continue;
      }

      final platformKey = installedPlatform.platform.toLowerCase();
      final automation = _supportedPurchaseHistoryAutomations[platformKey];
      if (automation == null) {
        debugPrint(
          '[PurchaseHistoryLoadingService] skip unsupported purchase history '
          'automation platform=$platformKey '
          'displayName=${installedPlatform.displayName}',
        );
        continue;
      }

      plans.add(
        PurchaseHistoryAutomationPlan(
          canAutomate: true,
          platform: automation.platform,
          displayName: automation.displayName,
          packageName: automation.packageName,
          startStep: automation.startStep,
        ),
      );
    }

    return plans;
  }

  List<String> unsupportedInstalledPlatformNames(
    List<InstalledShoppingPlatform> platforms,
  ) {
    return platforms
        .where((platform) => platform.isInstalled)
        .where(
          (platform) => !_supportedPurchaseHistoryAutomations.containsKey(
            platform.platform.toLowerCase(),
          ),
        )
        .map((platform) => platform.displayName)
        .where((name) => name.trim().isNotEmpty)
        .toList(growable: false);
  }

  String? skippedAutomationMessage(List<InstalledShoppingPlatform> platforms) {
    final unsupportedNames = unsupportedInstalledPlatformNames(platforms);
    if (unsupportedNames.isEmpty) {
      return null;
    }

    return '${unsupportedNames.join(', ')}는 아직 구매이력 자동화가 준비되지 않아 이번 수집에서 제외했어요.';
  }

  String? unsupportedAutomationReason(List<InstalledShoppingPlatform> platforms) {
    final installedPlatforms = platforms
        .where((platform) => platform.isInstalled)
        .map((platform) => platform.displayName)
        .where((name) => name.trim().isNotEmpty)
        .toList(growable: false);
    if (installedPlatforms.isEmpty) {
      return '확인된 쇼핑 앱이 없어 저장된 구매이력만 불러오고 있어요.';
    }

    return '현재는 컬리와 쿠팡 구매이력 자동 불러오기를 우선 확인하고 있어요.';
  }

  Future<Map<String, dynamic>> getAutomationStatus() {
    return _automationService.getAutomationStatus();
  }

  Future<bool> returnToDdalangooApp() {
    return _automationService.returnToDdalangooApp();
  }

  Future<void> prepareForExtraction() async {
    await _automationService.clearAutomationTask();
    await _automationService.clearPurchaseHistoryResult();
  }

  Future<void> startExtraction(PurchaseHistoryAutomationPlan plan) async {
    if (!plan.canAutomate || plan.platform == null) {
      return;
    }

    await _automationService.startPurchaseHistoryExtraction(
      platform: plan.platform!,
      displayName: plan.displayName ?? plan.platform!,
      packageName: plan.packageName,
      startStep: plan.startStep,
      targetHistoryCount: 30,
    );
  }

  Future<void> startCoupangPurchaseHistoryDumpInspection() {
    return _automationService.startCoupangPurchaseHistoryDumpInspection();
  }

  Future<void> startCoupangPurchaseHistoryCollectionFromCurrentScreen({
    int targetHistoryCount = 30,
  }) {
    return _automationService
        .startCoupangPurchaseHistoryExtractionFromCurrentScreen(
          targetHistoryCount: targetHistoryCount,
        );
  }

  Future<List<AccessibilityPurchaseHistoryItem>> getAccumulatedItems() async {
    final rawJson = await _automationService
        .getAccumulatedPurchaseHistoryResult();
    return AccessibilityPurchaseHistoryItem.expandedListFromJsonString(rawJson);
  }

  Future<String> getAccumulatedPurchaseHistoryResult() {
    return _automationService.getAccumulatedPurchaseHistoryResult();
  }

  Future<AccessibilityPurchaseHistoryImportResponse>
  importAccumulatedPurchaseHistory() async {
    final response = await _automationService
        .importAccumulatedPurchaseHistory();
    return AccessibilityPurchaseHistoryImportResponse.fromJson(response);
  }

  Future<PurchaseHistoryListResponse> fetchUserHistories({
    required int userId,
    int? limit,
  }) {
    return _purchaseHistoryRepository.getUserHistories(
      userId: userId,
      limit: limit,
    );
  }

  int? _resolveDevUserIdOverride() {
    try {
      final raw = dotenv.env['SHOPPING_DEV_USER_ID']?.trim();
      if (raw == null || raw.isEmpty) {
        return null;
      }
      return int.tryParse(raw);
    } catch (_) {
      return null;
    }
  }
}
