function normalizedRuId(value) {
  return String(value ?? "").trim();
}


function unique(values) {
  return [...new Set(values)];
}


export function auditQuestionsFromUserPrompt(userPrompt) {
  try {
    const payload = JSON.parse(String(userPrompt ?? ""));
    return Array.isArray(payload?.audit_questions) ? payload.audit_questions : [];
  } catch {
    return [];
  }
}


export function auditAnswersError(answers, auditQuestions) {
  const submitted = Array.isArray(answers) ? answers : [];
  const expected = unique(
    (Array.isArray(auditQuestions) ? auditQuestions : [])
      .map((question) => normalizedRuId(question?.ru_id ?? question?.slot_id))
      .filter(Boolean),
  );
  const actual = submitted.map((answer) => normalizedRuId(answer?.ru_id ?? answer?.slot_id));
  const counts = new Map();
  for (const slotId of actual.filter(Boolean)) {
    counts.set(slotId, (counts.get(slotId) || 0) + 1);
  }

  const expectedSet = new Set(expected);
  const missing = expected.filter((slotId) => !counts.has(slotId));
  const duplicate = unique(
    actual.filter((slotId) => slotId && (counts.get(slotId) || 0) > 1),
  );
  const unexpected = unique(
    actual.filter((slotId) => slotId && !expectedSet.has(slotId)),
  );
  const blankCount = actual.filter((slotId) => !slotId).length;
  if (!missing.length && !duplicate.length && !unexpected.length && !blankCount) {
    for (const answer of submitted) {
      if (answer.confidence !== undefined && (!Number.isFinite(answer.confidence) || answer.confidence < 0 || answer.confidence > 1)) {
        return "confidence must be between 0 and 1";
      }
      if (answer.status === "known" && answer.value == null) return "known answers require a non-null value";
    }
    return null;
  }

  const details = [];
  if (missing.length) details.push(`missing: ${missing.join(", ")}`);
  if (duplicate.length) details.push(`duplicate: ${duplicate.join(", ")}`);
  if (unexpected.length) details.push(`unexpected: ${unexpected.join(", ")}`);
  if (blankCount) details.push(`blank ru_id: ${blankCount}`);
  return (
    "submit exactly one answer for each expected Requirement Unit; " +
    details.join("; ")
  );
}

export function workflowReminder(kind, stopReason, accepted) {
  if (accepted || stopReason !== 'stop') return null;
  const tool = {coding: 'submit_delivery', clarification: 'message_client or finish_clarification', audit: 'submit_audit_answers'}[kind];
  return tool ? `Protocol reminder (one recovery opportunity): your previous turn ended without the required workflow action. Use ${tool} to complete this phase. Preserve your current work and evidence; no test results or reference answers are provided by this reminder.` : null;
}
