const $=id=>document.getElementById(id);
let token=null, generation=0;
const el=(tag,text)=>{const n=document.createElement(tag);n.textContent=text;return n;};
async function api(path,method='GET',body){
  const response=await fetch(path,{method,headers:{'Content-Type':'application/json',...(token?{Authorization:'Bearer '+token}:{})},...(body===undefined?{}:{body:JSON.stringify(body)})});
  const data=await response.json();if(!response.ok)throw Error(data.error?.code||'request_failed');return data;
}
function clearSession(){token=null;generation++;$('workspace').hidden=true;$('login').hidden=false;for(const id of ['results','connections','messages','posts','target','group-select'])$(id).replaceChildren();$('message').value='';$('content').value='';$('receipt').value='';$('identity').textContent='';$('plan').textContent='';}
async function refresh(){
  const epoch=generation;
  const [me,people,dash]=await Promise.all([api('/api/me'),api('/api/people'),api('/api/dashboard')]);
  if(epoch!==generation)return;
  const u=me.user;$('identity').textContent=u.display+' · '+u.id;$('plan').textContent=u.plan;
  $('interests').value=u.interests.join(',');$('x').value=u.x;$('y').value=u.y;
  for(const [id,rows,name] of [['target',people.people.filter(p=>p.id!==u.id),'display'],['group-select',dash.groups,'name']]){
    const previous=$(id).value;$(id).replaceChildren();for(const row of rows){const n=el('option',row[name]+' ('+row.id+')');n.value=row.id;$(id).append(n);}if(rows.some(r=>r.id===previous))$(id).value=previous;
  }
  $('connections').replaceChildren(...dash.connections.map(c=>el('li',c.target+' · '+(c.accepted?'connected':c.incoming?'incoming':'requested'))));
  $('messages').replaceChildren(...dash.messages.map(m=>{const n=el('article',m.sender+' → '+m.recipient+': '+m.content);n.dataset.messageId=m.id;return n;}));
  $('posts').replaceChildren(...dash.posts.map(p=>{const n=el('article','');n.dataset.postId=p.id;n.append(el('h3',p.author+(p.featured?' · Featured':'')),el('p',p.content),el('span','Likes: '+p.likes+' '));const b=el('button','Like');b.addEventListener('click',()=>perform(async()=>{await api('/api/like','POST',{post_id:p.id});await refresh();}));n.append(b);return n;}));
}
async function perform(work){const epoch=generation;$('feedback').textContent='';try{await work();if(epoch===generation)$('feedback').textContent='saved';}catch(e){if(epoch===generation)$('feedback').textContent=e.message;}}
function form(id,work){$(id).addEventListener('submit',event=>{event.preventDefault();perform(work);});}
form('login',async()=>{const result=await api('/api/login','POST',{id:$('username').value,password:$('password').value});generation++;token=result.token;$('login').hidden=true;$('workspace').hidden=false;$('feedback').textContent='';await refresh();});
$('logout').addEventListener('click',()=>perform(async()=>{await api('/api/logout','POST',{});clearSession();}));
form('profile',async()=>{await api('/api/profile','PUT',{interests:$('interests').value.trim()?$('interests').value.split(',').map(v=>v.trim()):[],x:Number($('x').value),y:Number($('y').value)});await refresh();});
form('discover',async()=>{const epoch=generation;const result=await api('/api/matches?radius='+encodeURIComponent($('radius').value)+'&role='+$('role').value);if(epoch!==generation)return;$('results').replaceChildren(...result.matches.map(m=>{const n=el('article','');n.dataset.userId=m.id;n.append(el('h3',m.display+' · '+m.id),el('p',m.role+' · '+m.shared+' shared · degree '+m.degree+' · '+m.distance.toFixed(2)+' km'));return n;}));});
for(const decision of ['request','accept'])$(decision).addEventListener('click',()=>perform(async()=>{await api('/api/connection','POST',{target:$('target').value,decision});await refresh();}));
for(const blocked of [true,false])$(blocked?'block':'unblock').addEventListener('click',()=>perform(async()=>{await api('/api/block','POST',{target:$('target').value,blocked});await refresh();$('results').replaceChildren();}));
form('message-form',async()=>{await api('/api/message','POST',{target:$('target').value,content:$('message').value});$('message').value='';await refresh();});
form('group-form',async()=>{const group=await api('/api/group','POST',{name:$('group-name').value});$('group-name').value='';await refresh();$('group-select').value=group.id;});
$('invite').addEventListener('click',()=>perform(async()=>{await api('/api/invite','POST',{group_id:$('group-select').value,target:$('target').value});await refresh();}));
form('post-form',async()=>{await api('/api/post','POST',{group_id:$('group-select').value,content:$('content').value,featured:$('featured').checked});$('content').value='';await refresh();});
form('subscribe',async()=>{await api('/api/subscribe','POST',{receipt_id:$('receipt').value});$('receipt').value='';await refresh();});
