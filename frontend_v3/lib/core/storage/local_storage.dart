import 'package:shared_preferences/shared_preferences.dart';

abstract final class LocalStorage {
  static const String _userIdKey = 'user_id';

  static Future<void> saveUserId(int userId) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setInt(_userIdKey, userId);
  }

  static Future<int?> getUserId() async {
    final prefs = await SharedPreferences.getInstance();
    return prefs.getInt(_userIdKey);
  }

  static Future<void> clearUserId() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove(_userIdKey);
  }

  static Future<bool> isLoggedIn() async {
    final userId = await getUserId();
    return userId != null;
  }
}
