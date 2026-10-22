const q=s=>document.querySelector(s);let token='',bundle=null,view={page:'home'},history=[],epoch=0;
async function api(path,body){const r=await fetch(path,{method:body?'POST':'GET',headers:{Authorization:'Bearer '+token,'Content-Type':'application/json'},body:body?JSON.stringify(body):undefined});if(!r.ok)throw Error('Request could not be completed.');return r.json();}
async function digest(bytes){return Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes)),x=>x.toString(16).padStart(2,'0')).join('');}
async function synchronize(){throw Error('Complete content synchronization.');}
function go(next){history.push({...view});view=next;render();track();}
function track(){if(!token)return;const t=view.page==='product'?['product',view.product_id]:view.page==='category'?['category',view.category_id]:['page','home'];api('/track',{event_id:crypto.randomUUID(),target_type:t[0],target_id:t[1]}).catch(()=>{});}
function render(){const lang=q('#language').value;document.documentElement.lang=lang;q('#content').replaceChildren();q('#version').textContent=bundle?'Content version '+bundle.version:'No synchronized content';q('#back').disabled=!history.length;if(!bundle)return;const cats=[...bundle.categories].sort((a,b)=>a.order-b.order||a.id.localeCompare(b.id));if(view.page!=='home'&&!cats.some(c=>c.id===view.category_id)){view={page:'home'};history=[];}q('#heading').textContent=lang==='es'?'Catálogo':'Catalogue';
 if(view.page==='home'){for(const c of cats){const b=document.createElement('button');b.className='card';b.textContent=c.text[lang];b.dataset.category=c.id;b.onclick=()=>go({page:'category',category_id:c.id});q('#content').append(b);}}
 else if(view.page==='category'){const c=cats.find(x=>x.id===view.category_id);q('#heading').textContent=c.text[lang];for(const p of bundle.products.filter(p=>p.category_id===c.id).sort((a,b)=>a.order-b.order||a.id.localeCompare(b.id))){const b=document.createElement('button'),img=document.createElement('img'),span=document.createElement('span');b.className='card';b.dataset.product=p.id;img.src=bundle.images[p.asset_id];img.alt='';span.textContent=p.text[lang];b.append(img,span);b.onclick=()=>go({page:'product',category_id:c.id,product_id:p.id});q('#content').append(b);}}
 else {const p=bundle.products.find(p=>p.id===view.product_id&&p.category_id===view.category_id);if(!p){view={page:'category',category_id:view.category_id};return render();}q('#heading').textContent=p.text[lang];const img=document.createElement('img');img.className='detail';img.alt=p.text[lang];img.src=bundle.images[p.asset_id];q('#content').append(img);}}
q('#back').onclick=()=>{if(history.length){view=history.pop();render();track();}};
q('#logo').onclick=()=>{if(view.page!=='home')go({page:'home'});};
q('#language').onchange=render;q('#sync').onclick=()=>{const mark=epoch;synchronize().catch(e=>{if(mark===epoch)q('#status').textContent=e.message;});};
q('#connect').onsubmit=e=>{e.preventDefault();epoch++;token=q('#token').value;q('#token').value='';q('#status').textContent='Session connected.';};
q('#settings').onsubmit=async e=>{e.preventDefault();try{await api('/settings',{device_id:q('#device').value});q('#status').textContent='Network settings request acknowledged.';}catch(e){q('#status').textContent=e.message;}};
try{bundle=JSON.parse(localStorage.getItem('kiosk-content')||'null');}catch{bundle=null;}render();

if('serviceWorker' in navigator)navigator.serviceWorker.register('/sw.js');
