import {Midi} from '@tonejs/midi';
import {PDFDocument,StandardFonts,rgb} from 'pdf-lib';

const $=selector=>document.querySelector(selector);
const chartSelect=$('#chart');
const video=$('#recording');
const scoreRoot=$('#score');
const pitchList=$('#pitch-list');
const transposeInput=$('#transpose');
const modeSelect=$('#mode');
const seekInput=$('#seek');
const positionOutput=$('#position');
const errorOutput=$('#error');

const PITCH_NAMES=['C','C#','D','D#','E','F','F#','G','G#','A','A#','B'];
const STAFF_LINE_COLOR='#213c43';
const ACTIVE_NOTE_COLOR='#bd552b';
const DEFAULT_NOTE_COLOR=STAFF_LINE_COLOR;
const DIATONIC_BY_CLASS=[0,0,1,1,2,3,3,4,4,5,5,6];

let config=null;
let configPromise=null;
let sourceMidi=null;
let sourceBytes=null;
let sourceNotes=Object.freeze([]);
// The accepted score is a separate immutable view of the source.  Keeping the
// view, rather than editing parsed MIDI note objects, makes every consumer use
// the same pitch/timing snapshot.
let currentScore=Object.freeze([]);
let scoreDuration=1;
let acceptedOffset=0;
let rejectedOffsetInput=null;
let pendingSeek=null;
let loadSerial=0;

let audioContext=null;
let analyser=null;
let voices=[];
let audioSerial=0;

function makeError(code,message=code){
  const error=new Error(message);
  error.code=code;
  return error;
}

function errorMessage(error){
  if(error&&typeof error.message==='string'&&error.message)return error.message;
  return String(error||'Unknown error');
}

function showError(error){
  errorOutput.textContent=errorMessage(error);
}

function clearError(){
  errorOutput.textContent='';
}

function pitchLabel(midi){
  const value=Math.trunc(midi);
  const pitchClass=((value%12)+12)%12;
  return `${PITCH_NAMES[pitchClass]}${Math.floor(value/12)-1}`;
}

/* C4 is the ledger-line note immediately below a treble staff.  E4 is the
 * bottom staff line and F5 is the top staff line.  Sharps share their
 * natural pitch's vertical position. */
function staffY(midi){
  const pitchClass=((midi%12)+12)%12;
  const octave=Math.floor(midi/12);
  const diatonicFromC4=(octave-5)*7+DIATONIC_BY_CLASS[pitchClass];
  return 140-diatonicFromC4*5;
}

function svgElement(tag,attributes={},text){
  const element=document.createElementNS('http://www.w3.org/2000/svg',tag);
  for(const [name,value] of Object.entries(attributes))element.setAttribute(name,String(value));
  if(text!==undefined)element.textContent=text;
  return element;
}

function snapshotNotes(parsed){
  const result=[];
  for(const track of parsed.tracks){
    for(const note of track.notes){
      const midi=Number(note.midi);
      const time=Number(note.time);
      const duration=Number(note.duration);
      if(!Number.isInteger(midi)||midi<0||midi>127||!Number.isFinite(time)||!Number.isFinite(duration)||duration<0){
        throw makeError('invalid_midi','invalid MIDI note');
      }
      result.push(Object.freeze({
        midi,
        time,
        duration,
        velocity:Number.isFinite(Number(note.velocity))?Number(note.velocity):0.8
      }));
    }
  }
  return Object.freeze(result);
}

function buildScore(offset){
  return Object.freeze(sourceNotes.map(source=>Object.freeze({
    midi:source.midi+offset,
    time:source.time,
    duration:source.duration,
    velocity:source.velocity,
    sourceMidi:source.midi
  })));
}

