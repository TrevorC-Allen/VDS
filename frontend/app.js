const state = {
  datasetId: "",
  profile: null,
  selectedTable: "",
  runHistory: [],
  progressTimer: null,
  progressStep: 0,
  isUploading: false,
  isAnalyzing: false,
  hasPendingUpload: false,
  activeResultMessage: null,
};

const el = {
  chatMessages: document.querySelector("#chat-messages"),
  welcomeMessage: document.querySelector(".welcome-message"),
  profileMessage: document.querySelector("#profile-message"),
  resultTemplate: document.querySelector("#result-message"),
  resultMessage: document.querySelector("#result-message"),
  newChatButton: document.querySelector("#new-chat-button"),
  fileInput: document.querySelector("#file-input"),
  fileSummary: document.querySelector("#file-summary"),
  fileDetail: document.querySelector("#file-detail"),
  uploadButton: document.querySelector("#upload-button"),
  runButton: document.querySelector("#run-button"),
  questionInput: document.querySelector("#question-input"),
  executionMode: document.querySelector("#execution-mode"),
  agentMode: document.querySelector("#agent-mode"),
  apiStatus: document.querySelector("#api-status"),
  datasetStatus: document.querySelector("#dataset-status"),
  datasetChip: document.querySelector("#dataset-chip"),
  profileSummary: document.querySelector("#profile-summary"),
  tableList: document.querySelector("#table-list"),
  fieldTableBody: document.querySelector("#field-table-body"),
  answer: document.querySelector("#answer"),
  chartPanel: document.querySelector("#chart-panel"),
  resultTitle: document.querySelector("#result-title"),
  resultStatus: document.querySelector("#result-status"),
  resultTable: document.querySelector("#result-table"),
  insightPanel: document.querySelector(".insight-panel"),
  insightSummary: document.querySelector("#insight-summary"),
  insightList: document.querySelector("#insight-list"),
  processDetails: document.querySelector("#process-details"),
  processPanel: document.querySelector(".process-panel"),
  processSummary: document.querySelector("#process-summary"),
  processTimeline: document.querySelector("#process-timeline"),
  runHistory: document.querySelector("#run-history"),
  historyCount: document.querySelector("#history-count"),
};

el.fileInput.addEventListener("change", updateFileSummary);
el.newChatButton.addEventListener("click", resetConversation);
el.uploadButton.addEventListener("click", uploadFiles);
el.runButton.addEventListener("click", runAnalysis);
el.questionInput.addEventListener("input", updateRunButton);
el.questionInput.addEventListener("keydown", handleQuestionKeydown);

updateFileSummary();

function updateFileSummary() {
  const files = [...el.fileInput.files];
  if (!files.length) {
    state.hasPendingUpload = false;
    el.fileSummary.textContent = "选择文件";
    el.fileDetail.textContent = "CSV / Excel 支持多选";
    el.uploadButton.disabled = true;
    updateRunButton();
    return;
  }
  state.hasPendingUpload = true;
  el.fileSummary.textContent = `${files.length} 个文件已附加`;
  el.fileDetail.textContent = files.map((file) => file.name).join(" / ");
  el.uploadButton.disabled = false;
  updateRunButton();
}

async function uploadFiles() {
  const files = [...el.fileInput.files];
  if (!files.length) {
    setApiStatus("error", "请选择文件");
    return null;
  }
  state.isUploading = true;
  setApiStatus("idle", "上传中");
  el.uploadButton.disabled = true;
  updateRunButton();
  try {
    const payload = new FormData();
    const endpoint = files.length === 1 ? "/api/data-agent/upload" : "/api/data-agent/upload-batch";
    if (files.length === 1) {
      payload.append("file", files[0]);
    } else {
      files.forEach((file) => payload.append("files", file));
    }
    const response = await fetch(endpoint, { method: "POST", body: payload });
    const profile = await response.json();
    if (!response.ok || !profile.success) {
      throw new Error(errorText(profile) || `HTTP ${response.status}`);
    }
    state.profile = profile;
    state.datasetId = profile.dataset_id;
    state.selectedTable = profile.tables?.[0]?.table_name || "";
    renderProfile();
    el.profileMessage.classList.add("hidden");
    setApiStatus("ready", "数据集已就绪");
    state.hasPendingUpload = false;
    el.fileSummary.textContent = `${files.length} 个文件已就绪`;
    el.fileDetail.textContent = "已准备好，直接提问即可";
    return profile;
  } catch (error) {
    setApiStatus("error", "上传失败");
    state.datasetId = "";
    state.profile = null;
    state.selectedTable = "";
    state.hasPendingUpload = true;
    el.fileSummary.textContent = `${files.length} 个文件上传失败`;
    el.fileDetail.textContent = `上传失败：${String(error.message || error)}`;
    return null;
  } finally {
    state.isUploading = false;
    el.uploadButton.disabled = !state.hasPendingUpload;
    updateRunButton();
  }
}

