import 'package:flutter/material.dart';
import 'app.dart';
import 'maintenance.dart';
void main() => runApp(FixtureApp(repository: FixtureRepository(const String.fromEnvironment('FIRESTORE_ORIGIN', defaultValue: 'http://127.0.0.1:8080'))));
