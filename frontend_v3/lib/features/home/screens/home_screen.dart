import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';

import '../../../app/routes.dart';
import '../../../app/theme/app_colors.dart';
import '../../../app/theme/app_radii.dart';
import '../../../app/theme/app_spacing.dart';
import '../../../app/theme/app_surface_styles.dart';
import '../../../app/theme/app_text_styles.dart';
import '../../../core/services/voice_service.dart';
import '../../../core/storage/local_storage.dart';
import '../../../data/repositories/agent_repository.dart';
import '../../../shared/layout/layout_presets.dart';
import '../../../shared/layout/screen_frame.dart';
import '../../../shared/layout/app_responsive.dart';
import '../../../shared/widgets/dialogue_bubble.dart';
import '../../../shared/widgets/primary_button.dart';
import '../../shopping/screens/shopping_flow_screen.dart';

class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key});

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  final UserRepository _userRepository = UserRepository();
  final VoiceService _voiceService = VoiceService.instance;
  static const Color _temporaryDebugColor = Color(0xFF1E9E4A);

  String? _userName;
  Future<void> _speechQueue = Future<void>.value();
  int _speechRunId = 0;

  @override
  void initState() {
    super.initState();
    unawaited(_loadHomeDataAndSpeakGreeting());
  }

  @override
  void dispose() {
    _speechRunId += 1;
    unawaited(_voiceService.stopSpeaking());
    super.dispose();
  }

  Future<void> _loadHomeDataAndSpeakGreeting() async {
    await _loadHomeData();
    if (!mounted) {
      return;
    }
    unawaited(_speakGreetingSentences());
  }

  Future<void> _loadHomeData() async {
    try {
      final cachedUserName = await LocalStorage.getUserName();
      if (mounted &&
          cachedUserName != null &&
          cachedUserName.trim().isNotEmpty) {
        setState(() {
          _userName = cachedUserName.trim();
        });
      }

      final userId = await LocalStorage.getUserId();
      if (userId == null) {
        return;
      }

      final results = await Future.wait<Object>([
        _userRepository.getUser(userId),
      ]);
      if (!mounted) {
        return;
      }

      final user = results[0] as dynamic;
      setState(() {
        _userName = user.name as String?;
      });
    } catch (_) {
      // Home data is best-effort; keep the default greeting on failure.
    }
  }

  Future<void> _logout() async {
    await LocalStorage.clearSession();
    if (!mounted) {
      return;
    }
    Navigator.of(
      context,
    ).pushNamedAndRemoveUntil(AppRoutes.login, (route) => false);
  }

  // 말풍선 문구를 한 문장씩 순서대로 보여준다. DialogueBubble의
  // cyclePages 기능과 같은 기준('\n')으로 TTS도 한 문장씩 백엔드에 보내서,
  // 화면 텍스트와 실제로 말하는 내용이 같은 순서로 흘러가게 맞춘다.
  String get _greetingText {
    final trimmed = _userName?.trim();
    if (trimmed == null || trimmed.isEmpty) {
      return '안녕하세요! 저는 딸랑구예요 :)\n'
          '오늘도 반갑게 인사하러 왔어요!\n'
          '화면 아래쪽 버튼을 누르면 바로 시작할 수 있어요!';
    }
    return '$trimmed님, 안녕하세요!\n'
        '오늘도 딸랑구가 쇼핑을 도와드릴게요.\n'
        '화면 아래쪽 버튼을 누르면 바로 시작할 수 있어요!';
  }

  List<String> get _greetingHighlightedWords {
    final trimmed = _userName?.trim();
    return [if (trimmed != null && trimmed.isNotEmpty) trimmed, '딸랑구'];
  }

  List<String> get _greetingSentences {
    return _greetingText
        .split('\n')
        .map((sentence) => sentence.trim())
        .where((sentence) => sentence.isNotEmpty)
        .toList(growable: false);
  }

  Future<void> _speakGreetingSentences() {
    final runId = ++_speechRunId;
    final sentences = _greetingSentences;
    _speechQueue = _speechQueue.then((_) async {
      try {
        await _voiceService.init();
        await _voiceService.stopSpeaking();
        for (final sentence in sentences) {
          if (!mounted || runId != _speechRunId) {
            return;
          }
          await _voiceService.speak(sentence);
        }
      } catch (_) {
        // 홈 인사 TTS는 보조 기능이라 실패해도 화면 진입을 막지 않는다.
      }
    });
    return _speechQueue;
  }

  @override
  Widget build(BuildContext context) {
    final responsive = context.responsive;

    return ScreenFrame(
      preset: LayoutPreset.standard,
      child: LayoutBuilder(
        builder: (context, constraints) {
          return Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Expanded(
                child: LayoutBuilder(
                  builder: (context, contentConstraints) {
                    final compact =
                        contentConstraints.maxHeight < 820 ||
                        responsive.usesCondensedLayout;
                    final imageHeight = responsive.bound(
                      responsive.heightScaled(
                        compact ? 236 : 300,
                        minFactor: 0.8,
                        maxFactor: 1.0,
                      ),
                      min: 210,
                      max: 300,
                    );
                    final sectionGap = responsive.bound(
                      responsive.heightScaled(
                        compact ? AppSpacing.md : AppSpacing.xl,
                        minFactor: 0.72,
                        maxFactor: 1.0,
                      ),
                      min: AppSpacing.sm,
                      max: AppSpacing.xl,
                    );
                    final headerGap = responsive.bound(
                      responsive.heightScaled(
                        compact ? AppSpacing.sm : AppSpacing.lg,
                        minFactor: 0.72,
                        maxFactor: 1.0,
                      ),
                      min: AppSpacing.xs,
                      max: AppSpacing.lg,
                    );
                    // "딸랑구가 본 나 보기"처럼 2줄로 넘어가는 라벨이 있어서
                    // 기존 높이(104~128)로는 텍스트가 살짝 잘렸다(오버플로우).
                    // 여유를 좀 더 뒀다.
                    final shortcutHeight = responsive.bound(
                      responsive.heightScaled(
                        compact ? 132 : 144,
                        minFactor: 0.84,
                        maxFactor: 1.0,
                      ),
                      min: 120,
                      max: 144,
                    );
                    final useSingleColumnShortcuts =
                        contentConstraints.maxWidth < 340;

                    Widget buildShortcutCard({
                      required IconData icon,
                      required String title,
                      required VoidCallback onTap,
                    }) {
                      return SizedBox(
                        height: shortcutHeight,
                        child: _ShortcutCard(
                          icon: icon,
                          title: title,
                          onTap: onTap,
                        ),
                      );
                    }

                    return CustomScrollView(
                      physics: const ClampingScrollPhysics(),
                      slivers: [
                        SliverToBoxAdapter(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Row(
                                crossAxisAlignment: CrossAxisAlignment.start,
                                children: [
                                  if (kDebugMode)
                                    Column(
                                      crossAxisAlignment:
                                          CrossAxisAlignment.start,
                                      children: [
                                        TextButton(
                                          onPressed: () {
                                            Navigator.of(
                                              context,
                                            ).pushNamedAndRemoveUntil(
                                              AppRoutes.splashMock,
                                              (route) => false,
                                            );
                                          },
                                          style: TextButton.styleFrom(
                                            padding: const EdgeInsets.symmetric(
                                              horizontal: AppSpacing.xs,
                                              vertical: AppSpacing.xxs,
                                            ),
                                            minimumSize: Size.zero,
                                            tapTargetSize: MaterialTapTargetSize
                                                .shrinkWrap,
                                          ),
                                          child: Text(
                                            'mock 첫 흐름 보기',
                                            style: AppTextStyles.caption
                                                .copyWith(
                                                  color: _temporaryDebugColor,
                                                  fontWeight: FontWeight.w800,
                                                ),
                                          ),
                                        ),
                                        TextButton(
                                          onPressed: () {
                                            Navigator.of(context).pushNamed(
                                              AppRoutes.flowEntryMock,
                                            );
                                          },
                                          style: TextButton.styleFrom(
                                            padding: const EdgeInsets.symmetric(
                                              horizontal: AppSpacing.xs,
                                              vertical: AppSpacing.xxs,
                                            ),
                                            minimumSize: Size.zero,
                                            tapTargetSize: MaterialTapTargetSize
                                                .shrinkWrap,
                                          ),
                                          child: Text(
                                            'mock 쇼핑 흐름 보기',
                                            style: AppTextStyles.caption
                                                .copyWith(
                                                  color: _temporaryDebugColor,
                                                  fontWeight: FontWeight.w800,
                                                ),
                                          ),
                                        ),
                                      ],
                                    ),
                                  const Spacer(),
                                  TextButton(
                                    onPressed: _logout,
                                    child: Text(
                                      '로그아웃',
                                      style: AppTextStyles.body2.copyWith(
                                        color: AppColors.primaryPinkDark,
                                        fontWeight: FontWeight.w800,
                                      ),
                                    ),
                                  ),
                                ],
                              ),
                              SizedBox(height: headerGap),
                              DialogueBubble(
                                text: _greetingText,
                                cyclePages: true,
                                highlightedWords: _greetingHighlightedWords,
                                style: AppTextStyles.title2.copyWith(
                                  fontSize: responsive.bound(
                                    responsive.font(compact ? 22 : 25),
                                    min: 21,
                                    max: 25,
                                  ),
                                  height: 1.32,
                                  fontWeight: FontWeight.w600,
                                  color: AppColors.textPrimary,
                                ),
                                emphasizedStyle: AppTextStyles.title2.copyWith(
                                  fontSize: responsive.bound(
                                    responsive.font(compact ? 22 : 25),
                                    min: 21,
                                    max: 25,
                                  ),
                                  height: 1.32,
                                  fontWeight: FontWeight.w800,
                                  color: AppColors.primaryPinkDark,
                                ),
                              ),
                              SizedBox(height: sectionGap),
                              Center(
                                child: Image.asset(
                                  'assets/images/character/top/ddalangoo_greeting_top.png',
                                  height: imageHeight,
                                  fit: BoxFit.contain,
                                ),
                              ),
                            ],
                          ),
                        ),
                        SliverFillRemaining(
                          hasScrollBody: false,
                          fillOverscroll: true,
                          child: Align(
                            alignment: Alignment.bottomLeft,
                            child: Padding(
                              padding: EdgeInsets.only(
                                top: sectionGap,
                                bottom: responsive.bound(
                                  responsive.heightScaled(
                                    compact ? AppSpacing.lg : AppSpacing.xl,
                                    minFactor: 0.76,
                                    maxFactor: 1.0,
                                  ),
                                  min: AppSpacing.md,
                                  max: AppSpacing.xl,
                                ),
                              ),
                              child: Column(
                                mainAxisSize: MainAxisSize.min,
                                crossAxisAlignment: CrossAxisAlignment.start,
                                children: [
                                  Row(
                                    mainAxisSize: MainAxisSize.min,
                                    children: [
                                      Container(
                                        width: 10,
                                        height: 10,
                                        decoration: const BoxDecoration(
                                          color: AppColors.primaryPink,
                                          shape: BoxShape.circle,
                                        ),
                                      ),
                                      const SizedBox(width: AppSpacing.xs),
                                      Text(
                                        '바로가기',
                                        style: AppTextStyles.body1.copyWith(
                                          color: AppColors.primaryPinkDark,
                                          fontWeight: FontWeight.w700,
                                          height: 1.25,
                                        ),
                                      ),
                                    ],
                                  ),
                                  const SizedBox(height: AppSpacing.md),
                                  if (useSingleColumnShortcuts)
                                    Column(
                                      children: [
                                        buildShortcutCard(
                                          icon: Icons.shopping_cart_outlined,
                                          title: '장바구니 보기',
                                          onTap: () => Navigator.of(
                                            context,
                                          ).pushNamed(AppRoutes.cart),
                                        ),
                                        const SizedBox(height: AppSpacing.md),
                                        buildShortcutCard(
                                          icon: Icons.auto_awesome_rounded,
                                          title: '딸랑구가 본 나',
                                          onTap: () {
                                            Navigator.of(context).pushNamed(
                                              AppRoutes.preferenceReport,
                                            );
                                          },
                                        ),
                                      ],
                                    )
                                  else
                                    Row(
                                      children: [
                                        Expanded(
                                          child: buildShortcutCard(
                                            icon: Icons.shopping_cart_outlined,
                                            title: '장바구니 보기',
                                            onTap: () => Navigator.of(
                                              context,
                                            ).pushNamed(AppRoutes.cart),
                                          ),
                                        ),
                                        const SizedBox(width: AppSpacing.md),
                                        Expanded(
                                          child: buildShortcutCard(
                                            icon: Icons.auto_awesome_rounded,
                                            title: '딸랑구가 본 나',
                                            onTap: () {
                                              Navigator.of(context).pushNamed(
                                                AppRoutes.preferenceReport,
                                              );
                                            },
                                          ),
                                        ),
                                      ],
                                    ),
                                ],
                              ),
                            ),
                          ),
                        ),
                      ],
                    );
                  },
                ),
              ),
              SizedBox(
                height: responsive.bound(
                  responsive.heightScaled(
                    AppSpacing.lg,
                    minFactor: 0.72,
                    maxFactor: 1.0,
                  ),
                  min: AppSpacing.sm,
                  max: AppSpacing.lg,
                ),
              ),
              // "딸랑구를 불러보세요!" 회색 안내 문구는 삭제하고, 같은 안내를
              // 말풍선 문구(화면 아래쪽 버튼을 누르면...)에 녹여 넣었다.
              PrimaryButton(
                label: '딸랑구야 도와줘!',
                icon: Icons.phone_in_talk_rounded,
                onPressed: () {
                  // named route(AppRoutes.flowEntry)로 가면 ShoppingFlowScreen이
                  // userName 없이 시작해서, 컨트롤러 부트스트랩 단계에서
                  // 사용자 이름을 다시 네트워크로 조회한다. 그 대기 시간 동안
                  // "쇼핑 화면을 준비하고 있어요" 초기화 화면이 잠깐 보였다가
                  // 사라지는 깜빡임이 생겼다. 홈 화면이 이미 알고 있는
                  // _userName을 그대로 넘겨서 그 조회를 건너뛰게 한다.
                  Navigator.of(context).push(
                    MaterialPageRoute<void>(
                      builder: (_) => ShoppingFlowScreen(userName: _userName),
                    ),
                  );
                },
              ),
            ],
          );
        },
      ),
    );
  }
}

