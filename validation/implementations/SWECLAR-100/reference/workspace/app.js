const q = selector => document.querySelector(selector);

let token = '';
let bundle = null;
let view = { page: 'home' };
let history = [];
let sessionEpoch = 0;
let statusState = null;

const labels = {
  en: {
    catalogue: 'Catalogue',
    back: 'Back',
    language: 'Language',
    english: 'English',
    spanish: 'Spanish',
    noContent: 'No synchronized content',
    contentVersion: version => `Content version ${version}`,
    tools: 'Connection and device tools',
    accessToken: 'Access token',
    connect: 'Connect',
    synchronize: 'Synchronize content',
    managedDevice: 'Managed device',
    settings: 'Request network settings',
    homeHeading: 'Catalogue',
    connected: 'Session connected.',
    synchronizing: 'Synchronizing content…',
    synchronized: version => `Content synchronized (version ${version}).`,
    noSession: 'Connect an access token before synchronizing.',
    failed: 'Content synchronization failed.',
    settingsAcknowledged: 'Network settings request acknowledged.',
    requestFailed: 'Request could not be completed.'
  },
  es: {
    catalogue: 'Catálogo',
    back: 'Atrás',
    language: 'Idioma',
    english: 'Inglés',
    spanish: 'Español',
    noContent: 'No hay contenido sincronizado',
    contentVersion: version => `Versión de contenido ${version}`,
    tools: 'Herramientas de conexión y dispositivo',
    accessToken: 'Token de acceso',
    connect: 'Conectar',
    synchronize: 'Sincronizar contenido',
    managedDevice: 'Dispositivo administrado',
    settings: 'Solicitar configuración de red',
    homeHeading: 'Catálogo',
    connected: 'Sesión conectada.',
    synchronizing: 'Sincronizando contenido…',
    synchronized: version => `Contenido sincronizado (versión ${version}).`,
    noSession: 'Conecte un token de acceso antes de sincronizar.',
    failed: 'No se pudo sincronizar el contenido.',
    settingsAcknowledged: 'Solicitud de configuración de red confirmada.',
    requestFailed: 'No se pudo completar la solicitud.'
  }
};

function currentLanguage() {
  return q('#language').value === 'es' ? 'es' : 'en';
}

function currentLabels() {
  return labels[currentLanguage()];
}

function setLabels(lang) {
  const text = labels[lang];
  document.documentElement.lang = lang;
  document.title = lang === 'es' ? 'Kiosco de catálogo' : 'Catalogue kiosk';
  q('#logo').textContent = text.catalogue;
  q('#back').textContent = text.back;
  q('#language-label').textContent = text.language;
  q('#language').setAttribute('aria-label', text.language);
  q('#language option[value="en"]').textContent = text.english;
  q('#language option[value="es"]').textContent = text.spanish;
  q('#tools-label').textContent = text.tools;
  q('#token-label').textContent = text.accessToken;
  q('#connect-button').textContent = text.connect;
  q('#sync').textContent = text.synchronize;
  q('#device-label').textContent = text.managedDevice;
  q('#settings-button').textContent = text.settings;
}

function statusMessage(key, argument, lang = currentLanguage()) {
  const text = labels[lang];
  if (key === 'version') return text.contentVersion(argument);
  if (key === 'synchronized') return text.synchronized(argument);
  return text[key] || '';
}

function setStatus(message, key = null, argument = null) {
  statusState = key ? { key, argument } : { message: message || '' };
  q('#status').textContent = key ? statusMessage(key, argument) : (message || '');
}

function showStatus(key, argument = null) {
  setStatus(statusMessage(key, argument), key, argument);
}

async function api(path, body, accessToken = token) {
  const options = {
    method: body === undefined ? 'GET' : 'POST',
    headers: {}
  };
  if (accessToken) options.headers.Authorization = `Bearer ${accessToken}`;
  if (body !== undefined) {
    options.headers['Content-Type'] = 'application/json';
    options.body = JSON.stringify(body);
  }
  let response;
  try {
    response = await fetch(path, options);
  } catch {
    throw new Error(currentLabels().requestFailed);
  }
  if (!response.ok) throw new Error(currentLabels().requestFailed);
  try {
    return await response.json();
  } catch {
    throw new Error(currentLabels().requestFailed);
  }
}

async function digest(bytes) {
  const hash = await crypto.subtle.digest('SHA-256', bytes);
  return Array.from(new Uint8Array(hash), value => value.toString(16).padStart(2, '0')).join('');
}

