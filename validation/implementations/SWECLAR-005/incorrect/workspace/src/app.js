import { buildCyclePlan } from './cycle-planner.js';
import { readStore, writeStore, defaultSettings, validateSettings } from './journal-store.js';

const $ = id => document.getElementById(id);
const today = () => new Date().toISOString().slice(0, 10);

let state = readStore();
let lastRenderedDay = null;
const inFlightReminders = new Set();

const registration = navigator.serviceWorker
  .register('/sw.js')
  .then(() => navigator.serviceWorker.ready);
registration.catch(() => {
  $('feedback').textContent = 'notification_unavailable';
});

const active = () => state.profiles.find(profile => profile.id === state.activeId);

function planFor(profile, date) {
  const { reminderTime, remindersEnabled, ...planning } = profile.settings;
  return buildCyclePlan({ ...planning, asOf: date });
}

function node(tag, text) {
  const element = document.createElement(tag);
  element.textContent = text;
  return element;
}

function save(nextState = state) {
  writeStore(nextState);
}

function setPermissionText() {
  $('permission').textContent = typeof Notification === 'undefined' ? 'unavailable' : Notification.permission;
}

function render() {
  const profile = active();
  if (!profile) return;

  const date = today();
  const plan = planFor(profile, date);
  lastRenderedDay = date;

  $('today').textContent = date;
  $('journal-title').textContent = profile.label;
  $('current-day').textContent = String(plan.currentDay);
  $('current-phase').textContent = plan.currentPhase;
  $('cycle-start').textContent = plan.cycleStart;
  $('recommendation').textContent = plan.recommendation ?? 'No prompt for this phase';
  $('timeline').replaceChildren(
    ...plan.timeline.map(day => {
      const element = node('div', '');
      element.className = 'day';
      element.dataset.date = day.date;
      element.dataset.phase = day.phase;
      element.dataset.day = String(day.day);
      element.append(node('strong', String(day.day)), node('span', day.date), node('p', day.phase));
      if (day.date === date) element.setAttribute('aria-current', 'date');
      return element;
    }),
  );
  $('reminder-history').replaceChildren(...profile.notifiedDays.map(value => node('li', value)));
  setPermissionText();
}

function populate() {
  const selection = $('profile-select');
  selection.replaceChildren(
    ...state.profiles.map(profile => {
      const option = node('option', profile.label);
      option.value = profile.id;
      return option;
    }),
  );
  selection.value = state.activeId ?? '';

  const profile = active();
  $('workspace').hidden = !profile;
  if (!profile) {
    lastRenderedDay = null;
    setPermissionText();
    return;
  }

  const settings = profile.settings;
  $('period-start').value = settings.periodStart ?? '';
  $('cycle-length').value = settings.cycleLength ?? '';
  $('period-length').value = settings.periodLength ?? '';
  $('seed').value = settings.seed ?? 0;
  $('prompt-pools').value = JSON.stringify(
    settings.promptPools === undefined ? {} : settings.promptPools,
    null,
    2,
  );
  $('reminder-time').value = settings.reminderTime ?? '';
  $('reminders-enabled').checked = settings.remindersEnabled === true;
  render();
}

