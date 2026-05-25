const MONITOR_EVENT_TYPES = [
  "monitor_connected",
  "analysis_requested",
  "workflow_started",
  "agent_started",
  "agent_completed",
  "agent_failed",
  "correction_rerun_started",
  "workflow_completed",
  "response_ready",
  "analysis_failed",
];

const state = {
  streamRunId: new URLSearchParams(window.location.search).get("monitor_run_id") || "workbench_live",
  activeRunId: "",
  events: [],
  source: null,
};

const el = {
  runLabel: document.querySelector("#monitor-run-label"),
  eventCount: document.querySelector("#monitor-event-count"),
  agentCount: document.querySelector("#monitor-agent-count"),
  toolCount: document.querySelector("#monitor-tool-count"),
  eventList: document.querySelector("#monitor-event-list"),
  parsed: document.querySelector("#monitor-parsed"),
  json: document.querySelector("#monitor-json"),
  finalStatus: document.querySelector("#monitor-final-status"),
  streamStatus: document.querySelector("#monitor-stream-status"),
  clearButton: document.querySelector("#monitor-clear"),
};

el.clearButton.addEventListener("click", () => {
  state.events = [];
  state.activeRunId = "";
  render();
});

connect();
render();

function connect() {
  if (!window.EventSource) {
    el.streamStatus.textContent = "浏览器不支持实时流";
    return;
  }
  state.source = new EventSource(`/api/data-agent/monitor/stream?monitor_run_id=${encodeURIComponent(state.streamRunId)}`);
  MONITOR_EVENT_TYPES.forEach((type) => state.source.addEventListener(type, handleEvent));
  state.source.onerror = () => {
    el.streamStatus.textContent = "连接重试中";
  };
}

function handleEvent(event) {
  try {
    addEvent(JSON.parse(event.data));
  } catch {
    addEvent({
      event_id: `evt_parse_${Date.now()}`,
      monitor_run_id: state.activeRunId || state.streamRunId,
      event_type: "client_error",
      title: "事件解析失败",
      summary: "收到了一条无法解析的实时事件。",
      role: "",
      stage: "client",
      status: "failed",
      created_at: new Date().toISOString(),
      elapsed_ms: 0,
      payload: { data: String(event.data || "") },
    });
  }
}

function addEvent(event) {
  const eventId = event.event_id || `${event.event_type || "event"}_${Date.now()}_${state.events.length}`;
  if (state.events.some((item) => item.event_id === eventId)) return;
  state.events.push({ ...event, event_id: eventId });
  state.events = state.events.slice(-260);
  if (event.monitor_run_id && event.monitor_run_id !== "workbench_live") {
    state.activeRunId = event.monitor_run_id;
  }
  render();
}

function render() {
  const events = currentEvents();
  const finalPayload = latestFinalPayload(events);
  const roles = new Set(events.filter((event) => event.role).map((event) => event.role));
  const toolCount = events.reduce((sum, event) => sum + Number(event.payload?.new_tool_calls?.length || event.payload?.tool_call_summary?.length || 0), 0);
  const finalTools = finalPayload?.debug?.tool_call_summaries || finalPayload?.tool_call_summary || [];
  el.runLabel.textContent = state.activeRunId
    ? `${state.activeRunId} / ${monitorStatusLabel(events, finalPayload)}`
    : state.streamRunId === "workbench_live"
      ? "全局监听：/workbench-monitor"
      : `监听：${state.streamRunId}`;
  el.streamStatus.textContent = state.source ? "实时连接" : "未连接";
  el.eventCount.textContent = String(events.length);
  el.agentCount.textContent = String(Math.max(roles.size, (finalPayload?.debug?.agent_task_results || finalPayload?.agent_task_results || []).length));
  el.toolCount.textContent = String(Math.max(toolCount, finalTools.length));
  el.finalStatus.textContent = finalPayload
    ? finalPayload.success === false
      ? "有错误"
      : "已完成"
    : events.some((event) => event.status === "failed")
      ? "有错误"
      : events.length
        ? "运行中"
        : "暂无结果";
  renderEvents(events);
  renderParsed(finalPayload, events);
  el.json.textContent = formatJsonPreview(finalPayload || events.at(-1) || {});
}

