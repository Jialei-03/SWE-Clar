import {NotebookHost, request, element, message} from './host.js';

const host = new NotebookHost();
let state = null;
let selected = [];
let anchor = null;

const sidebar = document.querySelector('#sidebar');
const tree = document.querySelector('#tree');
const uid = () => 'ITEM-' + crypto.randomUUID();

function allItems(items) {
  return items.flatMap(item => [item, ...(item.children ? allItems(item.children) : [])]);
}
function active() {
  return state.tabs.find(tab => tab.id === state.active_tab);
}
function activeItem(id) {
  return allItems(active()?.items || []).find(item => item.id === id);
}
function currentFolder() {
  // A selected folder is the visible destination for the creation controls.
  // A bookmark or an empty selection means the active tab root.
  const item = activeItem(selected[0]);
  return item?.kind === 'folder' ? item.id : null;
}
function rows() {
  return [...tree.querySelectorAll('.tree-row')];
}
function rowFor(id) {
  return rows().find(row => row.dataset.item === id);
}
function applySelection() {
  for (const node of rows()) {
    const isSelected = selected.includes(node.dataset.item);
    node.classList.toggle('selected', isSelected);
    node.setAttribute('aria-selected', String(isSelected));
  }
}

async function action(command) {
  await host.flush();
  state = await request('/api/action', command);
  message();
  render();
  return state;
}
function guarded(work) {
  return (...args) => Promise.resolve().then(() => work(...args)).catch(message);
}

function select(row, event = {}) {
  const id = row.dataset.item;
  const visible = rows().map(node => node.dataset.item);
  const shift = event.shiftKey === true;
  const toggle = event.ctrlKey === true || event.metaKey === true;

  if (shift && anchor && visible.includes(anchor) && visible.includes(id)) {
    const start = visible.indexOf(anchor);
    const end = visible.indexOf(id);
    selected = visible.slice(Math.min(start, end), Math.max(start, end) + 1);
  } else if (toggle) {
    if (selected.includes(id)) {
      selected = selected.filter(value => value !== id);
      // Removing an item does not create a new anchor.  The clarification
      // assigns the anchor only when a Ctrl/Meta gesture newly includes an
      // item, so a later Shift range still starts at the prior anchor.
    } else {
      selected = [...selected, id];
      anchor = id;
    }
  } else {
    selected = [id];
    anchor = id;
  }
  applySelection();
  row.focus();
}

async function rename(row, item) {
  const target = row.querySelector('.label');
  if (!target || target.querySelector('input')) return;
  const input = element('input', undefined, {'aria-label': 'Rename item'});
  input.value = item.label;
  target.replaceChildren(input);
  input.focus();
  input.select();

  let finishing = false;
  const finish = async save => {
    if (finishing) return;
    // Mark the edit as closing before replacing the row.  Replacing a focused
    // input fires blur synchronously in browsers; without this guard Enter
    // could submit the same rename twice.
    finishing = true;
    if (!save) {
      render();
      rowFor(item.id)?.focus();
      return;
    }
    try {
      await action({type: 'rename', id: item.id, label: input.value});
      rowFor(item.id)?.focus();
    } catch (error) {
      // An invalid label should not silently end an in-cell edit.  Keep the
      // input available for correction and, importantly, never navigate host.
      finishing = false;
      message(error);
      input.focus();
      input.select();
    }
  };
  input.onkeydown = event => {
    event.stopPropagation();
    if (event.key === 'Enter') {
      event.preventDefault();
      finish(true);
    } else if (event.key === 'Escape') {
      event.preventDefault();
      finish(false);
    }
  };
  input.onblur = () => finish(true);
}

async function toggleFolder(item) {
  if (item.kind !== 'folder') return;
  const expanded = state.expanded.includes(item.id)
    ? state.expanded.filter(id => id !== item.id)
    : [...state.expanded, item.id];
  await action({type: 'view', expanded});
  rowFor(item.id)?.focus();
}

async function open(item) {
  if (item.kind === 'folder') {
    await toggleFolder(item);
  } else {
    await action({type: 'open', id: item.id});
    await host.refresh();
  }
}

