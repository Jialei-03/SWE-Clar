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

  String time(dynamic value) {
    if (value is! int) return value.toString();
    return '${DateTime.fromMillisecondsSinceEpoch(value, isUtc: true).toIso8601String().replaceFirst('.000Z', '')} UTC';
  }

  String providerLabel(dynamic id) {
    for (final provider in c.providers) {
      if (provider['id'] == id) return provider['label'].toString();
    }
    return id.toString();
  }

  String clinicLabel(dynamic id) {
    for (final clinic in c.clinics) {
      if (clinic['id'] == id) return clinic['label'].toString();
    }
    return id.toString();
  }

  Widget input(
    String key,
    String label,
    TextEditingController control, {
    bool secret = false,
    bool numeric = false,
  }) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 8),
      child: TextField(
        key: ValueKey(key),
        controller: control,
        obscureText: secret,
        keyboardType: numeric ? TextInputType.number : TextInputType.text,
        decoration: InputDecoration(
          labelText: label,
          border: const OutlineInputBorder(),
        ),
      ),
    );
  }

  Widget button(String key, String label, VoidCallback onPressed) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: FilledButton(
        key: ValueKey(key),
        onPressed: c.busy ? null : onPressed,
        child: Text(label, overflow: TextOverflow.ellipsis),
      ),
    );
  }

  Widget select(
    String key,
    String label,
    String? value,
    List<Map<String, dynamic>> options,
    void Function(String) onChanged, {
    bool includeAll = false,
  }) {
    final choices = <Map<String, dynamic>>[
      if (includeAll) {'id': '', 'label': 'All providers'},
      ...options,
    ];
    final candidate = includeAll ? (value ?? '') : value;
    final selected = choices.any((row) => row['id'] == candidate)
        ? candidate
        : null;
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 8),
      child: InputDecorator(
        decoration: InputDecoration(
          labelText: label,
          border: const OutlineInputBorder(),
        ),
        child: DropdownButtonHideUnderline(
          child: DropdownButton<String>(
            key: ValueKey(key),
            isExpanded: true,
            value: selected,
            hint: const Text('Choose'),
            items: choices
                .map(
                  (row) => DropdownMenuItem<String>(
                    value: row['id'] as String,
                    child: Text(
                      row['label'].toString(),
                      key: ValueKey('$key-option-${row['id']}'),
                      overflow: TextOverflow.ellipsis,
                    ),
                  ),
                )
                .toList(),
            onChanged: c.busy
                ? null
                : (changed) {
                    if (changed != null) onChanged(changed);
                  },
          ),
        ),
      ),
    );
  }

  Widget login() => ListView(
        padding: const EdgeInsets.all(20),
        children: [
          const Text(
            'Clinic appointments',
            style: TextStyle(fontSize: 26, fontWeight: FontWeight.w600),
          ),
          const SizedBox(height: 4),
          const Text('Synthetic scheduling application'),
          input('login-username', 'Username', username),
          input('login-password', 'Password', password, secret: true),
          button(
            'login-submit',
            'Sign in',
            () => c.login(username.text, password.text),
          ),
        ],
      );

  Widget availability() {
    final visibleProviders = c.providers
        .where((provider) => provider['clinic_id'] == c.clinicId)
        .toList();
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        select('clinic-select', 'Clinic', c.clinicId, c.clinics, c.chooseClinic),
        select(
          'provider-select',
          'Provider',
          c.providerId,
          visibleProviders,
          (value) => c.chooseProvider(value.isEmpty ? null : value),
          includeAll: true,
        ),
        button(
          'availability-refresh',
          'Refresh available times',
          c.refreshAvailability,
        ),
        if (c.slots.isEmpty) const Text('No available times'),
        ...c.slots.map(
          (slot) => Card(
            key: ValueKey('slot-${slot['id']}'),
            child: Padding(
              padding: const EdgeInsets.all(12),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    providerLabel(slot['provider_id']),
                    style: const TextStyle(fontWeight: FontWeight.bold),
                    overflow: TextOverflow.ellipsis,
                  ),
                  Text(clinicLabel(slot['clinic_id']),
                      overflow: TextOverflow.ellipsis),
                  Text(time(slot['start_ms']), overflow: TextOverflow.ellipsis),
                  Text('Slot ${slot['id']}', overflow: TextOverflow.ellipsis),
                  if (c.user!['role'] == 'patient')
                    button(
                      'book-${slot['id']}',
                      'Book this time',
                      () => c.book(slot['id'] as String),
                    ),
                ],
              ),
            ),
          ),
        ),
      ],
    );
  }

  Widget publish() {
    final clinic = c.user!['clinic_id'];
    final ownProviders = c.providers
        .where((provider) => provider['clinic_id'] == clinic)
        .toList();
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        Text(
          'Publish a time at ${clinicLabel(clinic)}',
          style: const TextStyle(fontSize: 18),
          overflow: TextOverflow.ellipsis,
        ),
        select(
          'provider-select',
          'Provider',
          c.providerId,
          ownProviders,
          c.chooseProvider,
        ),
        input('slot-id', 'Slot identifier', slotId),
        input(
          'slot-start',
          'Start time — UTC milliseconds',
          slotStart,
          numeric: true,
        ),
        const Text('Each slot lasts 30 minutes. Use a future minute boundary.'),
        button(
          'publish-submit',
          'Publish time',
          () => c.publish(slotId.text, slotStart.text),
        ),
      ],
    );
  }

  Widget appointments() => ListView(
        padding: const EdgeInsets.all(16),
        children: [
          button(
            'appointments-refresh',
            'Refresh appointments',
            c.refreshAppointments,
          ),
          if (c.appointments.isEmpty) const Text('No appointments yet'),
          ...c.appointments.map(
            (appointment) => Card(
              key: ValueKey('appointment-${appointment['id']}'),
              child: Padding(
                padding: const EdgeInsets.all(12),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      providerLabel(appointment['provider_id']),
                      style: const TextStyle(fontWeight: FontWeight.bold),
                      overflow: TextOverflow.ellipsis,
                    ),
                    Text(
                      clinicLabel(appointment['clinic_id']),
                      overflow: TextOverflow.ellipsis,
                    ),
                    Text(
                      time(appointment['start_ms']),
                      overflow: TextOverflow.ellipsis,
                    ),
                    Text('Status: ${appointment['status']}'),
                    Text(
                      'Patient: ${appointment['patient_id']}',
                      overflow: TextOverflow.ellipsis,
                    ),
                    Text(
                      'Appointment: ${appointment['id']}',
                      overflow: TextOverflow.ellipsis,
                    ),
                    if (appointment['cancel_reason'] != null)
                      Text(
                        'Reason: ${appointment['cancel_reason']}',
                        overflow: TextOverflow.ellipsis,
                      ),
                    if (appointment['status'] == 'active')
                      Wrap(
                        spacing: 8,
                        children: [
                          button(
                            'cancel-${appointment['id']}',
                            'Cancel',
                            () {
                              reason.clear();
                              c.openCancel(appointment);
                            },
                          ),
                          button(
                            'move-${appointment['id']}',
                            'Change time',
                            () => c.openMove(appointment),
                          ),
                        ],
                      ),
                  ],
                ),
              ),
            ),
          ),
        ],
      );

  Widget dialog() {
    final appointment = c.dialogAppointment!;
    final isCancel = c.dialog == 'cancel';
    return Center(
      child: AlertDialog(
        title: Text(isCancel ? 'Cancel appointment' : 'Change appointment time'),
        content: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 320, maxHeight: 360),
          child: SingleChildScrollView(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                Text(time(appointment['start_ms']),
                    overflow: TextOverflow.ellipsis),
                if (isCancel) input('cancel-reason', 'Reason', reason),
                if (!isCancel)
                  select(
                    'move-slot-select',
                    'New time',
                    c.moveSlotId,
                    c.moveSlots
                        .map(
                          (slot) => <String, dynamic>{
                            'id': slot['id'],
                            'label': '${time(slot['start_ms'])} · ${slot['id']}',
                          },
                        )
                        .toList(),
                    c.chooseMoveSlot,
                  ),
                if (!isCancel && c.moveSlots.isEmpty)
                  const Text('No other times available'),
                if (c.error != null)
                  Text(
                    c.error!,
                    style: const TextStyle(color: Colors.red),
                  ),
              ],
            ),
          ),
        ),
        actions: [
          button('dialog-close', 'Close', c.closeDialog),
          if (isCancel)
            button(
              'cancel-submit',
              'Confirm cancellation',
              () => c.cancel(reason.text),
            ),
          if (!isCancel)
            button('move-submit', 'Confirm new time', c.move),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) => AnimatedBuilder(
        animation: c,
        builder: (context, _) => MaterialApp(
          debugShowCheckedModeBanner: false,
          theme: ThemeData(
            colorSchemeSeed: Colors.teal,
            useMaterial3: true,
          ),
          home: Scaffold(
            appBar: AppBar(
              title: Text(
                c.user == null ? 'Clinic' : c.user!['label'] as String,
                overflow: TextOverflow.ellipsis,
              ),
              actions: [
                if (c.user != null)
                  TextButton(
                    key: const ValueKey('logout'),
                    onPressed: c.busy
                        ? null
                        : () async {
                            await c.logout();
                            if (c.user == null) {
                              username.clear();
                              password.clear();
                            }
                          },
                    child: const Text('Sign out'),
                  ),
              ],
            ),
            body: Stack(
              children: [
                Column(
                  children: [
                    if (c.busy) const LinearProgressIndicator(),
                    if (c.error != null && c.dialog == null)
                      Padding(
                        padding: const EdgeInsets.all(8),
                        child: Text(
                          c.error!,
                          style: const TextStyle(color: Colors.red),
                          maxLines: 3,
                          overflow: TextOverflow.ellipsis,
                        ),
                      ),
                    if (c.user != null)
                      Wrap(
                        spacing: 8,
                        runSpacing: 2,
                        alignment: WrapAlignment.center,
                        children: [
                          button(
                            'nav-availability',
                            'Available times',
                            () => c.navigate('availability'),
                          ),
                          button(
                            'nav-appointments',
                            'Appointments',
                            () => c.navigate('appointments'),
                          ),
                          if (c.user!['role'] == 'staff')
                            button(
                              'nav-publish',
                              'Publish',
                              () => c.navigate('publish'),
                            ),
                        ],
                      ),
                    Expanded(
                      child: c.user == null
                          ? login()
                          : switch (c.page) {
                              'appointments' => appointments(),
                              'publish' => publish(),
                              _ => availability(),
                            },
                    ),
                  ],
                ),
                if (c.dialog != null)
                  const Positioned.fill(
                    child: ModalBarrier(
                      dismissible: false,
                      color: Colors.black38,
                    ),
                  ),
                if (c.dialog != null) dialog(),
              ],
            ),
          ),
        ),
      );

  @override
  void dispose() {
    username.dispose();
    password.dispose();
    slotId.dispose();
    slotStart.dispose();
    reason.dispose();
    super.dispose();
  }
}
