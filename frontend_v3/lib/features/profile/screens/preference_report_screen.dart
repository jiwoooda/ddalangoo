import 'package:flutter/material.dart';

import '../../../app/theme/app_colors.dart';
import '../../../app/theme/app_radii.dart';
import '../../../app/theme/app_spacing.dart';
import '../../../app/theme/app_surface_styles.dart';
import '../../../app/theme/app_text_styles.dart';
import '../../../core/storage/local_storage.dart';
import '../../../shared/layout/app_responsive.dart';
import '../../../shared/layout/layout_presets.dart';
import '../../../shared/layout/screen_frame.dart';
import '../../../shared/widgets/primary_button.dart';

/// 스몰토크 & 구매이력 크롤링을 바탕으로 백엔드가 계산해두는
/// `user_preference_cache`(선호 브랜드/가격대/재구매 패턴/선호 플랫폼)를
/// 사용자에게 보여주는 화면.
///
/// 주의: 현재 백엔드에는 이 데이터를 프론트에 내려주는 API가 없어서
/// (백엔드 코드는 이번 작업 범위에서 수정하지 않기로 함) 데모용 목데이터로
/// 화면만 우선 구성했다. 실제 데이터 연동을 위해서는 백엔드에
/// preference 조회용 엔드포인트 추가가 별도로 필요하다.
class PreferenceReportScreen extends StatefulWidget {
  const PreferenceReportScreen({super.key});

  @override
  State<PreferenceReportScreen> createState() =>
      _PreferenceReportScreenState();
}

class _PreferenceReportScreenState extends State<PreferenceReportScreen> {
  String? _userName;

  @override
  void initState() {
    super.initState();
    _loadUserName();
  }

  Future<void> _loadUserName() async {
    final cachedUserName = await LocalStorage.getUserName();
    if (!mounted) {
      return;
    }
    if (cachedUserName != null && cachedUserName.trim().isNotEmpty) {
      setState(() => _userName = cachedUserName.trim());
    }
  }

  @override
  Widget build(BuildContext context) {
    final responsive = context.responsive;
    final verticalGap = responsive.bound(
      responsive.heightScaled(AppSpacing.lg, minFactor: 0.72, maxFactor: 1.0),
      min: AppSpacing.sm,
      max: AppSpacing.lg,
    );

    return ScreenFrame(
      preset: LayoutPreset.cartCompact,
      child: Column(
        children: [
          // 하단에 이미 "홈으로 돌아가기" 버튼이 있어서, 상단 좌측 뒤로가기
          // 화살표는 중복이라 지우고 제목만 가운데에 둔다.
          Center(
            child: Text(
              '딸랑구가 본 나',
              textAlign: TextAlign.center,
              style: AppTextStyles.body1.copyWith(
                fontWeight: FontWeight.w800,
                fontSize: responsive.bound(
                  responsive.font(18, minFactor: 0.94, maxFactor: 1.0),
                  min: 16,
                  max: 18,
                ),
              ),
            ),
          ),
          SizedBox(height: verticalGap),
          Expanded(child: _buildBody(responsive)),
          SizedBox(height: verticalGap),
          PrimaryButton(
            label: '홈으로 돌아가기',
            icon: Icons.home_rounded,
            onPressed: () => Navigator.of(context).maybePop(),
          ),
        ],
      ),
    );
  }

