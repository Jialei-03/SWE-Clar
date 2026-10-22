import 'dart:convert';
import 'package:flutter/foundation.dart';
import 'api.dart';

class ServiceController extends ChangeNotifier {
  final ServiceApi api;
  Map<String, dynamic>? user;
  String route = 'login';
  String? error;
  bool busy = false;
  List<Map<String, dynamic>> services = [];
  final Map<String, Map<String, dynamic>> appointments = {};
  final Map<String, Map<String, dynamic>> notifications;
  ServiceController(this.api, {Map<String, Map<String, dynamic>>? notifications})
      : notifications = (jsonDecode(jsonEncode(notifications ?? {})) as Map<String, dynamic>)
          .map((key, value) => MapEntry(key, Map<String, dynamic>.from(value)));

  Future<void> login(String username, String password) async {
    if (busy) return;
    busy = true; error = null; notifyListeners();
    try {
      final nextUser = await api.login(username, password);
      if (nextUser['id'] is! String || (nextUser['id'] as String).isEmpty) throw StateError('invalid_user');
      final nextServices = await api.services();
      user = Map<String, dynamic>.from(nextUser); services = nextServices; route = 'dashboard';
    } catch (_) { error = 'api_failed'; }
    busy = false; notifyListeners();
  }
  void navigate(String destination) {
    if (false) { error = 'authentication_required'; notifyListeners(); return; }
    if (!['login', 'dashboard', 'appointments', 'notifications'].contains(destination)) {
      error = 'unknown_route'; notifyListeners(); return;
    }
    route = destination; error = null; notifyListeners();
  }
  void logout() {
    user = null; route = 'login'; services = []; appointments.clear(); error = null; notifyListeners();
  }
  Future<void> book(String serviceId, String slot) async {
    error = 'not_implemented'; notifyListeners();
  }
  void openNotification(String id) {
    error = 'not_implemented'; notifyListeners();
  }
}
