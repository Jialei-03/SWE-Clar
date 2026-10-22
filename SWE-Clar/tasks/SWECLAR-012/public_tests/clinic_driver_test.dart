// Public Flutter observation transport. No business assertions or private cases.
import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:ui' as ui;
import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:clinic_application/clinic.dart';

void main() {
  testWidgets('Public clinic operation session', (tester) async {
    HttpOverrides.global = null;
    WidgetController.hitTestWarningShouldBeFatal = true;
    final transport = HttpClient();
    final controlOrigin = Platform.environment['CLINIC_CONTROL_ORIGIN']!;
    final controlToken = Platform.environment['CLINIC_CONTROL_TOKEN']!;
    final applicationOrigin = Platform.environment['CLINIC_ORIGIN']!;
    var controller = ClinicController(origin: applicationOrigin);
    final boundary = GlobalKey();
    bool mounted = false;
    await tester.binding.setSurfaceSize(const Size(390, 844));
    await tester.runAsync(() async {
      for (final entry in {'Roboto': 'Roboto-Regular.ttf', 'MaterialIcons': 'MaterialIcons-Regular.otf'}.entries) {
        final bytes = await File('/opt/flutter/bin/cache/artifacts/material_fonts/${entry.value}').readAsBytes();
        final loader = FontLoader(entry.key)..addFont(Future.value(ByteData.view(bytes.buffer)));
        await loader.load();
      }
    });

    Future<Map<String, dynamic>> exchange(String method, String path, [Map<String, dynamic>? body]) async {
      final request = await transport.openUrl(method, Uri.parse('$controlOrigin$path'));
      request.headers.set('Authorization', 'Bearer $controlToken');
      if (body != null) {
        final bytes = utf8.encode(jsonEncode(body));
        request.headers.contentType = ContentType.json;
        request.contentLength = bytes.length;
        request.add(bytes);
      }
      final response = await request.close();
      if (response.statusCode != 200) throw StateError('Operation transport failed: ${response.statusCode}');
      return jsonDecode(await utf8.decoder.bind(response).join()) as Map<String, dynamic>;
    }

    Future<void> settle(bool wait) async {
      if (wait) await tester.runAsync(() => controller.settle().timeout(const Duration(seconds: 20)));
      if (mounted) {
        if (controller.busy) {
          await tester.pump();
        } else {
          await tester.pumpAndSettle();
        }
      }
    }

    Future<void> mount() async {
      await tester.pumpWidget(RepaintBoundary(key: boundary, child: ClinicApp(controller: controller)));
      mounted = true;
      await settle(true);
    }

    Future<Finder> control(String key) async {
      final finder = find.byKey(ValueKey<String>(key));
      for (int i = 0; finder.evaluate().isEmpty && i < 25; i++) {
        final scroll = find.byType(Scrollable);
        if (scroll.evaluate().isEmpty) break;
        await tester.drag(scroll.last, const Offset(0, -240));
        await settle(false);
      }
      if (finder.evaluate().isEmpty) throw StateError('Control not found: $key');
      await tester.ensureVisible(finder.last);
      await settle(false);
      return finder.last;
    }

    Map<String, dynamic> inspect() {
      final row = <String, dynamic>{'busy': controller.busy, 'error': controller.error};
      if (!mounted) return row;
      row['texts'] = [for (final element in find.byType(Text).evaluate())
        (element.widget as Text).data ?? (element.widget as Text).textSpan?.toPlainText()];
      final controls = <Map<String, dynamic>>[];
      final keyedTexts = <String, List<String>>{};
      for (final element in find.byWidgetPredicate((widget) => widget.key is ValueKey).evaluate()) {
        final key = (element.widget.key as ValueKey).value.toString();
        final values = <String>[];
        void collect(Element node) {
          if (node.widget is Text) {
            final text = node.widget as Text;
            final value = text.data ?? text.textSpan?.toPlainText();
            if (value != null) values.add(value);
          }
          node.visitChildElements(collect);
        }
        collect(element);
        keyedTexts[key] = values;
        final item = <String, dynamic>{'key': key, 'type': element.widget.runtimeType.toString()};
        if (element.widget is ButtonStyleButton) item['enabled'] = (element.widget as ButtonStyleButton).onPressed != null;
        if (element.widget is TextField) {
          final field = element.widget as TextField;
          item['text'] = field.obscureText ? '<redacted>' : field.controller?.text;
        }
        controls.add(item);
      }
      row['controls'] = controls;
      row['keyed_texts'] = keyedTexts;
      return row;
    }

    while (true) {
      final operation = (await tester.runAsync(() => exchange('GET', '/next')))!;
      if (operation['op'] == 'close') break;
      final row = <String, dynamic>{'op': operation['op'], 'sequence': operation['sequence']};
      final wait = operation['wait'] != false;
      try {
        switch (operation['op']) {
          case 'mount':
            await mount();
          case 'viewport':
            final width = (operation['width'] as num).toDouble();
            final height = (operation['height'] as num).toDouble();
            if (width < 240 || height < 320 || width > 1600 || height > 1600) throw ArgumentError('Viewport outside supported range');
            await tester.binding.setSurfaceSize(Size(width, height));
            await settle(wait);
          case 'tap':
            final finder = await control(operation['key'] as String);
            await tester.runAsync(() => tester.tap(finder));
            await settle(wait);
          case 'enter_text':
            final finder = await control(operation['key'] as String);
            await tester.enterText(finder, operation['text'] as String);
            await settle(wait);
          case 'select':
            final key = operation['key'] as String;
            final finder = await control(key);
            // Register the dropdown route's completion callback in the real-I/O
            // zone too: its onChanged callback may start an HTTP request later.
            await tester.runAsync(() => tester.tap(finder));
            await settle(false);
            final option = await control('$key-option-${operation['value']}');
            await tester.runAsync(() => tester.tap(option));
            await settle(wait);
          case 'inspect':
            await settle(wait);
          case 'reopen_client':
            await settle(true);
            if (mounted) await tester.pumpWidget(const SizedBox());
            controller.dispose();
            controller = ClinicController(origin: applicationOrigin);
            if (mounted) await mount();
          case 'capture':
            if (!mounted) throw StateError('Mount before capture');
            await settle(wait);
            await tester.runAsync(() async {
              final render = boundary.currentContext!.findRenderObject()! as RenderRepaintBoundary;
              final image = await render.toImage();
              final bytes = await image.toByteData(format: ui.ImageByteFormat.png);
              await File(operation['path'] as String).writeAsBytes(bytes!.buffer.asUint8List());
              image.dispose();
            });
            row['capture'] = operation['name'];
          default:
            throw ArgumentError('Unknown public UI operation: ${operation['op']}');
        }
        row.addAll(inspect());
      } catch (error, stack) {
        row['operation_error'] = error.toString();
        row['stack'] = stack.toString();
      }
      final errors = <String>[];
      Object? error;
      while ((error = tester.takeException()) != null) { errors.add(error.toString()); }
      row['render_errors'] = errors;
      await tester.runAsync(() => exchange('POST', '/result', row));
    }
    if (mounted) await tester.pumpWidget(const SizedBox());
    controller.dispose();
    transport.close(force: true);
    await tester.binding.setSurfaceSize(null);
  }, timeout: const Timeout(Duration(seconds: 230)));
}
