export function project(result, selectedKeys) {
  const selected = new Set(selectedKeys), points = [];
  let xMax = 1, yMax = 1;
  for (const family of result?.families || []) {
    const key = `${family.a}:${family.b}`;
    if (!selected.has(key)) continue;
    for (const line of family.lines) for (const [u, v] of line.points) {
      points.push({family_key: key, n: line.n, u, v});
      xMax = Math.max(xMax, u); yMax = Math.max(yMax, v);
    }
  }
  return {bounds: {x_min: 0, x_max: xMax, y_min: 0, y_max: yMax},
    points: points.map(point => ({...point, px: 48 + 624 * point.u / xMax, py: 432 - 384 * point.v / yMax}))};
}

export class ExplorerClient {
  constructor() {
    this.result = null; this.selectedKeys = []; this.error = null;
    this.serial = 0; this.disposed = false; this.listeners = new Set();
  }
  emit() { for (const listener of this.listeners) listener(); }
  async run(problem) {
    if (this.disposed) return;
    const serial = ++this.serial;
    try {
      const response = await fetch('/api/geometry', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(problem)});
      const result = await response.json();
      if (!response.ok) throw new Error('Invalid problem. Check the input ranges and options.');
      if (this.disposed) return;
      this.result = result;
      this.selectedKeys = result.families.map(family => `${family.a}:${family.b}`);
      this.error = null; this.emit();
    } catch (error) {
      if (this.disposed) return;
      this.result = null; this.selectedKeys = []; this.error = error.message || 'Request failed'; this.emit();
    }
  }
  select(keys) {
    // TODO: implement comparison selection after clarification.
  }
  exportCSV() {
    // TODO: implement export of the accepted selection.
    return null;
  }
  dispose() { this.disposed = true; this.serial++; this.listeners.clear(); }
}

export class ExplorerView {
  constructor(client, doc) {
    this.client = client; this.doc = doc; this.cleanups = [];
    this.el = id => doc.getElementById(id);
    this.listen(this.el('problem-form'), 'submit', event => {
      event.preventDefault();
      client.run({total: Number(this.el('total').value), limit: Number(this.el('limit').value),
        family_policy: this.el('family-policy').value, coordinates: this.el('coordinates').value});
    });
    this.listen(this.el('export'), 'click', () => {
      const csv = client.exportCSV(); if (csv === null) return;
      const url = URL.createObjectURL(new Blob([csv], {type: 'text/csv;charset=utf-8'}));
      const link = doc.createElement('a'); link.href = url; link.download = 'lattice.csv';
      doc.body.append(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000);
    });
    this.update = () => this.render(); client.listeners.add(this.update); this.render();
  }
  listen(target, event, handler) { target.addEventListener(event, handler); this.cleanups.push(() => target.removeEventListener(event, handler)); }
  render() {
    const c = this.client, projected = project(c.result, c.selectedKeys);
    this.el('error').hidden = !c.error; this.el('error').textContent = c.error || '';
    this.el('export').disabled = c.result === null;
    this.el('result-summary').dataset.pointCount = String(projected.points.length);
    this.el('result-summary').textContent = c.result ? `${projected.points.length} selected lattice points` : 'Run a problem to explore its geometry.';
    this.el('family-list').replaceChildren(...(c.result?.families || []).map(f => {
      const label = this.doc.createElement('label'), box = this.doc.createElement('input');
      box.type = 'checkbox'; box.dataset.familyKey = `${f.a}:${f.b}`; box.checked = c.selectedKeys.includes(box.dataset.familyKey);
      box.addEventListener('change', () => c.select([...this.doc.querySelectorAll('[data-family-key]:checked')].map(node => node.dataset.familyKey)));
      label.append(box, this.doc.createTextNode(`a=${f.a}, b=${f.b} · ${f.point_count} points`)); return label;
    }));
    const canvas = this.el('plot'), ctx = canvas.getContext('2d'); canvas.width = 720; canvas.height = 480;
    ctx.fillStyle = '#fbfcf9'; ctx.fillRect(0, 0, 720, 480);
    ctx.strokeStyle = '#6e7771'; ctx.lineWidth = 1; ctx.beginPath(); ctx.moveTo(48, 48); ctx.lineTo(48, 432); ctx.lineTo(672, 432); ctx.stroke();
    ctx.font = '13px sans-serif'; ctx.fillStyle = '#465048'; ctx.fillText('0', 30, 450);
    ctx.fillText(projected.bounds.x_max.toFixed(2), 638, 450); ctx.fillText(projected.bounds.y_max.toFixed(2), 4, 44);
    const families = (c.result?.families || []).map(f => `${f.a}:${f.b}`);
    for (const point of projected.points) {
      ctx.fillStyle = `hsl(${(families.indexOf(point.family_key) * 137 + 205) % 360} 65% 38%)`;
      ctx.beginPath(); ctx.arc(point.px, point.py, 2.5, 0, Math.PI * 2); ctx.fill();
    }
  }
  dispose() { this.client.listeners.delete(this.update); for (const cleanup of this.cleanups) cleanup(); }
}

if (typeof document !== 'undefined' && document.getElementById('problem-form')) {
  const client = new ExplorerClient(), view = new ExplorerView(client, document);
  window.addEventListener('pagehide', () => { view.dispose(); client.dispose(); });
}
