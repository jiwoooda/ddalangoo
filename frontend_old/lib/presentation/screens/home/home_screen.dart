// 홈 화면
import 'dart:async';

import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import '../../../core/services/gpt_voice_service.dart';
import '../../../core/storage/local_storage.dart';
import '../../../data/repositories/agent_repository.dart';

class HomeScreen extends StatefulWidget {
  const HomeScreen({
    super.key,
    this.previewUserName,
    this.enableDataLoad = true,
    this.enableVoiceIntro = true,
  });

  final String? previewUserName;
  final bool enableDataLoad;
  final bool enableVoiceIntro;

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  final UserRepository _userRepository = UserRepository();
  final GptVoiceService _voiceService = GptVoiceService.instance;
  String _userName = '';
  bool _isCallHovered = false;
  bool _isLogoutHovered = false;
  bool _hasPlayedHomeIntro = false;
  bool _keepSpeakingOnDispose = false;

  @override
  void initState() {
    super.initState();
    if (widget.previewUserName != null) {
      _userName = widget.previewUserName!;
    }
    if (widget.enableDataLoad) {
      _loadUser();
    } else if (widget.enableVoiceIntro) {
      _playHomeIntroIfNeeded();
    }
  }

  Future<void> _loadUser() async {
    final userId = await LocalStorage.getUserId();
    if (userId == null) {
      _playHomeIntroIfNeeded();
      return;
    }
    try {
      final user = await _userRepository.getUser(userId);
      if (!mounted) return;
      setState(() => _userName = user.name);
    } catch (e) {
      // 유저 정보 로드 실패 시 무시
    } finally {
      _playHomeIntroIfNeeded();
    }
  }

  Future<void> _logout() async {
    if (!widget.enableDataLoad) return;
    await _voiceService.stopSpeaking();
    await LocalStorage.clearUserId();
    if (!mounted) return;
    context.go('/login');
  }

  void _setCallHovered(bool value) {
    if (_isCallHovered == value) return;
    setState(() => _isCallHovered = value);
  }

  void _setLogoutHovered(bool value) {
    if (_isLogoutHovered == value) return;
    setState(() => _isLogoutHovered = value);
  }

  String get _homeIntroText => _userName.isEmpty
      ? '딸랑구와 전화 한통으로 원하는 걸 구매해요! 화면 하단의 초록색 전화 버튼을 눌러 딸랑구를 호출하세요!'
      : '$_userName님, 딸랑구와 전화 한통으로 원하는 걸 구매해요! 화면 하단의 초록색 전화 버튼을 눌러 딸랑구를 호출하세요!';

  String get _callGreetingText =>
      _userName.isEmpty ? '무엇을 구매하고 싶으신가요?' : '$_userName님, 무엇을 구매하고 싶으신가요?';

  void _warmScreenTtsPhrases() {
    unawaited(
      _voiceService.prefetchMultiple([
        _homeIntroText,
        _callGreetingText,
        '딸랑구를 연결하고 있어요. 잠시만 기다려주세요.',
      ]),
    );
  }

  void _playHomeIntroIfNeeded() {
    if (!mounted || _hasPlayedHomeIntro || !widget.enableVoiceIntro) return;
    _hasPlayedHomeIntro = true;
    _warmScreenTtsPhrases();
    unawaited(_speakWithoutBlockingNavigation(_homeIntroText));
  }

  Future<void> _handleCallTap() async {
    if (!widget.enableDataLoad) return;
    _keepSpeakingOnDispose = true;
    await _voiceService.stopSpeaking();
    await _speakWithoutBlockingNavigation('딸랑구를 연결하고 있어요. 잠시만 기다려주세요.');
    if (!mounted) return;
    context.go('/call');
  }

  Future<void> _speakWithoutBlockingNavigation(String text) async {
    try {
      await _voiceService.speak(text);
    } catch (e) {
      debugPrint('🔇 [Home TTS Fallback] $e');
    }
  }

