import 'package:flutter/material.dart';
import 'controller.dart';

class ServiceApp extends StatefulWidget {
  final ServiceController controller;
  const ServiceApp({super.key, required this.controller});
  @override
  State<ServiceApp> createState() => _ServiceAppState();
}
class _ServiceAppState extends State<ServiceApp> {
  final username = TextEditingController();
  final password = TextEditingController();
  @override
  void dispose() { username.dispose(); password.dispose(); super.dispose(); }
  @override
  Widget build(BuildContext context) => MaterialApp(
    debugShowCheckedModeBanner: false,
    theme: ThemeData(colorSchemeSeed: const Color(0xff235a73), useMaterial3: true),
    home: AnimatedBuilder(animation: widget.controller, builder: (context, _) {
      final c = widget.controller;
      return Scaffold(
        appBar: AppBar(title: const Text('Service appointments'), actions: c.user == null ? [] : [
          IconButton(key: const Key('notifications'), tooltip: 'Notifications', icon: const Icon(Icons.notifications_outlined), onPressed: () => c.navigate('notifications')),
          TextButton(key: const Key('logout'), onPressed: c.logout, child: const Text('Sign out')),
        ]),
        body: SafeArea(child: Center(child: ConstrainedBox(constraints: const BoxConstraints(maxWidth: 700), child: ListView(
          padding: const EdgeInsets.all(20), children: [
            if (c.error != null) Text(c.error!, key: const Key('error'), style: const TextStyle(color: Colors.red)),
            if (c.route == 'login') ...[
              const Text('Welcome back', style: TextStyle(fontSize: 28, fontWeight: FontWeight.bold)),
              const SizedBox(height: 24),
              TextField(key: const Key('username'), controller: username, decoration: const InputDecoration(labelText: 'Username')),
              TextField(key: const Key('password'), controller: password, obscureText: true, decoration: const InputDecoration(labelText: 'Password')),
              const SizedBox(height: 20),
              FilledButton(key: const Key('login'), onPressed: c.busy ? null : () => c.login(username.text, password.text), child: const Text('Sign in')),
            ] else ...[
              Wrap(spacing: 12, children: [
                TextButton(key: const Key('dashboard-tab'), onPressed: () => c.navigate('dashboard'), child: const Text('Services')),
                TextButton(key: const Key('appointments-tab'), onPressed: () => c.navigate('appointments'), child: const Text('Appointments')),
              ]),
              if (c.route == 'dashboard') ...[
                const Text('Choose a service', style: TextStyle(fontSize: 26, fontWeight: FontWeight.bold)),
                const SizedBox(height: 12),
                for (final service in c.services) Card(child: Padding(padding: const EdgeInsets.all(16), child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text(service['title'] as String, style: const TextStyle(fontSize: 20)),
                  const SizedBox(height: 12),
                  Wrap(spacing: 8, runSpacing: 8, children: [for (final slot in service['available_slots'] as List)
                    OutlinedButton(key: Key('book-${service['id']}-$slot'), onPressed: c.busy ? null : () => c.book(service['id'] as String, slot as String), child: Text(slot as String))]),
                ]))),
              ],
              if (c.route == 'appointments') ...[
                const Text('Your appointments', style: TextStyle(fontSize: 26, fontWeight: FontWeight.bold)),
                for (final row in c.appointments.values) ListTile(key: Key('appointment-${row['id']}'), leading: const Icon(Icons.event_available), title: Text(row['service_id'] as String), subtitle: Text(row['slot'] as String)),
              ],
              if (c.route == 'notifications') ...[
                const Text('Notifications', style: TextStyle(fontSize: 26, fontWeight: FontWeight.bold)),
                for (final entry in c.notifications.entries) ListTile(key: Key('notification-${entry.key}'), title: Text(entry.value['title'] as String? ?? entry.key),
                  leading: Icon(entry.value['read'] == true ? Icons.mark_email_read : Icons.mark_email_unread),
                  onTap: () => c.openNotification(entry.key)),
              ],
            ],
            if (c.busy) const LinearProgressIndicator(),
          ],
        )))),
      );
    }),
  );
}
