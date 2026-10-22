import 'dart:convert';
import 'dart:io';

abstract class ServiceApi {
  Future<Map<String, dynamic>> login(String username, String password);

  Future<List<Map<String, dynamic>>> services();

  Future<Map<String, dynamic>> book(String serviceId, String slot);
}

/// HTTP implementation of the service contract used by the mobile component.
/// Each call creates a short-lived client, sends a real request, checks the
/// status code, and decodes the JSON response before returning it.
class HttpServiceApi implements ServiceApi {
  final Uri baseUrl;

  HttpServiceApi(this.baseUrl);

  Future<dynamic> request(String path, [Map<String, dynamic>? body]) async {
    final client = HttpClient();
    try {
      final request = await client.openUrl(
        body == null ? 'GET' : 'POST',
        baseUrl.resolve(path),
      );
      request.headers.set(HttpHeaders.acceptHeader, ContentType.json.mimeType);
      if (body != null) {
        final bytes = utf8.encode(jsonEncode(body));
        request.headers.contentType = ContentType.json;
        request.contentLength = bytes.length;
        request.add(bytes);
      }
      final response = await request.close();
      final text = await utf8.decoder.bind(response).join();
      if (response.statusCode < 200 || response.statusCode >= 300) {
        throw StateError('api_failed');
      }
      return jsonDecode(text);
    } finally {
      client.close(force: true);
    }
  }

  @override
  Future<Map<String, dynamic>> login(String username, String password) async {
    final value = await request('/login', <String, dynamic>{
      'username': username,
      'password': password,
    });
    return Map<String, dynamic>.from(value as Map);
  }

  @override
  Future<List<Map<String, dynamic>>> services() async {
    final value = await request('/services');
    return (value as List)
        .map((dynamic row) => Map<String, dynamic>.from(row as Map))
        .toList();
  }

  @override
  Future<Map<String, dynamic>> book(String serviceId, String slot) async {
    final value = await request('/appointments', <String, dynamic>{
      'service_id': serviceId,
      'slot': slot,
    });
    return Map<String, dynamic>.from(value as Map);
  }
}
