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
    this.reason,
  });

  final bool canAutomate;
  final String? platform;
  final String? displayName;
  final String? reason;
}

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

  PurchaseHistoryAutomationPlan createAutomationPlan(
    List<InstalledShoppingPlatform> platforms,
  ) {
    final kurlyInstalled = platforms.any(
      (platform) => platform.platform == 'kurly' && platform.isInstalled,
    );

    if (kurlyInstalled) {
      return const PurchaseHistoryAutomationPlan(
        canAutomate: true,
        platform: 'kurly',
        displayName: '컬리',
      );
    }

    final installedCount = platforms
        .where((platform) => platform.isInstalled)
        .length;
    if (installedCount > 0) {
      return const PurchaseHistoryAutomationPlan(
        canAutomate: false,
        reason: '현재는 컬리 구매이력 자동 불러오기만 우선 연결되어 있어요.',
      );
    }

    return const PurchaseHistoryAutomationPlan(
      canAutomate: false,
      reason: '확인된 쇼핑 앱이 없어 저장된 구매이력만 불러오고 있어요.',
    );
  }

  Future<Map<String, dynamic>> getAutomationStatus() {
    return _automationService.getAutomationStatus();
  }

  Future<void> prepareForExtraction() async {
    await _automationService.clearAutomationTask();
    await _automationService.clearPurchaseHistoryResult();
  }

  Future<void> startExtraction(PurchaseHistoryAutomationPlan plan) async {
    if (!plan.canAutomate || plan.platform == null) {
      return;
    }

    switch (plan.platform) {
      case 'kurly':
        await _automationService.startKurlyPurchaseHistoryExtraction();
        return;
      default:
        throw UnsupportedError(
          'Unsupported purchase history automation platform: ${plan.platform}',
        );
    }
  }

  Future<List<AccessibilityPurchaseHistoryItem>> getAccumulatedItems() async {
    final rawJson = await _automationService
        .getAccumulatedPurchaseHistoryResult();
    return AccessibilityPurchaseHistoryItem.expandedListFromJsonString(rawJson);
  }

  Future<AccessibilityPurchaseHistoryImportResponse>
  importAccumulatedPurchaseHistory() async {
    final response = await _automationService
        .importAccumulatedPurchaseHistory();
    return AccessibilityPurchaseHistoryImportResponse.fromJson(response);
  }

  Future<PurchaseHistoryListResponse> fetchUserHistories({
    required int userId,
    int limit = 8,
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
