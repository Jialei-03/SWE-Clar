export class WorkspaceClient extends EventTarget {
  constructor() {
    super();
    this.token = null;
    this.workspace = null;
    this.conversation = null;
    this.ranking = null;
    this.error = '';
    this.selectedId = null;
    this.epoch = 0;
    this.pending = null;
    // A workflow intent survives a failed/lost response so a later identical
    // call can safely replay the same server request.
    this.intent = null;
    this.refreshSerial = 0;
  }

  changed() { this.dispatchEvent(new Event('change')); }

  scope() { return { epoch: this.epoch, selectedId: this.selectedId }; }

  current(scope) {
    return scope.epoch === this.epoch && scope.selectedId === this.selectedId;
  }

  clear() {
    this.epoch++;
    this.refreshSerial++;
    this.token = null;
    this.workspace = this.conversation = this.ranking = null;
    this.selectedId = null;
    this.pending = this.intent = null;
    this.error = '';
    this.changed();
  }

  async request(path, method = 'GET', body = undefined, token = this.token, image = false) {
    const headers = {};
    if (token) headers.Authorization = `Bearer ${token}`;
    if (body !== undefined) headers['Content-Type'] = 'application/json';
    const response = await fetch(path, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    if (!response.ok) {
      let message = `Request failed (${response.status})`;
      try { message = (await response.json()).error || message; } catch (_) {}
      if (response.status === 401 && token && token === this.token) this.clear();
      const error = new Error(message);
      error.status = response.status;
      throw error;
    }
    return image ? response.blob() : response.json();
  }

  async login(username, password) {
    // A new login is a new UI security scope.  It never inherits data from a
    // previous account or from a browser storage cache.
    this.clear();
    const epoch = this.epoch;
    try {
      const result = await this.request('/api/login', 'POST', { username, password }, null);
      if (epoch !== this.epoch) return;
      this.token = result.token;
      await this.refresh();
    } catch (error) {
      if (epoch === this.epoch) {
        this.error = error.message;
        this.changed();
      }
    }
  }

  async logout() {
    const token = this.token;
    this.clear();
    if (token) {
      try { await this.request('/api/logout', 'POST', {}, token); } catch (_) {}
    }
  }

  async refresh() {
    if (!this.token) return;
    const scope = this.scope();
    const serial = ++this.refreshSerial;
    const token = this.token;
    try {
      const [workspace, history, selected] = await Promise.all([
        this.request('/api/workspace', 'GET', undefined, token),
        this.request('/api/rankings', 'GET', undefined, token),
        scope.selectedId
          ? this.request(`/api/conversations/${encodeURIComponent(scope.selectedId)}`, 'GET', undefined, token)
          : Promise.resolve(null),
      ]);
      if (!this.current(scope) || serial !== this.refreshSerial) return;
      this.workspace = workspace;
      this.ranking = history.rankings.length
        ? history.rankings[history.rankings.length - 1]
        : null;
      this.conversation = selected?.conversation || null;
      this.changed();
    } catch (error) {
      if (this.current(scope) && serial === this.refreshSerial) {
        this.error = error.message;
        this.changed();
      }
    }
  }

  async openConversation(id) {
    this.epoch++;
    this.selectedId = id;
    this.conversation = null;
    this.pending = this.intent = null;
    this.error = '';
    this.changed();
    await this.refresh();
  }

  async action(work) {
    if (!this.token || this.pending) return;
    const scope = this.scope();
    const marker = {};
    this.pending = marker;
    this.error = '';
    this.changed();
    try {
      return await work(scope);
    } catch (error) {
      if (this.current(scope)) {
        this.error = error.message;
        this.changed();
      }
    } finally {
      if (this.pending === marker) {
        this.pending = null;
        this.changed();
      }
    }
  }

  async createConversation(title) {
    return this.action(async scope => {
      this.intent = null;
      const result = await this.request('/api/conversations', 'POST', { title });
      if (this.current(scope)) {
        this.selectedId = result.conversation.id;
        this.conversation = result.conversation;
        await this.refresh();
      }
      return result;
    });
  }

  async upload(label, kind, file) {
    return this.action(async scope => {
      this.intent = null;
      if (!file) throw new Error('Choose a PNG image');
      const bytes = new Uint8Array(await file.arrayBuffer());
      if (!this.current(scope)) return;
      let binary = '';
      for (const byte of bytes) binary += String.fromCharCode(byte);
      const result = await this.request('/api/assets', 'POST', {
        label,
        kind,
        image_base64: btoa(binary),
      });
      if (this.current(scope)) await this.refresh();
      return result;
    });
  }

  newRequestId() {
    if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
    if (globalThis.crypto?.getRandomValues) {
      const bytes = new Uint8Array(16);
      globalThis.crypto.getRandomValues(bytes);
      return [...bytes].map(value => value.toString(16).padStart(2, '0')).join('');
    }
    return `${Date.now().toString(36)}_${Math.random().toString(36).slice(2)}`.slice(0, 64);
  }

  sameSemantic(left, right) {
    return JSON.stringify(left) === JSON.stringify(right);
  }

  async workflow(operation, fields) {
    // The view disables controls while pending; keep the same invariant for
    // direct callers so a second click cannot replace an in-flight intent.
    if (!this.token || this.pending) return;
    let semantic;
    if (operation === 'extract') {
      semantic = {
        conversation_id: this.selectedId,
        asset_id: fields?.asset_id,
      };
    } else if (operation === 'coach') {
      semantic = {
        conversation_id: this.selectedId,
        question: typeof fields?.question === 'string'
          ? fields.question.trim()
          : fields?.question,
      };
    } else {
      semantic = {
        asset_ids: Array.isArray(fields?.asset_ids) ? [...fields.asset_ids] : fields?.asset_ids,
      };
    }

    // A changed semantic payload deliberately abandons the old retry intent.
    // Otherwise retain the original fields and key, even if a refresh changed
    // other client-side state while the reply was unavailable.
    if (!this.intent || this.intent.operation !== operation
        || !this.sameSemantic(this.intent.semantic, semantic)) {
      this.intent = {
        operation,
        semantic,
        fields: operation === 'extract'
          ? { conversation_id: semantic.conversation_id, asset_id: semantic.asset_id }
          : operation === 'coach'
            ? { conversation_id: semantic.conversation_id, question: semantic.question }
            : { asset_ids: Array.isArray(semantic.asset_ids) ? [...semantic.asset_ids] : semantic.asset_ids },
        request_id: this.newRequestId(),
      };
    }
    const intent = this.intent;

    return this.action(async scope => {
      const result = await this.request(`/api/${intent.operation}`, 'POST', {
        ...intent.fields,
        request_id: intent.request_id,
      });
      if (this.current(scope)) {
        // The server response is durable.  Clear retry state before refresh so
        // a refresh/network error cannot accidentally repeat a committed action.
        if (this.intent === intent) this.intent = null;
        await this.refresh();
      }
      return result;
    });
  }

  async extract(assetId) {
    return this.workflow('extract', { asset_id: assetId });
  }

  async coach(question) {
    return this.workflow('coach', {
      question: typeof question === 'string' ? question.trim() : question,
    });
  }

  async rank(assetIds) {
    return this.workflow('rank', {
      asset_ids: Array.isArray(assetIds) ? [...assetIds] : assetIds,
    });
  }

  async saveProfile(tone, goal) {
    return this.action(async scope => {
      this.intent = null;
      try {
        const result = await this.request('/api/profile', 'PUT', {
          tone,
          goal,
          revision: this.workspace?.profile.revision,
        });
        if (this.current(scope)) await this.refresh();
        return result;
      } catch (error) {
        // A stale optimistic revision needs an authoritative refresh while the
        // conflict remains visible to the user.
        if (error.status === 409 && this.current(scope)) await this.refresh();
        throw error;
      }
    });
  }

  dispose() { this.clear(); }
}


export class WorkspaceView {
  constructor(client, document) {
    this.client = client;
    this.document = document;
    this.listeners = [];
    this.objectUrls = [];
    this.assetGeneration = 0;
    this.assetSignature = null;
    this.profileSignature = null;
    this.onChange = () => this.render();
    client.addEventListener('change', this.onChange);
    this.bind('login-form', 'submit', () => client.login(this.value('username'), this.value('password')));
    this.bind('logout', 'click', () => client.logout());
    this.bind('create-conversation', 'click', () => client.createConversation(this.value('conversation-title')));
    this.bind('upload', 'click', () => client.upload(
      this.value('asset-label'), this.value('asset-kind'), this.element('asset-file').files[0]));
    this.bind('extract', 'click', () => client.extract(
      this.document.querySelector('[data-screenshot-id]:checked')?.dataset.screenshotId));
    this.bind('coach', 'click', () => client.coach(this.value('question')));
    this.bind('save-profile', 'click', () => client.saveProfile(this.value('tone'), this.value('goal')));
    this.bind('rank', 'click', () => client.rank(
      [...this.document.querySelectorAll('[data-photo-id]:checked')]
        .map(node => node.dataset.photoId)));
    this.render();
  }

  element(id) { return this.document.getElementById(id); }
  value(id) { return this.element(id).value; }

  bind(id, type, callback) {
    const node = this.element(id);
    const handler = event => { event.preventDefault(); callback(); };
    node.addEventListener(type, handler);
    this.listeners.push(() => node.removeEventListener(type, handler));
  }

  node(tag, content, className) {
    const node = this.document.createElement(tag);
    if (content !== undefined) node.textContent = content;
    if (className) node.className = className;
    return node;
  }

  clearImages() {
    this.assetGeneration++;
    for (const url of this.objectUrls) URL.revokeObjectURL(url);
    this.objectUrls = [];
  }

  render() {
    const client = this.client;
    const authenticated = !!client.token;
    this.element('login-form').hidden = authenticated;
    this.element('workspace').hidden = !authenticated;
    this.element('logout').hidden = !authenticated;
    this.element('error').textContent = client.error || '';
    for (const id of ['create-conversation', 'upload', 'extract', 'coach', 'save-profile', 'rank']) {
      this.element(id).disabled = !authenticated || !!client.pending;
    }
    this.element('extract').disabled ||= !client.conversation;
    this.element('coach').disabled ||= !client.conversation;

    const conversations = this.element('conversation-list');
    conversations.replaceChildren();
    for (const conversation of client.workspace?.conversations || []) {
      const button = this.node('button', conversation.title);
      button.type = 'button';
      button.dataset.conversationId = conversation.id;
      button.setAttribute('aria-pressed', String(client.selectedId === conversation.id));
      button.onclick = () => client.openConversation(conversation.id);
      conversations.append(button);
    }

    const transcript = this.element('transcript');
    transcript.replaceChildren();
    for (const message of client.conversation?.messages || []) {
      transcript.append(this.node('p', `${message.sender}: ${message.text}`, 'message'));
    }

    const advice = this.element('advice-list');
    advice.replaceChildren();
    for (const item of client.conversation?.advice || []) {
      const row = this.node('article', undefined, 'advice');
      row.append(this.node('strong', item.question), this.node('p', item.text));
      advice.append(row);
    }

    const profileSignature = JSON.stringify([client.token, client.workspace?.profile]);
    if (profileSignature !== this.profileSignature) {
      this.profileSignature = profileSignature;
      this.element('tone').value = client.workspace?.profile.tone || '';
      this.element('goal').value = client.workspace?.profile.goal || '';
    }

    const assetSignature = JSON.stringify([client.token, client.workspace?.assets]);
    if (assetSignature !== this.assetSignature) {
      this.assetSignature = assetSignature;
      this.renderAssets();
    }

    const ranking = this.element('ranking');
    ranking.replaceChildren();
    for (const item of client.ranking?.items || []) {
      const row = this.node('li');
      row.dataset.rankedAssetId = item.asset_id;
      row.append(this.node('strong', `${item.asset_id}: ${item.score}`));
      for (const reason of item.reasons) row.append(this.node('p', reason));
      ranking.append(row);
    }

    if (!authenticated) {
      for (const id of ['password', 'question', 'conversation-title', 'asset-label', 'asset-file']) {
        this.element(id).value = '';
      }
    }
  }

  renderAssets() {
    const selected = new Set([
      ...this.document.querySelectorAll('[data-photo-id]:checked, [data-screenshot-id]:checked'),
    ].map(node => node.dataset.photoId || node.dataset.screenshotId));
    this.clearImages();
    const generation = this.assetGeneration;
    const token = this.client.token;
    const list = this.element('asset-list');
    list.replaceChildren();
    for (const asset of this.client.workspace?.assets || []) {
      const row = this.node('article', undefined, 'asset');
      row.dataset.assetId = asset.id;
      const label = this.node('label');
      const input = this.node('input');
      input.type = asset.kind === 'screenshot' ? 'radio' : 'checkbox';
      if (asset.kind === 'screenshot') {
        input.name = 'screenshot';
        input.dataset.screenshotId = asset.id;
      } else {
        input.dataset.photoId = asset.id;
      }
      input.checked = selected.has(asset.id);
      label.append(input, this.node('span', `${asset.label} (${asset.kind})`));
      const image = this.node('img');
      image.alt = asset.label;
      row.append(label, image);
      list.append(row);

      // The token is sent in an Authorization header; it is never put in an
      // image URL or persistent browser storage.
      this.client.request(`/api/assets/${encodeURIComponent(asset.id)}/image`,
        'GET', undefined, token, true).then(blob => {
        if (generation !== this.assetGeneration || token !== this.client.token) return;
        const url = URL.createObjectURL(blob);
        this.objectUrls.push(url);
        image.src = url;
      }).catch(error => {
        if (generation === this.assetGeneration && token === this.client.token) {
          this.client.error = error.message;
          this.element('error').textContent = error.message;
        }
      });
    }
  }

  dispose() {
    this.clearImages();
    this.client.removeEventListener('change', this.onChange);
    for (const remove of this.listeners) remove();
    for (const button of this.element('conversation-list').querySelectorAll('button')) button.onclick = null;
    this.listeners = [];
  }
}

if (typeof document !== 'undefined' && document.getElementById('login-form')) {
  const client = new WorkspaceClient();
  const view = new WorkspaceView(client, document);
  window.addEventListener('pagehide', () => { view.dispose(); client.dispose(); }, { once: true });
}
