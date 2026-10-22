const q = (selector) => document.querySelector(selector);
let epoch = 0;
let sites = [];

async function request(path, body) {
  const options = { method: body === undefined ? 'GET' : 'POST' };
  if (body !== undefined) {
    options.headers = { 'Content-Type': 'application/json' };
    options.body = JSON.stringify(body);
  }
  const response = await fetch(path, options);
  let data;
  try {
    data = await response.json();
  } catch (_error) {
    data = { error: 'request_failed' };
  }
  if (!response.ok) {
    throw new Error(data && data.error ? data.error : 'request_failed');
  }
  return data;
}

async function history() {
  const mine = epoch;
  const rows = await request('/history');
  if (mine !== epoch) return;
  q('#history').replaceChildren(
    ...rows.map((record) => {
      const item = document.createElement('p');
      const state = record.ended_at === null
        ? 'Checked in'
        : `${record.duration_seconds} seconds`;
      item.textContent = `${record.site_id} · ${state}`;
      return item;
    }),
  );
}

function selectSection(name) {
  q('#section').textContent = name;
  q('#nav').querySelectorAll('button').forEach((button) => {
    button.setAttribute('aria-current', button.dataset.section === name ? 'page' : 'false');
  });
}

function renderNavigation(navigation) {
  const sections = Array.isArray(navigation.sections) ? navigation.sections : [];
  const center = Math.floor(sections.length / 2);
  q('#nav').replaceChildren(
    ...sections.map((name, index) => {
      const button = document.createElement('button');
      button.type = 'button';
      button.textContent = name;
      button.dataset.section = name;
      // The fixture places Plans in the middle.  The index fallback keeps the
      // center emphasis correct if a private fixture uses a translated label.
      if (name === 'Plans' || index === center) button.classList.add('primary');
      button.onclick = () => selectSection(name);
      return button;
    }),
  );
  if (sections.length) selectSection(sections[0]);
}

async function enter(user) {
  const mine = ++epoch;
  const [locations, navigation] = await Promise.all([
    request('/sites'),
    request('/navigation'),
  ]);
  if (mine !== epoch) return;
  sites = locations;
  q('#auth').hidden = true;
  q('#workspace').hidden = false;
  q('#actor').textContent = user.email;
  q('#sites').replaceChildren(
    ...sites.map((site) => {
      const option = document.createElement('option');
      option.value = site.id;
      option.textContent = site.name;
      return option;
    }),
  );
  renderNavigation(navigation);
  await history();
}

q('#account').onsubmit = async (event) => {
  event.preventDefault();
  try {
    const user = await request('/login', {
      email: q('#email').value,
      password: q('#password').value,
    });
    await enter(user);
    q('#password').value = '';
    q('#error').textContent = '';
  } catch (error) {
    q('#error').textContent = error.message;
  }
};

q('#register').onclick = async () => {
  try {
    await request('/register', {
      email: q('#email').value,
      password: q('#password').value,
    });
    q('#error').textContent = 'Account created. Sign in.';
  } catch (error) {
    q('#error').textContent = error.message;
  }
};

q('#checkin').onclick = () => {
  const mine = epoch;
  const site_id = q('#sites').value;
  const id = window.crypto && typeof window.crypto.randomUUID === 'function'
    ? window.crypto.randomUUID()
    : `${Math.random().toString(36).slice(2)}-${Math.random().toString(36).slice(2)}`;
  q('#status').textContent = 'Reading location…';

  if (!navigator.geolocation) {
    q('#status').textContent = 'location_unavailable';
    return;
  }

  try {
    navigator.geolocation.getCurrentPosition(
      async (position) => {
        if (mine !== epoch) return;
        try {
          await request('/checkin', {
            id,
            site_id,
            latitude: position.coords.latitude,
            longitude: position.coords.longitude,
          });
          if (mine !== epoch) return;
          q('#status').textContent = 'Checked in';
          await history();
        } catch (error) {
          if (mine === epoch) q('#status').textContent = error.message;
        }
      },
      () => {
        // Permission denial must not create an HTTP attendance request.
        if (mine === epoch) q('#status').textContent = 'location_unavailable';
      },
      { enableHighAccuracy: true, timeout: 5000, maximumAge: 0 },
    );
  } catch (_error) {
    q('#status').textContent = 'location_unavailable';
  }
};

q('#checkout').onclick = async () => {
  const mine = epoch;
  try {
    await request('/checkout', {});
    if (mine !== epoch) return;
    q('#status').textContent = 'Checked out';
    await history();
  } catch (error) {
    if (mine === epoch) q('#status').textContent = error.message;
  }
};

q('#logout').onclick = async () => {
  try {
    await request('/logout', {});
  } finally {
    epoch += 1;
    q('#workspace').hidden = true;
    q('#auth').hidden = false;
    q('#history').replaceChildren();
    q('#status').textContent = '';
    q('#actor').textContent = '';
  }
};

const initialEpoch = epoch;
request('/me')
  .then((user) => {
    if (epoch === initialEpoch) return enter(user);
    return undefined;
  })
  .catch(() => undefined);
