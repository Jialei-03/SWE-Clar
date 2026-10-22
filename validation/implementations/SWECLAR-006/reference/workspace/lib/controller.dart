import 'dart:convert';
import 'dart:io';

import 'package:flutter/foundation.dart';

/// Makes a JSON-shaped map independent of the map supplied by its caller.
///
/// The state used by this component is deliberately JSON data rather than a
/// collection of model classes.  Going through JSON here also makes nested
/// lists and maps independent, not just the top-level map.
Map<String, dynamic> clone(Map<String, dynamic> value) {
  return jsonDecode(jsonEncode(value)) as Map<String, dynamic>;
}

abstract class BookingStorage {
  Future<void> save(Map<String, dynamic> state);

  Future<Map<String, dynamic>?> load();
}

/// A small, local JSON store.
///
/// The temporary file lives beside the destination, so a rename is an atomic
/// replacement on the supported filesystem.  A unique name prevents a stale
/// temporary file from being mistaken for a successful save.
class FileBookingStorage implements BookingStorage {
  final File file;

  FileBookingStorage(this.file);

  @override
  Future<Map<String, dynamic>?> load() async {
    if (!await file.exists()) {
      return null;
    }
    final decoded = jsonDecode(await file.readAsString());
    return Map<String, dynamic>.from(decoded as Map);
  }

  @override
  Future<void> save(Map<String, dynamic> state) async {
    await file.parent.create(recursive: true);

    // Include both a process identifier and a timestamp.  The operation is
    // local and single-process by contract, but this also avoids colliding
    // with a leftover file from an interrupted earlier operation.
    final token =
        '${pid}-${DateTime.now().microsecondsSinceEpoch}-${identityHashCode(state)}';
    final pending = File('${file.path}.tmp-$token');
    var renamed = false;
    try {
      await pending.writeAsString(jsonEncode(state), flush: true);
      await pending.rename(file.path);
      renamed = true;
    } finally {
      // rename removes the temporary path.  The check is useful for write or
      // rename failures and ensures a successful call never leaves a sibling.
      if (!renamed && await pending.exists()) {
        await pending.delete();
      }
    }
  }
}

class _RejectedAction implements Exception {
  final String code;

  const _RejectedAction(this.code);
}

Never _reject(String code) => throw _RejectedAction(code);

/// Controller for the synthetic booking workspace.
class BookingController extends ChangeNotifier {
  final BookingStorage storage;
  final String actorId;
  final String platform;

  Map<String, dynamic> _state;
  String? error;
  bool busy = false;

  BookingController(
    Map<String, dynamic> initial,
    this.storage, {
    required this.actorId,
    this.platform = 'android',
  }) : _state = clone(initial);

  /// A detached snapshot.  Mutating the returned value cannot mutate us.
  Map<String, dynamic> get snapshot => clone(_state);

  /// Restore a complete valid state from the store.
  ///
  /// A missing file is intentionally a no-op.  The supplied storage contract
  /// provides valid JSON when a file exists, so validation/corruption repair is
  /// not part of this component.
  Future<void> restore() async {
    final saved = await storage.load();
    if (saved != null) {
      _state = clone(saved);
    }
    notifyListeners();
  }

  /// Return exactly the registered screens supported by this platform.
  /// Results, including nested platform lists, are detached from the state.
  List<Map<String, dynamic>> screens() {
    final registry = _mapAt(_state, 'screens');
    final result = <Map<String, dynamic>>[];
    for (final entry in registry.entries) {
      final screenId = entry.key;
      final record = entry.value;
      if (record is! Map) continue;
      final platforms = record['platforms'];
      if (platforms is! List || !platforms.contains(platform)) continue;
      final row = Map<String, dynamic>.from(
        clone(Map<String, dynamic>.from(record)),
      );
      // The registry key is authoritative even if harmless metadata happens
      // to contain a field with this name.
      row['screen_id'] = screenId;
      result.add(row);
    }
    result.sort((left, right) {
      return (left['screen_id'] as String)
          .compareTo(right['screen_id'] as String);
    });
    return result;
  }

