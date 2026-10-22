import path from 'node:path';import {createRequire} from 'node:module';import {mkdir,copyFile} from 'node:fs/promises';
const modules=path.resolve(process.env.UI_NODE_MODULES||'node_modules');const require=createRequire(path.join(modules,'../package.json'));const {build}=require('esbuild');
const out=path.resolve(process.argv[2]||'dist');await mkdir(out,{recursive:true});
await build({entryPoints:['entry.jsx'],bundle:true,outfile:path.join(out,'app.js'),alias:{'react-native':'react-native-web'},nodePaths:[modules],define:{'process.env.NODE_ENV':'"production"'}});
await build({entryPoints:['model.js'],bundle:true,platform:'node',format:'cjs',outfile:path.join(out,'model.cjs')});
for(const file of ['index.html','config.json'])await copyFile(file,path.join(out,file));
