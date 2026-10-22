import path from 'node:path';import fs from 'node:fs';import {createRequire} from 'node:module';
const modules=path.resolve(process.env.UI_NODE_MODULES||'node_modules'),require=createRequire(path.join(modules,'../package.json'));const{transform}=require('esbuild');fs.mkdirSync('dist',{recursive:true});
const source=fs.readFileSync('App.jsx','utf8')
 .replace(/import React,\s*\{\s*useState\s*\}\s*from\s*['"]react['"];?/,"const {useState}=React;")
 .replace(/import\s*\{\s*createRoot\s*\}\s*from\s*['"]react-dom\/client['"];?/,"const {createRoot}=ReactDOM;");
const result=await transform(source,{loader:'jsx',format:'iife',target:'es2020'});fs.writeFileSync('dist/app.js',result.code);fs.copyFileSync(path.join(modules,'react/umd/react.production.min.js'),'dist/react.js');fs.copyFileSync(path.join(modules,'react-dom/umd/react-dom.production.min.js'),'dist/react-dom.js');fs.copyFileSync('index.html','dist/index.html');
