const MONITOR_EVENT_TYPES = [
  "monitor_connected",
  "message_requested",
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
  activeRunId: new URLSearchParams(window.location.search).get("monitor_run_id") || "",
  selectedByUser: Boolean(new URLSearchParams(window.location.search).get("monitor_run_id")),
  events: [],
  source: null,
};

const el = {
  runLabel: document.querySelector("#monitor-run-label"),
  eventCount: document.querySelector("#monitor-event-count"),
  agentCount: document.querySelector("#monitor-agent-count"),
  toolCount: document.querySelector("#monitor-tool-count"),
  messageList: document.querySelector("#monitor-message-list"),
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
  state.selectedByUser = false;
  try {
    window.localStorage.removeItem("vds-monitor-runs");
    window.localStorage.removeItem("vds-active-monitor-run");
  } catch {
    // Storage is optional.
  }
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
  if (!state.selectedByUser && event.monitor_run_id && event.monitor_run_id !== "workbench_live") {
    state.activeRunId = event.monitor_run_id;
  }
  render();
}

function render() {
  const runRecords = monitorRunRecords();
  if (!state.activeRunId && runRecords.length) {
    state.activeRunId = runRecords[0].monitor_run_id;
  }
  const events = currentEvents();
  const finalPayload = latestFinalPayload(events);
  const activeRecord = runRecords.find((record) => record.monitor_run_id === state.activeRunId) || null;
  const roles = new Set(events.filter((event) => event.role).map((event) => event.role));
  const toolCount = events.reduce((sum, event) => sum + Number(event.payload?.new_tool_calls?.length || event.payload?.tool_call_summary?.length || 0), 0);
  const finalTools = finalPayload?.debug?.tool_call_summaries || finalPayload?.tool_call_summary || [];
  el.runLabel.textContent = state.activeRunId
    ? `${messageTitle(activeRecord, events)} / ${monitorStatusLabel(events, finalPayload)}`
    : state.streamRunId === "workbench_live"
      ? "全局监听：/monitor"
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
  renderMessages(runRecords);
  renderEvents(events);
  renderParsed(finalPayload, events, activeRecord);
  el.json.textContent = formatJsonPreview(finalPayload || events.at(-1) || {});
}

function currentEvents() {
  if (!state.activeRunId) return state.events;
  if (state.activeRunId === "workbench_live") return state.events;
  return state.events.filter((event) => event.monitor_run_id === state.activeRunId || event.event_type === "monitor_connected");
}

function monitorRunRecords() {
  const byId = new Map();
  readMonitorRunStorage().forEach((record) => {
    if (record?.monitor_run_id) byId.set(record.monitor_run_id, normalizeRunRecord(record));
  });
  state.events.forEach((event) => {
    const runId = event.monitor_run_id;
    if (!runId || runId === "workbench_live") return;
    const current = byId.get(runId) || { monitor_run_id: runId };
    const payload = event.payload || {};
    byId.set(runId, {
      ...current,
      monitor_run_id: runId,
      question: current.question || payload.question || payload.state_before?.question || "",
      dataset_id: current.dataset_id || payload.dataset_id || payload.state_before?.dataset_id || "",
      conversation_id: current.conversation_id || payload.conversation_id || "",
      execution_mode: current.execution_mode || payload.execution_mode || "",
      agent_mode: current.agent_mode || payload.agent_mode || "",
      status: event.status === "failed" ? "failed" : current.status || (isRunFinished(event) ? "completed" : "running"),
      created_at: current.created_at || event.created_at,
      updated_at: event.created_at || current.updated_at || current.created_at,
    });
  });
  if (state.streamRunId && state.streamRunId !== "workbench_live" && !byId.has(state.streamRunId)) {
    byId.set(state.streamRunId, { monitor_run_id: state.streamRunId, status: "running" });
  }
  return [...byId.values()]
    .map(normalizeRunRecord)
    .sort((a, b) => String(b.updated_at || b.created_at || "").localeCompare(String(a.updated_at || a.created_at || "")));
}

