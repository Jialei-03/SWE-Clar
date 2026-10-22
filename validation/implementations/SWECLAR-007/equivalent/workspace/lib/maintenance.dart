import 'dart:convert';

import 'package:http/http.dart' as http;

/// A small Firestore REST repository used by the maintenance application.
///
/// The repository deliberately deals in Firestore's wire-format documents
/// rather than converting fields into Dart primitives.  That keeps reads
/// lossless and, in turn, lets normalization replace only the configured
/// relation field while retaining every other typed value in a document.
class FixtureRepository {
  static final RegExp _configurationIdentifier = RegExp(
    r'^[A-Za-z_][A-Za-z0-9_]*$',
  );
  static final RegExp _documentIdentifier = RegExp(r'^[A-Za-z0-9_-]+$');
  static const Map<String, _RelationSpec>
  _relationSpecs = <String, _RelationSpec>{
    'providers': _RelationSpec(field: 'clinic', targetCollection: 'clinics'),
    'bookings': _RelationSpec(field: 'provider', targetCollection: 'providers'),
  };

  final Uri origin;
  final http.Client client;
  final String project;

  FixtureRepository(
    String base, {
    http.Client? client,
    this.project = 'demo-sweclar',
  }) : origin = Uri.parse(base),
       client = client ?? http.Client() {
    if (!['127.0.0.1', 'localhost'].contains(origin.host) ||
        origin.scheme != 'http' ||
        !project.startsWith('demo-')) {
      throw ArgumentError('A local demo emulator is required');
    }
  }

  /// The Firestore REST resource prefix for this repository's database.
  String get documents => 'projects/$project/databases/(default)/documents';

  Uri endpoint(String path) => origin.replace(path: '/v1/$path');

  Future<Map<String, dynamic>?> getDocument(String path) async {
    final response = await client.get(endpoint('$documents/$path'));
    if (response.statusCode == 404) return null;
    if (response.statusCode != 200) {
      throw StateError('Firestore read failed: ${response.statusCode}');
    }
    return _decodeDocument(response.body);
  }

  /// Lists all documents in [collection], following the REST page token until
  /// the collection is exhausted.
  Future<List<Map<String, dynamic>>> list(String collection) async {
    final result = <Map<String, dynamic>>[];
    String? pageToken;

    while (true) {
      final page = await _readCollectionPage(collection, pageToken);
      result.addAll(page.documents);
      pageToken = page.nextPageToken;
      if (pageToken == null) return result;
    }
  }

  Future<_DocumentPage> _readCollectionPage(
    String collection,
    String? pageToken,
  ) async {
    final uri = endpoint('$documents/$collection').replace(
      queryParameters: <String, String>{
        'pageSize': '50',
        if (pageToken != null) 'pageToken': pageToken,
      },
    );
    final response = await client.get(uri);
    if (response.statusCode != 200) {
      throw StateError('Firestore list failed: ${response.statusCode}');
    }

    final decoded = jsonDecode(response.body);
    if (decoded is! Map) {
      throw const FormatException('Firestore list response is not an object');
    }
    final body = Map<String, dynamic>.from(decoded);
    final rawDocuments = body['documents'];
    if (rawDocuments != null && rawDocuments is! List) {
      throw const FormatException('Firestore documents is not a list');
    }

    final pageDocuments = <Map<String, dynamic>>[];
    for (final raw in (rawDocuments as List? ?? const <dynamic>[])) {
      if (raw is! Map) {
        throw const FormatException('Firestore document is not an object');
      }
      // Keep the complete Firestore wire document.  The caller needs name,
      // fields, updateTime, and any other metadata for lossless operations.
      pageDocuments.add(Map<String, dynamic>.from(raw));
    }

    final rawNextPageToken = body['nextPageToken'];
    final nextPageToken = switch (rawNextPageToken) {
      null => null,
      String token when token.isNotEmpty => token,
      String() => null,
      _ => throw const FormatException(
        'Firestore nextPageToken is not a string',
      ),
    };
    return _DocumentPage(pageDocuments, nextPageToken);
  }

  /// Returns the display label for a Firestore document.
  ///
  /// An explicitly typed string, including the empty string, is a real name;
  /// only a missing or differently typed name falls back to the document ID.
  String label(Map<String, dynamic> doc) {
    final id = _documentId(doc);
    final fields = _fields(doc);
    final rawName = fields['name'];
    final name = _stringValue(rawName);
    return name ?? id;
  }

