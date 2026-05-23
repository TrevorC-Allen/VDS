const state = {
  datasetId: "",
  profile: null,
  selectedTable: "",
  runHistory: [],
};

const el = {
  chatMessages: document.querySelector("#chat-messages"),
  profileMessage: document.querySelector("#profile-message"),
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
  resultStatus: document.querySelector("#result-status"),
  resultTable: document.querySelector("#result-table"),
  insightSummary: document.querySelector("#insight-summary"),
  insightList: document.querySelector("#insight-list"),
  qualityScore: document.querySelector("#quality-score"),
  qualitySummary: document.querySelector("#quality-summary"),
  qualityList: document.querySelector("#quality-list"),
  verificationBadge: document.querySelector("#verification-badge"),
  sourceTables: document.querySelector("#source-tables"),
  selectionReason: document.querySelector("#selection-reason"),
  joinPlan: document.querySelector("#join-plan"),
  joinSummary: document.querySelector("#join-summary"),
  processTimeline: document.querySelector("#process-timeline"),
  warningsErrors: document.querySelector("#warnings-errors"),
  clarification: document.querySelector("#clarification"),
  runHistory: document.querySelector("#run-history"),
  historyCount: document.querySelector("#history-count"),
};

el.fileInput.addEventListener("change", updateFileSummary);
el.newChatButton.addEventListener("click", resetConversation);
el.uploadButton.addEventListener("click", uploadFiles);
el.runButton.addEventListener("click", runAnalysis);
el.questionInput.addEventListener("input", updateRunButton);

updateFileSummary();

function updateFileSummary() {
  const files = [...el.fileInput.files];
  if (!files.length) {
    el.fileSummary.textContent = "选择文件";
    el.fileDetail.textContent = "CSV / Excel 支持多选";
    el.uploadButton.disabled = true;
    return;
  }
  el.fileSummary.textContent = `${files.length} 个文件待上传`;
  el.fileDetail.textContent = files.map((file) => file.name).join(" / ");
  el.uploadButton.disabled = false;
}

async function uploadFiles() {
  const files = [...el.fileInput.files];
  if (!files.length) {
    setApiStatus("error", "请选择文件");
    return;
  }
  setApiStatus("idle", "上传中");
  el.uploadButton.disabled = true;
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
    revealMessage(el.profileMessage);
    clearResult();
    setApiStatus("ready", "数据集已就绪");
    el.fileSummary.textContent = `${files.length} 个文件已上传`;
    el.fileDetail.textContent = state.datasetId || files.map((file) => file.name).join(" / ");
  } catch (error) {
    setApiStatus("error", "上传失败");
    renderIssues([], [String(error.message || error)]);
  } finally {
    el.uploadButton.disabled = false;
    updateRunButton();
  }
}

