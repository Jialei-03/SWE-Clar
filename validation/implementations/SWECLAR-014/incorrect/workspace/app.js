const DIRECTIONS = new Set(['left', 'right', 'up', 'down']);

function monotonicNow() {
  // performance.now() is monotonic and is the only clock used for elapsed
  // browser time.  The fallback is useful for small non-browser development
  // harnesses and deliberately is not a wall-clock source.
  return typeof performance !== 'undefined' && typeof performance.now === 'function'
    ? performance.now() : 0;
}

function commandId() {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID();
  }
  if (typeof crypto !== 'undefined' && typeof crypto.getRandomValues === 'function') {
    const bytes = new Uint8Array(16);
    crypto.getRandomValues(bytes);
    return Array.from(bytes, byte => byte.toString(16).padStart(2, '0')).join('');
  }
  // This path is only for a very small development harness without Web
  // Crypto.  It still has the protocol's permitted characters and length.
  return `command-${Math.random().toString(36).slice(2)}-${Math.random().toString(36).slice(2)}`.slice(0, 64);
}

export class ArenaClient {
  constructor() {
    this.state = null;
    this.playerId = null;
    this.token = null;
    this.roomId = null;
    this.error = null;
    this.busy = false;

    this.listeners = new Set();
    this.epoch = 0;
    this.lastSeq = 0;
    this.anchorLocal = 0;
    this.anchorServer = 0;
    this.countdownGeneration = null;
    this.remainingCap = 0;

    // A failed command keeps this object so an explicit repeat of the same
    // intent retries the exact original generation/payload/id.
    this.intent = null;
    this.refreshing = null;
    this.needsRefresh = false;
    this.disposed = false;
  }

  emit() {
    for (const listener of [...this.listeners]) {
      try {
        listener();
      } catch (_error) {
        // A view listener must not prevent the controller from notifying the
        // remaining listeners or completing a network operation.
      }
    }
  }

  player() {
    return this.state?.players?.find(player => player.id === this.playerId) || null;
  }

  serverTime() {
    if (!this.state || !Number.isFinite(this.anchorServer)) return 0;
    return this.anchorServer + Math.max(0, monotonicNow() - this.anchorLocal);
  }

  rawRemaining(player, serverTime = this.serverTime()) {
    if (!player || !player.alive || !Number.isFinite(player.protected_until_ms)) return 0;
    return Math.max(0, Math.ceil((player.protected_until_ms - serverTime) / 1000));
  }

  remaining() {
    const player = this.player();
    if (!player || !player.alive) {
      this.remainingCap = 0;
      return 0;
    }

    // This also makes the method safe for ordinary development tests that
    // replace state directly rather than going through acceptState.
    if (this.countdownGeneration !== player.generation) {
      this.countdownGeneration = player.generation;
      this.remainingCap = this.rawRemaining(player);
    }
    const current = this.rawRemaining(player);
    if (!Number.isFinite(this.remainingCap)) this.remainingCap = current;
    this.remainingCap = Math.max(0, Math.min(this.remainingCap, current));
    return this.remainingCap;
  }

  acceptState(state) {
    if (!this.token || !state || !state.room || !Array.isArray(state.players)) return false;
    if (this.roomId !== null && state.room.id !== this.roomId) return false;
    if (!Number.isSafeInteger(state.seq) || state.seq <= this.lastSeq) return false;
    if (!Number.isFinite(state.server_now_ms)) return false;

    const oldPlayer = this.player();
    const oldGeneration = oldPlayer?.generation;
    const incomingPlayer = state.players.find(player => player.id === this.playerId) || null;
    const incomingGeneration = incomingPlayer?.generation;

    // Sequence acceptance, state replacement and the time anchor are one
    // operation.  Older/duplicate responses return before touching any of it.
    this.state = state;
    this.roomId = state.room.id;
    this.lastSeq = state.seq;
    this.anchorLocal = monotonicNow();
    this.anchorServer = state.server_now_ms;
    this.needsRefresh = false;

    if (!incomingPlayer || !incomingPlayer.alive) {
      this.countdownGeneration = incomingGeneration ?? null;
      this.remainingCap = 0;
    } else if (
      oldGeneration === undefined ||
      (Number.isFinite(oldGeneration) && Number.isFinite(incomingGeneration) && incomingGeneration > oldGeneration) ||
      this.countdownGeneration !== incomingGeneration
    ) {
      // A genuinely newer generation starts a new six-second countdown.
      this.countdownGeneration = incomingGeneration;
      this.remainingCap = this.rawRemaining(incomingPlayer, state.server_now_ms);
    } else {
      // Re-anchoring a same-generation response can otherwise make a delayed
      // countdown increase.  Preserve the smallest displayed value.
      this.countdownGeneration = incomingGeneration;
      this.remainingCap = Math.max(
        0,
        Math.min(this.remainingCap, this.rawRemaining(incomingPlayer, state.server_now_ms)),
      );
    }

    this.emit();
    return true;
  }

