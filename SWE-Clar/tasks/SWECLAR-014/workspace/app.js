export class ArenaClient {
  constructor() {
    this.state = null; this.playerId = null; this.token = null; this.roomId = null;
    this.error = null; this.busy = false; this.epoch = 0; this.listeners = new Set();
    this.anchor = 0; this.anchorTime = 0; this.lastRemaining = Infinity; this.localUntil = 0;
    this.intent = null; this.refreshing = null;
  }
  emit() { for (const listener of this.listeners) listener(); }
  player() { return this.state?.players.find(p => p.id === this.playerId); }
  serverTime() { return this.anchorTime + Math.max(0, performance.now() - this.anchor); }
  remaining() { return 0; } // Visible protection timing is unfinished.
  acceptState(state) {
    if (!this.token || state.room.id !== this.roomId) return false;
    this.state = state; this.anchor = performance.now(); this.anchorTime = state.server_now_ms;
    this.emit(); return true;
  }
  async request(path, body, token = this.token) {
    let response;
    try {
      response = await fetch(path, {method: body === undefined ? 'GET' : 'POST',
        headers: {'Content-Type': 'application/json', ...(token ? {Authorization: `Bearer ${token}`} : {})},
        ...(body === undefined ? {} : {body: JSON.stringify(body)})});
    } catch { throw new Error('Connection failed. Retry the same action.'); }
    const data = await response.json();
    if (!response.ok) {
      const error = new Error(`Request failed: ${data.error}`); error.status = response.status; throw error;
    }
    return data;
  }
  clear() {
    this.epoch++; this.busy = false; this.state = null; this.playerId = null; this.token = null; this.roomId = null;
    this.intent = null; this.lastRemaining = Infinity; this.localUntil = 0; this.anchor = this.anchorTime = 0;
  }
  async join(roomId, label) {
    if (this.busy) return;
    this.clear(); this.busy = true; this.error = null; const epoch = this.epoch; this.emit();
    try {
      const data = await this.request('/api/join', {room_id: roomId, label}, null);
      if (epoch !== this.epoch) return;
      this.roomId = roomId; this.token = data.token; this.playerId = data.player_id;
      this.acceptState(data.state);
    } catch (error) { if (epoch === this.epoch) this.error = error.message; }
    finally { if (epoch === this.epoch) { this.busy = false; this.emit(); } }
  }
  async refresh(force = false) {
    if (this.refreshing) { await this.refreshing; if (!force) return; }
    if (!this.token) return;
    const epoch = this.epoch, token = this.token;
    const pending = (async () => {
      try {
        const data = await this.request('/api/state', undefined, token);
        if (epoch === this.epoch) this.acceptState(data.state);
      } catch (error) {
        if (epoch !== this.epoch) return;
        if (error.status === 401) this.clear();
        this.error = error.message; this.emit();
      }
    })();
    this.refreshing = pending;
    try { await pending; } finally { if (this.refreshing === pending) this.refreshing = null; }
  }
  async perform(operation, direction) {
    if (this.busy || !this.token || !this.player()) return;
    if (operation) { // Retry-intent reconciliation is unfinished.
      this.intent = {operation, direction, body: {generation: this.player().generation,
        command_id: crypto.randomUUID(), ...(operation === 'move' ? {direction} : {})}};
    }
    const intent = this.intent, epoch = this.epoch;
    this.busy = true; this.error = null; this.emit();
    try {
      const data = await this.request(`/api/${operation}`, intent.body);
      if (epoch !== this.epoch) return;
      this.acceptState(data.state); this.intent = null;
    } catch (error) {
      if (epoch !== this.epoch) return;
      this.error = error.message;
      if (error.status === 401) this.clear();
      if (error.status === 409) { await this.refresh(true); this.intent = null; }
    } finally { if (epoch === this.epoch) { this.busy = false; this.emit(); } }
  }
  move(direction) { return this.perform('move', direction); }
  respawn() { return this.perform('respawn'); }
  async leave() {
    const token = this.token;
    this.clear(); this.busy = false; this.error = null; const epoch = this.epoch; this.emit();
    if (token) { try { await this.request('/api/leave', {}, token); } catch (error) { if (epoch === this.epoch) { this.error = error.message; this.emit(); } } }
  }
  dispose() { this.clear(); this.listeners.clear(); }
}