async function runAnalysis() {
  const question = el.questionInput.value.trim();
  if (!question || state.isUploading || state.isAnalyzing) {
    updateRunButton();
    return;
  }
  if (state.hasPendingUpload) {
    const uploaded = await uploadFiles();
    if (!uploaded) {
      updateRunButton();
      return;
    }
  }
  state.isAnalyzing = true;
  el.runButton.disabled = true;
  appendUserMessage(question);
  el.questionInput.value = "";
  renderProgress(question);
  setApiStatus("idle", "处理中");
  try {
    const response = await fetch("/api/data-agent/message", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        dataset_id: state.datasetId,
        question,
        execution_mode: el.executionMode.value,
        agent_mode: el.agentMode.value,
      }),
    });
    const result = await response.json();
    if (!response.ok) {
      throw new Error(errorText(result) || `HTTP ${response.status}`);
    }
    stopProgress();
    result.question = question;
    renderResult(result);
    const isChat = result.answer_type === "chat" || result.debug?.agent_mode === "chat_without_dataset" || result.debug?.agent_mode === "chat_with_dataset";
    setApiStatus(result.success ? "ready" : "error", result.success ? (isChat ? "已回复" : "分析完成") : "需要继续确认");
  } catch (error) {
    stopProgress();
    setApiStatus("error", "分析失败");
    renderUserFacingError("分析失败", String(error.message || error));
  } finally {
    state.isAnalyzing = false;
    updateRunButton();
  }
}

function handleQuestionKeydown(event) {
  if (event.key !== "Enter" || event.shiftKey || event.isComposing) {
    return;
  }
  event.preventDefault();
  runAnalysis();
}

function updateRunButton() {
  const hasQuestion = Boolean(el.questionInput.value.trim());
  el.runButton.disabled = !hasQuestion || state.isUploading || state.isAnalyzing;
}

function renderProfile() {
  const profile = state.profile;
  const tables = profile?.tables || [];
  el.datasetChip.textContent = state.datasetId ? "数据已上传" : "未上传数据";
  el.datasetStatus.textContent = profile
    ? `${profile.file_name || "uploaded dataset"} / 数据已就绪`
    : "等待上传数据集";
  el.profileSummary.textContent = profile
    ? `${tables.length} 张表，${tables.reduce((sum, table) => sum + Number(table.row_count || 0), 0)} 行`
    : "暂无数据概览";

  if (!tables.length) {
    el.tableList.className = "table-list empty-state";
    el.tableList.textContent = "上传后显示文件、sheet、表名和行列数。";
    renderFieldTable(null);
    return;
  }

  el.tableList.className = "table-list";
  el.tableList.innerHTML = "";
  tables.forEach((table) => {
    const button = document.createElement("button");
    button.className = `table-card${table.table_name === state.selectedTable ? " selected" : ""}`;
    button.type = "button";
    button.innerHTML = `
      <span>
        <strong>${escapeHtml(table.table_name || "-")}</strong>
        <span class="table-meta">${escapeHtml(table.source_file || "-")} / ${escapeHtml(table.sheet || "sheet: -")}</span>
      </span>
      <span class="count-pill">${Number(table.row_count || 0)} x ${Number(table.column_count || 0)}</span>
    `;
    button.addEventListener("click", () => {
      state.selectedTable = table.table_name;
      renderProfile();
    });
    el.tableList.append(button);
  });
  renderFieldTable(tables.find((table) => table.table_name === state.selectedTable) || tables[0]);
}

