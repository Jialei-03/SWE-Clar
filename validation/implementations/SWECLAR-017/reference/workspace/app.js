/* Session-only browser state. The service is authoritative for all business records. */
export class MarketplaceClient {
  constructor() {
    this.catalog = null;
    this.detail = null;
    this.agreements = [];
    this.error = '';
    this.token = null;
    this.selected = null;
    this.accountEpoch = 0;
    this.selectionEpoch = 0;
    this.readEpoch = 0;
    this.listeners = new Set();
  }

  subscribe(listener) { this.listeners.add(listener); return () => this.listeners.delete(listener); }
  emit() { for (const listener of this.listeners) listener(); }
  clear() {
    this.catalog = null; this.detail = null; this.agreements = [];
    this.token = null; this.selected = null;
    this.selectionEpoch++; this.readEpoch++;
  }
  scope() { return {account: this.accountEpoch, selection: this.selectionEpoch}; }
  current(scope) { return scope.account === this.accountEpoch && scope.selection === this.selectionEpoch; }
  async request(path, body, method, token = this.token) {
    const headers = {'Content-Type': 'application/json'};
    if (token) headers.Authorization = `Bearer ${token}`;
    const response = await fetch(path, {
      method: method || (body === undefined ? 'GET' : 'POST'), headers,
      ...(body === undefined ? {} : {body: JSON.stringify(body)})
    });
    const value = await response.json();
    if (!response.ok) {
      const error = new Error(response.status === 409 ? 'Conflict: the record changed. Review the refreshed information and try again.' :
        response.status === 401 ? 'Your session has ended. Please sign in.' :
        response.status === 403 ? 'This account cannot perform that action.' :
        response.status === 404 ? 'That record is unavailable.' : 'Check the submitted values.');
      error.status = response.status; throw error;
    }
    return value;
  }
  fail(error, scope) {
    if (!this.current(scope)) return;
    if (error.status === 401) { this.accountEpoch++; this.clear(); }
    this.error = error.message || 'The request failed. Please try again.';
    this.emit();
  }
  async login(username, password) {
    this.accountEpoch++; this.clear(); this.error = ''; this.emit();
    const scope = this.scope();
    try {
      const value = await this.request('/api/login', {username, password}, 'POST', null);
      if (!this.current(scope)) return;
      this.token = value.token;
      await this.load();
    } catch (error) { this.fail(error, scope); }
  }
  async logout() {
    const token = this.token;
    this.accountEpoch++; this.clear(); this.error = ''; this.emit();
    if (token) {
      try { await this.request('/api/logout', {}, 'POST', token); }
      catch (_) { /* The local session is already cleared; never restore it. */ }
    }
  }
  async load() {
    if (!this.token) return;
    const scope = this.scope(), read = ++this.readEpoch, selected = this.selected;
    try {
      const [catalog, agreements, detail] = await Promise.all([
        this.request('/api/catalog'), this.request('/api/agreements'),
        selected === null ? Promise.resolve(null) : this.request(`/api/listings/${encodeURIComponent(selected)}`)
      ]);
      if (!this.current(scope) || read !== this.readEpoch) return;
      this.catalog = catalog; this.agreements = agreements.agreements; this.detail = detail;
      this.emit();
    } catch (error) {
      if (read === this.readEpoch) this.fail(error, scope);
    }
  }
  async refresh() { this.error = ''; await this.load(); }
  async openListing(id) {
    this.selected = id; this.selectionEpoch++; this.detail = null;
    this.error = ''; this.emit(); await this.load();
  }
  async mutate(path, body, method = 'POST') {
    const scope = this.scope(); this.error = '';
    try {
      const value = await this.request(path, body, method);
      if (!this.current(scope)) return;
      await this.load();
      return value;
    } catch (error) {
      if (!this.current(scope)) return;
      if (error.status === 409) {
        await this.load();
        if (!this.current(scope)) return;
      }
      this.fail(error, scope);
    }
  }
  ask(text) {
    if (this.selected !== null) return this.mutate(`/api/listings/${encodeURIComponent(this.selected)}/questions`, {text});
  }
  offer(amountCents) {
    if (this.selected !== null) return this.mutate(`/api/listings/${encodeURIComponent(this.selected)}/offers`, {amount_cents: amountCents});
  }
  changePrice(priceCents) {
    if (this.detail) return this.mutate(`/api/listings/${encodeURIComponent(this.detail.listing.id)}/price`,
      {price_cents: priceCents, revision: this.detail.listing.revision}, 'PATCH');
  }
  counter(offerId, amountCents) {
    const offer = this.detail?.offers.find(item => item.id === offerId);
    if (offer) return this.mutate(`/api/offers/${encodeURIComponent(offerId)}/counter`, {amount_cents: amountCents, version: offer.version});
  }
  accept(offerId) {
    const offer = this.detail?.offers.find(item => item.id === offerId);
    if (offer) return this.mutate(`/api/offers/${encodeURIComponent(offerId)}/accept`, {version: offer.version});
  }
  dispose() { this.accountEpoch++; this.clear(); this.listeners.clear(); }
}

