import 'package:flutter/foundation.dart';
import 'api.dart';

class ClinicController extends ChangeNotifier {
  final ClinicApi api;
  ClinicController({required String origin}) : api = ClinicApi(origin);
  bool busy = false;
  String? error;
  String? token;
  Map<String, dynamic>? user;
  List<Map<String, dynamic>> clinics = [], providers = [], slots = [], appointments = [], moveSlots = [];
  String? clinicId, providerId, moveSlotId;
  String page = 'availability';
  String? dialog;
  Map<String, dynamic>? dialogAppointment;
  int nowMs = 0;
  Future<void> _pending = Future.value();

  Future<void> settle() => _pending;

  List<Map<String, dynamic>> rows(dynamic value) => (value as List).map((e) => Map<String, dynamic>.from(e as Map)).toList();

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

  Future<Map<String, dynamic>> call(String method, String path, [Map<String, dynamic>? body]) =>
      api.call(method, path, body: body, token: token);

  Future<void> login(String username, String password) => run(() async {
    final result = await api.call('POST', '/api/login', body: {'username': username, 'password': password});
    token = result['token'] as String;
    user = Map<String, dynamic>.from(result['user']);
    final catalog = await call('GET', '/api/catalog');
    clinics = rows(catalog['clinics']);
    providers = rows(catalog['providers']);
    nowMs = catalog['now_ms'] as int;
    clinicId = user!['clinic_id'] as String? ?? clinics.first['id'] as String;
    providerId = null;
    page = 'availability';
    await loadAvailability();
  });

  Future<void> logout() => run(() async {
    await call('POST', '/api/logout', {});
    token = null;
    user = null;
    clinics = []; providers = []; slots = []; appointments = []; moveSlots = [];
    clinicId = null; providerId = null; moveSlotId = null;
    dialog = null; dialogAppointment = null;
  });

  Future<void> loadAvailability() async {
    if (clinicId == null) { slots = []; return; }
    final query = Uri(queryParameters: {'clinic_id': clinicId!, if (providerId != null) 'provider_id': providerId!}).query;
    slots = rows((await call('GET', '/api/slots?$query'))['slots']);
  }

  Future<void> loadAppointments() async {
    appointments = rows((await call('GET', '/api/appointments'))['appointments']);
  }

  Future<void> navigate(String value) => run(() async {
    page = value;
    dialog = null;
    dialogAppointment = null;
    if (value == 'appointments') await loadAppointments();
    if (value == 'availability') await loadAvailability();
    if (value == 'publish') {
      clinicId = user!['clinic_id'] as String;
      providerId = providers.firstWhere((p) => p['clinic_id'] == clinicId)['id'] as String;
    }
  });

  Future<void> chooseClinic(String value) => run(() async {
    clinicId = value;
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
    if (start == null || providerId == null) throw const ApiFailure('Enter a provider and UTC millisecond time.', 400);
    await call('POST', '/api/slots', {'id': id, 'provider_id': providerId, 'start_ms': start});
    page = 'availability';
    await loadAvailability();
  });

  void updateAppointment(Map<String, dynamic> appointment) {
    appointments = [...appointments.where((a) => a['id'] != appointment['id']), appointment];
    appointments.sort((a, b) {
      final time = (a['start_ms'] as int).compareTo(b['start_ms'] as int);
      return time != 0 ? time : (a['id'] as String).compareTo(b['id'] as String);
    });
  }

  Future<void> book(String slotId) => run(() async {
    throw const ApiFailure('Booking is not implemented.', 501);
  });

  Future<void> openCancel(Map<String, dynamic> appointment) => run(() async {
    dialogAppointment = Map<String, dynamic>.from(appointment);
    dialog = 'cancel';
  });

  Future<void> cancel(String reason) => run(() async {
    throw const ApiFailure('Cancellation is not implemented.', 501);
  });

  Future<void> openMove(Map<String, dynamic> appointment) => run(() async {
    dialogAppointment = Map<String, dynamic>.from(appointment);
    moveSlots = [];
    moveSlotId = null;
    dialog = 'move';
  });

  void chooseMoveSlot(String value) {
    if (busy) return;
    moveSlotId = value;
    notifyListeners();
  }

  Future<void> move() => run(() async {
    throw const ApiFailure('Changing appointment time is not implemented.', 501);
  });

  void closeDialog() {
    if (busy) return;
    dialog = null;
    dialogAppointment = null;
    moveSlotId = null;
    error = null;
    notifyListeners();
  }

  @override
  void dispose() {
    api.close();
    super.dispose();
  }
}