function renderFieldTable(table) {
  if (!table) {
    el.fieldTableBody.innerHTML = `<tr><td colspan="3" class="muted-cell">选择一个表查看字段预览。</td></tr>`;
    return;
  }
  el.fieldTableBody.innerHTML = (table.columns || [])
    .map(
      (column) => `
        <tr>
          <td>${escapeHtml(column.name)}</td>
          <td>${escapeHtml(column.inferred_type)}</td>
          <td>${escapeHtml((column.sample_values || []).slice(0, 3).join(", ") || "-")}</td>
        </tr>
      `,
    )
    .join("");
}

function renderResult(result) {
  const rows = result.result?.rows || [];
  const columns = result.result?.columns || [];
  const isChat = result.answer_type === "chat" || result.debug?.agent_mode === "chat_without_dataset" || result.debug?.agent_mode === "chat_with_dataset";
  const isOverviewShaped = Boolean(result.debug?.user_experience_shaping?.applied);
  el.resultMessage.classList.remove("thinking-only");
  el.resultTitle.textContent = isChat ? "VDS" : "分析结果";
  el.answer.textContent = result.answer || "-";
  el.resultStatus.textContent = isChat ? "已回复" : result.success ? "已完成" : "需要继续确认";
  renderRows(rows, columns);
  renderChart(isOverviewShaped ? null : result.chart, rows, columns, result.answer);
  renderInsight(!isChat && result.success && !isOverviewShaped ? result.insight : null);
  renderProcess(result.reasoning_trace_view || [], result);
  pushHistory(result);
  revealMessage(el.resultMessage, "start");
}

function renderRows(rows, columns) {
  if (!rows.length) {
    el.resultTable.className = "result-table hidden";
    el.resultTable.textContent = "";
    return;
  }
  const safeColumns = columns.length ? columns : Object.keys(rows[0]);
  el.resultTable.className = "result-table";
  el.resultTable.innerHTML = `
    <table>
      <thead><tr>${safeColumns.map((column) => `<th>${escapeHtml(column)}</th>`).join("")}</tr></thead>
      <tbody>
        ${rows
          .slice(0, 50)
          .map((row) => `<tr>${safeColumns.map((column) => `<td>${escapeHtml(row[column])}</td>`).join("")}</tr>`)
          .join("")}
      </tbody>
    </table>
  `;
}

function renderChart(chart, fallbackRows = [], fallbackColumns = [], answer = "") {
  el.chartPanel.classList.remove("hidden");
  const type = chart?.chart_type;
  const rows = chart?.data?.length ? chart.data : fallbackRows;
  const x = chart?.x || fallbackColumns[0];
  const y = chart?.y || fallbackColumns.find((column) => Number.isFinite(Number(rows?.[0]?.[column])));
  if (!type || type === "kpi" || !rows.length || !x || !y) {
    el.chartPanel.className = "chart-panel hidden";
    return;
  }
  const values = rows
    .map((row) => ({ label: String(row[x] ?? ""), value: Number(row[y]) }))
    .filter((item) => item.label && Number.isFinite(item.value));
  if (values.length <= 1) {
    el.chartPanel.className = "chart-panel hidden";
    return;
  }
  el.chartPanel.className = "chart-panel";
  if (type === "line") {
    el.chartPanel.innerHTML = renderLineChart(values, chart);
  } else if (type === "pie" || type === "donut") {
    el.chartPanel.innerHTML = renderPieChart(values, chart, type);
  } else {
    el.chartPanel.innerHTML = renderBarChart(values, chart, type === "horizontal_bar");
  }
}