  /// Apply an action using save-before-publish semantics.
  Future<bool> act(Map<String, dynamic> action) async {
    // This check happens before any notification or write.  In particular, a
    // second action cannot clear the first action's error or enqueue a second
    // save while the first save is held open.
    if (busy) return false;

    final input = clone(action);
    busy = true;
    error = null;
    notifyListeners();

    Map<String, dynamic> proposed;
    try {
      proposed = apply(_state, input);
    } on _RejectedAction catch (rejection) {
      error = rejection.code;
      busy = false;
      notifyListeners();
      return false;
    } catch (_) {
      // The public input and state are JSON-shaped and valid.  Treat an
      // unexpected preparation failure as a rejected action rather than
      // publishing a partial state.
      error = 'storage_failed';
      busy = false;
      notifyListeners();
      return false;
    }

    try {
      // Give storage its own object.  It is legal for a storage implementation
      // to retain or mutate its argument after save returns.
      final savedArgument = clone(proposed);
      await storage.save(savedArgument);
      // Publish another detached copy, never the object retained by storage.
      _state = clone(proposed);
      return true;
    } catch (_) {
      error = 'storage_failed';
      return false;
    } finally {
      busy = false;
      notifyListeners();
    }
  }

  /// Public for compatibility with the starter implementation.  Actions use
  /// this same pure state transformation before saving.
  Map<String, dynamic> apply(
    Map<String, dynamic> source,
    Map<String, dynamic> action,
  ) {
    final kind = action['type'];
    final state = clone(source);
    final users = _mapAt(state, 'users');
    if (!users.containsKey(actorId)) {
      _reject('unknown_actor');
    }

    const knownActions = <String>{
      'navigate',
      'back',
      'create_booking',
      'extend',
      'confirm',
      'message',
      'admin_status',
    };
    if (kind is! String || !knownActions.contains(kind)) {
      _reject('unknown_action');
    }

    switch (kind) {
      case 'navigate':
        _applyNavigate(state, action);
        break;
      case 'back':
        _applyBack(state);
        break;
      case 'create_booking':
        _applyCreateBooking(state, action);
        break;
      case 'extend':
        _applyExtend(state, action);
        break;
      case 'confirm':
        _applyConfirm(state, action);
        break;
      case 'message':
        _applyMessage(state, action);
        break;
      case 'admin_status':
        _applyAdminStatus(state, action);
        break;
    }
    return state;
  }

  void _applyNavigate(Map<String, dynamic> state, Map<String, dynamic> action) {
    final target = action['screen_id'];
    if (target is! String || target.trim().isEmpty ||
        !_isSupportedScreen(state, target)) {
      _reject('unknown_screen');
    }

    final current = state['route'];
    if (current != target) {
      final history = _listAt(state, 'history');
      history.add(current);
      state['route'] = target;
    }
    // A navigation to the current route is an accepted no-op.  It is still
    // passed through the common save-before-publish path by act().
  }

  void _applyBack(Map<String, dynamic> state) {
    final history = _listAt(state, 'history');
    while (history.isNotEmpty) {
      final candidate = history.removeLast();
      if (candidate is String && _isSupportedScreen(state, candidate)) {
        state['route'] = candidate;
        return;
      }
    }
    // If every candidate was stale or incompatible, the current route is
    // deliberately retained and the history is empty.
  }

  void _applyCreateBooking(
    Map<String, dynamic> state,
    Map<String, dynamic> action,
  ) {
    final bookingId = action['booking_id'];
    final peerId = action['peer_id'];
    final users = _mapAt(state, 'users');
    final bookings = _mapAt(state, 'bookings');
    if (bookingId is! String || bookingId.trim().isEmpty ||
        peerId is! String || peerId.trim().isEmpty ||
        !users.containsKey(peerId) || peerId == actorId ||
        bookings.containsKey(bookingId)) {
      _reject('invalid_booking');
    }

    bookings[bookingId] = <String, dynamic>{
      'participants': <String>[actorId, peerId],
      'extension_minutes': 0,
      'extended': false,
      'confirmed': false,
      'status': 'draft',
    };
  }

  void _applyExtend(
    Map<String, dynamic> state,
    Map<String, dynamic> action,
  ) {
    final bookingId = action['booking_id'];
    final minutes = action['minutes'];
    final bookings = _mapAt(state, 'bookings');
    final booking = bookingId is String ? bookings[bookingId] : null;
    if (bookingId is! String || bookingId.trim().isEmpty ||
        booking is! Map ||
        !_isParticipant(booking, actorId) ||
        booking['status'] != 'draft' ||
        booking['confirmed'] != false ||
        booking['extended'] != false ||
        minutes is! int ||
        minutes < 1 ||
        minutes > 30) {
      _reject('extension_denied');
    }

    booking['extension_minutes'] = minutes;
    booking['extended'] = true;
  }

