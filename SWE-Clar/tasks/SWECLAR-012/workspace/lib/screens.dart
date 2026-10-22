import 'package:flutter/material.dart';
import 'controller.dart';

class ClinicApp extends StatefulWidget {
  final ClinicController controller;
  const ClinicApp({super.key, required this.controller});
  @override
  State<ClinicApp> createState() => _ClinicAppState();
}

class _ClinicAppState extends State<ClinicApp> {
  final username = TextEditingController();
  final password = TextEditingController();
  final slotId = TextEditingController();
  final slotStart = TextEditingController();
  final reason = TextEditingController();
  ClinicController get c => widget.controller;

  String time(dynamic value) => '${DateTime.fromMillisecondsSinceEpoch(value as int, isUtc: true).toIso8601String().replaceFirst('.000Z', '')} UTC';
  String providerLabel(dynamic id) => c.providers.where((p) => p['id'] == id).firstOrNull?['label'] as String? ?? id.toString();
  String clinicLabel(dynamic id) => c.clinics.where((p) => p['id'] == id).firstOrNull?['label'] as String? ?? id.toString();

  Widget input(String key, String label, TextEditingController control, {bool secret = false, bool numeric = false}) =>
      Padding(padding: const EdgeInsets.symmetric(vertical: 8), child: TextField(
        key: ValueKey(key), controller: control, obscureText: secret,
        keyboardType: numeric ? TextInputType.number : TextInputType.text,
        decoration: InputDecoration(labelText: label, border: const OutlineInputBorder()),
      ));

  Widget button(String key, String label, VoidCallback onPressed) =>
      Padding(padding: const EdgeInsets.symmetric(vertical: 4), child: FilledButton(
        key: ValueKey(key), onPressed: c.busy ? null : onPressed, child: Text(label)));

  Widget select(String key, String label, String? value, List<Map<String, dynamic>> options,
      void Function(String) onChanged, {bool includeAll = false}) {
    final choices = [if (includeAll) {'id': '', 'label': 'All providers'}, ...options];
    return Padding(padding: const EdgeInsets.symmetric(vertical: 8), child: InputDecorator(
      decoration: InputDecoration(labelText: label, border: const OutlineInputBorder()),
      child: DropdownButtonHideUnderline(child: DropdownButton<String>(
        key: ValueKey(key), isExpanded: true, value: includeAll ? (value ?? '') : value,
        hint: const Text('Choose'),
        items: choices.map((row) => DropdownMenuItem<String>(
          value: row['id'] as String,
          child: Text(row['label'] as String, key: ValueKey('$key-option-${row['id']}'), overflow: TextOverflow.ellipsis),
        )).toList(),
        onChanged: c.busy ? null : (value) { if (value != null) onChanged(value); },
      )),
    ));
  }

  Widget login() => ListView(padding: const EdgeInsets.all(20), children: [
    const Text('Clinic appointments', style: TextStyle(fontSize: 26, fontWeight: FontWeight.w600)),
    const Text('Synthetic scheduling application'),
    input('login-username', 'Username', username),
    input('login-password', 'Password', password, secret: true),
    button('login-submit', 'Sign in', () => c.login(username.text, password.text)),
  ]);