function snapshotIsUsable(snapshot) {
  if (!snapshot || !Number.isInteger(snapshot.version) || snapshot.version < 0) return false;
  if (!Array.isArray(snapshot.categories) || !Array.isArray(snapshot.products)) return false;
  if (!snapshot.assets || typeof snapshot.assets !== 'object' || Array.isArray(snapshot.assets)) return false;
  for (const [assetId, metadata] of Object.entries(snapshot.assets)) {
    if (!assetId || !metadata || typeof metadata !== 'object') return false;
    if (typeof metadata.url !== 'string' || !metadata.url) return false;
    if (!/^[0-9a-f]{64}$/i.test(metadata.sha256 || '')) return false;
  }
  for (const product of snapshot.products) {
    if (!product || typeof product !== 'object' || typeof product.asset_id !== 'string') return false;
    if (!Object.prototype.hasOwnProperty.call(snapshot.assets, product.asset_id)) return false;
  }
  return true;
}

function bytesToBase64(bytes) {
  let binary = '';
  // Avoid spreading a large image into one giant function call.
  for (let start = 0; start < bytes.length; start += 0x8000) {
    binary += String.fromCharCode(...bytes.subarray(start, start + 0x8000));
  }
  return btoa(binary);
}

function imageDataUrl(bytes, response) {
  const declared = (response.headers.get('Content-Type') || '').split(';', 1)[0].trim();
  const mime = declared && declared.startsWith('image/') ? declared : 'image/svg+xml';
  return `data:${mime};base64,${bytesToBase64(bytes)}`;
}

function sessionIsCurrent(mark, accessToken) {
  return mark === sessionEpoch && accessToken === token;
}

async function synchronize() {
  const mark = sessionEpoch;
  const accessToken = token;
  if (!accessToken) throw new Error(currentLabels().noSession);
  showStatus('synchronizing');

  const snapshot = await api('/snapshot', undefined, accessToken);
  if (!sessionIsCurrent(mark, accessToken)) return false;
  if (!snapshotIsUsable(snapshot)) throw new Error(currentLabels().failed);

  const images = Object.create(null);
  for (const [assetId, metadata] of Object.entries(snapshot.assets)) {
    if (!sessionIsCurrent(mark, accessToken)) return false;
    let assetUrl;
    try {
      assetUrl = new URL(metadata.url, window.location.href);
    } catch {
      throw new Error(currentLabels().failed);
    }
    // A catalogue image is fetched from this service, not from an arbitrary
    // URL embedded in content.  This also prevents bearer-token forwarding.
    if (assetUrl.origin !== window.location.origin) throw new Error(currentLabels().failed);
    let response;
    try {
      response = await fetch(assetUrl.href, {
        headers: { Authorization: `Bearer ${accessToken}` }
      });
    } catch {
      throw new Error(currentLabels().failed);
    }
    if (!response.ok) throw new Error(currentLabels().failed);
    const bytes = new Uint8Array(await response.arrayBuffer());
    const actualHash = await digest(bytes);
    if (actualHash.toLowerCase() !== metadata.sha256.toLowerCase()) {
      throw new Error(currentLabels().failed);
    }
    const checkedImage = new Image(); checkedImage.src = imageDataUrl(bytes, response); await checkedImage.decode(); images[assetId] = checkedImage.src;
  }

  if (!sessionIsCurrent(mark, accessToken)) return false;
  const candidate = {
    version: snapshot.version,
    categories: snapshot.categories,
    products: snapshot.products,
    assets: snapshot.assets,
    images
  };
  // This is the first persistent write.  All image responses and checksums
  // have succeeded, so an error before/at this write leaves the old bundle.
  try {
    localStorage.setItem('kiosk-content', JSON.stringify(candidate));
  } catch {
    throw new Error(currentLabels().failed);
  }
  if (!sessionIsCurrent(mark, accessToken)) return false;
  bundle = candidate;
  render();
  showStatus('synchronized', candidate.version);
  return true;
}

