import 'package:flutter/material.dart';

import '../../../app/routes.dart';
import '../../../app/theme/app_colors.dart';
import '../../../app/theme/app_radii.dart';
import '../../../app/theme/app_spacing.dart';
import '../../../app/theme/app_text_styles.dart';
import '../../../shared/layout/app_responsive.dart';
import '../../../shared/layout/layout_presets.dart';
import '../../../shared/layout/screen_frame.dart';
import '../../../shared/widgets/dialogue_bubble.dart';
import '../../../shared/widgets/end_conversation_button.dart';
import '../../../shared/widgets/shopping_progress_stepper.dart';
import '../../../shared/widgets/voice_input_button.dart';

class FlowEntryPlaceholderScreen extends StatelessWidget {
  const FlowEntryPlaceholderScreen({super.key, this.userName});

  final String? userName;

  List<DialogueSegment> get _promptSegments {
    if (userName == null || userName!.trim().isEmpty) {
      return const [DialogueSegment(text: '뭐가 필요하세요?')];
    }

    return [
      DialogueSegment(text: '$userName님\n', emphasized: true),
      const DialogueSegment(text: '뭐가 필요하세요?'),
    ];
  }

  @override
  Widget build(BuildContext context) {
    final responsive = context.responsive;

    return ScreenFrame(
      preset: LayoutPreset.conversation,
      child: LayoutBuilder(
        builder: (context, constraints) {
          final compact =
              constraints.maxHeight < 760 || responsive.usesCondensedLayout;
          final imageHeight = responsive.bound(
            responsive.heightScaled(
              compact ? 220 : 260,
              minFactor: 0.8,
              maxFactor: 1.0,
            ),
            min: 180,
            max: 260,
          );
          final bubbleFontSize = responsive.bound(
            responsive.font(compact ? 22 : 24, minFactor: 0.94, maxFactor: 1.0),
            min: 21,
            max: 24,
          );
          final largeGap = responsive.bound(
            responsive.heightScaled(
              AppSpacing.xl,
              minFactor: 0.72,
              maxFactor: 1.0,
            ),
            min: AppSpacing.lg,
            max: AppSpacing.xl,
          );

          return Column(
            children: [
              Align(
                alignment: Alignment.centerRight,
                child: EndConversationButton(
                  compact: true,
                  variant: EndConversationButtonVariant.dark,
                  onPressed: () {
                    Navigator.of(
                      context,
                    ).pushNamedAndRemoveUntil(AppRoutes.home, (route) => false);
                  },
                ),
              ),
              const SizedBox(height: AppSpacing.md),
              const ShoppingProgressStepper(
                currentStep: ShoppingProgressStep.productCheck,
              ),
              SizedBox(height: largeGap),
              DialogueBubble(
                segments: _promptSegments,
                style: TextStyle(
                  fontSize: bubbleFontSize,
                  height: 1.25,
                  fontWeight: FontWeight.w700,
                  color: AppColors.textStrong,
                ),
              ),
              SizedBox(height: largeGap),
              Expanded(
                child: Center(
                  child: Image.asset(
                    'assets/images/character/full/ddalangoo_cheerful.png',
                    height: imageHeight,
                    fit: BoxFit.contain,
                  ),
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
              Wrap(
                spacing: AppSpacing.sm,
                runSpacing: AppSpacing.sm,
                children: const [
                  _ExampleChip(label: '토마토 사고 싶어'),
                  _ExampleChip(label: '삼겹살 1근 구매해줘'),
                ],
              ),
              SizedBox(height: largeGap),
              VoiceInputButton(
                state: VoiceInputState.active,
                onPressed: () {
                  ScaffoldMessenger.of(context).showSnackBar(
                    const SnackBar(
                      content: Text('다음 상품 요청 단계는 이어서 구현할 예정이에요.'),
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

class _ExampleChip extends StatelessWidget {
  const _ExampleChip({required this.label});

  final String label;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(
        horizontal: AppSpacing.md,
        vertical: AppSpacing.sm,
      ),
      decoration: BoxDecoration(
        color: AppColors.surface,
        borderRadius: BorderRadius.circular(AppRadii.pill),
        border: Border.all(color: AppColors.border),
      ),
      child: Text(
        label,
        style: AppTextStyles.body2.copyWith(
          color: AppColors.textPrimary,
          fontWeight: FontWeight.w700,
        ),
      ),
    );
  }
}