async function keyboard(event, row, item) {
  if (event.isComposing) return;
  const key = event.key;

  if (key === 'ArrowUp' || key === 'ArrowDown') {
    event.preventDefault();
    event.stopPropagation();
    const visible = rows();
    const position = visible.indexOf(row);
    if (position < 0) return;
    const nextPosition = Math.max(
      0,
      Math.min(visible.length - 1, position + (key === 'ArrowUp' ? -1 : 1)),
    );
    const target = visible[nextPosition];
    select(target, event);
    return;
  }

  if (key === 'ArrowRight') {
    event.preventDefault();
    event.stopPropagation();
    if (item.kind === 'folder' && !state.expanded.includes(item.id)) {
      await toggleFolder(item);
    }
    return;
  }

  if (key === 'ArrowLeft') {
    event.preventDefault();
    event.stopPropagation();
    if (item.kind === 'folder' && state.expanded.includes(item.id)) {
      await toggleFolder(item);
    }
    return;
  }

  if (key === 'F2') {
    event.preventDefault();
    event.stopPropagation();
    await rename(row, item);
    return;
  }

  if (key === 'Enter') {
    event.preventDefault();
    event.stopPropagation();
    await open(item);
    return;
  }

  if (key === 'Escape') {
    event.preventDefault();
    event.stopPropagation();
    return;
  }
}

function selectedForDrag(_event, row) {
  if (!selected.includes(row.dataset.item)) {
    // A drag always establishes a one-item selection when its origin was not
    // selected; modifier keys must not accidentally append an old selection.
    selected = [row.dataset.item];
    anchor = row.dataset.item;
    applySelection();
    row.focus();
  }
  return selected.slice();
}

async function drop(event, tabId, parentId, index) {
  event.preventDefault();
  event.stopPropagation();
  const encoded = event.dataTransfer?.getData('application/x-notebook-items');
  if (!encoded) return;
  let ids;
  try {
    ids = JSON.parse(encoded);
  } catch (_) {
    return;
  }
  const command = {type: 'move', ids, tab_id: tabId, parent_id: parentId};
  if (index !== undefined) command.index = index;
  await action(command);
}

function render() {
  if (!state) return;
  const currentTab = active();
  if (!currentTab) return;

  sidebar.style.width = state.width + 'px';
  sidebar.classList.toggle('wrap', state.wrap);
  document.querySelector('#word-wrap').checked = state.wrap;

  const tabs = document.querySelector('#tabs');
  tabs.replaceChildren();
  for (const tab of state.tabs) {
    const button = element('button', tab.name, {
      'data-tab': tab.id,
      'aria-selected': String(tab.id === state.active_tab),
    });
    button.classList.toggle('active', tab.id === state.active_tab);
    button.onclick = guarded(async () => {
      selected = [];
      anchor = null;
      await action({type: 'activate', id: tab.id});
    });
    button.ondragover = event => {
      event.preventDefault();
      event.dataTransfer.dropEffect = 'move';
    };
    button.ondrop = guarded(event => drop(event, tab.id, null));
    tabs.append(button);
  }

  tree.replaceChildren();
  function append(items, depth, parentId) {
    for (const item of items) {
      const row = element('div', undefined, {
        class: 'tree-row',
        'data-item': item.id,
        'data-kind': item.kind,
        role: 'treeitem',
        tabindex: '0',
        draggable: 'true',
        'aria-selected': String(selected.includes(item.id)),
      });
      row.style.paddingLeft = depth * 14 + 'px';
      row.classList.toggle('selected', selected.includes(item.id));

      if (item.kind === 'folder') {
        const expanded = state.expanded.includes(item.id);
        row.setAttribute('aria-expanded', String(expanded));
        const expand = element('button', expanded ? '−' : '+', {
          class: 'expand',
          'aria-label': 'Toggle ' + item.label,
          tabindex: '-1',
        });
        expand.onclick = guarded(async event => {
          event.stopPropagation();
          await toggleFolder(item);
        });
        row.append(expand);
      } else {
        row.append(element('span', '↗', {'aria-hidden': 'true', class: 'bookmark-glyph'}));
      }

      const text = element('span', item.label, {class: 'label'});
      row.append(text);
      if (item.kind === 'bookmark') {
        const button = element('button', 'Open', {'aria-label': 'Open ' + item.label, tabindex: '-1'});
        button.onclick = guarded(async event => {
          event.stopPropagation();
          await open(item);
        });
        row.append(button);
      }

      row.onclick = event => select(row, event);
      text.ondblclick = event => {
        event.stopPropagation();
        rename(row, item).catch(message);
      };
      row.onkeydown = guarded(event => keyboard(event, row, item));
      row.ondragstart = event => {
        const ids = selectedForDrag(event, row);
        event.dataTransfer.setData('application/x-notebook-items', JSON.stringify(ids));
        event.dataTransfer.effectAllowed = 'move';
      };
      row.ondragover = event => {
        event.preventDefault();
        event.stopPropagation();
        event.dataTransfer.dropEffect = 'move';
      };
      row.ondrop = guarded(event => {
        if (item.kind === 'folder') {
          return drop(event, currentTab.id, item.id);
        }
        // For a bookmark destination, compute the index after selected direct
        // siblings are removed, exactly as the server does.
        const remaining = items.filter(candidate => !selected.includes(candidate.id));
        const before = remaining.findIndex(candidate => candidate.id === item.id);
        return drop(event, currentTab.id, parentId, before < 0 ? 0 : before);
      });

      tree.append(row);
      if (item.kind === 'folder' && state.expanded.includes(item.id)) {
        append(item.children, depth + 1, item.id);
      }
    }
  }
  append(currentTab.items, 0, null);
}

