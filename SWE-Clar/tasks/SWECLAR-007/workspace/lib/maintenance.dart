import 'dart:convert';
import 'package:http/http.dart' as http;

class FixtureRepository {
  final Uri origin;
  final http.Client client;
  final String project;
  FixtureRepository(String base, {http.Client? client, this.project = 'demo-sweclar'})
      : origin = Uri.parse(base), client = client ?? http.Client() {
    if (!['127.0.0.1', 'localhost'].contains(origin.host) || origin.scheme != 'http' || !project.startsWith('demo-')) {
      throw ArgumentError('A local demo emulator is required');
    }
  }
  String get documents => 'projects/$project/databases/(default)/documents';
  Uri endpoint(String path) => origin.replace(path: '/v1/$path');

  Future<Map<String, dynamic>?> getDocument(String path) async {
    final response = await client.get(endpoint('$documents/$path'));
    if (response.statusCode == 404) return null;
    if (response.statusCode != 200) throw StateError('Firestore read failed: ${response.statusCode}');
    return Map<String, dynamic>.from(jsonDecode(response.body));
  }

  Future<List<Map<String, dynamic>>> list(String collection) async {
    final result = <Map<String, dynamic>>[];
    String? token;
    do {
      final response = await client.get(endpoint('$documents/$collection').replace(queryParameters: {
        'pageSize': '50', if (token != null) 'pageToken': token,
      }));
      if (response.statusCode != 200) throw StateError('Firestore list failed: ${response.statusCode}');
      final body = jsonDecode(response.body);
      result.addAll((body['documents'] as List? ?? []).map((x) => Map<String, dynamic>.from(x)));
      token = body['nextPageToken'];
    } while (token != null && token.isNotEmpty);
    return result;
  }

  String label(Map<String, dynamic> doc) {
    final name = doc['fields']?['name']?['stringValue'];
    return name is String ? name : (doc['name'] as String).split('/').last;
  }

  // TODO: support legacy document relationships.

  Future<List<Map<String, dynamic>>> view(String collection) async {
    if (!['clinics', 'providers', 'bookings'].contains(collection)) throw ArgumentError('Unknown page');
    final records = await list(collection);
    return records.map((doc) => <String, dynamic>{
      'id': (doc['name'] as String).split('/').last,
      'name': label(doc),
      'relation_id': null,
      'relation_name': collection == 'clinics' ? null : 'Unlinked',
    }).toList();
  }

  Future<List<Map<String, String>>> normalize(String collection, String field, String targetCollection) async {
    if (![collection, field, targetCollection].every((x) => RegExp(r'^[A-Za-z_][A-Za-z0-9_]*$').hasMatch(x))) {
      throw ArgumentError('Invalid relation configuration');
    }
    throw UnimplementedError('Relation cleanup is not implemented');
  }
  void close() => client.close();
}