function eventId() {
  if (crypto.randomUUID) return crypto.randomUUID();
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function track() {
  if (!token) return;
  const target = view.page === 'product'
    ? ['product', view.product_id]
    : view.page === 'category'
      ? ['category', view.category_id]
      : ['page', 'home'];
  const accessToken = token;
  api('/track', {
    event_id: eventId(),
    target_type: target[0],
    target_id: target[1]
  }, accessToken).catch(() => {});
}

function sortedCategories() {
  return [...bundle.categories].sort((a, b) => a.order - b.order || String(a.id).localeCompare(String(b.id)));
}

function sortedProducts(categoryId) {
  return bundle.products
    .filter(product => product.category_id === categoryId)
    .sort((a, b) => a.order - b.order || String(a.id).localeCompare(String(b.id)));
}

function go(next) {
  history.push({ ...view });
  view = { ...next };
  render();
  track();
}

function render() {
  const lang = currentLanguage();
  const text = labels[lang];
  setLabels(lang);
  if (statusState) {
    q('#status').textContent = statusState.key
      ? statusMessage(statusState.key, statusState.argument, lang)
      : statusState.message;
  }
  q('#version').textContent = bundle && Number.isInteger(bundle.version)
    ? text.contentVersion(bundle.version)
    : text.noContent;
  q('#back').disabled = history.length === 0;
  q('#content').replaceChildren();

  if (!bundle || !Array.isArray(bundle.categories) || !Array.isArray(bundle.products)) {
    q('#heading').textContent = text.homeHeading;
    return;
  }

  const categories = sortedCategories();
  if (view.page !== 'home' && !categories.some(category => category.id === view.category_id)) {
    view = { page: 'home' };
    history = [];
    q('#back').disabled = true;
  }
  q('#heading').textContent = text.homeHeading;

  if (view.page === 'home') {
    for (const category of categories) {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'card category-card';
      button.textContent = category.text[lang];
      button.dataset.category = category.id;
      button.onclick = () => go({ page: 'category', category_id: category.id });
      q('#content').append(button);
    }
    return;
  }

  if (view.page === 'category') {
    const category = categories.find(item => item.id === view.category_id);
    if (!category) return;
    q('#heading').textContent = category.text[lang];
    for (const product of sortedProducts(category.id)) {
      const button = document.createElement('button');
      const image = document.createElement('img');
      const span = document.createElement('span');
      button.type = 'button';
      button.className = 'card product-card';
      button.dataset.product = product.id;
      image.alt = product.text[lang];
      image.src = bundle.images && bundle.images[product.asset_id] || '';
      span.textContent = product.text[lang];
      button.append(image, span);
      button.onclick = () => go({
        page: 'product',
        category_id: category.id,
        product_id: product.id
      });
      q('#content').append(button);
    }
    return;
  }

  const product = bundle.products.find(item =>
    item.id === view.product_id && item.category_id === view.category_id
  );
  if (!product || product.category_id !== view.category_id) {
    view = { page: 'category', category_id: view.category_id };
    return render();
  }
  q('#heading').textContent = product.text[lang];
  const image = document.createElement('img');
  image.className = 'detail';
  image.alt = product.text[lang];
  image.src = bundle.images && bundle.images[product.asset_id] || '';
  const description = document.createElement('p');
  description.className = 'product-text';
  description.textContent = product.text[lang];
  q('#content').append(image, description);
}

q('#back').onclick = () => {
  if (history.length) {
    view = history.pop();
    render();
    track();
  }
};

q('#logo').onclick = () => {
  if (view.page === 'product') {
    go({ page: 'category', category_id: view.category_id });
  } else if (view.page === 'category') {
    go({ page: 'home' });
  }
};

q('#language').onchange = () => render();
q('#sync').onclick = () => {
  const mark = sessionEpoch;
  synchronize().catch(() => {
    // A session change deliberately makes the old operation a no-op.
    if (mark === sessionEpoch) showStatus(token ? 'failed' : 'noSession');
  });
};

q('#connect').onsubmit = event => {
  event.preventDefault();
  // Incrementing before assigning the new token invalidates all old syncs,
  // including a sync that is currently waiting on an image response.
  sessionEpoch += 1;
  token = q('#token').value;
  q('#token').value = '';
  showStatus('connected');
};

q('#settings').onsubmit = async event => {
  event.preventDefault();
  try {
    await api('/settings', { device_id: q('#device').value });
    showStatus('settingsAcknowledged');
  } catch {
    showStatus('requestFailed');
  }
};

try {
  const stored = JSON.parse(localStorage.getItem('kiosk-content') || 'null');
  if (stored && typeof stored === 'object') bundle = stored;
} catch {
  bundle = null;
}
render();

if ('serviceWorker' in navigator) navigator.serviceWorker.register('/sw.js').catch(() => {});
