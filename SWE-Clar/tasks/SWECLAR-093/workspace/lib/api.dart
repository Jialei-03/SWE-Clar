import 'dart:async';
import 'dart:convert';
import 'dart:io';
abstract class ShopApi {
 Future<List<Map<String,dynamic>>> catalog();
 Future<List<Map<String,dynamic>>> inbox();
 Future<Map<String,dynamic>> cart();
 Future<Map<String,dynamic>> action(Map<String,dynamic> value);
 Future<Stream<Map<String,dynamic>>> connect();
 Future<void> close();
}
class HttpShopApi implements ShopApi {
 final Uri base;final String token;final HttpClient client=HttpClient();WebSocket? socket;
 HttpShopApi(this.base,this.token);
 Future<dynamic> request(String method,String path,[Map<String,dynamic>? body]) async {
  final r=await client.openUrl(method,base.resolve(path));r.headers.set('Authorization','Bearer $token');
  if(body!=null){r.headers.contentType=ContentType.json;r.write(jsonEncode(body));}
  final response=await r.close();final data=jsonDecode(await utf8.decoder.bind(response).join());
  if(response.statusCode<200||response.statusCode>=300)throw StateError(data['error']?.toString()??'request_failed');return data;
 }
 @override Future<List<Map<String,dynamic>>> catalog() async =>(await request('GET','/catalog') as List).map((x)=>Map<String,dynamic>.from(x)).toList();
 @override Future<List<Map<String,dynamic>>> inbox() async =>(await request('GET','/inbox') as List).map((x)=>Map<String,dynamic>.from(x)).toList();
 @override Future<Map<String,dynamic>> cart() async =>Map<String,dynamic>.from(await request('GET','/cart'));
 @override Future<Map<String,dynamic>> action(Map<String,dynamic> value) async =>Map<String,dynamic>.from(await request('POST','/actions',value));
 @override Future<Stream<Map<String,dynamic>>> connect() async {
  socket=await WebSocket.connect(base.resolve('/events').replace(scheme:base.scheme=='https'?'wss':'ws').toString(),headers:{'Authorization':'Bearer $token'});
  return socket!.map((value)=>Map<String,dynamic>.from(jsonDecode(value as String)));
 }
 @override Future<void> close() async {await socket?.close();client.close(force:true);}
}