  void _applyConfirm(
    Map<String, dynamic> state,
    Map<String, dynamic> action,
  ) {
    final bookingId = action['booking_id'];
    final bookings = _mapAt(state, 'bookings');
    final booking = bookingId is String ? bookings[bookingId] : null;
    if (bookingId is! String || bookingId.trim().isEmpty ||
        booking is! Map ||
        !_isParticipant(booking, actorId) ||
        booking['status'] != 'draft' ||
        booking['confirmed'] != false) {
      _reject('confirmation_denied');
    }

    booking['confirmed'] = true;
    booking['status'] = 'confirmed';
  }

  void _applyMessage(
    Map<String, dynamic> state,
    Map<String, dynamic> action,
  ) {
    final bookingId = action['booking_id'];
    final messageId = action['message_id'];
    final recipientId = action['recipient_id'];
    final text = action['text'];
    final bookings = _mapAt(state, 'bookings');
    final messages = _mapAt(state, 'messages');
    final booking = bookingId is String ? bookings[bookingId] : null;

    if (bookingId is! String || bookingId.trim().isEmpty ||
        messageId is! String || messageId.trim().isEmpty ||
        recipientId is! String || recipientId.trim().isEmpty ||
        text is! String || text.trim().isEmpty ||
        booking is! Map ||
        !_isParticipant(booking, actorId) ||
        recipientId == actorId ||
        !_isParticipant(booking, recipientId)) {
      _reject('message_denied');
    }

    final proposed = <String, dynamic>{
      'booking_id': bookingId,
      'sender_id': actorId,
      'recipient_id': recipientId,
      'text': text,
    };
    final existing = messages[messageId];
    if (existing != null) {
      if (existing is Map &&
          existing['booking_id'] == proposed['booking_id'] &&
          existing['sender_id'] == proposed['sender_id'] &&
          existing['recipient_id'] == proposed['recipient_id'] &&
          existing['text'] == proposed['text']) {
        // Idempotent replay.  Do not replace metadata or reorder the record.
        return;
      }
      _reject('message_conflict');
    }

    messages[messageId] = proposed;
  }

  void _applyAdminStatus(
    Map<String, dynamic> state,
    Map<String, dynamic> action,
  ) {
    final users = _mapAt(state, 'users');
    final actor = users[actorId];
    if (actor is! Map || actor['role'] != 'admin') {
      _reject('admin_required');
    }

    final bookingId = action['booking_id'];
    final eventId = action['event_id'];
    final status = action['status'];
    final bookings = _mapAt(state, 'bookings');
    final audit = _mapAt(state, 'audit');
    final booking = bookingId is String ? bookings[bookingId] : null;
    const allowed = <String>{'draft', 'confirmed', 'cancelled', 'completed'};
    if (bookingId is! String || bookingId.trim().isEmpty ||
        eventId is! String || eventId.trim().isEmpty ||
        status is! String || !allowed.contains(status) ||
        booking is! Map) {
      _reject('invalid_status');
    }

    final existing = audit[eventId];
    if (existing != null) {
      if (existing is Map &&
          existing['booking_id'] == bookingId &&
          existing['actor_id'] == actorId &&
          existing['status'] == status) {
        // A replay is accepted but must not reapply a stale status after a
        // later, different event.
        return;
      }
      _reject('event_conflict');
    }

    audit[eventId] = <String, dynamic>{
      'booking_id': bookingId,
      'actor_id': actorId,
      'status': status,
    };
    booking['status'] = status;
    booking['confirmed'] = status == 'confirmed' || status == 'completed';
  }

  static bool _isParticipant(Map booking, String id) {
    final participants = booking['participants'];
    return participants is List && participants.contains(id);
  }

  static Map<String, dynamic> _mapAt(
    Map<String, dynamic> state,
    String field,
  ) {
    final value = state[field];
    if (value is Map<String, dynamic>) return value;
    if (value is Map) {
      final converted = Map<String, dynamic>.from(value);
      state[field] = converted;
      return converted;
    }
    final replacement = <String, dynamic>{};
    state[field] = replacement;
    return replacement;
  }

  static List<dynamic> _listAt(Map<String, dynamic> state, String field) {
    final value = state[field];
    if (value is List) return value;
    final replacement = <dynamic>[];
    state[field] = replacement;
    return replacement;
  }

  bool _isSupportedScreen(
    Map<String, dynamic> state,
    String screenId,
  ) {
    final screens = _mapAt(state, 'screens');
    final screen = screens[screenId];
    if (screen is! Map) return false;
    final platforms = screen['platforms'];
    return platforms is List && platforms.contains(platform);
  }
}
