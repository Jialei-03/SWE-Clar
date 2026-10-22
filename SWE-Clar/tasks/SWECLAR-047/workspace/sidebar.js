import {NotebookHost, request, element, message} from './host.js';
const host = new NotebookHost();
let state, selected = [], anchor = null;
const sidebar = document.querySelector('#sidebar'), tree = document.querySelector('#tree');
const uid = ()=>'ITEM-'+crypto.randomUUID();
function allItems(items) { return items.flatMap(x=>[x,...(x.children ? allItems(x.children) : [])]); }
function active() { return state.tabs.find(x=>x.id===state.active_tab); }
function currentFolder() { const item=allItems(active().items).find(x=>x.id===selected[0]); return item?.kind==='folder' ? item.id : null; }
async function action(command) {
  state = await request('/api/action',command); message(); render(); return state;
}
function guarded(work) { return (...args)=>Promise.resolve().then(()=>work(...args)).catch(message); }
function rows() { return [...tree.querySelectorAll('.tree-row')]; }
function select(row,event) {
  const id=row.dataset.item, visible=rows().map(x=>x.dataset.item);
  if (event.shiftKey && anchor && visible.includes(anchor)) {
    const a=visible.indexOf(anchor), b=visible.indexOf(id); selected=visible.slice(Math.min(a,b),Math.max(a,b)+1);
  } else if (event.ctrlKey || event.metaKey) {
    selected=selected.includes(id) ? selected.filter(x=>x!==id) : [...selected,id]; anchor=id;
  } else { selected=[id]; anchor=id; }
  for (const node of rows()) { node.classList.toggle('selected',selected.includes(node.dataset.item)); node.setAttribute('aria-selected',String(selected.includes(node.dataset.item))); }
  row.focus();
}
function rename(row,item) {
  const target=row.querySelector('.label'), input=element('input',undefined,{'aria-label':'Rename item'}); input.value=item.label;
  target.replaceChildren(input); input.focus(); input.select();
  let finished=false;
  const finish=guarded(async save=>{if(finished)return;finished=true;if(save)await action({type:'rename',id:item.id,label:input.value});else render();tree.querySelector(`[data-item="${item.id}"]`)?.focus();});
  input.onkeydown=event=>{event.stopPropagation();if(event.key==='Enter')finish(true);if(event.key==='Escape')finish(false);};
  input.onblur=()=>finish(true);
}
async function open(item) {
  if(item.kind==='folder') {
    const expanded=state.expanded.includes(item.id)?state.expanded.filter(x=>x!==item.id):[...state.expanded,item.id];
    await action({type:'view',expanded});
  } else {await action({type:'open',id:item.id});await host.refresh();}
}
async function keyboard(event,row,item) {
  // Complete the client-approved keyboard behavior.
}

