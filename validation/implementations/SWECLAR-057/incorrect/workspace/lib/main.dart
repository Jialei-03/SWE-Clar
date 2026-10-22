import 'package:flutter/material.dart';

import 'api.dart';
import 'controller.dart';
import 'service_app.dart';

void main() {
  const endpoint = String.fromEnvironment(
    'API_BASE',
    defaultValue: 'http://127.0.0.1:8080',
  );
  runApp(
    ServiceApp(
      controller: ServiceController(HttpServiceApi(Uri.parse(endpoint))),
    ),
  );
}
