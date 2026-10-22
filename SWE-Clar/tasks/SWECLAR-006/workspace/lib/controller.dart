import 'dart:convert';
import 'dart:io';
import 'package:flutter/foundation.dart';
Map<String,dynamic> clone(Map<String,dynamic> value)=>jsonDecode(jsonEncode(value)) as Map<String,dynamic>;
abstract class BookingStorage {Future<void> save(Map<String,dynamic> state);Future<Map<String,dynamic>?> load();}
class FileBookingStorage implements BookingStorage {
 final File file;FileBookingStorage(this.file);
 @override Future<Map<String,dynamic>?> load()async=>await file.exists()?jsonDecode(await file.readAsString()) as Map<String,dynamic>:null;
 @override Future<void> save(Map<String,dynamic> state)async{await file.parent.create(recursive:true);final pending=File('${file.path}.pending');try{await pending.writeAsString(jsonEncode(state),flush:true);await pending.rename(file.path);}finally{if(await pending.exists())await pending.delete();}}
}
class BookingController extends ChangeNotifier {
 final BookingStorage storage;final String actorId;final String platform;Map<String,dynamic> _state;String? error;bool busy=false;
 BookingController(Map<String,dynamic> initial,this.storage,{required this.actorId,this.platform='android'}):_state=clone(initial);
 Map<String,dynamic> get snapshot=>clone(_state);
 Future<void> restore()async{final saved=await storage.load();if(saved!=null)_state=clone(saved);notifyListeners();}
 List<Map<String,dynamic>> screens(){final values=(_state['screens'] as Map).entries.where((e)=>(e.value['platforms'] as List).contains(platform)).map((e)=>{'screen_id':e.key,...clone(Map<String,dynamic>.from(e.value))}).toList();values.sort((a,b)=>(a['screen_id'] as String).compareTo(b['screen_id'] as String));return values;}
 Future<bool> act(Map<String,dynamic> action)async{
  if(busy)return false;busy=true;error=null;notifyListeners();
  try{final next=apply(_state,clone(action));await storage.save(clone(next));_state=clone(next);return true;}catch(e){error=e is StateError?e.message.toString():'storage_failed';return false;}finally{busy=false;notifyListeners();}
 }
 Map<String,dynamic> apply(Map<String,dynamic> source,Map<String,dynamic> a){
  final s=clone(source);final kind=a['type'];final users=s['users'] as Map;if(!users.containsKey(actorId))throw StateError('unknown_actor');
  final bookings=s['bookings'] as Map;final messages=s['messages'] as Map;
  switch(kind){
   case 'navigate':final target=a['screen_id'];final screen=(s['screens'] as Map)[target];if(screen==null||!(screen['platforms'] as List).contains(platform))throw StateError('unknown_screen');s['route']=target;break;
   case 'back':throw StateError('not_implemented');
   case 'create_booking':final id=a['booking_id'];final peer=a['peer_id'];if(id is! String||id.trim().isEmpty||bookings.containsKey(id)||!users.containsKey(peer)||peer==actorId)throw StateError('invalid_booking');bookings[id]={'participants':[actorId,peer],'extension_minutes':0,'extended':false,'confirmed':false,'status':'draft'};break;
   case 'extend':case 'confirm':case 'message':case 'admin_status':throw StateError('not_implemented');
   default:throw StateError('unknown_action');
  }
  return s;
 }
}
