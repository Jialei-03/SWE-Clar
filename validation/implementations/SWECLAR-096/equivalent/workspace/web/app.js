const form = document.getElementById('calculator');
const results = document.getElementById('results');
const error = document.getElementById('error');
const summary = document.getElementById('summary');
const download = document.getElementById('download');
const reset = document.getElementById('reset');

let savedValues = null;
let generation = 0;

const labels = {
  land_area_sqm: 'Land area in square metres',
  site_area_sqm: 'Site area in square metres',
  gross_floor_area_sqft: 'Gross floor area in square feet',
};

function setReportAccess(enabled) {
  download.disabled = !enabled;
}

function clearResults(message = '') {
  savedValues = null;
  results.hidden = true;
  summary.replaceChildren();
  setReportAccess(false);
  error.textContent = message;
}

// Editing an input invalidates the displayed calculation.  The next
// successful response is the only thing that can re-enable report download.
form.addEventListener('input', () => {
  generation += 1;
  clearResults();
});

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  const currentGeneration = ++generation;
  clearResults();

  try {
    const values = Object.fromEntries(
      [...new FormData(form)].map(([key, value]) => [key, Number(value)]),
    );
    const response = await fetch('/calculate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(values),
    });
    const data = await response.json();

    if (currentGeneration !== generation) return;
    if (!response.ok) throw new Error(data.error || 'invalid_input');

    savedValues = { ...data.inputs };
    summary.replaceChildren();
    for (const [key, value] of Object.entries(data.summary)) {
      const term = document.createElement('dt');
      const definition = document.createElement('dd');
      term.textContent = labels[key] || key;
      definition.dataset.field = key;
      definition.textContent = Number(value).toFixed(2);
      summary.append(term, definition);
    }
    results.hidden = false;
    setReportAccess(true);
    error.textContent = '';
  } catch (_error) {
    if (currentGeneration !== generation) return;
    clearResults('Please check the input values');
  }
});

reset.addEventListener('click', () => {
  if (!window.confirm('Clear all inputs and results?')) return;

  generation += 1;
  HTMLFormElement.prototype.reset.call(form);
  clearResults('Values cleared');
});

download.addEventListener('click', async () => {
  if (!savedValues || download.disabled) return;

  const currentGeneration = generation;
  try {
    const response = await fetch('/report', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(savedValues),
    });
    if (!response.ok) throw new Error('report failed');

    const blob = await response.blob();
    if (currentGeneration !== generation || !savedValues) return;

    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = 'area-report.pdf';
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  } catch (_error) {
    if (currentGeneration === generation) error.textContent = 'Unable to generate report';
  }
});
