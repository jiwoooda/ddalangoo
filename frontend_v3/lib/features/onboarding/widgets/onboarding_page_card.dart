import 'package:flutter/material.dart';

import '../../../app/theme/app_colors.dart';
import '../../../app/theme/app_radii.dart';
import '../../../app/theme/app_spacing.dart';
import '../../../app/theme/app_text_styles.dart';
import '../../../shared/layout/app_responsive.dart';

class OnboardingPageCard extends StatelessWidget {
  const OnboardingPageCard({
    super.key,
    required this.title,
    required this.assetPath,
    this.bubbleText,
    this.compactBubble = false,
    this.trailingTags = const <String>[],
    this.description,
    this.footer,
  });

  final String title;
  final String assetPath;
  final String? bubbleText;

  /// true면 말풍선을 더 작은 크기(글씨/패딩 축소)로 보여준다. 페이지의
  /// 핵심 대사가 아니라 부가 안내("신규 가입자라면 시작하기를 눌러보세요!"
  /// 같은)를 담을 때 쓴다 — 같은 말풍선 디자인(흰 배경/핑크 테두리/꼬리)은
  /// 그대로 유지해서 화면 간 통일감은 지키면서 크기만 구분한다.
  final bool compactBubble;
  final List<String> trailingTags;
  final String? description;
  final Widget? footer;

  @override
  Widget build(BuildContext context) {
    final responsive = context.responsive;

    // 카드(배경+테두리+그림자) 없이 텍스트/캐릭터를 화면에 바로 배치한다.
    // 상단 = 제목(+설명, +접근성 페이지의 버튼), 하단 = 캐릭터+말풍선/태그.
    // 가장자리 여백은 이 위젯이 아니라 부모 ScreenFrame이 이미 준다.
    return LayoutBuilder(
      builder: (context, constraints) {
        final compactHeight =
            constraints.maxHeight < 640 || responsive.usesCondensedLayout;
        final sectionGap = responsive.bound(
          responsive.heightScaled(
            compactHeight ? AppSpacing.lg : AppSpacing.xl,
            minFactor: 0.72,
            maxFactor: 1.0,
          ),
          min: AppSpacing.md,
          max: AppSpacing.xl,
        );
        // 캐릭터+말풍선을 화면에서 더 크게 보여줘 여백을 줄인다. (화면이
        // 비어 보인다는 피드백을 반영해 배율/최소·최대값을 한 단계 키웠다.)
        final imageHeight = responsive.bound(
          constraints.maxHeight * (compactHeight ? 0.46 : 0.52),
          min: 260,
          max: 380,
        );
        final titleSize = responsive.bound(
          responsive.font(
            compactHeight ? 25 : 28,
            minFactor: 0.94,
            maxFactor: 1.0,
          ),
          min: 24,
          max: 28,
        );

        return Column(
          crossAxisAlignment: CrossAxisAlignment.center,
          children: [
            // 제목이 화면 맨 위에 바짝 붙지 않도록 여백을 더 준다.
            SizedBox(height: sectionGap * 1.6),
            Text(
              title,
              textAlign: TextAlign.center,
              style: AppTextStyles.title1.copyWith(
                height: 1.22,
                fontSize: titleSize,
              ),
            ),
            if (description != null) ...[
              SizedBox(
                height: responsive.bound(
                  responsive.heightScaled(
                    AppSpacing.sm,
                    minFactor: 0.72,
                    maxFactor: 1.0,
                  ),
                  min: AppSpacing.xs,
                  max: AppSpacing.sm,
                ),
              ),
              Text(
                description!,
                textAlign: TextAlign.center,
                style: AppTextStyles.body2.copyWith(
                  color: AppColors.textSecondary,
                  height: 1.4,
                  fontSize: responsive.font(15, minFactor: 0.94, maxFactor: 1.0),
                ),
              ),
            ],
            const Spacer(),
            if (footer != null) ...[footer!, const Spacer()],
            if (bubbleText != null) ...[
              _SpeechChip(label: bubbleText!, compact: compactBubble),
              SizedBox(height: sectionGap),
            ],
            if (trailingTags.isNotEmpty) ...[
              Wrap(
                alignment: WrapAlignment.center,
                spacing: AppSpacing.sm,
                runSpacing: AppSpacing.md,
                children: [
                  for (final tag in trailingTags) _StatusTag(label: tag),
                ],
              ),
              SizedBox(height: sectionGap),
            ],
            Image.asset(assetPath, height: imageHeight, fit: BoxFit.contain),
          ],
        );
      },
    );
  }
}

class _SpeechChip extends StatelessWidget {
  const _SpeechChip({required this.label, this.compact = false});

  final String label;
  final bool compact;

