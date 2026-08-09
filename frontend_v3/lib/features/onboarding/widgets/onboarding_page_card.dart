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
    this.trailingTags = const <String>[],
  });

  final String title;
  final String assetPath;
  final String? bubbleText;
  final List<String> trailingTags;

  @override
  Widget build(BuildContext context) {
    final responsive = context.responsive;

    return LayoutBuilder(
      builder: (context, constraints) {
        final compactHeight =
            constraints.maxHeight < 640 || responsive.usesCondensedLayout;
        final verticalPadding = responsive.bound(
          responsive.heightScaled(
            compactHeight ? AppSpacing.lg : AppSpacing.xl,
            minFactor: 0.72,
            maxFactor: 1.0,
          ),
          min: AppSpacing.md,
          max: AppSpacing.xl,
        );
        final horizontalPadding = responsive.bound(
          responsive.widthScaled(
            AppSpacing.lg,
            minFactor: 0.85,
            maxFactor: 1.0,
          ),
          min: AppSpacing.md,
          max: AppSpacing.xl,
        );
        final imageHeight = responsive.bound(
          constraints.maxHeight * (compactHeight ? 0.28 : 0.33),
          min: 180,
          max: 250,
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
          children: [
            Expanded(
              child: Center(
                child: Container(
                  width: double.infinity,
                  padding: EdgeInsets.symmetric(
                    horizontal: horizontalPadding,
                    vertical: verticalPadding,
                  ),
                  decoration: BoxDecoration(
                    color: AppColors.surface,
                    borderRadius: BorderRadius.circular(AppRadii.xl),
                    border: Border.all(color: AppColors.border),
                    boxShadow: const [
                      BoxShadow(
                        color: AppColors.shadow,
                        blurRadius: 24,
                        offset: Offset(0, 12),
                      ),
                    ],
                  ),
                  child: Column(
                    mainAxisAlignment: MainAxisAlignment.center,
                    children: [
                      if (bubbleText != null) ...[
                        _SpeechChip(label: bubbleText!),
                        SizedBox(height: verticalPadding),
                      ],
                      if (trailingTags.isNotEmpty) ...[
                        Wrap(
                          alignment: WrapAlignment.center,
                          spacing: AppSpacing.sm,
                          runSpacing: AppSpacing.md,
                          children: [
                            for (final tag in trailingTags)
                              _StatusTag(label: tag),
                          ],
                        ),
                        SizedBox(height: verticalPadding),
                      ],
                      Image.asset(
                        assetPath,
                        height: imageHeight,
                        fit: BoxFit.contain,
                      ),
                      SizedBox(height: verticalPadding),
                      Text(
                        title,
                        textAlign: TextAlign.center,
                        style: AppTextStyles.title1.copyWith(
                          height: 1.22,
                          fontSize: titleSize,
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            ),
          ],
        );
      },
    );
  }
}

class _SpeechChip extends StatelessWidget {
  const _SpeechChip({required this.label});

  final String label;

  @override
  Widget build(BuildContext context) {
    final responsive = context.responsive;
    final bubbleTailSize = responsive.bound(
      responsive.scale(15, minFactor: 0.9, maxFactor: 1.0),
      min: 13,
      max: 15,
    );

    return Stack(
      clipBehavior: Clip.none,
      children: [
        Container(
          padding: EdgeInsets.symmetric(
            horizontal: responsive.bound(
              responsive.widthScaled(
                AppSpacing.lg,
                minFactor: 0.86,
                maxFactor: 1.0,
              ),
              min: AppSpacing.md,
              max: AppSpacing.lg,
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
            style: AppTextStyles.body1.copyWith(
              fontSize: responsive.font(18, minFactor: 0.94, maxFactor: 1.0),
              fontWeight: FontWeight.w700,
              color: AppColors.primaryPinkDark,
            ),
          ),
        ),
        Positioned(
          left: responsive.bound(
            responsive.widthScaled(34, minFactor: 0.88, maxFactor: 1.0),
            min: 26,
            max: 34,
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
