import 'dart:io';
import 'dart:typed_data';
import 'package:flutter/services.dart';
import 'dart:ui' as ui;
import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter_test/flutter_test.dart';
void main() {
 testWidgets('Real render, tap, and file persistence', (tester) async {
  await tester.runAsync(()async{
   for(final entry in {'Roboto':'Roboto-Regular.ttf','MaterialIcons':'MaterialIcons-Regular.otf'}.entries){
    final bytes=await File('/opt/flutter/bin/cache/artifacts/material_fonts/${entry.value}').readAsBytes();
    final loader=FontLoader(entry.key)..addFont(Future.value(ByteData.view(bytes.buffer)));await loader.load();
   }
  });
  int count=0;
  final boundary=GlobalKey();
  await tester.binding.setSurfaceSize(const Size(360,720));
  await tester.pumpWidget(RepaintBoundary(key:boundary,child:MaterialApp(home:StatefulBuilder(builder:(context,setState)=>Scaffold(body:Center(child:ElevatedButton(onPressed:()=>setState(()=>count++),child:Text('Count $count'))))))));
  await tester.tap(find.byType(ElevatedButton));await tester.pumpAndSettle();expect(find.text('Count 1'),findsOneWidget);
  final render=boundary.currentContext!.findRenderObject()! as RenderRepaintBoundary;
  await tester.runAsync(()async{
   final image=await render.toImage();final bytes=await image.toByteData(format:ui.ImageByteFormat.png);
   expect(bytes!.lengthInBytes,greaterThan(100));
   await File('render.png').writeAsBytes(bytes.buffer.asUint8List());image.dispose();
   final pending=File('state.pending');await pending.writeAsString('{"count":1}',flush:true);await pending.rename('state.json');expect(await File('state.json').readAsString(),'{"count":1}');expect(await pending.exists(),isFalse);
  });
  expect(tester.takeException(),isNull);
 });
}
