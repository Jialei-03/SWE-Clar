/*
 * SWE-Clar Pi adapter.
 *
 * The Python evaluation server owns the run document and the official task runtime.
 * This process owns one complete Pi session. Pi's native read/bash/edit/write
 * definitions are bound to the per-run task container; clarification and audit
 * receive the same native read definition over an allowlisted frozen file view.
 * The final JSON object is deliberately self-contained so the server can
 * persist the complete model/tool transcript in the run timeline.
 */

import { requireConfiguredEndpoint } from './endpoint_config.mjs';
import { constants as fsConstants } from 'node:fs';
import { access as fsAccess, readFile as fsReadFile } from 'node:fs/promises';
import path from 'node:path';
import { withOutputBudget } from './output-budget.mjs';
import { observeAnthropicRefusals } from './refusal_observer.mjs';
const observedRefusal = observeAnthropicRefusals();

import { dockerBashOperations, dockerFileOperations } from './runtime_operations.mjs';

import { Type, getSupportedThinkingLevels } from '@mariozechner/pi-ai';
import {
  AuthStorage,
  ModelRegistry,
  SessionManager,
  SettingsManager,
  createBashToolDefinition,
  createAgentSession,
  createEditToolDefinition,
  createExtensionRuntime,
  createReadToolDefinition,
  createWriteToolDefinition,
} from '@mariozechner/pi-coding-agent';
import { auditAnswersError, auditQuestionsFromUserPrompt, workflowReminder } from './workflow_validation.mjs';
import { createMessageProgressGate } from './message_progress_gate.mjs';
import { createRequestIdleWatchdog } from './request_idle_watchdog.mjs';
import { mappedReadOperations as confinedReadOperations, mappedWorkingDirectory } from './mapped_read.mjs';

const MAX_TRACE_TEXT = Infinity;
const IMAGE_MIME = new Map([
  ['.png', 'image/png'],
  ['.jpg', 'image/jpeg'],
  ['.jpeg', 'image/jpeg'],
  ['.gif', 'image/gif'],
  ['.webp', 'image/webp'],
]);

function clip(value, limit = MAX_TRACE_TEXT) {
  const text = String(value ?? '');
  if (text.length <= limit) return text;
  return `${text.slice(0, limit)}\n… [truncated ${text.length - limit} chars]`;
}

function textFromContent(content) {
  if (!Array.isArray(content)) return typeof content === 'string' ? content : '';
  return content
    .filter(item => item && item.type === 'text')
    .map(item => item.text || '')
    .join('');
}

function thinkingFromContent(content) {
  if (!Array.isArray(content)) return '';
  return content
    .filter(item => item && item.type === 'thinking')
    .map(item => item.thinking || '')
    .join('');
}

function toolCallsFromContent(content) {
  if (!Array.isArray(content)) return [];
  return content
    .filter(item => item && item.type === 'toolCall')
    .map(item => ({
      id: item.id,
      name: item.name,
      arguments: item.arguments || {},
    }));
}

function redactImageData(message) {
  if (!message || !Array.isArray(message.content)) return message;
  return {
    ...message,
    content: message.content.map(item => {
      if (!item || item.type !== 'image') return item;
      return {
        type: 'image',
        mimeType: item.mimeType || null,
        data: '[attachment bytes omitted from persisted transcript]',
      };
    }),
  };
}

function assistantSummary(message) {
  if (!message || message.role !== 'assistant') return null;
  return {
    text: clip(textFromContent(message.content)),
    thinking: clip(thinkingFromContent(message.content)),
    tool_calls: toolCallsFromContent(message.content),
    stop_reason: message.stopReason || null,
    error: message.errorMessage || null,
    usage: message.usage || null,
    provider: message.provider || null,
    model: message.model || null,
    timestamp: message.timestamp || null,
  };
}

function toolResultSummary(result) {
  if (!result || result.role !== 'toolResult') return null;
  return {
    tool_call_id: result.toolCallId,
    tool_name: result.toolName,
    content: clip(textFromContent(result.content)),
    is_error: Boolean(result.isError),
    details: result.details || null,
    timestamp: result.timestamp || null,
  };
}

