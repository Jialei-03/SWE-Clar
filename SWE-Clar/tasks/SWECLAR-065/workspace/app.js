const h=React.createElement;
const sections=['patients','charts','scales','predictions','groups'];
const title=s=>s.replaceAll('_',' ').replace(/\b\w/g,c=>c.toUpperCase());
const supplied=structuredClone(window.DASHBOARD_DATA);
let state={metrics:structuredClone(supplied.metrics || {}),active_section:'patients',onboarding:{steps:[],index:0,complete:false}};
const root=ReactDOM.createRoot(document.getElementById('root'));
function numeric(v){return typeof v==='number' && Number.isFinite(v);}
function validMetrics(m){return m && typeof m==='object' && !Array.isArray(m) && Object.values(m).every(v=>numeric(v) || Array.isArray(v) && v.every(numeric));}
function render(){ReactDOM.flushSync(()=>root.render(h(App)));}
function dispatch(action){return {error:{code:'not_implemented'}};}
function Chart({name,values}){
  const max=Math.max(1,...values.map(Math.abs));
  return h('section',{className:'chart','data-metric':name},h('h3',null,title(name)),h('svg',{viewBox:'0 0 600 180',role:'img','aria-label':title(name)},values.map((v,i)=>h('rect',{key:i,x:i*600/Math.max(1,values.length)+8,y:160-Math.abs(v)/max*140,width:Math.max(1,600/Math.max(1,values.length)-16),height:Math.abs(v)/max*140,'data-value':String(v)}))),h('ol',{className:'chart-values'},values.map((v,i)=>h('li',{key:i},String(v)))));
}
function App(){
 const flow=state.onboarding;
 return h(React.Fragment,null,
  h('header',null,h('h1',null,'Patient dashboard'),h('p',null,'Synthetic data for interface evaluation'),h('nav',{'aria-label':'Sections'},sections.map(s=>h('button',{key:s,'aria-current':state.active_section===s?'page':undefined,onClick:()=>dispatch({type:'navigate',section:s})},title(s))))),
  h('main',null,h('h2',{id:'section-title'},title(state.active_section)),state.error?h('p',{id:'error',role:'alert'},state.error.code):null,
   h('div',{className:'metrics'},Object.entries(state.metrics).filter(([,v])=>!Array.isArray(v)).map(([key,value])=>h('article',{key,className:'metric','data-metric':key},h('h3',null,title(key)),h('div',{className:'metric-value'},String(value))))),
   Object.entries(state.metrics).filter(([,v])=>Array.isArray(v)).map(([key,value])=>h(Chart,{key,name:key,values:value})),
   h('button',{id:'start-guide',onClick:()=>dispatch({type:'start_onboarding',steps:supplied.onboarding_steps || []})},'Start guide'),
   flow.steps.length?h('section',{id:'onboarding','aria-label':'Onboarding'},h('h3',null,flow.complete?'Guide complete':'Step '+(flow.index+1)+' of '+flow.steps.length),h('p',{id:'guide-content'},flow.complete?'All steps completed':flow.steps[flow.index]),h('p',{id:'guide-progress'},flow.index+' / '+flow.steps.length+' completed'),flow.complete?null:h('button',{id:'guide-next',onClick:()=>dispatch({type:'advance_onboarding'})},'Next step')):null),
  h('footer',null,'Example dashboard. No real patient records.'));
}
window.dashboard={dispatch,snapshot:()=>structuredClone(state)};
if(!validMetrics(state.metrics)){state.metrics={};state.error={code:'invalid_metrics'};}
render();
