import 'package:flutter/material.dart';

import 'controller.dart';

class BookingApp extends StatefulWidget {
  final BookingController controller;

  const BookingApp({super.key, required this.controller});

  @override
  State<BookingApp> createState() => _BookingAppState();
}

class _BookingAppState extends State<BookingApp> {
  final bookingId = TextEditingController(text: 'sample-booking');
  final peer = TextEditingController(text: 'guest');
  final minutes = TextEditingController(text: '5');
  final message = TextEditingController();
  int _operationSequence = 0;

  BookingController get controller => widget.controller;

  @override
  void dispose() {
    bookingId.dispose();
    peer.dispose();
    minutes.dispose();
    message.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        useMaterial3: true,
        colorSchemeSeed: const Color(0xff23685a),
      ),
      home: AnimatedBuilder(
        animation: controller,
        builder: (context, _) {
          final state = controller.snapshot;
          return _buildWorkspace(context, state);
        },
      ),
    );
  }

  Widget _buildWorkspace(
    BuildContext context,
    Map<String, dynamic> state,
  ) {
    final route = state['route'];
    return Scaffold(
      appBar: AppBar(
        title: const Text('Booking workspace'),
        leading: IconButton(
          key: const Key('back'),
          tooltip: 'Back',
          icon: const Icon(Icons.arrow_back),
          onPressed: controller.busy
              ? null
              : () => controller.act(<String, dynamic>{'type': 'back'}),
        ),
      ),
      body: SafeArea(
        child: Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 700),
            child: ListView(
              padding: const EdgeInsets.all(20),
              children: <Widget>[
                Text(
                  'Signed in: ${controller.actorId}',
                  style: Theme.of(context).textTheme.labelLarge,
                ),
                const SizedBox(height: 8),
                _navigation(context),
                if (controller.error != null) ...<Widget>[
                  const SizedBox(height: 8),
                  Text(
                    controller.error!,
                    key: const Key('error'),
                    style: const TextStyle(color: Colors.red),
                  ),
                ],
                const SizedBox(height: 16),
                if (route == 'bookings')
                  _bookingsPage(state)
                else if (route == 'messages')
                  _messagesPage(state)
                else
                  _homePage(),
                if (controller.busy) ...<Widget>[
                  const SizedBox(height: 16),
                  const LinearProgressIndicator(),
                ],
              ],
            ),
          ),
        ),
      ),
    );
  }

  Widget _navigation(BuildContext context) {
    final available = controller.screens();
    return Wrap(
      spacing: 8,
      runSpacing: 4,
      children: <Widget>[
        for (final screen in available)
          TextButton(
            key: Key('nav-${screen['screen_id']}'),
            onPressed: controller.busy
                ? null
                : () => controller.act(<String, dynamic>{
                      'type': 'navigate',
                      'screen_id': screen['screen_id'],
                    }),
            child: Text('${screen['title']}'),
          ),
      ],
    );
  }

  Widget _homePage() {
    return const Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: <Widget>[
        Text(
          'Plan a booking',
          style: TextStyle(fontSize: 28, fontWeight: FontWeight.bold),
        ),
        SizedBox(height: 12),
        Text(
          'Choose Bookings to create or confirm a local booking. '
          'Messages are stored in this workspace.',
        ),
      ],
    );
  }

  Widget _bookingsPage(Map<String, dynamic> state) {
    final bookings = _map(state['bookings']);
    final users = _map(state['users']);
    final actorRecord = users[controller.actorId];
    final isAdmin = actorRecord is Map && actorRecord['role'] == 'admin';

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: <Widget>[
        const Text(
          'Bookings',
          style: TextStyle(fontSize: 26, fontWeight: FontWeight.bold),
        ),
        const SizedBox(height: 8),
        TextField(
          key: const Key('booking-id'),
          controller: bookingId,
          decoration: const InputDecoration(labelText: 'Booking ID'),
          textInputAction: TextInputAction.next,
        ),
        TextField(
          key: const Key('peer'),
          controller: peer,
          decoration: const InputDecoration(labelText: 'Other participant'),
          textInputAction: TextInputAction.done,
        ),
        const SizedBox(height: 8),
        FilledButton(
          key: const Key('create'),
          onPressed: controller.busy
              ? null
              : () => controller.act(<String, dynamic>{
                    'type': 'create_booking',
                    'booking_id': bookingId.text,
                    'peer_id': peer.text,
                  }),
          child: const Text('Create booking'),
        ),
        const SizedBox(height: 16),
        TextField(
          key: const Key('minutes'),
          controller: minutes,
          keyboardType: TextInputType.number,
          decoration: const InputDecoration(labelText: 'Extension minutes'),
        ),
        const SizedBox(height: 8),
        for (final entry in bookings.entries)
          if (_visibleBooking(entry.value, isAdmin))
            _bookingCard(entry.key, entry.value, isAdmin),
        if (bookings.isEmpty)
          const Padding(
            padding: EdgeInsets.only(top: 12),
            child: Text('No bookings are saved yet.'),
          ),
      ],
    );
  }

  bool _visibleBooking(dynamic rawBooking, bool isAdmin) {
    if (rawBooking is! Map) return false;
    if (isAdmin) return true;
    return _isParticipant(_map(rawBooking), controller.actorId);
  }

  Widget _bookingCard(
    dynamic id,
    dynamic rawBooking,
    bool isAdmin,
  ) {
    final booking = _map(rawBooking);
    final participant = _isParticipant(booking, controller.actorId);
    final bookingKey = '$id';
    final status = '${booking['status']}';
    final extension = '${booking['extension_minutes']}';

    return Card(
      key: Key('card-$bookingKey'),
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: <Widget>[
            Text(
              'Booking $bookingKey',
              key: Key('booking-$bookingKey'),
            ),
            Text(
              'Status: $status · extension $extension min',
              key: Key('status-$bookingKey'),
            ),
            const SizedBox(height: 8),
            Wrap(
              spacing: 8,
              runSpacing: 4,
              children: <Widget>[
                if (participant)
                  OutlinedButton(
                    key: Key('extend-$bookingKey'),
                    onPressed: controller.busy
                        ? null
                        : () => controller.act(<String, dynamic>{
                              'type': 'extend',
                              'booking_id': id,
                              'minutes': int.tryParse(minutes.text),
                            }),
                    child: const Text('Extend'),
                  ),
                if (participant)
                  OutlinedButton(
                    key: Key('confirm-$bookingKey'),
                    onPressed: controller.busy
                        ? null
                        : () => controller.act(<String, dynamic>{
                              'type': 'confirm',
                              'booking_id': id,
                            }),
                    child: const Text('Confirm'),
                  ),
                if (isAdmin)
                  OutlinedButton(
                    key: Key('complete-$bookingKey'),
                    onPressed: controller.busy
                        ? null
                        : () => controller.act(<String, dynamic>{
                              'type': 'admin_status',
                              'booking_id': id,
                              'event_id': _freshOperationId(
                                'admin',
                                _map(controller.snapshot['audit']),
                              ),
                              'status': 'completed',
                            }),
                    child: const Text('Mark completed'),
                  ),
              ],
            ),
          ],
        ),
      ),
    );
  }

  Widget _messagesPage(Map<String, dynamic> state) {
    final messages = _map(state['messages']);

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: <Widget>[
        const Text(
          'Messages',
          style: TextStyle(fontSize: 26, fontWeight: FontWeight.bold),
        ),
        const SizedBox(height: 8),
        TextField(
          key: const Key('chat-booking'),
          controller: bookingId,
          decoration: const InputDecoration(labelText: 'Booking ID'),
          textInputAction: TextInputAction.next,
        ),
        TextField(
          key: const Key('recipient'),
          controller: peer,
          decoration: const InputDecoration(labelText: 'Recipient'),
          textInputAction: TextInputAction.next,
        ),
        TextField(
          key: const Key('message'),
          controller: message,
          minLines: 1,
          maxLines: 4,
          decoration: const InputDecoration(labelText: 'Message'),
        ),
        const SizedBox(height: 8),
        FilledButton(
          key: const Key('send'),
          onPressed: controller.busy
              ? null
              : () => controller.act(<String, dynamic>{
                    'type': 'message',
                    'booking_id': bookingId.text,
                    'recipient_id': peer.text,
                    'message_id': _freshOperationId('message', messages),
                    'text': message.text,
                  }),
          child: const Text('Save message'),
        ),
        const SizedBox(height: 16),
        for (final entry in messages.entries)
          if (_visibleMessage(entry.value)) _messageRow(entry.key, entry.value),
        if (messages.isEmpty)
          const Padding(
            padding: EdgeInsets.only(top: 12),
            child: Text('No messages are visible to this user.'),
          ),
      ],
    );
  }

  bool _visibleMessage(dynamic rawMessage) {
    if (rawMessage is! Map) return false;
    return rawMessage['sender_id'] == controller.actorId ||
        rawMessage['recipient_id'] == controller.actorId;
  }

  Widget _messageRow(dynamic id, dynamic rawMessage) {
    final value = _map(rawMessage);
    return ListTile(
      key: Key('message-$id'),
      contentPadding: EdgeInsets.zero,
      title: Text('${value['text']}'),
      subtitle: Text('${value['sender_id']} to ${value['recipient_id']}'),
    );
  }

  String _freshOperationId(String prefix, Map<String, dynamic> records) {
    var candidate = '$prefix-${DateTime.now().microsecondsSinceEpoch}-'
        '${_operationSequence++}';
    while (records.containsKey(candidate)) {
      candidate = '$prefix-${DateTime.now().microsecondsSinceEpoch}-'
          '${_operationSequence++}';
    }
    return candidate;
  }

  static Map<String, dynamic> _map(dynamic value) {
    if (value is Map<String, dynamic>) return value;
    if (value is Map) return Map<String, dynamic>.from(value);
    return <String, dynamic>{};
  }

  static bool _isParticipant(Map<String, dynamic> booking, String id) {
    final participants = booking['participants'];
    return participants is List && participants.contains(id);
  }
}