  Widget availability() => ListView(padding: const EdgeInsets.all(16), children: [
    select('clinic-select', 'Clinic', c.clinicId, c.clinics, c.chooseClinic),
    select('provider-select', 'Provider', c.providerId, c.providers.where((p) => p['clinic_id'] == c.clinicId).toList(),
      (value) => c.chooseProvider(value.isEmpty ? null : value), includeAll: true),
    button('availability-refresh', 'Refresh available times', c.refreshAvailability),
    if (c.slots.isEmpty) const Text('No available times'),
    ...c.slots.map((slot) => Card(key: ValueKey('slot-${slot['id']}'), child: Padding(
      padding: const EdgeInsets.all(12), child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text(providerLabel(slot['provider_id']), style: const TextStyle(fontWeight: FontWeight.bold)),
        Text(clinicLabel(slot['clinic_id'])), Text(time(slot['start_ms'])), Text('Slot ${slot['id']}'),
        if (c.user!['role'] == 'patient') button('book-${slot['id']}', 'Book this time', () => c.book(slot['id'] as String)),
      ]),
    ))),
  ]);

  Widget publish() => ListView(padding: const EdgeInsets.all(16), children: [
    Text('Publish a time at ${clinicLabel(c.user!['clinic_id'])}', style: const TextStyle(fontSize: 18)),
    select('provider-select', 'Provider', c.providerId, c.providers.where((p) => p['clinic_id'] == c.user!['clinic_id']).toList(), c.chooseProvider),
    input('slot-id', 'Slot identifier', slotId),
    input('slot-start', 'Start time — UTC milliseconds', slotStart, numeric: true),
    const Text('Each slot lasts 30 minutes. Use a future minute boundary.'),
    button('publish-submit', 'Publish time', () => c.publish(slotId.text, slotStart.text)),
  ]);

  Widget appointments() => ListView(padding: const EdgeInsets.all(16), children: [
    button('appointments-refresh', 'Refresh appointments', c.refreshAppointments),
    if (c.appointments.isEmpty) const Text('No appointments yet'),
    ...c.appointments.map((appointment) => Card(key: ValueKey('appointment-${appointment['id']}'), child: Padding(
      padding: const EdgeInsets.all(12), child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text(providerLabel(appointment['provider_id']), style: const TextStyle(fontWeight: FontWeight.bold)),
        Text(clinicLabel(appointment['clinic_id'])), Text(time(appointment['start_ms'])),
        Text('Status: ${appointment['status']}'), Text('Patient: ${appointment['patient_id']}'),
        Text('Appointment: ${appointment['id']}'),
        if (appointment['cancel_reason'] != null) Text('Reason: ${appointment['cancel_reason']}'),
        if (appointment['status'] == 'active') Wrap(spacing: 8, children: [
          button('cancel-${appointment['id']}', 'Cancel', () { reason.clear(); c.openCancel(appointment); }),
          button('move-${appointment['id']}', 'Change time', () => c.openMove(appointment)),
        ]),
      ]),
    ))),
  ]);

  Widget dialog() => Center(child: AlertDialog(
    title: Text(c.dialog == 'cancel' ? 'Cancel appointment' : 'Change appointment time'),
    content: SizedBox(width: 320, child: SingleChildScrollView(child: Column(mainAxisSize: MainAxisSize.min, children: [
      Text(time(c.dialogAppointment!['start_ms'])),
      if (c.dialog == 'cancel') input('cancel-reason', 'Reason', reason),
      if (c.dialog == 'move') select('move-slot-select', 'New time', c.moveSlotId,
        c.moveSlots.map((s) => {'id': s['id'], 'label': '${time(s['start_ms'])} · ${s['id']}'}).toList(), c.chooseMoveSlot),
      if (c.dialog == 'move' && c.moveSlots.isEmpty) const Text('No other times available'),
      if (c.error != null) Text(c.error!, style: const TextStyle(color: Colors.red)),
    ]))),
    actions: [
      button('dialog-close', 'Close', c.closeDialog),
      if (c.dialog == 'cancel') button('cancel-submit', 'Confirm cancellation', () => c.cancel(reason.text)),
      if (c.dialog == 'move') button('move-submit', 'Confirm new time', c.move),
    ],
  ));

  @override
  Widget build(BuildContext context) => AnimatedBuilder(animation: c, builder: (context, _) => MaterialApp(
    debugShowCheckedModeBanner: false,
    theme: ThemeData(colorSchemeSeed: Colors.teal, useMaterial3: true),
    home: Scaffold(
      appBar: AppBar(title: Text(c.user == null ? 'Clinic' : c.user!['label'] as String), actions: [
        if (c.user != null) TextButton(key: const ValueKey('logout'), onPressed: c.busy ? null : () async {
          await c.logout();
          if (c.user == null) { username.clear(); password.clear(); }
        }, child: const Text('Sign out')),
      ]),
      body: Stack(children: [
        Column(children: [
          if (c.busy) const LinearProgressIndicator(),
          if (c.error != null && c.dialog == null) Padding(padding: const EdgeInsets.all(8), child: Text(c.error!, style: const TextStyle(color: Colors.red))),
          if (c.user != null) Wrap(spacing: 8, children: [
            button('nav-availability', 'Available times', () => c.navigate('availability')),
            button('nav-appointments', 'Appointments', () => c.navigate('appointments')),
            if (c.user!['role'] == 'staff') button('nav-publish', 'Publish', () => c.navigate('publish')),
          ]),
          Expanded(child: c.user == null ? login() : switch (c.page) {
            'appointments' => appointments(), 'publish' => publish(), _ => availability(),
          }),
        ]),
        if (c.dialog != null) const Positioned.fill(child: ModalBarrier(dismissible: false, color: Colors.black38)),
        if (c.dialog != null) dialog(),
      ]),
    ),
  ));

  @override
  void dispose() {
    username.dispose(); password.dispose(); slotId.dispose(); slotStart.dispose(); reason.dispose();
    super.dispose();
  }
}