function renderBarChart(values, chart, horizontal) {
  const width = 620;
  const height = Math.max(230, values.length * (horizontal ? 26 : 0) + 170);
  const max = Math.max(...values.map((item) => Math.abs(item.value)), 1);
  const colors = ["#2563eb", "#0ea5e9", "#4f46e5", "#14b8a6", "#f59e0b", "#64748b"];
  const bars = values.slice(0, 16).map((item, index) => {
    if (horizontal) {
      const barWidth = (Math.abs(item.value) / max) * 410;
      const y = 58 + index * 28;
      return `
        <text x="20" y="${y + 15}" class="axis-label">${escapeHtml(shortLabel(item.label, 16))}</text>
        <rect x="150" y="${y}" width="${barWidth}" height="18" fill="${colors[index % colors.length]}" rx="3"></rect>
        <text x="${160 + barWidth}" y="${y + 14}" class="value-label">${formatNumber(item.value)}</text>
      `;
    }
    const barWidth = Math.max(18, 420 / values.length - 10);
    const x = 70 + index * (barWidth + 10);
    const barHeight = (Math.abs(item.value) / max) * 130;
    const y = 190 - barHeight;
    return `
      <rect x="${x}" y="${y}" width="${barWidth}" height="${barHeight}" fill="${colors[index % colors.length]}" rx="3"></rect>
      <text x="${x + barWidth / 2}" y="213" text-anchor="middle" class="axis-label">${escapeHtml(shortLabel(item.label, 8))}</text>
      <text x="${x + barWidth / 2}" y="${Math.max(48, y - 6)}" text-anchor="middle" class="value-label">${formatNumber(item.value)}</text>
    `;
  });
  return `
    <div class="chart-title">${escapeHtml(chart?.title || "自动图表")}</div>
    <svg class="chart-svg" viewBox="0 0 ${width} ${height}" role="img">
      <line x1="60" y1="190" x2="580" y2="190" class="axis-line"></line>
      ${bars.join("")}
    </svg>
  `;
}

function renderLineChart(values, chart) {
  const width = 620;
  const height = 250;
  const min = Math.min(...values.map((item) => item.value));
  const max = Math.max(...values.map((item) => item.value));
  const span = Math.max(max - min, 1);
  const points = values.slice(0, 30).map((item, index, list) => {
    const x = 58 + (index / Math.max(list.length - 1, 1)) * 500;
    const y = 190 - ((item.value - min) / span) * 135;
    return { x, y, label: item.label, value: item.value };
  });
  return `
    <div class="chart-title">${escapeHtml(chart?.title || "趋势图")}</div>
    <svg class="chart-svg" viewBox="0 0 ${width} ${height}" role="img">
      <line x1="55" y1="190" x2="565" y2="190" class="axis-line"></line>
      <polyline points="${points.map((point) => `${point.x},${point.y}`).join(" ")}" class="line-path"></polyline>
      ${points
        .map(
          (point, index) => `
            <circle cx="${point.x}" cy="${point.y}" r="4" class="line-dot"></circle>
            ${index === 0 || index === points.length - 1 ? `<text x="${point.x}" y="${point.y - 10}" text-anchor="middle" class="value-label">${formatNumber(point.value)}</text>` : ""}
          `,
        )
        .join("")}
    </svg>
  `;
}

function renderPieChart(values, chart, type) {
  const colors = ["#2563eb", "#0ea5e9", "#4f46e5", "#14b8a6", "#f59e0b", "#64748b", "#7c3aed", "#22c55e"];
  const total = values.reduce((sum, item) => sum + Math.max(item.value, 0), 0) || 1;
  let start = 0;
  const slices = values.slice(0, 8).map((item, index) => {
    const pct = Math.max(item.value, 0) / total;
    const end = start + pct * 360;
    const segment = `${colors[index % colors.length]} ${start}deg ${end}deg`;
    start = end;
    return { ...item, pct, color: colors[index % colors.length], segment };
  });
  return `
    <div class="chart-title">${escapeHtml(chart?.title || "构成图")}</div>
    <div class="pie-layout">
      <div class="pie-shape ${type === "donut" ? "donut" : ""}" style="background: conic-gradient(${slices.map((slice) => slice.segment).join(", ")});"></div>
      <ul class="pie-legend">
        ${slices
          .map((slice) => `<li><span style="background:${slice.color}"></span>${escapeHtml(shortLabel(slice.label, 16))} ${formatPercent(slice.pct * 100)}</li>`)
          .join("")}
      </ul>
    </div>
  `;
}

