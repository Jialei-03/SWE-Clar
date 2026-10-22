'use strict';
const $=id=>document.getElementById(id), fields=['document_id','name','group','contact','reviewer','reference'];
let state={profiles:[],template:null,assets:[]},creating=false;
const message=(text,error=false)=>{$('status').textContent=text;$('status').className=error?'error':'';};
async function api(path,{method='GET',body}={}){
  const form=body instanceof FormData;
  const response=await fetch('/api'+path,{method,credentials:'same-origin',headers:body&&!form?{'Content-Type':'application/json'}:{},body:body?(form?body:JSON.stringify(body)):undefined});
  const result=await response.json();if(!response.ok){const error=new Error(result.error?.message||'Request failed');error.code=result.error?.code;throw error;}return result;
}
const option=(value,text)=>{const o=document.createElement('option');o.value=value;o.textContent=text;return o;};
function applyProfile(){
  const profile=state.profiles.find(x=>x.id===$('profilePicker').value);if(!profile)return;
  creating=false;const form=$('profileForm');form.elements.id.value=profile.id;form.elements.id.readOnly=true;fields.forEach(f=>form.elements[f].value=profile.values[f]);
}
function applyStyle(){const form=$('styleForm'),s=state.template.styles[form.elements.field.value];for(const [k,v]of Object.entries(s)){if(k==='visible'||k==='border')form.elements[k].checked=v;else form.elements[k].value=v??'';}}
function applyPlacement(){$('placementForm').elements.asset_id.value=state.template.placements[$('placementForm').elements.slot.value]??'';}
async function refresh({draft=false}={}){
  const [profiles,template,assets,documents,audit]=await Promise.all([api('/profiles'),api('/template'),api('/assets'),api('/documents'),api('/audit')]);
  const selected=$('profilePicker').value;state={profiles:profiles.profiles,template,assets:assets.assets};
  $('profilePicker').replaceChildren(...state.profiles.map(x=>option(x.id,x.id+' · '+x.values.name)));if(state.profiles.some(x=>x.id===selected))$('profilePicker').value=selected;
  $('revision').textContent='Saved template revision: '+template.revision;
  const selectedAsset=$('placementForm').elements.asset_id.value;
  $('placementForm').elements.asset_id.replaceChildren(option('','No image'),...state.assets.map(x=>option(x.id,x.id)));
  $('assets').replaceChildren(...state.assets.map(x=>{const li=document.createElement('li'),img=document.createElement('img'),label=document.createElement('span');img.src='/api/assets/'+x.id;img.alt='Uploaded image '+x.id;label.textContent=x.id;li.append(img,label);return li;}));
  $('documents').replaceChildren(...documents.documents.map(d=>{const li=document.createElement('li'),link=document.createElement('a');link.href='/api/documents/'+encodeURIComponent(d.filename);link.download=d.filename;link.textContent='Download '+d.filename;li.append(link,document.createTextNode(' · '+d.bytes+' bytes · revision '+d.revision));return li;}));
  $('audit').replaceChildren(...audit.events.map(e=>{const tr=document.createElement('tr');for(const v of[e.id,e.actor_id,e.type,e.target,e.revision,new Date(e.timestamp*1000).toISOString()]){const td=document.createElement('td');td.textContent=v;tr.append(td);}return tr;}));
  if(draft){$('placementForm').elements.asset_id.value=selectedAsset;}else{applyProfile();applyStyle();applyPlacement();}
}
async function session(){const {user}=await api('/session');$('identity').textContent=user.id+' ('+user.role+')';$('login').hidden=true;$('logout').hidden=false;$('workspace').hidden=false;await refresh();}
function action(form,handler){form.addEventListener('submit',async e=>{e.preventDefault();const button=form.querySelector('button');button.disabled=true;try{await handler(form);}catch(error){if(error.code==='revision_conflict'){await refresh({draft:true});message(error.message+' Draft retained; retry explicitly.',true);}else message(error.message,true);}finally{button.disabled=false;}});}
$('styleForm').elements.field.replaceChildren(...fields.map(x=>option(x,x)));
action($('login'),async f=>{await api('/login',{method:'POST',body:{username:f.elements.username.value,password:f.elements.password.value}});await session();message('Signed in.');});
$('logout').onclick=async()=>{try{await api('/logout',{method:'POST',body:{}});$('workspace').hidden=true;$('logout').hidden=true;$('login').hidden=false;$('identity').textContent='';message('Signed out.');}catch(e){message(e.message,true);}};
$('profilePicker').onchange=applyProfile;$('newProfile').onclick=()=>{creating=true;$('profileForm').reset();$('profileForm').elements.id.readOnly=false;$('profileForm').elements.id.focus();};
action($('profileForm'),async f=>{const values={};fields.forEach(k=>values[k]=f.elements[k].value);const id=f.elements.id.value;await api(creating?'/profiles':'/profiles/'+id,{method:creating?'POST':'PUT',body:creating?{id,values}:{values}});await refresh();$('profilePicker').value=id;applyProfile();message('Profile saved.');});
action($('renderForm'),async f=>{await api('/render',{method:'POST',body:{profile_id:$('profilePicker').value,kind:f.elements.kind.value,filename:f.elements.filename.value}});await refresh();message('PDF saved. Download it from Saved documents.');});
$('styleForm').elements.field.onchange=applyStyle;
action($('styleForm'),async f=>{const values={color:f.elements.color.value,background:f.elements.background.value||null,font_size:Number(f.elements.font_size.value),weight:f.elements.weight.value,border:f.elements.border.checked,visible:f.elements.visible.checked};await api('/template/fields/'+f.elements.field.value,{method:'PATCH',body:{expected_revision:state.template.revision,values}});await refresh();message('Field settings saved.');});
action($('uploadForm'),async f=>{await api('/assets',{method:'POST',body:new FormData(f)});await refresh();f.reset();message('Image uploaded.');});
$('placementForm').elements.slot.onchange=applyPlacement;
action($('placementForm'),async f=>{await api('/template/placements/'+f.elements.slot.value,{method:'PUT',body:{expected_revision:state.template.revision,asset_id:f.elements.asset_id.value||null}});await refresh();message('Placement saved.');});
$('refresh').onclick=()=>refresh().then(()=>message('Saved state refreshed.')).catch(e=>message(e.message,true));
session().catch(e=>{if(e.code!=='authentication_required')message(e.message,true);});
