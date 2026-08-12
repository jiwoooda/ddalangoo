import 'package:flutter/foundation.dart';
import 'package:flutter_dotenv/flutter_dotenv.dart';

import '../../../core/services/accessibility_automation_service.dart';
import '../../../core/storage/local_storage.dart';
import '../../../data/repositories/agent_repository.dart';

class PlatformCheckService {
  PlatformCheckService({
    AccessibilityAutomationService? automationService,
    UserRepository? userRepository,
  }) : _automationService =
           automationService ?? AccessibilityAutomationService.instance,
       _userRepository = userRepository ?? UserRepository();

  final AccessibilityAutomationService _automationService;
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
        '[PlatformCheckService] failed to resolve user name: $error\n$stackTrace',
      );
      return null;
    }
  }

  Future<List<InstalledShoppingPlatform>> getInstalledPlatforms() async {
    return _automationService.getInstalledShoppingPlatforms();
  }

  Future<Map<String, dynamic>> getAutomationStatus() async {
    return _automationService.getAutomationStatus();
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