function renderScore(score=currentScore){
  scoreRoot.replaceChildren();
  const duration=Math.max(1,scoreDuration);

  // Keep the normal scaffold geometry unchanged, while allowing a valid
  // extreme MIDI transposition to remain visible with ledger lines.
  let top=0;
  let bottom=240;
  for(const note of score){
    const y=staffY(note.midi);
    top=Math.min(top,y-35);
    bottom=Math.max(bottom,y+10);
  }
  scoreRoot.setAttribute('viewBox',`0 ${top} 1000 ${bottom-top}`);

  const staffLines=[];
  for(let line=0;line<5;line++){
    staffLines.push(svgElement('line',{
      x1:20,y1:90+line*10,x2:980,y2:90+line*10,
      stroke:STAFF_LINE_COLOR,'stroke-width':1
    }));
  }
  scoreRoot.append(...staffLines);

  for(const [index,note] of score.entries()){
    const x=50+(note.time/duration)*870;
    const y=staffY(note.midi);
    const label=pitchLabel(note.midi);
    const group=svgElement('g',{
      'data-note':index,
      'data-midi':note.midi,
      'data-source-midi':note.sourceMidi,
      'data-time':note.time,
      'data-duration':note.duration,
      'aria-label':`${label} at ${note.time.toFixed(3)} seconds`
    });

    group.append(
      svgElement('ellipse',{cx:x,cy:y,rx:7,ry:5,fill:DEFAULT_NOTE_COLOR,'data-note-head':'true'}),
      svgElement('line',{x1:x+6,y1:y,x2:x+6,y2:y-28,stroke:STAFF_LINE_COLOR,'stroke-width':1.5})
    );

    if(label.includes('#')){
      group.append(svgElement('text',{
        x:x-17,y:y+5,'font-size':16,fill:STAFF_LINE_COLOR,'text-anchor':'middle'
      },'#'));
    }
    group.append(svgElement('text',{
      x,y:190,'text-anchor':'middle','font-size':14,fill:STAFF_LINE_COLOR
    },label));

    // Ledger lines below the E4 line and above the F5 line only.
    for(let ledger=140;ledger<=y;ledger+=10){
      group.append(svgElement('line',{
        x1:x-12,y1:ledger,x2:x+12,y2:ledger,stroke:STAFF_LINE_COLOR,'stroke-width':1
      }));
    }
    for(let ledger=80;ledger>=y;ledger-=10){
      group.append(svgElement('line',{
        x1:x-12,y1:ledger,x2:x+12,y2:ledger,stroke:STAFF_LINE_COLOR,'stroke-width':1
      }));
    }
    scoreRoot.append(group);
  }
  pitchList.textContent=score.map(note=>pitchLabel(note.midi)).join(' · ');
}

function acceptOffset(offset){
  acceptedOffset=offset;
  currentScore=buildScore(offset);
  renderScore(currentScore);
}

function stopSynth(){
  audioSerial+=1;
  const oldVoices=voices;
  voices=[];
  for(const voice of oldVoices){
    try{voice.osc.stop();}catch{}
    try{voice.osc.disconnect();}catch{}
    try{voice.gain.disconnect();}catch{}
  }
}

async function getAudioContext(){
  if(!audioContext){
    const AudioContextClass=window.AudioContext||window.webkitAudioContext;
    if(!AudioContextClass)throw makeError('synth_unavailable','Synthesizer audio is unavailable');
    audioContext=new AudioContextClass();
    analyser=audioContext.createAnalyser();
    analyser.fftSize=8192;
    analyser.connect(audioContext.destination);
  }
  if(audioContext.state==='suspended')await audioContext.resume();
  return audioContext;
}

