export class RouteClient {
  constructor() {
    this.user = null; this.assets = []; this.waypoints = []; this.routes = [];
    this.routeDetail = null; this.waypointDetail = null; this.error = '';
    this.token = null; this.routeId = null; this.waypointId = null;
    this.sort = 'asc'; this.query = ''; this.account = 0; this.selection = 0; this.read = 0;
    this.listeners = new Set();
  }
  subscribe(callback) { this.listeners.add(callback); return () => this.listeners.delete(callback); }
  emit() { for (const callback of this.listeners) callback(); }
  scope() { return {account: this.account, selection: this.selection}; }
  current(scope) { return scope.account === this.account && scope.selection === this.selection; }
  clear() {
    this.user = null; this.assets = []; this.waypoints = []; this.routes = [];
    this.routeDetail = null; this.waypointDetail = null; this.token = null;
    this.routeId = null; this.waypointId = null; this.sort = 'asc'; this.query = '';
    this.selection++; this.read++;
  }
  async request(path, body, method, token = this.token) {
    const headers = {'Content-Type': 'application/json'};
    if (token) headers.Authorization = `Bearer ${token}`;
    const response = await fetch(path, {method: method || (body === undefined ? 'GET' : 'POST'), headers,
      ...(body === undefined ? {} : {body: JSON.stringify(body)})});
    const value = await response.json();
    if (!response.ok) {
      const error = new Error(response.status === 409 ? 'Conflict: review the refreshed record and submit again.' :
        response.status === 401 ? 'Please sign in again.' : value.error === 'profile_required' ? 'Save both your name and a profile photo first.' :
        response.status === 403 ? 'This record belongs to another member.' : response.status === 404 ? 'The selected record is unavailable.' :
        'Check the required fields and submitted values. A profile needs both a name and a photo.');
      error.status = response.status; throw error;
    }
    return value;
  }
  fail(error, scope) {
    if (!this.current(scope)) return;
    if (error.status === 401) { this.account++; this.clear(); }
    this.error = error.message || 'Request failed. You may retry.'; this.emit();
  }
  async login(username, password) {
    this.account++; this.clear(); this.error = ''; this.emit();
    const scope = this.scope();
    try {
      const value = await this.request('/api/login', {username, password}, 'POST', null);
      if (!this.current(scope)) return;
      this.token = value.token; await this.load();
    } catch (error) { this.fail(error, scope); }
  }
  async logout() {
    const token = this.token; this.account++; this.clear(); this.error = ''; this.emit();
    if (token) try { await this.request('/api/logout', {}, 'POST', token); } catch (_) {}
  }
  async load() {
    if (!this.token) return;
    const scope = this.scope(), read = ++this.read;
    try {
      const [me, assets, waypoints, routes, routeDetail, waypointDetail] = await Promise.all([
        this.request('/api/me'), this.request('/api/assets'), this.request('/api/waypoints'),
        this.request(`/api/routes?sort=${encodeURIComponent(this.sort)}&q=${encodeURIComponent(this.query)}`),
        this.routeId === null ? null : this.request(`/api/routes/${encodeURIComponent(this.routeId)}`),
        this.waypointId === null ? null : this.request(`/api/waypoints/${encodeURIComponent(this.waypointId)}`)
      ]);
      if (!this.current(scope) || read !== this.read) return;
      this.user = me.user; this.assets = assets.assets; this.waypoints = waypoints.waypoints;
      this.routes = routes.routes; this.routeDetail = routeDetail; this.waypointDetail = waypointDetail;
      this.emit();
    } catch (error) { if (read === this.read) this.fail(error, scope); }
  }
  async refresh() { this.error = ''; await this.load(); }
  async mutate(path, body, method = 'POST') {
    const scope = this.scope(); this.error = '';
    try {
      const value = await this.request(path, body, method);
      if (!this.current(scope)) return;
      await this.load(); return value;
    } catch (error) {
      if (!this.current(scope)) return;
      if (error.status === 409) await this.load();
      this.fail(error, scope);
    }
  }
  upload(pngBase64) { return this.mutate('/api/assets', {png_base64: pngBase64}); }
  saveProfile(name, photoId) { return this.mutate('/api/profile', {name, photo_id: photoId}, 'PUT'); }
  createWaypoint(name, lat, lon, photoIds) { return this.mutate('/api/waypoints', {name, lat, lon, photo_ids: photoIds}); }
  createRoute(title, waypointIds) { return this.mutate('/api/routes', {title, waypoint_ids: waypointIds}); }
  async openRoute(id) { this.routeId = id; this.routeDetail = null; this.selection++; this.error = ''; this.emit(); await this.load(); }
  async openWaypoint(id) { this.waypointId = id; this.waypointDetail = null; this.selection++; this.error = ''; this.emit(); await this.load(); }
  async setCatalog(sort, query) { this.sort = sort; this.query = query; this.error = ''; await this.load(); }
  setPinned(routeId, pinned) { return this.mutate(`/api/routes/${encodeURIComponent(routeId)}/pin`, {pinned}, 'PUT'); }
  submitStatus(status) { return this.mutate('/api/touring-status', {status}, 'PUT'); }
  editWaypoint(lat, lon) {
    const waypoint = this.waypointDetail?.waypoint;
    if (waypoint) return this.mutate(`/api/waypoints/${encodeURIComponent(waypoint.id)}`, {lat, lon, revision: waypoint.revision}, 'PATCH');
  }
  comment(text, requestId) {
    if (this.waypointId !== null) return this.mutate(`/api/waypoints/${encodeURIComponent(this.waypointId)}/comments`, {text, request_id: requestId});
  }
  dispose() { this.account++; this.clear(); this.listeners.clear(); }
}