  async request(path, body, token = this.token) {
    let response;
    try {
      response = await fetch(path, {
        method: body === undefined ? 'GET' : 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? {Authorization: `Bearer ${token}`} : {}),
        },
        ...(body === undefined ? {} : {body: JSON.stringify(body)}),
      });
    } catch (_error) {
      throw new Error('Connection failed. Retry the same action.');
    }

    let data;
    try {
      data = await response.json();
    } catch (_error) {
      const error = new Error('Invalid response from server. Retry the same action.');
      error.status = response.status;
      throw error;
    }
    if (!response.ok) {
      const error = new Error(`Request failed: ${data?.error || response.status}`);
      error.status = response.status;
      error.code = data?.error;
      throw error;
    }
    return data;
  }

  clear() {
    this.epoch += 1;
    this.busy = false;
    this.state = null;
    this.playerId = null;
    this.token = null;
    this.roomId = null;
    this.intent = null;
    this.refreshing = null;
    this.needsRefresh = false;
    this.lastSeq = 0;
    this.anchorLocal = 0;
    this.anchorServer = 0;
    this.countdownGeneration = null;
    this.remainingCap = 0;
  }

  async join(roomId, label) {
    if (this.busy || this.disposed) return false;
    this.clear();
    this.busy = true;
    this.error = null;
    const epoch = this.epoch;
    this.emit();
    try {
      const data = await this.request('/api/join', {room_id: roomId, label}, null);
      if (epoch !== this.epoch || this.disposed) return false;
      this.roomId = data.state?.room?.id ?? roomId;
      this.token = data.token;
      this.playerId = data.player_id;
      if (!this.acceptState(data.state)) {
        throw new Error('Invalid state from server.');
      }
      this.error = null;
      return true;
    } catch (error) {
      if (epoch !== this.epoch || this.disposed) return false;
      this.error = error.message;
      return false;
    } finally {
      if (epoch === this.epoch && !this.disposed) {
        this.busy = false;
        this.emit();
      }
    }
  }

  async refresh(force = false) {
    if (!this.token || this.disposed) return false;
    if (this.refreshing) {
      // A forced refresh is satisfied by the already in-flight authoritative
      // request; starting a second poll would only add a race.
      return await this.refreshing;
    }

    const epoch = this.epoch;
    const token = this.token;
    const pending = (async () => {
      try {
        const data = await this.request('/api/state', undefined, token);
        if (epoch !== this.epoch || this.disposed) return false;
        const accepted = this.acceptState(data.state);
        // If the response is older than a state already accepted, that
        // existing state is authoritative enough to clear the refresh gate.
        if (!accepted) this.needsRefresh = false;
        return true;
      } catch (error) {
        if (epoch !== this.epoch || this.disposed) return false;
        if (error.status === 401) {
          this.clear();
          this.error = error.message;
          this.emit();
          return false;
        }
        this.error = error.message;
        this.emit();
        return false;
      }
    })();
    this.refreshing = pending;
    try {
      return await pending;
    } finally {
      if (this.refreshing === pending) this.refreshing = null;
    }
  }

  async perform(operation, direction) {
    if (this.busy || !this.token || !this.player() || this.disposed) return false;
    if (this.needsRefresh) return false;
    if (operation === 'move' && !DIRECTIONS.has(direction)) return false;

    const sameIntent = this.intent &&
      this.intent.operation === operation &&
      this.intent.direction === direction;
    if (!sameIntent) {
      const player = this.player();
      this.intent = {
        operation,
        direction,
        body: {
          generation: player.generation,
          command_id: commandId(),
          ...(operation === 'move' ? {direction} : {}),
        },
      };
    }

    const intent = this.intent;
    const epoch = this.epoch;
    this.busy = true;
    this.error = null;
    this.emit();
    try {
      const data = await this.request(`/api/${operation}`, intent.body);
      if (epoch !== this.epoch || this.disposed) return false;
      this.acceptState(data.state);
      this.intent = null;
      this.error = null;
      return true;
    } catch (error) {
      if (epoch !== this.epoch || this.disposed) return false;
      if (error.status === 401) {
        this.clear();
        this.error = error.message;
        this.emit();
        return false;
      }
      if (error.status === 409) {
        // A conflict means the locally captured generation/intent is no
        // longer usable.  Refresh before enabling another action.
        this.intent = null;
        this.needsRefresh = true;
        const refreshed = await this.refresh(true);
        if (epoch !== this.epoch || this.disposed) return false;
        if (!refreshed) this.error = 'Could not refresh authoritative state. Retry.';
        else this.error = error.message;
        return false;
      }
      // Network failures and unexpected server failures retain the exact
      // intent.  The next explicit repeat can safely replay its command id.
      this.error = error.message;
      return false;
    } finally {
      if (epoch === this.epoch && !this.disposed) {
        this.busy = false;
        this.emit();
      }
    }
  }

  move(direction) {
    return this.perform('move', direction);
  }

  respawn() {
    return this.perform('respawn');
  }

  async leave() {
    const token = this.token;
    this.clear();
    this.error = null;
    const epoch = this.epoch;
    this.emit();
    if (!token || this.disposed) return true;
    try {
      await this.request('/api/leave', {}, token);
      return true;
    } catch (error) {
      if (epoch !== this.epoch || this.disposed) return false;
      // Room data remains cleared even if the transport failed; the old
      // session is not reused by this controller.
      this.error = error.message;
      this.emit();
      return false;
    }
  }

  dispose() {
    this.disposed = true;
    this.clear();
    this.listeners.clear();
  }
}