async function scheduleSynth(){
  stopSynth();
  if(modeSelect.value!=='synth'||video.paused||!currentScore.length)return;
  const serial=audioSerial;
  const context=await getAudioContext();
  if(serial!==audioSerial||modeSelect.value!=='synth'||video.paused)return;

  const position=Number.isFinite(video.currentTime)?video.currentTime:0;
  const now=context.currentTime;
  const scheduled=[];
  for(const note of currentScore){
    const noteEnd=note.time+note.duration;
    if(noteEnd<=position)continue;
    const startOffset=Math.max(0,note.time-position);
    const endOffset=noteEnd-position;
    if(endOffset<=startOffset)continue;

    const oscillator=context.createOscillator();
    const gain=context.createGain();
    const startAt=now+startOffset;
    const endAt=now+endOffset;
    const frequency=440*Math.pow(2,(note.midi-69)/12);
    oscillator.type='sine';
    oscillator.frequency.value=frequency;
    gain.gain.value=0.12;
    oscillator.connect(gain).connect(analyser);
    oscillator.start(startAt);
    oscillator.stop(endAt);
    scheduled.push({osc:oscillator,gain});
  }
  if(serial!==audioSerial||modeSelect.value!=='synth'||video.paused){
    for(const voice of scheduled){
      try{voice.osc.stop();}catch{}
      try{voice.osc.disconnect();}catch{}
      try{voice.gain.disconnect();}catch{}
    }
    return;
  }
  voices=scheduled;
}

function updateSeekRange(){
  const duration=video.duration;
  if(Number.isFinite(duration)&&duration>=0)seekInput.max=String(duration);
}

function waitForMetadata(serial){
  if(serial!==loadSerial)return Promise.resolve();
  if(video.readyState>=1)return Promise.resolve();
  return new Promise((resolve,reject)=>{
    let settled=false;
    const finish=(callback,value)=>{
      if(settled)return;
      settled=true;
      video.removeEventListener('loadedmetadata',onMetadata);
      video.removeEventListener('durationchange',onDuration);
      video.removeEventListener('error',onError);
      clearTimeout(timer);
      callback(value);
    };
    const onMetadata=()=>finish(resolve);
    const onDuration=()=>{if(video.readyState>=1)finish(resolve);};
    const onError=()=>finish(reject,makeError('recording_unavailable','recording media is unavailable'));
    const timer=setTimeout(()=>finish(reject,makeError('recording_timeout','recording metadata did not load')),15000);
    video.addEventListener('loadedmetadata',onMetadata);
    video.addEventListener('durationchange',onDuration);
    video.addEventListener('error',onError);
  });
}

function parseMidiBytes(bytes){
  if(bytes.byteLength<14||String.fromCharCode(...bytes.subarray(0,4))!=='MThd'){
    throw makeError('invalid_midi','invalid MIDI file');
  }
  let parsed;
  try{
    parsed=new Midi(bytes.slice().buffer);
  }catch(error){
    throw makeError('invalid_midi','invalid MIDI file');
  }
  const parsedNotes=snapshotNotes(parsed);
  if(!parsedNotes.length)throw makeError('empty_score','MIDI file contains no notes');
  let finalTime=0;
  for(const note of parsedNotes)finalTime=Math.max(finalTime,note.time+note.duration);
  const midiDuration=Number(parsed.duration);
  scoreDuration=Math.max(1,Number.isFinite(midiDuration)?midiDuration:0,finalTime);
  return {parsed,bytes:bytes.slice(),notes:parsedNotes};
}

async function loadChart(id){
  if(!config){
    if(!configPromise)throw makeError('config_unavailable','chart configuration is unavailable');
    await configPromise;
  }
  const chart=config.charts.find(item=>item.id===id);
  if(!chart)throw makeError('unknown_chart','unknown chart');
  const serial=++loadSerial;

  stopSynth();
  video.pause();
  const response=await fetch(chart.midi);
  if(!response.ok)throw makeError('midi_unavailable','MIDI file is unavailable');
  const raw=new Uint8Array(await response.arrayBuffer());
  const decoded=parseMidiBytes(raw);
  if(serial!==loadSerial)return;

  sourceMidi=decoded.parsed;
  sourceBytes=decoded.bytes;
  sourceNotes=decoded.notes;
  acceptedOffset=0;
  rejectedOffsetInput=null;
  transposeInput.value='0';
  currentScore=Object.freeze([]);
  const parsedDuration=Number(sourceMidi.duration);
  scoreDuration=Math.max(1,Number.isFinite(parsedDuration)?parsedDuration:0);
  for(const note of sourceNotes)scoreDuration=Math.max(scoreDuration,note.time+note.duration);
  acceptOffset(0);
  chartSelect.value=chart.id;
  $('#title').textContent=chart.title;
  seekInput.value='0';
  pendingSeek=null;
  positionOutput.textContent='0.00';
  clearError();

  video.muted=modeSelect.value==='synth';
  video.src=chart.recording;
  video.load();
  await waitForMetadata(serial);
  updateSeekRange();
}