  Widget _buildBody(AppResponsive responsive) {
    final greetingName = _userName == null || _userName!.isEmpty
        ? '고객'
        : _userName!;

    return SingleChildScrollView(
      physics: const ClampingScrollPhysics(),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            '$greetingName님과 나눈 스몰토크와 구매이력을 바탕으로\n딸랑구가 핵심만 정리했어요.',
            style: AppTextStyles.body2.copyWith(
              color: AppColors.textSecondary,
              fontWeight: FontWeight.w600,
              height: 1.4,
            ),
          ),
          SizedBox(height: AppSpacing.lg),
          // 순서: 관심 키워드 → 재구매 상품 → 이용 플랫폼 → 브랜드 → 평균 구매가
          const _PreferenceSection(
            icon: Icons.auto_awesome_rounded,
            title: '관심 키워드',
            child: _ChipGroup(
              labels: ['신선식품', '가성비', '빠른배송', '소포장'],
            ),
          ),
          const SizedBox(height: AppSpacing.md),
          const _PreferenceSection(
            icon: Icons.replay_rounded,
            title: '자주 재구매하는 상품',
            child: _ChipGroup(labels: ['토마토', '삼겹살', '계란', '우유']),
          ),
          const SizedBox(height: AppSpacing.md),
          const _PreferenceSection(
            icon: Icons.storefront_outlined,
            title: '주로 이용하는 플랫폼',
            child: _ChipGroup(labels: ['쿠팡']),
          ),
          const SizedBox(height: AppSpacing.md),
          const _PreferenceSection(
            icon: Icons.storefront_rounded,
            title: '자주 찾는 브랜드',
            child: _ChipGroup(labels: ['오뚜기', '풀무원', 'CJ제일제당', '동원']),
          ),
          const SizedBox(height: AppSpacing.md),
          const _PreferenceSection(
            icon: Icons.payments_rounded,
            title: '평균 구매가',
            child: _StatLine(
              headline: '평균 24,000원',
              caption: '보통 12,000원 ~ 38,000원 사이에서 구매해요',
            ),
          ),
          const SizedBox(height: AppSpacing.sm),
        ],
      ),
    );
  }
}

class _PreferenceSection extends StatelessWidget {
  const _PreferenceSection({
    required this.icon,
    required this.title,
    required this.child,
  });

  final IconData icon;
  final String title;
  final Widget child;

  @override
  Widget build(BuildContext context) {
    final responsive = context.responsive;

    return Container(
      width: double.infinity,
      padding: EdgeInsets.all(
        responsive.bound(
          responsive.scale(AppSpacing.md, minFactor: 0.84, maxFactor: 1.0),
          min: AppSpacing.sm,
          max: AppSpacing.md,
        ),
      ),
      decoration: AppSurfaceStyles.elevatedCard(radius: AppRadii.lg),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(icon, size: 18, color: AppColors.primaryPinkDark),
              const SizedBox(width: AppSpacing.xs),
              Text(
                title,
                style: AppTextStyles.body2.copyWith(
                  color: AppColors.textStrong,
                  fontWeight: FontWeight.w800,
                ),
              ),
            ],
          ),
          const SizedBox(height: AppSpacing.sm),
          child,
        ],
      ),
    );
  }
}

class _ChipGroup extends StatelessWidget {
  const _ChipGroup({required this.labels});

  final List<String> labels;

  @override
  Widget build(BuildContext context) {
    if (labels.isEmpty) {
      return Text(
        '아직 쌓인 데이터가 없어요.',
        style: AppTextStyles.caption.copyWith(color: AppColors.textMuted),
      );
    }

    return Wrap(
      spacing: AppSpacing.xs,
      runSpacing: AppSpacing.xs,
      children: [for (final label in labels) _PreferenceChip(label: label)],
    );
  }
}

class _PreferenceChip extends StatelessWidget {
  const _PreferenceChip({required this.label});

  final String label;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(
        horizontal: AppSpacing.sm,
        vertical: AppSpacing.xs,
      ),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(AppRadii.pill),
        border: Border.all(color: AppColors.primaryPinkDark, width: 1.25),
      ),
      child: Text(
        label,
        style: AppTextStyles.caption.copyWith(
          color: AppColors.primaryPinkDark,
          fontWeight: FontWeight.w800,
        ),
      ),
    );
  }
}

class _StatLine extends StatelessWidget {
  const _StatLine({required this.headline, required this.caption});

  final String headline;
  final String caption;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          headline,
          style: AppTextStyles.title2.copyWith(
            color: AppColors.primaryPinkDark,
            fontWeight: FontWeight.w800,
          ),
        ),
        const SizedBox(height: AppSpacing.xxs),
        Text(
          caption,
          style: AppTextStyles.caption.copyWith(color: AppColors.textMuted),
        ),
      ],
    );
  }
}
