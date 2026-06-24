import 'package:flutter/material.dart';

import '../models/shopping_v1_models.dart';

class ProductCard extends StatelessWidget {
  const ProductCard({super.key, required this.product});

  final ProductViewData product;

  @override
  Widget build(BuildContext context) {
    final overlayLabel = product.platform ?? '쇼핑 플랫폼';
    final overlayLogoAsset = _logoAssetFor(product.platform);
    final quantityText = product.displayQuantityInfo;

    return LayoutBuilder(
      builder: (context, constraints) {
        return Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Expanded(
              flex: 7,
              child: SizedBox(
                width: double.infinity,
                child: Stack(
                  children: [
                    Positioned.fill(
                      child: ClipRRect(
                        borderRadius: BorderRadius.circular(0),
                        child: product.imageUrl == null
                            ? _placeholder()
                            : Image.network(
                                product.imageUrl!,
                                fit: BoxFit.cover,
                                errorBuilder: (context, error, stackTrace) =>
                                    _placeholder(),
                              ),
                      ),
                    ),
                    Positioned(
                      top: 0,
                      left: 0,
                      child: _PlatformOverlayBadge(
                        label: overlayLabel,
                        logoAsset: overlayLogoAsset,
                      ),
                    ),
                  ],
                ),
              ),
            ),
            const SizedBox(height: 16),
            Flexible(
              flex: 3,
              child: Padding(
                padding: const EdgeInsets.symmetric(horizontal: 16),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  mainAxisAlignment: MainAxisAlignment.start,
                  children: [
                    Text(
                      product.displayTitle,
                      maxLines: 4,
                      overflow: TextOverflow.ellipsis,
                      textAlign: TextAlign.left,
                      style: const TextStyle(
                        fontFamily: 'Pretendard',
                        fontSize: 24,
                        fontWeight: FontWeight.w900,
                        color: Color(0xFF111111),
                        height: 1.25,
                      ),
                    ),
                    if (quantityText.isNotEmpty) ...[
                      const SizedBox(height: 10),
                      RichText(
                        maxLines: 2,
                        overflow: TextOverflow.ellipsis,
                        textAlign: TextAlign.left,
                        text: TextSpan(
                          style: const TextStyle(
                            fontFamily: 'Pretendard',
                            fontSize: 18,
                            fontWeight: FontWeight.w500,
                            color: Color(0xFF7A7A7A),
                            height: 1.4,
                          ),
                          children: [
                            const TextSpan(text: '개당 중량 x 수량 '),
                            TextSpan(
                              text: quantityText,
                              style: const TextStyle(
                                color: Color(0xFF111111),
                                fontWeight: FontWeight.w800,
                              ),
                            ),
                          ],
                        ),
                      ),
                    ],
                    const SizedBox(height: 8),
                    RichText(
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                      textAlign: TextAlign.left,
                      text: TextSpan(
                        style: const TextStyle(
                          fontFamily: 'Pretendard',
                          fontSize: 18,
                          fontWeight: FontWeight.w500,
                          color: Color(0xFF7A7A7A),
                          height: 1.4,
                        ),
                        children: [
                          const TextSpan(text: '총 가격 '),
                          TextSpan(
                            text: product.displayPrice,
                            style: const TextStyle(
                              color: Color(0xFF111111),
                              fontWeight: FontWeight.w800,
                            ),
                          ),
                        ],
                      ),
                    ),
                  ],
                ),
              ),
            ),
          ],
        );
      },
    );
  }

  Widget _placeholder() {
    return Container(
      color: const Color(0xFFF4F5F7),
      alignment: Alignment.center,
      child: const Icon(
        Icons.shopping_bag_rounded,
        size: 72,
        color: Color(0xFFBEC9D4),
      ),
    );
  }

  String? _logoAssetFor(String? platform) {
    switch (platform?.trim().toLowerCase()) {
      case 'naver':
      case '네이버':
        return 'assets/images/naver.png';
      case 'coupang':
        return 'assets/images/coupang.png';
      case 'kurly':
        return 'assets/images/kurly.png';
      case '컬리N마트':
      case 'kurlynmart':
        return 'assets/images/kurlynmart.png';
      default:
        return null;
    }
  }
}

class _PlatformOverlayBadge extends StatelessWidget {
  const _PlatformOverlayBadge({required this.label, this.logoAsset});

  final String label;
  final String? logoAsset;

  @override
  Widget build(BuildContext context) {
    if (logoAsset != null) {
      return Container(
        color: Colors.white,
        child: Image.asset(
          logoAsset!,
          width: 92,
          height: 92,
          fit: BoxFit.contain,
        ),
      );
    }

    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
      decoration: BoxDecoration(
        color: Colors.white.withValues(alpha: 0.94),
        borderRadius: BorderRadius.circular(999),
      ),
      child: Text(
        _balanceWords(label, targetCharsPerLine: 6),
        textAlign: TextAlign.center,
        style: const TextStyle(
          fontFamily: 'Pretendard',
          fontSize: 20,
          fontWeight: FontWeight.w800,
          color: Color(0xFF334152),
        ),
      ),
    );
  }
}

String _balanceWords(String source, {int targetCharsPerLine = 14}) {
  final normalized = source
      .replaceAll('\n', ' ')
      .replaceAll(RegExp(r'\s+'), ' ')
      .trim();
  if (normalized.isEmpty || !normalized.contains(' ')) {
    return normalized;
  }

  final tokens = normalized.split(' ');
  final lines = <String>[];
  final buffer = StringBuffer();

  for (final token in tokens) {
    final candidate = buffer.isEmpty ? token : '${buffer.toString()} $token';
    if (buffer.isNotEmpty && candidate.runes.length > targetCharsPerLine) {
      lines.add(buffer.toString());
      buffer
        ..clear()
        ..write(token);
      continue;
    }

    if (buffer.isNotEmpty) {
      buffer.write(' ');
    }
    buffer.write(token);
  }

  if (buffer.isNotEmpty) {
    lines.add(buffer.toString());
  }

  return lines.join('\n');
}
