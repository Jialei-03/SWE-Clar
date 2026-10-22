'use strict';
class LoyaltyClient {
  constructor(baseURL = '') {
    this.baseURL = baseURL; this.epoch = 0; this.token = ''; this.listeners = new Set();
    this.clear();
  }
  clear() {
    this.user = null; this.error = null; this.preferences = null; this.wallet = null;
    for (const key of ['malls','shops','branches','rewards','assets','receipts','promotions','inbox','redemptions','merchant_owners']) this[key] = [];
  }
  notify() { for (const listener of this.listeners) listener(); }
  async request(path, method = 'GET', body, epoch = this.epoch, token = this.token) {
    const response = await fetch(this.baseURL + path, {method, headers: {'Content-Type':'application/json', ...(token ? {Authorization:'Bearer ' + token} : {})}, ...(body === undefined ? {} : {body:JSON.stringify(body)})});
    const data = await response.json();
    if (epoch !== this.epoch) throw new Error('stale_response');
    if (!response.ok) {
      if (response.status === 401) { ++this.epoch; this.token = ''; this.clear(); }
      this.error = data.error || {code:'request_failed'}; this.notify();
      throw new Error(this.error.code);
    }
    return data;
  }
  async login(username, password) {
    const epoch = ++this.epoch; this.token = ''; this.clear(); this.notify();
    try {
      const data = await this.request('/api/login', 'POST', {username,password}, epoch, '');
      if (epoch !== this.epoch) return;
      this.token = data.token; this.user = data.user; this.notify(); await this.refresh();
    } catch (error) { if (epoch === this.epoch && !this.error) { this.error = {code:'request_failed'}; this.notify(); } }
  }
  async logout() {
    const token = this.token; const epoch = ++this.epoch;
    this.token = ''; this.clear(); this.notify();
    try { await this.request('/api/logout', 'POST', {}, epoch, token); } catch (_) {}
  }
  async refresh() {
    if (!this.user) return;
    const epoch = this.epoch, role = this.user.role;
    const paths = [['/api/catalog', null]];
    if (role === 'consumer') paths.push(['/api/assets','assets'], ['/api/receipts','receipts'], ['/api/preferences','preferences'], ['/api/inbox','inbox'], ['/api/wallet','wallet'], ['/api/redemptions','redemptions']);
    if (role === 'administrator') paths.push(['/api/merchant-owners','merchant_owners'], ['/api/receipts','receipts'], ['/api/promotions','promotions'], ['/api/redemptions','redemptions']);
    if (role === 'merchant') paths.push(['/api/promotions','promotions']);
    try {
      const values = await Promise.all(paths.map(([path]) => this.request(path, 'GET', undefined, epoch)));
      if (epoch !== this.epoch) return;
      values.forEach((value, index) => {
        const key = paths[index][1];
        if (key === null) for (const collection of ['malls','shops','branches','rewards']) this[collection] = value[collection];
        else this[key] = key === 'wallet' ? value : value[key === 'inbox' ? 'messages' : key];
      });
      this.error = null; this.notify();
    } catch (_) { if (epoch === this.epoch && !this.error) { this.error = {code:'request_failed'}; this.notify(); } }
  }
  async mutate(path, method, payload) {
    const epoch = this.epoch;
    try {
      const data = await this.request(path, method, payload, epoch);
      if (epoch === this.epoch) await this.refresh();
      return data;
    } catch (_) { if (epoch === this.epoch && !this.error) { this.error = {code:'request_failed'}; this.notify(); } }
  }
  upload(png_base64) { return this.mutate('/api/assets','POST',{png_base64}); }
  createMall(payload) { return this.mutate('/api/malls','POST',payload); }
  createShop(payload) { return this.mutate('/api/shops','POST',payload); }
  createBranch(payload) { return this.mutate('/api/branches','POST',payload); }
  setParticipation(id, participating) { return this.mutate('/api/branches/' + encodeURIComponent(id),'PATCH',{participating}); }
  submitReceipt(payload) { return this.mutate('/api/receipts','POST',payload); }
  reviewReceipt(id, decision) { return this.mutate('/api/receipts/' + encodeURIComponent(id) + '/review','POST',{decision}); }
  savePreferences(payload) { return this.mutate('/api/preferences','PUT',payload); }
  createPromotion(payload) { return this.mutate('/api/promotions','POST',payload); }
  cancelPromotion(id) { return this.mutate('/api/promotions/' + encodeURIComponent(id) + '/cancel','POST',{}); }
  dispatch() { return this.mutate('/api/dispatch','POST',{}); }
  redeem(payload) { return this.mutate('/api/redemptions','POST',payload); }
  dispose() { ++this.epoch; this.token = ''; this.clear(); this.notify(); this.listeners.clear(); }
}

