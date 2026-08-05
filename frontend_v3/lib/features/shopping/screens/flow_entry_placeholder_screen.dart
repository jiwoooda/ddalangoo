import 'package:flutter/material.dart';

import '../../../app/routes.dart';
import '../../../app/theme/app_colors.dart';
import '../../../app/theme/app_radii.dart';
import '../../../app/theme/app_spacing.dart';
import '../../../app/theme/app_text_styles.dart';
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
    return ScreenFrame(
      preset: LayoutPreset.conversation,
      child: Column(
        children: [
          const ShoppingProgressStepper(
            currentStep: ShoppingProgressStep.productCheck,
          ),
          const SizedBox(height: AppSpacing.xl),
          DialogueBubble(
            segments: _promptSegments,
            style: const TextStyle(
              fontSize: 24,
              height: 1.25,
              fontWeight: FontWeight.w700,
              color: AppColors.textStrong,
            ),
          ),
          const SizedBox(height: AppSpacing.xl),
          Expanded(
            child: Center(
              child: Image.asset(
                'assets/images/ddalangoo_cheerful.png',
                height: 260,
                fit: BoxFit.contain,
              ),
            ),
          ),
          const SizedBox(height: AppSpacing.lg),
          Wrap(
            spacing: AppSpacing.sm,
            runSpacing: AppSpacing.sm,
            children: const [
              _ExampleChip(label: '토마토 사고 싶어'),
              _ExampleChip(label: '삼겹살 1근 구매해줘'),
            ],
          ),
          const SizedBox(height: AppSpacing.xl),
          VoiceInputButton(
            label: '말씀해주세요',
            state: VoiceInputState.active,
            onPressed: () {
              ScaffoldMessenger.of(context).showSnackBar(
                const SnackBar(content: Text('다음 상품 요청 단계는 이어서 구현할 예정이에요.')),
              );
            },
          ),
          const SizedBox(height: AppSpacing.lg),
          EndConversationButton(
            variant: EndConversationButtonVariant.dark,
            onPressed: () {
              Navigator.of(
                context,
              ).pushNamedAndRemoveUntil(AppRoutes.home, (route) => false);
            },
          ),
        ],
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
