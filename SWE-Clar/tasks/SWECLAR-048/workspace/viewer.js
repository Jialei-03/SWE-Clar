let state, generation=0, busy=false;
const canvas=document.querySelector('#video'), context=canvas.getContext('2d'), status=document.querySelector('#status');
async function request(path,body) {
  const response=await fetch(path,body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  const result=await response.json();if(!response.ok)throw new Error(result.error);return result;
}
function error(e){status.textContent=e.message;}
function render() {
  const select=document.querySelector('#device');select.replaceChildren();
  for(const source of state.devices){const option=document.createElement('option');option.value=source.id;option.textContent=source.name;select.append(option);}
  select.value=state.selected||'';document.querySelector('#resolution').value=state.resolution;document.querySelector('#display-input').value=state.display_input;
  document.body.classList.toggle('kiosk',state.kiosk);generation++;
}
async function control(event){state=await request('/api/control',event);render();}
async function frame() {
  if(busy)return;busy=true;const started=generation;
  try {
    const response=await fetch('/api/frame');if(!response.ok)throw new Error((await response.json()).error);
    const bitmap=await createImageBitmap(await response.blob());
    try {
      if(started!==generation)return;
      canvas.width=bitmap.width;canvas.height=bitmap.height;context.drawImage(bitmap,0,0);
      canvas.dataset.sequence=response.headers.get('X-Frame-Sequence');canvas.dataset.input=response.headers.get('X-Display-Input');canvas.dataset.state='playing';
      status.textContent=`${state.display_input} · ${bitmap.width} × ${bitmap.height} · zoom ${state.zoom}`;
    } finally {bitmap.close();}
  } catch(e) {
    if(started===generation){/* Failure presentation is incomplete. */canvas.dataset.state='error';delete canvas.dataset.sequence;error(e);}
  } finally {busy=false;}
}
document.querySelector('#scan').onclick=()=>request('/api/scan',{}).then(s=>{state=s;render();}).catch(error);
document.querySelector('#device').onchange=e=>control({type:'device',id:e.target.value}).catch(error);
document.querySelector('#resolution').onchange=e=>control({type:'resolution',value:e.target.value}).catch(error);
document.querySelector('#display-input').onchange=e=>control({type:'display',value:e.target.value}).catch(error);
window.addEventListener('keydown',e=>{if(['Enter','Escape','Equal','Minus'].includes(e.code)){e.preventDefault();control({type:'key',key:e.code}).catch(error);}});
window.addEventListener('controller-input',e=>control({type:'controller',button:e.detail.button}).catch(error));
for(const button of document.querySelectorAll('[data-button]'))button.onclick=()=>window.dispatchEvent(new CustomEvent('controller-input',{detail:{button:Number(button.dataset.button)}}));
state=await request('/api/state');render();await frame();setInterval(frame,150);
