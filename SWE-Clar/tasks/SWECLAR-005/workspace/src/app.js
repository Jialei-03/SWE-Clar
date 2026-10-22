import {buildCyclePlan,dateDay,PHASES} from './cycle-planner.js';
import {readStore,writeStore,emptyStore,defaultSettings,validateSettings} from './journal-store.js';
const $=id=>document.getElementById(id);
let state=readStore(),generation=0,busy=false,lastDay=null;
const today=()=>new Date().toISOString().slice(0,10);
const active=()=>state.profiles.find(p=>p.id===state.activeId);
function planFor(profile,date){const {reminderTime,remindersEnabled,...input}=profile.settings;return buildCyclePlan({...input,asOf:date});}
function node(tag,text){const n=document.createElement(tag);n.textContent=text;return n;}
function save(){writeStore(state);}
function populate(){
  const selection=$('profile-select');selection.replaceChildren(...state.profiles.map(p=>{const n=node('option',p.label);n.value=p.id;return n;}));
  selection.value=state.activeId??'';
  const profile=active();$('workspace').hidden=!profile;if(!profile)return;
  const s=profile.settings;
  $('period-start').value=s.periodStart;$('cycle-length').value=s.cycleLength;$('period-length').value=s.periodLength;$('seed').value=s.seed??0;
  $('prompt-pools').value=JSON.stringify(s.promptPools??{},null,2);$('reminder-time').value=s.reminderTime;$('reminders-enabled').checked=s.remindersEnabled;
  render();
}
function render(){
  const profile=active();if(!profile)return;
  const day=today(),plan=planFor(profile,day);lastDay=day;
  $('today').textContent=day;$('journal-title').textContent=profile.label;$('current-day').textContent=plan.currentDay;$('current-phase').textContent=plan.currentPhase;$('cycle-start').textContent=plan.cycleStart;
  $('recommendation').textContent=plan.recommendation??'No prompt for this phase';
  $('timeline').replaceChildren(...plan.timeline.map(d=>{const n=node('div','');n.className='day';n.dataset.date=d.date;n.dataset.phase=d.phase;n.dataset.day=d.day;n.append(node('strong',d.day),node('span',d.date),node('p',d.phase));if(d.date===day)n.setAttribute('aria-current','date');return n;}));
  $('reminder-history').replaceChildren(...profile.notifiedDays.map(d=>node('li',d)));
  $('permission').textContent=Notification.permission;
}
$('create-form').addEventListener('submit',event=>{
  event.preventDefault();$('feedback').textContent='';
  const label=$('label').value.trim();if(!label||label.length>60){$('feedback').textContent='invalid_input';return;}
  const profile={id:crypto.randomUUID(),label,settings:defaultSettings(today()),notifiedDays:[]};state.profiles.push(profile);state.activeId=profile.id;generation++;save();$('label').value='';populate();$('feedback').textContent='saved';
});
$('profile-select').addEventListener('change',()=>{state.activeId=$('profile-select').value;generation++;save();$('feedback').textContent='';populate();});
$('settings-form').addEventListener('submit',event=>{
  event.preventDefault();$('feedback').textContent='';
  try{
    if(['cycle-length','period-length','seed'].some(id=>!$(id).value.trim()))throw Error('invalid_input');
    const settings={periodStart:$('period-start').value,cycleLength:Number($('cycle-length').value),periodLength:Number($('period-length').value),seed:Number($('seed').value),promptPools:JSON.parse($('prompt-pools').value),reminderTime:$('reminder-time').value,remindersEnabled:$('reminders-enabled').checked};
    validateSettings(settings);active().settings=settings;generation++;save();render();$('feedback').textContent='saved';
  }catch{$('feedback').textContent='invalid_input';}
});
$('enable-notifications').addEventListener('click',async()=>{
  try{const permission=await Notification.requestPermission();$('permission').textContent=permission;$('feedback').textContent=permission==='granted'?'permission_granted':'permission_unavailable';}
  catch{$('feedback').textContent='permission_unavailable';}
});
const registration=navigator.serviceWorker.register('/sw.js').then(()=>navigator.serviceWorker.ready);
registration.catch(()=>{$('feedback').textContent='notification_unavailable';});
async function maybeNotify(){
  // Complete actual reminder delivery after clarifying the scheduling policy.
}

setInterval(()=>{if(active()&&lastDay!==today())render();maybeNotify();},500);
populate();maybeNotify();
