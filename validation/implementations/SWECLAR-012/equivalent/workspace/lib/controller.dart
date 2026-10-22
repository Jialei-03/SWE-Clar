import 'dart:math';

import 'package:flutter/foundation.dart';

import 'api.dart';

class ClinicController extends ChangeNotifier {
  final ClinicApi api;
  ClinicController({required String origin}) : api = ClinicApi(origin);

  bool busy = false;
  String? error;
  String? token;
  Map<String, dynamic>? user;
  List<Map<String, dynamic>> clinics = [];
  List<Map<String, dynamic>> providers = [];
  List<Map<String, dynamic>> slots = [];
  List<Map<String, dynamic>> appointments = [];
  List<Map<String, dynamic>> moveSlots = [];
  String? clinicId;
  String? providerId;
  String? moveSlotId;
  String page = 'availability';
  String? dialog;
  Map<String, dynamic>? dialogAppointment;
  int nowMs = 0;

  Future<void> _pending = Future<void>.value();

  // Action IDs are client-generated opaque identifiers.  They are deliberately
  // kept in controller state so a lost HTTP response can be retried exactly.
  static final Random _random = Random.secure();
  static int _actionCounter = 0;
  String? _pendingBookingSlotId;
  String? _pendingBookingRequestId;
  String? _pendingMoveAppointmentId;
  String? _pendingMoveTargetId;
  int? _pendingMoveRevision;
  String? _pendingMoveOperationId;

  Future<void> settle() => _pending;

  List<Map<String, dynamic>> rows(dynamic value) =>
      (value as List).map((e) => Map<String, dynamic>.from(e as Map)).toList();

  String _actionId(String prefix) {
    final counter = ++_actionCounter;
    final random = _random.nextInt(1 << 32).toRadixString(16);
    // The prefix and separators are in the public identifier alphabet and the
    // total length remains comfortably below 64 characters.
    return '${prefix}_${counter}_$random';
  }

  Future<void> run(Future<void> Function() work) {
    if (busy) return _pending;
    busy = true;
    error = null;
    notifyListeners();
    _pending = () async {
      try {
        await work();
      } catch (failure) {
        error = failure.toString();
      } finally {
        busy = false;
        notifyListeners();
      }
    }();
    return _pending;
  }

  Future<Map<String, dynamic>> call(String method, String path,
          [Map<String, dynamic>? body]) =>
      api.call(method, path, body: body, token: token);

  Future<void> login(String username, String password) => run(() async {
        final result = await api.call(
          'POST',
          '/api/login',
          body: {'username': username, 'password': password},
        );
        final newToken = result['token'] as String;
        final newUser = Map<String, dynamic>.from(result['user'] as Map);
        // Load the authenticated catalog with the new session before exposing
        // the session in the rendered tree.
        final catalog = await api.call(
          'GET',
          '/api/catalog',
          token: newToken,
        );
        final newClinics = rows(catalog['clinics']);
        final newProviders = rows(catalog['providers']);
        token = newToken;
        user = newUser;
        clinics = newClinics;
        providers = newProviders;
        nowMs = catalog['now_ms'] as int;
        final ownClinic = newUser['clinic_id'] as String?;
        clinicId = ownClinic ??
            (newClinics.isEmpty ? null : newClinics.first['id'] as String);
        providerId = null;
        page = 'availability';
        dialog = null;
        dialogAppointment = null;
        moveSlots = [];
        moveSlotId = null;
        _clearActionIntents();
        await loadAvailability();
      });

  Future<void> logout() => run(() async {
        Object? failure;
        try {
          await call('POST', '/api/logout', {});
        } catch (caught) {
          failure = caught;
        } finally {
          // A local sign-out must clear all user-specific rendered state even
          // if the server reply was interrupted.
          token = null;
          user = null;
          clinics = [];
          providers = [];
          slots = [];
          appointments = [];
          moveSlots = [];
          clinicId = null;
          providerId = null;
          moveSlotId = null;
          dialog = null;
          dialogAppointment = null;
          _clearActionIntents();
        }
        if (failure != null) throw failure;
      });

