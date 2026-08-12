import 'package:flutter/material.dart';

import '../../app/theme/app_colors.dart';
import '../../app/theme/app_radii.dart';
import '../../app/theme/app_spacing.dart';
import '../../app/theme/app_surface_styles.dart';
import '../../app/theme/app_text_styles.dart';
import '../layout/app_responsive.dart';
import 'voice_input_button.dart';

/// 온보딩 대화형 화면들(이름 입력 스몰토크, 딸랑구 인사 스몰토크 등)에서
/// 공통으로 쓰는 음성 입력 패널. 카드 형태 배경 위에 마이크 버튼을 가운데
/// 두고, 좌우에 선택적으로 예시 답변 위젯을 배치한다. 화면마다 패널
/// 모양/배경색이 제각각이던 문제를 해결하기 위해 하나로 통일했다.
class VoicePanel extends StatelessWidget {
  const VoicePanel({
    super.key,
    required this.state,
    required this.onPressed,
    this.leadingReply,
    this.trailingReply,
  });

  final VoiceInputState state;
  final VoidCallback onPressed;
  final Widget? leadingReply;
  final Widget? trailingReply;

  static const double _baseHeight = 126;
  static const double _minHeight = 108;

  /// 패널 실제 렌더 높이와 동일한 공식. 이 패널을 오버레이로 띄우는
  /// 화면에서 콘텐츠가 패널에 가리지 않도록 하단 여백을 계산할 때
  /// 이 값을 그대로 재사용하면 패널 높이와 항상 일치한다.
  static double heightFor(BuildContext context) {
    final responsive = context.responsive;
    return responsive.bound(
      responsive.heightScaled(_baseHeight, minFactor: 0.84, maxFactor: 1.0),
      min: _minHeight,
      max: _baseHeight,
    );
  }

  @override
  Widget build(BuildContext context) {
    final responsive = context.responsive;
    final backgroundColor = state == VoiceInputState.inactive
        ? const Color(0xFFF7F7FA)
        : AppColors.pastelPinkSoft;
    final panelHeight = heightFor(context);

    return AnimatedContainer(
      duration: const Duration(milliseconds: 220),
      width: double.infinity,
      height: panelHeight,
      padding: EdgeInsets.symmetric(
        horizontal: responsive.bound(
          responsive.widthScaled(
            AppSpacing.md,
            minFactor: 0.84,
            maxFactor: 1.0,
          ),
          min: AppSpacing.sm,
          max: AppSpacing.md,
        ),
      ),
      decoration: AppSurfaceStyles.elevatedCard(
        radius: AppRadii.xl,
        color: backgroundColor,
      ),
      child: Row(
        children: [
          Expanded(
            child: Align(
              alignment: Alignment.centerRight,
              child: leadingReply ?? const SizedBox.shrink(),
            ),
          ),
          const SizedBox(width: AppSpacing.xs),
          Center(
            child: VoiceInputButton(
              state: state,
              onPressed: onPressed,
              diameter: 72,
              iconSize: 34,
              labelSpacing: 6,
            ),
          ),
          const SizedBox(width: AppSpacing.xs),
          Expanded(
            child: Align(
              alignment: Alignment.centerLeft,
              child: trailingReply ?? const SizedBox.shrink(),
            ),
          ),
        ],
      ),
    );
  }
}

/// 데모/mock 용도로 붙이는 "예시 답변" 칩. 초록색으로 표시해 실제 서비스
/// 문구가 아니라 바로 눌러서 다음 단계로 넘어가 볼 수 있는 지름길임을
/// 시각적으로 구분한다.
class VoiceExampleReplyChip extends StatelessWidget {
  const VoiceExampleReplyChip({
    super.key,
    required this.label,
    required this.textAlign,
    this.onTap,
  });

  final String label;
  final TextAlign textAlign;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    final isEnabled = onTap != null;
    return Material(
      color: Colors.transparent,
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(AppRadii.md),
        child: Padding(
          padding: const EdgeInsets.symmetric(
            horizontal: AppSpacing.xs,
            vertical: AppSpacing.xxs,
          ),
          child: Text(
            '"$label"',
            textAlign: textAlign,
            maxLines: 2,
            style: AppTextStyles.caption.copyWith(
              color: isEnabled
                  ? AppColors.success
                  : AppColors.success.withValues(alpha: 0.45),
              fontWeight: FontWeight.w400,
              height: 1.35,
            ),
          ),
        ),
      ),
    );
  }
}
