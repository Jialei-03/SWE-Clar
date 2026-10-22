// Observe metadata only; never alter requests, responses, safety decisions, or reasoning.
export function refusalFromEvent(event) {
  if ((event?.delta?.stop_reason ?? event?.stop_reason) !== 'refusal') return null;
  const details = event?.delta?.stop_details ?? event?.stop_details;
  const category = details?.category;
  return {code: 'provider_refusal', type: 'refusal',
    category: typeof category === 'string' && /^[a-z_]{1,80}$/.test(category) ? category : null};
}
export function observeAnthropicRefusals(originalFetch = globalThis.fetch) {
  const pending = []; let refusal = null;
  globalThis.fetch = async (...args) => {
    const response = await originalFetch(...args);
    const url = String(args[0]?.url ?? args[0]);
    if (!url.includes('/providers/anthropic/') || !url.includes('/messages')) return response;
    const copy = response.clone();
    pending.push((async () => {
      if (!(copy.headers.get('content-type') || '').includes('text/event-stream')) {
        refusal = refusalFromEvent(await copy.json()) || refusal; return;
      }
      const reader = copy.body.getReader(); const decoder = new TextDecoder(); let buffer = '';
      try {
        for (;;) {
          const {done, value} = await reader.read(); if (done) break;
          buffer += decoder.decode(value, {stream: true});
          let pos;
          while ((pos = buffer.indexOf('\n')) >= 0) {
            const line = buffer.slice(0,pos).trim(); buffer=buffer.slice(pos+1);
            if (!line.startsWith('data:')) continue;
            try {refusal = refusalFromEvent(JSON.parse(line.slice(5))) || refusal;} catch {}
          }
        }
      } finally {reader.releaseLock();}
    })().catch(() => {}));
    return response;
  };
  return async () => {await Promise.all(pending); return refusal;};
}
