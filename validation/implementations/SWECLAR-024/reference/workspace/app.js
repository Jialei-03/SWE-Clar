const q = selector => document.querySelector(selector);
let generation = 0;

async function json(url) {
  const response = await fetch(url, { credentials: 'same-origin' });
  if (!response.ok) throw Error('Unable to load videos.');
  return response.json();
}

async function load() {
  const mark = ++generation;
  const rows = await json('/archives?q=' + encodeURIComponent(q('#query').value));
  if (mark !== generation) return;
  const list = q('#archives');
  list.replaceChildren();
  for (const row of rows) {
    const button = document.createElement('button');
    button.className = 'archive';
    button.dataset.event = row.event_id;
    button.textContent = row.title;
    button.onclick = () => {
      const player = q('#player');
      q('#now-playing').textContent = row.title;
      // The view request is tied to the browser's real playback event.  No
      // viewer/session identity is accepted from page data or the caller.
      player.onplaying = () => {
        fetch('/view', {
          method: 'POST',
          credentials: 'same-origin',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ event_id: row.event_id })
        }).catch(() => {});
      };
      player.src = row.media_url;
      player.hidden = false;
      const play = player.play();
      if (play && play.catch) play.catch(() => {});
    };
    list.append(button);
  }
}

q('#search').onsubmit = event => {
  event.preventDefault();
  load().catch(error => { q('#status').textContent = error.message; });
};

json('/calendar').then(rows => {
  for (const row of rows) {
    const li = document.createElement('li');
    li.textContent = row.title + ' · ' + new Date(row.start).toLocaleString();
    q('#events').append(li);
  }
}).catch(error => { q('#status').textContent = error.message; });

load().catch(error => { q('#status').textContent = error.message; });
