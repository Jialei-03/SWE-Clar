const q = (selector) => document.querySelector(selector);

let viewer = null;
let marker = null;
let selectedPoint = null;
let trackRecords = [];
let epoch = 0;

async function request(path, body) {
  const options = {
    method: body === undefined ? 'GET' : 'POST',
    credentials: 'same-origin',
  };
  if (body !== undefined) {
    options.headers = { 'Content-Type': 'application/json' };
    options.body = JSON.stringify(body);
  }
  const response = await fetch(path, options);
  if (!response.ok) {
    if (response.status === 404) throw Error('No sample found.');
    if (response.status === 403) throw Error('Please check your session or input.');
    throw Error('The local request could not be completed.');
  }
  return response.json();
}

function centerSelectedPoint() {
  if (!viewer || !selectedPoint) return;
  viewer.camera.setView({
    // The camera is placed directly above the selected coordinate.  No
    // longitude/state offset is used to compensate for the side panels.
    destination: Cesium.Cartesian3.fromDegrees(
      selectedPoint.longitude,
      selectedPoint.latitude,
      selectedPoint.height,
    ),
    orientation: {
      heading: 0,
      pitch: -Cesium.Math.PI_OVER_TWO,
      roll: 0,
    },
  });
  viewer.scene.requestRender();
}

function resizeMap() {
  if (!viewer) return;
  const focus = selectedPoint && { ...selectedPoint };
  viewer.resize();
  // A canvas resize changes the viewport, not the geographic target.  Set the
  // camera back to the same world coordinate after Cesium has resized it.
  if (focus) {
    selectedPoint = focus;
    centerSelectedPoint();
  } else {
    viewer.scene.requestRender();
  }
}

function createViewer() {
  if (viewer) return;

  // The viewer is deliberately configured with no imagery or online terrain.
  // The ellipsoid, local grid entities and selected points are real Cesium
  // scene geometry, rather than a state flag standing in for a map.
  if (Cesium.Ion) Cesium.Ion.defaultAccessToken = undefined;
  viewer = new Cesium.Viewer('map', {
    baseLayer: false,
    terrainProvider: new Cesium.EllipsoidTerrainProvider(),
    geocoder: false,
    baseLayerPicker: false,
    animation: false,
    timeline: false,
    homeButton: false,
    sceneModePicker: false,
    navigationHelpButton: false,
    fullscreenButton: false,
    infoBox: false,
    selectionIndicator: false,
    skyBox: false,
    skyAtmosphere: false,
    scene3DOnly: true,
  });
  viewer.scene.globe.baseColor = Cesium.Color.fromCssColorString('#d4e0dc');
  viewer.scene.globe.show = true;
  viewer.scene.backgroundColor = Cesium.Color.fromCssColorString('#253b4c');

  // A small local reference grid makes the synthetic ellipsoid visible while
  // keeping the reconstruction independent of map imagery or tile services.
  for (let step = -2; step <= 2; step += 1) {
    const coordinate = step * 0.05;
    for (const coordinates of [
      [-0.12, coordinate, 0.12, coordinate],
      [coordinate, -0.12, coordinate, 0.12],
    ]) {
      viewer.entities.add({
        polyline: {
          positions: Cesium.Cartesian3.fromDegreesArray(coordinates),
          width: 1,
          material: Cesium.Color.fromCssColorString('#8faaa0'),
        },
      });
    }
  }
  viewer.camera.setView({
    destination: Cesium.Cartesian3.fromDegrees(0, 0, 9000000),
    orientation: {
      heading: 0,
      pitch: -Cesium.Math.PI_OVER_TWO,
      roll: 0,
    },
  });

  const map = q('#map');
  if (window.ResizeObserver) {
    new ResizeObserver(resizeMap).observe(map);
  }
  window.addEventListener('resize', resizeMap, { passive: true });
}

function displayPoint(point) {
  const location = Cesium.Cartesian3.fromDegrees(point.longitude, point.latitude);
  if (marker) viewer.entities.remove(marker);
  marker = viewer.entities.add({
    id: 'selected-sample',
    position: location,
    point: {
      pixelSize: 14,
      color: Cesium.Color.fromCssColorString('#e29551'),
      outlineColor: Cesium.Color.WHITE,
      outlineWidth: 2,
      disableDepthTestDistance: Number.POSITIVE_INFINITY,
    },
  });
  selectedPoint = {
    longitude: point.longitude,
    latitude: point.latitude,
    height: 20000,
  };
  centerSelectedPoint();
}

function clearDisplayedPoint() {
  if (marker && viewer) viewer.entities.remove(marker);
  marker = null;
  selectedPoint = null;
}

function allocatePanelSpace() {
  const workspace = q('#workspace');
  const panels = [
    ['#main-panel', '--left'],
    ['#camera-panel', '--right'],
  ];
  for (const [selector, variable] of panels) {
    const panel = q(selector);
    // Keep a compact, fixed reservation for an open drawer rather than
    // letting the grid use the drawer's actual rendered width.
    const measured = panel.hidden ? 0 : 280;
    workspace.style.setProperty(variable, `${measured}px`);
  }
  resizeMap();
}