tree.ondragover = event => {
  event.preventDefault();
  event.dataTransfer.dropEffect = 'move';
};
tree.ondrop = guarded(event => drop(event, active().id, null));

document.querySelector('#toggle-sidebar').onclick = () => {
  sidebar.hidden = !sidebar.hidden;
  if (sidebar.hidden) document.querySelector('#wrap-menu').hidden = true;
};

document.querySelector('#add-bookmark').onclick = guarded(async () => {
  const target = host.target(document.querySelector('#target-kind').value);
  if (!target) throw new Error('No current object of this type');
  await action({type: 'bookmark', id: uid(), target_id: target.id, parent_id: currentFolder()});
});

document.querySelector('#new-folder').onclick = guarded(async () => {
  const name = prompt('Folder label');
  if (name !== null) await action({type: 'folder', id: uid(), label: name, parent_id: currentFolder()});
});

document.querySelector('#new-tab').onclick = guarded(async () => {
  const name = prompt('Tab name');
  if (name !== null) await action({type: 'tab', id: uid(), name});
});

document.querySelector('#delete-item').onclick = guarded(async () => {
  if (selected.length !== 1) throw new Error('Select one item to delete');
  if (confirm('Delete selected item and its descendants?')) {
    await action({type: 'delete', id: selected[0], confirmed: true, recursive: true});
    selected = [];
    anchor = null;
    applySelection();
  }
});

document.querySelector('#sort-items').onclick = guarded(() => action({
  type: 'sort',
  parent_id: currentFolder(),
}));

sidebar.oncontextmenu = event => {
  event.preventDefault();
  document.querySelector('#wrap-menu').hidden = false;
};
document.querySelector('#word-wrap').onchange = guarded(event => action({
  type: 'view',
  wrap: event.target.checked,
}));

document.addEventListener('click', event => {
  if (!sidebar.contains(event.target) && event.target.id !== 'toggle-sidebar') {
    sidebar.hidden = true;
    document.querySelector('#wrap-menu').hidden = true;
  }
});

const resize = document.querySelector('#resize');
let resizing = false;
let pendingWidth = 0;
resize.onpointerdown = event => {
  resizing = true;
  pendingWidth = state.width;
  if (event.pointerId !== undefined) resize.setPointerCapture?.(event.pointerId);
  event.preventDefault();
};
resize.onpointermove = event => {
  if (!resizing || !Number.isFinite(event.clientX)) return;
  pendingWidth = Math.round(Math.max(
    180,
    Math.min(480, event.clientX - sidebar.getBoundingClientRect().left),
  ));
  sidebar.style.width = pendingWidth + 'px';
};
resize.onpointerup = guarded(async event => {
  if (!resizing) return;
  resizing = false;
  try {
    if (event.pointerId !== undefined) resize.releasePointerCapture?.(event.pointerId);
  } catch (_) { /* already released */ }
  await action({type: 'view', width: pendingWidth});
});
resize.onpointercancel = resize.onpointerup;

await host.refresh();
state = await request('/api/state');
render();
