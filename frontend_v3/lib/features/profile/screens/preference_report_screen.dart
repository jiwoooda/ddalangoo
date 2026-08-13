import 'package:flutter/material.dart';

import '../../../app/theme/app_colors.dart';
import '../../../app/theme/app_radii.dart';
import '../../../app/theme/app_spacing.dart';
import '../../../app/theme/app_surface_styles.dart';
import '../../../app/theme/app_text_styles.dart';
import '../../../core/storage/local_storage.dart';
import '../../../data/models/preference_report_model.dart';
import '../../../data/repositories/preference_report_repository.dart';
import '../../../shared/layout/app_responsive.dart';
import '../../../shared/layout/layout_presets.dart';
import '../../../shared/layout/screen_frame.dart';
import '../../../shared/widgets/primary_button.dart';

/// 스몰토크 & 구매이력 크롤링을 바탕으로 백엔드가 계산해두는
/// `user_preference_cache`(선호 브랜드/가격대/재구매 패턴/선호 플랫폼)를
/// 사용자에게 보여주는 화면.
class PreferenceReportScreen extends StatefulWidget {
  const PreferenceReportScreen({super.key});

  @override
  State<PreferenceReportScreen> createState() => _PreferenceReportScreenState();
}

class _PreferenceReportScreenState extends State<PreferenceReportScreen> {
  final PreferenceReportRepository _repository = PreferenceReportRepository();

  String? _userName;
  PreferenceReportModel? _report;
  bool _isLoading = true;
  String? _errorMessage;

  @override
  void initState() {
    super.initState();
    _loadReport();
  }

  Future<void> _loadReport() async {
    final cachedUserName = await LocalStorage.getUserName();
    final userId = await LocalStorage.getUserId();
    if (!mounted) {
      return;
    }
    if (cachedUserName != null && cachedUserName.trim().isNotEmpty) {
      setState(() => _userName = cachedUserName.trim());
    }

    if (userId == null) {
      setState(() {
        _isLoading = false;
        _errorMessage = '로그인 정보를 찾지 못했어요.';
      });
      return;
    }

    try {
      final report = await _repository.getUserPreferenceReport(userId: userId);
      if (!mounted) {
        return;
      }
      setState(() {
        _report = report;
        _isLoading = false;
        _errorMessage = null;
      });
    } catch (_) {
      if (!mounted) {
        return;
      }
      setState(() {
        _isLoading = false;
        _errorMessage = '분석 정보를 불러오지 못했어요. 잠시 뒤 다시 확인해주세요.';
      });
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

    if (_isLoading) {
      return const Center(child: CircularProgressIndicator());
    }

    if (_errorMessage != null) {
      return Center(
        child: Text(
          _errorMessage!,
          textAlign: TextAlign.center,
          style: AppTextStyles.body2.copyWith(
            color: AppColors.textSecondary,
            fontWeight: FontWeight.w700,
            height: 1.4,
          ),
        ),
      );
    }

    final report = _report;
    if (report == null || !report.hasData) {
      return Center(
        child: Text(
          '$greetingName님의 구매 이력과 대화가 조금 더 쌓이면\n딸랑구가 분석을 정리해드릴게요.',
          textAlign: TextAlign.center,
          style: AppTextStyles.body2.copyWith(
            color: AppColors.textSecondary,
            fontWeight: FontWeight.w700,
            height: 1.4,
          ),
        ),
      );
    }

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
          if (report.summary?.trim().isNotEmpty == true) ...[
            _PreferenceSection(
              icon: Icons.summarize_rounded,
              title: '한 줄 요약',
              child: Text(
                report.summary!.trim(),
                style: AppTextStyles.caption.copyWith(
                  color: AppColors.textSecondary,
                  fontWeight: FontWeight.w700,
                  height: 1.4,
                ),
              ),
            ),
            const SizedBox(height: AppSpacing.md),
          ],
          _PreferenceSection(
            icon: Icons.auto_awesome_rounded,
            title: '관심 키워드',
            child: _ChipGroup(labels: report.interestKeywords),
          ),
          const SizedBox(height: AppSpacing.md),
          _PreferenceSection(
            icon: Icons.replay_rounded,
            title: '자주 재구매하는 상품',
            child: _ChipGroup(labels: report.repurchaseProducts),
          ),
          const SizedBox(height: AppSpacing.md),
          _PreferenceSection(
            icon: Icons.storefront_outlined,
            title: '주로 이용하는 플랫폼',
            child: _ChipGroup(labels: report.preferredPlatforms),
          ),
          const SizedBox(height: AppSpacing.md),
          _PreferenceSection(
            icon: Icons.storefront_rounded,
            title: '자주 찾는 브랜드',
            child: _ChipGroup(labels: report.preferredBrands),
          ),
          const SizedBox(height: AppSpacing.md),
          _PreferenceSection(
            icon: Icons.payments_rounded,
            title: '평균 구매가',
            child: _PriceRangeLine(priceRange: report.priceRange),
          ),
          const SizedBox(height: AppSpacing.sm),
        ],
      ),
    );
  }
}

class _PriceRangeLine extends StatelessWidget {
  const _PriceRangeLine({required this.priceRange});

  final PreferencePriceRangeModel? priceRange;

  @override
  Widget build(BuildContext context) {
    final average = priceRange?.average;
    final minPrice = priceRange?.min;
    final maxPrice = priceRange?.max;
    if (average == null || average <= 0) {
      return Text(
        '아직 쌓인 데이터가 없어요.',
        style: AppTextStyles.caption.copyWith(color: AppColors.textMuted),
      );
    }

    final hasRange =
        minPrice != null && minPrice > 0 && maxPrice != null && maxPrice > 0;
    return _StatLine(
      headline: '평균 ${_formatPrice(average)}',
      caption: hasRange
          ? '보통 ${_formatPrice(minPrice)} ~ ${_formatPrice(maxPrice)} 사이에서 구매해요'
          : '구매 이력 기준으로 계산했어요',
    );
  }

  String _formatPrice(int price) {
    final digits = price.toString();
    final buffer = StringBuffer();
    for (var index = 0; index < digits.length; index += 1) {
      final reverseIndex = digits.length - index;
      buffer.write(digits[index]);
      if (reverseIndex > 1 && reverseIndex % 3 == 1) {
        buffer.write(',');
      }
    }
    return '$buffer원';
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
