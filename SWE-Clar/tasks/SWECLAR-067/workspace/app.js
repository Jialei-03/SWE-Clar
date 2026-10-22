(()=>{
 const clone=value=>JSON.parse(JSON.stringify(value));
 const seed=clone(window.ASSISTANT_DATA||{});let state;
 try{state=JSON.parse(localStorage.getItem('assistant-workspace'))||seed;}catch{state=seed;}
 state.conversations??={};state.bug_reports??={};state.outbox??=[];state.view??={screen:'main'};
 const element=id=>document.getElementById(id);
 function persist(){localStorage.setItem('assistant-workspace',JSON.stringify(state));}
 function paragraph(text){const p=document.createElement('p');p.textContent=String(text);return p;}
 function target(destination,prefill){const url=new URL(destination,location.href);if(prefill!==undefined)url.searchParams.set('text',prefill);return url.href;}
 function render(){
  for(const id of ['home','clinic','chat'])element(id).hidden=(id==='home'?'main':id)!==state.view.screen;
  element('error').textContent=state.error?.code||'';
  const list=element('conversation-list');list.replaceChildren();
  for(const [id,conversation] of Object.entries(state.conversations)){const button=document.createElement('button');button.dataset.conversation=id;button.textContent=conversation.title||id;button.onclick=()=>dispatch({type:'open_chat',conversation_id:id});list.append(button);}
  const chat=state.conversations[state.view.conversation_id];element('transcript').replaceChildren(...(chat?.transcript||[]).map(paragraph));element('pending-question').textContent=chat?.pending_question||'';
  const chatLink=element('chat-cta');chatLink.href='#';
  const ctas=element('clinic-ctas');ctas.replaceChildren();for(const label of ['Schedule Demo','Request a Demo','Pre-Onboard Patients']){const a=document.createElement('a');a.textContent=label;a.href=target(state.routes.schedule);ctas.append(a);}
  element('tips').replaceChildren(...(state.tip_paragraphs||[]).map(paragraph));element('acknowledgement').textContent=state.acknowledgement||'';
  element('feedback').replaceChildren(...state.outbox.filter(x=>x.type==='feedback_prompt').map(x=>{const p=paragraph('Please share feedback on this conversation.');p.dataset.noticeId=x.notice_id;return p;}));
 }
 async function dispatch(event){
  const e=clone(event);const next=clone(state);delete next.error;
  const fail=code=>{state={...state,error:{code}};render();return clone(state);};
  if(e.type==='open_chat'){
   const conversation=next.conversations[e.conversation_id];if(!conversation)return fail('unknown_conversation');
   next.view={screen:'main'};
  }else if(e.type==='show_page'){
   if(!['main','clinic'].includes(e.page))return fail('unknown_page');next.view={screen:e.page};
  }else if(e.type==='format_tip'){
   if(!Array.isArray(e.sentences)||!e.sentences.length||!e.sentences.every(x=>typeof x==='string'&&x.trim()))return fail('invalid_tip');
   next.tip_paragraphs=[e.sentences.map(x=>x.trim()).join(' ')];next.formatted_tip=next.tip_paragraphs.join('\n\n');
  }else if(e.type==='activate_cta'){
   if(e.page==='main'&&e.action==='Chat with Assistant')next.navigation={destination:next.routes.chat,prefill:next.routes.chat_prefill};
   else if(e.page==='clinic'&&['Schedule Demo','Request a Demo','Pre-Onboard Patients'].includes(e.action))next.navigation={destination:next.routes.schedule};
   else return fail('unknown_cta');
   location.assign(target(next.navigation.destination,next.navigation.prefill));
  }else if(e.type==='report_bug'){
   return fail('not_implemented');
  }else if(e.type==='feedback_tick'){
   if(!Number.isInteger(e.day)||e.day<0||!Number.isInteger(e.interval_days)||e.interval_days<=0||typeof e.user_id!=='string'||!e.user_id)return fail('invalid_schedule');
   const id=`feedback:${e.user_id}:${Math.floor(e.day/e.interval_days)}`;
   if(!next.outbox.some(x=>x.notice_id===id))next.outbox.push({notice_id:id,user_id:e.user_id,type:'feedback_prompt'});
  }else return fail('unknown_event');
  state=next;persist();render();return clone(state);
 }
 document.querySelectorAll('[data-page]').forEach(button=>button.onclick=()=>dispatch({type:'show_page',page:button.dataset.page}));
 element('report-bug').onclick=()=>dispatch({type:'report_bug',conversation_id:state.view.conversation_id,report_id:`report:${state.view.conversation_id}`});
 window.assistantApp={dispatch,snapshot:()=>clone(state)};render();
})();
