(()=>{
 const config=JSON.parse(document.querySelector('#site-config').textContent);
 const key='campaign:'+config.site_id+':';
 const consentKey=key+'consent',outboxKey=key+'outbox';
 const panel=document.querySelector('#consent');
 const form=document.querySelector('form');
 const status=document.querySelector('#form-status');
 const count=document.querySelector('#outbox-count');
 const store={
  get(k){try{return localStorage.getItem(k);}catch(error){return null;}},
  set(k,v){try{localStorage.setItem(k,v);}catch(error){}}
 };

 // Consent: an explicit input decision overrides and is persisted on every load;
 // otherwise a stored accept/decline is restored; anything else starts undecided.
 const supplied=config.consent_decision;
 if(supplied==='accept'||supplied==='decline'){
  store.set(consentKey,supplied);
 }else{
  const stored=store.get(consentKey);
  if(stored!=='accept'&&stored!=='decline')panel.hidden=false;
 }
 for(const [id,decision] of [['accept','accept'],['decline','decline']]){
  document.getElementById(id).addEventListener('click',()=>{
   store.set(consentKey,decision);
   panel.hidden=true;
  });
 }

 // Outbox: absent, malformed, non-array or record arrays lacking string
 // request_id/name/email/message are treated as empty.
 const isRecord=value=>value!==null&&typeof value==='object'&&!Array.isArray(value)
  &&typeof value.request_id==='string'&&typeof value.name==='string'
  &&typeof value.email==='string'&&typeof value.message==='string';
 let rows=[];
 try{
  const raw=store.get(outboxKey);
  if(raw!==null){
   const parsed=JSON.parse(raw);
   if(Array.isArray(parsed)&&parsed.every(isRecord))rows=parsed;
  }
 }catch(error){rows=[];}
 const persist=()=>store.set(outboxKey,JSON.stringify(rows));
 const newRequestId=()=>{
  if(window.crypto&&typeof crypto.randomUUID==='function')return crypto.randomUUID();
  return 'request-'+Date.now().toString(36)+'-'+Math.random().toString(36).slice(2)+Date.now().toString(36).slice(-4);
 };

 // Contact form: explicit local validation so the required feedback always runs.
 const emailPattern=/^[^\s@]+@[^\s@]+\.[^\s@]+$/;
 form.addEventListener('submit',event=>{
  event.preventDefault();
  const name=form.elements.name.value.trim();
  const email=form.elements.email.value.trim().toLowerCase();
  const message=form.elements.message.value.trim();
  const valid=name.length>=1&&name.length<=80
   &&message.length>=1&&message.length<=2000
   &&email.length<=254&&emailPattern.test(email);
  if(!valid){
   status.textContent='invalid_contact';
   return;
  }
  rows.push({request_id:newRequestId(),name:name,email:email,message:message});
  persist();
  status.textContent='saved_locally';
  count.textContent='Requests: '+rows.length;
  form.reset();
 });
 count.textContent='Requests: '+rows.length;
})();