function readMonitorRunStorage() {
  const records = [];
  try {
    const list = JSON.parse(window.localStorage.getItem("vds-monitor-runs") || "[]");
    if (Array.isArray(list)) records.push(...list);
    const active = JSON.parse(window.localStorage.getItem("vds-active-monitor-run") || "null");
    if (active?.monitor_run_id && !records.some((record) => record?.monitor_run_id === active.monitor_run_id)) {
      records.unshift(active);
    }
  } catch {
    // Storage is optional; live events are still enough for current runs.
  }
  return records;
}

function normalizeRunRecord(record) {
  return {
    monitor_run_id: String(record?.monitor_run_id || ""),
    conversation_id: String(record?.conversation_id || ""),
    conversation_title: String(record?.conversation_title || ""),
    question: String(record?.question || ""),
    answer: String(record?.answer || ""),
    answer_type: String(record?.answer_type || ""),
    dataset_id: String(record?.dataset_id || ""),
    execution_mode: String(record?.execution_mode || ""),
    agent_mode: String(record?.agent_mode || ""),
    status: String(record?.status || "running"),
    error: String(record?.error || ""),
    created_at: String(record?.created_at || ""),
    updated_at: String(record?.updated_at || record?.created_at || ""),
  };
}

function isRunFinished(event) {
  return event.event_type === "response_ready" || event.event_type === "workflow_completed" || event.event_type === "analysis_failed";
}

function renderMessages(records) {
  if (!records.length) {
    el.messageList.innerHTML = `<li class="monitor-empty">从 Workbench 发送消息后，这里会按对话列出每一条消息。</li>`;
    return;
  }
  const groups = groupedRunRecords(records);
  el.messageList.innerHTML = groups
    .map(
      (group) => `
        <li class="monitor-conversation-group">
          <div class="monitor-conversation-title">
            <strong>${escapeHtml(group.title)}</strong>
            <span>${group.records.length} 条消息</span>
          </div>
          <ol>
            ${group.records.map((record, index) => renderMessageButton(record, index)).join("")}
          </ol>
        </li>
      `,
    )
    .join("");
  el.messageList.querySelectorAll("[data-monitor-run-id]").forEach((button) => {
    button.addEventListener("click", () => {
      state.activeRunId = button.getAttribute("data-monitor-run-id") || "";
      state.selectedByUser = true;
      render();
    });
  });
}

function groupedRunRecords(records) {
  const groups = new Map();
  records.forEach((record) => {
    const key = record.conversation_id || record.dataset_id || "ungrouped";
    const group = groups.get(key) || {
      key,
      title: record.conversation_title || (record.conversation_id ? `对话 ${shortId(record.conversation_id)}` : record.dataset_id ? `数据集 ${shortId(record.dataset_id)}` : "未归属对话"),
      records: [],
      updated_at: "",
    };
    group.records.push(record);
    group.updated_at = [group.updated_at, record.updated_at || record.created_at].sort().at(-1) || "";
    groups.set(key, group);
  });
  return [...groups.values()]
    .map((group) => ({
      ...group,
      records: group.records.sort((a, b) => String(a.created_at || "").localeCompare(String(b.created_at || ""))),
    }))
    .sort((a, b) => String(b.updated_at).localeCompare(String(a.updated_at)));
}