async function runAnalysis() {
  const question = el.questionInput.value.trim();
  if (!state.datasetId || !question) {
    updateRunButton();
    return;
  }
  appendUserMessage(question);
  setApiStatus("idle", "分析中");
  el.runButton.disabled = true;
  try {
    const response = await fetch("/api/data-agent/analyze", {
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
    result.question = question;
    renderResult(result);
    setApiStatus(result.success ? "ready" : "error", result.success ? "分析完成" : "需要处理");
  } catch (error) {
    setApiStatus("error", "分析失败");
    renderIssues([], [String(error.message || error)]);
  } finally {
    updateRunButton();
  }
}

function updateRunButton() {
  el.runButton.disabled = !state.datasetId || !el.questionInput.value.trim();
}

function renderProfile() {
  const profile = state.profile;
  const tables = profile?.tables || [];
  el.datasetChip.textContent = `dataset_id: ${state.datasetId || "-"}`;
  el.datasetStatus.textContent = profile
    ? `${profile.file_name || "uploaded dataset"} / ${profile.status || "unknown"}`
    : "等待上传数据集";
  el.profileSummary.textContent = profile
    ? `${tables.length} 张表，${tables.reduce((sum, table) => sum + Number(table.row_count || 0), 0)} 行`
    : "暂无 profile";

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
    el.fieldTableBody.innerHTML = `<tr><td colspan="6" class="muted-cell">选择一个表查看字段画像。</td></tr>`;
    return;
  }
  el.fieldTableBody.innerHTML = (table.columns || [])
    .map(
      (column) => `
        <tr>
          <td>${escapeHtml(column.name)}</td>
          <td>${escapeHtml(column.inferred_type)}</td>
          <td>${formatPercent(Number(column.missing_rate || 0) * 100)}</td>
          <td>${Number(column.unique_count || 0)}</td>
          <td>${escapeHtml((column.semantic_hints || []).join(", ") || "-")}</td>
          <td>${escapeHtml((column.sample_values || []).slice(0, 3).join(", ") || "-")}</td>
        </tr>
      `,
    )
    .join("");
}

function renderResult(result) {
  const verification = result.verification || {};
  const debug = result.debug || {};
  const rows = result.result?.rows || [];
  const columns = result.result?.columns || [];
  el.answer.textContent = result.answer || "-";
  el.resultStatus.textContent = `${result.success ? "success" : "not successful"} / ${result.run_id || "-"}`;
  renderRows(rows, columns);
  renderChart(result.chart, rows, columns, result.answer);
  renderInsight(result.insight);
  renderQuality(result.quality_report || state.profile?.quality_report);
  renderProcess(result.reasoning_trace_view || []);
  renderVerification(verification);
  el.sourceTables.textContent = formatJson(debug.source_tables || result.logic_form?.source_tables || []);
  el.selectionReason.textContent = debug.table_selection_reason || result.logic_form?.table_selection_reason || "-";
  el.joinPlan.textContent = formatJson(debug.join_plan || result.logic_form?.join_plan || {});
  el.joinSummary.textContent = formatJson(debug.join_execution_summary || {});
  renderIssues(result.warnings || [], result.errors || [], verification);
  pushHistory(result);
  revealMessage(el.resultMessage);
}

function renderRows(rows, columns) {
  if (!rows.length) {
    el.resultTable.className = "result-table empty-state";
    el.resultTable.textContent = "本次没有表格行。";
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
  const type = chart?.chart_type;
  const rows = chart?.data?.length ? chart.data : fallbackRows;
  const x = chart?.x || fallbackColumns[0];
  const y = chart?.y || fallbackColumns.find((column) => Number.isFinite(Number(rows?.[0]?.[column])));
  if (!type || type === "kpi" || !rows.length || !x || !y) {
    el.chartPanel.className = "chart-panel kpi-panel";
    el.chartPanel.innerHTML = `
      <div class="kpi-value">${escapeHtml(answer || chart?.title || "-")}</div>
      <div class="chart-reason">${escapeHtml(chart?.reason || chart?.selection_reason || "单值结果无需图表。")}</div>
    `;
    return;
  }
  const values = rows
    .map((row) => ({ label: String(row[x] ?? ""), value: Number(row[y]) }))
    .filter((item) => item.label && Number.isFinite(item.value));
  if (!values.length) {
    el.chartPanel.className = "chart-panel empty-state";
    el.chartPanel.textContent = "后端返回的 chart spec 没有可绘制数值。";
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
    <div class="chart-reason">${escapeHtml(chart?.reason || chart?.selection_reason || "")}</div>
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
    <div class="chart-reason">${escapeHtml(chart?.reason || chart?.selection_reason || "")}</div>
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
    <div class="chart-reason">${escapeHtml(chart?.reason || chart?.selection_reason || "")}</div>
  `;
}

function renderInsight(insight) {
  el.insightSummary.textContent = insight?.summary || "暂无洞察。";
  const items = [];
  (insight?.anomaly_findings || []).forEach((item) => items.push({ label: "异常", text: item.message || stringifyIssue(item) }));
  (insight?.volatility_findings || []).forEach((item) => items.push({ label: "波动", text: item.message || stringifyIssue(item) }));
  (insight?.business_suggestions || insight?.suggestions || []).forEach((text) => items.push({ label: "建议", text }));
  (insight?.caveats || []).forEach((text) => items.push({ label: "注意", text }));
  el.insightList.innerHTML = items.length
    ? items.map((item) => `<li><strong>${escapeHtml(item.label)}</strong>${escapeHtml(item.text)}</li>`).join("")
    : `<li class="muted-cell">暂无建议。</li>`;
}

function renderQuality(report) {
  if (!report) {
    el.qualityScore.className = "badge neutral";
    el.qualityScore.textContent = "未扫描";
    el.qualitySummary.textContent = "上传或分析后显示质量扫描结果。";
    el.qualityList.innerHTML = "";
    return;
  }
  const score = Number(report.quality_score ?? 0);
  el.qualityScore.className = `badge ${score >= 80 ? "pass" : score >= 60 ? "warn" : "fail"}`;
  el.qualityScore.textContent = `${formatNumber(score)} / 100`;
  el.qualitySummary.textContent = report.summary || `发现 ${Number(report.issue_count || 0)} 个潜在问题。`;
  const issues = report.issues || [];
  el.qualityList.innerHTML = issues.length
    ? issues
        .slice(0, 8)
        .map((issue) => `<li><strong>${escapeHtml(issue.severity || "-")} · ${escapeHtml(issue.issue_type || "-")}</strong>${escapeHtml(issue.message || "")}</li>`)
        .join("")
    : `<li class="muted-cell">未发现明显问题。</li>`;
}

function renderProcess(steps) {
  if (!steps.length) {
    el.processTimeline.innerHTML = `<li class="muted-cell">运行后显示结构化过程。</li>`;
    return;
  }
  el.processTimeline.innerHTML = steps
    .map(
      (step) => `
        <li>
          <span class="step-dot ${escapeHtml(step.status || "completed")}"></span>
          <div>
            <strong>${escapeHtml(step.name || step.step_id || "-")}</strong>
            <p>${escapeHtml(step.summary || "")}</p>
          </div>
        </li>
      `,
    )
    .join("");
}

function renderVerification(verification) {
  const passed = Boolean(verification.passed);
  el.verificationBadge.className = `badge ${passed ? "pass" : "fail"}`;
  el.verificationBadge.textContent = passed ? "通过" : "未通过";
}

function renderIssues(warnings, errors, verification = {}) {
  const items = [];
  warnings.forEach((warning) => items.push({ type: "warning", text: stringifyIssue(warning) }));
  errors.forEach((error) => items.push({ type: "error", text: stringifyIssue(error) }));
  const action = verification.correction_action;
  if (action?.action === "clarify_join_key") {
    el.clarification.classList.remove("hidden");
    el.clarification.textContent = `需要确认 join key：${action.reason || "后端没有足够置信度执行多表 join。"}`;
  } else {
    el.clarification.classList.add("hidden");
    el.clarification.textContent = "";
  }
  if (!items.length) {
    el.warningsErrors.innerHTML = `<li class="muted-cell">暂无 warnings 或 errors。</li>`;
    return;
  }
  el.warningsErrors.innerHTML = items
    .map((item) => `<li class="${item.type}"><strong>${item.type}</strong><br>${escapeHtml(item.text)}</li>`)
    .join("");
}

function pushHistory(result) {
  state.runHistory.unshift({
    runId: result.run_id,
    success: result.success,
    answer: result.answer,
    question: result.question,
  });
  state.runHistory = state.runHistory.slice(0, 8);
  el.historyCount.textContent = String(state.runHistory.length);
  el.runHistory.innerHTML = state.runHistory
    .map(
      (item) => `
        <li>
          <strong>${escapeHtml(item.success ? "success" : "needs review")} / ${escapeHtml(item.runId || "-")}</strong>
          <span>${escapeHtml(item.question || "")}</span>
        </li>
      `,
    )
    .join("");
}

function clearResult() {
  el.resultMessage?.classList.add("hidden");
  el.answer.textContent = "-";
  el.resultStatus.textContent = "尚未运行";
  el.resultTable.className = "result-table empty-state";
  el.resultTable.textContent = "结果表会显示在这里。";
  el.chartPanel.className = "chart-panel empty-state";
  el.chartPanel.textContent = "图表会根据后端 chart spec 自动展示。";
  renderInsight(null);
  renderQuality(state.profile?.quality_report);
  renderProcess([]);
  el.verificationBadge.className = "badge neutral";
  el.verificationBadge.textContent = "未验证";
  el.sourceTables.textContent = "-";
  el.selectionReason.textContent = "-";
  el.joinPlan.textContent = "-";
  el.joinSummary.textContent = "-";
  renderIssues([], []);
}

function appendUserMessage(question) {
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

function revealMessage(message) {
  if (!message) return;
  message.classList.remove("hidden");
  scrollToLatest();
}

function scrollToLatest() {
  requestAnimationFrame(() => {
    el.chatMessages.scrollTop = el.chatMessages.scrollHeight;
  });
}

function resetConversation() {
  state.datasetId = "";
  state.profile = null;
  state.selectedTable = "";
  el.fileInput.value = "";
  [...el.chatMessages.querySelectorAll(".user-message")].forEach((message) => message.remove());
  el.profileMessage.classList.add("hidden");
  el.resultMessage.classList.add("hidden");
  updateFileSummary();
  renderProfile();
  clearResult();
  setApiStatus("idle", "API 未连接");
  el.datasetChip.textContent = "dataset_id: -";
  el.datasetStatus.textContent = "等待上传数据集";
  el.questionInput.value = "";
  updateRunButton();
  scrollToLatest();
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

function stringifyIssue(issue) {
  if (typeof issue === "string") return issue;
  if (issue?.error_message) return issue.error_message;
  return JSON.stringify(issue);
}

function formatJson(value) {
  if (!value || (typeof value === "object" && !Object.keys(value).length)) return "-";
  return JSON.stringify(value, null, 2);
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
