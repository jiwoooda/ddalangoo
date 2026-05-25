// userId 저장/불러오기용

import 'package:shared_preferences/shared_preferences.dart';

class LocalStorage {
  static const String _userIdKey = 'user_id';
  static const int _demoUserId = 1;

  // userId 저장 (로그인/회원가입 후)
  static Future<void> saveUserId(int userId) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setInt(_userIdKey, userId);
  }

  // userId 불러오기
  static Future<int?> getUserId() async {
    final prefs = await SharedPreferences.getInstance();
    return prefs.getInt(_userIdKey);
  }

  // userId 삭제 (로그아웃)
  static Future<void> clearUserId() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove(_userIdKey);
  }

  // 로그인 API가 준비되기 전, 데모 유저 ID를 고정 저장
  static Future<void> saveDemoUserId() async {
    await saveUserId(_demoUserId);
  }

  // 로그인 여부 확인
  static Future<bool> isLoggedIn() async {
    final userId = await getUserId();
    return userId != null;
  }
}