function renderInsight(insight) {
  const suggestions = (insight?.business_suggestions || insight?.suggestions || []).filter(isUserFacingInsightText);
  const summary = cleanInsightSummary(insight?.summary || "");
  const hasInsight = Boolean(summary || suggestions.length);
  el.insightPanel?.classList.toggle("hidden", !hasInsight);
  if (!hasInsight) {
    el.insightSummary.textContent = "";
    el.insightList.innerHTML = "";
    return;
  }
  el.insightSummary.textContent = summary;
  const items = [];
  suggestions.forEach((text) => items.push({ label: "建议", text }));
  el.insightList.innerHTML = items.length
    ? items.map((item) => `<li><strong>${escapeHtml(item.label)}</strong>${escapeHtml(item.text)}</li>`).join("")
    : "";
}

function renderProgress(question) {
  stopProgress();
  const message = createAssistantResultMessage();
  bindResultMessage(message);
  el.resultMessage.classList.add("thinking-only");
  el.resultTable.className = "result-table hidden";
  el.resultTable.textContent = "";
  el.chartPanel.className = "chart-panel hidden";
  el.chartPanel.textContent = "";
  el.insightPanel?.classList.add("hidden");
  el.chatMessages.append(el.resultMessage);
  revealMessage(el.resultMessage);

  const steps = buildLiveSteps(question, Boolean(state.datasetId));
  const update = () => {
    const currentStep = steps[state.progressStep] || steps[steps.length - 1];
    renderProcessItems(
      steps.map((step, index) => ({
        ...step,
        status: index < state.progressStep ? "completed" : index === state.progressStep ? "active" : "pending",
      })),
      currentStep?.summary || "正在整理回答。",
    );
    state.progressStep = Math.min(state.progressStep + 1, steps.length - 1);
  };
  state.progressStep = 0;
  update();
  state.progressTimer = window.setInterval(update, 1100);
}

function stopProgress() {
  if (state.progressTimer) {
    window.clearInterval(state.progressTimer);
    state.progressTimer = null;
  }
}

function renderProcess(steps, result = {}) {
  if (!steps.length && !result.question && !result.answer) {
    renderProcessItems([], "提问后显示分析过程。");
    return;
  }
  const friendlySteps = buildFriendlySteps(steps, result);
  if (!friendlySteps.length) {
    renderProcessItems([], "提问后显示分析过程。");
    return;
  }
  renderProcessItems(friendlySteps, result.question ? `已完成：围绕“${shortLabel(result.question, 28)}”整理出回答。` : "已完成本次分析。");
}

function renderProcessItems(steps, summary) {
  el.processSummary.textContent = summary;
  const hasActiveStep = steps.some((step) => step.status === "active");
  const hasFailedStep = steps.some((step) => step.status === "failed");
  el.processPanel?.classList.toggle("is-active", hasActiveStep);
  el.processPanel?.classList.toggle("is-failed", hasFailedStep);
  if (!steps.length) {
    el.processTimeline.innerHTML = `<li class="muted-cell">提问后显示分析过程。</li>`;
    return;
  }
  el.processTimeline.innerHTML = steps
    .map(
      (step) => `
        <li class="${escapeHtml(step.status || "completed")}">
          <span class="step-dot ${escapeHtml(step.status || "completed")}"></span>
          <div>
            <strong>${escapeHtml(step.title || "-")}</strong>
            <p>${escapeHtml(step.summary || "")}</p>
          </div>
        </li>
      `,
    )
    .join("");
}

function buildLiveSteps(question, hasDataset) {
  const shortQuestion = shortLabel(question, 30);
  if (!hasDataset) {
    return [
      { title: "理解问题", summary: `用户提到了“${shortQuestion}”，我会先判断这是聊天、口径讨论还是需要数据的问题。` },
      { title: "整理回复", summary: "当前没有上传数据，我会直接回复可讨论的部分，不编造业务结论。" },
    ];
  }
  const maybeChat = "我会先判断这是普通对话、数据概览，还是需要正式分析。";
  return [
    { title: "理解问题", summary: `用户提到了“${shortQuestion}”，${maybeChat}` },
    { title: "选择数据", summary: "我会从已上传文件里找最相关的数据表，避免拿错文件回答。" },
    { title: "匹配字段", summary: "我会确认哪些字段像指标、哪些字段像维度，以及是否需要多表关联。" },
    { title: "制定分析方式", summary: "我会判断这是排序、汇总、对比还是需要 join 后再回答。" },
    { title: "执行分析", summary: "我正在让后端执行分析，并等待可验证的结构化结果。" },
    { title: "生成回答", summary: "我会把结果整理成直接回答，而不是把后端审计细节丢给用户。" },
  ];
}

