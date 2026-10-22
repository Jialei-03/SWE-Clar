import 'package:flutter/material.dart';
import 'maintenance.dart';

class FixtureApp extends StatelessWidget {
  final FixtureRepository repository;
  const FixtureApp({super.key, required this.repository});
  @override Widget build(BuildContext context) => MaterialApp(
    title: 'Appointment maintenance',
    debugShowCheckedModeBanner: false,
    theme: ThemeData(colorScheme: ColorScheme.fromSeed(seedColor: const Color(0xff397b6e))),
    home: BookingPage(repository: repository),
  );
}

class BookingPage extends StatefulWidget {
  final FixtureRepository repository;
  const BookingPage({super.key, required this.repository});
  @override State<BookingPage> createState() => _BookingPageState();
}

class _BookingPageState extends State<BookingPage> {
  static const collections = ['clinics','providers','bookings'];
  int section = 0;
  int loadGeneration = 0;
  List<Map<String,dynamic>> rows = [];
  String loadState = 'loading';
  String repairState = 'idle';
  int? repairCount;

  @override void initState() { super.initState(); load(); }

  Future<void> load() async {
    final generation = ++loadGeneration;
    final collection = collections[section];
    setState(() { loadState = 'loading'; });
    try {
      final result = await widget.repository.view(collection);
      if (!mounted || generation != loadGeneration) return;
      setState(() { rows = result; loadState = 'ready'; });
    } catch (_) {
      if (mounted && generation == loadGeneration) setState(() { rows = []; loadState = 'error'; });
    }
  }

  Future<void> repair() async {
    setState(() { repairState = 'error'; repairCount = null; });
    // TODO: connect relation maintenance and completion feedback.
  }

  void navigate(int next) {
    setState(() { section = next; rows = []; });
    load();
  }

  @override Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: const Text('Appointment maintenance')),
    body: Center(child: ConstrainedBox(constraints: const BoxConstraints(maxWidth: 850), child: Padding(
      padding: const EdgeInsets.all(20), child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Text(collections[section], key: const ValueKey<String>('page-title'), style: Theme.of(context).textTheme.headlineMedium),
        const SizedBox(height: 12),
        Wrap(spacing: 12, runSpacing: 8, children: [
          OutlinedButton(key: const ValueKey<String>('refresh'), onPressed: load, child: const Text('Refresh')),
          FilledButton(key: const ValueKey<String>('repair'), onPressed: repairState == 'pending' ? null : repair, child: const Text('Repair provider relations')),
        ]),
        const SizedBox(height: 8),
        Text(repairState, key: const ValueKey<String>('repair-state')),
        if (repairState == 'pending') const Text('Repair in progress', key: ValueKey<String>('repair-progress')),
        if (repairCount != null && repairState == 'success') Text('$repairCount', key: const ValueKey<String>('repair-count')),
        Text(loadState, key: const ValueKey<String>('load-state')),
        if (loadState == 'error') const Text('Data could not be loaded; use Refresh to retry.'),
        if (loadState == 'ready' && rows.isEmpty) const Text('No records', key: ValueKey<String>('empty-state')),
        const SizedBox(height: 8),
        Expanded(child: ListView.builder(key: const ValueKey<String>('record-list'), itemCount: rows.length, itemBuilder: (context,index) {
          final row = rows[index]; final id = row['id'] as String;
          return Card(key: ValueKey<String>('record-$id'), child: Padding(padding: const EdgeInsets.all(12), child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(row['name'] as String, key: ValueKey<String>('name-$id')),
            Text(id, key: ValueKey<String>('id-$id')),
            if (row['relation_name'] != null) Text(row['relation_name'] as String, key: ValueKey<String>('relation-$id')),
          ])));
        })),
      ]),
    ))),
    bottomNavigationBar: NavigationBar(selectedIndex: section, onDestinationSelected: navigate, destinations: const [
      NavigationDestination(key: ValueKey<String>('nav-clinics'), icon: Icon(Icons.local_hospital_outlined), label: 'Clinics'),
      NavigationDestination(key: ValueKey<String>('nav-providers'), icon: Icon(Icons.people_outline), label: 'Providers'),
      NavigationDestination(key: ValueKey<String>('nav-bookings'), icon: Icon(Icons.calendar_month_outlined), label: 'Bookings'),
    ]),
  );
}
