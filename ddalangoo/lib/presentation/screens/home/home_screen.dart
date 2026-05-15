// 홈 화면
import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import '../../../core/storage/local_storage.dart';
import '../../../data/repositories/agent_repository.dart';

class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key});

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  final UserRepository _userRepository = UserRepository();
  String _userName = '';

  @override
  void initState() {
    super.initState();
    _loadUser();
  }

  Future<void> _loadUser() async {
    final userId = await LocalStorage.getUserId();
    if (userId == null) return;
    try {
      final user = await _userRepository.getUser(userId);
      setState(() => _userName = user.name);
    } catch (e) {
      // 유저 정보 로드 실패 시 무시
    }
  }

  Future<void> _logout() async {
    await LocalStorage.clearUserId();
    if (!mounted) return;
    context.go('/login');
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFFFDF0F3),
      body: SafeArea(
        child: Column(
          children: [
            // 상단 로그아웃 버튼
            Align(
              alignment: Alignment.topRight,
              child: TextButton(
                onPressed: _logout,
                child: const Text(
                  '로그아웃',
                  style: TextStyle(color: Color(0xFF888888)),
                ),
              ),
            ),

            // 가운데 콘텐츠
            Expanded(
              child: Column(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  // 딸랑구 캐릭터
                  const Text('👧🏻', style: TextStyle(fontSize: 100)),
                  const SizedBox(height: 24),

                  // 딸랑구 이름
                  const Text(
                    '딸랑구',
                    style: TextStyle(
                      fontSize: 32,
                      fontWeight: FontWeight.bold,
                      color: Color(0xFFE8325A),
                    ),
                  ),
                  const SizedBox(height: 12),

                  // 안내 문구
                  Text(
                    _userName.isEmpty
                        ? '딸랑구와 전화 한통으로 원하는 걸 구매해요!'
                        : '$_userName님, 딸랑구와 전화 한통으로\n원하는 걸 구매해요!',
                    textAlign: TextAlign.center,
                    style: const TextStyle(
                      fontSize: 16,
                      color: Color(0xFF555555),
                    ),
                  ),
                  const SizedBox(height: 8),

                  const Text(
                    '화면 하단의 초록색 전화 버튼을 눌러 딸랑구를 호출하세요!',
                    style: TextStyle(fontSize: 14, color: Color(0xFFE8325A)),
                  ),
                ],
              ),
            ),

            // 하단 전화 걸기 버튼
            Padding(
              padding: const EdgeInsets.only(bottom: 60),
              child: Column(
                children: [
                  GestureDetector(
                    onTap: () => context.go('/call'),
                    child: Container(
                      width: 72,
                      height: 72,
                      decoration: const BoxDecoration(
                        color: Color(0xFF4CAF50),
                        shape: BoxShape.circle,
                      ),
                      child: const Icon(
                        Icons.call,
                        color: Colors.white,
                        size: 32,
                      ),
                    ),
                  ),
                  const SizedBox(height: 8),
                  const Text(
                    '전화 걸기',
                    style: TextStyle(fontSize: 14, color: Color(0xFF555555)),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}