function currentEvents() {
  if (!state.activeRunId) return state.events;
  return state.events.filter((event) => event.monitor_run_id === state.activeRunId || event.event_type === "monitor_connected");
}

function latestFinalPayload(events) {
  for (const event of [...events].reverse()) {
    if (event.payload?.response) return event.payload.response;
    if (event.event_type === "workflow_completed" || event.event_type === "response_ready") return event.payload;
  }
  return null;
}

function renderEvents(events) {
  if (!events.length) {
    el.eventList.innerHTML = `<li class="monitor-empty">运行开始后显示每个 agent、工具和环节事件。</li>`;
    return;
  }
  el.eventList.innerHTML = events
    .map(
      (event) => `
        <li class="monitor-event ${escapeHtml(event.status || "completed")}">
          <details>
            <summary>
              <span class="monitor-event-dot"></span>
              <span class="monitor-event-main">
                <strong>${escapeHtml(event.title || event.event_type || "事件")}</strong>
                <span>${escapeHtml([monitorRoleName(event.role), event.stage, formatElapsed(event.elapsed_ms)].filter(Boolean).join(" / "))}</span>
              </span>
            </summary>
            <p>${escapeHtml(event.summary || "")}</p>
            <pre>${escapeHtml(formatJsonPreview(event.payload || {}, 9000))}</pre>
          </details>
        </li>
      `,
    )
    .join("");
}

function renderParsed(payload, events) {
  if (!payload) {
    const running = events.filter((event) => event.event_type?.startsWith("agent_"));
    if (!running.length) {
      el.parsed.className = "monitor-parsed empty-state";
      el.parsed.textContent = "这里会把长 JSON 拆成 agent 流、工具调用和阶段摘要。";
      return;
    }
    el.parsed.className = "monitor-parsed";
    el.parsed.innerHTML = renderLiveAgentFlow(running);
    return;
  }
  el.parsed.className = "monitor-parsed";
  const sections = [
    renderFinalAgentFlow(payload),
    renderFinalToolCalls(payload),
    renderFinalTraceSteps(payload),
    renderFinalDataRoute(payload),
  ].filter(Boolean);
  el.parsed.innerHTML = sections.join("") || `<div class="empty-state">本次响应没有可解析的 agent 明细。</div>`;
}

function renderLiveAgentFlow(events) {
  const items = events.slice(-30).map((event) => ({
    role: event.role || event.stage || event.event_type,
    status: event.status || "active",
    summary: event.summary || "",
    confidence: event.payload?.result?.confidence,
  }));
  return `<div class="monitor-flow">${items.map(renderAgentPill).join("")}</div>`;
}

function renderFinalAgentFlow(payload) {
  const roles = payload.debug?.agent_task_results || payload.agent_task_results || [];
  if (!roles.length) return "";
  return `
    <div class="monitor-subsection">
      <h3>Agent 流</h3>
      <div class="monitor-flow">${roles.map(renderAgentPill).join("")}</div>
    </div>
  `;
}

function renderAgentPill(item) {
  const status = item.success === false || item.status === "failed" ? "failed" : item.status === "active" ? "active" : "completed";
  const confidence = item.confidence === undefined || item.confidence === null ? "" : `confidence ${Number(item.confidence).toFixed(2)}`;
  const issues = (item.issues || []).slice(0, 2).join("；");
  return `
    <div class="monitor-agent-pill ${escapeHtml(status)}">
      <strong>${escapeHtml(monitorRoleName(item.role))}</strong>
      <span>${escapeHtml(confidence || status)}</span>
      ${issues ? `<p>${escapeHtml(issues)}</p>` : ""}
    </div>
  `;
}

