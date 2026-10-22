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
    String? token;

    do {
      final uri = endpoint('$documents/$collection').replace(
        queryParameters: <String, String>{
          'pageSize': '50',
          if (token != null) 'pageToken': token,
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
      for (final raw in (rawDocuments as List? ?? const <dynamic>[])) {
        if (raw is! Map) {
          throw const FormatException('Firestore document is not an object');
        }
        // Do not project or normalize the document here.  In particular,
        // name, fields, updateTime, and any other returned metadata remain
        // available to callers.
        result.add(Map<String, dynamic>.from(raw));
      }

      final rawToken = body['nextPageToken'];
      if (rawToken == null) {
        token = null;
      } else if (rawToken is String) {
        token = rawToken.isEmpty ? null : rawToken;
      } else {
        throw const FormatException('Firestore nextPageToken is not a string');
      }
    } while (token != null);

    return result;
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
    final targetCollection = switch (collection) {
      'providers' => 'clinics',
      'bookings' => 'providers',
      _ => null,
    };
    final relationField = switch (collection) {
      'providers' => 'clinic',
      'bookings' => 'provider',
      _ => null,
    };

    Map<String, Map<String, dynamic>> targets =
        <String, Map<String, dynamic>>{};
    if (targetCollection != null) {
      final targetDocuments = await list(targetCollection);
      targets = _indexDocuments(targetDocuments);
    }

    final rows = <Map<String, dynamic>>[];
    for (final doc in records) {
      final id = _documentId(doc);
      String? relationId;
      String? relationName;
      if (targetCollection != null && relationField != null) {
        final fields = _fields(doc);
        if (fields.containsKey(relationField)) {
          relationId = _resolveRelation(
            fields[relationField],
            targetCollection,
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
    if (value is! Map) return null;

    String? candidate;
    if (_hasOnlyKey(value, 'stringValue')) {
      final stringValue = value['stringValue'];
      if (stringValue is String && _validDocumentIdentifier(stringValue)) {
        candidate = stringValue;
      }
    } else if (_hasOnlyKey(value, 'referenceValue')) {
      final referenceValue = value['referenceValue'];
      if (referenceValue is String) {
        final prefix = '$documents/$targetCollection/';
        if (referenceValue.startsWith(prefix)) {
          final suffix = referenceValue.substring(prefix.length);
          if (_validDocumentIdentifier(suffix) &&
              referenceValue == '$prefix$suffix') {
            candidate = suffix;
          }
        }
      }
    } else if (_hasOnlyKey(value, 'mapValue')) {
      final mapValue = value['mapValue'];
      if (mapValue is Map) {
        final nestedFields = mapValue['fields'];
        if (nestedFields is Map) {
          final idValue = nestedFields['id'];
          if (idValue is Map && _hasOnlyKey(idValue, 'stringValue')) {
            final nestedId = idValue['stringValue'];
            if (nestedId is String && _validDocumentIdentifier(nestedId)) {
              candidate = nestedId;
            }
          }
        }
      }
    }

    if (candidate == null || !targets.containsKey(candidate)) return null;
    return candidate;
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
