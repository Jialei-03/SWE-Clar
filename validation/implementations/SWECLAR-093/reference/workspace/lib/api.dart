import 'dart:async';
import 'dart:convert';
import 'dart:io';

abstract class ShopApi {
  Future<List<Map<String, dynamic>>> catalog();
  Future<List<Map<String, dynamic>>> inbox();
  Future<Map<String, dynamic>> cart();
  Future<Map<String, dynamic>> action(Map<String, dynamic> value);
  Future<Stream<Map<String, dynamic>>> connect();
  Future<void> close();
}

/// An HTTP/API failure with the structured error returned by the service.
class ShopApiException implements Exception {
  final int statusCode;
  final String code;

  const ShopApiException(this.statusCode, this.code);

  @override
  String toString() => 'ShopApiException($statusCode, $code)';
}

class HttpShopApi implements ShopApi {
  final Uri base;
  final String token;
  final HttpClient client = HttpClient();
  WebSocket? socket;

  HttpShopApi(this.base, this.token);

  Uri _endpoint(String path) => base.resolve(path);

  Future<dynamic> request(
    String method,
    String path, [
    Map<String, dynamic>? body,
  ]) async {
    final request = await client.openUrl(method, _endpoint(path));
    request.headers.set('Authorization', 'Bearer $token');
    if (body != null) {
      request.headers.contentType = ContentType.json;
      request.write(jsonEncode(body));
    }

    final response = await request.close();
    final text = await response.transform(utf8.decoder).join();
    dynamic data;
    if (text.trim().isNotEmpty) {
      try {
        data = jsonDecode(text);
      } on FormatException {
        throw const ShopApiException(0, 'invalid_response');
      }
    }

    if (response.statusCode < 200 || response.statusCode >= 300) {
      final code = data is Map && data['error'] is String
          ? data['error'] as String
          : 'request_failed';
      throw ShopApiException(response.statusCode, code);
    }
    return data;
  }

  @override
  Future<List<Map<String, dynamic>>> catalog() async {
    final value = await request('GET', '/catalog');
    if (value is! List) throw const ShopApiException(0, 'invalid_response');
    return value
        .map<Map<String, dynamic>>((item) => _mapCopy(item))
        .toList(growable: true);
  }

  @override
  Future<List<Map<String, dynamic>>> inbox() async {
    final value = await request('GET', '/inbox');
    if (value is! List) throw const ShopApiException(0, 'invalid_response');
    return value
        .map<Map<String, dynamic>>((item) => _mapCopy(item))
        .toList(growable: true);
  }

  @override
  Future<Map<String, dynamic>> cart() async {
    final value = await request('GET', '/cart');
    if (value is! Map) throw const ShopApiException(0, 'invalid_response');
    return _mapCopy(value);
  }

  @override
  Future<Map<String, dynamic>> action(Map<String, dynamic> value) async {
    final response = await request('POST', '/actions', value);
    if (response is! Map) throw const ShopApiException(0, 'invalid_response');
    return _mapCopy(response);
  }

  @override
  Future<Stream<Map<String, dynamic>>> connect() async {
    // A controller normally has one connection.  Closing an old one here also
    // prevents a reconnect from leaving a second delivery path behind.
    final previous = socket;
    socket = null;
    await previous?.close();

    final endpoint = _endpoint('/events');
    final scheme = endpoint.scheme == 'https' || endpoint.scheme == 'wss' ? 'wss' : 'ws';
    final connected = await WebSocket.connect(
      endpoint.replace(scheme: scheme).toString(),
      headers: <String, dynamic>{'Authorization': 'Bearer $token'},
    );
    socket = connected;

    return connected.map<Map<String, dynamic>>((value) {
      dynamic decoded;
      if (value is String) {
        decoded = jsonDecode(value);
      } else if (value is List<int>) {
        decoded = jsonDecode(utf8.decode(value));
      } else {
        throw const FormatException('invalid websocket message');
      }
      if (decoded is! Map) throw const FormatException('invalid websocket message');
      return _mapCopy(decoded);
    });
  }

  @override
  Future<void> close() async {
    final current = socket;
    socket = null;
    await current?.close();
    client.close(force: true);
  }
}

Map<String, dynamic> _mapCopy(Map value) {
  final result = <String, dynamic>{};
  value.forEach((key, item) {
    if (key is String) result[key] = _valueCopy(item);
  });
  return result;
}

dynamic _valueCopy(dynamic value) {
  if (value is Map) return _mapCopy(value);
  if (value is List) return value.map(_valueCopy).toList(growable: true);
  return value;
}