function validateOffset(raw){
  if(!sourceNotes.length)throw makeError('no_chart','load a chart first');
  if(typeof raw==='string'&&raw.trim()==='')throw makeError('invalid_transposition','transposition must be an integer');
  const value=Number(raw);
  if(!Number.isSafeInteger(value))throw makeError('invalid_transposition','transposition must be an integer');
  if(sourceNotes.some(note=>note.midi+value<0||note.midi+value>127)){
    throw makeError('invalid_transposition','transposition would create an out-of-range MIDI note');
  }
  return Object.is(value,-0)?0:value;
}

function changeTransposition(){
  const attempted=transposeInput.value;
  try{
    const next=validateOffset(attempted);
    acceptOffset(next);
    rejectedOffsetInput=null;
    clearError();
    scheduleSynth().catch(showError);
  }catch(error){
    rejectedOffsetInput=attempted;
    transposeInput.value=String(acceptedOffset);
    showError(error);
  }
}

function seekTo(value){
  if(!Number.isFinite(value)){
    showError(makeError('invalid_seek','seek position must be finite'));
    return;
  }
  const duration=video.duration;
  if(!Number.isFinite(duration)){
    pendingSeek=value;
    return;
  }
  const clamped=Math.max(0,Math.min(duration,value));
  seekInput.value=String(clamped);
  try{video.currentTime=clamped;}catch(error){showError(error);}
}

function handleSeek(){
  const raw=seekInput.value.trim();
  if(raw==='')return;
  seekTo(Number(raw));
}

function download(bytes,type,name){
  const url=URL.createObjectURL(new Blob([bytes],{type}));
  const link=document.createElement('a');
  link.href=url;
  link.download=name;
  link.style.display='none';
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(()=>URL.revokeObjectURL(url),1000);
}

function buildExportMidi(){
  if(!sourceBytes)throw makeError('no_chart','load a chart first');
  let midi;
  try{
    midi=new Midi(sourceBytes.slice().buffer);
  }catch{
    throw makeError('invalid_midi','current MIDI cannot be exported');
  }
  let scoreIndex=0;
  for(const track of midi.tracks){
    for(const note of track.notes){
      const scoreNote=currentScore[scoreIndex++];
      if(!scoreNote||!Number.isInteger(scoreNote.midi)||scoreNote.midi<0||scoreNote.midi>127){
        throw makeError('invalid_transposition','current score contains an out-of-range MIDI note');
      }
      // Only replace the pitch.  The freshly parsed copy retains every
      // original tick, duration, tempo and track event for the export.
      note.midi=scoreNote.midi;
    }
  }
  if(scoreIndex!==currentScore.length)throw makeError('invalid_midi','current MIDI note data changed');
  return midi.toArray();
}

const PDF_STAFF_BOX=Object.freeze({x:35,y:315,width:772,height:185.28});
const PDF_INK=rgb(33/255,60/255,67/255);

function readScoreViewBox(){
  const values=(scoreRoot.getAttribute('viewBox')||'0 0 1000 240').trim().split(/[ ,]+/).map(Number);
  if(values.length===4&&values.every(Number.isFinite)&&values[2]>0&&values[3]>0)return values;
  return [0,0,1000,240];
}

