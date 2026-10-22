import 'dart:convert';
import '../lib/maintenance.dart';
Future<void> main(List<String> args) async {
 if(args.length!=4)throw ArgumentError('Usage: migrate.dart http://127.0.0.1:PORT collection field target_collection');
 final repo=FixtureRepository(args[0]);
 try{print(jsonEncode({'dangling_relations':await repo.normalize(args[1],args[2],args[3])}));}finally{repo.close();}
}