  Future<List<Map<String, dynamic>>> view(String collection) async {
    if (!const <String>[
      'clinics',
      'providers',
      'bookings',
    ].contains(collection)) {
      throw ArgumentError('Unknown page');
    }

    final records = await list(collection);
    final relation = _relationSpecs[collection];
    final targets = relation == null
        ? <String, Map<String, dynamic>>{}
        : _indexDocuments(await list(relation.targetCollection));

    final rows = <Map<String, dynamic>>[];
    for (final doc in records) {
      final id = _documentId(doc);
      String? relationId;
      String? relationName;
      if (relation != null) {
        final fields = _fields(doc);
        if (fields.containsKey(relation.field)) {
          relationId = _resolveRelation(
            fields[relation.field],
            relation.targetCollection,
            targets,
          );
        }
        relationName = relationId == null
            ? 'Unlinked'
            : label(targets[relationId]!);
      }

      rows.add(<String, dynamic>{
        'id': id,
        'name': label(doc),
        'relation_id': relationId,
        'relation_name': relationName,
      });
    }

    rows.sort(
      (a, b) => _compareDocumentIds(a['id'] as String, b['id'] as String),
    );
    return rows;
  }

  /// Normalizes one top-level relation field in one atomic Firestore commit.
  ///
  /// Reads retain Firestore's typed values.  A changed source document is
  /// written in full with its original fields (apart from the configured
  /// relation) and an update-time precondition, so a concurrent edit causes
  /// the complete commit to fail rather than being overwritten.
  Future<List<Map<String, String>>> normalize(
    String collection,
    String field,
    String targetCollection,
  ) async {
    // Validate all configuration before even beginning a migration.  This is
    // intentionally before any possible write and also avoids issuing reads
    // for a request that cannot be valid.
    if (!_validConfigurationIdentifier(collection) ||
        !_validConfigurationIdentifier(field) ||
        !_validConfigurationIdentifier(targetCollection)) {
      throw ArgumentError('Invalid relation configuration');
    }

    final sourceDocuments = await list(collection);
    final targetDocuments = await list(targetCollection);
    final targets = _indexDocuments(targetDocuments);

    final changes = <_DocumentChange>[];
    final reports = <Map<String, String>>[];

    for (final document in sourceDocuments) {
      final fields = _fields(document);
      if (!fields.containsKey(field)) {
        // A missing relation is not a dangling relation.  Leave the source
        // completely untouched and do not include it in the report.
        continue;
      }

      final relationId = _resolveRelation(
        fields[field],
        targetCollection,
        targets,
      );
      if (relationId != null && _isStringRelation(fields[field], relationId)) {
        // This is already the canonical representation and needs no write.
        continue;
      }

      final newFields = Map<String, dynamic>.from(fields);
      if (relationId == null) {
        newFields.remove(field);
        reports.add(<String, String>{
          'document': _documentId(document),
          'field': field,
          'reason': 'dangling_relation',
        });
      } else {
        newFields[field] = <String, dynamic>{'stringValue': relationId};
      }

      final documentName = document['name'];
      final updateTime = document['updateTime'];
      if (documentName is! String || documentName.isEmpty) {
        throw const FormatException('Source document has no resource name');
      }
      if (updateTime is! String || updateTime.isEmpty) {
        throw const FormatException('Changed source has no updateTime');
      }
      changes.add(
        _DocumentChange(
          id: _documentId(document),
          name: documentName,
          fields: newFields,
          updateTime: updateTime,
        ),
      );
    }

    if (changes.isEmpty) {
      // In particular, do not issue an empty commit on a repeat migration.
      return const <Map<String, String>>[];
    }

    changes.sort((a, b) => _compareDocumentIds(a.id, b.id));
    reports.sort((a, b) => _compareDocumentIds(a['document']!, b['document']!));

    final body = <String, dynamic>{
      'writes': <Map<String, dynamic>>[
        for (final change in changes)
          <String, dynamic>{
            'update': <String, dynamic>{
              'name': change.name,
              'fields': change.fields,
            },
            'currentDocument': <String, dynamic>{
              'updateTime': change.updateTime,
            },
          },
      ],
    };

    final response = await client.post(
      endpoint('$documents:commit'),
      headers: const <String, String>{'Content-Type': 'application/json'},
      body: jsonEncode(body),
    );
    if (response.statusCode != 200) {
      // The REST commit is atomic.  Propagate the failure; callers must not
      // receive a report that could be mistaken for a successful migration.
      throw StateError('Firestore commit failed: ${response.statusCode}');
    }

    return reports;
  }

  void close() => client.close();

  bool _validConfigurationIdentifier(String value) {
    final match = _configurationIdentifier.firstMatch(value);
    return match != null && match.group(0) == value;
  }

  bool _validDocumentIdentifier(String value) =>
      _documentIdentifier.hasMatch(value) &&
      _documentIdentifier.firstMatch(value)?.group(0) == value;

