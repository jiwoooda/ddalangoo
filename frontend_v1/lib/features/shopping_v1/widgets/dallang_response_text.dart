import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';

class DallangResponseText extends StatelessWidget {
  const DallangResponseText({
    super.key,
    required this.text,
    this.fontSize = 34,
    this.maxLines,
  });

  final String text;
  final double fontSize;
  final int? maxLines;

  static final RegExp _highlightPattern = RegExp(
    r'('
    //r'[가-힣A-Za-z0-9]+\s*님|'
    r'\d[\d,]*원|'
    r'\d+\s*개|'
    r'\d+\s*자리|'
    r'몇 개|'
    r'가장 싼|'
    r'최저가|'
    r'리뷰가 좋고|'
    r'인기 있는|'
    r'6자리|'
    r'진행 중|'
    r'결제가 완료|'
    r'주문이 완료|'
    r'구매를 완료|'
    r'구매가 완료|'
    r'다른 상품|'
    r')',
  );
  static final RegExp _searchKeywordPattern = RegExp(
    r'([^.!?。！？\n]+?)(?=(?:을|를)\s*찾고 있어요)|([^.!?。！？\n]+?)(?=\s*님)',
  );

  @override
  Widget build(BuildContext context) {
    final balancedText = _balanceTextByWords(text);
    final matches =
        <RegExpMatch>[
          ..._highlightPattern.allMatches(balancedText),
          ..._searchKeywordPattern.allMatches(balancedText),
        ]..sort((a, b) {
          final startCompare = a.start.compareTo(b.start);
          if (startCompare != 0) {
            return startCompare;
          }
          return a.end.compareTo(b.end);
        });

    final spans = <TextSpan>[];
    var currentIndex = 0;
    for (final match in matches) {
      if (match.start < currentIndex) {
        continue;
      }
      if (match.start > currentIndex) {
        spans.add(
          TextSpan(text: balancedText.substring(currentIndex, match.start)),
        );
      }
      spans.add(
        TextSpan(
          text: match.group(0),
          style: const TextStyle(
            color: Color(0xFFD77B9E),
            fontWeight: FontWeight.w800,
          ),
        ),
      );
      currentIndex = match.end;
    }
    if (currentIndex < balancedText.length) {
      spans.add(TextSpan(text: balancedText.substring(currentIndex)));
    }

    return Text.rich(
      TextSpan(
        style: GoogleFonts.jua(
          textStyle: TextStyle(
            fontSize: fontSize,
            height: 1.38,
            color: const Color(0xFF112030),
            fontWeight: FontWeight.w700,
            letterSpacing: -0.4,
          ),
        ),
        children: spans,
      ),
      textAlign: TextAlign.center,
      maxLines: maxLines,
      overflow: maxLines != null ? TextOverflow.ellipsis : TextOverflow.visible,
    );
  }
}

String _balanceTextByWords(String source, {int targetCharsPerLine = 13}) {
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