class _ShortcutCard extends StatelessWidget {
  const _ShortcutCard({required this.icon, required this.title, this.onTap});

  final IconData icon;
  final String title;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    final responsive = context.responsive;

    return Material(
      color: Colors.transparent,
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(AppRadii.lg),
        child: Container(
          padding: EdgeInsets.all(
            responsive.bound(
              responsive.scale(AppSpacing.md, minFactor: 0.84, maxFactor: 1.0),
              min: AppSpacing.sm,
              max: AppSpacing.md,
            ),
          ),
          decoration: AppSurfaceStyles.elevatedCard(radius: AppRadii.lg),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              const Spacer(),
              Center(
                child: Icon(
                  icon,
                  color: AppColors.primaryPinkDark,
                  size: responsive.bound(
                    responsive.scale(30, minFactor: 0.86, maxFactor: 1.0),
                    min: 26,
                    max: 30,
                  ),
                ),
              ),
              const SizedBox(height: AppSpacing.md),
              Text(
                title,
                maxLines: 2,
                textAlign: TextAlign.center,
                style: AppTextStyles.body1.copyWith(
                  color: AppColors.primaryPinkDark,
                  fontWeight: FontWeight.w700,
                  height: 1.25,
                  fontSize: responsive.bound(
                    responsive.font(18, minFactor: 0.94, maxFactor: 1.0),
                    min: 16,
                    max: 18,
                  ),
                ),
              ),
              const Spacer(),
            ],
          ),
        ),
      ),
    );
  }
}