  Map<String, dynamic> _decodeDocument(String body) {
    final decoded = jsonDecode(body);
    if (decoded is! Map) {
      throw const FormatException(
        'Firestore document response is not an object',
      );
    }
    return Map<String, dynamic>.from(decoded);
  }

  Map<String, dynamic> _fields(Map<String, dynamic> document) {
    final rawFields = document['fields'];
    if (rawFields == null) return <String, dynamic>{};
    if (rawFields is! Map) {
      throw const FormatException('Firestore fields is not an object');
    }
    return Map<String, dynamic>.from(rawFields);
  }

  String _documentId(Map<String, dynamic> document) {
    final name = document['name'];
    if (name is! String || name.isEmpty) {
      throw const FormatException('Firestore document has no resource name');
    }
    final slash = name.lastIndexOf('/');
    if (slash < 0 || slash == name.length - 1) {
      throw const FormatException('Firestore document has no document ID');
    }
    return name.substring(slash + 1);
  }

  String? _stringValue(dynamic value) {
    if (value is! Map || !_hasOnlyKey(value, 'stringValue')) return null;
    final raw = value['stringValue'];
    return raw is String ? raw : null;
  }

  Map<String, Map<String, dynamic>> _indexDocuments(
    List<Map<String, dynamic>> documents,
  ) {
    final result = <String, Map<String, dynamic>>{};
    for (final document in documents) {
      final id = _documentId(document);
      result[id] = document;
    }
    return result;
  }

  /// Resolves a legacy relation to a target ID, or returns null when it is
  /// absent from the target set or is not one of the three accepted formats.
  String? _resolveRelation(
    dynamic value,
    String targetCollection,
    Map<String, Map<String, dynamic>> targets,
  ) {
    final candidate = _relationCandidate(value, targetCollection);
    return candidate != null && targets.containsKey(candidate)
        ? candidate
        : null;
  }

  /// Extracts an ID without consulting the target index.  Keeping extraction
  /// separate from existence checking makes the same compatibility rules serve
  /// both page rendering and atomic normalization.
  String? _relationCandidate(dynamic value, String targetCollection) {
    if (value is! Map) return null;

    if (_hasOnlyKey(value, 'stringValue')) {
      return _validCandidate(value['stringValue']);
    }

    if (_hasOnlyKey(value, 'referenceValue')) {
      final referenceValue = value['referenceValue'];
      if (referenceValue is! String) return null;
      final prefix = '$documents/$targetCollection/';
      if (!referenceValue.startsWith(prefix)) return null;
      final suffix = referenceValue.substring(prefix.length);
      final candidate = _validCandidate(suffix);
      return candidate != null && referenceValue == '$prefix$suffix'
          ? candidate
          : null;
    }

    if (!_hasOnlyKey(value, 'mapValue')) return null;
    final mapValue = value['mapValue'];
    if (mapValue is! Map) return null;
    final nestedFields = mapValue['fields'];
    if (nestedFields is! Map) return null;
    final idValue = nestedFields['id'];
    if (idValue is! Map || !_hasOnlyKey(idValue, 'stringValue')) {
      return null;
    }
    return _validCandidate(idValue['stringValue']);
  }

  String? _validCandidate(dynamic value) {
    return value is String && _validDocumentIdentifier(value) ? value : null;
  }

  bool _hasOnlyKey(Map<dynamic, dynamic> value, String key) =>
      value.length == 1 && value.containsKey(key);

  bool _isStringRelation(dynamic value, String id) {
    if (value is! Map || !_hasOnlyKey(value, 'stringValue')) return false;
    return value['stringValue'] == id && value['stringValue'] is String;
  }

  int _compareDocumentIds(String left, String right) {
    final leftRunes = left.runes.toList(growable: false);
    final rightRunes = right.runes.toList(growable: false);
    final length = leftRunes.length < rightRunes.length
        ? leftRunes.length
        : rightRunes.length;
    for (var i = 0; i < length; i++) {
      final comparison = leftRunes[i].compareTo(rightRunes[i]);
      if (comparison != 0) return comparison;
    }
    return leftRunes.length.compareTo(rightRunes.length);
  }
}

class _RelationSpec {
  final String field;
  final String targetCollection;

  const _RelationSpec({required this.field, required this.targetCollection});
}

class _DocumentPage {
  final List<Map<String, dynamic>> documents;
  final String? nextPageToken;

  const _DocumentPage(this.documents, this.nextPageToken);
}

class _DocumentChange {
  final String id;
  final String name;
  final Map<String, dynamic> fields;
  final String updateTime;

  const _DocumentChange({
    required this.id,
    required this.name,
    required this.fields,
    required this.updateTime,
  });
}
