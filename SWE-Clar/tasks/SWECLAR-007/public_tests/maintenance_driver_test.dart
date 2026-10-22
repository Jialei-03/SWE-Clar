// Public transport: execute actual candidate code and Flutter widgets; no business oracle.
import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';
import 'dart:ui' as ui;
import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:appointment_fixture/app.dart';
import 'package:appointment_fixture/maintenance.dart';

class NetworkBinding extends AutomatedTestWidgetsFlutterBinding {
  @override bool get overrideHttpClient => false;
}
class ObservedClient extends http.BaseClient {
  final http.Client delegate=http.Client();
  final calls=<Map<String,dynamic>>[];
  int pending=0;
  int blocked=0;
  String? failMethod;
  String? holdMethod;
  String? holdPath;
  Completer<void>? gate;
  @override Future<http.StreamedResponse> send(http.BaseRequest request) async {
    pending++;
    calls.add({'method':request.method,'url':request.url.toString()});
    try {
      if(holdMethod==request.method && (holdPath==null || request.url.path.contains(holdPath!)) && gate!=null) { blocked++; try {await gate!.future;} finally {blocked--;} }
      if(failMethod==request.method) return http.StreamedResponse(Stream.value(utf8.encode('{"error":"controlled local failure"}')),503);
      final result=await delegate.send(request);
      // Track completion of response content, not only receipt of response headers.
      final bytes=await result.stream.toBytes();
      return http.StreamedResponse(Stream.value(bytes),result.statusCode,headers:result.headers);
    } finally { pending--; }
  }
  @override void close()=>delegate.close();
}

void main(){
 NetworkBinding();
 testWidgets('Public maintenance operation session',(tester) async {
  WidgetController.hitTestWarningShouldBeFatal=true;
  await tester.binding.setSurfaceSize(const Size(360,950));
  await tester.runAsync(()async{
   for(final entry in {'Roboto':'Roboto-Regular.ttf','MaterialIcons':'MaterialIcons-Regular.otf'}.entries){
    final bytes=await File('/opt/flutter/bin/cache/artifacts/material_fonts/${entry.value}').readAsBytes();
    await (FontLoader(entry.key)..addFont(Future.value(ByteData.view(bytes.buffer)))).load();
   }
  });
  final input=(await tester.runAsync(()async=>jsonDecode(await File(Platform.environment['MAINTENANCE_OPERATIONS']!).readAsString()))) as Map<String,dynamic>;
  final client=ObservedClient();
  final repo=FixtureRepository(input['origin'] as String,client:client);
  final boundary=GlobalKey();bool mounted=false;
  final rows=<Map<String,dynamic>>[];
  Future<void> settle({bool wait=true}) async {
    if(wait) {
      await tester.runAsync(()async {
        for(var i=0;i<1000;i++) {
          await Future<void>.delayed(const Duration(milliseconds:10));
          if(client.gate!=null && client.blocked>0 && client.pending==client.blocked) {
            await Future<void>.delayed(const Duration(milliseconds:10));
            if(client.pending==client.blocked)return;
          }
          if(client.pending==0) {
            await Future<void>.delayed(const Duration(milliseconds:10));
            if(client.pending==0)return;
          }
        }
        throw StateError('Candidate network operation exceeded 10 seconds');
      });
    }
    if(mounted)await tester.pumpAndSettle();
  }
  Future<Map<String,dynamic>> observe(Future<dynamic> Function() operation) async {
    return (await tester.runAsync(()async {
      try { return <String,dynamic>{'value':await operation()}; }
      catch(error) { return <String,dynamic>{'candidate_error':error.toString()}; }
    }))!;
  }
  for(final raw in input['operations'] as List){
    final operation=Map<String,dynamic>.from(raw);final row=<String,dynamic>{'op':operation['op']};
    try {
      switch(operation['op']) {
        case 'mount':
          await tester.runAsync(()=>tester.pumpWidget(RepaintBoundary(key:boundary,child:FixtureApp(repository:repo))));mounted=true;await settle();break;
        case 'view':
          row.addAll(await observe(()=>repo.view(operation['collection'] as String))); break;
        case 'list':
          row.addAll(await observe(()=>repo.list(operation['collection'] as String))); break;
        case 'get':
          row.addAll(await observe(()=>repo.getDocument(operation['path'] as String))); break;
        case 'normalize':
          row.addAll(await observe(()=>repo.normalize(operation['collection'] as String,operation['field'] as String,operation['target'] as String))); await settle();break;
        case 'tap':
          final finder=find.byKey(ValueKey<String>(operation['key'] as String));
          await tester.ensureVisible(finder);await tester.pumpAndSettle();await tester.runAsync(()=>tester.tap(finder));await settle();break;
        case 'hold':client.holdMethod=operation['method'] as String;client.holdPath=operation['path_contains'] as String?;client.gate=Completer<void>();break;
        case 'release':client.holdMethod=null;client.gate?.complete();client.gate=null;await settle();break;
        case 'fail':client.failMethod=operation['method'] as String?;break;
        case 'viewport':await tester.binding.setSurfaceSize(Size((operation['width'] as num).toDouble(),(operation['height'] as num).toDouble()));await settle();break;
        case 'scroll':await tester.drag(find.byKey(const ValueKey<String>('record-list')),Offset(0,(operation['dy'] as num).toDouble()));await settle();break;
        case 'capture':
          await settle();await tester.runAsync(()async {
            final render=boundary.currentContext!.findRenderObject()! as RenderRepaintBoundary;
            final image=await render.toImage();final bytes=await image.toByteData(format:ui.ImageByteFormat.png);
            await File(operation['path'] as String).writeAsBytes(bytes!.buffer.asUint8List());image.dispose();
          });break;
        case 'inspect':await settle();break;
        default:throw ArgumentError('Unknown public operation');
      }
      row['requests']=List<Map<String,dynamic>>.from(client.calls);row['pending_requests']=client.pending;
      if(mounted) {
        row['texts']=[for(final element in find.byType(Text).evaluate()) (element.widget as Text).data ?? (element.widget as Text).textSpan?.toPlainText()];
        row['visible_records']=[for(final element in find.byWidgetPredicate((w)=>w.key is ValueKey && (w.key as ValueKey).value.toString().startsWith('record-') && (w.key as ValueKey).value!='record-list').hitTestable().evaluate()) (element.widget.key as ValueKey).value.toString()];
        final keyed=<String,List<String>>{};
        final buttons=<String,bool>{};
        for(final element in find.byWidgetPredicate((w)=>w.key is ValueKey).evaluate()) {
          final key=(element.widget.key as ValueKey).value.toString();final texts=<String>[];
          void collect(Element current){if(current.widget is Text){final t=current.widget as Text;final text=t.data??t.textSpan?.toPlainText();if(text!=null)texts.add(text);}current.visitChildElements(collect);}
          collect(element);keyed[key]=texts;
          if(element.widget is ButtonStyleButton)buttons[key]=(element.widget as ButtonStyleButton).onPressed!=null;
        }
        row['keyed_texts']=keyed;row['enabled_buttons']=buttons;
      }
      final errors=<String>[];Object? error;while((error=tester.takeException())!=null)errors.add(error.toString());row['render_errors']=errors;
    } catch(error,stack){row['operation_error']=error.toString();row['stack']=stack.toString();}
    rows.add(row);
  }
  if(mounted)await tester.pumpWidget(const SizedBox());client.gate?.complete();repo.close();await tester.binding.setSurfaceSize(null);
  await tester.runAsync(()=>File(Platform.environment['MAINTENANCE_OBSERVATIONS']!).writeAsString(jsonEncode({'observations':rows})));
 });
}
