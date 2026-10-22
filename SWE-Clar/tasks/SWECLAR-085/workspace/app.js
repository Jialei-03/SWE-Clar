const audio = document.querySelector('#audio');
let selected = null;
let deadline = null;
let requestVersion = 0;
function renderSelection() {
  document.querySelector('#selected').textContent = selected ? selected.title : 'No selection';
  document.querySelectorAll('[data-id]').forEach(button => {
    button.classList.toggle('playing', !!selected && button.dataset.id === selected.id);
  });
}
function publishMetadata() {
  if (!selected || !('mediaSession' in navigator)) return;
  navigator.mediaSession.metadata = new MediaMetadata({title:selected.title, artist:selected.artist});
  navigator.mediaSession.playbackState = audio.paused ? 'paused' : 'playing';
}
async function play(item) {
  const version = ++requestVersion;
  audio.pause();
  selected = item;
  audio.src = item.url;
  await new Promise((resolve,reject) => {
    audio.onloadedmetadata = resolve;
    audio.onerror = () => reject(new Error('Cannot load audio'));
    audio.load();
  });
  if (version !== requestVersion) return;
  if (item.live) {
    const data = await fetch('/api/live').then(response => response.json());
    audio.currentTime = data.offset;
  }
  await audio.play();
  renderSelection();
  publishMetadata();
}
function pause() { audio.pause(); renderSelection(); publishMetadata(); }
async function resume() {
  if (!selected) return;
  if (selected.live) audio.currentTime = (await fetch('/api/live').then(r=>r.json())).offset;
  await audio.play(); renderSelection(); publishMetadata();
}
async function refresh(page) {
  const rows = await fetch('/api/'+page).then(response=>response.json());
  const target = document.querySelector('#'+page);
  target.replaceChildren();
  rows.forEach(row => {
    const button = document.createElement('button');
    button.dataset.id = row.id; button.textContent = row.title;
    button.onclick = () => play(row).catch(showError);
    target.append(button);
  });
  renderSelection();
}
function showError(error) { document.querySelector('#error').textContent=error.message; }
function showRemaining() {
  document.querySelector('#remaining').textContent = deadline === null ? '' : Math.max(0,(deadline-performance.now())/1000).toFixed(1);
}
document.querySelector('#pause').onclick = pause;
document.querySelector('#resume').onclick = () => resume().catch(showError);
for (const page of ['schedule','recent']) document.querySelector('#refresh-'+page).onclick = () => refresh(page).catch(showError);
document.querySelector('#set-timer').onclick = () => {
  const seconds = Number(document.querySelector('#seconds').value);
  if (Number.isFinite(seconds) && seconds > 0) deadline = performance.now()+seconds*1000;
  showRemaining();
};
document.querySelector('#cancel-timer').onclick = () => { deadline=null; showRemaining(); };
document.querySelector('#show-timer').onclick = showRemaining;
setInterval(() => { if(deadline!==null && performance.now()>=deadline){deadline=null;pause();} showRemaining(); },50);
audio.addEventListener('play',()=>{renderSelection();publishMetadata();});
audio.addEventListener('pause',()=>{renderSelection();publishMetadata();});
Promise.all(['schedule','recent'].map(refresh)).catch(showError);
