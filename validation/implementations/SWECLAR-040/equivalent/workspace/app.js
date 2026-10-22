const q=selector=>document.querySelector(selector);

async function action(payload){
  const response=await fetch('/action',{
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify(payload)
  });
  if(!response.ok)throw Error('Operation failed');
  return response.json();
}

async function show(){
  const params=new URLSearchParams({q:q('#search').value});
  const rows=await (await fetch('/groups?'+params)).json();
  const fragment=document.createDocumentFragment();

  for(const row of rows){
    const section=document.createElement('section');
    section.dataset.group=row.group_id;

    const title=document.createElement('h2');
    title.textContent=row.name||'Unnamed group';
    section.append(title);

    const input=document.createElement('input');
    input.value=row.name||'';
    input.setAttribute('aria-label','Group name');

    const save=document.createElement('button');
    save.textContent='Save name';
    save.onclick=async()=>{
      try{
        await action({type:'label',group_id:row.group_id,name:input.value});
        await show();
      }catch(error){
        q('#error').textContent=error.message;
      }
    };
    section.append(input,save);

    const images=document.createElement('div');
    for(const key of row.image_keys){
      const image=document.createElement('img');
      image.src='/image?key='+encodeURIComponent(key);
      image.alt='Synthetic asset '+key;
      images.append(image);
    }
    section.append(images);
    fragment.append(section);
  }

  q('#groups').replaceChildren(fragment);
}

q('#scan').onclick=async()=>{
  try{
    await action({type:'scan'});
    q('#error').textContent='';
    await show();
  }catch(error){
    q('#error').textContent=error.message;
  }
};
q('#search').oninput=show;
show();
