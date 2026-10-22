// Public operation adapter: no business expectations or private test cases.
import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';
import 'package:flutter/services.dart';
import 'dart:ui' as ui;
import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:booking_workspace/controller.dart';
import 'package:booking_workspace/booking_app.dart';

Map<String,dynamic> copyMap(Map value) => jsonDecode(jsonEncode(value)) as Map<String,dynamic>;
class ObservedStorage implements BookingStorage {
 final FileBookingStorage delegate;
 bool fail=false;
 Completer<void>? gate;
 int writes=0;
 Map<String,dynamic>? received;
 ObservedStorage(String path):delegate=FileBookingStorage(File(path));
 @override Future<void> save(Map<String,dynamic> state) async {
  received=state;
  if(gate!=null)await gate!.future;
  if(fail)throw const FileSystemException('Synthetic storage failure');
  await delegate.save(state);writes++;
 }
 @override Future<Map<String,dynamic>?> load()=>delegate.load();
}
void main(){
 testWidgets('Public booking operation session',(tester)async{
  WidgetController.hitTestWarningShouldBeFatal=true;
  await tester.binding.setSurfaceSize(const Size(360,950));
  await tester.runAsync(()async{
   for(final entry in {'Roboto':'Roboto-Regular.ttf','MaterialIcons':'MaterialIcons-Regular.otf'}.entries){
    final bytes=await File('/opt/flutter/bin/cache/artifacts/material_fonts/${entry.value}').readAsBytes();
    final loader=FontLoader(entry.key)..addFont(Future.value(ByteData.view(bytes.buffer)));await loader.load();
   }
  });
  final inputPath=Platform.environment['BOOKING_OPERATIONS']!;
  final outputPath=Platform.environment['BOOKING_OBSERVATIONS']!;
  final input=await tester.runAsync(()async=>jsonDecode(await File(inputPath).readAsString()) as Map<String,dynamic>);
  final observations=<Map<String,dynamic>>[];
  final storage=ObservedStorage(input!['state_path'] as String);
  Map<String,dynamic> original=copyMap(input['initial'] as Map);
  BookingController controller=BookingController(original,storage,actorId:input['actor'] as String,platform:input['platform'] as String? ?? 'android');
  final boundary=GlobalKey();bool mounted=false;Future<bool>? pending;
  Future<void> mount()async{
   await tester.pumpWidget(RepaintBoundary(key:boundary,child:BookingApp(controller:controller)));
   await tester.pumpAndSettle();mounted=true;
  }
  Future<void> settle()async{if(mounted){if(controller.busy){await tester.pump();}else{await tester.pumpAndSettle();}}}
  for(final value in input['operations'] as List){
   final operation=Map<String,dynamic>.from(value as Map);
   final row=<String,dynamic>{'op':operation['op']};
   try{
    switch(operation['op']){
     case 'mount':await mount();break;
     case 'file_storage_probe':
      row.addAll((await tester.runAsync(() async {
       final dir=await Directory.systemTemp.createTemp('booking-file-probe-');
       try {
        final file=File('${dir.path}/state.json');
        final store=FileBookingStorage(file);
        final prior=copyMap(input['initial'] as Map);
        final next=copyMap(prior)..['history']=['home','bookings'];
        await store.save(prior);
        final alias=File('${dir.path}/previous.json');
        final linked=await Process.run('ln',[file.path,alias.path]);
        if(linked.exitCode!=0)throw StateError('Cannot prepare file replacement observation: ${linked.stderr}');
        final oldBytes=await alias.readAsString();
        await store.save(next);
        return <String,dynamic>{'previous_bytes_preserved':await alias.readAsString()==oldBytes,
         'loaded':await store.load(),'expected':next,
         'siblings':[for(final entry in await dir.list().toList())entry.path.split('/').last]};
       } finally {await dir.delete(recursive:true);}
      }))!);break;
     case 'viewport':await tester.binding.setSurfaceSize(Size((operation['width'] as num).toDouble(),(operation['height'] as num).toDouble()));await settle();break;
     case 'act':
      final action=copyMap(operation['action'] as Map);final before=copyMap(action);
      row['accepted']=await tester.runAsync(()=>controller.act(action));row['action_unchanged']=jsonEncode(action)==jsonEncode(before);await settle();break;
     case 'tap':
      final finder=find.byKey(ValueKey<String>(operation['key'] as String));
      await tester.ensureVisible(finder);await settle();await tester.runAsync(()=>tester.tap(finder));
      await tester.runAsync(()async{for(var i=0;controller.busy && i<500;i++)await Future<void>.delayed(const Duration(milliseconds:10));});
      await settle();break;
     case 'enter_text':await tester.enterText(find.byKey(ValueKey<String>(operation['key'] as String)),operation['text'] as String);await settle();break;
     case 'hold_storage':storage.gate=Completer<void>();break;
     case 'begin_act':await tester.runAsync(()async{pending=controller.act(copyMap(operation['action'] as Map));});break;
     case 'finish_act':row['accepted']=await tester.runAsync(()async{storage.gate?.complete();storage.gate=null;return await pending!;});pending=null;await settle();break;
     case 'fail_storage':storage.fail=operation['value'] as bool;break;
     case 'restore':await tester.runAsync(()=>controller.restore());await settle();break;
     case 'reopen':
      final actor=controller.actorId,platform=controller.platform;final wasMounted=mounted;
      if(mounted){await tester.pumpWidget(const SizedBox());mounted=false;}
      controller.dispose();controller=BookingController(copyMap(input['initial'] as Map),storage,actorId:actor,platform:platform);
      await tester.runAsync(()=>controller.restore());if(wasMounted)await mount();break;

     case 'switch_actor':
      final state=controller.snapshot;
      if(mounted){await tester.pumpWidget(const SizedBox());mounted=false;}
      controller.dispose();controller=BookingController(state,storage,actorId:operation['actor'] as String,platform:operation['platform'] as String? ?? controller.platform);
      if(operation['mount']==true)await mount();break;
     case 'mutate_initial':original.clear();break;
     case 'mutate_snapshot':controller.snapshot.clear();break;
     case 'mutate_screens':
      final screens=controller.screens();if(screens.isNotEmpty){screens.first['title']='Edited external copy';(screens.first['platforms'] as List).clear();}break;
     case 'mutate_saved_argument':storage.received?.clear();break;
     case 'capture':
      if(!mounted)throw StateError('Mount before capture');
      final target=operation['path'] as String;
      await tester.runAsync(()async{
       final render=boundary.currentContext!.findRenderObject()! as RenderRepaintBoundary;
       final image=await render.toImage();final bytes=await image.toByteData(format:ui.ImageByteFormat.png);
       await File(target).writeAsBytes(bytes!.buffer.asUint8List());image.dispose();
      });row['capture_path']=target;break;
     case 'inspect':break;
     default:throw ArgumentError('Unknown public operation');
    }
    row['snapshot']=controller.snapshot;row['screens']=controller.screens();row['error']=controller.error;row['busy']=controller.busy;row['writes']=storage.writes;
    if(mounted){
     row['texts']=[for(final element in find.byType(Text).evaluate())(element.widget as Text).data ?? (element.widget as Text).textSpan?.toPlainText()];
     row['controls']=[for(final element in find.byWidgetPredicate((w)=>w.key is ValueKey).evaluate()){'key':(element.widget.key as ValueKey).value.toString(),'type':element.widget.runtimeType.toString()}];
     final keyedTexts=<String,List<String>>{};
     for(final element in find.byWidgetPredicate((w)=>w.key is ValueKey).evaluate()){
      final texts=<String>[];
      void collect(Element current){if(current.widget is Text){final text=current.widget as Text;final value=text.data ?? text.textSpan?.toPlainText();if(value!=null)texts.add(value);}current.visitChildElements(collect);}
      collect(element);keyedTexts[(element.widget.key as ValueKey).value.toString()]=texts;
     }
     row['keyed_texts']=keyedTexts;

    }
    final errors=<String>[];Object? error;while((error=tester.takeException())!=null)errors.add(error.toString());row['render_errors']=errors;
   }catch(error,stack){row['operation_error']=error.toString();row['stack']=stack.toString();}
   observations.add(row);
  }
  if(mounted)await tester.pumpWidget(const SizedBox());controller.dispose();await tester.binding.setSurfaceSize(null);
  await tester.runAsync(()=>File(outputPath).writeAsString(jsonEncode({'observations':observations})));
 });
}