function renderMessageButton(record, index) {
  const active = record.monitor_run_id === state.activeRunId ? " active" : "";
  const failed = record.status === "failed" ? " failed" : "";
  const question = record.question || "这条消息暂时没有问题文本";
  const meta = [formatTime(record.created_at), record.dataset_id ? `数据 ${shortId(record.dataset_id)}` : "", record.answer_type ? readableAnswerType(record.answer_type) : ""]
    .filter(Boolean)
    .join(" / ");
  return `
    <li>
      <button class="monitor-message-button${active}${failed}" type="button" data-monitor-run-id="${escapeHtml(record.monitor_run_id)}">
        <span>消息 ${index + 1}</span>
        <strong>${escapeHtml(question)}</strong>
        <em>${escapeHtml(meta || record.monitor_run_id)}</em>
      </button>
    </li>
  `;
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

function renderParsed(payload, events, activeRecord = null) {
  const nodeCards = renderNodeExplanations(payload, events);
  if (!payload) {
    const running = events.filter((event) => event.event_type?.startsWith("agent_"));
    if (!running.length) {
      el.parsed.className = "monitor-parsed empty-state";
      el.parsed.textContent = "运行后会按顺序显示每个节点：收到什么、做了什么、发出什么。";
      return;
    }
    el.parsed.className = "monitor-parsed";
    el.parsed.innerHTML = [renderSelectedMessageSummary(activeRecord, payload, events), nodeCards || renderLiveAgentFlow(running)].filter(Boolean).join("");
    return;
  }
  el.parsed.className = "monitor-parsed";
  const sections = [
    renderSelectedMessageSummary(activeRecord, payload, events),
    nodeCards,
    nodeCards ? "" : renderFinalTraceSteps(payload),
  ].filter(Boolean);
  el.parsed.innerHTML = sections.join("") || `<div class="empty-state">请选择左侧某一条消息查看节点。</div>`;
}

function renderSelectedMessageSummary(record, payload, events) {
  const question = record?.question || events.find((event) => event.payload?.question)?.payload?.question || "";
  const answer = record?.answer || payload?.answer || "";
  const status = monitorStatusLabel(events, payload);
  const meta = [
    record?.conversation_id ? `对话 ${shortId(record.conversation_id)}` : "",
    record?.dataset_id || payload?.dataset_id ? `数据 ${shortId(record?.dataset_id || payload?.dataset_id)}` : "",
    record?.answer_type || payload?.answer_type ? `回答 ${readableAnswerType(record?.answer_type || payload?.answer_type)}` : "",
  ].filter(Boolean);
  if (!question && !answer && !meta.length) return "";
  return `
    <section class="monitor-selected-message">
      <header>
        <span>${escapeHtml(status)}</span>
        <strong>${escapeHtml(question || "当前消息")}</strong>
      </header>
      ${answer ? `<p>${escapeHtml(answer)}</p>` : ""}
      ${meta.length ? `<div>${meta.map((item) => `<em>${escapeHtml(item)}</em>`).join("")}</div>` : ""}
    </section>
  `;
}

function renderNodeExplanations(payload, events) {
  const completed = agentCompletedEvents(events);
  if (!completed.length) return "";
  return `
    <div class="monitor-subsection">
      <h3>节点解释：收到 -> 处理 -> 发出</h3>
      <p class="monitor-subsection-note">这里按真实执行顺序解释每个节点。上游是它收到信息的来源，下游是它把结果交给谁；原始 JSON 收在每张卡片底部。</p>
      ${renderNodePath(completed)}
      <div class="monitor-node-list">
        ${completed.map((event, index) => renderNodeCard(event, index, payload, completed)).join("")}
      </div>
    </div>
  `;
}

function agentCompletedEvents(events) {
  const startedByStage = new Map();
  const completed = [];
  events.forEach((event) => {
    if (!event.role) return;
    const key = `${event.stage || event.role}:${event.role}`;
    if (event.event_type === "agent_started") {
      startedByStage.set(key, event);
      return;
    }
    if (event.event_type !== "agent_completed") return;
    const started = startedByStage.get(key);
    completed.push({
      ...event,
      payload: {
        ...(event.payload || {}),
        state_before: event.payload?.state_before || started?.payload?.state_before || {},
      },
    });
  });
  return completed;
}

function renderNodePath(events) {
  const labels = events.map((event) => monitorRoleName(event.role));
  if (!labels.length) return "";
  return `
    <div class="monitor-node-path" aria-label="节点执行顺序">
      ${labels.map((label) => `<span>${escapeHtml(label)}</span>`).join("")}
    </div>
  `;
}

function renderNodeCard(event, index, payload, completedEvents) {
  const role = event.role || "";
  const details = buildNodeDetails(event, payload);
  const status = event.status === "failed" || details.failed ? "failed" : "completed";
  const upstream = index === 0 ? "用户问题 / 数据集" : monitorRoleName(completedEvents[index - 1]?.role);
  const downstream = index === completedEvents.length - 1 ? "最终页面 / API" : monitorRoleName(completedEvents[index + 1]?.role);
  return `
    <article class="monitor-node-card ${escapeHtml(status)}">
      <header>
        <span>${String(index + 1).padStart(2, "0")}</span>
        <div>
          <h4>${escapeHtml(monitorRoleName(role))}</h4>
          <p>${escapeHtml(details.purpose)}</p>
        </div>
        <strong class="monitor-node-status">${escapeHtml(status === "failed" ? "异常" : "完成")}</strong>
      </header>
      <div class="monitor-node-transfer">
        <span>上游：${escapeHtml(upstream)}</span>
        <span>当前：${escapeHtml(monitorRoleName(role))}</span>
        <span>下游：${escapeHtml(downstream)}</span>
      </div>
      <div class="monitor-node-columns">
        ${renderNodeBox("收到什么（输入）", details.received)}
        ${renderNodeBox("干了什么（处理）", details.did)}
        ${renderNodeBox("发出什么（输出）", details.sent)}
      </div>
      ${details.note ? `<p class="monitor-node-note">${escapeHtml(details.note)}</p>` : ""}
      <details class="monitor-node-raw">
        <summary>查看这个节点的安全事件 JSON</summary>
        <pre>${escapeHtml(formatJsonPreview(event.payload || {}, 12000))}</pre>
      </details>
    </article>
  `;
}

function renderNodeBox(title, lines) {
  const items = (lines || []).filter(Boolean);
  return `
    <section class="monitor-node-box">
      <h5>${escapeHtml(title)}</h5>
      ${
        items.length
          ? `<ul>${items.map((line) => `<li>${escapeHtml(line)}</li>`).join("")}</ul>`
          : `<p>没有新的可读信息。</p>`
      }
    </section>
  `;
}

function buildNodeDetails(event, finalPayload) {
  const role = event.role || "";
  const payload = event.payload || {};
  const task = payload.task || {};
  const result = payload.result || {};
  const output = result.output_payload || {};
  const before = payload.state_before || {};
  const after = payload.state_after || {};
  const tools = payload.new_tool_calls || [];
  const purpose = rolePurpose(role);
  const fallbackReceived = [
    task.input_payload?.question ? `用户问题：${task.input_payload.question}` : before.question ? `用户问题：${before.question}` : "",
    task.input_payload?.dataset_id || before.dataset_id ? `数据集：${task.input_payload?.dataset_id || before.dataset_id}` : "",
  ];
  const base = {
    purpose,
    received: fallbackReceived,
    did: [event.summary || resultSummary(result), tools.length ? `调用工具：${tools.map((tool) => tool.tool_name).filter(Boolean).join("、")}` : ""],
    sent: readableStateDelta(before, after),
    note: "",
    failed: result.success === false || event.status === "failed",
  };

  if (role === "planner") {
    const logicForm = output.logic_form || after.logic_form || finalPayload?.logic_form || {};
    const plan = output.analysis_plan || after.analysis_plan || {};
    return {
      ...base,
      received: [
        ...fallbackReceived,
        "数据结构：表名、字段名、字段类型和样例值。",
        "用户约束：执行模式、口径提示和当前数据上下文。",
      ],
      did: [
        `判断这是什么分析：${readableOperation(logicForm.operation)}`,
        readableRoute(logicForm),
        `拆成可执行步骤：${readableSteps(plan.steps)}`,
      ],
      sent: [
        logicForm.operation ? `分析口径：${readableOperation(logicForm.operation)}` : "",
        logicForm.source_tables?.length ? `要用的数据表：${logicForm.source_tables.join("、")}` : "",
        readableMetricAndDimension(logicForm),
        plan.steps?.length ? `交给执行节点的步骤：${plan.steps.length} 步` : "",
      ],
      note: "Planner 的输出决定后面 executor 要按什么口径计算。",
    };
  }

  if (role === "data_engineer") {
    const profile = output;
    return {
      ...base,
      received: [
        `数据集：${task.input_payload?.dataset_id || before.dataset_id || "-"}`,
        "已上传的数据文件和表结构。",
      ],
      did: [
        `读取表画像：${readableTables(profile.tables)}`,
        profile.quality_report?.summary ? `数据质量摘要：${profile.quality_report.summary}` : "",
      ],
      sent: [
        profile.tables?.length ? `表和字段摘要：${profile.tables.length} 张表` : "",
        "把数据画像交给后续节点核对字段和口径。",
      ],
      note: "它不回答问题，只负责让后续节点知道数据长什么样。",
    };
  }

  if (role === "pandas_executor") {
    return executionNodeDetails(base, "Pandas", output, before, after);
  }

  if (role === "sql_executor") {
    return executionNodeDetails(base, "SQL", output, before, after);
  }

  if (role === "verifier") {
    const verification = output.verification || after.verification || {};
    return {
      ...base,
      received: [
        before.pandas?.success !== undefined ? `Pandas 结果：${before.pandas.success ? "成功" : "失败"}` : "",
        before.sql?.success !== undefined || before.sql?.skipped !== undefined
          ? `SQL 结果：${before.sql.skipped ? "跳过" : before.sql.success ? "成功" : "失败"}`
          : "",
        `分析口径：${readableOperation(before.operation || finalPayload?.logic_form?.operation)}`,
      ],
      did: [
        `核对执行是否成功：${verification.passed ? "通过" : "未通过"}`,
        verification.pandas_sql_consistent !== undefined ? `Pandas/SQL 是否一致：${verification.pandas_sql_consistent ? "一致" : "不一致"}` : "",
        ...(verification.semantic_verification_notes || []).slice(0, 3),
      ],
      sent: [
        `校验结论：${verification.passed === undefined ? "-" : verification.passed ? "通过" : "未通过"}`,
        verification.issues?.length ? `问题：${verification.issues.join("；")}` : "没有发现需要阻断的校验问题。",
      ],
      note: "Verifier 是防止错口径、错结果直接进入最终回答的关口。",
      failed: verification.passed === false,
    };
  }

  if (role === "correction") {
    const needsCorrection = output.needs_correction;
    return {
      ...base,
      received: [
        after.verification?.passed !== undefined ? `校验结论：${after.verification.passed ? "通过" : "未通过"}` : "",
        after.verification?.issues?.length ? `校验问题：${after.verification.issues.join("；")}` : "校验没有给出必须修正的问题。",
      ],
      did: [
        needsCorrection ? "规划修正方向，并准备让执行节点重跑。" : "判断不需要修正，允许流程继续。",
        output.correction_action ? `修正动作：${formatCompact(output.correction_action)}` : "",
      ],
      sent: [
        needsCorrection ? "发出修正后的分析口径，交给执行节点重跑。" : "不发起重跑，流程进入洞察生成。",
        output.corrected_logic_form ? `修正后的口径：${formatCompact(output.corrected_logic_form)}` : "",
      ],
      note: "Correction 只做有边界的修正规划，不会随意改代码或访问标准答案。",
    };
  }

  if (role === "insight") {
    const insight = output.insight || after.insight || finalPayload?.insight || {};
    return {
      ...base,
      received: [
        after.verification?.passed !== undefined ? `已验证结果：${after.verification.passed ? "可信" : "不可信"}` : "",
        after.pandas?.row_count !== undefined ? `结果行数：${after.pandas.row_count}` : "",
      ],
      did: [
        insight.summary ? `提炼结论：${insight.summary}` : "根据已验证结果生成业务摘要。",
        insight.caveats?.length ? `限制说明：${insight.caveats.slice(0, 2).join("；")}` : "",
      ],
      sent: [
        insight.summary ? "insight.summary 已交给最终回答节点。" : "",
        insight.suggestions?.length ? `建议：${insight.suggestions.slice(0, 2).join("；")}` : "",
      ],
      note: "Insight 不能重新计算，只能基于已验证结果解释。",
    };
  }

  if (role === "visualization") {
    const chart = output.chart || after.chart || finalPayload?.chart || {};
    return {
      ...base,
      received: [
        after.pandas?.row_count !== undefined ? `可展示结果：${after.pandas.row_count} 行` : "",
        after.operation ? `分析类型：${after.operation}` : "",
      ],
      did: [
        chart.chart_type ? `选择图表：${chart.chart_type}` : "判断本次是否适合生成图表。",
        chart.x || chart.y ? `编码字段：x=${chart.x || "-"}，y=${chart.y || "-"}` : "",
      ],
      sent: [
        chart.chart_type ? `chart spec：${chart.title || chart.chart_type}` : "没有生成图表配置。",
        chart.reason ? `选择原因：${chart.reason}` : "",
      ],
      note: "Visualization 只输出图表配置，前端负责渲染。",
    };
  }

  if (role === "response_builder") {
    const finalResponse = payload.final_response || finalPayload || {};
    return {
      ...base,
      received: [
        "已验证的计算结果、洞察、图表配置、错误和 warnings。",
        finalPayload?.debug?.trace_path ? `Trace 文件：${finalPayload.debug.trace_path}` : "",
      ],
      did: [
        "把内部结果整理成稳定 API 响应。",
        finalResponse.answer ? `最终答案：${finalResponse.answer}` : "",
      ],
      sent: [
        `回答类型：${readableAnswerType(finalPayload?.answer_type)}`,
        finalResponse.answer ? `返回给页面的答案：${finalResponse.answer}` : "",
        `是否成功：${finalResponse.success ?? finalPayload?.success ?? "-"}`,
      ],
      note: "这是返回给页面和外部 API 的最后一道格式化节点。",
      failed: finalResponse.success === false,
    };
  }

  return base;
}

function executionNodeDetails(base, backendName, output, before, after) {
  const skipped = output.skipped || after[backendName.toLowerCase()]?.skipped;
  const success = output.success ?? after[backendName.toLowerCase()]?.success;
  const rows = output.rows || [];
  const value = output.value;
  return {
    ...base,
    received: [
      `Planner 给的分析口径：${readableOperation(before.operation)}`,
      before.source_tables?.length ? `要读取的数据表：${before.source_tables.join("、")}` : "",
      before.has_analysis_plan ? "已收到 Planner 拆好的执行步骤。" : "",
    ],
    did: [
      skipped ? `${backendName} 不适合本题或本模式，已跳过。` : `用 ${backendName} 执行分析计划。`,
      output.summary ? `执行摘要：${output.summary}` : "",
      output.reason ? `原因：${output.reason}` : "",
    ],
    sent: [
      success !== undefined ? `${backendName} 执行状态：${success ? "成功" : "失败"}` : "",
      rows.length ? `表格结果：${rows.length} 行，前 2 行 ${formatCompact(rows.slice(0, 2))}` : "",
      value !== undefined && value !== null ? `结果值：${formatCompact(value)}` : "",
    ],
    note: `${backendName} 节点只负责受控执行，不决定业务结论。`,
    failed: success === false,
  };
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
      <h3>技术 Agent 状态（辅助）</h3>
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
      <h3>工具调用明细（辅助）</h3>
      <div class="monitor-tool-list">
        ${tools
          .map(
            (tool) => `
              <div class="monitor-tool-row ${tool.success ? "completed" : "failed"}">
                <strong>${escapeHtml(monitorRoleName(tool.requested_by))} -> ${escapeHtml(tool.tool_name || "-")}</strong>
                <span>${escapeHtml(tool.success ? "成功" : "失败")} ${tool.latency_ms ? `/ ${formatNumber(tool.latency_ms)}ms` : ""}</span>
                <p>收到参数：${escapeHtml(formatJsonPreview(tool.arguments_summary || {}, 900))}</p>
                <p>返回结果：${escapeHtml(formatJsonPreview(tool.result_summary || {}, 900))}</p>
              </div>
            `,
          )
          .join("")}
      </div>
    </div>
  `;
}

function renderFinalTraceSteps(payload) {
  const processView = payload.process_view_v2 || {};
  if (Array.isArray(processView.steps) && processView.steps.length) {
    return `
      <div class="monitor-subsection">
        <h3>安全过程摘要</h3>
        <p class="monitor-subsection-note">${escapeHtml(processView.summary || "")}</p>
        <div class="monitor-step-list">
          ${processView.steps
            .map(
              (step) => `
                <div class="monitor-step-row ${escapeHtml(step.status || "completed")}">
                  <strong>${escapeHtml(step.title || "-")}</strong>
                  <p>${escapeHtml(step.summary || "")}</p>
                  ${step.evidence?.length ? `<span>${escapeHtml(step.evidence.slice(0, 2).join("；"))}</span>` : ""}
                </div>
              `,
            )
            .join("")}
        </div>
      </div>
    `;
  }
  const steps = payload.reasoning_trace_view || [];
  if (!steps.length) return "";
  return `
    <div class="monitor-subsection">
      <h3>阶段摘要（辅助）</h3>
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
      <h3>路由与交互（辅助）</h3>
      <dl class="monitor-route-list">
        ${parts.map(([key, value]) => `<dt>${escapeHtml(key)}</dt><dd>${escapeHtml(value)}</dd>`).join("")}
      </dl>
    </div>
  `;
}

function rolePurpose(role) {
  const descriptions = {
    planner: "把问题翻译成后续节点能执行的分析口径。",
    data_engineer: "看清数据里有哪些表、字段、样例和质量情况。",
    pandas_executor: "按计划用 Pandas 计算主结果。",
    sql_executor: "在支持时用 SQL 再算一遍，给校验节点交叉核对。",
    verifier: "检查计算是否成功、是否一致、是否符合问题口径。",
    correction: "校验发现问题时，决定是否修正口径并触发重跑。",
    insight: "把已验证结果整理成业务结论、建议和限制说明。",
    visualization: "判断是否适合画图，并输出图表配置。",
    response_builder: "把前面所有产物合成最终 API 响应和页面答案。",
    single_agent: "用单 Agent 链路完成理解、执行、校验和回答。",
  };
  return descriptions[role] || "处理当前流程中的一个内部节点。";
}

function resultSummary(result) {
  if (!result) return "";
  if (result.success === false) return `节点失败：${(result.issues || []).join("；") || "无详细原因"}`;
  if (result.role) return `${monitorRoleName(result.role)} 已完成。`;
  return "";
}

function readableRoute(logicForm) {
  if (!logicForm || !Object.keys(logicForm).length) return "尚未形成可读路由。";
  const parts = [
    logicForm.source_tables?.length ? `表：${logicForm.source_tables.join("、")}` : "",
    logicForm.parameters?.metric || logicForm.metric ? `指标：${logicForm.parameters?.metric || logicForm.metric}` : "",
    logicForm.parameters?.dimension || logicForm.group_by ? `维度：${logicForm.parameters?.dimension || logicForm.group_by}` : "",
  ].filter(Boolean);
  return parts.length ? parts.join("；") : `分析类型：${readableOperation(logicForm.operation)}`;
}

function readableMetricAndDimension(logicForm) {
  if (!logicForm) return "";
  const metric = logicForm.parameters?.metric || logicForm.metric;
  const dimension = logicForm.parameters?.dimension || logicForm.group_by;
  const pieces = [
    metric ? `指标：${metric}` : "",
    dimension ? `维度：${dimension}` : "",
    logicForm.parameters?.aggregation ? `汇总方式：${logicForm.parameters.aggregation}` : "",
  ].filter(Boolean);
  return pieces.length ? pieces.join("；") : "";
}

function readableOperation(operation) {
  const raw = String(operation || "").trim();
  if (!raw) return "-";
  const labels = {
    aggregation: "汇总计算",
    boolean_percentage: "占比计算",
    distinct_count: "去重计数",
    field_lookup: "字段查询",
    metric_per_distinct_entity: "按唯一实体计算指标",
    rank_by_metric: "按指标排名",
    ranking: "排名/最高最低",
    row_count: "行数统计",
    top_count: "出现次数最高/最常见",
    trend: "趋势分析",
    vds_current_filtered_metric_top: "按条件找当前最高指标",
    vds_current_metric_top: "找当前最高指标",
    vds_period_growth_count_share: "周期增长数量占比",
    vds_period_rank_change: "周期排名变化",
    vds_peer_anomaly: "同类异常对比",
    vds_status_impact_top: "状态影响排名",
  };
  return labels[raw] ? `${labels[raw]} (${raw})` : raw.replaceAll("_", " ");
}

function readableAnswerType(answerType) {
  const raw = String(answerType || "").trim();
  const labels = {
    chart: "图表",
    error: "错误",
    scalar: "单值",
    table: "表格",
    text: "文本",
    chat: "普通对话",
  };
  return raw ? `${labels[raw] || raw} (${raw})` : "-";
}

function readableSteps(steps) {
  if (!Array.isArray(steps) || !steps.length) return "没有显式步骤。";
  return steps
    .slice(0, 4)
    .map((step) => (typeof step === "string" ? step : step.name || step.operation || step.description || formatCompact(step)))
    .join(" -> ");
}

function readableTables(tables) {
  if (!Array.isArray(tables) || !tables.length) return "没有表画像。";
  return tables
    .slice(0, 4)
    .map((table) => `${table.table_name || table.name || "表"} (${table.row_count ?? "-"} 行 / ${table.column_count ?? table.columns?.length ?? "-"} 列)`)
    .join("；");
}

function readableStateDelta(before, after) {
  const lines = [];
  if (!before?.operation && after?.operation) lines.push(`新增分析操作：${after.operation}`);
  if ((before?.source_tables || []).join("|") !== (after?.source_tables || []).join("|") && after?.source_tables?.length) {
    lines.push(`选表结果：${after.source_tables.join("、")}`);
  }
  if (!before?.has_analysis_plan && after?.has_analysis_plan) lines.push("生成 analysis_plan。");
  if (before?.pandas?.success !== after?.pandas?.success && after?.pandas?.success !== undefined) {
    lines.push(`Pandas 状态：${after.pandas.success ? "成功" : "失败"}`);
  }
  if (before?.sql?.success !== after?.sql?.success && after?.sql?.success !== undefined) {
    lines.push(`SQL 状态：${after.sql.skipped ? "跳过" : after.sql.success ? "成功" : "失败"}`);
  }
  if (before?.verification?.passed !== after?.verification?.passed && after?.verification?.passed !== undefined) {
    lines.push(`校验结论：${after.verification.passed ? "通过" : "未通过"}`);
  }
  if (!before?.has_insight && after?.has_insight) lines.push("生成 insight。");
  if (!before?.has_chart && after?.has_chart) lines.push("生成 chart spec。");
  return lines;
}

function formatCompact(value, limit = 180) {
  let text = "";
  try {
    text = JSON.stringify(value ?? {}, null, 0);
  } catch {
    text = String(value ?? "");
  }
  return text.length > limit ? `${text.slice(0, limit)}...` : text;
}

function messageTitle(record, events) {
  if (record?.question) return record.question.length > 64 ? `${record.question.slice(0, 64)}...` : record.question;
  const eventQuestion = events.find((event) => event.payload?.question)?.payload?.question;
  if (eventQuestion) return String(eventQuestion).length > 64 ? `${String(eventQuestion).slice(0, 64)}...` : String(eventQuestion);
  return state.activeRunId || "当前消息";
}

function monitorStatusLabel(events, payload) {
  if (payload) return payload.success === false ? "有错误" : "已完成";
  if (events.some((event) => event.status === "failed")) return "有错误";
  if (events.length) return "运行中";
  return "等待事件";
}

function shortId(value) {
  const text = String(value || "");
  if (text.length <= 18) return text;
  return `${text.slice(0, 10)}...${text.slice(-4)}`;
}

function formatTime(value) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function monitorRoleName(role) {
  const names = {
    planner: "计划节点 (Planner)",
    data_engineer: "数据理解节点",
    pandas_executor: "Pandas 计算节点",
    sql_executor: "SQL 复算节点",
    verifier: "校验节点",
    correction: "修正节点",
    insight: "洞察节点",
    visualization: "图表节点",
    response_builder: "回答组装节点",
    single_agent: "单 Agent 节点",
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
