let state = null;
let generation = 0;
let busy = false;
let controlTail = Promise.resolve();

const canvas = document.querySelector('#video');
const context = canvas.getContext('2d');
const status = document.querySelector('#status');
const deviceSelect = document.querySelector('#device');

async function request(path, body) {
  const options = {cache: 'no-store'};
  if (body !== undefined) {
    options.method = 'POST';
    options.headers = {'Content-Type': 'application/json'};
    options.body = JSON.stringify(body);
  }
  const response = await fetch(path, options);
  let result = null;
  try {
    result = await response.json();
  } catch (_) {
    result = {error: 'invalid_response'};
  }
  if (!response.ok) throw new Error(result && result.error ? result.error : 'request_failed');
  return result;
}

function showError(error) {
  status.textContent = error && error.message ? error.message : String(error);
}

function render() {
  deviceSelect.replaceChildren();
  for (const source of state.devices) {
    const option = document.createElement('option');
    option.value = source.id;
    option.textContent = source.name;
    deviceSelect.append(option);
  }
  deviceSelect.value = state.selected || '';
  document.querySelector('#resolution').value = state.resolution;
  document.querySelector('#display-input').value = state.display_input;
  document.body.classList.toggle('kiosk', state.kiosk);
  generation += 1;
}

function clearVideo(error) {
  // clearRect removes every old pixel without changing the intrinsic geometry
  // that describes the last requested output size.
  context.clearRect(0, 0, canvas.width, canvas.height);
  canvas.dataset.state = 'error';
  delete canvas.dataset.sequence;
  delete canvas.dataset.input;
  showError(error);
}

function displayName() {
  if (state.display_input === 'auxiliary') return 'auxiliary';
  const source = state.devices.find(item => item.id === state.selected);
  return source ? source.name : 'preview';
}

function control(event) {
  const operation = controlTail.then(async () => {
    state = await request('/api/control', event);
    render();
    return state;
  });
  // A rejected operation must not prevent a later input from being handled.
  controlTail = operation.catch(() => undefined);
  return operation;
}

function scan() {
  const operation = controlTail.then(async () => {
    state = await request('/api/scan', {});
    render();
    return state;
  });
  controlTail = operation.catch(() => undefined);
  return operation;
}

async function frame() {
  if (busy || !state) return;
  busy = true;
  const started = generation;
  try {
    const response = await fetch('/api/frame', {cache: 'no-store'});
    if (!response.ok) {
      let result = null;
      try {
        result = await response.json();
      } catch (_) {
        result = null;
      }
      throw new Error(result && result.error ? result.error : 'frame_failed');
    }
    const bitmap = await createImageBitmap(await response.blob());
    try {
      // A control or scan that completed while this frame was in flight made
      // its pixels stale.  The next polling turn captures the new input.
      if (started !== generation) return;
      canvas.width = bitmap.width;
      canvas.height = bitmap.height;
      context.drawImage(bitmap, 0, 0);
      const input = response.headers.get('X-Display-Input') || state.display_input;
      canvas.dataset.sequence = response.headers.get('X-Frame-Sequence') || '';
      canvas.dataset.input = input;
      canvas.dataset.state = 'playing';
      status.textContent = `${input} · ${input === 'preview' ? displayName() : 'auxiliary'} · ${bitmap.width} × ${bitmap.height} · zoom ${state.zoom}`;
    } finally {
      bitmap.close();
    }
  } catch (error) {
    // Even if a control completed while this request was in flight, these
    // pixels are no longer a trustworthy live result.  Never leave them on
    // screen as if they were current video.
    clearVideo(error);
  } finally {
    busy = false;
  }
}

document.querySelector('#scan').onclick = () => scan().catch(showError);

deviceSelect.onchange = event =>
  control({type: 'device', id: event.target.value})
    .catch(error => {
      render();
      showError(error);
    });

document.querySelector('#resolution').onchange = event =>
  control({type: 'resolution', value: event.target.value})
    .catch(error => {
      render();
      showError(error);
    });

document.querySelector('#display-input').onchange = event =>
  control({type: 'display', value: event.target.value})
    .catch(error => {
      render();
      showError(error);
    });

window.addEventListener('keydown', event => {
  if (['Enter', 'Escape', 'Equal', 'Minus'].includes(event.code)) {
    event.preventDefault();
    control({type: 'key', key: event.code}).catch(showError);
  }
});

window.addEventListener('controller-input', event => {
  const button = event.detail && event.detail.button;
  control({type: 'controller', button}).catch(showError);
});

for (const button of document.querySelectorAll('[data-button]')) {
  button.onclick = () => window.dispatchEvent(new CustomEvent('controller-input', {
    detail: {button: Number(button.dataset.button)}
  }));
}

state = await request('/api/state');
render();
await frame();
setInterval(frame, 150);