  @override
  Widget build(BuildContext context) {
    final responsive = context.responsive;
    final bubbleTailSize = responsive.bound(
      responsive.scale(compact ? 11 : 15, minFactor: 0.9, maxFactor: 1.0),
      min: compact ? 10 : 13,
      max: compact ? 11 : 15,
    );

    return Stack(
      clipBehavior: Clip.none,
      children: [
        Container(
          padding: EdgeInsets.symmetric(
            horizontal: responsive.bound(
              responsive.widthScaled(
                compact ? AppSpacing.md : AppSpacing.lg,
                minFactor: 0.86,
                maxFactor: 1.0,
              ),
              min: compact ? AppSpacing.sm : AppSpacing.md,
              max: compact ? AppSpacing.md : AppSpacing.lg,
            ),
            vertical: responsive.bound(
              responsive.heightScaled(
                compact ? AppSpacing.xs : AppSpacing.sm,
                minFactor: 0.82,
                maxFactor: 1.0,
              ),
              min: compact ? AppSpacing.xxs : AppSpacing.xs,
              max: compact ? AppSpacing.xs : AppSpacing.sm,
            ),
          ),
          decoration: BoxDecoration(
            color: Colors.white,
            borderRadius: BorderRadius.circular(AppRadii.pill),
            border: Border.all(color: AppColors.secondaryPink),
            boxShadow: const [
              BoxShadow(
                color: AppColors.shadow,
                blurRadius: 14,
                offset: Offset(0, 8),
              ),
            ],
          ),
          child: Text(
            label,
            textAlign: TextAlign.center,
            style: AppTextStyles.body1.copyWith(
              fontSize: responsive.font(
                compact ? 15 : 24,
                minFactor: 0.94,
                maxFactor: 1.0,
              ),
              fontWeight: compact ? FontWeight.w700 : FontWeight.w800,
              color: AppColors.primaryPinkDark,
            ),
          ),
        ),
        Positioned(
          left: responsive.bound(
            responsive.widthScaled(
              compact ? 24 : 34,
              minFactor: 0.88,
              maxFactor: 1.0,
            ),
            min: compact ? 18 : 26,
            max: compact ? 24 : 34,
          ),
          bottom: -7,
          child: Transform.rotate(
            angle: 0.7853981633974483,
            child: Container(
              width: bubbleTailSize,
              height: bubbleTailSize,
              decoration: BoxDecoration(
                color: Colors.white,
                border: Border(
                  right: BorderSide(color: AppColors.secondaryPink),
                  bottom: BorderSide(color: AppColors.secondaryPink),
                ),
              ),
            ),
          ),
        ),
      ],
    );
  }
}

class _StatusTag extends StatelessWidget {
  const _StatusTag({required this.label});

  final String label;

  @override
  Widget build(BuildContext context) {
    final responsive = context.responsive;
    final bubbleTailSize = responsive.bound(
      responsive.scale(13, minFactor: 0.9, maxFactor: 1.0),
      min: 11,
      max: 13,
    );

    return Stack(
      clipBehavior: Clip.none,
      children: [
        Container(
          padding: EdgeInsets.symmetric(
            horizontal: responsive.bound(
              responsive.widthScaled(
                AppSpacing.md,
                minFactor: 0.9,
                maxFactor: 1.0,
              ),
              min: AppSpacing.sm,
              max: AppSpacing.md,
            ),
            vertical: responsive.bound(
              responsive.heightScaled(
                AppSpacing.sm,
                minFactor: 0.82,
                maxFactor: 1.0,
              ),
              min: AppSpacing.xs,
              max: AppSpacing.sm,
            ),
          ),
          decoration: BoxDecoration(
            color: Colors.white,
            borderRadius: BorderRadius.circular(AppRadii.pill),
            border: Border.all(color: AppColors.secondaryPink),
            boxShadow: const [
              BoxShadow(
                color: AppColors.shadow,
                blurRadius: 14,
                offset: Offset(0, 8),
              ),
            ],
          ),
          child: Text(
            label,
            style: AppTextStyles.body2.copyWith(
              fontSize: responsive.font(16, minFactor: 0.94, maxFactor: 1.0),
              fontWeight: FontWeight.w700,
              color: AppColors.primaryPinkDark,
            ),
          ),
        ),
        Positioned(
          left: responsive.bound(
            responsive.widthScaled(24, minFactor: 0.88, maxFactor: 1.0),
            min: 18,
            max: 24,
          ),
          bottom: -6,
          child: Transform.rotate(
            angle: 0.7853981633974483,
            child: Container(
              width: bubbleTailSize,
              height: bubbleTailSize,
              decoration: BoxDecoration(
                color: Colors.white,
                border: Border(
                  right: BorderSide(color: AppColors.secondaryPink),
                  bottom: BorderSide(color: AppColors.secondaryPink),
                ),
              ),
            ),
          ),
        ),
      ],
    );
  }
}
