class PreferencePriceRangeModel {
  const PreferencePriceRangeModel({this.average, this.min, this.max});

  final int? average;
  final int? min;
  final int? max;

  factory PreferencePriceRangeModel.fromJson(Map<String, dynamic> json) {
    return PreferencePriceRangeModel(
      average: json['average'] as int?,
      min: json['min'] as int?,
      max: json['max'] as int?,
    );
  }
}

class PreferenceReportModel {
  const PreferenceReportModel({
    required this.userId,
    required this.hasData,
    required this.interestKeywords,
    required this.repurchaseProducts,
    required this.preferredPlatforms,
    required this.preferredBrands,
    this.priceRange,
    this.summary,
    this.computedAt,
  });

  final int userId;
  final bool hasData;
  final List<String> interestKeywords;
  final List<String> repurchaseProducts;
  final List<String> preferredPlatforms;
  final List<String> preferredBrands;
  final PreferencePriceRangeModel? priceRange;
  final String? summary;
  final String? computedAt;

  factory PreferenceReportModel.fromJson(Map<String, dynamic> json) {
    return PreferenceReportModel(
      userId: json['userId'] as int,
      hasData: json['hasData'] == true,
      interestKeywords: _stringsOf(json['interestKeywords']),
      repurchaseProducts: _stringsOf(json['repurchaseProducts']),
      preferredPlatforms: _stringsOf(json['preferredPlatforms']),
      preferredBrands: _stringsOf(json['preferredBrands']),
      priceRange: json['priceRange'] is Map
          ? PreferencePriceRangeModel.fromJson(
              Map<String, dynamic>.from(json['priceRange'] as Map),
            )
          : null,
      summary: json['summary'] as String?,
      computedAt: json['computedAt'] as String?,
    );
  }

  static List<String> _stringsOf(Object? value) {
    return (value as List<dynamic>? ?? const <dynamic>[])
        .map((item) => item.toString().trim())
        .where((item) => item.isNotEmpty)
        .toList(growable: false);
  }
}