function buildFriendlySteps(steps, result) {
  const isChat = result.answer_type === "chat" || result.debug?.agent_mode === "chat_without_dataset" || result.debug?.agent_mode === "chat_with_dataset";
  if (isChat) {
    const chatSteps = steps.length
      ? steps.map((step) => ({
          title: friendlyStepTitle(String(step.name || step.title || "")),
          summary: friendlySummaryFallback(step),
          status: step.status || "completed",
        }))
      : [{ title: "整理回复", summary: "已根据当前对话直接回复。", status: "completed" }];
    return chatSteps;
  }
  const sourceTables = result.debug?.source_tables || result.logic_form?.source_tables || [];
  const selection = parseSelectionReason(result.debug?.table_selection_reason || result.logic_form?.table_selection_reason || "");
  const joinText = friendlyJoinText(result.debug?.join_plan || result.logic_form?.join_plan || {});
  const compact = [
    { title: "理解问题", summary: result.question ? `你想知道：${result.question}` : "已理解本次提问。" },
    {
      title: "选择数据",
      summary: sourceTables.length ? `使用 ${sourceTables.join("、")}。${selection.note ? ` ${selection.note}` : ""}` : "从上传文件中选择相关数据。",
    },
    {
      title: "匹配字段",
      summary: [selection.metric ? `指标是 ${selection.metric}` : "", selection.dimension ? `维度是 ${selection.dimension}` : ""].filter(Boolean).join("，") || "已找到回答问题需要的字段。",
    },
    { title: "执行分析", summary: "完成计算，并检查结果可以用于回答。" },
    { title: "生成回答", summary: result.answer ? `答案是 ${shortLabel(result.answer, 90)}。` : "已生成最终回答。" },
  ];
  if (result.debug?.join_plan?.trusted || result.logic_form?.join_plan?.trusted) {
    compact.splice(3, 0, { title: "关联数据", summary: joinText });
  }
  return compact.map((step) => ({ ...step, status: "completed" }));
}

function friendlyStepTitle(name) {
  if (name.includes("上传") || name.includes("Profile")) return "读取上传数据";
  if (name.includes("意图")) return "理解你的问题";
  if (name.includes("表路由")) return "选择相关数据";
  if (name.includes("字段")) return "匹配字段含义";
  if (name.includes("分析计划")) return "制定分析方式";
  if (name.includes("Join")) return "判断多表关联";
  if (name.includes("执行")) return "执行分析";
  if (name.includes("校验") || name.includes("修正")) return "核对结果";
  if (name.includes("图表")) return "选择展示方式";
  if (name.includes("洞察")) return "整理结论";
  if (name.includes("最终")) return "生成回答";
  return name || "处理步骤";
}

function friendlyStepSummary(title, step, result, sourceTables, selection, joinText) {
  if (title === "读取上传数据") return "已读取上传文件，并识别出表、字段和样例。";
  if (title === "理解你的问题") return result.question ? `已理解你的问题：${result.question}` : friendlySummaryFallback(step);
  if (title === "选择相关数据") {
    const selected = sourceTables.length ? `已选择 ${sourceTables.join("、")}。` : friendlySummaryFallback(step);
    return [selected, selection.note].filter(Boolean).join(" ");
  }
  if (title === "匹配字段含义") {
    const parts = [];
    if (selection.metric) parts.push(`关注指标：${selection.metric}`);
    if (selection.dimension) parts.push(`分析维度：${selection.dimension}`);
    return parts.length ? `${parts.join("；")}。` : "已匹配本次问题需要使用的字段。";
  }
  if (title === "制定分析方式") return "已确定如何从数据中得到答案。";
  if (title === "判断多表关联") return joinText;
  if (title === "执行分析") return "已完成计算并整理出结果数据。";
  if (title === "核对结果") return "已核对结果可以用于回答。";
  if (title === "选择展示方式") return "已选择适合本次结果的展示方式。";
  if (title === "整理结论") return result.insight?.summary || "已整理主要结论。";
  if (title === "生成回答") return result.answer ? `最终回答：${result.answer}` : "已生成最终回答。";
  return friendlySummaryFallback(step);
}

