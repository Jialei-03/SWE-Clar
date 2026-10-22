import 'dart:convert';
import 'dart:io';

class ApiFailure implements Exception {
  final String message;
  final int? status;
  const ApiFailure(this.message, [this.status]);
  bool get transport => status == null;
  @override
  String toString() => message;
}

class ClinicApi {
  final String origin;
  final HttpClient _client = HttpClient();
  ClinicApi(this.origin);

  Future<Map<String, dynamic>> call(String method, String path,
      {Map<String, dynamic>? body, String? token}) async {
    try {
      final request = await _client.openUrl(method, Uri.parse('$origin$path'));
      if (token != null) request.headers.set('Authorization', 'Bearer $token');
      if (body != null) {
        final bytes = utf8.encode(jsonEncode(body));
        request.headers.contentType = ContentType.json;
        request.contentLength = bytes.length;
        request.add(bytes);
      }
      final response = await request.close().timeout(const Duration(seconds: 10));
      final text = await utf8.decoder.bind(response).join().timeout(const Duration(seconds: 10));
      final value = jsonDecode(text) as Map<String, dynamic>;
      if (response.statusCode >= 400) {
        throw ApiFailure(value['error']?.toString() ?? 'request_failed', response.statusCode);
      }
      return value;
    } on ApiFailure {
      rethrow;
    } catch (_) {
      throw const ApiFailure('Connection interrupted. Retry the action or refresh.');
    }
  }

  void close() => _client.close(force: true);
}
