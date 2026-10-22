import 'package:flutter/material.dart';
import 'controller.dart';
class ShopApp extends StatelessWidget {
 final ShopController controller;const ShopApp({super.key,required this.controller});
 @override Widget build(BuildContext context)=>MaterialApp(home:ShopScreen(controller:controller));
}
class ShopScreen extends StatefulWidget {
 final ShopController controller;const ShopScreen({super.key,required this.controller});
 @override State<ShopScreen> createState()=>_ShopScreenState();
}
class _ShopScreenState extends State<ShopScreen>{
 final channel=TextEditingController(text:'updates'),quantity=TextEditingController(text:'1');
 @override void dispose(){channel.dispose();quantity.dispose();super.dispose();}
 @override Widget build(BuildContext context)=>AnimatedBuilder(animation:widget.controller,builder:(context,_) {final c=widget.controller;
 return Scaffold(appBar:AppBar(title:const Text('Sample shop')),body:ListView(padding:const EdgeInsets.all(20),children:[
 if(c.error!=null)Text(c.error!,key:const Key('error')),
 TextField(key:const Key('channel'),controller:channel,decoration:const InputDecoration(labelText:'Channel')),
 Wrap(spacing:12,children:[FilledButton(key:const Key('subscribe'),onPressed:()=>c.channel(channel.text,true),child:const Text('Subscribe')),TextButton(key:const Key('unsubscribe'),onPressed:()=>c.channel(channel.text,false),child:const Text('Unsubscribe'))]),
 Text('Unread ${c.messages.length}',key:const Key('unread')),
 for(final message in c.messages)ListTile(key:Key('message-${message['id']}'),title:Text(message['title'] as String)),
 const Divider(),TextField(key:const Key('quantity'),controller:quantity,keyboardType:TextInputType.number,decoration:const InputDecoration(labelText:'Quantity')),
 for(final product in c.products)ListTile(title:Text(product['title'] as String),subtitle:Text('Price ${product['price_cents']} cents'),trailing:FilledButton(key:Key('add-${product['id']}'),onPressed:()=>c.change(product['id'] as String,int.tryParse(quantity.text)??0,true),child:const Text('Add'))),
 for(final line in c.basket['lines'] as List)ListTile(title:Text('${line['product_id']} × ${line['quantity']}'),subtitle:Text('Line ${line['line_total_cents']} cents'),trailing:TextButton(key:Key('remove-${line['product_id']}'),onPressed:()=>c.change(line['product_id'] as String,1,false),child:const Text('Remove one'))),
 Text('Total ${c.basket['total_cents']} cents',key:const Key('total'))]));});
}