function freshId() {
  let id;
  do {
    if (globalThis.crypto && typeof globalThis.crypto.randomUUID === 'function') {
      id = globalThis.crypto.randomUUID();
    } else {
      id = `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
    }
  } while (!id || state.profiles.some(profile => profile.id === id));
  return id;
}

$('create-form').addEventListener('submit', event => {
  event.preventDefault();
  $('feedback').textContent = '';

  const label = $('label').value.trim();
  if (!label || label.length > 60) {
    $('feedback').textContent = 'invalid_input';
    return;
  }

  const profile = {
    id: freshId(),
    label,
    settings: defaultSettings(today()),
    notifiedDays: [],
  };
  const nextState = {
    activeId: profile.id,
    profiles: [...state.profiles, profile],
  };

  try {
    save(nextState);
    state = nextState;
    $('label').value = '';
    populate();
    $('feedback').textContent = 'saved';
    void maybeNotify();
  } catch {
    $('feedback').textContent = 'invalid_input';
  }
});

$('profile-select').addEventListener('change', () => {
  const selectedId = $('profile-select').value;
  if (!state.profiles.some(profile => profile.id === selectedId)) return;

  const nextState = { ...state, activeId: selectedId };
  try {
    save(nextState);
    state = nextState;
    $('feedback').textContent = '';
    populate();
    void maybeNotify();
  } catch {
    $('feedback').textContent = 'invalid_input';
  }
});

$('settings-form').addEventListener('submit', event => {
  event.preventDefault();
  $('feedback').textContent = '';

  const profile = active();
  if (!profile) {
    $('feedback').textContent = 'invalid_input';
    return;
  }

  try {
    if (
      !$('period-start').value.trim() ||
      !$('cycle-length').value.trim() ||
      !$('period-length').value.trim() ||
      !$('seed').value.trim()
    ) {
      throw new Error('invalid_input');
    }

    const settings = {
      periodStart: $('period-start').value,
      cycleLength: Number($('cycle-length').value),
      periodLength: Number($('period-length').value),
      seed: Number($('seed').value),
      promptPools: JSON.parse($('prompt-pools').value),
      reminderTime: $('reminder-time').value,
      remindersEnabled: $('reminders-enabled').checked,
    };
    validateSettings(settings);

    const nextProfiles = state.profiles.map(candidate =>
      candidate.id === profile.id ? { ...candidate, settings } : candidate,
    );
    const nextState = { ...state, profiles: nextProfiles };
    save(nextState);
    state = nextState;
    render();
    $('feedback').textContent = 'saved';
    void maybeNotify();
  } catch {
    // Do not populate or render on failure: the submitted controls remain
    // exactly as entered while the saved plan remains on screen.
    $('feedback').textContent = 'invalid_input';
  }
});

$('enable-notifications').addEventListener('click', async () => {
  try {
    if (typeof Notification === 'undefined') throw new Error('unavailable');
    const permission = await Notification.requestPermission();
    $('permission').textContent = permission;
    $('feedback').textContent = permission === 'granted' ? 'permission_granted' : 'permission_unavailable';
    if (permission === 'granted') void maybeNotify();
  } catch {
    $('feedback').textContent = 'permission_unavailable';
    setPermissionText();
  }
});

function reminderDue(settings, date) {
  const [hours, minutes] = settings.reminderTime.split(':').map(Number);
  const now = new Date();
  // The date argument is deliberately only used to select the UTC journal
  // day.  Comparing the UTC clock here handles the exact minute boundary.
  if (now.toISOString().slice(0, 10) !== date) return false;
  return now.getUTCHours() * 60 + now.getUTCMinutes() >= hours * 60 + minutes;
}

async function maybeNotify() {
  const initialProfile = active();
  if (!initialProfile || !initialProfile.settings.remindersEnabled) return;
  if (typeof Notification === 'undefined' || Notification.permission !== 'granted') return;

  const date = today();
  if (initialProfile.notifiedDays.includes(date) || !reminderDue(initialProfile.settings, date)) return;

  const key = `${initialProfile.id}:${date}`;
  if (inFlightReminders.has(key)) return;
  inFlightReminders.add(key);

  try {
    const serviceWorker = await registration;
    const profile = state.profiles.find(candidate => candidate.id === initialProfile.id);

    // Re-read all delivery decisions after registration resolves.  This makes
    // an edit made while the registration was starting take effect before the
    // browser notification is requested.
    if (
      !profile ||
      state.activeId !== profile.id ||
      !profile.settings.remindersEnabled ||
      profile.notifiedDays.includes(date) ||
      typeof Notification === 'undefined' ||
      Notification.permission !== 'granted' ||
      !reminderDue(profile.settings, date)
    ) {
      return;
    }

    const plan = planFor(profile, date);
    if (plan.recommendation === null) return;

    await serviceWorker.showNotification('Cycle Calendar reminder', {
      body: plan.recommendation,
      tag: `cycle:${profile.id}:${date}`,
      data: { profileId: profile.id, date, phase: plan.currentPhase },
    });

    // The successful showNotification call is the delivery boundary.  Only
    // after it resolves is this date persisted as delivered.
    if (!profile.notifiedDays.includes(date)) {
      profile.notifiedDays.push(date);
      save(state);
      if (active()?.id === profile.id) render();
    }
  } catch {
    // Permission failures, unavailable registrations and browser delivery
    // failures do not consume the date; a later check can retry.
  } finally {
    inFlightReminders.delete(key);
  }
}

setInterval(() => {
  if (active() && lastRenderedDay !== today()) render();
  void maybeNotify();
}, 500);

populate();
void maybeNotify();