export class ArenaView {
  constructor(client, doc) {
    this.client = client;
    this.doc = doc;
    this.disposed = false;
    this.el = id => doc.getElementById(id);
    this.cleanups = [];

    this.listen(this.el('join-form'), 'submit', event => {
      event.preventDefault();
      client.join(this.el('room-select').value, this.el('player-label').value);
    });
    this.listen(this.el('leave'), 'click', () => client.leave());
    this.listen(this.el('respawn'), 'click', () => client.respawn());
    for (const button of doc.querySelectorAll('[data-direction]')) {
      this.listen(button, 'click', () => client.move(button.dataset.direction));
    }
    this.listen(doc, 'keydown', event => {
      const direction = {
        ArrowLeft: 'left', ArrowRight: 'right', ArrowUp: 'up', ArrowDown: 'down',
      }[event.key];
      if (direction && client.token && !['INPUT', 'SELECT', 'TEXTAREA'].includes(event.target.tagName)) {
        event.preventDefault();
        client.move(direction);
      }
    });

    this.update = () => this.renderState();
    client.listeners.add(this.update);

    client.request('/api/rooms', undefined, null).then(data => {
      if (this.disposed) return;
      this.el('room-select').replaceChildren(...data.rooms.map(room => {
        const option = doc.createElement('option');
        option.value = room.id;
        option.textContent = room.label;
        return option;
      }));
    }).catch(error => {
      if (this.disposed) return;
      client.error = error.message;
      client.emit();
    });

    this.poll = setInterval(() => client.refresh(), 150);
    this.frame = () => {
      if (this.disposed) return;
      this.renderFrame();
      this.animation = requestAnimationFrame(this.frame);
    };
    this.renderState();
    this.animation = requestAnimationFrame(this.frame);
  }

