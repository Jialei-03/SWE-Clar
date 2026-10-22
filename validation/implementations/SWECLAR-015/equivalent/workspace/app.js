function keyFor(family) {
  return `${family.a}:${family.b}`;
}

function iterableKeys(value) {
  if (Array.isArray(value)) return value;
  if (value instanceof Set) return [...value];
  return [];
}

function formInteger(value) {
  const text = String(value).trim();
  // Keep decimal/exponent spellings as strings so the service's strict JSON
  // integer validation rejects them instead of silently rounding/coercing.
  return /^-?\d+$/.test(text) ? Number(text) : text;
}

/**
 * Return the shared-scale data used by the canvas renderer.
 * All selected families use one pair of maxima; the lower bounds are always
 * zero so that raw and normalized views can be compared without per-family
 * rescaling.
 */
export function project(result, selectedKeys) {
  const selected = new Set(iterableKeys(selectedKeys));
  const points = [];
  let xMax = 1;
  let yMax = 1;
  const families = Array.isArray(result?.families) ? result.families : [];

  for (const family of families) {
    const familyKey = keyFor(family);
    if (!selected.has(familyKey)) continue;
    const lines = Array.isArray(family.lines) ? family.lines : [];
    for (const line of lines) {
      const linePoints = Array.isArray(line.points) ? line.points : [];
      for (const point of linePoints) {
        const u = point[0];
        const v = point[1];
        points.push({family_key: familyKey, n: line.n, u, v});
        xMax = Math.max(xMax, u);
        yMax = Math.max(yMax, v);
      }
    }
  }

  return {
    bounds: {x_min: 0, x_max: xMax, y_min: 0, y_max: yMax},
    points: points.map(point => ({
      ...point,
      px: 48 + 624 * point.u / xMax,
      py: 432 - 384 * point.v / yMax,
    })),
  };
}

export class ExplorerClient {
  constructor() {
    this.result = null;
    this.selectedKeys = [];
    this.error = null;
    this.serial = 0;
    this.disposed = false;
    this.listeners = new Set();
  }

  emit() {
    // A copy makes listener removal during a render safe and keeps the public
    // listener mechanism independent of request ordering.
    for (const listener of [...this.listeners]) listener();
  }

  async run(problem) {
    if (this.disposed) return;
    const requestSerial = ++this.serial;
    let response;
    let payload;

    try {
      response = await fetch('/api/geometry', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(problem),
      });
      payload = await response.json();
      if (!response.ok) {
        const detail = payload && typeof payload.error === 'string'
          ? payload.error
          : `Request failed (${response.status})`;
        throw new Error(detail);
      }
      if (!payload || typeof payload !== 'object' ||
          !Array.isArray(payload.families)) {
        throw new Error('Invalid geometry response');
      }
    } catch (error) {
      // An older failure is just as stale as an older success.  In particular,
      // it must not clear the last accepted result or its selection.
      if (this.disposed || requestSerial !== this.serial) return;
      this.error = error && error.message ? error.message : 'Request failed';
      this.emit();
      return;
    }

    if (this.disposed || requestSerial !== this.serial) return;
    const families = Array.isArray(payload?.families) ? payload.families : [];
    this.result = payload;
    this.selectedKeys = families.map(keyFor);
    this.error = null;
    this.emit();
  }

  select(familyKeys) {
    if (this.disposed || !this.result || !Array.isArray(this.result.families)) return;
    const wanted = new Set(iterableKeys(familyKeys));
    // Use the result's canonical family order.  This keeps the observable
    // selection stable while still ignoring unknown and duplicate keys.
    this.selectedKeys = this.result.families
      .map(keyFor)
      .filter(key => wanted.has(key));
    this.emit();
  }

  exportCSV() {
    if (!this.result || !Array.isArray(this.result.families)) return null;
    const selected = new Set(this.selectedKeys);
    const rows = ['a,b,n,u,v'];

    // The result itself is ordered by b, n, then original x.  Iterating it
    // directly preserves that order without trying to reconstruct x from a
    // transformed coordinate.
    for (const family of this.result.families) {
      if (!selected.has(keyFor(family))) continue;
      for (const line of Array.isArray(family.lines) ? family.lines : []) {
        for (const point of Array.isArray(line.points) ? line.points : []) {
          rows.push([family.a, family.b, line.n, point[0], point[1]].join(','));
        }
      }
    }
    return `${rows.join('\n')}\n`;
  }

  dispose() {
    this.disposed = true;
    this.serial++;
    this.listeners.clear();
  }
}

