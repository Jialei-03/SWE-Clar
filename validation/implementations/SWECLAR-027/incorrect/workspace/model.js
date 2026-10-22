export function transition(state, event, config) {
  // Copy the state before applying an event.  The transition function is also
  // used independently of the renderer, so do not mutate state, event, or
  // config while deciding whether a navigation is allowed.
  const next = { ...state };

  if (event?.type === 'navigate') {
    const routes = Array.isArray(config?.routes) ? config.routes : [];
    const protectedRoutes = Array.isArray(config?.protectedRoutes)
      ? config.protectedRoutes
      : [];

    if (!routes.includes(event.route)) {
      // A rejected navigation leaves the active route (and every other state
      // field) alone, but records why it was rejected.
      return { ...next, error: 'unknown_route' };
    }

    if (protectedRoutes.includes(event.route) && config?.authenticated !== true) {
      return { ...next, error: 'auth_required' };
    }

    return { ...next, route: event.route, error: '' };
  }

  if (event?.type === 'toggle_filter') {
    return { ...next, openNow: !Boolean(next.openNow) };
  }

  return next;
}

export function displayRating(value) {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric.toFixed(1) : '0.0';
}