class LoyaltyView {
  constructor(client, document) {
    this.client = client; this.document = document; this.urls = []; this.generation = 0; this.bindings = [];
    this.lastEpoch = client.epoch; this.listener = () => this.render(); client.listeners.add(this.listener);
    const byId = id => document.getElementById(id);
    const value = id => byId(id).value;
    const number = id => { const raw = value(id); if (!raw.trim()) throw new Error('invalid_request'); return Number(raw); };
    const action = (id, fn, event = 'click') => {
      const listener = async e => {
        e.preventDefault();
        try { await fn(); } catch (_) { client.error = {code:'invalid_request'}; client.notify(); }
      };
      byId(id).addEventListener(event, listener); this.bindings.push([byId(id), event, listener]);
    };
    action('login-form', () => client.login(value('username'), value('password')), 'submit');
    action('logout', () => client.logout()); action('refresh', () => client.refresh());
    action('create-mall', () => client.createMall({id:value('mall-id'),name:value('mall-name')}));
    action('create-shop', () => client.createShop({id:value('shop-id'),name:value('shop-name'),owner_id:value('shop-owner'),category:value('shop-category')}));
    action('create-branch', () => client.createBranch({id:value('branch-id'),shop_id:value('branch-shop'),mall_id:value('branch-mall'),participating:byId('branch-participating').checked}));
    action('upload-photo', async () => {
      const epoch = client.epoch, file = byId('upload-file').files[0]; if (!file) throw new Error('invalid_request');
      const bytes = new Uint8Array(await file.arrayBuffer()); let binary = '';
      for (const byte of bytes) binary += String.fromCharCode(byte);
      if (epoch === client.epoch) await client.upload(btoa(binary));
    });
    action('submit-receipt', () => client.submitReceipt({request_id:value('receipt-key'),branch_id:value('receipt-branch'),receipt_number:value('receipt-number'),date:value('receipt-date'),amount_cents:number('receipt-amount'),asset_id:value('receipt-asset')}));
    action('save-preferences', () => client.savePreferences({categories:JSON.parse(value('preference-categories')),mall_ids:JSON.parse(value('preference-malls'))}));
    action('create-promotion', () => client.createPromotion({shop_id:value('promotion-shop'),branch_ids:JSON.parse(value('promotion-branches')),title:value('promotion-title'),body:value('promotion-body'),due_at:number('promotion-due'),expires_at:number('promotion-expiry')}));
    action('dispatch', () => client.dispatch());
    action('redeem', () => client.redeem({request_id:value('redemption-key'),reward_id:value('redemption-reward')}));
    this.render();
  }
  releaseImages() { for (const url of this.urls) URL.revokeObjectURL(url); this.urls = []; }
  node(tag, text) { const element = this.document.createElement(tag); if (text !== undefined) element.textContent = text; return element; }
  button(row, hook, text, fn) { const button = this.node('button', text); button.setAttribute(hook, ''); button.addEventListener('click', fn); row.append(button); }
  async picture(parent, identity, generation) {
    const client = this.client, epoch = client.epoch;
    const container = this.node('div'); container.dataset.assetId = identity; parent.append(container);
    try {
      const response = await fetch(client.baseURL + '/api/assets/' + encodeURIComponent(identity), {headers:{Authorization:'Bearer ' + client.token}});
      if (generation !== this.generation || epoch !== client.epoch) return;
      if (response.status === 401) { ++client.epoch; client.token = ''; client.clear(); client.error = {code:'unauthenticated'}; client.notify(); return; }
      if (!response.ok) return;
      const blob = await response.blob();
      if (generation !== this.generation || epoch !== client.epoch) return;
      const url = URL.createObjectURL(blob); this.urls.push(url);
      const image = this.node('img'); image.alt = 'Submitted receipt image'; image.src = url;
      const link = this.node('a', 'View full-size image'); link.href = url; link.target = '_blank'; link.rel = 'noopener';
      container.append(image, link);
    } catch (_) {}
  }
  select(id, rows, label = row => row.name || row.id) {
    const element = this.document.getElementById(id), old = element.value;
    element.replaceChildren(); for (const row of rows) { const option = this.node('option', label(row)); option.value = row.id; element.append(option); }
    if (rows.some(row => row.id === old)) element.value = old;
  }
  render() {
    const c = this.client, d = this.document, generation = ++this.generation, role = c.user?.role;
    this.releaseImages();
    if (this.lastEpoch !== c.epoch) {
      for (const input of d.querySelectorAll('input,textarea')) { input.value = ''; if (input.type === 'checkbox') input.checked = false; }
      this.lastEpoch = c.epoch;
    }
    d.getElementById('login-form').hidden = !!c.user;
    d.getElementById('workspace').hidden = !c.user;
    d.getElementById('error').textContent = c.error?.code || '';
    for (const section of d.querySelectorAll('[data-roles]')) section.hidden = !section.dataset.roles.split(' ').includes(role);
    for (const id of ['catalog','assets','receipts','promotions','inbox','ledger','rewards','redemptions']) d.getElementById(id).replaceChildren();
    d.getElementById('wallet-balance').textContent = c.wallet ? String(c.wallet.balance) : '';
    if (!c.user) return;
    const catalog = d.getElementById('catalog');
    for (const [kind, rows] of [['mall',c.malls],['shop',c.shops],['branch',c.branches]]) for (const record of rows) {
      const row = this.node('article', Object.entries(record).map(([key,value]) => key + ': ' + value).join(' · ')); row.setAttribute('data-' + kind + '-id', record.id);
      if (kind === 'branch' && role === 'administrator') {
        const label = this.node('label', 'Participating '), checkbox = this.node('input'); checkbox.type = 'checkbox'; checkbox.checked = record.participating;
        checkbox.setAttribute('data-participating', ''); checkbox.addEventListener('change', () => c.setParticipation(record.id, checkbox.checked)); label.append(checkbox); row.append(label);
      }
      catalog.append(row);
    }
    this.select('branch-shop',c.shops); this.select('branch-mall',c.malls); this.select('receipt-branch',c.branches);
    this.select('receipt-asset',c.assets); this.select('promotion-shop',c.shops.filter(s => s.owner_id === c.user.id)); this.select('redemption-reward',c.rewards);
    this.select('shop-owner', c.merchant_owners);
    for (const asset of c.assets) this.picture(d.getElementById('assets'),asset.id,generation);
    for (const receipt of c.receipts) {
      const row = this.node('article', Object.entries(receipt).map(([key,value]) => key + ': ' + value).join(' · ')); row.dataset.receiptId = receipt.id;
      this.picture(row,receipt.asset_id,generation);
      if (role === 'administrator') { this.button(row,'data-approve','Approve',() => c.reviewReceipt(receipt.id,'approved')); this.button(row,'data-reject','Reject',() => c.reviewReceipt(receipt.id,'rejected')); }
      d.getElementById('receipts').append(row);
    }
    for (const promotion of c.promotions) {
      const row = this.node('article', promotion.title + ' · ' + promotion.status + ' · delivered: ' + promotion.delivered_count); row.dataset.promotionId = promotion.id;
      if (role === 'merchant') this.button(row,'data-cancel','Cancel',() => c.cancelPromotion(promotion.id)); d.getElementById('promotions').append(row);
    }
    for (const message of c.inbox) { const row = this.node('article',message.title + ' · ' + message.body); row.dataset.messageId = message.id; d.getElementById('inbox').append(row); }
    for (const entry of c.wallet?.ledger || []) { const row = this.node('article',entry.kind + ' · delta: ' + entry.delta + ' · balance: ' + entry.balance); row.dataset.ledgerId = entry.id; d.getElementById('ledger').append(row); }
    for (const reward of c.rewards) d.getElementById('rewards').append(this.node('article',reward.name + ' · cost: ' + reward.cost + ' · stock: ' + reward.stock));
    for (const redemption of c.redemptions) { const row = this.node('article',redemption.reward_id + ' · cost: ' + redemption.cost + ' · ' + redemption.status); row.dataset.redemptionId = redemption.id; d.getElementById('redemptions').append(row); }
    if (c.preferences) { d.getElementById('preference-categories').value = JSON.stringify(c.preferences.categories); d.getElementById('preference-malls').value = JSON.stringify(c.preferences.mall_ids); }
  }
  dispose() { ++this.generation; this.releaseImages(); this.client.listeners.delete(this.listener); for (const [node,event,listener] of this.bindings) node.removeEventListener(event,listener); this.bindings = []; }
}
window.LoyaltyClient = LoyaltyClient; window.LoyaltyView = LoyaltyView;
if (document.getElementById('workspace')) { window.loyaltyClient = new LoyaltyClient(); window.loyaltyView = new LoyaltyView(window.loyaltyClient,document); }
