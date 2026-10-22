function stableToolCall(toolCall) {
  return {
    id: toolCall?.id || null,
    name: toolCall?.name || null,
    arguments: toolCall?.arguments || {},
  };
}

function messageProgressFingerprint(message) {
  if (!message || message.role !== "assistant" || !Array.isArray(message.content)) {
    return null;
  }

  const content = message.content.flatMap((item) => {
    if (!item) return [];
    if (item.type === "text" && item.text) {
      return [{type: "text", text: item.text}];
    }
    if (item.type === "thinking" && item.thinking) {
      return [{type: "thinking", thinking: item.thinking}];
    }
    if (item.type === "toolCall") {
      return [{type: "toolCall", ...stableToolCall(item)}];
    }
    return [];
  });
  const error = message.errorMessage || null;
  const stopReason = message.stopReason || null;
  if (content.length === 0 && error === null && stopReason === null) {
    return null;
  }
  return JSON.stringify({content, error, stopReason});
}

export function createMessageProgressGate() {
  let lastFingerprint = null;
  return {
    observe(message) {
      const fingerprint = messageProgressFingerprint(message);
      if (fingerprint === null || fingerprint === lastFingerprint) return false;
      lastFingerprint = fingerprint;
      return true;
    },
    reset() {
      lastFingerprint = null;
    },
  };
}
