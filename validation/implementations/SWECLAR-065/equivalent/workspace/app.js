const h = React.createElement;

const sections = ['patients', 'charts', 'scales', 'predictions', 'groups'];
const hasOwn = (value, key) => Object.prototype.hasOwnProperty.call(value, key);

function clone(value) {
  if (value === undefined || value === null || typeof value !== 'object') return value;
  if (typeof structuredClone === 'function') return structuredClone(value);
  return JSON.parse(JSON.stringify(value));
}

const title = value => String(value)
  .replace(/_/g, ' ')
  .replace(/\b\w/g, character => character.toUpperCase());

// Keep all host data private. State transitions below only read from this copy,
// so neither the initial data object nor action payloads are ever used as state.
const supplied = window.DASHBOARD_DATA && typeof window.DASHBOARD_DATA === 'object'
  ? clone(window.DASHBOARD_DATA)
  : {};

function numeric(value) {
  return typeof value === 'number' && Number.isFinite(value);
}

function numericSeries(value) {
  if (!Array.isArray(value)) return false;
  for (let index = 0; index < value.length; index += 1) {
    if (!numeric(value[index])) return false;
  }
  return true;
}

function validMetrics(metrics) {
  if (!metrics || typeof metrics !== 'object' || Array.isArray(metrics)) return false;
  const keys = Object.keys(metrics);
  for (let index = 0; index < keys.length; index += 1) {
    const value = metrics[keys[index]];
    if (!numeric(value) && !numericSeries(value)) return false;
  }
  return true;
}

function validSteps(steps) {
  if (!Array.isArray(steps) || steps.length === 0) return false;
  for (let index = 0; index < steps.length; index += 1) {
    if (typeof steps[index] !== 'string' || steps[index].trim().length === 0) return false;
  }
  return true;
}

function withError(current, code) {
  return { ...current, error: { code } };
}

function withoutError(current) {
  if (!hasOwn(current, 'error')) return current;
  const next = { ...current };
  delete next.error;
  return next;
}

const suppliedMetrics = hasOwn(supplied, 'metrics') ? supplied.metrics : {};
const initialMetricsValid = validMetrics(suppliedMetrics);
let state = {
  metrics: initialMetricsValid ? clone(suppliedMetrics) : {},
  active_section: 'patients',
  onboarding: { steps: [], index: 0, complete: false }
};
if (!initialMetricsValid) state = withError(state, 'invalid_metrics');

const suppliedSteps = hasOwn(supplied, 'onboarding_steps')
  ? (Array.isArray(supplied.onboarding_steps) ? clone(supplied.onboarding_steps) : supplied.onboarding_steps)
  : [];

const root = ReactDOM.createRoot(document.getElementById('root'));

function render() {
  ReactDOM.flushSync(() => root.render(h(App)));
}

function result(ok) {
  const current = clone(state);
  const flow = clone(current.onboarding);
  const response = {
    ok,
    state: current,
    metrics: clone(current.metrics),
    active_section: current.active_section,
    onboarding: flow,
    steps: clone(flow.steps),
    index: flow.index,
    complete: flow.complete
  };
  if (current.error) response.error = clone(current.error);
  return response;
}

function failure(code) {
  state = withError(state, code);
  render();
  return result(false);
}

function success(nextState) {
  state = withoutError(nextState);
  render();
  return result(true);
}

