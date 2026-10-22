const audio = document.querySelector('#audio');
const selectedLabel = document.querySelector('#selected');
const errorLabel = document.querySelector('#error');
const remainingLabel = document.querySelector('#remaining');

const pages = ['schedule', 'recent'];
const pageRequests = {schedule: 0, recent: 0};
const playback = {
  selected: null,
  generation: 0,
  cancelReadyWait: null,
  expectedLivePlay: null,
};
const sleepTimer = {deadline: null};

function isCurrent(generation) {
  return generation === playback.generation;
}

function startPlaybackOperation() {
  // Invalidating the previous operation prevents a slow metadata or live
  // request from starting a source which the user has already replaced.
  playback.generation += 1;
  const cancel = playback.cancelReadyWait;
  playback.cancelReadyWait = null;
  playback.expectedLivePlay = null;
  if (cancel) cancel();
  return playback.generation;
}

function isLiveProgramme(programme) {
  return !!programme && (
    programme.live === true ||
    programme.live === 'true' ||
    programme.live === 1
  );
}

function idFor(programme) {
  return programme == null ? '' : String(programme.id);
}

function audioIsAdvancing() {
  return audio.paused === false && audio.ended !== true;
}

function audioHasSelectionPlaying() {
  return playback.selected !== null && audioIsAdvancing();
}

function renderSelection() {
  const programme = playback.selected;
  selectedLabel.textContent = programme ? String(programme.title ?? '') : 'No selection';

  const selectedId = idFor(programme);
  const playing = audioHasSelectionPlaying();
  document.querySelectorAll('[data-id]').forEach(button => {
    button.classList.toggle(
      'playing',
      playing && button.dataset.id === selectedId,
    );
  });
}

function currentMediaSession() {
  if (typeof navigator === 'undefined' || !navigator.mediaSession) return null;
  return navigator.mediaSession;
}

function publishMetadata() {
  const session = currentMediaSession();
  if (!session) return;

  try {
    // Clear first so a browser cannot retain artist/album fields from an old
    // selection if its MediaMetadata implementation is incomplete.
    session.metadata = null;
    if (playback.selected && typeof window.MediaMetadata === 'function') {
      const programme = playback.selected;
      session.metadata = new window.MediaMetadata({
        title: String(programme.title ?? ''),
        artist: String(programme.artist ?? ''),
        album: String(programme.album ?? ''),
      });
    }
  } catch (error) {
    // Media Session is optional and some browsers expose only part of it.
  }

  try {
    session.playbackState = audioIsAdvancing() ? 'playing' : 'paused';
  } catch (error) {
    // playbackState can be read-only in older or simulated browsers.
  }
}

function syncPlaybackUi() {
  renderSelection();
  publishMetadata();
}

function showError(error) {
  if (!errorLabel) return;
  errorLabel.textContent = error && error.message ? error.message : String(error);
}

async function fetchJson(url) {
  const response = await fetch(url);
  if (response && response.ok === false) {
    throw new Error(`Request failed: ${response.status}`);
  }
  return response.json();
}

function waitForAudioMetadata(generation) {
  if (!isCurrent(generation)) return Promise.resolve(false);
  if (audio.readyState >= 1) return Promise.resolve(true);

  return new Promise((resolve, reject) => {
    let settled = false;

    const finish = (success, error) => {
      if (settled) return;
      settled = true;
      audio.removeEventListener('loadedmetadata', onMetadata);
      audio.removeEventListener('error', onError);
      if (playback.cancelReadyWait === cancel) playback.cancelReadyWait = null;
      if (error) reject(error);
      else resolve(success);
    };
    const onMetadata = () => finish(true);
    const onError = () => finish(false, new Error('Cannot load audio'));
    const cancel = () => finish(false);

    playback.cancelReadyWait = cancel;
    audio.addEventListener('loadedmetadata', onMetadata);
    audio.addEventListener('error', onError);

    // Loading a cached URL may synchronously make metadata available.
    if (audio.readyState >= 1) finish(true);
  });
}

async function liveOffset() {
  const data = await fetchJson('/api/live');
  const offset = Number(data && data.offset);
  if (!Number.isFinite(offset) || offset < 0) {
    throw new Error('Invalid live programme offset');
  }
  return offset;
}

async function seekToLivePosition(generation) {
  const offset = await liveOffset();
  if (!isCurrent(generation)) return false;
  audio.currentTime = offset;
  return true;
}

async function startAudio(programme, generation) {
  if (!isCurrent(generation)) return false;

  // The native play event is also handled below. This marker distinguishes
  // that event from a play initiated by the element's own controls.
  playback.expectedLivePlay = isLiveProgramme(programme) ? generation : null;
  try {
    await audio.play();
  } catch (error) {
    if (playback.expectedLivePlay === generation) playback.expectedLivePlay = null;
    if (isCurrent(generation)) throw error;
    return false;
  }

  if (!isCurrent(generation)) return false;
  syncPlaybackUi();
  return true;
}

