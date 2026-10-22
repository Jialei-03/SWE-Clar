import 'dart:async';

import 'package:flutter/foundation.dart';

import 'api.dart';

const int _maxSafeInteger = 9007199254740991;

class ShopController extends ChangeNotifier {
  final ShopApi api;

  List<Map<String, dynamic>> products = <Map<String, dynamic>>[];
  List<Map<String, dynamic>> messages = <Map<String, dynamic>>[];
  Map<String, dynamic> basket = <String, dynamic>{
    'lines': <dynamic>[],
    'total_cents': 0,
  };

  String? error;
  bool loaded = false;
  StreamSubscription<Map<String, dynamic>>? subscription;
  bool stopped = false;

  ShopController(this.api);

  Future<void> load() async {
    if (stopped) return;

    try {
      final oldSubscription = subscription;
      subscription = null;
      await oldSubscription?.cancel();

      // Connect before reading the initial inbox.  An event published during
      // the HTTP reads is then either received here or found in the snapshot,
      // and receive() deduplicates the two paths.
      final stream = await api.connect();
      if (stopped) return;
      subscription = stream.listen(
        receive,
        onError: (_) {
          if (!stopped) {
            error = 'Connection failed';
            notifyListeners();
          }
        },
      );

      final loadedProducts = await api.catalog();
      final existingMessages = await api.inbox();
      final loadedBasket = await api.cart();
      if (stopped) return;

      // The API implementations are allowed to return their configured
      // records directly.  Keep controller-owned copies so displaying or
      // updating state never mutates a fixture or a caller-owned object.
      products = loadedProducts.map(_copyMap).toList(growable: true);
      for (final message in existingMessages) {
        _addMessage(message, notify: false);
      }
      basket = _copyBasket(loadedBasket);
      loaded = true;
      error = null;
    } catch (_) {
      if (!stopped) error = 'Unable to load';
    }

    if (!stopped) notifyListeners();
  }

  /// Adds a notification from the WebSocket or an initial inbox snapshot.
  /// Delivery is idempotent by notification id.
  void receive(Map<String, dynamic> message) {
    _addMessage(message, notify: true);
  }

  void _addMessage(Map<String, dynamic> message, {required bool notify}) {
    if (stopped) return;
    final id = message['id'];
    if (messages.any((existing) => existing['id'] == id)) return;
    messages.add(_copyMap(message));
    if (notify && !stopped) notifyListeners();
  }

  Future<void> channel(String value, bool enabled) async {
    if (stopped) return;
    if (value.trim().isEmpty) {
      error = 'Invalid channel';
      notifyListeners();
      return;
    }

    try {
      final result = await api.action(<String, dynamic>{
        'type': enabled ? 'subscribe' : 'unsubscribe',
        'channel': value,
      });
      if (result.containsKey('error')) throw StateError('channel_failed');
      error = null;
    } catch (_) {
      error = 'Invalid channel';
    }
    if (!stopped) notifyListeners();
  }

  Future<void> change(String product, int quantity, bool add) async {
    if (stopped) return;
    if (quantity <= 0 || quantity > _maxSafeInteger) {
      error = 'Invalid quantity';
      notifyListeners();
      return;
    }

    try {
      final next = await api.action(<String, dynamic>{
        'type': add ? 'add' : 'remove',
        'product_id': product,
        'quantity': quantity,
      });
      if (next.containsKey('error') ||
          next['lines'] is! List ||
          !next.containsKey('total_cents')) {
        throw StateError('invalid_cart_response');
      }
      if (!stopped) {
        basket = _copyBasket(next);
        error = null;
      }
    } catch (_) {
      // In particular, do not replace basket with a failed/partial response.
      error = 'Cart update failed';
    }
    if (!stopped) notifyListeners();
  }

  @override
  void dispose() {
    stopped = true;
    final active = subscription;
    subscription = null;
    if (active != null) unawaited(active.cancel());
    unawaited(api.close());
    super.dispose();
  }
}

Map<String, dynamic> _copyMap(Map value) {
  final copy = <String, dynamic>{};
  value.forEach((key, item) {
    if (key is String) copy[key] = _copyValue(item);
  });
  return copy;
}

dynamic _copyValue(dynamic value) {
  if (value is Map) return _copyMap(value);
  if (value is List) return value.map(_copyValue).toList(growable: true);
  return value;
}

Map<String, dynamic> _copyBasket(Map<String, dynamic> value) {
  final copy = _copyMap(value);
  final lines = copy['lines'];
  copy['lines'] = lines is List ? lines.toList(growable: true) : <dynamic>[];
  return copy;
}
