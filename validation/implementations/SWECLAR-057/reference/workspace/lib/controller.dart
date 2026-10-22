import 'package:flutter/foundation.dart';

import 'api.dart';

/// The routes that can be displayed by [ServiceApp].
const Set<String> _knownRoutes = <String>{
  'login',
  'dashboard',
  'appointments',
  'notifications',
};

/// Make a defensive, recursively copied value from data returned by an API or
/// supplied by a caller.  The controller owns the data it exposes through its
/// public fields; in particular, notification state must not alias the map
/// passed to the constructor.
dynamic _copyValue(dynamic value) {
  if (value is Map) {
    return <String, dynamic>{
      for (final entry in value.entries)
        entry.key.toString(): _copyValue(entry.value),
    };
  }
  if (value is List) {
    return value.map<dynamic>(_copyValue).toList();
  }
  return value;
}

Map<String, dynamic> _copyMap(Map value) =>
    Map<String, dynamic>.from(_copyValue(value) as Map);

class ServiceController extends ChangeNotifier {
  final ServiceApi api;

  Map<String, dynamic>? user;
  String route = 'login';
  String? error;
  bool busy = false;
  List<Map<String, dynamic>> services = <Map<String, dynamic>>[];
  final Map<String, Map<String, dynamic>> appointments =
      <String, Map<String, dynamic>>{};
  final Map<String, Map<String, dynamic>> notifications;

  // A logout starts a new session.  Both the session number and operation
  // number are checked when an asynchronous request completes, so an old
  // request cannot update a newer session (or a controller that was disposed).
  int _session = 0;
  int _nextOperation = 0;
  int? _activeOperation;
  bool _disposed = false;

  ServiceController(
    this.api, {
    Map<String, Map<String, dynamic>>? notifications,
  }) : notifications = <String, Map<String, dynamic>>{
         for (final entry
             in (notifications ?? <String, Map<String, dynamic>>{}).entries)
           entry.key: _copyMap(entry.value),
       };

  void _notify() {
    if (!_disposed) {
      notifyListeners();
    }
  }

  bool _isCurrent(int session, int operation) =>
      !_disposed && _session == session && _activeOperation == operation;

  int _startOperation() {
    final operation = ++_nextOperation;
    _activeOperation = operation;
    busy = true;
    error = null;
    _notify();
    return operation;
  }

  void _finishOperation(int session, int operation) {
    if (!_isCurrent(session, operation)) return;
    _activeOperation = null;
    busy = false;
    _notify();
  }

  void _setError(String value) {
    if (_disposed) return;
    error = value;
    _notify();
  }

  /// Validate and defensively copy a service catalog before it is committed.
  /// A catalog is only useful to the UI when every entry has the public API
  /// shape promised by the service contract.
  List<Map<String, dynamic>> _validatedServices(
    List<Map<String, dynamic>> response,
  ) {
    final result = <Map<String, dynamic>>[];
    for (final raw in response) {
      final row = _copyMap(raw);
      final id = row['id'];
      final title = row['title'];
      final slots = row['available_slots'];
      if (id is! String ||
          id.isEmpty ||
          title is! String ||
          slots is! List ||
          slots.any((dynamic slot) => slot is! String)) {
        throw const FormatException('invalid_service');
      }
      result.add(row);
    }
    return result;
  }

  /// Log in and load the catalog as one guarded operation.  Neither the user
  /// nor the catalog is committed until both responses have been validated.
  Future<void> login(String username, String password) async {
    if (_disposed || busy) return;

    final session = _session;
    final operation = _startOperation();
    try {
      final response = await api.login(username, password);
      if (!_isCurrent(session, operation)) return;

      final id = response['id'];
      if (id is! String || id.isEmpty) {
        throw const FormatException('invalid_user');
      }
      final nextUser = _copyMap(response);

      final responseServices = await api.services();
      if (!_isCurrent(session, operation)) return;
      final nextServices = _validatedServices(responseServices);

      if (!_isCurrent(session, operation)) return;
      user = nextUser;
      services = nextServices;
      route = 'dashboard';
      error = null;
    } catch (_) {
      // A request invalidated by logout/disposal is deliberately silent.  In
      // particular it must not restore a user or replace a newer error.
      if (_isCurrent(session, operation)) {
        error = 'api_failed';
      }
    } finally {
      _finishOperation(session, operation);
    }
  }