async function drop(event,tabId,parentId,index) {
  event.preventDefault();event.stopPropagation();
  const ids=JSON.parse(event.dataTransfer.getData('application/x-notebook-items'));
  const command={type:'move',ids,tab_id:tabId,parent_id:parentId};if(index!==undefined)command.index=index;
  await action(command);
}
function render() {
  sidebar.style.width=state.width+'px';sidebar.classList.toggle('wrap',state.wrap);document.querySelector('#word-wrap').checked=state.wrap;
  const tabs=document.querySelector('#tabs');tabs.replaceChildren();
  for(const tab of state.tabs) {
    const button=element('button',tab.name,{'data-tab':tab.id});button.classList.toggle('active',tab.id===state.active_tab);
    button.onclick=guarded(async()=>{selected=[];await action({type:'activate',id:tab.id});});
    button.ondragover=e=>e.preventDefault();button.ondrop=guarded(e=>drop(e,tab.id,null));tabs.append(button);
  }
  tree.replaceChildren();
  function append(items,depth,parentId) {
    for(const item of items) {
      const row=element('div',undefined,{class:'tree-row','data-item':item.id,role:'treeitem',tabindex:'0',draggable:'true','aria-selected':String(selected.includes(item.id))});row.style.paddingLeft=(depth*14)+'px';row.classList.toggle('selected',selected.includes(item.id));
      if(item.kind==='folder') {
        row.setAttribute('aria-expanded',String(state.expanded.includes(item.id)));
        const expand=element('button',state.expanded.includes(item.id)?'−':'+',{class:'expand','aria-label':'Toggle '+item.label});
        expand.onclick=guarded(async e=>{e.stopPropagation();await open(item);});row.append(expand);
      } else row.append(element('span','↗',{'aria-hidden':'true'}));
      const text=element('span',item.label,{class:'label'});row.append(text);
      if(item.kind==='bookmark'){const button=element('button','Open',{'aria-label':'Open '+item.label});button.onclick=guarded(async e=>{e.stopPropagation();await open(item);});row.append(button);}
      row.onclick=e=>select(row,e);text.ondblclick=e=>{e.stopPropagation();rename(row,item);};
      row.onkeydown=guarded(e=>keyboard(e,row,item));
      row.ondragstart=e=>{if(!selected.includes(item.id))select(row,{});e.dataTransfer.setData('application/x-notebook-items',JSON.stringify(selected));e.dataTransfer.effectAllowed='move';};
      row.ondragover=e=>{e.preventDefault();e.stopPropagation();};
      row.ondrop=guarded(e=>drop(e,state.active_tab,item.kind==='folder'?item.id:parentId,item.kind==='folder'?undefined:items.filter(x=>!selected.includes(x.id)).findIndex(x=>x.id===item.id)));
      tree.append(row);if(item.children&&state.expanded.includes(item.id))append(item.children,depth+1,item.id);
    }
  }
  append(active().items,0,null);
}
tree.ondragover=e=>e.preventDefault();tree.ondrop=guarded(e=>drop(e,state.active_tab,null));
document.querySelector('#toggle-sidebar').onclick=()=>{sidebar.hidden=!sidebar.hidden;};
document.querySelector('#add-bookmark').onclick=guarded(async()=>{
  const target=host.target(document.querySelector('#target-kind').value);if(!target)throw new Error('No current object of this type');
  await action({type:'bookmark',id:uid(),target_id:target.id,parent_id:currentFolder()});
});
document.querySelector('#new-folder').onclick=guarded(async()=>{const name=prompt('Folder label');if(name!==null)await action({type:'folder',id:uid(),label:name,parent_id:currentFolder()});});
document.querySelector('#new-tab').onclick=guarded(async()=>{const name=prompt('Tab name');if(name!==null)await action({type:'tab',id:uid(),name});});
document.querySelector('#delete-item').onclick=guarded(async()=>{if(selected.length!==1)throw new Error('Select one item to delete');if(confirm('Delete selected item and its descendants?')){await action({type:'delete',id:selected[0],confirmed:true,recursive:true});selected=[];}});
document.querySelector('#sort-items').onclick=guarded(()=>action({type:'sort',parent_id:currentFolder()}));
sidebar.oncontextmenu=e=>{e.preventDefault();document.querySelector('#wrap-menu').hidden=false;};
document.querySelector('#word-wrap').onchange=guarded(e=>action({type:'view',wrap:e.target.checked}));
document.addEventListener('click',e=>{if(!sidebar.contains(e.target)&&e.target.id!=='toggle-sidebar'){sidebar.hidden=true;document.querySelector('#wrap-menu').hidden=true;}});
const resize=document.querySelector('#resize');let resizing=false,width=0;
resize.onpointerdown=e=>{resizing=true;resize.setPointerCapture(e.pointerId);e.preventDefault();};
resize.onpointermove=e=>{if(resizing){width=Math.round(Math.max(180,Math.min(480,e.clientX-sidebar.getBoundingClientRect().left)));sidebar.style.width=width+'px';}};
resize.onpointerup=guarded(async e=>{if(resizing){resizing=false;resize.releasePointerCapture(e.pointerId);if(width)await action({type:'view',width});}});
await host.refresh();state=await request('/api/state');render();
