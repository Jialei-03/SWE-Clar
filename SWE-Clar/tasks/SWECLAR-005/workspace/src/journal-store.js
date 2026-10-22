import {buildCyclePlan,PHASES,dateDay} from './cycle-planner.js';
export const KEY='cycle-journals';
export function validateSettings(settings){
  if(!settings||typeof settings!=='object'||!/^([01]\d|2[0-3]):[0-5]\d$/.test(settings.reminderTime)||typeof settings.remindersEnabled!=='boolean')throw Error('invalid_input');
  const {reminderTime,remindersEnabled,...plan}=settings;
  buildCyclePlan({...plan,asOf:settings.periodStart});
  return settings;
}
export function emptyStore(){return {activeId:null,profiles:[]};}
export function readStore(){
  const raw=localStorage.getItem(KEY);
  if(raw===null)return emptyStore();
  try{
    const value=JSON.parse(raw);
    if(!value||!Array.isArray(value.profiles)||!value.profiles.every(p=>p&&typeof p.id==='string'&&p.id&&typeof p.label==='string'&&p.label.trim()&&p.label.length<=60&&Array.isArray(p.notifiedDays)&&p.notifiedDays.every(d=>{dateDay(d);return true;})&&validateSettings(p.settings)))throw Error();
    if(new Set(value.profiles.map(p=>p.id)).size!==value.profiles.length||!(value.activeId===null||value.profiles.some(p=>p.id===value.activeId)))throw Error();
    return value;
  }catch{return emptyStore();}
}
export function writeStore(state){localStorage.setItem(KEY,JSON.stringify(state));}
export function defaultSettings(today){
  return {periodStart:today,cycleLength:28,periodLength:5,seed:0,reminderTime:'08:00',remindersEnabled:false,
    promptPools:Object.fromEntries(PHASES.map((phase,i)=>[phase,[`Journal prompt ${i+1}: record a small moment.`,`Journal prompt ${i+1}: make time for a conversation.`]]))};
}
