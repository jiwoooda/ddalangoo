import 'package:flutter/material.dart';

import '../../../app/theme/app_colors.dart';
import '../../../app/theme/app_text_styles.dart';

class HighlightedSpeechText extends StatelessWidget {
  const HighlightedSpeechText({
    super.key,
    required this.text,
    this.highlightWords = const <String>[],
    this.textAlign = TextAlign.left,
    this.style,
    this.highlightStyle,
  });

  final String text;
  final List<String> highlightWords;
  final TextAlign textAlign;
  final TextStyle? style;
  final TextStyle? highlightStyle;

  @override
  Widget build(BuildContext context) {
    final baseStyle = style ?? AppTextStyles.body1;
    final emphasizedStyle =
        highlightStyle ??
        baseStyle.copyWith(
          color: AppColors.primaryPinkDark,
          fontWeight: FontWeight.w800,
        );

    return RichText(
      textAlign: textAlign,
      text: TextSpan(
        style: baseStyle,
        children: _buildSpans(
          source: text,
          baseStyle: baseStyle,
          emphasizedStyle: emphasizedStyle,
        ),
      ),
    );
  }

  List<TextSpan> _buildSpans({
    required String source,
    required TextStyle baseStyle,
    required TextStyle emphasizedStyle,
  }) {
    final words =
        highlightWords.toSet().where((word) => word.isNotEmpty).toList()
          ..sort((a, b) => b.length.compareTo(a.length));

    if (words.isEmpty) {
      return [TextSpan(text: source, style: baseStyle)];
    }

    final spans = <TextSpan>[];
    final buffer = StringBuffer();
    var index = 0;

    while (index < source.length) {
      String? matchedWord;
      for (final word in words) {
        if (source.startsWith(word, index)) {
          matchedWord = word;
          break;
        }
      }

      if (matchedWord == null) {
        buffer.write(source[index]);
        index += 1;
        continue;
      }

      if (buffer.isNotEmpty) {
        spans.add(TextSpan(text: buffer.toString(), style: baseStyle));
        buffer.clear();
      }

      spans.add(TextSpan(text: matchedWord, style: emphasizedStyle));
      index += matchedWord.length;
    }

    if (buffer.isNotEmpty) {
      spans.add(TextSpan(text: buffer.toString(), style: baseStyle));
    }

    return spans;
  }
}
