import { buildCyclePlan, PHASES, dateDay } from './cycle-planner.js';

export const KEY = 'cycle-journals';
const PROFILE_KEYS = new Set(['id', 'label', 'settings', 'notifiedDays']);
const REQUIRED_PROFILE_KEYS = ['id', 'label', 'settings', 'notifiedDays'];
const SETTING_KEYS = new Set([
  'periodStart',
  'cycleLength',
  'periodLength',
  'seed',
  'promptPools',
  'reminderTime',
  'remindersEnabled',
]);
const REQUIRED_SETTING_KEYS = [
  'periodStart',
  'cycleLength',
  'periodLength',
  'reminderTime',
  'remindersEnabled',
];
const hasOwn = (value, key) => Object.prototype.hasOwnProperty.call(value, key);

function isRecord(value) {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) return false;
  const prototype = Object.getPrototypeOf(value);
  return prototype === Object.prototype || prototype === null;
}

function validLabel(label) {
  return typeof label === 'string' && label === label.trim() && label.length >= 1 && label.length <= 60;
}

export function validateSettings(settings) {
  if (!isRecord(settings)) throw new Error('invalid_input');
  if (Reflect.ownKeys(settings).some(key => typeof key !== 'string' || !SETTING_KEYS.has(key))) {
    throw new Error('invalid_input');
  }
  if (REQUIRED_SETTING_KEYS.some(key => !hasOwn(settings, key))) throw new Error('invalid_input');
  if (typeof settings.reminderTime !== 'string' || !/^([01]\d|2[0-3]):[0-5]\d$/.test(settings.reminderTime)) {
    throw new Error('invalid_input');
  }
  if (typeof settings.remindersEnabled !== 'boolean') throw new Error('invalid_input');

  // Keep the optional planner fields optional here, just as they are in the
  // public planning interface.  The page-created settings always include both.
  const planningInput = {
    periodStart: settings.periodStart,
    cycleLength: settings.cycleLength,
    periodLength: settings.periodLength,
    asOf: settings.periodStart,
  };
  if (Object.prototype.hasOwnProperty.call(settings, 'seed')) planningInput.seed = settings.seed;
  if (Object.prototype.hasOwnProperty.call(settings, 'promptPools')) planningInput.promptPools = settings.promptPools;
  buildCyclePlan(planningInput);
  return settings;
}

export function emptyStore() {
  return { activeId: null, profiles: [] };
}

function validNotifiedDays(days) {
  if (!Array.isArray(days)) return false;
  const seen = new Set();
  try {
    for (const value of days) {
      dateDay(value);
      if (seen.has(value)) return false;
      seen.add(value);
    }
  } catch {
    return false;
  }
  return true;
}

function validProfile(profile) {
  if (!isRecord(profile)) return false;
  if (
    Reflect.ownKeys(profile).some(key => typeof key !== 'string' || !PROFILE_KEYS.has(key)) ||
    REQUIRED_PROFILE_KEYS.some(key => !hasOwn(profile, key))
  ) {
    return false;
  }
  if (typeof profile.id !== 'string' || !profile.id.trim()) return false;
  if (!validLabel(profile.label)) return false;
  if (!validNotifiedDays(profile.notifiedDays)) return false;
  try {
    validateSettings(profile.settings);
  } catch {
    return false;
  }
  return true;
}

export function readStore() {
  let raw;
  try {
    raw = localStorage.getItem(KEY);
    if (raw === null) return emptyStore();
    const value = JSON.parse(raw);
    if (
      !isRecord(value) ||
      Reflect.ownKeys(value).some(key => typeof key !== 'string' || !['activeId', 'profiles'].includes(key)) ||
      !hasOwn(value, 'activeId') ||
      !hasOwn(value, 'profiles')
    ) {
      return emptyStore();
    }
    if (!Array.isArray(value.profiles) || !value.profiles.every(validProfile)) return emptyStore();
    if (new Set(value.profiles.map(profile => profile.id)).size !== value.profiles.length) return emptyStore();
    if (
      value.activeId !== null &&
      (typeof value.activeId !== 'string' || !value.profiles.some(profile => profile.id === value.activeId))
    ) {
      return emptyStore();
    }
    if (value.profiles.length === 0 && value.activeId !== null) return emptyStore();
    return value;
  } catch {
    return emptyStore();
  }
}

export function writeStore(state) {
  localStorage.setItem(KEY, JSON.stringify(state));
}

export function defaultSettings(today) {
  return {
    periodStart: today,
    cycleLength: 28,
    periodLength: 5,
    seed: 0,
    reminderTime: '08:00',
    remindersEnabled: false,
    promptPools: Object.fromEntries(
      PHASES.map((phase, index) => [
        phase,
        [
          `Journal prompt ${index + 1}: record a small moment.`,
          `Journal prompt ${index + 1}: make time for a conversation.`,
        ],
      ]),
    ),
  };
}