export class ArenaView {
  constructor(client, doc) {
    this.client = client; this.doc = doc; this.disposed = false;
    this.el = id => doc.getElementById(id); this.cleanups = [];
    this.listen(this.el('join-form'), 'submit', event => {
      event.preventDefault(); client.join(this.el('room-select').value, this.el('player-label').value);
    });
    this.listen(this.el('leave'), 'click', () => client.leave());
    this.listen(this.el('respawn'), 'click', () => client.respawn());
    for (const button of doc.querySelectorAll('[data-direction]')) this.listen(button, 'click', () => client.move(button.dataset.direction));
    this.listen(doc, 'keydown', event => {
      const direction = {ArrowLeft: 'left', ArrowRight: 'right', ArrowUp: 'up', ArrowDown: 'down'}[event.key];
      if (direction && client.token && !['INPUT', 'SELECT', 'TEXTAREA'].includes(event.target.tagName)) {
        event.preventDefault(); client.move(direction);
      }
    });
    this.update = () => this.renderState(); client.listeners.add(this.update);
    client.request('/api/rooms', undefined, null).then(data => {
      if (this.disposed) return;
      this.el('room-select').replaceChildren(...data.rooms.map(room => {
        const option = doc.createElement('option'); option.value = room.id; option.textContent = room.label; return option;
      }));
    }).catch(error => { client.error = error.message; client.emit(); });
    this.poll = setInterval(() => client.refresh(), 150);
    this.frame = () => {
      if (this.disposed) return;
      this.renderFrame(); this.animation = requestAnimationFrame(this.frame);
    };
    this.renderState(); this.animation = requestAnimationFrame(this.frame);
  }
  listen(target, name, callback) {
    target.addEventListener(name, callback); this.cleanups.push(() => target.removeEventListener(name, callback));
  }
  renderState() {
    const c = this.client, joined = Boolean(c.state), player = c.player();
    this.el('join-form').hidden = joined; this.el('game').hidden = !joined;
    this.el('join').disabled = c.busy;
    this.el('error').hidden = !c.error; this.el('error').textContent = c.error || '';
    this.el('room-title').textContent = c.state?.room.label || '';
    for (const button of this.doc.querySelectorAll('[data-direction]')) button.disabled = c.busy || !player?.alive;
    this.el('respawn').disabled = c.busy || !player || (player.alive && c.intent?.operation !== 'respawn');
    this.el('roster').replaceChildren(...(c.state?.players || []).map(p => {
      const row = this.doc.createElement('div'); row.dataset.playerId = p.id;
      row.textContent = `${p.label}${p.id === c.playerId ? ' (you)' : ''} · Health ${p.hp}/3 · ${p.alive ? 'alive' : 'dead'}`;
      return row;
    }));
    this.renderFrame();
  }
  renderFrame() {
    const c = this.client, seconds = c.state ? c.remaining() : 0;
    this.el('shield-remaining').textContent = String(seconds);
    this.el('shield-indicator').hidden = seconds <= 0;
    const canvas = this.el('arena'), ctx = canvas.getContext('2d');
    if (!c.state) { ctx.clearRect(0, 0, canvas.width, canvas.height); return; }
    const {room, players} = c.state;
    if (canvas.width !== room.cols * 24) canvas.width = room.cols * 24;
    if (canvas.height !== room.rows * 24) canvas.height = room.rows * 24;
    ctx.fillStyle = '#f8fbfc'; ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.strokeStyle = '#dce5e9'; ctx.lineWidth = 1;
    for (let x = 0; x <= room.cols; x++) { ctx.beginPath(); ctx.moveTo(x * 24, 0); ctx.lineTo(x * 24, canvas.height); ctx.stroke(); }
    for (let y = 0; y <= room.rows; y++) { ctx.beginPath(); ctx.moveTo(0, y * 24); ctx.lineTo(canvas.width, y * 24); ctx.stroke(); }
    ctx.fillStyle = '#526671'; for (const [x, y] of room.walls) ctx.fillRect(x * 24 + 1, y * 24 + 1, 22, 22);
    for (const p of players) {
      if (!p.alive) continue;
      const x = (p.x + .5) * 24, y = (p.y + .5) * 24;
      const protectedNow = p.id === c.playerId ? seconds > 0 : c.serverTime() < p.protected_until_ms;
      if (protectedNow) { ctx.strokeStyle = '#188f76'; ctx.lineWidth = 2; ctx.beginPath(); ctx.arc(x, y, 10, 0, Math.PI * 2); ctx.stroke(); }
      ctx.fillStyle = p.id === c.playerId ? '#175b94' : '#bb6325';
      ctx.beginPath(); ctx.arc(x, y, 6, 0, Math.PI * 2); ctx.fill();
      if (p.id === c.playerId) { ctx.fillStyle = 'white'; ctx.fillRect(x - 2, y - 2, 4, 4); }
    }
  }
  dispose() {
    this.disposed = true; clearInterval(this.poll); cancelAnimationFrame(this.animation);
    this.client.listeners.delete(this.update); for (const cleanup of this.cleanups) cleanup();
  }
}

if (typeof document !== 'undefined' && document.getElementById('join-form')) {
  const client = new ArenaClient(); const view = new ArenaView(client, document);
  window.addEventListener('pagehide', () => { view.dispose(); client.dispose(); });
}
