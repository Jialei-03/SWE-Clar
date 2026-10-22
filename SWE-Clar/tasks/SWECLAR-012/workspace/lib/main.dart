import 'package:flutter/material.dart';
import 'clinic.dart';

void main() {
  final controller = ClinicController(origin: const String.fromEnvironment('CLINIC_ORIGIN', defaultValue: 'http://127.0.0.1:8081'));
  runApp(ClinicApp(controller: controller));
}
