import 'package:flutter/material.dart';

import 'maintenance.dart';

class FixtureApp extends StatelessWidget {
  final FixtureRepository repository;

  const FixtureApp({super.key, required this.repository});

  @override
  Widget build(BuildContext context) => MaterialApp(
    title: 'Appointment maintenance',
    debugShowCheckedModeBanner: false,
    theme: ThemeData(
      colorScheme: ColorScheme.fromSeed(seedColor: const Color(0xff397b6e)),
      useMaterial3: true,
    ),
    home: BookingPage(repository: repository),
  );
}

class BookingPage extends StatefulWidget {
  final FixtureRepository repository;

  const BookingPage({super.key, required this.repository});

  @override
  State<BookingPage> createState() => _BookingPageState();
}

enum _LoadResult { ready, error, stale }

class _BookingPageState extends State<BookingPage> {
  static const collections = <String>['clinics', 'providers', 'bookings'];

  int section = 0;
  int _loadGeneration = 0;
  List<Map<String, dynamic>> rows = <Map<String, dynamic>>[];
  String loadState = 'loading';
  String repairState = 'idle';
  int? repairCount;

  @override
  void initState() {
    super.initState();
    _loadSection(section);
  }

  /// Starts a read for exactly one selected section.
  ///
  /// A generation is captured before the request is issued.  Navigation and
  /// refresh both advance that generation, so a slow response can never put
  /// rows from an old request back into the current page.
  Future<_LoadResult> _loadSection(int requestedSection) async {
    final generation = ++_loadGeneration;
    final collection = collections[requestedSection];

    if (mounted) {
      setState(() {
        rows = <Map<String, dynamic>>[];
        loadState = 'loading';
      });
    }

    try {
      final result = await widget.repository.view(collection);
      if (!mounted ||
          generation != _loadGeneration ||
          requestedSection != section) {
        return _LoadResult.stale;
      }
      setState(() {
        rows = result;
        loadState = 'ready';
      });
      return _LoadResult.ready;
    } catch (_) {
      if (!mounted ||
          generation != _loadGeneration ||
          requestedSection != section) {
        return _LoadResult.stale;
      }
      setState(() {
        rows = <Map<String, dynamic>>[];
        loadState = 'error';
      });
      return _LoadResult.error;
    }
  }

  /// Publicly reachable refresh action for the selected page.
  Future<void> load() async {
    await _loadSection(section);
  }

  Future<void> repair() async {
    if (repairState == 'pending') return;

    setState(() {
      repairState = 'pending';
      repairCount = null;
    });

    try {
      final report = await widget.repository.normalize(
        'providers',
        'clinic',
        'clinics',
      );
      if (!mounted) return;

      // The selection is intentionally read after normalize completes.  If a
      // user navigated while the migration was pending, completion stays on
      // that page rather than switching back to providers.
      // Keep the operation pending until its post-commit reload has completed.
      // This keeps the repair control disabled for the whole workflow and
      // makes a reload failure an honest repair failure rather than a success
      // count paired with an error page.
      final reloadResult = await _loadSection(section);
      if (!mounted) return;
      if (reloadResult == _LoadResult.error) {
        setState(() {
          repairState = 'error';
          repairCount = null;
        });
        return;
      }
      // Reload from Firestore, rather than constructing rows from the report.
      // _loadSection has its own generation guard and therefore also handles
      // navigation or refreshes that raced with the repair.
      setState(() {
        repairState = 'success';
        repairCount = report.length;
      });
    } catch (_) {
      if (!mounted) return;
      setState(() {
        repairState = 'error';
        repairCount = null;
      });
      // Do not synthesize a proposed repair result after a failed read or
      // commit.  Existing rows, if any, are the last rows actually read.
    }
  }

  void navigate(int next) {
    if (next < 0 || next >= collections.length) return;
    setState(() {
      section = next;
      rows = <Map<String, dynamic>>[];
    });
    _loadSection(next);
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: const Text('Appointment maintenance')),
    body: SafeArea(
      child: LayoutBuilder(
        builder: (context, constraints) {
          final width = constraints.maxWidth > 850
              ? 850.0
              : constraints.maxWidth;
          return Align(
            alignment: Alignment.topCenter,
            child: SizedBox(
              width: width,
              height: constraints.maxHeight,
              child: Padding(
                padding: const EdgeInsets.all(16),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    Text(
                      collections[section],
                      key: const ValueKey<String>('page-title'),
                      style: Theme.of(context).textTheme.headlineMedium,
                    ),
                    const SizedBox(height: 12),
                    Wrap(
                      spacing: 12,
                      runSpacing: 8,
                      children: [
                        OutlinedButton(
                          key: const ValueKey<String>('refresh'),
                          onPressed: load,
                          child: const Text('Refresh'),
                        ),
                        FilledButton(
                          key: const ValueKey<String>('repair'),
                          onPressed: repairState == 'pending' ? null : repair,
                          child: const Text('Repair provider relations'),
                        ),
                      ],
                    ),
                    const SizedBox(height: 8),
                    Text(
                      repairState,
                      key: const ValueKey<String>('repair-state'),
                    ),
                    if (repairState == 'pending')
                      const Padding(
                        padding: EdgeInsets.only(top: 4),
                        child: Text(
                          'Repair in progress',
                          key: ValueKey<String>('repair-progress'),
                        ),
                      ),
                    if (repairState == 'error')
                      const Text('Repair failed; use Repair to retry.'),
                    if (repairCount != null && repairState == 'success')
                      Text(
                        '$repairCount',
                        key: const ValueKey<String>('repair-count'),
                      ),
                    Text(loadState, key: const ValueKey<String>('load-state')),
                    if (loadState == 'error')
                      const Text(
                        'Data could not be loaded; use Refresh to retry.',
                      ),
                    if (loadState == 'ready' && rows.isEmpty)
                      const Text(
                        'No records',
                        key: ValueKey<String>('empty-state'),
                      ),
                    const SizedBox(height: 8),
                    Expanded(
                      child: ListView.builder(
                        key: const ValueKey<String>('record-list'),
                        itemCount: rows.length,
                        itemBuilder: (context, index) {
                          final row = rows[index];
                          final id = row['id'] as String;
                          return Card(
                            key: ValueKey<String>('record-$id'),
                            child: Padding(
                              padding: const EdgeInsets.all(12),
                              child: Column(
                                crossAxisAlignment: CrossAxisAlignment.start,
                                children: [
                                  Text(
                                    row['name'] as String,
                                    key: ValueKey<String>('name-$id'),
                                  ),
                                  Text(id, key: ValueKey<String>('id-$id')),
                                  if (row['relation_name'] != null)
                                    Text(
                                      row['relation_name'] as String,
                                      key: ValueKey<String>('relation-$id'),
                                    ),
                                ],
                              ),
                            ),
                          );
                        },
                      ),
                    ),
                  ],
                ),
              ),
            ),
          );
        },
      ),
    ),
    bottomNavigationBar: NavigationBar(
      selectedIndex: section,
      onDestinationSelected: navigate,
      destinations: const [
        NavigationDestination(
          key: ValueKey<String>('nav-clinics'),
          icon: Icon(Icons.local_hospital_outlined),
          label: 'Clinics',
        ),
        NavigationDestination(
          key: ValueKey<String>('nav-providers'),
          icon: Icon(Icons.people_outline),
          label: 'Providers',
        ),
        NavigationDestination(
          key: ValueKey<String>('nav-bookings'),
          icon: Icon(Icons.calendar_month_outlined),
          label: 'Bookings',
        ),
      ],
    ),
  );
}
