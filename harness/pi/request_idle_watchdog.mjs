export function createRequestIdleWatchdog({ timeoutMs, onTimeout }) {
  if (!Number.isFinite(timeoutMs) || timeoutMs <= 0) {
    throw new Error("request idle timeout must be a positive number");
  }
  if (typeof onTimeout !== "function") {
    throw new Error("request idle timeout requires an onTimeout callback");
  }

  let timer = null;
  let active = false;

  const arm = () => {
    if (!active) return;
    if (timer !== null) clearTimeout(timer);
    timer = setTimeout(() => {
      timer = null;
      active = false;
      onTimeout();
    }, timeoutMs);
  };

  return {
    start() {
      active = true;
      arm();
    },
    touch() {
      arm();
    },
    stop() {
      active = false;
      if (timer !== null) clearTimeout(timer);
      timer = null;
    },
  };
}