function clientMessageError(value) {
  const message = String(value || '').trim();
  if (!message) return 'message must not be empty';
  if (
    /\bRU-\d{3}\b|\bRequirement Units?\b|\bhidden tests?\b|\b(?:coding\s+)?benchmark\b|\bevaluator\b/iu.test(
      message
    )
  ) {
    return 'message must use ordinary project language and must not mention internal evaluation terminology';
  }
  return null;
}

function buildResourceLoader(systemPrompt) {
  return {
    getExtensions: () => ({ extensions: [], errors: [], runtime: createExtensionRuntime() }),
    getSkills: () => ({ skills: [], diagnostics: [] }),
    getPrompts: () => ({ prompts: [], diagnostics: [] }),
    getThemes: () => ({ themes: [], diagnostics: [] }),
    getAgentsFiles: () => ({ agentsFiles: [] }),
    getSystemPrompt: () => systemPrompt,
    getAppendSystemPrompt: () => [],
    extendResources: () => {},
    reload: async () => {},
  };
}

function registerModel(input, authStorage) {
  const registry = ModelRegistry.inMemory(authStorage);
  const config = input.model_config || {};
  if (!config.provider || !config.model || (config.builtin_provider !== true && !config.base_url)) {
    throw new Error('Configure provider, model and endpoint explicitly');
  }
  const provider = config.provider;
  const modelId = config.model;
  const runtimeKey =
    process.env.SWECLAR_PI_MODEL_API_KEY || config.api_key || '';
  if (config.builtin_provider === true) {
    if (runtimeKey) authStorage.setRuntimeApiKey(provider, runtimeKey);
    // Pi's bundled catalog can lag the provider's model catalog.  Register only
    // the selected missing model (for example GPT-5.6) against Pi's built-in
    // OAuth provider; the credential remains in AuthStorage and never enters
    // the model definition or process environment.
    if (!registry.find(provider, modelId)) {
      requireConfiguredEndpoint(config);
      const oauth = authStorage.getOAuthProviders().find(item => item.id === provider);
      if (!oauth) throw new Error(`Pi OAuth provider ${provider} is unavailable`);
      registry.registerProvider(provider, {
        baseUrl: config.base_url,
        api: config.api || 'openai-codex-responses',
        oauth,
        models: [
          {
            id: modelId,
            name: config.name || modelId,
            reasoning: config.reasoning !== false,
            thinkingLevelMap: config.thinking_level_map || undefined,
            input: config.input || ['text'],
            contextWindow:
              Number.isInteger(config.context_window) && config.context_window > 0
                ? config.context_window
                : 272000,
            maxTokens:
              Number.isInteger(config.model_max_output_tokens) && config.model_max_output_tokens > 0
                ? config.model_max_output_tokens
                : 128000,
            cost: config.cost || { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
          },
        ],
      });
    }
  } else {
    registry.registerProvider(provider, {
      baseUrl: config.base_url,
      api: config.api || 'openai-completions',
      apiKey: runtimeKey,
      authHeader: config.auth_header !== false,
      headers: config.headers || {},
      models: [
        {
          id: modelId,
          name: config.name || modelId,
          reasoning: config.reasoning !== false && config.thinking !== 'disabled',
          thinkingLevelMap: config.thinking_level_map || undefined,
          input: config.input || ['text'],
          contextWindow:
            Number.isInteger(config.context_window) && config.context_window > 0
              ? config.context_window
              : 1000000,
          maxTokens:
            Number.isInteger(config.model_max_output_tokens) && config.model_max_output_tokens > 0
              ? config.model_max_output_tokens
              : 65536,
          cost: config.cost || { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
          compat: config.compat || {
            supportsDeveloperRole: false,
            supportsReasoningEffort: false,
            maxTokensField: 'max_completion_tokens',
          },
        },
      ],
    });
  }
  const model = registry.find(provider, modelId);
  if (!model) throw new Error(`Pi model ${provider}/${modelId} is unavailable`);
  if (config.thinking_level_map) model.thinkingLevelMap = {...model.thinkingLevelMap, ...config.thinking_level_map};
  return { registry, model };
}

async function main(input) {
  const toolEvents = [];
  const eventTrace = [];
  const turns = [];
  let currentTurn = null;
  const streamProgress = input.stream_progress !== false;
  let lastMessageProgressMs = 0;
  const emitProgress = payload => {
    if (!streamProgress) return;
    try {
      process.stdout.write(`${JSON.stringify({ kind: 'pi_progress', ...payload })}\n`);
    } catch {
      // The Python owner may stop a run while a provider response is in
      // flight. Progress is best effort; the final result/error still owns
      // the durable outcome.
    }
  };
  const configuredIdleSeconds = Number(
    input.request_idle_timeout_s ?? process.env.SWECLAR_PI_REQUEST_IDLE_TIMEOUT_SECONDS ?? 900
  );
  const requestIdleTimeoutSeconds = Number.isFinite(configuredIdleSeconds)
    ? Math.max(1, configuredIdleSeconds)
    : 900;
  const requestIdleWatchdog = createRequestIdleWatchdog({
    timeoutMs: requestIdleTimeoutSeconds * 1000,
    onTimeout: () => {
      process.stderr.write(
        `Pi provider request idle timeout after ${requestIdleTimeoutSeconds}s without model or tool progress.\n`
      );
      process.exit(124);
    },
  });
  const messageProgressGate = createMessageProgressGate();
  const config = input.model_config || {};
  const sessionKind = String(input.session_kind || 'text');
  const codingSession = sessionKind === 'coding';
  const clarificationSession = sessionKind === 'clarification';
  const auditSession = sessionKind === 'audit';
  const runtimeBacked = Boolean(input.runtime_container);
  const mappedReadBacked = Array.isArray(input.read_roots) && input.read_roots.length > 0;
  const authStorage = AuthStorage.create(input.auth_path || '/tmp/sweclar-pi-auth.json');
  const { registry, model } = registerModel(input, authStorage);
  const systemPrompt = String(input.system_prompt || '');
  const supportedThinking = getSupportedThinkingLevels(model);
  const thinkingLevel = supportedThinking.at(-1);
  const requestSettings = []; 

  let acceptedWorkflowAction = null;
  const recordWorkflowTool = (name, params, { accepted, output }) => {
    const now = new Date().toISOString();
    const record = {
      tool: name,
      input: params,
      output,
      accepted,
      started_at: now,
      completed_at: now,
      duration_ms: 0,
    };
    toolEvents.push(record);
    emitProgress({
      event: 'tool_completed',
      tool_event: record,
      tool_call_count: toolEvents.length,
    });
    return record;
  };
  const messageClient = {
    name: 'message_client',
    label: 'Message Client',
    description: 'Send one natural requirements-conversation turn to the Client Simulator.',
    promptSnippet: 'Continue the requirements conversation with the Client Simulator.',
    parameters: Type.Object({
      message: Type.String({
        description:
          'A natural Client-facing project message; it may contain context, proposals, questions, or a follow-up statement, and must not mention internal evaluation terminology.',
      }),
    }),
    executionMode: 'sequential',
    async execute(_toolCallId, params) {
      if (acceptedWorkflowAction) {
        const output = 'Rejected: one workflow action has already been accepted in this turn.';
        const record = recordWorkflowTool('message_client', params, { accepted: false, output });
        return { content: [{ type: 'text', text: output }], details: record };
      }
      const error = clientMessageError(params.message);
      if (error) {
        const output = `Rejected: ${error}.`;
        const record = recordWorkflowTool('message_client', params, { accepted: false, output });
        return { content: [{ type: 'text', text: output }], details: record };
      }
      acceptedWorkflowAction = { action: 'message', message: String(params.message).trim() };
      const output =
        'Accepted. The benchmark will send this message to the Client Simulator; end this turn now.';
      const record = recordWorkflowTool('message_client', params, { accepted: true, output });
      // The accepted workflow action is the complete result of this Pi turn.
      // Asking the provider for another assistant message after the tool result
      // adds no benchmark information and weaker models can loop for many
      // additional requests instead of ending. Pi's native terminate flag
      // stops cleanly after the completed tool batch without imposing a turn,
      // question, or trajectory limit before an action is accepted.
      return { content: [{ type: 'text', text: output }], details: record, terminate: true };
    },
  };
  const finishClarification = {
    name: 'finish_clarification',
    label: 'Finish Clarification',
    description:
      'End the centralized clarification phase when the available information is sufficient.',
    promptSnippet: 'Finish clarification and freeze the current context.',
    parameters: Type.Object({
      reason: Type.Optional(
        Type.String({
          description:
            'A short optional operational reason; do not provide hidden chain-of-thought.',
        })
      ),
    }),
    executionMode: 'sequential',
    async execute(_toolCallId, params) {
      if (acceptedWorkflowAction) {
        const output = 'Rejected: one workflow action has already been accepted in this turn.';
        const record = recordWorkflowTool('finish_clarification', params, {
          accepted: false,
          output,
        });
        return { content: [{ type: 'text', text: output }], details: record };
      }
      acceptedWorkflowAction = {
        action: 'ready',
        reason: String(params.reason || '')
          .trim()
          .slice(0, 500),
      };
      const output =
        'Accepted. Clarification will end and the benchmark will freeze this context; end this turn now.';
      const record = recordWorkflowTool('finish_clarification', params, { accepted: true, output });
      return { content: [{ type: 'text', text: output }], details: record, terminate: true };
    },
  };
  const submitAuditAnswers = {
    name: 'submit_audit_answers',
    label: 'Submit Audit Answers',
    description: 'Submit one verbal answer for every Requirement Unit in the audit branch.',
    promptSnippet: 'Submit the complete Requirement Unit audit answers.',
    parameters: Type.Object({
      answers: Type.Array(
        Type.Object({
          ru_id: Type.String(),
          status: Type.Union([Type.Literal('known'), Type.Literal('unknown')]),
          value: Type.Any(),
        })
      ),
    }),
    executionMode: 'sequential',
    async execute(_toolCallId, params) {
      if (acceptedWorkflowAction) {
        const output = 'Rejected: audit answers were already submitted in this turn.';
        const record = recordWorkflowTool('submit_audit_answers', params, {
          accepted: false,
          output,
        });
        return { content: [{ type: 'text', text: output }], details: record };
      }
      const submissionError = auditAnswersError(
        params.answers,
        auditQuestionsFromUserPrompt(input.user_prompt)
      );
      if (submissionError) {
        const output = `Rejected: ${submissionError}.`;
        const record = recordWorkflowTool('submit_audit_answers', params, {
          accepted: false,
          output: `Rejected: ${submissionError}.`,
        });
        return { content: [{ type: 'text', text: output }], details: record };
      }
      const answers = (params.answers || []).map(answer => ({
        ru_id: String(answer?.ru_id ?? answer?.slot_id ?? '').trim(),
        status: answer?.status,
        value: answer?.status === 'unknown' ? null : answer?.value ?? null,
      }));
      acceptedWorkflowAction = { action: 'audit', answers };
      const output = 'Accepted. Audit answers have been submitted; end this turn now.';
      const record = recordWorkflowTool('submit_audit_answers', params, { accepted: true, output });
      return { content: [{ type: 'text', text: output }], details: record, terminate: true };
    },
  };
  const submitDelivery = {
    name: 'submit_delivery',
    label: 'Submit Delivery',
    description:
      'Finish the coding task by submitting a concise delivery summary and the checks actually run.',
    promptSnippet: 'Submit the completed coding delivery.',
    parameters: Type.Object({
      summary: Type.String({ description: 'Concise description of the completed implementation.' }),
      checks: Type.Array(
        Type.String({ description: 'A build or test command actually run, with a concise result.' })
      ),
    }),
    executionMode: 'sequential',
    async execute(_toolCallId, params) {
      if (acceptedWorkflowAction) {
        const output = 'Rejected: a delivery was already submitted in this turn.';
        const record = recordWorkflowTool('submit_delivery', params, { accepted: false, output });
        return { content: [{ type: 'text', text: output }], details: record };
      }
      acceptedWorkflowAction = {
        action: 'delivery',
        summary: String(params.summary || '').trim(),
        checks: params.checks || [],
      };
      const output = 'Accepted. The coding delivery has been submitted; end this turn now.';
      const record = recordWorkflowTool('submit_delivery', params, { accepted: true, output });
      return { content: [{ type: 'text', text: output }], details: record, terminate: true };
    },
  };
  const settingsManager = SettingsManager.inMemory({
    compaction: { enabled: true },
    retry: { enabled: true, maxRetries: 5 },
  });
  const cwd = runtimeBacked
    ? input.runtime_workspace || '/workspace/project'
    : mappedReadBacked
      ? mappedWorkingDirectory(input)
      : input.host_workdir || process.cwd();
  let nativeTools = [];
  if (runtimeBacked) {
    const operations = dockerFileOperations(input, IMAGE_MIME);
    nativeTools = (auditSession || clarificationSession || sessionKind === 'private_review') ? [createReadToolDefinition(cwd, { operations: operations.read })] : [
      createReadToolDefinition(cwd, { operations: operations.read }),
      createBashToolDefinition(cwd, { operations: dockerBashOperations(input) }),
      createEditToolDefinition(cwd, { operations: operations.edit }),
      createWriteToolDefinition(cwd, { operations: operations.write }),
    ];
  } else if ((clarificationSession || auditSession || sessionKind === 'private_review') && mappedReadBacked) {
    nativeTools = [createReadToolDefinition(cwd, { operations: confinedReadOperations(input, IMAGE_MIME) })];
  }
  const workflowTools = codingSession
    ? [submitDelivery]
    : clarificationSession
      ? [messageClient, finishClarification]
      : auditSession
        ? [submitAuditAnswers]
        : [];
  const customTools = [...nativeTools, ...workflowTools];
  const sessionResult = await createAgentSession({
    cwd,
    agentDir: input.agent_dir || '/tmp/sweclar-pi-agent',
    authStorage,
    modelRegistry: registry,
    model,
    thinkingLevel,
    // "all" disables custom workflow tools as well as Pi's built-ins.  A
    // clarification/audit session can legitimately have no native file tools,
    // but it must still be able to call message_client, finish_clarification, or
    // submit_audit_answers.  Disable only Pi's built-ins whenever SWE-Clar supplies
    // any custom tool.
    noTools: customTools.length ? 'builtin' : codingSession ? undefined : 'all',
    customTools,
    resourceLoader: buildResourceLoader(systemPrompt),
    sessionManager: SessionManager.inMemory(cwd),
    settingsManager,
  });
  const session = sessionResult.session;
  // Pi's simple provider defaults cap requests at 32k unless this option is
  // explicit. The registered model carries the pinned experiment budget.
  const nativeStream = session.agent.streamFn;
  session.agent.streamFn = (activeModel, context, options) =>
    nativeStream(activeModel, context, { ...options, maxTokens: activeModel.maxTokens });

  // MiniMax's OpenAI-compatible endpoint supports the same split reasoning
  // fields used by SWE-Clar's native client. Pi exposes the payload hook through
  // its underlying Agent, so the backend remains Pi while retaining the
  // provider's structured reasoning/tool-call response.
  session.agent.onPayload = payload => {
    const next = withOutputBudget(payload, model, config);
    if (model.api === 'anthropic-messages' && config.anthropic_effort) {
      delete next.thinking;
      next.output_config = {...next.output_config, effort: config.anthropic_effort};
    }
    requestSettings.push({model:model.id, api:model.api, thinking_level:thinkingLevel,
      reasoning:next.reasoning ?? null, reasoning_effort:next.reasoning_effort ?? null,
      thinking:next.thinking ?? null, output_config:next.output_config ?? null, max_tokens:next.max_tokens ?? null, max_completion_tokens:next.max_completion_tokens ?? null, max_output_tokens:next.max_output_tokens ?? null, configured_output_budget:config.model_max_output_tokens ?? model.maxTokens});
    // Audit can read public inputs and submit answers, but cannot execute or
    // modify files. Require some available tool, not specifically submission:
    // public-source inspection must remain possible before the final answer.
    // GLM 5.2 uses the same guard for Clarification workflow/tool actions.
    if (
      (clarificationSession || auditSession) &&
      !acceptedWorkflowAction &&
      Array.isArray(next.tools) &&
      next.tools.length > 0
    ) {
      if (model.api === 'openai-completions' && (auditSession || model.id.includes('glm-5p2'))) {
        next.tool_choice = 'required';
      }
    }
    if ((config.base_url || '').toLowerCase().includes('minimax')) {
      next.reasoning_split = true;
      if (config.thinking === 'adaptive' || config.thinking === 'disabled') {
        next.thinking = { type: config.thinking };
      }
    }
    if (config.top_p !== undefined && config.top_p !== null) next.top_p = config.top_p;
    if (config.temperature !== undefined && config.temperature !== null)
      next.temperature = config.temperature;
    return next;
  };

  const nativeToolCalls = new Map();
  const nativeToolNames = new Set(['read', 'bash', 'edit', 'write']);
  session.subscribe(event => {
    const type = event?.type;
    if (!type) return;
    if (type === 'message_update') {
      // Some gateways emit empty or duplicate keep-alive updates while the
      // request itself is wedged. Only content-changing deltas are progress;
      // otherwise those heartbeats can postpone the idle timeout forever.
      if (messageProgressGate.observe(event.message)) {
        requestIdleWatchdog.touch();
      }
      // Provider deltas can arrive token-by-token. Throttle persistence to a
      // readable cadence while keeping the latest assistant text/thinking
      // available to the Workspace during a long model turn.
      const now = Date.now();
      if (now - lastMessageProgressMs >= 250) {
        lastMessageProgressMs = now;
        emitProgress({
          event: 'assistant_update',
          assistant: assistantSummary(event.message),
        });
      }
      return;
    }
    if (
      type === 'tool_execution_start' ||
      type === 'tool_execution_end' ||
      type === 'turn_start' ||
      type === 'turn_end'
    ) {
      requestIdleWatchdog.touch();
    }
    const summary = { type };
    if (type === 'tool_execution_start') {
      summary.tool_call_id = event.toolCallId;
      summary.tool_name = event.toolName;
      summary.args = event.args || {};
      if (nativeToolNames.has(event.toolName)) {
        nativeToolCalls.set(event.toolCallId, {
          tool: event.toolName,
          input: event.args || {},
          started_at: new Date().toISOString(),
          started_ms: Date.now(),
        });
      }
      emitProgress({ event: 'tool_started', trace: summary });
    } else if (type === 'tool_execution_end') {
      summary.tool_call_id = event.toolCallId;
      summary.tool_name = event.toolName;
      summary.is_error = Boolean(event.isError);
      if (nativeToolNames.has(event.toolName)) {
        const started = nativeToolCalls.get(event.toolCallId) || {
          tool: event.toolName,
          input: {},
          started_at: new Date().toISOString(),
          started_ms: Date.now(),
        };
        const record = {
          tool: started.tool,
          input: started.input,
          output: clip(textFromContent(event.result?.content)),
          is_error: Boolean(event.isError),
          details: event.result?.details || null,
          started_at: started.started_at,
          completed_at: new Date().toISOString(),
          duration_ms: Date.now() - started.started_ms,
        };
        nativeToolCalls.delete(event.toolCallId);
        toolEvents.push(record);
        emitProgress({
          event: 'tool_completed',
          tool_event: record,
          tool_call_count: toolEvents.length,
        });
      }
      emitProgress({ event: 'tool_ended', trace: summary });
    } else if (type === 'turn_start') {
      messageProgressGate.reset();
      currentTurn = { turn_index: turns.length + 1, started_at: new Date().toISOString() };
      emitProgress({ event: 'turn_started', turn: currentTurn });
    } else if (type === 'turn_end') {
      const assistant = assistantSummary(event.message);
      const toolResults = (event.toolResults || []).map(toolResultSummary).filter(Boolean);
      const turn = {
        ...(currentTurn || { turn_index: turns.length + 1 }),
        completed_at: new Date().toISOString(),
        assistant,
        tool_results: toolResults,
      };
      turns.push(turn);
      currentTurn = null;
      emitProgress({
        event: 'turn_completed',
        turn,
        turn_count: turns.length,
        tool_call_count: toolEvents.length,
      });
    }
    eventTrace.push(summary);
  });

  requestIdleWatchdog.start();
  try {
    await session.prompt(String(input.user_prompt || ''));
    const lastAssistant = [...session.messages].reverse().find(message => message?.role === 'assistant');
    const reminder = workflowReminder(sessionKind, lastAssistant?.stopReason, acceptedWorkflowAction);
    if (reminder) {
      emitProgress({event: 'workflow_protocol_reminder', session_kind: sessionKind, attempt: 1});
      await session.prompt(reminder);
    }
  } finally {
    requestIdleWatchdog.stop();
  }
  const messages = session.messages;
  const assistants = messages.filter(message => message?.role === 'assistant');
  const finalAssistant =
    [...assistants].reverse().find(message => message.stopReason !== 'toolUse') ||
    assistants.at(-1);
  const finalSummary = assistantSummary(finalAssistant);
  const usage = assistants.reduce(
    (total, message) => {
      const value = message.usage || {};
      total.input_tokens += Number(value.input || 0);
      total.output_tokens += Number(value.output || 0);
      total.cache_read_tokens += Number(value.cacheRead || 0);
      total.cache_write_tokens += Number(value.cacheWrite || 0);
      total.llm_calls += 1;
      total.cost += Number(value.cost?.total || 0);
      return total;
    },
    {
      input_tokens: 0,
      output_tokens: 0,
      cache_read_tokens: 0,
      cache_write_tokens: 0,
      llm_calls: 0,
      cost: 0,
    }
  );
  usage.latency_s = 0;
  const refusal = await observedRefusal();
  if (refusal) throw Object.assign(new Error('Provider refused the request'), {refusal});
  if (finalAssistant?.stopReason === 'error') {
    throw new Error(finalAssistant.errorMessage || 'Pi returned an error response');
  }
  return {
    ok: true,
    backend: 'pi-coding-agent',
    backend_version: '0.73.1',
    request_settings: requestSettings,
    final_text: finalSummary?.text || '',
    final_message: finalSummary,
    messages,
    turns,
    event_trace: eventTrace,
    tool_events: toolEvents,
    tool_call_count: toolEvents.length,
    turn_count: turns.length,
    usage,
    workflow_action: acceptedWorkflowAction,
  };
}

let raw = '';
for await (const chunk of process.stdin) raw += chunk;
try {
  const input = JSON.parse(raw || '{}');
  const result = await main(input);
  // OAuth transports and provider SDKs may retain refresh timers or sockets.
  // The Python owner treats process EOF as the durable completion boundary,
  // so waiting for Node's event loop can leave a completed run shown as
  // "running" indefinitely. Flush the one final envelope, then exit cleanly.
  await new Promise((resolve, reject) => {
    process.stdout.write(`${JSON.stringify({ kind: 'pi_result', result })}\n`, error =>
      error ? reject(error) : resolve()
    );
  });
  process.exit(0);
} catch (error) {
  const refusal = error?.refusal || await observedRefusal();
  process.stderr.write(`${error?.stack || error}\n`);
  await new Promise(resolve => {
    process.stdout.write(
      `${JSON.stringify({
        kind: 'pi_result',
        result: {
          ok: false,
          refusal,
          error: String(error?.message || error),
        },
      })}\n`,
      resolve
    );
  });
  process.exit(1);
}
