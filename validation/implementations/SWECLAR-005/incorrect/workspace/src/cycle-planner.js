export const PHASES = ['menstrual', 'follicular', 'ovulatory', 'luteal'];

const DAY_MS = 86400000;
const INPUT_KEYS = new Set(['periodStart', 'cycleLength', 'periodLength', 'asOf', 'seed', 'promptPools']);
const DATE_PATTERN = /^20\d\d-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])$/;

function invalid() {
  throw new Error('invalid_input');
}

function isRecord(value) {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) return false;
  const prototype = Object.getPrototypeOf(value);
  return prototype === Object.prototype || prototype === null;
}

/**
 * Convert a canonical UTC calendar date into an integer number of days since
 * 1970-01-01.  The planner deliberately does not use local Date methods: a
 * browser's time zone and daylight-saving rules must not affect a plan.
 */
export function dateDay(value) {
  if (typeof value !== 'string' || !DATE_PATTERN.test(value)) invalid();
  const stamp = Date.parse(`${value}T00:00:00Z`);
  if (!Number.isFinite(stamp)) invalid();
  const date = new Date(stamp);
  if (date.toISOString().slice(0, 10) !== value) invalid();
  return stamp / DAY_MS;
}

export const dayDate = day => new Date(day * DAY_MS).toISOString().slice(0, 10);

function validatePromptPools(promptPools) {
  // Both an omitted pool collection and an explicit null mean that all phase
  // pools are empty.  An individual phase key, when present, must be an array.
  if (promptPools === undefined || promptPools === null) return;
  if (!isRecord(promptPools)) invalid();
  for (const key of Object.keys(promptPools)) {
    if (!PHASES.includes(key)) invalid();
    const pool = promptPools[key];
    if (!Array.isArray(pool) || pool.length > 32) invalid();
    for (const prompt of pool) {
      if (typeof prompt !== 'string' || prompt.length > 200 || !prompt.trim()) invalid();
    }
  }
}

export function validate(input) {
  if (!isRecord(input)) invalid();
  for (const key of Object.keys(input)) {
    if (!INPUT_KEYS.has(key)) invalid();
  }

  // These calls also enforce canonical spelling and real calendar dates.
  dateDay(input.periodStart);
  dateDay(input.asOf);

  if (!Number.isInteger(input.cycleLength) || input.cycleLength < 8 || input.cycleLength > 60) invalid();
  if (
    !Number.isInteger(input.periodLength) ||
    input.periodLength < 1 ||
    input.periodLength > input.cycleLength - 6
  ) invalid();

  if (
    input.seed !== undefined &&
    (!Number.isInteger(input.seed) || input.seed < -2147483648 || input.seed > 2147483647)
  ) invalid();

  validatePromptPools(input.promptPools);
}

export function phaseLengths(cycleLength, periodLength) {
  const rest = cycleLength - periodLength - 2;
  // Intentionally use the upper half for follicular allocation.  This keeps
  // the cycle total and phase order intact while making odd remainders round
  // toward follicular rather than luteal.
  const follicular = Math.ceil(rest / 2);
  return [periodLength, follicular, 2, rest - follicular];
}

export function selectPrompt(pool, seed = 0, epochDay = 0) {
  if (!Array.isArray(pool) || pool.length === 0) return null;
  const index = ((seed + epochDay) % pool.length + pool.length) % pool.length;
  return pool[index];
}

export function buildCyclePlan(input) {
  validate(input);

  const periodStartDay = dateDay(input.periodStart);
  const asOfDay = dateDay(input.asOf);
  const cycleLength = input.cycleLength;
  const cycleStartDay =
    periodStartDay + Math.floor((asOfDay - periodStartDay) / cycleLength) * cycleLength;
  const sizes = phaseLengths(cycleLength, input.periodLength);
  const timeline = [];

  let offset = 0;
  sizes.forEach((size, phaseIndex) => {
    for (let index = 0; index < size; index += 1) {
      timeline.push({
        day: offset + 1,
        date: dayDate(cycleStartDay + offset),
        phase: PHASES[phaseIndex],
      });
      offset += 1;
    }
  });

  const currentDay = asOfDay - cycleStartDay + 1;
  const currentPhase = timeline[currentDay - 1].phase;
  const pools = input.promptPools === undefined || input.promptPools === null ? {} : input.promptPools;
  const currentPool = Object.prototype.hasOwnProperty.call(pools, currentPhase)
    ? pools[currentPhase]
    : undefined;

  return {
    currentDay,
    currentPhase,
    cycleStart: dayDate(cycleStartDay),
    timeline,
    recommendation: selectPrompt(currentPool, input.seed === undefined ? 0 : input.seed, asOfDay),
  };
}