  Future<void> loadAvailability() async {
    if (clinicId == null) {
      slots = [];
      return;
    }
    final query = Uri(
      queryParameters: {
        'clinic_id': clinicId!,
        if (providerId != null) 'provider_id': providerId!,
      },
    ).query;
    slots = rows((await call('GET', '/api/slots?$query'))['slots']);
  }

  Future<void> loadAppointments() async {
    appointments = rows((await call('GET', '/api/appointments'))['appointments']);
  }

  Future<void> navigate(String value) => run(() async {
        page = value;
        dialog = null;
        dialogAppointment = null;
        moveSlots = [];
        moveSlotId = null;
        _clearMoveIntent();
        if (value == 'appointments') await loadAppointments();
        if (value == 'availability') await loadAvailability();
        if (value == 'publish') {
          clinicId = user!['clinic_id'] as String?;
          final ownProviders = providers
              .where((provider) => provider['clinic_id'] == clinicId)
              .toList();
          providerId = ownProviders.isEmpty ? null : ownProviders.first['id'] as String;
        }
      });

  Future<void> chooseClinic(String value) => run(() async {
        clinicId = value;
        // A provider from the previous clinic must never remain selected.
        providerId = null;
        await loadAvailability();
      });

  Future<void> chooseProvider(String? value) => run(() async {
        providerId = value;
        if (page == 'availability') await loadAvailability();
      });

  Future<void> refreshAvailability() => run(loadAvailability);
  Future<void> refreshAppointments() => run(loadAppointments);

  Future<void> publish(String id, String time) => run(() async {
        final start = int.tryParse(time.trim());
        if (start == null || providerId == null) {
          throw const ApiFailure(
            'Enter a provider and UTC millisecond time.',
            400,
          );
        }
        await call('POST', '/api/slots', {
          'id': id,
          'provider_id': providerId,
          'start_ms': start,
        });
        page = 'availability';
        await loadAvailability();
      });

  void updateAppointment(Map<String, dynamic> appointment) {
    appointments = [
      ...appointments.where((a) => a['id'] != appointment['id']),
      Map<String, dynamic>.from(appointment),
    ];
    appointments.sort((a, b) {
      final time = (a['start_ms'] as int).compareTo(b['start_ms'] as int);
      return time != 0
          ? time
          : (a['id'] as String).compareTo(b['id'] as String);
    });
  }

  Future<void> book(String slotId) => run(() async {
        if (_pendingBookingSlotId != slotId ||
            _pendingBookingRequestId == null) {
          _pendingBookingSlotId = slotId;
          _pendingBookingRequestId = _actionId('request');
        }
        final requestId = _pendingBookingRequestId!;
        try {
          final result = await call('POST', '/api/book', {
            'request_id': requestId,
            'slot_id': slotId,
          });
          final appointment =
              Map<String, dynamic>.from(result['appointment'] as Map);
          // The booking is acknowledged before any best-effort screen
          // refresh.  Do not create a second request ID if refresh fails.
          _pendingBookingSlotId = null;
          _pendingBookingRequestId = null;
          updateAppointment(appointment);
          page = 'appointments';
          await loadAvailability();
        } catch (failure) {
          // A transport failure may mean the server committed the booking.
          // Preserve the exact intent for the next tap.  A definite HTTP
          // response is a completed rejection and can start a new intent.
          if (failure is! ApiFailure || !failure.transport) {
            _pendingBookingSlotId = null;
            _pendingBookingRequestId = null;
          }
          rethrow;
        }
      });

  Future<void> openCancel(Map<String, dynamic> appointment) => run(() async {
        dialogAppointment = Map<String, dynamic>.from(appointment);
        dialog = 'cancel';
      });

  Future<void> cancel(String reason) => run(() async {
        final appointment = dialogAppointment;
        if (appointment == null) return;
        final id = Uri.encodeComponent(appointment['id'] as String);
        final result = await call(
          'POST',
          '/api/appointments/$id/cancel',
          {'reason': reason},
        );
        final updated = Map<String, dynamic>.from(result['appointment'] as Map);
        updateAppointment(updated);
        dialog = null;
        dialogAppointment = null;
        await loadAvailability();
      });

