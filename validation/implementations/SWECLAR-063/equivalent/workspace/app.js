const q = selector => document.querySelector(selector);
let token = '';
let epoch = 0;
let map = null;
let pins = null;
let urls = [];

async function api(path, body, access = token) {
  const response = await fetch(path, {
    method: body ? 'POST' : 'GET',
    headers: {
      Authorization: 'Bearer ' + access,
      'Content-Type': 'application/json'
    },
    body: body ? JSON.stringify(body) : undefined
  });
  if (!response.ok) throw Error('Please check your request.');
  return response.json();
}

function clear() {
  urls.forEach(URL.revokeObjectURL);
  urls = [];
  q('#feed').replaceChildren();
  if (pins) pins.clearLayers();
}

function showVenue(place) {
  const details = document.createElement('p');
  details.textContent = place.name + ' · ' + place.address;
  return details;
}

async function reload() {
  const mark = ++epoch;
  const access = token;
  const mode = q('#mode').value;
  const [rows, places, points] = await Promise.all([
    api('/feed', null, access),
    api('/venues', null, access),
    api('/pins?mode=' + encodeURIComponent(mode), null, access)
  ]);
  // A token change or a newer mode/feed load owns the page now.  In
  // particular, do not let old image requests repopulate the feed.
  if (mark !== epoch) return false;

  clear();
  q('#venue').replaceChildren();
  for (const [id, place] of Object.entries(places)) {
    const option = document.createElement('option');
    option.value = id;
    option.textContent = place.name;
    q('#venue').append(option);
  }

  for (const row of rows) {
    const card = document.createElement('article');
    const heading = document.createElement('h2');
    const caption = document.createElement('p');
    const place = showVenue(row.venue);
    const image = document.createElement('img');
    card.dataset.post = row.id;
    heading.textContent = row.food;
    caption.textContent = row.caption;
    image.alt = row.food;
    card.append(image, heading, caption, place);

    if (row.can_save) {
      const button = document.createElement('button');
      button.type = 'button';
      button.textContent = row.saved ? 'Unsave' : 'Save';
      button.onclick = async () => {
        const requestEpoch = epoch;
        try {
          await api('/save', {
            post_id: row.id,
            saved: !row.saved
          }, access);
          if (requestEpoch === epoch) await reload();
        } catch (error) {
          if (requestEpoch === epoch) q('#status').textContent = error.message;
        }
      };
      card.append(button);
    }
    q('#feed').append(card);

    fetch(row.image_url, { headers: { Authorization: 'Bearer ' + access } })
      .then(async response => {
        if (!response.ok) throw Error('Image unavailable.');
        return response.blob();
      })
      .then(blob => {
        if (mark !== epoch) return;
        const url = URL.createObjectURL(blob);
        urls.push(url);
        image.src = url;
      })
      .catch(error => {
        if (mark === epoch) q('#status').textContent = error.message;
      });
  }

  if (!map) {
    map = L.map('map', {
      zoomAnimation: false,
      fadeAnimation: false
    }).setView([0, 0], 15);
    pins = L.featureGroup().addTo(map);
    new ResizeObserver(() => {
      map.invalidateSize();
      if (pins.getLayers().length) {
        map.fitBounds(pins.getBounds(), {
          padding: [30, 30],
          maxZoom: 17,
          animate: false
        });
      }
    }).observe(q('#map'));
  }

  for (const point of points) {
    const tooltip = document.createElement('span');
    tooltip.textContent = point.food + ' · ' + point.name;
    L.circleMarker([point.latitude, point.longitude], {
      radius: 9,
      color: '#88582a', renderer: L.canvas()
    }).bindTooltip(tooltip).addTo(pins);
  }
  if (points.length) {
    map.fitBounds(pins.getBounds(), {
      padding: [30, 30],
      maxZoom: 17,
      animate: false
    });
  }
  q('#status').textContent = 'Loaded.';
  return true;
}

q('#connect').onsubmit = event => {
  event.preventDefault();
  epoch++;
  clear();
  token = q('#token').value;
  q('#token').value = '';
  reload().catch(error => {
    // Only the load associated with the current access session may report a
    // request failure after a later connection has started.
    if (token) q('#status').textContent = error.message;
  });
};

q('#mode').onchange = () => {
  reload().catch(error => q('#status').textContent = error.message);
};

q('#post').onsubmit = async event => {
  event.preventDefault();
  const requestEpoch = epoch;
  const access = token;
  try {
    const file = q('#photo').files[0];
    if (!file) throw Error('Choose a photo.');
    const data = await new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result.split(',')[1]);
      reader.onerror = reject;
      reader.readAsDataURL(file);
    });
    const image = await api('/upload', { data }, access);
    if (requestEpoch !== epoch) return;
    await api('/post', {
      post_id: crypto.randomUUID(),
      image_id: image.image_id,
      food: q('#food').value,
      caption: q('#caption').value,
      venue_id: q('#venue').value
    }, access);
    if (requestEpoch !== epoch) return;
    const displayed = await reload();
    if (displayed && access === token) q('#status').textContent = 'Post saved.';
  } catch (error) {
    if (requestEpoch === epoch) q('#status').textContent = error.message;
  }
};