function schedulePanelLayout() {
  // The browser must lay out an opened panel before its actual width can be
  // allocated to the grid.  A second frame also covers font/layout changes.
  requestAnimationFrame(allocatePanelSpace);
  requestAnimationFrame(() => requestAnimationFrame(allocatePanelSpace));
}

function setPanel(button, panel, open) {
  panel.hidden = !open;
  button.setAttribute('aria-expanded', String(open));
  // Allocate once synchronously for callers that inspect the layout directly,
  // then repeat after the browser has completed its normal layout pass.
  allocatePanelSpace();
  schedulePanelLayout();
}

const panelControls = [
  ['#main-toggle', '#main-panel'],
  ['#camera-toggle', '#camera-panel'],
];
for (const [buttonSelector, panelSelector] of panelControls) {
  const button = q(buttonSelector);
  const panel = q(panelSelector);
  button.addEventListener('click', () => setPanel(button, panel, panel.hidden));
}

function showTrackInfo(track) {
  q('#track-info').textContent = track
    ? `${track.name} · ${track.description}`
    : '';
}

function selectedTrack() {
  const id = q('#track').value;
  return trackRecords.find((track) => track.id === id) || null;
}

q('#track').addEventListener('change', () => {
  epoch += 1;
  clearDisplayedPoint();
  q('#metadata').textContent = '';
  const track = selectedTrack();
  showTrackInfo(track);
  q('#status').textContent = track ? 'Track selected.' : '';
});

async function enter(user) {
  const mark = ++epoch;
  q('#login-panel').hidden = true;
  q('#console').hidden = false;
  q('#user').textContent = user.name;
  createViewer();

  const tracks = await request('/tracks');
  if (mark !== epoch) return;
  trackRecords = tracks;
  const select = q('#track');
  select.replaceChildren();
  for (const track of tracks) {
    const option = document.createElement('option');
    option.value = track.id;
    option.textContent = track.name;
    select.append(option);
  }
  showTrackInfo(tracks[0] || null);
  q('#status').textContent = 'Local console ready.';
  allocatePanelSpace();
}

q('#login').addEventListener('submit', async (event) => {
  event.preventDefault();
  const mark = ++epoch;
  q('#login-error').textContent = '';
  try {
    const user = await request('/login', {
      username: q('#username').value,
      password: q('#password').value,
    });
    q('#password').value = '';
    if (mark !== epoch) return;
    await enter(user);
  } catch (error) {
    if (mark === epoch) q('#login-error').textContent = error.message;
  }
});

q('#logout').addEventListener('click', async () => {
  epoch += 1;
  try {
    await request('/logout', {});
  } finally {
    q('#console').hidden = true;
    q('#login-panel').hidden = false;
    q('#results').replaceChildren();
    q('#metadata').textContent = '';
    q('#track-info').textContent = '';
    q('#login-error').textContent = '';
    q('#status').textContent = '';
    q('#track').replaceChildren();
    trackRecords = [];
    clearDisplayedPoint();
    for (const [buttonSelector, panelSelector] of panelControls) {
      const button = q(buttonSelector);
      const panel = q(panelSelector);
      setPanel(button, panel, false);
    }
  }
});

q('#search').addEventListener('submit', async (event) => {
  event.preventDefault();
  const mark = epoch;
  try {
    const rows = await request(
      `/locations?q=${encodeURIComponent(q('#query').value)}`,
    );
    if (mark !== epoch) return;
    q('#results').replaceChildren();
    for (const row of rows) {
      const button = document.createElement('button');
      button.type = 'button';
      button.textContent = row.name;
      button.dataset.location = row.id;
      button.addEventListener('click', () => {
        if (mark !== epoch) return;
        clearDisplayedPoint();
        q('#metadata').textContent = '';
        displayPoint(row);
        q('#status').textContent = `Selected ${row.name}`;
      });
      q('#results').append(button);
    }
    q('#status').textContent = rows.length
      ? 'Choose a local result.'
      : 'No local locations found.';
  } catch (error) {
    if (mark === epoch) q('#status').textContent = error.message;
  }
});

function timezoneAwareInput(value) {
  // datetime-local is explicitly labelled UTC in this console.  Preserve an
  // offset if a caller supplies one while making the normal UI value aware.
  return /(?:Z|z|[+-]\d{2}:?\d{2})$/.test(value) ? value : `${value}Z`;
}

q('#rewind').addEventListener('submit', async (event) => {
  event.preventDefault();
  const mark = epoch;
  try {
    const result = await request(
      `/rewind?id=${encodeURIComponent(q('#track').value)}&at=${encodeURIComponent(
        timezoneAwareInput(q('#at').value),
      )}`,
    );
    if (mark !== epoch) return;
    displayPoint(result.sample);
    q('#track-info').textContent = `${result.name} · ${result.description}`;
    q('#metadata').textContent =
      `${result.name} · ${result.description} · ${result.sample.time}`;
    q('#status').textContent = 'Sample displayed.';
  } catch (error) {
    if (mark !== epoch) return;
    clearDisplayedPoint();
    q('#metadata').textContent = '';
    q('#status').textContent = error.message;
  }
});

const initialEpoch = epoch;
request('/me')
  .then((user) => {
    if (epoch === initialEpoch) return enter(user);
    return undefined;
  })
  .catch(() => undefined);
