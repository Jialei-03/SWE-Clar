export const PHASES=['menstrual','follicular','ovulatory','luteal'];
const DAY=86400000;
export function dateDay(value){
  if(typeof value!=='string'||!/^20\d\d-\d\d-\d\d$/.test(value))throw Error('invalid_input');
  const stamp=Date.parse(value+'T00:00:00Z');
  if(!Number.isFinite(stamp)||new Date(stamp).toISOString().slice(0,10)!==value)throw Error('invalid_input');
  return stamp/DAY;
}
export const dayDate=day=>new Date(day*DAY).toISOString().slice(0,10);
export function validate(input){
  if(!input||typeof input!=='object'||Array.isArray(input))throw Error('invalid_input');
  if(Object.keys(input).some(k=>!['periodStart','cycleLength','periodLength','asOf','seed','promptPools'].includes(k)))throw Error('invalid_input');
  dateDay(input.periodStart);dateDay(input.asOf);
  if(!Number.isInteger(input.cycleLength)||input.cycleLength<8||input.cycleLength>60||!Number.isInteger(input.periodLength)||input.periodLength<1||input.periodLength>input.cycleLength-6)throw Error('invalid_input');
  if(input.seed!==undefined&&(!Number.isInteger(input.seed)||input.seed<-2147483648||input.seed>2147483647))throw Error('invalid_input');
  const pools=input.promptPools??{};
  if(typeof pools!=='object'||Array.isArray(pools)||pools===null||Object.keys(pools).some(k=>!PHASES.includes(k)))throw Error('invalid_input');
  for(const pool of Object.values(pools))if(!Array.isArray(pool)||pool.length>32||pool.some(s=>typeof s!=='string'||s.length>200||!s.trim()))throw Error('invalid_input');
}
export function phaseLengths(cycleLength,periodLength){
  const rest=cycleLength-periodLength,part=Math.floor(rest/3);
  return [periodLength,part,part,rest-2*part];
}
export function selectPrompt(pool,seed,epochDay){
  if(!pool.length)return null;
  const index=((seed+epochDay)%pool.length+pool.length)%pool.length;
  return pool[0];
}
export function buildCyclePlan(input){
  validate(input);
  const anchor=dateDay(input.periodStart),today=dateDay(input.asOf),length=input.cycleLength;
  const cycleStart=anchor+Math.floor((today-anchor)/length)*length;
  const sizes=phaseLengths(length,input.periodLength),timeline=[];
  let offset=0;
  sizes.forEach((size,index)=>{for(let i=0;i<size;i++){timeline.push({day:offset+1,date:dayDate(cycleStart+offset),phase:PHASES[index]});offset++;}});
  const currentDay=today-cycleStart+1,currentPhase=timeline[currentDay-1].phase;
  return {currentDay,currentPhase,cycleStart:dayDate(cycleStart),timeline,recommendation:selectPrompt((input.promptPools??{})[currentPhase]??[],input.seed??0,today)};
}
