class WebPlayer {
  constructor() {
    this.audio = new Audio();
    this.audio.dataset.player = 'practice';
    this.audio.preload = 'auto';
    this.audio.hidden = true;
    document.body.append(this.audio);
    this.url = null;
    this.controller = null;
    this.generation = 0;
    this.loaded = false;
  }

  revokeUrl() {
    if (this.url) URL.revokeObjectURL(this.url);
    this.url = null;
  }

  unload() {
    this.audio.pause();
    this.audio.removeAttribute('src');
    // load() synchronously detaches the old media resource in browsers and
    // prevents it from continuing to advance while a new request is pending.
    this.audio.load();
    this.audio.currentTime = 0;
    this.loaded = false;
    this.revokeUrl();
  }

  invalidate() {
    this.generation += 1;
    if (this.controller) {
      this.controller.abort();
      this.controller = null;
    }
    return this.generation;
  }

  async play(track, base, token) {
    // Invalidate and unload before starting the network request.  Thus a new
    // click wins immediately, rather than only after its fetch completes.
    const request = this.invalidate();
    this.unload();
    const controller = new AbortController();
    this.controller = controller;

    let response;
    try {
      response = await fetch(`${base}/audio/${encodeURIComponent(track.id)}`, {
        headers: { Authorization: `Bearer ${token}` },
        signal: controller.signal,
      });
    } catch (error) {
      if (request !== this.generation) return;
      throw Error(error && error.name === 'AbortError' ? 'audio_unavailable' : 'audio_unavailable');
    }
    if (request !== this.generation) {
      // Consume/cancel stale bodies without touching the current element.
      try {
        await response.body?.cancel();
      } catch (_error) {
        // The request is stale; its cleanup must never reach the current UI.
      }
      return;
    }
    if (!response.ok) throw Error('audio_unavailable');

    let blob;
    try {
      blob = await response.blob();
    } catch (_error) {
      if (request !== this.generation) return;
      throw Error('audio_unavailable');
    }
    if (request !== this.generation) return;

    this.controller = null;
    this.url = URL.createObjectURL(blob);
    this.audio.src = this.url;
    this.audio.currentTime = 0;
    this.loaded = true;
    try {
      await this.audio.play();
    } catch (error) {
      if (request !== this.generation) return;
      throw Error('audio_playback_failed');
    }
    // A pause/new-track/logout can occur while play() is awaiting.  Those
    // operations already own the element, so do not resurrect this request.
  }

  pause() {
    this.invalidate();
    this.audio.pause();
  }

  async resume() {
    if (!this.loaded || !this.audio.src) return;
    try {
      await this.audio.play();
    } catch (_error) {
      throw Error('audio_playback_failed');
    }
  }

  async clear() {
    this.invalidate();
    this.unload();
  }

  async snapshot() {
    const position = Number.isFinite(this.audio.currentTime) ? this.audio.currentTime : 0;
    return {
      position,
      isPlaying: !this.audio.paused && !this.audio.ended,
    };
  }
}

export const player = new WebPlayer();