async function play(programme) {
  const generation = startPlaybackOperation();

  try {
    // Stop the old source before assigning the new one. The selected record is
    // independent from the paused state, so pause keeps the selection visible.
    audio.pause();
    playback.selected = programme;
    syncPlaybackUi();

    audio.src = programme.url;
    audio.load();
    if (!await waitForAudioMetadata(generation) || !isCurrent(generation)) return;

    if (isLiveProgramme(programme)) {
      if (!await seekToLivePosition(generation)) return;
    } else {
      if (!isCurrent(generation)) return;
      // Explicitly reset reused recent URLs as well as newly loaded sources.
      audio.currentTime = 0;
    }

    await startAudio(programme, generation);
  } catch (error) {
    if (isCurrent(generation)) throw error;
  }
}

async function resume() {
  const programme = playback.selected;
  if (!programme) return;
  const generation = startPlaybackOperation();

  try {
    if (audio.readyState < 1) {
      audio.load();
      if (!await waitForAudioMetadata(generation) || !isCurrent(generation)) return;
    }

    if (isLiveProgramme(programme)) {
      if (!await seekToLivePosition(generation)) return;
    }

    await startAudio(programme, generation);
  } catch (error) {
    if (isCurrent(generation)) throw error;
  }
}

function pause() {
  startPlaybackOperation();
  audio.pause();
  syncPlaybackUi();
}

async function alignNativeLivePlay() {
  const programme = playback.selected;
  if (!programme || !isLiveProgramme(programme) || !audioIsAdvancing()) return;

  const generation = startPlaybackOperation();
  try {
    const offset = await liveOffset();
    if (!isCurrent(generation) || playback.selected !== programme || !audioIsAdvancing()) return;
    audio.currentTime = offset;
    syncPlaybackUi();
  } catch (error) {
    if (isCurrent(generation)) showError(error);
  }
}

function handleAudioPlay() {
  const initiatedByApp = playback.expectedLivePlay !== null;
  playback.expectedLivePlay = null;
  syncPlaybackUi();

  // Clicking the element's native play control bypasses #resume, so a live
  // selection needs the same current-position lookup on that path.
  if (!initiatedByApp) void alignNativeLivePlay();
}

function handleAudioPause() {
  playback.expectedLivePlay = null;
  syncPlaybackUi();
}

audio.addEventListener('play', handleAudioPlay);
audio.addEventListener('playing', syncPlaybackUi);
audio.addEventListener('pause', handleAudioPause);
audio.addEventListener('ended', syncPlaybackUi);

document.querySelector('#pause').addEventListener('click', pause);
document.querySelector('#resume').addEventListener('click', () => {
  resume().catch(showError);
});

function renderPage(page, rows) {
  const fragment = document.createDocumentFragment();
  rows.forEach(row => {
    const button = document.createElement('button');
    button.type = 'button';
    button.dataset.id = idFor(row);
    button.textContent = String(row.title ?? '');
    button.addEventListener('click', () => play(row).catch(showError));
    fragment.append(button);
  });
  document.querySelector(`#${page}`).replaceChildren(fragment);
  renderSelection();
}

async function refresh(page) {
  const request = ++pageRequests[page];
  const rows = await fetchJson(`/api/${page}`);
  if (request !== pageRequests[page]) return;
  if (!Array.isArray(rows)) throw new Error(`Invalid ${page} response`);
  renderPage(page, rows);
}

for (const page of pages) {
  document.querySelector(`#refresh-${page}`).addEventListener('click', () => {
    refresh(page).catch(showError);
  });
}

function showRemaining() {
  if (sleepTimer.deadline === null) {
    remainingLabel.textContent = '';
    return;
  }
  const milliseconds = Math.max(0, sleepTimer.deadline - performance.now());
  remainingLabel.textContent = (milliseconds / 1000).toFixed(1);
}

function setSleepTimer() {
  const seconds = Number(document.querySelector('#seconds').value);
  if (Number.isFinite(seconds) && seconds > 0) {
    sleepTimer.deadline = performance.now() + seconds * 1000;
  }
  showRemaining();
}

function cancelSleepTimer() {
  sleepTimer.deadline = null;
  showRemaining();
}

document.querySelector('#set-timer').addEventListener('click', setSleepTimer);
document.querySelector('#cancel-timer').addEventListener('click', cancelSleepTimer);
document.querySelector('#show-timer').addEventListener('click', showRemaining);

setInterval(() => {
  if (sleepTimer.deadline !== null && performance.now() >= sleepTimer.deadline) {
    sleepTimer.deadline = null;
    pause();
  }
  showRemaining();
}, 50);

function installMediaSessionActions() {
  const session = currentMediaSession();
  if (!session || typeof session.setActionHandler !== 'function') return;

  try {
    session.setActionHandler('play', () => resume().catch(showError));
  } catch (error) {
    // Action handlers are optional across browser versions.
  }
  try {
    session.setActionHandler('pause', pause);
  } catch (error) {
    // Action handlers are optional across browser versions.
  }
}

installMediaSessionActions();
syncPlaybackUi();
Promise.all(pages.map(refresh)).catch(showError);