export class MarketplaceView {
  constructor(client, document) {
    this.client = client; this.document = document; this.bindings = [];
    this.on('login-form', 'submit', event => {
      event.preventDefault(); client.login(this.get('username').value, this.get('password').value);
      this.get('password').value = '';
    });
    this.on('logout', 'click', () => client.logout());
    this.on('refresh', 'click', () => client.refresh());
    this.on('ask', 'click', () => client.ask(this.get('question-text').value));
    this.on('place-offer', 'click', () => client.offer(this.money(this.get('offer-amount'))));
    this.on('save-price', 'click', () => client.changePrice(this.money(this.get('new-price'))));
    this.unsubscribe = client.subscribe(() => this.render());
    this.render();
  }
  get(id) { return this.document.getElementById(id); }
  money(input) { return input.value.trim() === '' ? null : Number(input.value); }
  on(id, event, callback) {
    const element = this.get(id); element.addEventListener(event, callback);
    this.bindings.push(() => element.removeEventListener(event, callback));
  }
  node(tag, text = '', attrs = {}) {
    const element = this.document.createElement(tag); element.textContent = text;
    for (const [key, value] of Object.entries(attrs)) element.setAttribute(key, value);
    return element;
  }
  labelNodes(labels) { return labels.map(label => this.node('span', label, {'data-label': label, class: 'badge'})); }
  render() {
    const client = this.client, user = client.catalog?.user;
    this.get('error').textContent = client.error;
    this.get('workspace').hidden = !user;
    this.get('logout').disabled = !client.token;
    this.get('signed-in').textContent = user ? `${user.username} · ${user.role}` : 'Signed out';
    const catalog = this.get('catalog'); catalog.replaceChildren();
    for (const listing of client.catalog?.listings || []) {
      const card = this.node('article', '', {class: 'catalog-card'});
      const button = this.node('button', listing.title, {'data-listing-id': listing.id, class: 'listing-select'});
      button.addEventListener('click', () => client.openListing(listing.id));
      card.append(button, this.node('p', `${listing.price_cents} cents · ${listing.status}`), ...this.labelNodes(listing.labels));
      catalog.append(card);
    }
    this.get('agreements').replaceChildren(...client.agreements.map(agreement =>
      this.node('li', `${agreement.listing_id} · ${agreement.amount_cents} cents`, {'data-agreement-id': agreement.id})));
    const detail = client.detail;
    this.get('listing-detail').hidden = !detail;
    if (!detail) {
      for (const id of ['listing-title', 'listing-price', 'listing-status', 'listing-labels', 'questions', 'offers']) this.get(id).replaceChildren();
      for (const id of ['question-text', 'offer-amount', 'new-price']) this.get(id).value = '';
      this.priceKey = null; return;
    }
    const listing = detail.listing, active = listing.status === 'active';
    this.get('listing-title').textContent = listing.title;
    this.get('listing-price').textContent = `${listing.price_cents} cents`;
    this.get('listing-status').textContent = listing.status;
    this.get('listing-labels').replaceChildren(...this.labelNodes(listing.labels));
    this.get('questions').replaceChildren(...detail.questions.map(question => this.node('li', `${question.author.username}: ${question.text}`)));
    for (const id of ['question-text', 'ask', 'offer-amount', 'place-offer']) this.get(id).disabled = !active || user.role !== 'buyer';
    for (const id of ['new-price', 'save-price']) this.get(id).disabled = !active || user.id !== listing.seller_id;
    const priceKey = `${client.accountEpoch}/${listing.id}/${listing.revision}`;
    if (this.priceKey !== priceKey) { this.get('new-price').value = listing.price_cents; this.priceKey = priceKey; }
    const rows = detail.offers.map(offer => {
      const row = this.node('li', '', {'data-offer-id': offer.id, class: 'offer-row'});
      row.append(this.node('p', `Offer: ${offer.amount_cents} cents${offer.counter_amount_cents === null ? '' : ` · Counter: ${offer.counter_amount_cents} cents`} · ${offer.status}`));
      if (user.id === listing.seller_id) {
        const label = this.node('label', 'Counter amount (integer cents)');
        const input = this.node('input', '', {'data-counter-amount': '', type: 'number', min: '1', max: '10000000', step: '1'});
        input.value = offer.counter_amount_cents ?? offer.amount_cents;
        const button = this.node('button', 'Counter', {'data-counter': ''});
        input.disabled = button.disabled = !active || offer.status !== 'pending';
        button.addEventListener('click', () => client.counter(offer.id, this.money(input)));
        label.append(input); row.append(label, button);
      }
      if (user.id === offer.buyer_id) {
        const button = this.node('button', 'Accept counteroffer', {'data-accept': ''});
        button.disabled = !(active && offer.status === 'countered') && offer.status !== 'accepted';
        button.addEventListener('click', () => client.accept(offer.id)); row.append(button);
      }
      return row;
    });
    this.get('offers').replaceChildren(...rows);
  }
  dispose() { this.unsubscribe(); for (const unbind of this.bindings) unbind(); }
}

if (typeof document !== 'undefined' && document.getElementById('login-form')) {
  const client = new MarketplaceClient();
  const view = new MarketplaceView(client, document);
  window.addEventListener('pagehide', () => { view.dispose(); client.dispose(); }, {once: true});
}
