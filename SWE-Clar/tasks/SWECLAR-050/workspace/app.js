import {ArenaView} from './render.js';
const view=new ArenaView(document.querySelector('#arena'),document.querySelector('#labels'));window.arenaView=view;
let data,playing=false,busy=false,nextId=1;
const stats=['health','attack','defense','speed','range','cooldown','projectile_speed'];
const status=document.querySelector('#status');
for(const key of stats){const label=document.createElement('label');label.textContent=key.replace('_',' ');const input=document.createElement('input');input.id='stat-'+key;input.type='number';input.step=key==='cooldown'?'1':'any';label.append(input);document.querySelector('#stat-fields').append(label);}
async function request(command){const response=await fetch('/api/command',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(command)});const value=await response.json();if(!response.ok)throw new Error(value.error);data=value;render();return value;}
const guarded=fn=>(...args)=>{try{return Promise.resolve(fn(...args)).catch(e=>{playing=false;status.textContent=e.message;});}catch(e){playing=false;status.textContent=e.message;}};
function option(value,text){const node=document.createElement('option');node.value=value;node.textContent=text;return node;}
function loadTemplate(id){const value=data.config.templates.find(x=>x.id===id);if(!value)return;for(const key of ['id','name','kind'])document.querySelector('#template-'+key).value=value[key];for(const key of stats)document.querySelector('#stat-'+key).value=value[key];}
function render(){
  const chosen=document.querySelector('#catalog').value,placement=document.querySelector('#placement-template').value;
  for(const name of ['catalog','placement-template']){const select=document.querySelector('#'+name);select.replaceChildren(...data.config.templates.map(x=>option(x.id,x.name)));select.value=(name==='catalog'?chosen:placement)||data.config.templates[0]?.id;if(!select.value&&data.config.templates.length)select.value=data.config.templates[0].id;}
  loadTemplate(document.querySelector('#catalog').value);document.querySelector('#limit').value=data.config.max_ticks;
  const locked=data.battle!==null;for(const input of document.querySelectorAll('aside input,aside select,aside button'))input.disabled=locked;
  document.querySelector('#start').disabled=locked;document.querySelector('#step').disabled=!data.battle||data.battle.status!=='running';
  const placements=document.querySelector('#placements');placements.replaceChildren();
  for(const unit of data.config.placements){const row=document.createElement('div'),select=document.createElement('button'),remove=document.createElement('button');select.textContent=`${unit.id} · ${unit.team}`;select.dataset.selectUnit=unit.id;select.disabled=locked;select.onclick=()=>{document.querySelector('#placement-id').value=unit.id;document.querySelector('#team').value=unit.team;document.querySelector('#placement-template').value=unit.template_id;};remove.textContent='Remove';remove.dataset.removeUnit=unit.id;remove.disabled=locked;remove.onclick=guarded(()=>request({type:'remove',id:unit.id}));row.append(select,remove);placements.append(row);}
  status.textContent=data.battle?`${data.battle.status} · tick ${data.battle.tick}`:'Arrange both teams';
  const finished=data.battle?.status==='finished';document.querySelector('#results').hidden=!finished;
  if(finished){playing=false;document.querySelector('#outcome').textContent=`Result: ${data.battle.winner} · ${data.battle.tick} ticks`;const results=document.querySelector('#team-results');results.replaceChildren();
    for(const team of ['A','B']){const section=document.createElement('div'),title=document.createElement('h3'),table=document.createElement('table');title.textContent='Team '+team;
      const head=document.createElement('tr');for(const text of ['Unit','Health','Damage']){const th=document.createElement('th');th.textContent=text;head.append(th);}table.append(head);
      for(const unit of data.battle.units.filter(x=>x.team===team)){const row=document.createElement('tr');row.dataset.resultUnit=unit.id;for(const text of [unit.name,unit.hp,unit.damage_dealt]){const cell=document.createElement('td');cell.textContent=String(text);row.append(cell);}table.append(row);}section.append(title,table);results.append(section);
    }
  }
  view.update(data);
}
document.querySelector('#catalog').onchange=e=>loadTemplate(e.target.value);
document.querySelector('#template-form').onsubmit=guarded(async e=>{e.preventDefault();const value={};for(const key of ['id','name','kind'])value[key]=document.querySelector('#template-'+key).value;for(const key of stats)value[key]=Number(document.querySelector('#stat-'+key).value);await request({type:'template',value});document.querySelector('#catalog').value=value.id;loadTemplate(value.id);});
document.querySelector('#delete-template').onclick=guarded(()=>request({type:'delete_template',id:document.querySelector('#template-id').value}));
document.querySelector('#clear').onclick=guarded(()=>request({type:'clear'}));document.querySelector('#save-limit').onclick=guarded(()=>request({type:'limit',value:Number(document.querySelector('#limit').value)}));
document.querySelector('#arena').onclick=guarded(async e=>{if(e.button!==0||data.battle)return;const p=view.ground(e.clientX,e.clientY);await request({type:'place',id:document.querySelector('#placement-id').value,template_id:document.querySelector('#placement-template').value,team:document.querySelector('#team').value,x:Math.round(p.x*1000)/1000,z:Math.round(p.z*1000)/1000});document.querySelector('#placement-id').value='UNIT-'+(++nextId);});
document.querySelector('#start').onclick=guarded(async()=>{await request({type:'start'});playing=true;});
document.querySelector('#pause').onclick=()=>{playing=!playing;};document.querySelector('#step').onclick=guarded(async()=>{playing=false;await request({type:'step',ticks:1});});
document.querySelector('#reset').onclick=guarded(async()=>{playing=false;await request({type:'reset'});});
document.querySelector('#camera-side').onclick=()=>{view.yaw+=Math.PI;view.draw();};document.querySelector('#names').onchange=e=>{view.showNames=e.target.checked;view.draw();};
setInterval(guarded(async()=>{if(!playing||busy||data.battle?.status!=='running')return;busy=true;try{await request({type:'step',ticks:1});}finally{busy=false;}}),100);
data=await(await fetch('/api/state')).json();render();