function friendlySummaryFallback(step) {
  const summary = String(step.summary || "");
  if (!summary || summary.includes("=") || summary.includes("{") || summary.includes("}")) return "已完成该步骤。";
  return summary;
}

function parseSelectionReason(reason) {
  const parsed = {};
  reason.split(";").forEach((part) => {
    const [key, value] = part.split("=").map((item) => item?.trim());
    if (key && value) parsed[key] = value;
  });
  const notes = [];
  if (reason.includes("explicit_table_mention")) notes.push("命中了你明确提到的数据文件。");
  if (parsed.join_plan === "trusted") notes.push("本题需要关联多张表，已找到可用关系。");
  return {
    metric: parsed.metric,
    dimension: parsed.dimension,
    note: notes.join(" "),
  };
}

function friendlyJoinText(joinPlan) {
  if (!joinPlan?.trusted) return "本题不需要关联多张表，或暂未找到需要关联的关系。";
  const left = joinPlan.left_table || "左表";
  const right = joinPlan.right_table || "右表";
  const key = joinPlan.left_key && joinPlan.right_key && joinPlan.left_key === joinPlan.right_key ? joinPlan.left_key : `${joinPlan.left_key || "-"} / ${joinPlan.right_key || "-"}`;
  return `已判断需要把 ${left} 和 ${right} 按 ${key} 关联后再回答。`;
}

function renderUserFacingError(title, message) {
  stopProgress();
  el.resultMessage.classList.remove("thinking-only");
  el.answer.textContent = title;
  el.resultStatus.textContent = "需要处理";
  el.resultTable.className = "result-table hidden";
  el.resultTable.textContent = "";
  el.chartPanel.className = "chart-panel hidden";
  el.chartPanel.textContent = "";
  renderInsight(null);
  renderProcessItems([{ title, summary: message || "请检查上传文件或稍后重试。", status: "failed" }], "处理没有完成。");
  revealMessage(el.resultMessage);
}

function pushHistory(result) {
  const isChat = result.answer_type === "chat" || result.debug?.agent_mode === "chat_without_dataset" || result.debug?.agent_mode === "chat_with_dataset";
  state.runHistory.unshift({
    runId: result.run_id,
    success: result.success,
    answer: result.answer,
    question: result.question,
    mode: isChat ? "chat" : "analysis",
  });
  state.runHistory = state.runHistory.slice(0, 8);
  el.historyCount.textContent = String(state.runHistory.length);
  el.runHistory.innerHTML = state.runHistory
    .map(
      (item) => `
        <li>
          <strong>${escapeHtml(item.mode === "chat" ? "已回复" : item.success ? "已完成分析" : "需要继续确认")}</strong>
          <span>${escapeHtml(item.question || "")}</span>
        </li>
      `,
    )
    .join("");
}

function clearResult() {
  stopProgress();
  el.resultMessage?.classList.add("hidden");
  el.resultMessage?.classList.remove("thinking-only");
  el.answer.textContent = "-";
  el.resultStatus.textContent = "尚未运行";
  el.resultTable.className = "result-table empty-state";
  el.resultTable.textContent = "结果表会显示在这里。";
  el.chartPanel.className = "chart-panel empty-state";
  el.chartPanel.classList.remove("hidden");
  el.chartPanel.textContent = "分析完成后会生成适合的图表或重点结果。";
  renderInsight(null);
  renderProcess([]);
}