function dispatch(action) {
  if (!action || typeof action !== 'object' || Array.isArray(action)) {
    return failure('invalid_action');
  }

  if (action.type === 'set_metrics') {
    if (!validMetrics(action.metrics)) return failure('invalid_metrics');
    return success({ ...state, metrics: clone(action.metrics) });
  }

  if (action.type === 'navigate') {
    if (!sections.includes(action.section)) return failure('unknown_section');
    return success({ ...state, active_section: action.section });
  }

  if (action.type === 'start_onboarding') {
    if (!validSteps(action.steps)) return failure('invalid_onboarding');
    return success({
      ...state,
      onboarding: { steps: clone(action.steps), index: 0, complete: false }
    });
  }

  if (action.type === 'advance_onboarding') {
    const flow = state.onboarding;
    if (!validSteps(flow.steps)) return failure('invalid_onboarding');

    // A completed flow is stable. This branch intentionally does not render,
    // which makes repeated advances true no-ops in both state and the DOM.
    if (flow.complete || flow.index >= flow.steps.length) {
      if (flow.index === flow.steps.length && flow.complete) return result(true);
      return success({
        ...state,
        onboarding: { steps: flow.steps, index: flow.steps.length, complete: true }
      });
    }

    const index = flow.index + 1;
    return success({
      ...state,
      onboarding: { steps: flow.steps, index, complete: index === flow.steps.length }
    });
  }

  return failure('unknown_action');
}

function Chart({ name, values }) {
  const maximum = values.reduce((largest, value) => Math.max(largest, Math.abs(value)), 1);
  const count = Math.max(1, values.length);
  const barWidth = Math.max(1, 600 / count - 16);

  return h(
    'section',
    { className: 'chart', 'data-metric': name },
    h('h3', null, title(name)),
    h(
      'svg',
      { viewBox: '0 0 600 180', role: 'img', 'aria-label': title(name) },
      values.map((value, index) => {
        const height = Math.abs(value) / maximum * 140;
        return h('rect', {
          key: index,
          className: 'chart-bar',
          x: index * 600 / count + 8,
          y: 160 - height,
          width: barWidth,
          height,
          'data-value': String(value)
        });
      })
    ),
    h(
      'ol',
      { className: 'chart-values' },
      values.map((value, index) => h('li', { key: index }, String(value)))
    )
  );
}

function App() {
  const flow = state.onboarding;

  return h(
    React.Fragment,
    null,
    h(
      'header',
      null,
      h('h1', null, 'Patient dashboard'),
      h('p', null, 'Synthetic data for interface evaluation'),
      h(
        'nav',
        { 'aria-label': 'Sections' },
        sections.map(section => h(
          'button',
          {
            key: section,
            type: 'button',
            'data-section': section,
            'aria-current': state.active_section === section ? 'page' : undefined,
            onClick: () => dispatch({ type: 'navigate', section })
          },
          title(section)
        ))
      )
    ),
    h(
      'main',
      null,
      h('h2', { id: 'section-title' }, title(state.active_section)),
      state.error ? h('p', { id: 'error', role: 'alert' }, state.error.code) : null,
      h(
        'div',
        { className: 'metrics' },
        Object.entries(state.metrics)
          .filter(([, value]) => !Array.isArray(value))
          .map(([key, value]) => h(
            'article',
            { key, className: 'metric', 'data-metric': key },
            h('h3', null, title(key)),
            h('div', { className: 'metric-value' }, String(value))
          ))
      ),
      Object.entries(state.metrics)
        .filter(([, value]) => Array.isArray(value))
        .map(([key, value]) => h(Chart, { key, name: key, values: value })),
      h(
        'button',
        {
          id: 'start-guide',
          type: 'button',
          onClick: () => dispatch({ type: 'start_onboarding', steps: suppliedSteps })
        },
        'Start guide'
      ),
      flow.steps.length
        ? h(
            'section',
            { id: 'onboarding', 'aria-label': 'Onboarding' },
            h('h3', null, flow.complete ? 'Guide complete' : 'Step ' + (flow.index + 1) + ' of ' + flow.steps.length),
            h('p', { id: 'guide-content' }, flow.complete ? 'All steps completed' : flow.steps[flow.index]),
            h('p', { id: 'guide-progress' }, flow.index + ' / ' + flow.steps.length + ' completed'),
            flow.complete
              ? null
              : h(
                  'button',
                  {
                    id: 'guide-next',
                    type: 'button',
                    onClick: () => dispatch({ type: 'advance_onboarding' })
                  },
                  'Next step'
                )
          )
        : null
    ),
    h('footer', null, 'Example dashboard. No real patient records.')
  );
}

window.dashboard = { dispatch, snapshot: () => clone(state) };
render();
