import 'dart:convert';
import 'dart:io';
import 'dart:ui' as ui;
import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  testWidgets('Real Flutter tap -> HTTP -> SQLite -> rendered response', (tester) async {
    // Widget tests normally replace HTTP with a 400-only client. This is an
    // environment-owned integration driver, so use real loopback networking.
    HttpOverrides.global = null;
    final client = HttpClient();
    final mode = Platform.environment['PROBE_MODE']!;
    final origin = Platform.environment['PROBE_ORIGIN']!;
    final boundary = GlobalKey();
    Future<void>? operation;
    String status = 'No request yet';
    Object? failure;
    await tester.runAsync(() async {
      for (final entry in {'Roboto': 'Roboto-Regular.ttf', 'MaterialIcons': 'MaterialIcons-Regular.otf'}.entries) {
        final bytes = await File('/opt/flutter/bin/cache/artifacts/material_fonts/${entry.value}').readAsBytes();
        final loader = FontLoader(entry.key)..addFont(Future.value(ByteData.view(bytes.buffer)));
        await loader.load();
      }
    });
    await tester.binding.setSurfaceSize(const Size(360, 720));
    await tester.pumpWidget(RepaintBoundary(key: boundary, child: MaterialApp(
      home: StatefulBuilder(builder: (context, setState) => Scaffold(
        appBar: AppBar(title: const Text('HTTP / SQLite capability')),
        body: Column(children: [
          Text(status),
          ElevatedButton(onPressed: () {
            operation = () async {
              try {
                if (mode == 'write') {
                  final request = await client.postUrl(Uri.parse('$origin/notes'));
                  request.headers.contentType = ContentType.json;
                  final payload = utf8.encode(jsonEncode({'body': 'Synthetic clinic fixture'}));
                  request.contentLength = payload.length;
                  request.add(payload);
                  final response = await request.close();
                  expect(response.statusCode, 201);
                  await response.drain<void>();
                }
                final request = await client.getUrl(Uri.parse('$origin/notes'));
                final response = await request.close();
                expect(response.statusCode, 200);
                final value = jsonDecode(await utf8.decoder.bind(response).join());
                expect(value['notes'], [{'id': 1, 'body': 'Synthetic clinic fixture'}]);
                setState(() { status = value['notes'][0]['body']; });
              } catch (error) { failure = error; }
            }();
          }, child: Text(mode == 'write' ? 'Save through HTTP' : 'Load after restart')),
        ]),
      )),
    )));
    await tester.runAsync(() async {
      await tester.tap(find.byType(ElevatedButton));
      await operation!.timeout(const Duration(seconds: 10));
    });
    expect(failure, isNull);
    await tester.pumpAndSettle();
    expect(find.text('Synthetic clinic fixture'), findsOneWidget);
    final render = boundary.currentContext!.findRenderObject()! as RenderRepaintBoundary;
    await tester.runAsync(() async {
      final image = await render.toImage();
      final bytes = await image.toByteData(format: ui.ImageByteFormat.png);
      await File('$mode.png').writeAsBytes(bytes!.buffer.asUint8List());
      image.dispose();
    });
    expect(tester.takeException(), isNull);
    client.close(force: true);
  });
}