function appendUserMessage(question) {
  el.welcomeMessage?.classList.add("hidden");
  const message = document.createElement("article");
  message.className = "message user-message";
  message.innerHTML = `
    <div class="avatar" aria-hidden="true">你</div>
    <div class="message-content">
      <p>${escapeHtml(question)}</p>
    </div>
  `;
  el.chatMessages.append(message);
  scrollToLatest();
}

function revealMessage(message, align = "latest") {
  if (!message) return;
  message.classList.remove("hidden");
  if (align === "start") {
    scrollToMessageStart(message);
  } else {
    scrollToLatest();
  }
}

function scrollToLatest() {
  requestAnimationFrame(() => {
    el.chatMessages.scrollTop = el.chatMessages.scrollHeight;
  });
}

function scrollToMessageStart(message) {
  requestAnimationFrame(() => {
    const target = Math.max(0, message.offsetTop - 10);
    el.chatMessages.scrollTo({ top: target, behavior: "smooth" });
  });
}

function resetConversation() {
  state.datasetId = "";
  state.profile = null;
  state.selectedTable = "";
  state.hasPendingUpload = false;
  state.activeResultMessage = null;
  el.fileInput.value = "";
  [...el.chatMessages.querySelectorAll(".user-message, .assistant-result-message")].forEach((message) => message.remove());
  bindResultMessage(el.resultTemplate);
  el.welcomeMessage?.classList.remove("hidden");
  el.profileMessage.classList.add("hidden");
  el.resultMessage.classList.add("hidden");
  updateFileSummary();
  renderProfile();
  clearResult();
  setApiStatus("idle", "准备就绪");
  el.datasetChip.textContent = "未上传数据";
  el.datasetStatus.textContent = "等待上传数据集";
  el.questionInput.value = "";
  updateRunButton();
  scrollToLatest();
}

function createAssistantResultMessage() {
  const message = el.resultTemplate.cloneNode(true);
  message.removeAttribute("id");
  message.classList.add("assistant-result-message");
  message.classList.remove("hidden");
  message.querySelectorAll("[id]").forEach((node) => node.removeAttribute("id"));
  return message;
}

function bindResultMessage(message) {
  state.activeResultMessage = message;
  el.resultMessage = message;
  el.resultTitle = message.querySelector(".result-panel h2");
  el.resultStatus = message.querySelector(".result-panel .block-header p");
  el.answer = message.querySelector(".answer-box");
  el.chartPanel = message.querySelector(".chart-panel");
  el.resultTable = message.querySelector(".result-table");
  el.insightPanel = message.querySelector(".insight-panel");
  el.insightSummary = message.querySelector(".insight-summary");
  el.insightList = message.querySelector(".compact-list");
  el.processPanel = message.querySelector(".process-panel");
  el.processSummary = message.querySelector(".process-line p");
  el.processTimeline = message.querySelector(".process-timeline");
}

function setApiStatus(status, text) {
  el.apiStatus.className = `status-dot ${status}`;
  el.apiStatus.textContent = text;
}

function errorText(payload) {
  const firstError = payload?.errors?.[0];
  if (!firstError) return "";
  return firstError.error_message || firstError.message || JSON.stringify(firstError);
}

function cleanInsightSummary(summary) {
  const text = String(summary || "").replace(/^Verified result:\s*/i, "").trim();
  return isUserFacingInsightText(text) ? text : "";
}

function isUserFacingInsightText(text) {
  const value = String(text || "");
  if (!value.trim()) return false;
  return !["数据质量", "高严重度", "quality_report", "verification", "warnings", "errors", "join trace", "Join / Verification"].some((token) =>
    value.includes(token),
  );
}

function stringifyIssue(issue) {
  if (typeof issue === "string") return issue;
  if (issue?.error_message) return issue.error_message;
  return JSON.stringify(issue);
}

function formatPercent(value) {
  return `${value.toFixed(value >= 10 ? 1 : 2)}%`;
}

function formatNumber(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return String(value ?? "-");
  return Math.abs(number) >= 1000 ? number.toLocaleString("zh-CN", { maximumFractionDigits: 1 }) : String(Number(number.toFixed(2)));
}

function shortLabel(value, limit) {
  const text = String(value ?? "");
  return text.length > limit ? `${text.slice(0, limit - 1)}…` : text;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}
