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
    r'(\d[\d,]*원|\d+\s*개|가장 싼 가격|찾는 중|리뷰가 좋고|결제가 완료되었어요|배송지|비밀번호 6자리)',
  );

  @override
  Widget build(BuildContext context) {
    final balancedText = _balanceTextByWords(text);
    final spans = <TextSpan>[];
    var currentIndex = 0;
    for (final match in _highlightPattern.allMatches(balancedText)) {
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
