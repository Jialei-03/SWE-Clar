import 'dart:convert';
import 'dart:io';
import 'package:http/http.dart' as http;
Future<void> main(List<String> args) async {
 final root=args.single;
 final response=await http.get(Uri.parse('$root/probe/first'));
 if(response.statusCode!=200 || jsonDecode(response.body)['fields']['note']['stringValue']!='kept')throw StateError('Real emulator read failed');
 final p=await http.patch(Uri.parse('$root/probe/dart-write'),headers:{'Content-Type':'application/json'},body:jsonEncode({'fields':{'from_dart':{'booleanValue':true}}}));
 if(p.statusCode!=200)throw StateError('Real emulator write failed');
 stdout.writeln(jsonEncode({'passed':true}));
}
