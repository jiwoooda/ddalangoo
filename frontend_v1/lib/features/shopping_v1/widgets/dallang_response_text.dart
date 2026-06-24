import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';

class DallangResponseText extends StatelessWidget {
  const DallangResponseText({super.key, required this.text});

  final String text;

  static final RegExp _highlightPattern = RegExp(
    r'(\d[\d,]*원|\d+\s*개|가장 싼 가격|찾는 중|리뷰가 좋고|결제가 완료되었어요|배송지|비밀번호 6자리)',
  );

  @override
  Widget build(BuildContext context) {
    final spans = <TextSpan>[];
    var currentIndex = 0;
    for (final match in _highlightPattern.allMatches(text)) {
      if (match.start > currentIndex) {
        spans.add(TextSpan(text: text.substring(currentIndex, match.start)));
      }
      spans.add(
        TextSpan(
          text: match.group(0),
          style: const TextStyle(
            color: Color(0xFFFF5B98),
            fontWeight: FontWeight.w800,
          ),
        ),
      );
      currentIndex = match.end;
    }
    if (currentIndex < text.length) {
      spans.add(TextSpan(text: text.substring(currentIndex)));
    }

    return Text.rich(
      textAlign: TextAlign.center,
      TextSpan(
        style: GoogleFonts.jua(
          textStyle: const TextStyle(
            fontSize: 34,
            height: 1.38,
            color: Color(0xFF112030),
            fontWeight: FontWeight.w700,
            letterSpacing: -0.4,
          ),
        ),
        children: spans,
      ),
    );
  }
}
