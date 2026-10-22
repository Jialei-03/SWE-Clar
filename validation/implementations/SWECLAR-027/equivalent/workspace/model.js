function configuredList(config, key) {
  return Array.isArray(config?.[key]) ? config[key] : [];
}

function copyState(state, changes) {
  // Object.assign creates a fresh top-level record for every event, including
  // events that are rejected or not understood.  Values that are not part of
  // the transition remain untouched and are deliberately carried through.
  return Object.assign({}, state, changes);
}

function navigationError(route, config) {
  const routes = configuredList(config, 'routes');
  if (!routes.includes(route)) return 'unknown_route';

  const protectedRoutes = configuredList(config, 'protectedRoutes');
  if (protectedRoutes.includes(route) && config?.authenticated !== true) {
    return 'auth_required';
  }

  return '';
}

export function transition(state, event, config) {
  const current = copyState(state);

  switch (event?.type) {
    case 'navigate': {
      const error = navigationError(event.route, config);
      return error
        ? copyState(current, { error })
        : copyState(current, { route: event.route, error: '' });
    }
    case 'toggle_filter':
      return copyState(current, { openNow: !current.openNow });
    default:
      return current;
  }
}

export function displayRating(value) {
  let numeric;
  try {
    numeric = Number(value);
  } catch {
    numeric = NaN;
  }
  return Number.isFinite(numeric) ? numeric.toFixed(1) : '0.0';
}
