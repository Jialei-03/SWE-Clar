// One experiment budget, translated to the selected wire protocol. Never
// silently omit a budget or change reasoning/history to satisfy an endpoint.
export function withOutputBudget(payload, model, config) {
  const budget = config.model_max_output_tokens ?? model.maxTokens;
  if (!Number.isInteger(budget) || budget <= 0) throw new Error('A positive integer output budget is required');
  let field;
  if (model.api === 'openai-responses') field = 'max_output_tokens';
  else if (model.api === 'openai-completions') {
    field = config.compat?.maxTokensField ?? model.compat?.maxTokensField;
    if (!['max_tokens', 'max_completion_tokens'].includes(field)) {
      throw new Error('Declare the Chat Completions output-budget field explicitly');
    }
  } else if (model.api === 'anthropic-messages') field = 'max_tokens';
  else throw new Error(`Output budget mapping is not qualified for API ${model.api}`);
  const next = {...payload};
  for (const key of ['max_tokens', 'max_completion_tokens', 'max_output_tokens']) delete next[key];
  next[field] = budget;
  return next;
}
