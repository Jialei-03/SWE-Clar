const $=id=>document.getElementById(id);
let token=null,actor=null,epoch=0,inflight=null,roomRows=[],savedRules=[],dirty=false;
// Caregivers have the separately granted rule-editing capability.  The server
// repeats this check; this only keeps the control honest for the browser.
const canEdit=()=>actor?.role==='caregiver';
const node=(tag,text,cls)=>{const e=document.createElement(tag);if(text!==undefined)e.textContent=String(text);if(cls)e.className=cls;return e;};
function clearData(){
 roomRows=[];savedRules=[];dirty=false;
 for(const id of ['rooms','alerts','saved-rules','identity','status','rule-status','download-status'])$(id).replaceChildren();
 for(const id of ['household','rule-room','rule-sensor'])$(id).replaceChildren();
 $('as-of').value='';$('rule-threshold').value='10';$('rule-severity').value='warning';
 $('rule-enabled').checked=true;$('rule-kind').value='fridge_open';$('save-rule').disabled=true;
}
async function api(path,body,method='GET',auth=token){
 const r=await fetch(path,{method,headers:{...(auth?{Authorization:'Bearer '+auth}:{}),...(body!==undefined?{'Content-Type':'application/json'}:{})},...(body!==undefined?{body:JSON.stringify(body)}:{})});
 if(!r.ok){let code='request_failed';try{code=(await r.json()).error.code;}catch{}throw Error(code);}
 return r.json();
}
function selectedTime(){const value=Date.parse($('as-of').value);if(!Number.isSafeInteger(value)||value<0||value>253402300799999)throw Error('invalid_evaluation_time');return value;}
function query(path,home,time){return path+'?'+new URLSearchParams({household_id:home,as_of:String(time)});}
function options(select,rows,selected){select.replaceChildren();for(const row of rows){const o=node('option',row.name);o.value=row.id;select.append(o);}if(rows.some(r=>r.id===selected))select.value=selected;}
function showRooms(rows){
 $('rooms').replaceChildren();if(!rows.length)$('rooms').append(node('p','No rooms'));
 for(const room of rows){const box=node('article',undefined,'room');box.dataset.roomId=room.room_id;box.append(node('h3',room.name));
  for(const sensor of room.sensors){const item=node('div',undefined,'sensor');item.dataset.sensorId=sensor.sensor_id;item.append(node('strong',sensor.name),node('span',sensor.sensor_id),node('div',sensor.value===null?'Unknown':sensor.value?'On':'Off','state'),node('div',sensor.timestamp_ms===null?'No observation':new Date(sensor.timestamp_ms).toISOString()),node('div',sensor.stale?'Stale':'Fresh',sensor.stale?'stale':''));box.append(item);}
  $('rooms').append(box);
 }
}
function showAlerts(rows){$('alerts').replaceChildren();if(!rows.length)$('alerts').append(node('p','No current alerts'));for(const row of rows){const e=node('article',undefined,'alert');e.dataset.alertId=row.alert_id;e.append(node('strong',row.kind+' · '+row.severity),node('div',row.room_id+' / '+row.sensor_id),node('p',row.explanation));$('alerts').append(e);}}
function compatibleSensor(sensor,kind){
 const contact=kind==='fridge_open'||kind==='exterior_open_night';
 const presence=kind==='bathroom_occupied_day'||kind==='bathroom_occupied_night'||kind==='no_occupancy';
 return (contact&&sensor.kind==='contact')||(presence&&sensor.kind==='presence');
}
function showRuleForm(){
 const room=roomRows.find(r=>r.room_id===$('rule-room').value);
 const kind=$('rule-kind').value;
 const prior=$('rule-sensor').value;
 const compatible=(room?.sensors??[]).filter(sensor=>compatibleSensor(sensor,kind));
 options($('rule-sensor'),compatible.map(s=>({id:s.sensor_id,name:s.name})),prior);
 const rule=savedRules.find(r=>r.kind===kind);
 if(rule){
  $('rule-sensor').value=rule.sensor_id;
  $('rule-threshold').value=rule.threshold_minutes;
  $('rule-enabled').checked=rule.enabled;
  $('rule-severity').value=rule.severity;
 }else{
  if(!$('rule-sensor').value && compatible.length)$('rule-sensor').value=compatible[0].sensor_id;
  $('rule-threshold').value='10';
  $('rule-enabled').checked=true;
  $('rule-severity').value='warning';
 }
 $('save-rule').disabled=!canEdit()||!room||!$('rule-sensor').value;
}
async function loadRules(expected=epoch){
 const home=$('household').value,room=$('rule-room').value;if(!home||!room)return;
 const result=await api('/api/rules?'+new URLSearchParams({household_id:home,room_id:room}));
 if(epoch!==expected||home!==$('household').value||room!==$('rule-room').value)return;
 savedRules=result.rules;$('saved-rules').replaceChildren();
 if(!savedRules.length)$('saved-rules').append(node('p','No saved rules'));
 for(const rule of savedRules)$('saved-rules').append(node('div',rule.kind+' / '+rule.sensor_id+' / '+rule.threshold_minutes+' min / '+rule.severity+' / '+(rule.enabled?'enabled':'disabled'),'saved-rule'));
 if(!dirty)showRuleForm();
}
async function refresh(){
 if(!token||!$('household').value)return;
 const expected=epoch,home=$('household').value;let time;
 try{time=selectedTime();}catch(e){$('status').textContent=e.message;return;}
 const key=expected+'|'+home+'|'+time;if(inflight===key)return;inflight=key;
 try{
  $('status').textContent='Loading';
  const [snapshot,alerts]=await Promise.all([api(query('/api/snapshot',home,time)),api(query('/api/alerts',home,time))]);
  if(epoch!==expected||home!==$('household').value||time!==selectedTime())return;
  roomRows=snapshot.rooms;showRooms(roomRows);showAlerts(alerts.alerts);
  const room=$('rule-room').value;options($('rule-room'),roomRows.map(r=>({id:r.room_id,name:r.name})),room);await loadRules(expected);
  if(epoch===expected)$('status').textContent='Updated';
 }catch(e){if(epoch===expected)$('status').textContent='Unable to refresh: '+e.message;}
 finally{if(inflight===key)inflight=null;}
}
$('login-form').addEventListener('submit',async e=>{
 e.preventDefault();const expected=++epoch;clearData();$('login-status').textContent='Signing in';
 try{
  const result=await api('/api/login',{id:$('account').value,password:$('password').value},'POST',null);if(epoch!==expected)return;
  token=result.token;actor=result.user;const data=await api('/api/homes');if(epoch!==expected)return;
  options($('household'),data.households);$('as-of').value=new Date(data.clock_ms).toISOString();$('identity').textContent=actor.name+' · '+actor.role;
  $('login-panel').hidden=true;$('application').hidden=false;$('logout').hidden=false;$('login-status').textContent='';$('password').value='';
  if(!data.households.length)$('status').textContent='No accessible households';await refresh();
 }catch(error){if(epoch===expected){token=null;actor=null;clearData();$('login-status').textContent='Sign in failed: '+error.message;}}
});
$('logout').addEventListener('click',()=>{
 const prior=token;epoch++;token=null;actor=null;clearData();
 $('account').value='';$('password').value='';$('login-status').textContent='';
 $('application').hidden=true;$('logout').hidden=true;$('login-panel').hidden=false;
 // Use the old token only for revocation; no response can be applied after
 // epoch was advanced above.
 if(prior)api('/api/logout',{},'POST',prior).catch(()=>{});
});
$('household').addEventListener('change',()=>{
 epoch++;roomRows=[];savedRules=[];dirty=false;
 for(const id of ['rooms','alerts','saved-rules','rule-room','rule-sensor'])$(id).replaceChildren();
 $('rule-threshold').value='10';$('rule-severity').value='warning';$('rule-enabled').checked=true;$('save-rule').disabled=true;
 refresh();
});
$('as-of').addEventListener('change',()=>{epoch++;refresh();});$('refresh').addEventListener('click',refresh);
$('rule-room').addEventListener('change',()=>{
 const expected=epoch;dirty=false;
 loadRules(expected).catch(e=>{if(epoch===expected)$('rule-status').textContent=e.message;});
});
$('rule-kind').addEventListener('change',()=>{dirty=false;showRuleForm();});
for(const id of ['rule-sensor','rule-threshold','rule-enabled','rule-severity'])$(id).addEventListener('input',()=>{dirty=true;});
$('rule-form').addEventListener('submit',async e=>{
 e.preventDefault();const expected=epoch,home=$('household').value,room=$('rule-room').value;$('rule-status').textContent='Saving';
 try{await api('/api/rules',{household_id:home,room_id:room,kind:$('rule-kind').value,sensor_id:$('rule-sensor').value,enabled:$('rule-enabled').checked,threshold_minutes:$('rule-threshold').value===''?null:Number($('rule-threshold').value),severity:$('rule-severity').value},'PUT');if(epoch!==expected)return;dirty=false;await loadRules(expected);$('rule-status').textContent='Saved';await refresh();}
 catch(error){if(epoch===expected){dirty=false;$('rule-status').textContent='Save failed: '+error.message;await loadRules(expected).catch(()=>{});}}
});
$('download').addEventListener('click',async()=>{
 const expected=epoch;$('download-status').textContent='Preparing report';
 try{const response=await fetch(query('/api/report.csv',$('household').value,selectedTime()),{headers:{Authorization:'Bearer '+token}});if(!response.ok)throw Error('request_failed');const blob=await response.blob();if(epoch!==expected)return;const url=URL.createObjectURL(blob);const link=node('a');link.href=url;link.download='activity-report.csv';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);$('download-status').textContent='Report downloaded';}
 catch(error){if(epoch===expected)$('download-status').textContent='Report failed: '+error.message;}
});
setInterval(()=>{if(token)refresh();},1000);