export class RouteView {
  constructor(client, document) {
    this.client = client; this.document = document; this.unbind = []; this.urls = new Set(); this.intent = null;
    this.on('login-form', 'submit', event => {event.preventDefault(); this.run(() => client.login(this.get('username').value, this.get('password').value)); this.get('password').value = '';});
    this.on('logout', 'click', () => this.run(() => client.logout()));
    this.on('refresh', 'click', () => this.run(() => client.refresh()));
    this.on('upload-photo', 'click', () => this.upload());
    this.on('save-profile', 'click', () => this.run(() => client.saveProfile(this.get('profile-name').value, this.get('profile-photo').value)));
    this.on('create-waypoint', 'click', () => this.run(async () => {
      const scope = client.scope(); const value = await client.createWaypoint(this.get('waypoint-name').value, this.number('waypoint-lat'), this.number('waypoint-lon'), this.selected('waypoint-photos'));
      if (value && client.current(scope)) for (const option of this.get('waypoint-photos').options) option.selected = false;
    }));
    this.on('create-route', 'click', () => this.run(() => {
      let ids; try { ids = JSON.parse(this.get('route-waypoints').value); } catch (_) { throw new Error('Enter waypoint IDs as a JSON array.'); }
      return client.createRoute(this.get('route-title').value, ids);
    }));
    this.on('apply-catalog', 'click', () => this.run(() => client.setCatalog(this.get('route-sort').value, this.get('route-query').value)));
    this.on('submit-status', 'click', () => this.run(() => client.submitStatus(this.get('touring-status').value)));
    this.on('save-location', 'click', () => this.run(() => client.editWaypoint(this.number('edit-lat'), this.number('edit-lon'))));
    this.on('send-comment', 'click', () => this.sendComment());
    this.unsubscribe = client.subscribe(() => this.render()); this.render();
  }
  get(id) { return this.document.getElementById(id); }
  number(id) { const value = this.get(id).value.trim(); return value === '' ? null : Number(value); }
  selected(id) { return Array.from(this.get(id).selectedOptions, option => option.value); }
  async run(operation) {
    const scope = this.client.scope();
    try { return await operation(); } catch (error) { this.client.fail(error, scope); }
  }
  on(id, type, callback) {
    const element = this.get(id); element.addEventListener(type, callback);
    this.unbind.push(() => element.removeEventListener(type, callback));
  }
  node(tag, content = '', attributes = {}) {
    const node = this.document.createElement(tag); node.textContent = content;
    for (const [key, value] of Object.entries(attributes)) node.setAttribute(key, value);
    return node;
  }
  option(value, label) { return this.node('option', label, {value}); }
  async upload() {
    const scope = this.client.scope();
    return this.run(async () => {
      const file = this.get('upload-file').files[0];
      if (!file) throw new Error('Choose a PNG file first.');
      const bytes = new Uint8Array(await file.arrayBuffer());
      if (!this.client.current(scope)) return;
      let binary = ''; for (const byte of bytes) binary += String.fromCharCode(byte);
      return this.client.upload(btoa(binary));
    });
  }
  sendComment() {
    return this.run(async () => {
      const client = this.client, text = this.get('comment-text').value, scope = client.scope();
      const signature = JSON.stringify([scope.account, client.waypointId, text.trim()]);
      if (!this.intent || this.intent.signature !== signature) this.intent = {signature, key: crypto.randomUUID()};
      const intent = this.intent, value = await client.comment(text, intent.key);
      if (value && client.current(scope) && this.intent === intent) { this.intent = null; this.get('comment-text').value = ''; }
    });
  }
  image(id) {
    const wrapper = this.node('figure', '', {'data-asset-id': id});
    const image = this.node('img', '', {alt: 'Synthetic uploaded photo'});
    const link = this.node('a', 'Open full-size photo', {target: '_blank', rel: 'noopener'});
    wrapper.append(image, link);
    const account = this.client.account, scope = this.client.scope(), token = this.client.token;
    fetch(`/api/assets/${encodeURIComponent(id)}`, {headers: {Authorization: `Bearer ${token}`}})
      .then(response => {if (!response.ok) {const error = new Error('Photo unavailable'); error.status = response.status; throw error;} return response.blob();})
      .then(blob => {
        if (!wrapper.isConnected || account !== this.client.account) return;
        const url = URL.createObjectURL(blob); this.urls.add(url); image.src = link.href = url;
      }).catch(error => {
        if (error.status === 401) this.client.fail(error, scope);
        else if (wrapper.isConnected && account === this.client.account) link.textContent = 'Photo unavailable';
      });
    return wrapper;
  }
  map() {
    const map = this.get('map'), client = this.client; map.replaceChildren();
    const element = (tag, attrs, text) => {
      const node = this.document.createElementNS('http://www.w3.org/2000/svg', tag);
      for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, value);
      if (text !== undefined) node.textContent = text; return node;
    };
    const xy = waypoint => [2 * (waypoint.lon + 180), 2 * (85 - waypoint.lat)];
    map.append(element('rect', {x: 0, y: 0, width: 720, height: 340, fill: '#edf3f0'}));
    for (let x = 0; x <= 720; x += 90) map.append(element('line', {x1: x, y1: 0, x2: x, y2: 340, stroke: '#ccdcd3'}));
    for (let y = 0; y <= 340; y += 85) map.append(element('line', {x1: 0, y1: y, x2: 720, y2: y, stroke: '#ccdcd3'}));
    if (client.routeDetail) map.append(element('polyline', {points: client.routeDetail.waypoints.map(xy).map(pair => pair.join(',')).join(' '), fill: 'none', stroke: '#aa4b29', 'stroke-width': 4, 'data-route-path': ''}));
    for (const waypoint of client.waypoints) {
      const [x, y] = xy(waypoint);
      const marker = element('circle', {cx: x, cy: y, r: 6, fill: '#265747', 'data-waypoint-id': waypoint.id, tabindex: 0, role: 'button', 'aria-label': waypoint.name});
      marker.addEventListener('click', () => this.run(() => client.openWaypoint(waypoint.id)));
      marker.addEventListener('keydown', event => {if (event.key === 'Enter' || event.key === ' ') {event.preventDefault(); this.run(() => client.openWaypoint(waypoint.id));}});
      map.append(marker, element('text', {x: x + 9, y: y - 9, 'font-size': 11, fill: '#193c30'}, waypoint.name));
    }
  }
  render() {
    for (const url of this.urls) URL.revokeObjectURL(url); this.urls.clear();
    const client = this.client, user = client.user;
    this.get('error').textContent = client.error; this.get('workspace').hidden = !user;
    this.get('logout').disabled = !client.token;
    if (!user) {
      for (const id of ['asset-list', 'waypoint-list', 'route-list', 'route-stops', 'waypoint-images', 'comments', 'route-heading', 'waypoint-heading', 'map']) this.get(id).replaceChildren();
      for (const id of ['profile-name', 'comment-text', 'edit-lat', 'edit-lon', 'upload-file', 'waypoint-name', 'waypoint-lat', 'waypoint-lon', 'route-title', 'route-waypoints', 'route-query']) this.get(id).value = '';
      this.get('route-sort').value = 'asc'; this.get('touring-status').value = 'planned';
      this.get('profile-photo').replaceChildren(); this.get('waypoint-photos').replaceChildren();
      this.get('route-detail').hidden = this.get('waypoint-detail').hidden = true;
      this.statusKey = this.profileKey = this.editKey = null; this.intent = null; return;
    }
    const previousPhoto = this.get('profile-photo').value, previousPhotos = this.selected('waypoint-photos');
    this.get('profile-photo').replaceChildren(this.option('', 'Choose a photo'), ...client.assets.map(asset => this.option(asset.id, `${asset.id} · ${asset.width}×${asset.height}`)));
    this.get('waypoint-photos').replaceChildren(...client.assets.map(asset => this.option(asset.id, `${asset.id} · ${asset.width}×${asset.height}`)));
    this.get('profile-photo').value = previousPhoto;
    for (const option of this.get('waypoint-photos').options) option.selected = previousPhotos.includes(option.value);
    const profileKey = JSON.stringify([user.id, user.name, user.photo_id]);
    if (this.profileKey !== profileKey) { this.get('profile-name').value = user.name; this.get('profile-photo').value = user.photo_id || ''; this.profileKey = profileKey; }
    const statusKey = `${client.account}/${user.touring_status}`;
    if (this.statusKey !== statusKey) { this.get('touring-status').value = user.touring_status; this.statusKey = statusKey; }
    this.get('asset-list').replaceChildren(...client.assets.map(asset => this.image(asset.id)));
    this.get('waypoint-list').replaceChildren(...client.waypoints.map(waypoint => {
      const row = this.node('li'); const button = this.node('button', waypoint.name, {'data-waypoint-id': waypoint.id});
      button.addEventListener('click', () => this.run(() => client.openWaypoint(waypoint.id)));
      row.append(button, this.node('small', ` ${waypoint.id} · ${waypoint.lat}, ${waypoint.lon}`)); return row;
    }));
    this.get('route-list').replaceChildren(...client.routes.map(route => {
      const row = this.node('li', '', {class: 'route-row'});
      const open = this.node('button', route.title, {'data-route-id': route.id});
      const pin = this.node('button', route.pinned ? 'Unpin' : 'Pin', {'data-pin-route': route.id, 'aria-label': `${route.pinned ? 'Unpin' : 'Pin'} ${route.title}`});
      open.addEventListener('click', () => this.run(() => client.openRoute(route.id)));
      pin.addEventListener('click', () => this.run(() => client.setPinned(route.id, !route.pinned))); pin.disabled = user.profile_required;
      row.append(open, pin); return row;
    }));
    this.get('route-detail').hidden = !client.routeDetail;
    this.get('route-heading').textContent = client.routeDetail?.route.title || '';
    this.get('route-stops').replaceChildren(...(client.routeDetail?.waypoints || []).map(waypoint => this.node('li', `${waypoint.name} · ${waypoint.lat}, ${waypoint.lon}`, {'data-stop-id': waypoint.id})));
    const waypoint = client.waypointDetail?.waypoint;
    this.get('waypoint-detail').hidden = !waypoint;
    this.get('waypoint-heading').textContent = waypoint?.name || '';
    this.get('waypoint-images').replaceChildren(...(waypoint?.photo_ids || []).map(id => this.image(id)));
    this.get('comments').replaceChildren(...(client.waypointDetail?.comments || []).map(comment => this.node('li', `${comment.author.name}: ${comment.text}`, {'data-comment-id': comment.id})));
    const editKey = waypoint ? `${client.account}/${waypoint.id}/${waypoint.revision}` : null;
    if (this.editKey !== editKey) {
      this.get('edit-lat').value = waypoint?.lat ?? ''; this.get('edit-lon').value = waypoint?.lon ?? ''; this.editKey = editKey;
    }
    for (const id of ['create-waypoint', 'create-route', 'send-comment', 'submit-status']) this.get(id).disabled = user.profile_required;
    for (const id of ['save-location', 'edit-lat', 'edit-lon']) this.get(id).disabled = user.profile_required || !waypoint || waypoint.owner_id !== user.id;
    this.map();
  }
  dispose() { this.unsubscribe(); for (const fn of this.unbind) fn(); for (const url of this.urls) URL.revokeObjectURL(url); this.urls.clear(); }
}

if (typeof document !== 'undefined' && document.getElementById('login-form')) {
  const client = new RouteClient(), view = new RouteView(client, document);
  window.addEventListener('pagehide', () => {view.dispose(); client.dispose();}, {once: true});
}
