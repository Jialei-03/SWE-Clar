/* Synthetic attendance client; tokens and records live only in this page. */
class AttendanceClient {
  constructor(baseURL = '', readerURL = 'http://127.0.0.1:8081') {
    this.base = baseURL.replace(/\/$/, ''); this.readerURL = readerURL.replace(/\/$/, '');
    this.listeners = new Set(); this.epoch = 0; this.readVersion = 0; this.token = null;
    this.clear();
  }
  clear() { this.user = null; for (const key of ['students','guardians','tags','devices','scans','attendance','inbox']) this[key] = []; this.error = null; }
  emit() { for (const listener of this.listeners) listener(); }
  subscribe(listener) { this.listeners.add(listener); return () => this.listeners.delete(listener); }
  async request(path, body, method = body === undefined ? 'GET' : 'POST', epoch = this.epoch) {
    try {
      const headers = {'Content-Type':'application/json'}; if (this.token) headers.Authorization = 'Bearer ' + this.token;
      const response = await fetch(this.base + path, {method, headers, body:body === undefined ? undefined : JSON.stringify(body)});
      const value = await response.json();
      if (epoch !== this.epoch) return null;
      if (!response.ok) {
        if (response.status === 401) { this.epoch++; this.token = null; this.clear(); }
        this.error = {code:value.error?.code || 'request_failed'}; this.emit(); throw Object.assign(new Error(this.error.code), {handled:true});
      }
      return value;
    } catch (error) {
      if (epoch === this.epoch && !error.handled) { this.error = {code:'network_error'}; this.emit(); }
      throw error;
    }
  }
  async login(username, password) {
    const epoch = ++this.epoch; this.token = null; this.clear(); this.emit();
    const value = await this.request('/api/login', {username,password}, 'POST', epoch);
    if (!value || epoch !== this.epoch) return;
    this.token = value.token; this.user = value.user; this.emit(); await this.refresh();
  }
  async logout() {
    const headers = {'Content-Type':'application/json','Authorization':'Bearer ' + this.token};
    this.epoch++; this.token = null; this.clear(); this.emit();
    try { await fetch(this.base + '/api/logout', {method:'POST',headers,body:'{}'}); } catch (_) {}
  }
  async refresh() {
    if (!this.user) return;
    const epoch = this.epoch, version = ++this.readVersion, parent = this.user.role === 'parent';
    const values = await Promise.all([
      this.request('/api/me',undefined,'GET',epoch), this.request('/api/roster',undefined,'GET',epoch),
      this.request('/api/attendance',undefined,'GET',epoch), this.request(parent ? '/api/inbox' : '/api/scans',undefined,'GET',epoch)
    ]);
    if (epoch !== this.epoch || version !== this.readVersion || values.some(v => !v)) return;
    this.user = values[0].user; Object.assign(this, values[1]); this.attendance = values[2].attendance;
    this.inbox = parent ? values[3].entries : []; this.scans = parent ? [] : values[3].scans;
    this.error = null; this.emit();
  }
  async mutate(path, body, method = 'POST') {
    const epoch = this.epoch;
    try { const value = await this.request(path,body,method,epoch); if (value && epoch === this.epoch) await this.refresh(); return value; }
    catch (error) {
      if (epoch === this.epoch && this.user) {
        const failure = this.error;
        try { await this.refresh(); } catch (_) {}
        if (epoch === this.epoch) { this.error = failure; this.emit(); }
      }
      throw error;
    }
  }
  scan(readingId,direction) { return this.mutate('/api/scans',{reading_id:readingId,direction}); }
  confirm(scanId,recipientId = null) { return this.mutate('/api/scans/'+encodeURIComponent(scanId)+'/confirm',{recipient_id:recipientId}); }
  setTagActive(uid,active) { return this.mutate('/api/tags/'+encodeURIComponent(uid),{active},'PATCH'); }
  setGuardianActive(id,active) { return this.mutate('/api/guardians/'+encodeURIComponent(id),{active},'PATCH'); }
  setRead(id,read) { return this.mutate('/api/inbox/'+encodeURIComponent(id),{read},'PUT'); }
  dispose() { this.epoch++; this.token = null; this.clear(); this.listeners.clear(); }
}