  Future<void> openMove(Map<String, dynamic> appointment) => run(() async {
        dialogAppointment = Map<String, dynamic>.from(appointment);
        dialog = 'move';
        moveSlots = [];
        moveSlotId = null;
        _clearMoveIntent();
        final clinic = appointment['clinic_id'] as String;
        final provider = appointment['provider_id'] as String;
        final query = Uri(
          queryParameters: {
            'clinic_id': clinic,
            'provider_id': provider,
          },
        ).query;
        final available = rows((await call('GET', '/api/slots?$query'))['slots']);
        final currentSlot = appointment['slot_id'];
        moveSlots = available
            .where((slot) => slot['id'] != currentSlot)
            .toList();
      });

  void chooseMoveSlot(String value) {
    if (busy) return;
    if (_pendingMoveTargetId != null && _pendingMoveTargetId != value) {
      // Selecting another target explicitly abandons a possibly lost action.
      _clearMoveIntent();
    }
    moveSlotId = value;
    notifyListeners();
  }

  Future<void> _refreshAppointmentAfterConflict(String id) async {
    try {
      final refreshed = await call(
        'GET',
        '/api/appointments/${Uri.encodeComponent(id)}',
      );
      final appointment =
          Map<String, dynamic>.from(refreshed['appointment'] as Map);
      dialogAppointment = appointment;
      updateAppointment(appointment);
      // The target list may have changed after the conflicting operation.
      if (dialog == 'move') {
        final clinic = appointment['clinic_id'] as String;
        final provider = appointment['provider_id'] as String;
        final query = Uri(
          queryParameters: {'clinic_id': clinic, 'provider_id': provider},
        ).query;
        final available = rows((await call('GET', '/api/slots?$query'))['slots']);
        moveSlots = available
            .where((slot) => slot['id'] != appointment['slot_id'])
            .toList();
        moveSlotId = null;
      }
    } catch (_) {
      // Keep the original conflict visible if a follow-up refresh is itself
      // interrupted.  The next explicit refresh can recover the screen.
    }
  }

  Future<void> move() => run(() async {
        final appointment = dialogAppointment;
        final target = moveSlotId;
        if (appointment == null || target == null) {
          throw const ApiFailure('Choose an available new time.', 400);
        }
        final id = appointment['id'] as String;
        final revision = appointment['revision'] as int;
        if (_pendingMoveAppointmentId != id ||
            _pendingMoveTargetId != target ||
            _pendingMoveRevision != revision ||
            _pendingMoveOperationId == null) {
          _pendingMoveAppointmentId = id;
          _pendingMoveTargetId = target;
          _pendingMoveRevision = revision;
          _pendingMoveOperationId = _actionId('operation');
        }
        final operationId = _pendingMoveOperationId!;
        try {
          final result = await call(
            'POST',
            '/api/appointments/${Uri.encodeComponent(id)}/move',
            {
              'operation_id': operationId,
              'to_slot_id': target,
              'expected_revision': revision,
            },
          );
          final updated =
              Map<String, dynamic>.from(result['appointment'] as Map);
          _clearMoveIntent();
          updateAppointment(updated);
          dialog = null;
          dialogAppointment = null;
          moveSlots = [];
          moveSlotId = null;
          await loadAvailability();
        } catch (failure) {
          if (failure is ApiFailure && failure.status == 409) {
            _clearMoveIntent();
            await _refreshAppointmentAfterConflict(id);
          } else if (failure is! ApiFailure || !failure.transport) {
            _clearMoveIntent();
          }
          rethrow;
        }
      });

  void _clearMoveIntent() {
    _pendingMoveAppointmentId = null;
    _pendingMoveTargetId = null;
    _pendingMoveRevision = null;
    _pendingMoveOperationId = null;
  }

  void _clearActionIntents() {
    _pendingBookingSlotId = null;
    _pendingBookingRequestId = null;
    _clearMoveIntent();
  }

  void closeDialog() {
    if (busy) return;
    dialog = null;
    dialogAppointment = null;
    moveSlotId = null;
    moveSlots = [];
    _clearMoveIntent();
    error = null;
    notifyListeners();
  }

  @override
  void dispose() {
    api.close();
    super.dispose();
  }
}