function renderFinalToolCalls(payload) {
  const tools = payload.debug?.tool_call_summaries || payload.tool_call_summary || [];
  if (!tools.length) return "";
  return `
    <div class="monitor-subsection">
      <h3>工具调用</h3>
      <div class="monitor-tool-list">
        ${tools
          .map(
            (tool) => `
              <div class="monitor-tool-row ${tool.success ? "completed" : "failed"}">
                <strong>${escapeHtml(monitorRoleName(tool.requested_by))} -> ${escapeHtml(tool.tool_name || "-")}</strong>
                <span>${escapeHtml(tool.success ? "pass" : "fail")} ${tool.latency_ms ? `/ ${formatNumber(tool.latency_ms)}ms` : ""}</span>
                <p>入参：${escapeHtml(formatJsonPreview(tool.arguments_summary || {}, 900))}</p>
                <p>结果：${escapeHtml(formatJsonPreview(tool.result_summary || {}, 900))}</p>
              </div>
            `,
          )
          .join("")}
      </div>
    </div>
  `;
}

function renderFinalTraceSteps(payload) {
  const steps = payload.reasoning_trace_view || [];
  if (!steps.length) return "";
  return `
    <div class="monitor-subsection">
      <h3>阶段摘要</h3>
      <div class="monitor-step-list">
        ${steps
          .map(
            (step) => `
              <div class="monitor-step-row ${escapeHtml(step.status || "completed")}">
                <strong>${escapeHtml(step.name || step.step_id || "-")}</strong>
                <p>${escapeHtml(step.summary || "")}</p>
                ${step.warnings?.length ? `<span>${escapeHtml(step.warnings.slice(0, 2).join("；"))}</span>` : ""}
              </div>
            `,
          )
          .join("")}
      </div>
    </div>
  `;
}

function renderFinalDataRoute(payload) {
  const debug = payload.debug || {};
  const logicForm = payload.logic_form || {};
  const parts = [
    ["Run", payload.run_id],
    ["模式", debug.agent_mode || payload.agent_mode],
    ["执行", payload.execution_mode],
    ["操作", debug.operation || logicForm.operation],
    ["数据表", (debug.source_tables || logicForm.source_tables || payload.source_tables || []).join("、")],
    ["选表原因", debug.table_selection_reason || logicForm.table_selection_reason],
    ["Join", formatJsonPreview(debug.join_plan || logicForm.join_plan || {}, 900)],
    ["Trace", debug.trace_path],
  ].filter(([, value]) => value !== undefined && value !== null && value !== "" && value !== "{}");
  if (!parts.length) return "";
  return `
    <div class="monitor-subsection">
      <h3>路由与交互</h3>
      <dl class="monitor-route-list">
        ${parts.map(([key, value]) => `<dt>${escapeHtml(key)}</dt><dd>${escapeHtml(value)}</dd>`).join("")}
      </dl>
    </div>
  `;
}

function monitorStatusLabel(events, payload) {
  if (payload) return payload.success === false ? "有错误" : "已完成";
  if (events.some((event) => event.status === "failed")) return "有错误";
  if (events.length) return "运行中";
  return "等待事件";
}

function monitorRoleName(role) {
  const names = {
    planner: "Planner",
    data_engineer: "Data Engineer",
    pandas_executor: "Pandas Executor",
    sql_executor: "SQL Executor",
    verifier: "Verifier",
    correction: "Correction",
    insight: "Insight",
    visualization: "Visualization",
    response_builder: "Response Builder",
    single_agent: "Single Agent",
  };
  return names[role] || role || "";
}

function formatElapsed(value) {
  const number = Number(value);
  if (!Number.isFinite(number) || number <= 0) return "";
  return number >= 1000 ? `${(number / 1000).toFixed(1)}s` : `${Math.round(number)}ms`;
}

function formatJsonPreview(value, limit = 22000) {
  let text = "";
  try {
    text = JSON.stringify(value ?? {}, null, 2);
  } catch {
    text = String(value ?? "");
  }
  return text.length > limit ? `${text.slice(0, limit)}\n... 截断 ${text.length - limit} 个字符` : text;
}

function formatNumber(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return String(value ?? "-");
  return Math.abs(number) >= 1000 ? number.toLocaleString("zh-CN", { maximumFractionDigits: 1 }) : String(Number(number.toFixed(2)));
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}
