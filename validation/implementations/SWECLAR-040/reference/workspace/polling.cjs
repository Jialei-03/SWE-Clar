// Prepared scheduling helper. The supplied queue serializes scans and manual work.
function startPolling(scan, queue, intervalMs) {
  if (!Number.isInteger(intervalMs) || intervalMs < 1) throw Error('Invalid polling interval');
  let stopped = false, timer, active = Promise.resolve();
  function tick() {
    if (stopped) return;
    active = queue(scan).catch(() => {}).finally(() => {
      if (!stopped) timer = setTimeout(tick, intervalMs);
    });
  }
  timer = setTimeout(tick, intervalMs);
  return async () => { stopped = true; clearTimeout(timer); await active; };
}
module.exports = {startPolling};
