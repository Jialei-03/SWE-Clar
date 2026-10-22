import 'package:flutter/material.dart';
import 'controller.dart';
class BookingApp extends StatefulWidget {
 final BookingController controller;const BookingApp({super.key,required this.controller});
 @override State<BookingApp> createState()=>_BookingAppState();
}
class _BookingAppState extends State<BookingApp>{
 final id=TextEditingController(text:'sample-booking'),peer=TextEditingController(text:'guest'),minutes=TextEditingController(text:'5'),message=TextEditingController();int sequence=0;
 @override void dispose(){id.dispose();peer.dispose();minutes.dispose();message.dispose();super.dispose();}
 @override Widget build(BuildContext context)=>MaterialApp(debugShowCheckedModeBanner:false,theme:ThemeData(useMaterial3:true,colorSchemeSeed:const Color(0xff23685a)),home:AnimatedBuilder(animation:widget.controller,builder:(context,_){final c=widget.controller,s=c.snapshot;final route=s['route'];return Scaffold(appBar:AppBar(title:const Text('Booking workspace'),leading:IconButton(key:const Key('back'),tooltip:'Back',icon:const Icon(Icons.arrow_back),onPressed:()=>c.act({'type':'back'}))),body:SafeArea(child:Center(child:ConstrainedBox(constraints:const BoxConstraints(maxWidth:700),child:ListView(padding:const EdgeInsets.all(20),children:[
 Text('Signed in: ${c.actorId}'),Wrap(spacing:8,children:[for(final screen in c.screens())TextButton(key:Key('nav-${screen['screen_id']}'),onPressed:()=>c.act({'type':'navigate','screen_id':screen['screen_id']}),child:Text(screen['title'] as String))]),
 if(c.error!=null)Text(c.error!,key:const Key('error'),style:const TextStyle(color:Colors.red)),
 if(route=='home')...[const Text('Plan a booking',style:TextStyle(fontSize:28,fontWeight:FontWeight.bold)),const SizedBox(height:12),const Text('Choose Bookings to create or confirm a local booking. Messages are stored in this workspace.')],
 if(route=='bookings')...[
 const Text('Bookings',style:TextStyle(fontSize:26,fontWeight:FontWeight.bold)),TextField(key:const Key('booking-id'),controller:id,decoration:const InputDecoration(labelText:'Booking ID')),TextField(key:const Key('peer'),controller:peer,decoration:const InputDecoration(labelText:'Other participant')),FilledButton(key:const Key('create'),onPressed:c.busy?null:()=>c.act({'type':'create_booking','booking_id':id.text,'peer_id':peer.text}),child:const Text('Create booking')),
 TextField(key:const Key('minutes'),controller:minutes,keyboardType:TextInputType.number,decoration:const InputDecoration(labelText:'Extension minutes')),
 for(final entry in (s['bookings'] as Map).entries)if((entry.value['participants'] as List).contains(c.actorId)||s['users'][c.actorId]['role']=='admin')Card(child:Padding(padding:const EdgeInsets.all(16),child:Column(crossAxisAlignment:CrossAxisAlignment.start,children:[Text(entry.key,key:Key('booking-${entry.key}')),Text('${entry.value['status']} · extension ${entry.value['extension_minutes']} min',key:Key('status-${entry.key}')),Wrap(spacing:8,children:[OutlinedButton(key:Key('extend-${entry.key}'),onPressed:()=>c.act({'type':'extend','booking_id':entry.key,'minutes':int.tryParse(minutes.text)}),child:const Text('Extend')),OutlinedButton(key:Key('confirm-${entry.key}'),onPressed:()=>c.act({'type':'confirm','booking_id':entry.key}),child:const Text('Confirm')),if(s['users'][c.actorId]['role']=='admin')OutlinedButton(key:Key('complete-${entry.key}'),onPressed:()=>c.act({'type':'admin_status','booking_id':entry.key,'event_id':'admin-${DateTime.now().microsecondsSinceEpoch}-${sequence++}','status':'completed'}),child:const Text('Mark completed'))])]))),
 ],
 if(route=='messages')...[
 const Text('Messages',style:TextStyle(fontSize:26,fontWeight:FontWeight.bold)),TextField(key:const Key('chat-booking'),controller:id,decoration:const InputDecoration(labelText:'Booking ID')),TextField(key:const Key('recipient'),controller:peer,decoration:const InputDecoration(labelText:'Recipient')),TextField(key:const Key('message'),controller:message,decoration:const InputDecoration(labelText:'Message')),FilledButton(key:const Key('send'),onPressed:()=>c.act({'type':'message','booking_id':id.text,'recipient_id':peer.text,'message_id':'message-${DateTime.now().microsecondsSinceEpoch}-${sequence++}','text':message.text}),child:const Text('Save message')),
 for(final entry in (s['messages'] as Map).entries)if(entry.value['sender_id']==c.actorId||entry.value['recipient_id']==c.actorId)ListTile(key:Key('message-${entry.key}'),title:Text(entry.value['text']),subtitle:Text('${entry.value['sender_id']} to ${entry.value['recipient_id']}')),
 ],if(c.busy)const LinearProgressIndicator(),
 ]))))); }));
}