class AttendanceView {
  constructor(client, document) {
    this.client = client; this.document = document; this.handlers = []; this.currentUser = null;
    this.listen('login-form','submit',event => { event.preventDefault(); this.run(() => client.login(this.value('username'),this.value('password'))); });
    this.listen('logout','click',() => this.run(() => client.logout()));
    this.listen('refresh','click',() => this.run(() => client.refresh()));
    this.listen('scan','click',() => this.run(async () => {
      const epoch = client.epoch;
      const payload = {uid:this.value('tag-uid'),device_id:this.value('device-id'),interaction:this.value('interaction'),at:Number(this.value('reading-time'))};
      const direction = this.value('direction');
      const response = await fetch(client.readerURL+'/readings',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
      const value = await response.json();
      if (epoch !== client.epoch) return;
      if (!response.ok) { client.error = value.error; client.emit(); return; }
      await client.scan(value.reading.id,direction);
    }));
    this.unsubscribe = client.subscribe(() => this.render()); this.render();
  }
  node(id) { return this.document.getElementById(id); }
  value(id) { return this.node(id).value; }
  listen(id,type,handler) { const node = this.node(id); if (!node) return; node.addEventListener(type,handler); this.handlers.push(() => node.removeEventListener(type,handler)); }
  async run(action) {
    const epoch = this.client.epoch;
    try { await action(); } catch (_) {
      if (epoch === this.client.epoch && !this.client.error) { this.client.error = {code:'network_error'}; this.client.emit(); }
    }
  }
  el(tag,text,attrs={}) {
    const node = this.document.createElement(tag); if (text !== undefined) node.textContent = text;
    for (const [key,value] of Object.entries(attrs)) node.setAttribute(key,value);
    return node;
  }
  options(select, items, placeholder) {
    const old = select.value; select.replaceChildren();
    if (placeholder !== undefined) select.append(this.el('option',placeholder,{value:''}));
    for (const item of items) select.append(this.el('option',item.name,{value:item.id}));
    if (items.some(i => i.id === old)) select.value = old;
  }
  render() {
    const c = this.client, staff = c.user && c.user.role !== 'parent', admin = c.user?.role === 'administrator';
    this.node('workspace').hidden = !c.user; this.node('login-form').hidden = !!c.user;
    this.node('error').textContent = c.error?.code || '';
    if (this.currentUser !== c.user?.id) {
      this.currentUser = c.user?.id;
      for (const id of ['password','tag-uid']) this.node(id).value = '';
      this.node('interaction').value = 'tap'; this.node('direction').value = 'in';
    }
    for (const id of ['scan-panel','pending-section']) this.node(id).hidden = !staff;
    this.node('inbox-section').hidden = c.user?.role !== 'parent'; this.node('admin-section').hidden = !admin;
    this.options(this.node('device-id'),c.devices,'Choose a device');
    const names = new Map(c.students.map(s => [s.id,s.name]));
    const nameFor = id => names.has(id) ? names.get(id) : id;
    const roster = this.node('roster'); roster.replaceChildren();
    for (const s of c.students) roster.append(this.el('li',s.name+' · '+s.presence,{'data-student-id':s.id}));
    const pending = this.node('pending-list'); const choices = new Map([...pending.querySelectorAll('[data-scan-id]')].map(row => [row.dataset.scanId,row.querySelector('[data-recipient]').value])); pending.replaceChildren();
    for (const scan of c.scans.filter(s => s.state === 'pending')) {
      const row = this.el('li',undefined,{'data-scan-id':scan.id}); row.append(this.el('span',nameFor(scan.student_id)+' · '+scan.direction));
      const select = this.el('select',undefined,{'data-recipient':'','aria-label':'Collection recipient'}); this.options(select,c.guardians,'No recipient');
      if (choices.has(scan.id)) select.value = choices.get(scan.id);
      const button = this.el('button','Confirm',{'data-confirm':'',type:'button'});
      button.addEventListener('click',() => this.run(() => c.confirm(scan.id,select.value || null))); row.append(select,button); pending.append(row);
    }
    const attendance = this.node('attendance-list'); attendance.replaceChildren();
    for (const item of c.attendance) attendance.append(this.el('li',nameFor(item.student_id)+' · '+item.direction+' · '+item.at,{'data-attendance-id':item.id}));
    const inbox = this.node('inbox'); inbox.replaceChildren();
    for (const item of c.inbox) {
      const row = this.el('li',undefined,{'data-entry-id':item.id}); row.append(this.el('span',nameFor(item.student_id)+' · '+item.direction));
      const label = this.el('label','Read '); const check = this.el('input',undefined,{type:'checkbox','data-read':''}); check.checked = item.read;
      check.addEventListener('change',() => this.run(() => c.setRead(item.id,check.checked))); label.append(check); row.append(label); inbox.append(row);
    }
    for (const [id,items,attribute,flag,action] of [['tag-list',c.tags,'data-tag-uid','data-tag-active',(key,value)=>c.setTagActive(key,value)],['guardian-list',c.guardians,'data-guardian-id','data-guardian-active',(key,value)=>c.setGuardianActive(key,value)]]) {
      const list = this.node(id); list.replaceChildren();
      if (admin) for (const item of items) {
        const key = item.uid || item.id; const row = this.el('li',undefined,{[attribute]:key}); const label = this.el('label',(item.name !== undefined ? item.name : key)+' active ');
        const check = this.el('input',undefined,{type:'checkbox',[flag]:''}); check.checked = item.active;
        check.addEventListener('change',() => this.run(() => action(key,check.checked))); label.append(check); row.append(label); list.append(row);
      }
    }
  }
  dispose() { this.unsubscribe(); for (const remove of this.handlers) remove(); }
}
window.AttendanceClient = AttendanceClient; window.AttendanceView = AttendanceView;
if (document.getElementById('workspace')) {
  const client = new AttendanceClient(); const view = new AttendanceView(client,document);
  window.addEventListener('pagehide',() => { view.dispose(); client.dispose(); },{once:true});
}