  /// Navigate to a known route, applying the authentication guard before
  /// changing either the route or the visible error state.
  void navigate(String destination) {
    if (_disposed) return;
    if (!_knownRoutes.contains(destination)) {
      _setError('unknown_route');
      return;
    }
    if (destination != 'login' && user == null) {
      _setError('authentication_required');
      return;
    }
    route = destination;
    error = null;
    _notify();
  }

  /// End the current session immediately.  The session counter invalidates
  /// every in-flight request before any of the visible state is reset.
  void logout() {
    if (_disposed) return;
    _session++;
    _activeOperation = null;
    busy = false;
    user = null;
    route = 'login';
    services = <Map<String, dynamic>>[];
    appointments.clear();
    error = null;
    _notify();
  }

  Map<String, dynamic>? _findService(String serviceId) {
    for (final service in services) {
      if (service['id'] == serviceId) return service;
    }
    return null;
  }

  bool _alreadyBooked(String serviceId, String slot) {
    for (final appointment in appointments.values) {
      if (appointment['service_id'] == serviceId &&
          appointment['slot'] == slot) {
        return true;
      }
    }
    return false;
  }

  bool _alreadyUsedAppointmentId(String id) {
    if (appointments.containsKey(id)) return true;
    return appointments.values.any((appointment) => appointment['id'] == id);
  }

  /// Book one slot after validating it against the loaded catalog.  Local
  /// validation happens before [ServiceApi.book], which keeps invalid actions
  /// from producing network calls and gives retryable API failures a stable
  /// state to return to.
  Future<void> book(String serviceId, String slot) async {
    if (_disposed || busy) return;

    if (user == null) {
      _setError('authentication_required');
      return;
    }

    final service = _findService(serviceId);
    if (service == null) {
      _setError('unknown_service');
      return;
    }

    final slots = service['available_slots'];
    if (slots is! List || !slots.contains(slot)) {
      _setError('unavailable_slot');
      return;
    }

    if (_alreadyBooked(serviceId, slot)) {
      _setError('duplicate_appointment');
      return;
    }

    final session = _session;
    final operation = _startOperation();
    try {
      final response = await api.book(serviceId, slot);
      if (!_isCurrent(session, operation)) return;

      final appointment = _copyMap(response);
      final id = appointment['id'];
      if (id is! String ||
          id.isEmpty ||
          _alreadyUsedAppointmentId(id) ||
          appointment['service_id'] != serviceId ||
          appointment['slot'] != slot ||
          _alreadyBooked(serviceId, slot)) {
        throw const FormatException('invalid_appointment');
      }

      appointments[id] = appointment;
      route = 'appointments';
      error = null;
    } catch (_) {
      if (_isCurrent(session, operation)) {
        error = 'api_failed';
      }
    } finally {
      _finishOperation(session, operation);
    }
  }

  String? _notificationDestination(Map<String, dynamic> notification) {
    // `route` is the compact form used by the original component.  Accepting
    // `destination` (and the descriptive `destination_route`) keeps the data
    // contract tolerant without changing the copied notification map.
    final routeValue = notification['route'];
    if (routeValue is String) return routeValue;
    final destination = notification['destination'];
    if (destination is String) return destination;
    final destinationRoute = notification['destination_route'];
    if (destinationRoute is String) return destinationRoute;
    return null;
  }

  /// Mark one valid notification as read and navigate to its destination.
  /// All validation occurs before mutating the notification map.
  void openNotification(String id) {
    if (_disposed) return;
    if (user == null) {
      _setError('authentication_required');
      return;
    }

    final notification = notifications[id];
    if (notification == null) {
      _setError('unknown_notification');
      return;
    }

    final destination = _notificationDestination(notification);
    if (destination == null || !_knownRoutes.contains(destination)) {
      _setError('unknown_route');
      return;
    }

    notification['read'] = true;
    route = destination;
    error = null;
    _notify();
  }

  @override
  void dispose() {
    _disposed = true;
    _session++;
    _activeOperation = null;
    busy = false;
    super.dispose();
  }
}
