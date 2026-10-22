(()=>{
 const config=JSON.parse(document.querySelector('#site-config').textContent),key='campaign:'+config.site_id+':';
 const panel=document.querySelector('#consent');panel.hidden=false;
 for(const id of ['accept','decline'])document.getElementById(id).addEventListener('click',()=>{panel.hidden=true;});
 const form=document.querySelector('form'),status=document.querySelector('#form-status'),count=document.querySelector('#outbox-count');
 let rows=[];count.textContent='Requests: 0';
 form.addEventListener('submit',event=>{event.preventDefault();rows.push({request_id:crypto.randomUUID(),name:form.elements.name.value,email:form.elements.email.value,message:form.elements.message.value});localStorage.setItem(key+'outbox',JSON.stringify(rows));status.textContent='saved_locally';count.textContent='Requests: '+rows.length;form.reset();});
})();
