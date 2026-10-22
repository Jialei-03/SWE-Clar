// Public generic operation/observation transport. No hidden assertions or cases.
import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';
import 'dart:ui' as ui;
import 'package:flutter/services.dart';
import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:service_flow/api.dart';
import 'package:service_flow/controller.dart';
import 'package:service_flow/service_app.dart';
Map<String,dynamic> clone(Map value)=>jsonDecode(jsonEncode(value)) as Map<String,dynamic>;
class ScriptApi implements ServiceApi {
 Map<String,dynamic> config={};final calls=<Map<String,dynamic>>[];
 String? held;Completer<dynamic>? gate;
 Future<dynamic> invoke(String method,Map<String,dynamic> arguments)async{
  calls.add({'method':method,...arguments});
  if(held==method)return await gate!.future;
  if(config['fail']==true)throw StateError('Synthetic API failure');
  if(config.containsKey(method))return config[method];
  if(method=='login')return {'id':'synthetic-user'};
  if(method=='services')return [{'id':'consultation','title':'General consultation','available_slots':['09:00','11:00']},{'id':'followup','title':'Follow-up visit','available_slots':['13:00']}];
  return {'id':'appointment-${calls.where((x)=>x['method']=='book').length}','service_id':arguments['service_id'],'slot':arguments['slot']};
 }
 @override Future<Map<String,dynamic>> login(String username,String password)async=>Map<String,dynamic>.from(await invoke('login',{'username':username,'password':password}));
 @override Future<List<Map<String,dynamic>>> services()async=>(await invoke('services',{}) as List).map((x)=>Map<String,dynamic>.from(x)).toList();
 @override Future<Map<String,dynamic>> book(String serviceId,String slot)async=>Map<String,dynamic>.from(await invoke('book',{'service_id':serviceId,'slot':slot}));
}
void main(){
 testWidgets('Public service operation session',(tester)async{
  WidgetController.hitTestWarningShouldBeFatal=true;
  await tester.binding.setSurfaceSize(const Size(360,900));
  await tester.runAsync(()async{
   for(final entry in {'Roboto':'Roboto-Regular.ttf','MaterialIcons':'MaterialIcons-Regular.otf'}.entries){
    final bytes=await File('/opt/flutter/bin/cache/artifacts/material_fonts/${entry.value}').readAsBytes();
    await (FontLoader(entry.key)..addFont(Future.value(ByteData.view(bytes.buffer)))).load();
   }
  });
  final input=await tester.runAsync(()async=>jsonDecode(await File(Platform.environment['BOOKING_OPERATIONS']!).readAsString()) as Map<String,dynamic>);
  ScriptApi api=ScriptApi();Map<String,Map<String,dynamic>> original={};
  ServiceController c=ServiceController(api);bool mounted=false;Future<void>? pending;
  final boundary=GlobalKey();final observations=<Map<String,dynamic>>[];
  Future<void> settle()async{if(mounted){if(c.busy){await tester.pump();}else{await tester.pumpAndSettle();}}}
  Future<void> mount()async{await tester.pumpWidget(RepaintBoundary(key:boundary,child:ServiceApp(controller:c)));mounted=true;await settle();}
  Future<void> call(Map<String,dynamic> op)async{
   if(op['method']=='login'){await c.login(op['username'] as String? ?? 'synthetic-user',op['password'] as String? ?? 'synthetic-password');}
   else {await c.book(op['service_id'] as String,op['slot'] as String);}
  }
  for(final value in input!['operations'] as List){
   final op=Map<String,dynamic>.from(value as Map);final row=<String,dynamic>{'op':op['op']};
   try{
    switch(op['op']){
     case 'reset':
      if(mounted){await tester.pumpWidget(const SizedBox());mounted=false;}c.dispose();api=ScriptApi();api.config=clone(op['api'] as Map? ?? {});
      original=(clone(op['notifications'] as Map? ?? {})).map((k,v)=>MapEntry(k,Map<String,dynamic>.from(v as Map)));c=ServiceController(api,notifications:original);break;
     case 'mount':await mount();break;
     case 'viewport':await tester.binding.setSurfaceSize(Size((op['width'] as num).toDouble(),(op['height'] as num).toDouble()));await settle();break;
     case 'enter_text':await tester.enterText(find.byKey(ValueKey<String>(op['key'] as String)),op['text'] as String);await settle();break;
     case 'tap':
      final finder=find.byKey(ValueKey<String>(op['key'] as String));await tester.ensureVisible(finder);await settle();await tester.runAsync(()=>tester.tap(finder));
      await tester.runAsync(()async{for(var i=0;c.busy&&i<500;i++)await Future<void>.delayed(const Duration(milliseconds:10));});await settle();break;
     case 'login':await tester.runAsync(()=>call({...op,'method':'login'}));await settle();break;
     case 'book':await tester.runAsync(()=>call({...op,'method':'book'}));await settle();break;
     case 'navigate':c.navigate(op['route'] as String);await settle();break;
     case 'logout':c.logout();await settle();break;
     case 'notification':c.openNotification(op['id'] as String);await settle();break;
     case 'configure':api.config=clone(op['api'] as Map);break;
     case 'hold':api.held=op['method'] as String;api.gate=Completer<dynamic>();break;
     case 'begin':await tester.runAsync(()async{pending=call(op);});await settle();break;
     case 'complete':await tester.runAsync(()async{api.gate!.complete(op['value']);api.gate=null;api.held=null;await pending;});pending=null;await settle();break;
     case 'http_flow':
      await tester.runAsync(()async{
       final prior=HttpOverrides.current;HttpOverrides.global=null;
       final controller=ServiceController(HttpServiceApi(Uri.parse(op['base_url'] as String)));
       final states=<Map<String,dynamic>>[];
       try{
        for(final raw in op['steps'] as List){
         final step=Map<String,dynamic>.from(raw as Map);
         if(step['method']=='login'){
          await controller.login(step['username'] as String,step['password'] as String);
         }else{
          await controller.book(step['service_id'] as String,step['slot'] as String);
         }
         states.add(clone({'user':controller.user,'route':controller.route,'error':controller.error,'appointments':controller.appointments,'busy':controller.busy}));
        }
        row['http_flow']=states;
       }finally{controller.dispose();HttpOverrides.global=prior;}
      });break;
     case 'http_probe':
      await tester.runAsync(()async{
       final prior=HttpOverrides.current;HttpOverrides.global=null;
       try{final http=HttpServiceApi(Uri.parse(op['base_url'] as String));row['http']={'user':await http.login('wire-user','wire-password'),'services':await http.services(),'appointment':await http.book('wire-service','15:00')};}
       catch(e){row['http_error']=e.toString();}finally{HttpOverrides.global=prior;}
      });break;
     case 'capture':
      await tester.runAsync(()async{final render=boundary.currentContext!.findRenderObject()! as RenderRepaintBoundary;final image=await render.toImage();final bytes=await image.toByteData(format:ui.ImageByteFormat.png);await File(op['path'] as String).writeAsBytes(bytes!.buffer.asUint8List());image.dispose();});break;
     case 'mutate_original':original[op['id'] as String]!.addAll(Map<String,dynamic>.from(op['value'] as Map));break;
     case 'inspect':break;
     default:throw ArgumentError('Unknown public operation');
    }
    row.addAll({'user':c.user,'route':c.route,'error':c.error,'busy':c.busy,'services':c.services,'appointments':c.appointments,'notifications':c.notifications,'original_notifications':original,'calls':api.calls});
    if(mounted){row['texts']=[for(final e in find.byType(Text).evaluate())(e.widget as Text).data ?? (e.widget as Text).textSpan?.toPlainText()];row['keys']=[for(final e in find.byWidgetPredicate((w)=>w.key is ValueKey).evaluate())(e.widget.key as ValueKey).value.toString()];}
    final errors=<String>[];Object? e;while((e=tester.takeException())!=null)errors.add(e.toString());row['render_errors']=errors;
   }catch(e){row['operation_error']=e.toString();}
   observations.add(clone(row));
  }
  if(mounted)await tester.pumpWidget(const SizedBox());c.dispose();await tester.binding.setSurfaceSize(null);
  await tester.runAsync(()=>File(Platform.environment['BOOKING_OBSERVATIONS']!).writeAsString(jsonEncode({'observations':observations})));
 });
}
