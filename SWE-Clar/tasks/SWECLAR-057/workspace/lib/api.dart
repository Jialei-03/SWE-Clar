import 'dart:convert';
import 'dart:io';

abstract class ServiceApi {
  Future<Map<String, dynamic>> login(String username, String password);
  Future<List<Map<String, dynamic>>> services();
  Future<Map<String, dynamic>> book(String serviceId, String slot);
}

class HttpServiceApi implements ServiceApi {
  final Uri baseUrl;
  HttpServiceApi(this.baseUrl);
  Future<dynamic> request(String path, [Map<String, dynamic>? body]) async {
    final client = HttpClient();
    try {
      final request = await client.openUrl(body == null ? 'GET' : 'POST', baseUrl.resolve(path));
      if (body != null) {
        request.headers.contentType = ContentType.json;
        request.write(jsonEncode(body));
      }
      final response = await request.close();
      final text = await utf8.decoder.bind(response).join();
      if (response.statusCode < 200 || response.statusCode >= 300) throw StateError('api_failed');
      return jsonDecode(text);
    } finally { client.close(force: true); }
  }
  @override
  Future<Map<String, dynamic>> login(String username, String password) async =>
      Map<String, dynamic>.from(await request('/login', {'username': username, 'password': password}));
  @override
  Future<List<Map<String, dynamic>>> services() async =>
      (await request('/services') as List).map((row) => Map<String, dynamic>.from(row)).toList();
  @override
  Future<Map<String, dynamic>> book(String serviceId, String slot) async =>
      Map<String, dynamic>.from(await request('/appointments', {'service_id': serviceId, 'slot': slot}));
}
