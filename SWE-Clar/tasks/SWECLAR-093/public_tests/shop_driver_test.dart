// Public generic Flutter and real network operations. No grading assertions.
import 'dart:async';import 'dart:convert';import 'dart:io';import 'dart:typed_data';import 'dart:ui' as ui;
import 'package:flutter/material.dart';import 'package:flutter/services.dart';import 'package:flutter/rendering.dart';import 'package:flutter_test/flutter_test.dart';
import 'package:realtime_shop/api.dart';import 'package:realtime_shop/controller.dart';import 'package:realtime_shop/shop_app.dart';
Map<String,dynamic> clone(Map value)=>jsonDecode(jsonEncode(value)) as Map<String,dynamic>;
void main(){testWidgets('Public shop operation session',(tester)async{
 Future<T?> io<T>(Future<T> Function() operation)async{Object? failure;StackTrace? stack;final result=await tester.runAsync(()async{try{return await operation();}catch(e,s){failure=e;stack=s;return null;}});if(failure!=null)Error.throwWithStackTrace(failure!,stack!);return result;}
 HttpOverrides.global=null;await tester.binding.setSurfaceSize(const Size(420,1100));
 final input=await io(()async=>jsonDecode(await File(Platform.environment['SHOP_OPERATIONS']!).readAsString()) as Map<String,dynamic>);
 final clients=<String,HttpShopApi>{},received=<String,List<Map<String,dynamic>>>{},streams=<StreamSubscription<Map<String,dynamic>>>[];
 final connections=<String,Map<String,dynamic>>{};
 ShopController? c;bool mounted=false;final boundary=GlobalKey();final observations=<Map<String,dynamic>>[];Map<String,dynamic>? original;
 await io(()async{for(final entry in {'Roboto':'Roboto-Regular.ttf','MaterialIcons':'MaterialIcons-Regular.otf'}.entries){final b=await File('/opt/flutter/bin/cache/artifacts/material_fonts/${entry.value}').readAsBytes();await (FontLoader(entry.key)..addFont(Future.value(ByteData.view(b.buffer)))).load();}});
 Future<void> wait(int ms)async{await io(()=>Future<void>.delayed(Duration(milliseconds:ms)));await tester.pump();}
 for(final raw in input!['operations'] as List){final op=Map<String,dynamic>.from(raw);final row=<String,dynamic>{'op':op['op']};try{
  switch(op['op']){
   case 'client':clients[op['name']]=HttpShopApi(Uri.parse(op['base']),op['token']);connections[op['name']]=op;break;
   case 'http':row['http']=await io(()async{final cfg=connections[op['name']]!;final client=HttpClient();try{final request=await client.openUrl(op['method']??'POST',Uri.parse('${cfg['base']}${op['path']}'));request.headers.set('Authorization','Bearer ${cfg['token']}');request.headers.contentType=ContentType.json;if(op.containsKey('value'))request.write(jsonEncode(op['value']));final response=await request.close();final text=await utf8.decoder.bind(response).join();dynamic body;try{body=jsonDecode(text);}catch(_){}return {'status':response.statusCode,'body':body,'raw':text};}finally{client.close(force:true);}});break;
   case 'connect':final name=op['name'] as String;received[name]=[];await io(()async{streams.add((await clients[name]!.connect()).listen((m)=>received[name]!.add(clone(m))));});break;
   case 'action':row['result']=await io(()=>clients[op['name']]!.action(Map<String,dynamic>.from(op['value'])));break;
   case 'get':row['result']=await io(()async{final a=clients[op['name']]!;switch(op['resource']){case 'catalog':return await a.catalog();case 'inbox':return await a.inbox();case 'cart':return await a.cart();default:throw ArgumentError('Unknown resource');}});break;
   case 'load':c=ShopController(clients[op['name']]!);await io(()=>c!.load());break;
   case 'mount':await tester.pumpWidget(RepaintBoundary(key:boundary,child:ShopApp(controller:c!)));mounted=true;break;
   case 'enter':await tester.enterText(find.byKey(ValueKey<String>(op['key'])),op['text']);break;
   case 'tap':final f=find.byKey(ValueKey<String>(op['key']));await tester.ensureVisible(f);await io(()=>tester.tap(f));await wait(op['wait_ms']??150);break;
   case 'receive':original=Map<String,dynamic>.from(op['value']);c!.receive(original!);break;
   case 'mutate_original':original!.addAll(Map<String,dynamic>.from(op['value']));break;
   case 'wait':await wait(op['ms']??150);break;
   case 'viewport':await tester.binding.setSurfaceSize(Size((op['width'] as num).toDouble(),(op['height'] as num).toDouble()));break;
   case 'capture':await tester.pump();await io(()async{final render=boundary.currentContext!.findRenderObject()! as RenderRepaintBoundary;final image=await render.toImage();final b=await image.toByteData(format:ui.ImageByteFormat.png);await File(op['path']).writeAsBytes(b!.buffer.asUint8List());image.dispose();});break;
   case 'inspect':break;
   default:throw ArgumentError('Unknown public operation');
  }
  await tester.pump();
 }catch(e){row['operation_error']=e.toString();}
 row['received']=received.map((k,v)=>MapEntry(k,v.map(clone).toList()));
 if(c!=null)row.addAll({'products':c!.products,'messages':c!.messages,'basket':c!.basket,'error':c!.error,'loaded':c!.loaded});
 if(mounted)row['texts']=[for(final e in find.byType(RichText).evaluate())(e.widget as RichText).text.toPlainText()];
 final errors=<String>[];Object? error;while((error=tester.takeException())!=null)errors.add(error.toString());row['render_errors']=errors;row['time_ms']=DateTime.now().millisecondsSinceEpoch;observations.add(clone(row));
 }
 if(mounted)await tester.pumpWidget(const SizedBox());await io(()async{for(final a in clients.values)await a.close();for(final s in streams)await s.cancel();await File(Platform.environment['SHOP_OBSERVATIONS']!).writeAsString(jsonEncode({'observations':observations,'process':{'pid':pid,'status':await File('/proc/self/status').readAsString(),'environment_keys':Platform.environment.keys.toList()}}));});c?.dispose();await tester.binding.setSurfaceSize(null);
});}
