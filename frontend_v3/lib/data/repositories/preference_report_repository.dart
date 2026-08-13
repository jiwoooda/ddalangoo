import 'package:dio/dio.dart';

import '../../core/network/api_client.dart';
import '../models/preference_report_model.dart';

class PreferenceReportRepository {
  PreferenceReportRepository({Dio? dio}) : _dio = dio ?? ApiClient.dio;

  final Dio _dio;

  Future<PreferenceReportModel> getUserPreferenceReport({
    required int userId,
  }) async {
    final response = await _dio.get('/api/users/$userId/preference-report');
    return PreferenceReportModel.fromJson(
      Map<String, dynamic>.from(response.data as Map),
    );
  }
}