function pdfPoint(x,y,viewBox){
  const [left,top,width,height]=viewBox;
  return {
    x:PDF_STAFF_BOX.x+(x-left)/width*PDF_STAFF_BOX.width,
    y:PDF_STAFF_BOX.y+PDF_STAFF_BOX.height-(y-top)/height*PDF_STAFF_BOX.height
  };
}

function drawPdfStaff(page,font){
  const viewBox=readScoreViewBox();
  const xScale=PDF_STAFF_BOX.width/viewBox[2];
  const yScale=PDF_STAFF_BOX.height/viewBox[3];
  const lineColor=PDF_INK;
  const drawLine=(x1,y1,x2,y2,thickness=0.8)=>{
    page.drawLine({start:pdfPoint(x1,y1,viewBox),end:pdfPoint(x2,y2,viewBox),thickness,color:lineColor});
  };

  for(let line=0;line<5;line++)drawLine(20,90+line*10,980,90+line*10);
  for(const note of currentScore){
    const x=50+(note.time/Math.max(1,scoreDuration))*870;
    const y=staffY(note.midi);
    const label=pitchLabel(note.midi);
    const center=pdfPoint(x,y,viewBox);
    page.drawEllipse({
      x:center.x,y:center.y,
      xScale:7*xScale,yScale:5*yScale,
      color:lineColor
    });
    drawLine(x+6,y,x+6,y-28,1.05);

    if(label.includes('#')){
      const accidental=pdfPoint(x-17,y+5,viewBox);
      page.drawText('#',{x:accidental.x-3,y:accidental.y-3,font,size:Math.max(7,16*Math.min(xScale,yScale)),color:lineColor});
    }
    const labelPoint=pdfPoint(x,190,viewBox);
    const labelSize=Math.max(7,14*Math.min(xScale,yScale));
    page.drawText(label,{x:labelPoint.x-font.widthOfTextAtSize(label,labelSize)/2,y:labelPoint.y,font,size:labelSize,color:lineColor});

    for(let ledger=140;ledger<=y;ledger+=10)drawLine(x-12,ledger,x+12,ledger);
    for(let ledger=80;ledger>=y;ledger-=10)drawLine(x-12,ledger,x+12,ledger);
  }
}

async function exportPdf(){
  if(!sourceBytes)throw makeError('no_chart','load a chart first');
  const documentPdf=await PDFDocument.create();
  const page=documentPdf.addPage([842,595]);
  const font=await documentPdf.embedFont(StandardFonts.Helvetica);
  page.drawText('Independent practice chart',{x:35,y:550,font,size:18});
  page.drawText(`Transposition: ${acceptedOffset>=0?'+':''}${acceptedOffset} semitones`,{x:35,y:530,font,size:11});

  // Draw the same staff primitives as the SVG in PDF coordinates.  This
  // keeps the export sharp at any zoom and avoids changing the accepted score
  // merely to make an image for the file.
  drawPdfStaff(page,font);

  const labels=currentScore.map(note=>pitchLabel(note.midi));
  const labelLines=[];
  let line='Pitch names: ';
  for(const label of labels){
    const candidate=line+(line==='Pitch names: ' ? '' : '  ')+label;
    if(line!=='Pitch names: '&&font.widthOfTextAtSize(candidate,12)>772){
      labelLines.push(line);
      line=`${label}`;
    }else line=candidate;
  }
  if(line)labelLines.push(line);
  let currentPage=page;
  let y=278;
  for(const labelLine of labelLines){
    if(y<35){
      currentPage=documentPdf.addPage([842,595]);
      currentPage.drawText('Pitch names (continued)',{x:35,y:550,font,size:14});
      y=520;
    }
    currentPage.drawText(labelLine,{x:35,y,font,size:12});
    y-=18;
  }
  download(await documentPdf.save(),'application/pdf','chart.pdf');
}

