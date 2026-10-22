(() => {
  'use strict';

  const REQUIRED_FIELDS = ['summary', 'drivers', 'vehicles'];
  const byId = (id) => document.getElementById(id);

  // Keep the currently selected panel as a small piece of UI state.  The
  // records themselves always come from window.FLEET_DATA.
  let openPanel = null;

  const hasOwn = (object, key) => (
    object !== null && object !== undefined
    && Object.prototype.hasOwnProperty.call(object, key)
  );

  const getData = () => window.FLEET_DATA;

  const missingFields = (data) => REQUIRED_FIELDS.filter((field) => !hasOwn(data, field));

  const clearRenderedContent = () => {
    byId('summary').replaceChildren();
    byId('drivers').replaceChildren();
    byId('vehicles').replaceChildren();
  };

  const showError = (error) => {
    const element = byId('error');
    element.hidden = false;
    element.textContent = `${error.code}: ${(error.fields || []).join(', ')}`;
    return { error };
  };

  const hideError = () => {
    const element = byId('error');
    element.hidden = true;
    element.textContent = '';
  };

  const renderList = (element, rows) => {
    element.replaceChildren();
    const fragment = document.createDocumentFragment();
    rows.forEach((row) => {
      const item = document.createElement('li');
      item.className = 'list-group-item';
      // textContent deliberately keeps names as text, even when a name looks
      // like HTML or contains an event-handler-looking string.
      item.textContent = row.name;
      item.dataset.recordId = String(row.id);
      fragment.append(item);
    });
    element.append(fragment);
  };

  const renderSummary = (summary) => {
    const element = byId('summary');
    element.replaceChildren();

    Object.entries(summary).forEach(([label, value]) => {
      const tile = document.createElement('div');
      tile.className = 'summary-tile';

      const heading = document.createElement('span');
      heading.className = 'summary-label';
      heading.textContent = label;

      const number = document.createElement('div');
      number.className = 'summary-value';
      number.textContent = String(value);

      tile.append(heading, number);
      element.append(tile);
    });
  };

  const closeSidebar = () => {
    openPanel = null;
    byId('sidebar').hidden = true;
    byId('sidebar-items').replaceChildren();
    byId('sidebar-title').textContent = '';
  };

  const renderSidebar = (target) => {
    const data = getData();
    const rows = data[target];
    const title = target === 'drivers' ? 'All drivers' : 'All vehicles';
    const sidebar = byId('sidebar');
    const items = byId('sidebar-items');

    openPanel = target;
    byId('sidebar-title').textContent = title;
    renderList(items, rows);
    sidebar.hidden = false;
  };

  const render = () => {
    const data = getData();
    const missing = missingFields(data);

    if (missing.length) {
      // Do not leave stale or partial records visible when the source is
      // incomplete.
      clearRenderedContent();
      closeSidebar();
      return showError({ code: 'missing_data', fields: missing });
    }

    hideError();
    renderSummary(data.summary);
    renderList(byId('drivers'), data.drivers);
    renderList(byId('vehicles'), data.vehicles);

    // A normal refresh keeps an already-open local panel in sync with the
    // current source object.  It never creates records of its own.
    if (openPanel) renderSidebar(openPanel);

    return { ok: true };
  };

  const unknownAction = () => ({ error: { code: 'unknown_action' } });

  const dispatch = (action) => {
    // Validate the complete action before changing any UI state.  In
    // particular, malformed actions must be harmless.
    if (!action || typeof action !== 'object' || Array.isArray(action)) {
      return unknownAction();
    }

    if (action.type === 'close_sidebar' && Object.keys(action).length === 1) {
      closeSidebar();
      return { ok: true };
    }

    if (
      action.type === 'view_all'
      && Object.keys(action).length === 2
      && (action.target === 'drivers' || action.target === 'vehicles')
    ) {
      const data = getData();
      const missing = missingFields(data);
      if (missing.length) return { error: { code: 'missing_data', fields: missing } };

      renderSidebar(action.target);
      return { ok: true };
    }

    return unknownAction();
  };

  window.dashboard = { dispatch, render };

  byId('view-drivers').addEventListener('click', () => {
    dispatch({ type: 'view_all', target: 'drivers' });
  });
  byId('view-vehicles').addEventListener('click', () => {
    dispatch({ type: 'view_all', target: 'vehicles' });
  });
  byId('close-sidebar').addEventListener('click', () => {
    dispatch({ type: 'close_sidebar' });
  });

  render();
})();