export class ExplorerView {
  constructor(client, doc) {
    this.client = client;
    this.doc = doc;
    this.cleanups = [];
    this.el = id => doc.getElementById(id);

    this.listen(this.el('problem-form'), 'submit', event => {
      event.preventDefault();
      client.run({
        total: formInteger(this.el('total').value),
        limit: formInteger(this.el('limit').value),
        family_policy: this.el('family-policy').value,
        coordinates: this.el('coordinates').value,
      });
    });
    this.listen(this.el('family-list'), 'change', event => {
      const target = event.target;
      if (!target || !target.matches ||
          !target.matches('input[type="checkbox"][data-family-key]')) return;
      const keys = [...this.el('family-list').querySelectorAll(
        'input[type="checkbox"][data-family-key]:checked'
      )].map(node => node.dataset.familyKey);
      client.select(keys);
    });
    this.listen(this.el('export'), 'click', () => {
      const csv = client.exportCSV();
      if (csv === null) return;
      const view = this.doc.defaultView || globalThis;
      const urlApi = view.URL || globalThis.URL;
      const blob = new Blob([csv], {type: 'text/csv;charset=utf-8'});
      const url = urlApi.createObjectURL(blob);
      const link = this.doc.createElement('a');
      link.href = url;
      link.download = 'lattice.csv';
      this.doc.body.append(link);
      link.click();
      link.remove();
      view.setTimeout(() => urlApi.revokeObjectURL(url), 1000);
    });

    this.update = () => this.render();
    client.listeners.add(this.update);
    this.render();
  }

  listen(target, event, handler) {
    target.addEventListener(event, handler);
    this.cleanups.push(() => target.removeEventListener(event, handler));
  }

  render() {
    const client = this.client;
    const projected = project(client.result, client.selectedKeys);
    const error = this.el('error');
    const summary = this.el('result-summary');
    const exportButton = this.el('export');

    error.hidden = !client.error;
    error.textContent = client.error || '';
    exportButton.disabled = client.result === null;
    summary.dataset.pointCount = String(projected.points.length);
    summary.textContent = client.result === null
      ? 'Run a problem to explore its geometry.'
      : `${projected.points.length} selected lattice points`;

    const list = this.el('family-list');
    list.replaceChildren();
    const selected = new Set(client.selectedKeys);
    for (const family of Array.isArray(client.result?.families)
      ? client.result.families : []) {
      const row = this.doc.createElement('label');
      row.className = 'family-row';
      const box = this.doc.createElement('input');
      box.type = 'checkbox';
      box.dataset.familyKey = keyFor(family);
      box.checked = selected.has(box.dataset.familyKey);
      const text = this.doc.createElement('span');
      text.textContent = `a=${family.a}, b=${family.b} · ${family.point_count} points`;
      row.append(box, text);
      list.append(row);
    }

    const canvas = this.el('plot');
    canvas.width = 720;
    canvas.height = 480;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    ctx.clearRect(0, 0, 720, 480);
    ctx.fillStyle = '#fbfcf9';
    ctx.fillRect(0, 0, 720, 480);

    // The public data viewport is deliberately fixed even though the canvas
    // itself scales responsively in CSS.
    ctx.strokeStyle = '#6e7771';
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(48, 48);
    ctx.lineTo(48, 432);
    ctx.lineTo(672, 432);
    ctx.stroke();

    ctx.strokeStyle = '#dbe3dc';
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(48, 48);
    ctx.lineTo(672, 48);
    ctx.moveTo(672, 48);
    ctx.lineTo(672, 432);
    ctx.stroke();

    const formatBound = value => Number.isInteger(value) ? String(value) : value.toFixed(2);
    ctx.font = '13px sans-serif';
    ctx.fillStyle = '#465048';
    ctx.fillText('0', 30, 450);
    ctx.fillText(formatBound(projected.bounds.x_max), 638, 450);
    ctx.fillText(formatBound(projected.bounds.y_max), 4, 44);
    ctx.fillText('u', 676, 450);
    ctx.fillText('v', 31, 40);

    const familyKeys = (Array.isArray(client.result?.families)
      ? client.result.families : []).map(keyFor);
    for (const point of projected.points) {
      const familyIndex = Math.max(0, familyKeys.indexOf(point.family_key));
      const hue = (familyIndex * 137 + 205) % 360;
      ctx.fillStyle = `hsla(${hue}, 65%, 38%, 0.78)`;
      ctx.strokeStyle = `hsl(${hue}, 70%, 25%)`;
      ctx.lineWidth = 1;
      const radius = 4;
      ctx.beginPath();
      if (familyIndex % 3 === 1) {
        ctx.rect(point.px - radius, point.py - radius, radius * 2, radius * 2);
      } else if (familyIndex % 3 === 2) {
        ctx.moveTo(point.px, point.py - radius - 1);
        ctx.lineTo(point.px + radius + 1, point.py + radius);
        ctx.lineTo(point.px - radius - 1, point.py + radius);
        ctx.closePath();
      } else {
        ctx.arc(point.px, point.py, radius, 0, Math.PI * 2);
      }
      ctx.fill();
      ctx.stroke();
    }
  }

  dispose() {
    this.client.listeners.delete(this.update);
    for (const cleanup of this.cleanups) cleanup();
    this.cleanups = [];
  }
}

// The module exports are the public interface.  These aliases are harmless for
// the real page and also make the developer interface easy to inspect in a
// browser console without replacing the module exports.
if (typeof window !== 'undefined') {
  window.ExplorerClient = ExplorerClient;
  window.ExplorerView = ExplorerView;
  window.project = project;
}

if (typeof document !== 'undefined' && document.getElementById('problem-form')) {
  const client = new ExplorerClient();
  const view = new ExplorerView(client, document);
  window.addEventListener('pagehide', () => {
    view.dispose();
    client.dispose();
  });
}