  listen(target, name, callback) {
    if (!target) return;
    target.addEventListener(name, callback);
    this.cleanups.push(() => target.removeEventListener(name, callback));
  }

  renderState() {
    const c = this.client;
    const joined = Boolean(c.state);
    const player = c.player();
    this.el('join-form').hidden = joined;
    this.el('game').hidden = !joined;
    this.el('join').disabled = c.busy;
    this.el('leave').disabled = !joined;
    this.el('error').hidden = !c.error;
    this.el('error').textContent = c.error || '';
    this.el('room-title').textContent = c.state?.room?.label || '';

    for (const button of this.doc.querySelectorAll('[data-direction]')) {
      button.disabled = c.busy || !player?.alive;
    }
    this.el('respawn').disabled = c.busy || !player || player.alive;

    this.el('roster').replaceChildren(...(c.state?.players || []).map(p => {
      const row = this.doc.createElement('div');
      row.dataset.playerId = p.id;
      row.textContent = `${p.label}${p.id === c.playerId ? ' (you)' : ''} · Health ${p.hp}/3 · ${p.alive ? 'alive' : 'dead'}`;
      return row;
    }));
    this.renderFrame();
  }

  renderFrame() {
    const c = this.client;
    const seconds = c.state ? c.remaining() : 0;
    const local = c.player();
    this.el('shield-remaining').textContent = String(seconds);
    this.el('shield-indicator').hidden = !(seconds > 0 && local?.alive);

    const canvas = this.el('arena');
    const ctx = canvas.getContext('2d');
    if (!c.state) {
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      return;
    }

    const {room, players} = c.state;
    if (canvas.width !== room.cols * 24) canvas.width = room.cols * 24;
    if (canvas.height !== room.rows * 24) canvas.height = room.rows * 24;
    const cell = 24;
    ctx.fillStyle = '#f8fbfc';
    ctx.fillRect(0, 0, canvas.width, canvas.height);

    ctx.strokeStyle = '#d5e1e6';
    ctx.lineWidth = 1;
    for (let x = 0; x <= room.cols; x += 1) {
      ctx.beginPath(); ctx.moveTo(x * cell + 0.5, 0); ctx.lineTo(x * cell + 0.5, canvas.height); ctx.stroke();
    }
    for (let y = 0; y <= room.rows; y += 1) {
      ctx.beginPath(); ctx.moveTo(0, y * cell + 0.5); ctx.lineTo(canvas.width, y * cell + 0.5); ctx.stroke();
    }

    ctx.fillStyle = '#536a76';
    for (const [x, y] of room.walls) {
      ctx.fillRect(x * cell + 1, y * cell + 1, cell - 2, cell - 2);
    }

    for (const p of players) {
      if (!p.alive) continue;
      const x = (p.x + 0.5) * cell;
      const y = (p.y + 0.5) * cell;
      const protectedNow = p.id === c.playerId
        ? seconds > 0
        : c.serverTime() < p.protected_until_ms;

      if (protectedNow) {
        ctx.strokeStyle = '#0b8f78';
        ctx.lineWidth = 3;
        ctx.beginPath(); ctx.arc(x, y, 10, 0, Math.PI * 2); ctx.stroke();
      }

      ctx.fillStyle = p.id === c.playerId ? '#175b94' : '#bb6325';
      ctx.beginPath(); ctx.arc(x, y, 7, 0, Math.PI * 2); ctx.fill();
      if (p.id === c.playerId) {
        ctx.strokeStyle = '#102e48';
        ctx.lineWidth = 2;
        ctx.strokeRect(x - 9, y - 9, 18, 18);
        ctx.fillStyle = '#ffffff';
        ctx.fillRect(x - 2, y - 2, 4, 4);
      }
    }
  }

  dispose() {
    this.disposed = true;
    clearInterval(this.poll);
    cancelAnimationFrame(this.animation);
    this.client.listeners.delete(this.update);
    for (const cleanup of this.cleanups) cleanup();
  }
}

if (typeof document !== 'undefined' && document.getElementById('join-form')) {
  const client = new ArenaClient();
  const view = new ArenaView(client, document);
  window.addEventListener('pagehide', () => {
    view.dispose();
    client.dispose();
  });
}