  @override
  void dispose() {
    if (!_keepSpeakingOnDispose) {
      unawaited(_voiceService.stopSpeaking());
    }
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFFFDF0F3),
      body: SafeArea(
        child: Column(
          children: [
            // 가운데 콘텐츠
            Expanded(
              child: LayoutBuilder(
                builder: (context, constraints) {
                  final logoImageHeight = constraints.maxHeight < 430
                      ? 190.0
                      : 300.0;
                  final logoTextHeight = constraints.maxHeight < 430
                      ? 56.0
                      : 80.0;

                  return SingleChildScrollView(
                    padding: const EdgeInsets.symmetric(horizontal: 20),
                    child: ConstrainedBox(
                      constraints: BoxConstraints(
                        minHeight: constraints.maxHeight,
                      ),
                      child: Column(
                        mainAxisAlignment: MainAxisAlignment.center,
                        children: [
                          Image.asset(
                            'assets/images/ddalangoo_logo_image.png',
                            height: logoImageHeight,
                            fit: BoxFit.contain,
                          ),
                          const SizedBox(height: 20),

                          Image.asset(
                            'assets/images/ddalangoo_logo_text.png',
                            height: logoTextHeight,
                            fit: BoxFit.contain,
                          ),
                          const SizedBox(height: 12),

                          // 화면 높이가 낮은 macOS 창에서도 문구가 잘리지 않도록 스크롤 영역 안에 둔다.
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
                            textAlign: TextAlign.center,
                            style: TextStyle(
                              fontSize: 14,
                              color: Color(0xFFE8325A),
                            ),
                          ),
                        ],
                      ),
                    ),
                  );
                },
              ),
            ),

            // 하단 전화 걸기 버튼
            Padding(
              padding: const EdgeInsets.fromLTRB(20, 0, 20, 28),
              child: Column(
                children: [
                  MouseRegion(
                    cursor: SystemMouseCursors.click,
                    onEnter: (_) => _setCallHovered(true),
                    onExit: (_) => _setCallHovered(false),
                    child: GestureDetector(
                      onTap: _handleCallTap,
                      child: Container(
                        width: 78,
                        height: 78,
                        decoration: BoxDecoration(
                          color: _isCallHovered
                              ? const Color(0xFF43A047)
                              : const Color(0xFF4CAF50),
                          shape: BoxShape.circle,
                          boxShadow: _isCallHovered
                              ? [
                                  BoxShadow(
                                    color: const Color(
                                      0xFF4CAF50,
                                    ).withValues(alpha: 0.24),
                                    blurRadius: 14,
                                    spreadRadius: 1,
                                  ),
                                ]
                              : null,
                        ),
                        child: const Icon(
                          Icons.call,
                          color: Colors.white,
                          size: 32,
                        ),
                      ),
                    ),
                  ),
                  const SizedBox(height: 8),
                  const Text(
                    '전화 걸기',
                    style: TextStyle(fontSize: 14, color: Color(0xFF555555)),
                  ),
                  const SizedBox(height: 18),
                  MouseRegion(
                    cursor: SystemMouseCursors.click,
                    onEnter: (_) => _setLogoutHovered(true),
                    onExit: (_) => _setLogoutHovered(false),
                    child: GestureDetector(
                      onTap: _logout,
                      child: Container(
                        width: double.infinity,
                        height: 58,
                        decoration: BoxDecoration(
                          color: _isLogoutHovered
                              ? const Color(0xFFE8325A)
                              : const Color(0xFFD9D9D9),
                          borderRadius: BorderRadius.circular(22),
                          boxShadow: _isLogoutHovered
                              ? [
                                  BoxShadow(
                                    color: const Color(
                                      0xFFE8325A,
                                    ).withValues(alpha: 0.22),
                                    blurRadius: 16,
                                    offset: const Offset(0, 8),
                                  ),
                                ]
                              : null,
                        ),
                        child: Row(
                          mainAxisAlignment: MainAxisAlignment.center,
                          children: [
                            Icon(
                              Icons.logout,
                              color: _isLogoutHovered
                                  ? Colors.white
                                  : const Color(0xFF666666),
                              size: 22,
                            ),
                            const SizedBox(width: 10),
                            Text(
                              '로그아웃',
                              style: TextStyle(
                                fontSize: 17,
                                fontWeight: FontWeight.w700,
                                color: _isLogoutHovered
                                    ? Colors.white
                                    : const Color(0xFF666666),
                              ),
                            ),
                          ],
                        ),
                      ),
                    ),
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
