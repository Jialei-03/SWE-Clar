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

  ClinicApi(String value) : origin = value.endsWith('/') ? value.substring(0, value.length - 1) : value;

  Future<Map<String, dynamic>> call(String method, String path,
      {Map<String, dynamic>? body, String? token}) async {
    try {
      final request = await _client
          .openUrl(method, Uri.parse('$origin$path'))
          .timeout(const Duration(seconds: 10));
      if (token != null) {
        request.headers.set('Authorization', 'Bearer $token');
      }
      if (body != null) {
        final bytes = utf8.encode(jsonEncode(body));
        request.headers.contentType = ContentType.json;
        // Explicit Content-Length is part of the public write transport
        // contract and avoids chunked requests to the local service.
        request.contentLength = bytes.length;
        request.add(bytes);
      }
      final response = await request
          .close()
          .timeout(const Duration(seconds: 10));
      final text = await utf8.decoder
          .bind(response)
          .join()
          .timeout(const Duration(seconds: 10));
      final decoded = jsonDecode(text);
      if (decoded is! Map) {
        throw const ApiFailure('Invalid service response.');
      }
      final value = Map<String, dynamic>.from(decoded);
      if (response.statusCode >= 400) {
        throw ApiFailure(
          value['error']?.toString() ?? 'request_failed',
          response.statusCode,
        );
      }
      return value;
    } on ApiFailure {
      rethrow;
    } catch (_) {
      throw const ApiFailure(
        'Connection interrupted. Retry the action or refresh.',
      );
    }
  }

  void close() => _client.close(force: true);
}
