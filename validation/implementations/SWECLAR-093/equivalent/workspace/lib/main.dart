import 'package:flutter/material.dart';
import 'api.dart';import 'controller.dart';import 'shop_app.dart';
void main(){final controller=ShopController(HttpShopApi(Uri.parse(const String.fromEnvironment('API_BASE',defaultValue:'http://127.0.0.1:8000')),const String.fromEnvironment('ACCESS_TOKEN')));runApp(ShopApp(controller:controller));controller.load();}