transposeInput.addEventListener('change',()=>{
  // An invalid input is restored to the last accepted value.  Do not let the
  // browser's follow-up change event immediately clear its feedback.
  if(rejectedOffsetInput!==null&&transposeInput.value===String(acceptedOffset))return;
  changeTransposition();
});
// Also accept programmatic/browser input updates.  Empty input is left alone
// until the change event so that a user can replace the value naturally.
transposeInput.addEventListener('input',()=>{
  const raw=transposeInput.value;
  if(raw.trim()===''){rejectedOffsetInput=null;return;}
  rejectedOffsetInput=null;
  changeTransposition();
});
seekInput.addEventListener('change',handleSeek);
seekInput.addEventListener('input',handleSeek);

$('#play').addEventListener('click',()=>{
  video.play().catch(showError);
});
$('#pause').addEventListener('click',()=>video.pause());
modeSelect.addEventListener('change',()=>{
  video.muted=modeSelect.value==='synth';
  stopSynth();
  if(!video.paused&&modeSelect.value==='synth')scheduleSynth().catch(showError);
});
video.addEventListener('play',()=>{
  if(modeSelect.value==='synth')scheduleSynth().catch(showError);
  else stopSynth();
});
video.addEventListener('pause',stopSynth);
video.addEventListener('seeking',stopSynth);
video.addEventListener('seeked',()=>{
  if(!video.paused&&modeSelect.value==='synth')scheduleSynth().catch(showError);
});
video.addEventListener('ended',stopSynth);
video.addEventListener('loadedmetadata',()=>{
  updateSeekRange();
  if(pendingSeek!==null){
    const requested=pendingSeek;
    pendingSeek=null;
    seekTo(requested);
  }
});
video.addEventListener('durationchange',updateSeekRange);
video.addEventListener('error',()=>{
  if(video.src)showError(makeError('recording_unavailable','recording media is unavailable'));
});

$('#midi-export').addEventListener('click',()=>{
  try{download(buildExportMidi(),'audio/midi','chart.mid');}
  catch(error){showError(error);}
});
$('#pdf-export').addEventListener('click',()=>{
  exportPdf().catch(showError);
});

function updateFrame(){
  const position=Number.isFinite(video.currentTime)?video.currentTime:0;
  positionOutput.textContent=position.toFixed(2);
  updateSeekRange();
  for(const group of scoreRoot.querySelectorAll('g[data-note]')){
    const note=currentScore[Number(group.dataset.note)];
    if(!note)continue;
    const active=!video.paused&&position>=note.time&&position<note.time+note.duration;
    const head=group.querySelector('[data-note-head]');
    if(head)head.setAttribute('fill',active?ACTIVE_NOTE_COLOR:DEFAULT_NOTE_COLOR);
    group.classList.toggle('active-note',active);
  }
  requestAnimationFrame(updateFrame);
}
requestAnimationFrame(updateFrame);

async function loadConfiguration(){
  const response=await fetch('config.json');
  if(!response.ok)throw makeError('config_unavailable','chart configuration is unavailable');
  const loaded=await response.json();
  if(!loaded||!Array.isArray(loaded.charts)||!loaded.charts.length)throw makeError('config_unavailable','chart configuration contains no charts');
  config=loaded;
  chartSelect.replaceChildren(...config.charts.map(chart=>{
    const option=document.createElement('option');
    option.value=chart.id;
    option.textContent=chart.title;
    return option;
  }));
  chartSelect.addEventListener('change',()=>loadChart(chartSelect.value).catch(showError));
  return config;
}

// Keep the documented function available to browser callers as well as to the
// normal selector workflow.  The configuration request is deliberately
// asynchronous so loadChart remains a Promise-returning entry point.
window.loadChart=loadChart;
configPromise=loadConfiguration();
configPromise.then(loaded=>loadChart(loaded.charts[0].id)).catch(showError);
