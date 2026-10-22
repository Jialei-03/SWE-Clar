import 'dart:async';
import 'package:flutter/foundation.dart';
import 'api.dart';
class ShopController extends ChangeNotifier {
 final ShopApi api;List<Map<String,dynamic>> products=[],messages=[];Map<String,dynamic> basket={'lines':<dynamic>[],'total_cents':0};
 String? error;bool loaded=false;StreamSubscription<Map<String,dynamic>>? subscription;bool stopped=false;
 ShopController(this.api);
 Future<void> load() async {
  try {
   final stream=await api.connect();subscription=stream.listen(receive,onError:(_){if(!stopped){error='Connection failed';notifyListeners();}});
   products=await api.catalog();final existing=await api.inbox();for(final message in existing)receive(message);basket=await api.cart();loaded=true;error=null;
  }catch(e){error='Unable to load';}if(!stopped)notifyListeners();
 }
 void receive(Map<String,dynamic> message){if(stopped||messages.any((x)=>x['id']==message['id']))return;messages.add(Map<String,dynamic>.from(message));}
 Future<void> channel(String value,bool enabled) async {try{await api.action({'type':enabled?'subscribe':'unsubscribe','channel':value});error=null;}catch(e){error='Invalid channel';}if(!stopped)notifyListeners();}
 Future<void> change(String product,int quantity,bool add) async {
  try{final next=await api.action({'type':add?'add':'remove','product_id':product,'quantity':quantity});if(!stopped){basket=next;error=null;}}catch(e){error='Cart update failed';}if(!stopped)notifyListeners();
 }
 @override void dispose(){stopped=true;subscription?.cancel();api.close();super.dispose();}
}
