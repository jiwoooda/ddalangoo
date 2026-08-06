import 'package:shared_preferences/shared_preferences.dart';

abstract final class LocalStorage {
  static const String _userIdKey = 'user_id';
  static const String _userNameKey = 'user_name';

  static Future<void> saveUserId(int userId) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setInt(_userIdKey, userId);
  }

  static Future<int?> getUserId() async {
    final prefs = await SharedPreferences.getInstance();
    return prefs.getInt(_userIdKey);
  }

  static Future<void> saveUserName(String userName) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_userNameKey, userName);
  }

  static Future<String?> getUserName() async {
    final prefs = await SharedPreferences.getInstance();
    return prefs.getString(_userNameKey);
  }

  static Future<void> clearUserId() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove(_userIdKey);
  }

  static Future<void> clearUserName() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove(_userNameKey);
  }

  static Future<void> clearSession() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove(_userIdKey);
    await prefs.remove(_userNameKey);
  }

  static Future<bool> isLoggedIn() async {
    final userId = await getUserId();
    return userId != null;
  }
}
