const MONITOR_RUN_INDEX_KEY = "vds-monitor-runs";
const ACTIVE_MONITOR_RUN_KEY = "vds-active-monitor-run";
const MAX_MONITOR_RUN_RECORDS = 80;
const ACTIVITY_EVENT_TYPES = [
  "monitor_connected",
  "message_requested",
  "analysis_requested",
  "workflow_started",
  "agent_started",
  "agent_completed",
  "workflow_completed",
  "response_ready",
  "analysis_failed",
  "thought_delta",
  "tool_considered",
  "dependency_note",
  "data_scan_note",
  "plan_note",
  "code_artifact_ready",
  "answer_outline_ready",
];

const state = {
  datasetId: "",
  conversationId: "",
  projectId: "",
  projects: [],
  projectDetails: null,
  projectConversations: [],
  projectViewTab: "chats",
  projectDraftActive: false,
  profile: null,
  selectedTable: "",
  fileRecords: [],
  runHistory: [],
  progressTimer: null,
  progressStep: 0,
  isUploading: false,
  isAnalyzing: false,
  hasPendingUpload: false,
  ruleModeEnabled: false,
  hasPendingRuleUpload: false,
  userRuleFileId: "",
  autoRuleFileIds: [],
  benchmarkRuleFileId: "",
  hasPendingBenchmarkRuleUpload: false,
  activeResultMessage: null,
  activeMonitorRunId: "",
  activeHistoryRunId: "",
  activitySource: null,
  activityEvents: [],
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
  filePanel: document.querySelector("#file-panel"),
  filePanelCount: document.querySelector("#file-panel-count"),
  filePanelList: document.querySelector("#file-panel-list"),
  uploadButton: document.querySelector("#upload-button"),
  ruleModeToggle: document.querySelector("#rule-mode-toggle"),
  ruleUploadPanel: document.querySelector("#rule-upload-panel"),
  ruleFileInput: document.querySelector("#rule-file-input"),
  ruleUploadButton: document.querySelector("#rule-upload-button"),
  ruleFileStatus: document.querySelector("#rule-file-status"),
  benchmarkRuleInput: document.querySelector("#benchmark-rule-input"),
  benchmarkRuleUploadButton: document.querySelector("#benchmark-rule-upload-button"),
  benchmarkRunButton: document.querySelector("#benchmark-run-button"),
  benchmarkStatus: document.querySelector("#benchmark-status"),
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
  artifactPanel: document.querySelector(".artifact-panel"),
  artifactList: document.querySelector(".artifact-list"),
  runHistory: document.querySelector("#run-history"),
  historyCount: document.querySelector("#history-count"),
  projectList: document.querySelector("#project-list"),
  newProjectButton: document.querySelector("#new-project-button"),
  projectCount: document.querySelector("#project-count"),
  projectSummary: document.querySelector("#project-summary"),
  projectHome: document.querySelector("#project-home"),
  projectHomeTitle: document.querySelector("#project-home-title"),
  projectNewChatButton: document.querySelector("#project-new-chat-button"),
  projectNewChatLabel: document.querySelector("#project-new-chat-label"),
  projectTabChats: document.querySelector("#project-tab-chats"),
  projectTabSources: document.querySelector("#project-tab-sources"),
  projectChatsPanel: document.querySelector("#project-chats-panel"),
  projectSourcesPanel: document.querySelector("#project-sources-panel"),
  projectConversationList: document.querySelector("#project-conversation-list"),
  projectSourceList: document.querySelector("#project-source-list"),
  projectMemoryList: document.querySelector("#project-memory-list"),
  contextMenu: document.querySelector("#context-menu"),
};

el.fileInput.addEventListener("change", updateFileSummary);
el.fileSummary.addEventListener("click", toggleFilePanel);
document.addEventListener("click", closeFilePanelFromOutside);
document.addEventListener("click", closeContextMenuFromOutside);
window.addEventListener("resize", closeContextMenu);
window.addEventListener("scroll", closeContextMenu, true);
el.ruleModeToggle?.addEventListener("change", updateRuleMode);
el.ruleFileInput?.addEventListener("change", updateRuleFileSummary);
el.ruleUploadButton?.addEventListener("click", uploadUserRule);
el.benchmarkRuleInput?.addEventListener("change", updateBenchmarkRuleSummary);
el.benchmarkRuleUploadButton?.addEventListener("click", uploadBenchmarkRule);
el.benchmarkRunButton?.addEventListener("click", runBenchmark);
el.newChatButton.addEventListener("click", startGlobalConversation);
el.newProjectButton?.addEventListener("click", createProjectFromPrompt);
el.projectNewChatButton?.addEventListener("click", startProjectConversation);
el.projectTabChats?.addEventListener("click", () => setProjectTab("chats"));
el.projectTabSources?.addEventListener("click", () => setProjectTab("sources"));
el.uploadButton.addEventListener("click", uploadFiles);
el.runButton.addEventListener("click", runAnalysis);
el.questionInput.addEventListener("input", handleQuestionInput);
el.questionInput.addEventListener("paste", handleQuestionPaste);
el.questionInput.addEventListener("focus", updateQuestionEmptyState);
el.questionInput.addEventListener("keydown", handleQuestionKeydown);

updateFileSummary();
updateQuestionEmptyState();
loadProjects().finally(() => loadConversations());

function updateFileSummary() {
  const files = [...el.fileInput.files];
  if (!files.length) {
    state.hasPendingUpload = false;
    state.fileRecords = [];
    el.fileSummary.textContent = "选择文件";
    el.fileDetail.textContent = "数据和说明文件支持多选";
    el.uploadButton.disabled = true;
    renderFilePanel();
    updateRunButton();
    return;
  }
  state.hasPendingUpload = true;
  state.fileRecords = files.map((file) => fileRecordFromFile(file, "pending"));
  el.fileSummary.textContent = `${files.length} 个文件已附加`;
  el.fileDetail.textContent = "点击查看文件";
  el.uploadButton.disabled = false;
  renderFilePanel();
  updateRunButton();
}

function applyRestoredFileRecords(profile) {
  state.hasPendingUpload = false;
  state.fileRecords = buildReadyFileRecords([], profile);
  el.uploadButton.disabled = true;
  renderFilePanel();
  if (state.fileRecords.length) {
    el.fileSummary.textContent = `${state.fileRecords.length} 个文件已就绪`;
    el.fileDetail.textContent = "点击查看文件";
  } else {
    el.fileSummary.textContent = "文件信息不可用";
    el.fileDetail.textContent = "需重新上传后继续分析";
  }
  updateRunButton();
}

function clearRestoredFileRecords() {
  state.hasPendingUpload = false;
  state.fileRecords = [];
  el.uploadButton.disabled = true;
  renderFilePanel();
  el.fileSummary.textContent = state.datasetId ? "文件信息不可用" : "选择文件";
  el.fileDetail.textContent = state.datasetId ? "需重新上传后继续分析" : "数据和说明文件支持多选";
  updateRunButton();
}

function toggleFilePanel(event) {
  event.stopPropagation();
  if (!state.fileRecords.length) return;
  const shouldOpen = el.filePanel?.classList.contains("hidden");
  el.filePanel?.classList.toggle("hidden", !shouldOpen);
  el.fileSummary.setAttribute("aria-expanded", String(shouldOpen));
}

function closeFilePanelFromOutside(event) {
  if (event.target.closest(".file-status-wrap")) return;
  closeFilePanel();
}

function closeFilePanel() {
  el.filePanel?.classList.add("hidden");
  el.fileSummary.setAttribute("aria-expanded", "false");
}

function renderFilePanel() {
  const records = state.fileRecords || [];
  el.fileSummary.disabled = !records.length;
  if (el.filePanelCount) el.filePanelCount.textContent = String(records.length);
  if (!records.length) {
    closeFilePanel();
    if (el.filePanelList) el.filePanelList.innerHTML = "";
    return;
  }
  if (!el.filePanelList) return;
  el.filePanelList.innerHTML = records
    .map(
      (file) => `
        <li>
          <div>
            <strong title="${escapeHtml(file.name)}">${escapeHtml(file.name)}</strong>
            <span>${escapeHtml(file.meta || "")}</span>
          </div>
          <em class="${escapeHtml(file.status)}">${escapeHtml(file.statusText)}</em>
        </li>
      `,
    )
    .join("");
}

function fileRecordFromFile(file, status, profile = null) {
  const tableCount = countTablesForSource(profile, file.name);
  return {
    name: file.name,
    size: file.size,
    status,
    statusText: fileStatusText(status),
    meta: fileMetaText(file.size, tableCount),
  };
}

function buildReadyFileRecords(files, profile) {
  const fileByName = new Map(files.map((file) => [file.name, file]));
  const sourceNames = uniqueSourceFileNames(profile);
  const names = sourceNames.length ? sourceNames : files.map((file) => file.name);
  return names.map((name) => {
    const file = fileByName.get(name);
    const tableCount = countTablesForSource(profile, name);
    return {
      name,
      size: file?.size || 0,
      status: "ready",
      statusText: fileStatusText("ready"),
      meta: fileMetaText(file?.size || 0, tableCount),
    };
  });
}

function uniqueSourceFileNames(profile) {
  const names = [];
  (profile?.tables || []).forEach((table) => {
    const name = String(table.source_file || profile?.file_name || "").trim();
    if (name && !names.includes(name)) names.push(name);
  });
  if (!names.length && profile?.file_name) {
    String(profile.file_name)
      .split(",")
      .map((name) => name.trim())
      .filter(Boolean)
      .forEach((name) => {
        if (!names.includes(name)) names.push(name);
      });
  }
  return names;
}

function countTablesForSource(profile, sourceName) {
  if (!profile || !sourceName) return 0;
  return (profile.tables || []).filter((table) => String(table.source_file || profile.file_name || "") === sourceName).length;
}

function fileMetaText(size, tableCount) {
  return [size ? formatFileSize(size) : "", tableCount ? `${tableCount} 张表` : ""].filter(Boolean).join(" / ") || "文件";
}

function fileStatusText(status) {
  if (status === "ready") return "已就绪";
  if (status === "failed") return "失败";
  return "待上传";
}

function updateRuleMode() {
  state.ruleModeEnabled = Boolean(el.ruleModeToggle?.checked);
  el.ruleUploadPanel?.classList.toggle("hidden", !state.ruleModeEnabled);
  if (!state.ruleModeEnabled) {
    state.userRuleFileId = "";
    state.hasPendingRuleUpload = false;
    if (el.ruleFileInput) el.ruleFileInput.value = "";
    if (el.ruleFileStatus) el.ruleFileStatus.textContent = "未上传用户分析规则";
  }
  updateRunButton();
  updateBenchmarkButtons();
}

function updateRuleFileSummary() {
  const file = el.ruleFileInput?.files?.[0];
  state.hasPendingRuleUpload = Boolean(file);
  state.userRuleFileId = state.hasPendingRuleUpload ? "" : state.userRuleFileId;
  if (el.ruleUploadButton) el.ruleUploadButton.disabled = !state.hasPendingRuleUpload;
  if (el.ruleFileStatus) {
    el.ruleFileStatus.textContent = file ? `待上传：${file.name}` : (state.userRuleFileId ? "用户分析规则已上传" : "未上传用户分析规则");
  }
  updateRunButton();
}

async function uploadUserRule() {
  const file = el.ruleFileInput?.files?.[0];
  if (!file) return null;
  setApiStatus("idle", "上传规则中");
  if (el.ruleUploadButton) el.ruleUploadButton.disabled = true;
  try {
    const payload = new FormData();
    payload.append("file", file);
    payload.append("file_role", "rule");
    payload.append("rule_scope", "user_analysis");
    if (state.datasetId) payload.append("bind_dataset_id", state.datasetId);
    const response = await fetch("/api/data-agent/upload", { method: "POST", body: payload });
    const result = await response.json();
    if (!response.ok || !result.success) {
      throw new Error(errorText(result) || `HTTP ${response.status}`);
    }
    state.userRuleFileId = result.file_id || "";
    state.hasPendingRuleUpload = false;
    if (el.ruleFileStatus) el.ruleFileStatus.textContent = `${result.file_name || "分析规则"} 已启用`;
    setApiStatus("ready", "Rule Mode 已启用");
    updateBenchmarkButtons();
    return result;
  } catch (error) {
    state.userRuleFileId = "";
    state.hasPendingRuleUpload = true;
    if (el.ruleFileStatus) el.ruleFileStatus.textContent = `规则上传失败：${String(error.message || error)}`;
    setApiStatus("error", "规则上传失败");
    return null;
  } finally {
    if (el.ruleUploadButton) el.ruleUploadButton.disabled = !state.hasPendingRuleUpload;
    updateRunButton();
  }
}

function updateBenchmarkRuleSummary() {
  const file = el.benchmarkRuleInput?.files?.[0];
  state.hasPendingBenchmarkRuleUpload = Boolean(file);
  state.benchmarkRuleFileId = state.hasPendingBenchmarkRuleUpload ? "" : state.benchmarkRuleFileId;
  if (el.benchmarkRuleUploadButton) el.benchmarkRuleUploadButton.disabled = !state.hasPendingBenchmarkRuleUpload;
  if (el.benchmarkStatus) {
    el.benchmarkStatus.textContent = file ? `待上传：${file.name}` : (state.benchmarkRuleFileId ? "Benchmark 规则已上传" : "内部 Benchmark 入口");
  }
  updateBenchmarkButtons();
}

async function uploadBenchmarkRule() {
  const file = el.benchmarkRuleInput?.files?.[0];
  if (!file) return null;
  if (el.benchmarkRuleUploadButton) el.benchmarkRuleUploadButton.disabled = true;
  if (el.benchmarkStatus) el.benchmarkStatus.textContent = "Benchmark 规则上传中";
  try {
    const payload = new FormData();
    payload.append("file", file);
    payload.append("file_role", "rule");
    payload.append("rule_scope", "benchmark");
    const response = await fetch("/api/data-agent/upload", { method: "POST", body: payload });
    const result = await response.json();
    if (!response.ok || !result.success) {
      throw new Error(errorText(result) || `HTTP ${response.status}`);
    }
    state.benchmarkRuleFileId = result.file_id || "";
    state.hasPendingBenchmarkRuleUpload = false;
    if (el.benchmarkStatus) el.benchmarkStatus.textContent = `${result.file_name || "Benchmark 规则"} 已上传`;
    updateBenchmarkButtons();
    return result;
  } catch (error) {
    state.benchmarkRuleFileId = "";
    state.hasPendingBenchmarkRuleUpload = true;
    if (el.benchmarkStatus) el.benchmarkStatus.textContent = `BM 规则上传失败：${String(error.message || error)}`;
    return null;
  } finally {
    if (el.benchmarkRuleUploadButton) el.benchmarkRuleUploadButton.disabled = !state.hasPendingBenchmarkRuleUpload;
    updateBenchmarkButtons();
  }
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
    const endpoint = state.projectId
      ? `/api/data-agent/projects/${encodeURIComponent(state.projectId)}/sources/upload`
      : files.length === 1
        ? "/api/data-agent/upload"
        : "/api/data-agent/upload-batch";
    if (!state.projectId && files.length === 1) {
      payload.append("file", files[0]);
    } else {
      files.forEach((file) => payload.append("files", file));
    }
    const response = await fetch(endpoint, { method: "POST", body: payload });
    const profile = await response.json();
    if (!response.ok || !profile.success) {
      throw new Error(errorText(profile) || `HTTP ${response.status}`);
    }
    const hasDatasetProfile = Boolean(profile.dataset_id);
    if (hasDatasetProfile) {
      state.profile = profile;
      state.datasetId = profile.dataset_id;
      state.autoRuleFileIds = profile.auto_bound_user_rule_file_ids || [];
      state.userRuleFileId = state.autoRuleFileIds[0] || state.userRuleFileId || "";
      state.selectedTable = profile.tables?.[0]?.table_name || "";
    }
    state.fileRecords = buildReadyFileRecords(files, profile);
    await loadProjects();
    if (state.projectId) {
      await loadProjectWorkspace(state.projectId);
    }
    renderProfile();
    renderFilePanel();
    el.profileMessage.classList.add("hidden");
    setApiStatus(
      "ready",
      hasDatasetProfile
        ? state.autoRuleFileIds.length
          ? "数据和规则已就绪"
          : "数据集已就绪"
        : "项目共享文件已添加",
    );
    state.hasPendingUpload = false;
    el.fileSummary.textContent = `${files.length} 个文件已就绪`;
    el.fileDetail.textContent = "点击查看文件";
    return profile;
  } catch (error) {
    setApiStatus("error", "上传失败");
    state.datasetId = "";
    state.profile = null;
    state.selectedTable = "";
    state.hasPendingUpload = true;
    state.fileRecords = files.map((file) => fileRecordFromFile(file, "failed"));
    el.fileSummary.textContent = `${files.length} 个文件上传失败`;
    el.fileDetail.textContent = "点击查看文件";
    renderFilePanel();
    return null;
  } finally {
    state.isUploading = false;
    el.uploadButton.disabled = !state.hasPendingUpload;
    updateRunButton();
  }
}

async function runAnalysis() {
  const question = getQuestionText();
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
  if (state.ruleModeEnabled && state.hasPendingRuleUpload) {
    const uploadedRule = await uploadUserRule();
    if (!uploadedRule) {
      updateRunButton();
      return;
    }
  }
  state.isAnalyzing = true;
  el.runButton.disabled = true;
  const monitorRunId = startMonitorRun(question);
  const liveActivity = Boolean(window.EventSource && monitorRunId);
  markHistoryRunning(question, monitorRunId);
  appendUserMessage(question);
  setQuestionText("");
  renderProgress(question, { liveActivity });
  if (liveActivity) connectActivityStream(monitorRunId);
  setApiStatus("idle", "处理中");
  try {
    const messageProjectId = currentMessageProjectId();
    const response = await fetch("/api/data-agent/message", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        dataset_id: state.datasetId,
        conversation_id: state.conversationId,
        project_id: messageProjectId,
        question,
        execution_mode: el.executionMode.value,
        agent_mode: el.agentMode.value,
        user_rule_file_id: state.userRuleFileId || "",
        monitor_run_id: monitorRunId,
      }),
    });
    const result = await response.json();
    if (!response.ok) {
      throw new Error(errorText(result) || `HTTP ${response.status}`);
    }
    stopProgress();
    closeActivityStream();
    result.question = question;
    renderResult(result);
    finishMonitorRun(result, question);
    const isChat = result.answer_type === "chat" || result.debug?.agent_mode === "chat_without_dataset" || result.debug?.agent_mode === "chat_with_dataset";
    setApiStatus(result.success ? "ready" : "error", result.success ? (isChat ? "已回复" : "分析完成") : "需要继续确认");
    if (state.projectId) {
      await loadProjects();
    }
    await loadConversations();
  } catch (error) {
    stopProgress();
    closeActivityStream();
    failMonitorRun(question, String(error.message || error));
    markHistoryFailed(question, String(error.message || error));
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

function handleQuestionInput() {
  if (!getQuestionText()) {
    setQuestionText("");
  }
  updateQuestionEmptyState();
  updateRunButton();
}

function handleQuestionPaste(event) {
  const text = event.clipboardData?.getData("text/plain");
  if (text == null) return;
  event.preventDefault();
  document.execCommand("insertText", false, text);
}

function getQuestionText() {
  return (el.questionInput.textContent || "").replace(/\u00a0/g, " ").trim();
}

function setQuestionText(text) {
  el.questionInput.textContent = text || "";
  updateQuestionEmptyState();
}

function updateQuestionEmptyState() {
  el.questionInput.classList.toggle("is-empty", !getQuestionText());
}

async function loadProjects() {
  if (!el.projectList) return;
  try {
    const response = await fetch("/api/data-agent/projects?limit=50");
    const payload = await response.json();
    if (!response.ok || !payload.success) {
      throw new Error(errorText(payload) || `HTTP ${response.status}`);
    }
    state.projects = payload.projects || [];
    if (state.projectId && !state.projects.some((project) => project.project_id === state.projectId)) {
      state.projectId = "";
      state.projectDetails = null;
      state.projectConversations = [];
      state.projectDraftActive = false;
    }
    renderProjects();
  } catch {
    state.projects = [];
    renderProjects();
  }
}

function renderProjects() {
  if (!el.projectList) return;
  if (el.projectCount) el.projectCount.textContent = String(state.projects.length);
  const current = currentProject();
  if (el.projectSummary) {
    el.projectSummary.textContent = current
      ? `${projectSourceCount(current)} files / ${projectMemoryCount(current)} memories`
      : "project-only memory";
  }
  if (!state.projects.length) {
    el.projectList.innerHTML = `<li class="project-empty">暂无 Project</li>`;
    return;
  }
  el.projectList.innerHTML = state.projects
    .map((project) => {
      const projectId = project.project_id || "";
      const name = project.name || "未命名 Project";
      const active = projectId && projectId === state.projectId ? " active" : "";
      return `
        <li class="project-item${active}" data-project-id="${escapeHtml(projectId)}">
          <button class="project-open-button" type="button" title="${escapeHtml(name)}" aria-label="打开 Project ${escapeHtml(name)}">
            <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 6h7l2 2h7v10a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2Z"></path></svg>
            <span>${escapeHtml(name)}</span>
          </button>
          <button class="project-menu-button" type="button" title="Project 选项" aria-label="Project 选项">
            ${ellipsisIcon()}
          </button>
        </li>
      `;
    })
    .join("");
  el.projectList.querySelectorAll(".project-open-button").forEach((button) => {
    button.addEventListener("click", () => openProject(button.closest(".project-item")?.dataset.projectId || ""));
  });
  el.projectList.querySelectorAll(".project-menu-button").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      openProjectMenu(button, button.closest(".project-item")?.dataset.projectId || "");
    });
  });
}

function ellipsisIcon() {
  return `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12h.01M12 12h.01M19 12h.01"></path></svg>`;
}

function editIcon() {
  return `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m12 20 8-8-4-4-8 8-2 6 6-2Z"></path><path d="m14 6 4 4"></path></svg>`;
}

function folderMoveIcon() {
  return `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 6h7l2 2h7v10a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2Z"></path><path d="M12 12v5M9.5 14.5h5"></path></svg>`;
}

function folderIcon() {
  return `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 6h7l2 2h7v10a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2Z"></path></svg>`;
}

function chevronRightIcon() {
  return `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m9 18 6-6-6-6"></path></svg>`;
}

function pinIcon() {
  return `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 17v5"></path><path d="m5 17 14 0"></path><path d="M7 17l2-7-2-5h10l-2 5 2 7"></path></svg>`;
}

function trashIcon() {
  return `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 6h18"></path><path d="M8 6V4h8v2"></path><path d="M6 6l1 15h10l1-15"></path><path d="M10 11v6M14 11v6"></path></svg>`;
}

function openProjectMenu(anchor, projectId) {
  if (!projectId) return;
  showContextMenu(anchor, [
    {
      label: "重命名",
      className: "project-rename-button",
      icon: editIcon(),
      action: () => renameProjectFromId(projectId),
    },
    {
      label: "删除",
      className: "project-delete-button danger",
      icon: trashIcon(),
      action: () => deleteProjectFromId(projectId),
    },
  ]);
}

async function openHistoryMenu(anchor, runId) {
  if (!runId) return;
  if (!state.projects.length) {
    await loadProjects();
  }
  const item = state.runHistory.find((entry) => entry.runId === runId)
    || state.projectConversations.find((entry) => entry.runId === runId);
  const isPinned = Boolean(item?.pinned);
  showContextMenu(anchor, [
    {
      label: isPinned ? "取消置顶" : "置顶聊天",
      className: "history-pin-button",
      icon: pinIcon(),
      action: () => toggleHistoryPinned(runId, !isPinned),
    },
    {
      label: "重命名",
      className: "history-rename-button",
      icon: editIcon(),
      action: () => renameConversationFromPrompt(runId),
    },
    {
      label: "移至项目",
      className: "history-project-button",
      icon: folderMoveIcon(),
      submenu: buildProjectMoveItems(runId),
    },
    {
      label: "删除",
      className: "history-delete-button danger",
      icon: trashIcon(),
      action: () => deleteHistoryConversation(runId),
    },
  ]);
}

function openProjectConversationMenu(anchor, runId) {
  if (!runId) return;
  const item = state.projectConversations.find((entry) => entry.runId === runId)
    || state.runHistory.find((entry) => entry.runId === runId);
  const isPinned = Boolean(item?.pinned);
  showContextMenu(anchor, [
    {
      label: isPinned ? "取消置顶" : "置顶聊天",
      className: "history-pin-button",
      icon: pinIcon(),
      action: () => toggleHistoryPinned(runId, !isPinned),
    },
    {
      label: "重命名",
      className: "history-rename-button",
      icon: editIcon(),
      action: () => renameConversationFromPrompt(runId),
    },
    {
      label: "删除",
      className: "project-conversation-delete-button danger",
      icon: trashIcon(),
      action: () => deleteHistoryConversation(runId),
    },
  ]);
}

function buildProjectMoveItems(runId) {
  const currentItem = state.runHistory.find((entry) => entry.runId === runId)
    || state.projectConversations.find((entry) => entry.runId === runId);
  const currentProjectId = currentItem?.projectId || "";
  const projectItems = state.projects.map((project) => ({
    label: project.name || "未命名 Project",
    className: project.project_id === currentProjectId ? "project-move-target current" : "project-move-target",
    icon: folderIcon(),
    action: () => assignHistoryToProject(runId, project.project_id || ""),
  }));
  return [
    {
      label: "新项目",
      className: "project-move-new",
      icon: folderMoveIcon(),
      action: () => createProjectForHistory(runId),
    },
    ...projectItems,
  ];
}

function showContextMenu(anchor, items) {
  if (!el.contextMenu || !anchor) return;
  closeContextMenu();
  el.contextMenu.innerHTML = items
    .map(
      (item, index) => `
        <div class="context-menu-item${item.submenu ? " has-submenu" : ""}" data-menu-index="${index}">
          <button class="${escapeHtml(item.className || "")}" type="button" role="menuitem"${item.submenu ? ' aria-haspopup="menu" aria-expanded="false"' : ""} data-menu-index="${index}">
            ${item.icon || ""}
            <span class="context-menu-label">${escapeHtml(item.label)}</span>
            ${item.submenu ? `<span class="context-menu-chevron">${chevronRightIcon()}</span>` : ""}
          </button>
          ${item.submenu ? renderContextSubmenu(item.submenu, index) : ""}
        </div>
      `,
    )
    .join("");
  el.contextMenu.classList.remove("hidden");
  const rect = anchor.getBoundingClientRect();
  const menuRect = el.contextMenu.getBoundingClientRect();
  const left = Math.max(8, Math.min(window.innerWidth - menuRect.width - 8, rect.right - menuRect.width));
  const top = Math.max(8, Math.min(window.innerHeight - menuRect.height - 8, rect.bottom + 6));
  el.contextMenu.style.left = `${left}px`;
  el.contextMenu.style.top = `${top}px`;
  el.contextMenu.classList.toggle("submenu-left", left + menuRect.width + 260 > window.innerWidth);
  el.contextMenu.querySelectorAll(".context-menu-item").forEach((row) => {
    row.addEventListener("mouseenter", () => {
      if (row.classList.contains("has-submenu")) {
        showContextSubmenu(row);
      } else {
        closeContextSubmenus();
      }
    });
    row.addEventListener("focusin", () => {
      if (row.classList.contains("has-submenu")) {
        showContextSubmenu(row);
      }
    });
  });
  el.contextMenu.querySelectorAll("button[data-menu-index]").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      const item = items[Number(button.dataset.menuIndex || 0)];
      if (item?.submenu) {
        showContextSubmenu(button.closest(".context-menu-item"));
        return;
      }
      closeContextMenu();
      item?.action?.();
    });
  });
  el.contextMenu.querySelectorAll("button[data-submenu-index]").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      const item = items[Number(button.dataset.parentIndex || 0)]?.submenu?.[Number(button.dataset.submenuIndex || 0)];
      closeContextMenu();
      item?.action?.();
    });
  });
}

function renderContextSubmenu(items, parentIndex) {
  if (!items?.length) {
    return `<div class="context-submenu hidden" role="menu"><div class="context-menu-empty">暂无 Project</div></div>`;
  }
  return `
    <div class="context-submenu hidden" role="menu">
      ${items
        .map(
          (item, index) => `
            <button class="${escapeHtml(item.className || "")}" type="button" role="menuitem" data-parent-index="${parentIndex}" data-submenu-index="${index}">
              ${item.icon || ""}
              <span class="context-menu-label">${escapeHtml(item.label)}</span>
            </button>
          `,
        )
        .join("")}
    </div>
  `;
}

function showContextSubmenu(row) {
  if (!row) return;
  closeContextSubmenus();
  row.querySelector(".context-submenu")?.classList.remove("hidden");
  row.querySelector("button")?.setAttribute("aria-expanded", "true");
}

function closeContextSubmenus() {
  if (!el.contextMenu) return;
  el.contextMenu.querySelectorAll(".context-submenu").forEach((submenu) => submenu.classList.add("hidden"));
  el.contextMenu.querySelectorAll("[aria-expanded='true']").forEach((button) => button.setAttribute("aria-expanded", "false"));
}

function closeContextMenuFromOutside(event) {
  if (!el.contextMenu || el.contextMenu.classList.contains("hidden")) return;
  if (event.target.closest(".context-menu, .history-menu-button, .project-menu-button, .project-conversation-menu-button")) return;
  closeContextMenu();
}

function closeContextMenu() {
  if (!el.contextMenu) return;
  el.contextMenu.classList.add("hidden");
  el.contextMenu.classList.remove("submenu-left");
  el.contextMenu.innerHTML = "";
}

function currentProject() {
  if (state.projectDetails?.project_id === state.projectId) return state.projectDetails;
  return state.projects.find((project) => project.project_id === state.projectId) || null;
}

function projectSourceCount(project) {
  return Number(project?.source_count ?? project?.sources?.length ?? 0);
}

function projectMemoryCount(project) {
  return Number(project?.memory_count ?? project?.memories?.length ?? 0);
}

async function createProjectFromPrompt() {
  const rawName = window.prompt("Project name", "新 Project");
  const name = String(rawName || "").trim();
  if (!name) return;
  try {
    const response = await fetch("/api/data-agent/projects", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    });
    const payload = await response.json();
    if (!response.ok || !payload.success) {
      throw new Error(errorText(payload) || `HTTP ${response.status}`);
    }
    state.projectId = payload.project?.project_id || "";
    state.projectDetails = payload.project || null;
    state.projectConversations = [];
    state.projectViewTab = "chats";
    state.projectDraftActive = false;
    await loadProjects();
    resetConversation();
    await loadProjectWorkspace(state.projectId);
    await loadConversations();
    setApiStatus("ready", "Project 已创建");
  } catch (error) {
    setApiStatus("error", `Project 创建失败：${String(error.message || error)}`);
  }
}

async function renameCurrentProjectFromPrompt() {
  return renameProjectFromId(state.projectId);
}

async function renameProjectFromId(projectId) {
  const current = state.projects.find((project) => project.project_id === projectId) || currentProject();
  if (!current) return;
  const rawName = window.prompt("Project name", current.name || "未命名 Project");
  const name = String(rawName || "").trim();
  if (!name || name === current.name) return;
  try {
    const response = await fetch(`/api/data-agent/projects/${encodeURIComponent(current.project_id)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    });
    const payload = await response.json();
    if (!response.ok || !payload.success) {
      throw new Error(errorText(payload) || `HTTP ${response.status}`);
    }
    if (state.projectId === current.project_id) {
      state.projectDetails = payload.project || state.projectDetails;
    }
    await loadProjects();
    renderProjectHome();
    setApiStatus("ready", "Project 已重命名");
  } catch (error) {
    setApiStatus("error", `Project 重命名失败：${String(error.message || error)}`);
  }
}

async function deleteCurrentProject() {
  return deleteProjectFromId(state.projectId);
}

async function deleteProjectFromId(projectId) {
  const current = state.projects.find((project) => project.project_id === projectId) || currentProject();
  if (!current) return;
  if (!window.confirm(`删除 Project「${current.name || "未命名 Project"}」？项目内对话会移出 Project，数据文件不会被删除。`)) return;
  try {
    const response = await fetch(`/api/data-agent/projects/${encodeURIComponent(current.project_id)}`, {
      method: "DELETE",
    });
    const payload = await response.json();
    if (!response.ok || !payload.success) {
      throw new Error(errorText(payload) || `HTTP ${response.status}`);
    }
    const deletedActiveProject = state.projectId === current.project_id;
    if (deletedActiveProject) {
      state.projectId = "";
      state.projectDetails = null;
      state.projectConversations = [];
      state.projectDraftActive = false;
      resetConversation();
    }
    await loadProjects();
    await loadConversations();
    setApiStatus("ready", "Project 已删除");
  } catch (error) {
    setApiStatus("error", `Project 删除失败：${String(error.message || error)}`);
  }
}

async function handleProjectChange() {
  await openProject(state.projectId);
}

async function openProject(projectId) {
  const safeProjectId = String(projectId || "").trim();
  if (!safeProjectId) {
    startGlobalConversation();
    return;
  }
  state.projectId = safeProjectId;
  state.projectViewTab = "chats";
  state.projectDraftActive = false;
  renderProjects();
  resetConversation();
  await loadProjectWorkspace(safeProjectId);
  setApiStatus("ready", "Project 已打开");
}

function startGlobalConversation() {
  state.projectId = "";
  state.projectDetails = null;
  state.projectConversations = [];
  state.projectViewTab = "chats";
  state.projectDraftActive = false;
  renderProjects();
  resetConversation();
}

function startProjectConversation() {
  if (!state.projectId) return;
  state.projectDraftActive = true;
  resetConversation();
  el.questionInput?.focus();
}

async function loadProjectWorkspace(projectId = state.projectId) {
  const safeProjectId = String(projectId || "").trim();
  if (!safeProjectId) {
    state.projectDetails = null;
    state.projectConversations = [];
    renderProjectHome();
    return;
  }
  try {
    const projectResponse = await fetch(`/api/data-agent/projects/${encodeURIComponent(safeProjectId)}`);
    const projectPayload = await projectResponse.json();
    if (!projectResponse.ok || !projectPayload.success) {
      throw new Error(errorText(projectPayload) || `HTTP ${projectResponse.status}`);
    }
    state.projectDetails = projectPayload.project || null;
    state.projectConversations = await loadProjectConversations(safeProjectId);
  } catch (error) {
    state.projectDetails = currentProject();
    state.projectConversations = [];
    setApiStatus("error", `Project 载入失败：${String(error.message || error)}`);
  }
  renderProjects();
  renderProjectHome();
}

async function loadProjectConversations(projectId) {
  const scopedQuery = new URLSearchParams({ limit: "30", project_id: projectId });
  const response = await fetch(`/api/data-agent/conversations?${scopedQuery.toString()}`);
  const payload = await response.json();
  if (!response.ok || !payload.success) {
    throw new Error(errorText(payload) || `HTTP ${response.status}`);
  }
  return sortHistoryItems((payload.conversations || []).map((item) => ({
    runId: item.conversation_id || "",
    title: item.title || "未命名对话",
    answer: item.last_message || "",
    question: item.last_message || "",
    updatedAt: item.updated_at || "",
    pinned: Boolean(item.pinned),
    pinnedAt: item.pinned_at || "",
    messageCount: item.message_count || 0,
    datasetId: item.dataset_id || "",
    projectId: item.project_id || projectId,
  })));
}

function setProjectTab(tab) {
  state.projectViewTab = tab === "sources" ? "sources" : "chats";
  renderProjectHome();
}

function renderProjectHome() {
  if (!el.projectHome) return;
  const current = currentProject();
  const showProjectHome = Boolean(state.projectId && !state.conversationId && !state.projectDraftActive);
  updateShellMode(showProjectHome);
  el.projectHome.classList.toggle("hidden", !showProjectHome);
  if (!showProjectHome) {
    updateProjectTabs();
    return;
  }
  el.welcomeMessage?.classList.add("hidden");
  const projectName = current?.name || "未命名 Project";
  if (el.projectHomeTitle) el.projectHomeTitle.textContent = projectName;
  if (el.projectNewChatLabel) el.projectNewChatLabel.textContent = `${projectName} 中的新聊天`;
  renderProjectConversationList();
  renderProjectSourceList();
  updateProjectTabs();
}

function updateShellMode(showProjectHome = Boolean(state.projectId && !state.conversationId && !state.projectDraftActive)) {
  document.body.classList.toggle("project-home-mode", showProjectHome);
  document.body.classList.toggle("project-context-mode", Boolean(state.projectId));
}

function updateProjectTabs() {
  const isSources = state.projectViewTab === "sources";
  el.projectTabChats?.classList.toggle("active", !isSources);
  el.projectTabSources?.classList.toggle("active", isSources);
  el.projectTabChats?.setAttribute("aria-selected", String(!isSources));
  el.projectTabSources?.setAttribute("aria-selected", String(isSources));
  el.projectChatsPanel?.classList.toggle("hidden", isSources);
  el.projectSourcesPanel?.classList.toggle("hidden", !isSources);
}

function renderProjectConversationList() {
  if (!el.projectConversationList) return;
  const conversations = state.projectConversations || [];
  if (!conversations.length) {
    el.projectConversationList.innerHTML = `<li class="project-home-empty">这个 Project 还没有聊天。</li>`;
    return;
  }
  el.projectConversationList.innerHTML = conversations
    .map((item) => `
      <li class="project-conversation-item${item.pinned ? " pinned" : ""}" data-conversation-id="${escapeHtml(item.runId || "")}">
        <button class="project-conversation-open" type="button" title="${escapeHtml(item.title || "未命名对话")}">
          <span class="project-conversation-title-row">
            ${item.pinned ? `<span class="pin-indicator" title="已置顶">${pinIcon()}</span>` : ""}
            <strong>${escapeHtml(item.title || "未命名对话")}</strong>
          </span>
          <span>${escapeHtml(projectConversationMeta(item))}</span>
        </button>
        <button class="project-conversation-menu-button" type="button" title="对话选项" aria-label="对话选项">
          ${ellipsisIcon()}
        </button>
      </li>
    `)
    .join("");
  el.projectConversationList.querySelectorAll(".project-conversation-open").forEach((button) => {
    button.addEventListener("click", () => loadConversation(button.closest(".project-conversation-item")?.dataset.conversationId || ""));
  });
  el.projectConversationList.querySelectorAll(".project-conversation-menu-button").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      openProjectConversationMenu(button, button.closest(".project-conversation-item")?.dataset.conversationId || "");
    });
  });
}

function renderProjectSourceList() {
  const project = state.projectDetails || {};
  renderProjectSourceGroup(el.projectSourceList, project.sources || [], "上传共享文件后会显示在这里。", deleteProjectSource);
  renderProjectSourceGroup(el.projectMemoryList, project.memories || [], "保存的 Project memory 会显示在这里。", deleteProjectMemory);
}

function renderProjectSourceGroup(listEl, records, emptyText, deleteHandler) {
  if (!listEl) return;
  if (!records.length) {
    listEl.innerHTML = `<li class="project-home-empty">${escapeHtml(emptyText)}</li>`;
    return;
  }
  listEl.innerHTML = records
    .map((record) => {
      const id = record.source_id || record.memory_id || "";
      const title = record.title || sourceTypeLabel(record.source_type || record.memory_type || "source");
      const meta = projectSourceMeta(record);
      return `
        <li class="project-source-item" data-record-id="${escapeHtml(id)}">
          <div>
            <strong>${escapeHtml(title)}</strong>
            <span>${escapeHtml(meta)}</span>
          </div>
          <button class="project-source-delete-button" type="button" title="删除" aria-label="删除">
            <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 6h18"></path><path d="M8 6V4h8v2"></path><path d="M6 6l1 15h10l1-15"></path><path d="M10 11v6M14 11v6"></path></svg>
          </button>
        </li>
      `;
    })
    .join("");
  listEl.querySelectorAll(".project-source-delete-button").forEach((button) => {
    button.addEventListener("click", () => deleteHandler(button.closest(".project-source-item")?.dataset.recordId || ""));
  });
}

function projectConversationMeta(item) {
  const count = item.messageCount ? `${item.messageCount} 条消息` : "Project chat";
  const updated = item.updatedAt ? ` · ${formatShortDate(item.updatedAt)}` : "";
  return `${item.pinned ? "已置顶 · " : ""}${count}${updated}`;
}

function projectSourceMeta(record) {
  const type = sourceTypeLabel(record.source_type || record.memory_type || "source");
  const ref = record.dataset_id || record.file_id || "";
  return ref ? `${type} · ${ref}` : type;
}

function sourceTypeLabel(type) {
  const labels = {
    dataset: "共享数据",
    rule: "规则文件",
    note: "项目说明",
    saved_response: "保存的回答",
    pinned: "Pinned memory",
    conversation_summary: "对话摘要",
  };
  return labels[type] || "Project source";
}

function formatShortDate(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleDateString("zh-CN", { month: "2-digit", day: "2-digit" });
}

async function deleteProjectSource(sourceId) {
  if (!state.projectId || !sourceId) return;
  if (!window.confirm("删除这个 Project source？")) return;
  try {
    const response = await fetch(`/api/data-agent/projects/${encodeURIComponent(state.projectId)}/sources/${encodeURIComponent(sourceId)}`, {
      method: "DELETE",
    });
    const payload = await response.json();
    if (!response.ok || !payload.success) {
      throw new Error(errorText(payload) || `HTTP ${response.status}`);
    }
    state.projectDetails = payload.project || state.projectDetails;
    await loadProjects();
    await loadProjectWorkspace(state.projectId);
    setApiStatus("ready", "Project source 已删除");
  } catch (error) {
    setApiStatus("error", `Project source 删除失败：${String(error.message || error)}`);
  }
}

async function deleteProjectMemory(memoryId) {
  if (!state.projectId || !memoryId) return;
  if (!window.confirm("删除这个 Project memory？")) return;
  try {
    const response = await fetch(`/api/data-agent/projects/${encodeURIComponent(state.projectId)}/memories/${encodeURIComponent(memoryId)}`, {
      method: "DELETE",
    });
    const payload = await response.json();
    if (!response.ok || !payload.success) {
      throw new Error(errorText(payload) || `HTTP ${response.status}`);
    }
    state.projectDetails = payload.project || state.projectDetails;
    await loadProjects();
    await loadProjectWorkspace(state.projectId);
    setApiStatus("ready", "Project memory 已删除");
  } catch (error) {
    setApiStatus("error", `Project memory 删除失败：${String(error.message || error)}`);
  }
}

function updateRunButton() {
  const hasQuestion = Boolean(getQuestionText());
  el.runButton.disabled = !hasQuestion || state.isUploading || state.isAnalyzing;
  updateBenchmarkButtons();
}

function currentMessageProjectId() {
  if (!state.projectId) return "";
  return state.conversationId || state.projectDraftActive ? state.projectId : "";
}

function updateBenchmarkButtons() {
  if (el.benchmarkRuleUploadButton) {
    el.benchmarkRuleUploadButton.disabled = !state.hasPendingBenchmarkRuleUpload;
  }
  if (el.benchmarkRunButton) {
    el.benchmarkRunButton.disabled = !state.datasetId || !state.benchmarkRuleFileId || state.isAnalyzing || state.isUploading;
  }
}

async function runBenchmark() {
  if (!state.datasetId) {
    if (el.benchmarkStatus) el.benchmarkStatus.textContent = "请先上传数据文件";
    return;
  }
  if (state.hasPendingBenchmarkRuleUpload) {
    const uploaded = await uploadBenchmarkRule();
    if (!uploaded) return;
  }
  if (!state.benchmarkRuleFileId) {
    if (el.benchmarkStatus) el.benchmarkStatus.textContent = "请先上传 Benchmark 规则";
    return;
  }
  if (el.benchmarkRunButton) el.benchmarkRunButton.disabled = true;
  if (el.benchmarkStatus) el.benchmarkStatus.textContent = "Benchmark 运行中";
  try {
    const response = await fetch("/api/data-agent/benchmark/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        dataset_id: state.datasetId,
        benchmark_rule_file_id: state.benchmarkRuleFileId,
        user_rule_file_id: state.ruleModeEnabled ? state.userRuleFileId : "",
        execution_mode: el.executionMode.value,
        agent_mode: el.agentMode.value,
      }),
    });
    const result = await response.json();
    if (!response.ok || !result.success) {
      throw new Error(errorText(result) || `HTTP ${response.status}`);
    }
    const accuracy = result.accuracy == null ? "未评分" : `${Math.round(result.accuracy * 10000) / 100}%`;
    if (el.benchmarkStatus) el.benchmarkStatus.textContent = `BM 完成：${result.correct}/${result.scored}，${accuracy}`;
  } catch (error) {
    if (el.benchmarkStatus) el.benchmarkStatus.textContent = `BM 失败：${String(error.message || error)}`;
  } finally {
    updateBenchmarkButtons();
  }
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

function renderResult(result, options = {}) {
  if (result.conversation_id) {
    state.conversationId = result.conversation_id;
  }
  if (result.dataset_id) {
    state.datasetId = result.dataset_id;
  }
  const rows = result.result?.rows || [];
  const columns = result.result?.columns || [];
  const isChat = result.answer_type === "chat" || result.debug?.agent_mode === "chat_without_dataset" || result.debug?.agent_mode === "chat_with_dataset";
  const isOverviewShaped = Boolean(result.debug?.user_experience_shaping?.applied);
  el.resultMessage.classList.remove("thinking-only");
  el.resultTitle.textContent = isChat ? "VDS" : "分析结果";
  el.answer.textContent = result.answer || "-";
  el.resultStatus.textContent = isChat ? "已回复" : result.success ? "已完成" : "需要继续确认";
  renderRows(rows, columns, result);
  renderChart(isOverviewShaped ? null : result.chart, rows, columns, result.answer);
  renderInsight(!isChat && result.success ? result.insight : null);
  renderProcess(result.process_view_v2 || result.reasoning_trace_view || [], result);
  renderExecutionArtifacts([]);
  if (options.updateHistory !== false) {
    pushHistory(result);
  }
  revealMessage(el.resultMessage, "start");
}

function renderRows(rows, columns, result = {}) {
  if (!rows.length || !shouldRenderRows(rows, columns, result)) {
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

function shouldRenderRows(rows, columns, result = {}) {
  if (!Array.isArray(rows) || !rows.length) return false;
  const safeColumns = columns.length ? columns : Object.keys(rows[0] || {});
  const isOverview = result.answer_type === "overview" || result.execution_mode === "overview";
  const isCleaning = result.answer_type === "cleaning_simulation" || result.execution_mode === "cleaning_simulation";
  if (isOverview) {
    const compactOverviewColumns = [
      ["指标", "数值"],
      ["表名", "来源", "行数", "列数", "可能含义", "关键字段"],
    ];
    return rows.length <= 30 && compactOverviewColumns.some((allowed) => allowed.length === safeColumns.length && allowed.every((column, index) => column === safeColumns[index]));
  }
  if (isCleaning) {
    return rows.length <= 40 && safeColumns.length <= 5;
  }
  const generalQuestion = looksLikeGeneralQuestion(result.question || "");
  const tooWideForMainAnswer = safeColumns.length > 12;
  const likelyRawDump = rows.length > 8 && tooWideForMainAnswer;
  return !(generalQuestion && likelyRawDump);
}

function looksLikeGeneralQuestion(question) {
  const compact = String(question || "").replace(/\s+/g, "");
  const tokens = ["看一下", "看下", "看看", "总结", "概览", "总览", "主要讲什么", "讲什么", "有什么字段", "有哪些字段", "字段含义", "什么意思", "清洗", "影响行数", "影响比例", "修改原始数据"];
  return tokens.some((token) => compact.includes(token));
}

function renderChart(chart, fallbackRows = [], fallbackColumns = [], answer = "") {
  el.chartPanel.classList.remove("hidden");
  const type = chart?.chart_type;
  const rows = chart?.data?.length ? chart.data : fallbackRows;
  const x = chart?.x || fallbackColumns[0];
  if (!type || type === "kpi") {
    el.chartPanel.className = "chart-panel hidden";
    return;
  }
  if (chart?.image_data_uri) {
    el.chartPanel.className = "chart-panel";
    el.chartPanel.innerHTML = renderChartImage(chart);
    return;
  }
  const y = resolveChartY(rows, chart?.y, fallbackColumns);
  if (!rows.length || !x || !y) {
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

function resolveChartY(rows, requestedY, fallbackColumns) {
  if (requestedY && rows.some((row) => Number.isFinite(Number(row?.[requestedY])))) {
    return requestedY;
  }
  return fallbackColumns.find((column) => rows.some((row) => Number.isFinite(Number(row?.[column]))));
}

function renderChartImage(chart) {
  return `
    <div class="chart-title">${escapeHtml(chart?.title || "自动图表")}</div>
    <img class="chart-image" src="${escapeHtml(chart.image_data_uri)}" alt="${escapeHtml(chart?.title || "分析图表")}" />
  `;
}

function renderBarChart(values, chart, horizontal) {
  const width = 620;
  const displayValues = values.slice(0, horizontal ? 18 : 16);
  const height = Math.max(230, displayValues.length * (horizontal ? 26 : 0) + 170);
  const max = Math.max(...values.map((item) => Math.abs(item.value)), 1);
  const colors = ["#2563eb", "#0ea5e9", "#4f46e5", "#14b8a6", "#f59e0b", "#64748b"];
  const bars = displayValues.map((item, index) => {
    if (horizontal) {
      const barWidth = (Math.abs(item.value) / max) * 410;
      const y = 58 + index * 28;
      return `
        <text x="20" y="${y + 15}" class="axis-label">${escapeHtml(shortLabel(item.label, 16))}</text>
        <rect x="150" y="${y}" width="${barWidth}" height="18" fill="${colors[index % colors.length]}" rx="3"></rect>
        <text x="${160 + barWidth}" y="${y + 14}" class="value-label">${formatNumber(item.value)}</text>
      `;
    }
    const barWidth = Math.max(18, 420 / displayValues.length - 10);
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
  const findings = [...(insight?.anomaly_findings || []), ...(insight?.volatility_findings || [])]
    .map((item) => item?.message)
    .filter(isUserFacingInsightText);
  const caveats = (insight?.caveats || []).filter(isUserFacingInsightText);
  const summary = cleanInsightSummary(insight?.summary || "");
  const hasInsight = Boolean(summary || suggestions.length || findings.length || caveats.length);
  el.insightPanel?.classList.toggle("hidden", !hasInsight);
  if (!hasInsight) {
    el.insightSummary.textContent = "";
    el.insightList.innerHTML = "";
    return;
  }
  el.insightSummary.textContent = summary;
  const items = [];
  findings.slice(0, 2).forEach((text) => items.push({ label: "洞察", text }));
  suggestions.slice(0, 3).forEach((text) => items.push({ label: insightCardLabel(text), text }));
  caveats.slice(0, 2).forEach((text) => items.push({ label: "边界", text }));
  el.insightList.innerHTML = items.length
    ? items.map((item) => renderInsightCard(item)).join("")
    : "";
}

function insightCardLabel(text) {
  return String(text || "").includes("观察") ? "洞察" : "建议";
}

function renderInsightCard(item) {
  const parsed = parseInsightText(item.text);
  return `
    <li class="insight-card ${escapeHtml(item.label)}">
      <strong>${escapeHtml(item.label)}</strong>
      <p>${escapeHtml(parsed.observation)}</p>
      ${parsed.evidence ? `<span>依据：${escapeHtml(parsed.evidence)}</span>` : ""}
      ${parsed.action ? `<span>建议：${escapeHtml(parsed.action)}</span>` : ""}
    </li>
  `;
}

function parseInsightText(text) {
  const raw = String(text || "").trim();
  const observation = raw.match(/观察[:：]([^；;]+)/)?.[1]?.trim() || raw.split(/[；;]/)[0] || raw;
  const evidence = raw.match(/依据[:：]([^；;]+)/)?.[1]?.trim() || "";
  const action = raw.match(/建议[:：]([^；;]+)/)?.[1]?.trim() || "";
  return { observation, evidence, action };
}

function renderExecutionArtifacts(artifacts) {
  const safeArtifacts = Array.isArray(artifacts) ? artifacts.filter((item) => item && item.code) : [];
  el.artifactPanel?.classList.add("hidden");
  if (!el.artifactList) return;
  el.artifactList.innerHTML = "";
}

function renderArtifactCards(artifacts) {
  const safeArtifacts = Array.isArray(artifacts) ? artifacts.filter((item) => item && item.code) : [];
  if (!safeArtifacts.length) return "";
  return `
    <li class="completed process-artifacts">
      <div>
        <strong>复现代码</strong>
        <p>这里收起展示安全复现片段，不在主答案区域占位。</p>
        <div class="artifact-list inline">
          ${safeArtifacts
    .slice(0, 3)
    .map(
      (artifact) => `
        <article class="artifact-card">
          <div class="artifact-card-header">
            <strong>${escapeHtml(artifact.title || artifact.language || "代码")}</strong>
            <span>${escapeHtml((artifact.language || "").toUpperCase())}</span>
          </div>
          <p>${escapeHtml(artifact.purpose || "安全复现片段。")}</p>
          <pre><code>${escapeHtml(artifact.code || "")}</code></pre>
          ${artifact.output_summary ? `<small>${escapeHtml(artifact.output_summary)}</small>` : ""}
        </article>
      `,
    )
    .join("")}
        </div>
      </div>
    </li>
  `;
}

function renderProgress(question, options = {}) {
  stopProgress();
  const message = createAssistantResultMessage();
  bindResultMessage(message);
  el.resultMessage.classList.add("thinking-only");
  el.resultTable.className = "result-table hidden";
  el.resultTable.textContent = "";
  el.chartPanel.className = "chart-panel hidden";
  el.chartPanel.textContent = "";
  el.insightPanel?.classList.add("hidden");
  renderExecutionArtifacts([]);
  el.chatMessages.append(el.resultMessage);
  revealMessage(el.resultMessage);

  const steps = buildLiveSteps(question, Boolean(state.datasetId));
  if (options.liveActivity) {
    renderProcessItems(
      [{ title: "接收实时过程", summary: "我先确认问题类型和可用数据，然后等待后端安全事件。", status: "active" }],
      "我先确认问题类型和可用数据。",
      [],
      { collapse: false },
    );
    return;
  }
  const update = () => {
    const currentStep = steps[state.progressStep] || steps[steps.length - 1];
    renderProcessItems(
      steps.map((step, index) => ({
        ...step,
        status: index < state.progressStep ? "completed" : index === state.progressStep ? "active" : "pending",
      })),
      currentStep?.summary || "正在整理回答。",
      [],
      { collapse: false },
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

function connectActivityStream(monitorRunId) {
  closeActivityStream();
  state.activityEvents = [];
  if (!window.EventSource || !monitorRunId) return false;
  const source = new EventSource(`/api/data-agent/monitor/stream?monitor_run_id=${encodeURIComponent(monitorRunId)}`);
  state.activitySource = source;
  ACTIVITY_EVENT_TYPES.forEach((type) => source.addEventListener(type, handleActivityEvent));
  source.onerror = () => {
    if (state.isAnalyzing) {
      setApiStatus("idle", "实时过程重试中");
    }
  };
  return true;
}

function closeActivityStream() {
  if (state.activitySource) {
    state.activitySource.close();
    state.activitySource = null;
  }
}

function handleActivityEvent(event) {
  let payload;
  try {
    payload = JSON.parse(event.data || "{}");
  } catch {
    return;
  }
  if (!payload || payload.monitor_run_id !== state.activeMonitorRunId) return;
  const step = activityStepFromMonitorEvent(payload);
  if (!step) return;
  const duplicate = state.activityEvents.some((item) => item.eventId === step.eventId);
  if (!duplicate) {
    state.activityEvents.push(step);
    state.activityEvents = state.activityEvents.slice(-12);
  }
  const latest = state.activityEvents.at(-1);
  const timelineSteps = state.activityEvents.map((item, index) => ({
    title: item.title,
    summary: item.summary,
    status: index === state.activityEvents.length - 1 && item.status === "active" ? "active" : item.status === "failed" ? "failed" : "completed",
  }));
  renderProcessItems(timelineSteps, latest?.summary || "正在处理。", [], { collapse: false });
}

function activityStepFromMonitorEvent(event) {
  const type = String(event.event_type || "");
  const status = event.status === "failed" ? "failed" : event.status === "active" ? "active" : "completed";
  const titleByType = {
    monitor_connected: "连接实时过程",
    message_requested: "理解问题",
    analysis_requested: "准备分析",
    workflow_started: "启动流程",
    agent_started: "执行步骤",
    agent_completed: "完成步骤",
    workflow_completed: "完成流程",
    response_ready: "生成回答",
    analysis_failed: "处理失败",
    thought_delta: "过程摘要",
    tool_considered: "选择工具",
    dependency_note: "检查依赖",
    data_scan_note: "扫描数据",
    plan_note: "制定计划",
    code_artifact_ready: "准备代码",
    answer_outline_ready: "整理回答",
  };
  const summaryByType = {
    monitor_connected: "实时过程通道已连接。",
    message_requested: "我先判断这是普通对话、数据概览、清洗策略还是正式分析。",
    analysis_requested: "我正在读取上传数据，并准备选择合适的后端路径。",
    workflow_started: "后端分析流程已开始，我只展示安全活动摘要。",
    agent_started: `${monitorRoleName(event.role)} 正在处理。`,
    agent_completed: `${monitorRoleName(event.role)} 已完成。`,
    workflow_completed: "后端流程已完成，正在合并最终结果。",
    response_ready: "最终结果已生成，我会以主回答和过程详情展示。",
    analysis_failed: "处理遇到问题，我会返回可读错误。",
    thought_delta: cleanActivityText(event.summary) || "正在整理安全过程摘要。",
    tool_considered: cleanActivityText(event.summary) || "正在选择可用工具路径。",
    dependency_note: cleanActivityText(event.summary) || "正在检查依赖和读取方式。",
    data_scan_note: cleanActivityText(event.summary) || "正在检查文件结构和字段。",
    plan_note: cleanActivityText(event.summary) || "正在制定分析计划。",
    code_artifact_ready: cleanActivityText(event.summary) || "复现代码片段已准备好，稍后放在处理过程里。",
    answer_outline_ready: cleanActivityText(event.summary) || "正在整理最终回答结构。",
  };
  if (!titleByType[type]) return null;
  return {
    eventId: event.event_id || `${type}_${state.activityEvents.length}`,
    title: titleByType[type],
    summary: summaryByType[type] || cleanActivityText(event.summary) || "正在处理。",
    status,
  };
}

function cleanActivityText(text) {
  const value = String(text || "").trim();
  if (!value) return "";
  const lowered = value.toLowerCase();
  const blocked = ["chain_of_thought", "raw_prompt", "raw reasoning", "reasoning_tokens", "api_key", "task_id", "standard_answer", "hidden_answer", "public_proxy", "scorer"];
  if (blocked.some((token) => lowered.includes(token))) return "";
  return shortLabel(value.replace(/\s+/g, " "), 96);
}

function monitorRoleName(role) {
  const key = String(role || "").trim();
  const names = {
    planner: "计划节点",
    executor: "执行节点",
    verifier: "校验节点",
    correction: "修正节点",
    response_builder: "回答节点",
    single_agent: "单 Agent",
  };
  return names[key] || key || "后端节点";
}

function renderProcess(processSource, result = {}) {
  const artifacts = result.execution_artifacts || [];
  if (processSource && !Array.isArray(processSource) && Array.isArray(processSource.steps)) {
    const steps = processSource.steps.map((step) => ({
      title: step.title || "-",
      summary: step.summary || "",
      status: step.status || "completed",
      evidence: normalizeProcessList(step.evidence, 4),
      assumptions: normalizeProcessList(step.assumptions, 3),
      caveats: normalizeProcessList(step.caveats, 3),
    }));
    renderProcessItems(steps, processSource.summary || "已完成本次分析。", artifacts, { collapse: true });
    return;
  }
  const steps = Array.isArray(processSource) ? processSource : [];
  if (!steps.length && !result.question && !result.answer) {
    renderProcessItems([], "提问后显示分析过程。", artifacts, { collapse: true });
    return;
  }
  const friendlySteps = buildFriendlySteps(steps, result);
  if (!friendlySteps.length) {
    renderProcessItems([], "提问后显示分析过程。", artifacts, { collapse: true });
    return;
  }
  renderProcessItems(friendlySteps, result.question ? `围绕“${shortLabel(result.question, 28)}”整理出回答。` : "本次回答已生成。", artifacts, { collapse: true });
}

function renderProcessItems(steps, summary, artifacts = [], options = {}) {
  el.processSummary.textContent = summary;
  if (options.collapse && el.processDetails) el.processDetails.open = false;
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
          <div>
            <strong>${escapeHtml(step.title || "-")}</strong>
            <p>${escapeHtml(step.summary || "")}</p>
            ${renderProcessEvidence(step)}
          </div>
        </li>
      `,
    )
    .join("") + renderArtifactCards(artifacts);
}

function normalizeProcessList(value, limit) {
  const items = Array.isArray(value) ? value : value ? [value] : [];
  return items
    .map((item) => String(item ?? "").trim())
    .filter(Boolean)
    .slice(0, limit);
}

function renderProcessEvidence(step) {
  const evidence = normalizeProcessList(step.evidence, 4);
  const caveats = normalizeProcessList(step.caveats, 3);
  const assumptions = normalizeProcessList(step.assumptions, 3);
  const chips = [
    ...evidence.map((text) => ({ text, type: "evidence" })),
    ...assumptions.map((text) => ({ text, type: "assumption" })),
    ...caveats.map((text) => ({ text, type: "caveat" })),
  ];
  if (!chips.length) return "";
  return `
    <div class="process-evidence" aria-label="过程依据">
      ${chips.map((chip) => `<span class="${escapeHtml(chip.type)}">${escapeHtml(chip.text)}</span>`).join("")}
    </div>
  `;
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
  renderExecutionArtifacts([]);
  renderProcessItems([{ title, summary: message || "请检查上传文件或稍后重试。", status: "failed" }], "处理没有完成。");
  revealMessage(el.resultMessage);
}

function pushHistory(result) {
  const isChat = result.answer_type === "chat" || result.debug?.agent_mode === "chat_without_dataset" || result.debug?.agent_mode === "chat_with_dataset";
  const conversation = result.conversation || {};
  const conversationId = result.conversation_id || conversation.conversation_id || state.conversationId || result.run_id || `history_${Date.now()}`;
  if (conversationId) {
    state.conversationId = conversationId;
  }
  const item = {
    runId: conversationId,
    success: result.success,
    answer: result.answer,
    question: result.question,
    title: conversation.title || result.question,
    mode: isChat ? "chat" : "analysis",
    unread: true,
    updatedAt: conversation.updated_at || new Date().toISOString(),
    messageCount: conversation.message_count || 0,
    projectId: conversation.project_id || currentMessageProjectId(),
    pinned: Boolean(conversation.pinned),
    pinnedAt: conversation.pinned_at || "",
  };
  state.runHistory = state.runHistory.filter((entry) => entry.runId !== conversationId && (!state.activeHistoryRunId || entry.runId !== state.activeHistoryRunId));
  state.activeHistoryRunId = "";
  state.runHistory.unshift(item);
  state.runHistory = sortHistoryItems(state.runHistory).slice(0, 8);
  renderHistory();
}

function markHistoryRunning(question, fallbackRunId) {
  const runId = state.conversationId || fallbackRunId || `pending_${Date.now()}`;
  state.activeHistoryRunId = runId;
  const existing = state.runHistory.find((entry) => entry.runId === runId);
  const item = {
    runId,
    success: null,
    answer: "",
    question,
    title: existing?.title || question || "新对话",
    mode: "running",
    unread: true,
    updatedAt: new Date().toISOString(),
    messageCount: existing?.messageCount || 0,
    projectId: currentMessageProjectId(),
    pinned: Boolean(existing?.pinned),
    pinnedAt: existing?.pinnedAt || "",
  };
  state.runHistory = state.runHistory.filter((entry) => entry.runId !== runId);
  state.runHistory.unshift(item);
  state.runHistory = sortHistoryItems(state.runHistory).slice(0, 8);
  renderHistory();
}

function markHistoryFailed(question, message) {
  const runId = state.activeHistoryRunId || state.conversationId || `failed_${Date.now()}`;
  const existing = state.runHistory.find((entry) => entry.runId === runId);
  const item = {
    runId,
    success: false,
    answer: message,
    question,
    title: existing?.title || question || "未完成对话",
    mode: "failed",
    unread: true,
    updatedAt: new Date().toISOString(),
    messageCount: existing?.messageCount || 0,
    projectId: currentMessageProjectId(),
    pinned: Boolean(existing?.pinned),
    pinnedAt: existing?.pinnedAt || "",
  };
  state.runHistory = state.runHistory.filter((entry) => entry.runId !== runId);
  state.runHistory.unshift(item);
  state.runHistory = sortHistoryItems(state.runHistory).slice(0, 8);
  state.activeHistoryRunId = "";
  renderHistory();
}

function sortHistoryItems(items) {
  return [...items].sort((left, right) => {
    if (Boolean(left.pinned) !== Boolean(right.pinned)) {
      return left.pinned ? -1 : 1;
    }
    const leftTime = String(left.pinnedAt || left.updatedAt || "");
    const rightTime = String(right.pinnedAt || right.updatedAt || "");
    return rightTime.localeCompare(leftTime);
  });
}

function renderHistory() {
  el.historyCount.textContent = String(state.runHistory.length);
  if (!state.runHistory.length) {
    el.runHistory.innerHTML = `<li class="history-empty">上传数据并提问后，这里会显示最近的分析记录。</li>`;
    return;
  }
  el.runHistory.innerHTML = state.runHistory
    .map(
      (item) => {
        const title = item.title || item.question || "未命名对话";
        const stateClass = item.mode === "running" ? "running" : item.success === false ? "failed" : "complete";
        return `
        <li class="history-item ${escapeHtml(stateClass)}${item.runId === state.conversationId ? " active" : ""}${item.pinned ? " pinned" : ""}" data-run-id="${escapeHtml(item.runId || "")}">
          <div class="history-item-text">
            <div class="history-title-row">
              ${item.pinned ? `<span class="pin-indicator" title="已置顶">${pinIcon()}</span>` : ""}
              <strong class="history-title" title="${escapeHtml(title)}">${escapeHtml(title)}</strong>
            </div>
            <input class="history-rename-input hidden" type="text" maxlength="80" value="${escapeHtml(title)}" aria-label="重命名历史对话" />
          </div>
          <button class="history-menu-button" type="button" title="对话选项" aria-label="对话选项">
            ${ellipsisIcon()}
          </button>
        </li>
      `;
      },
    )
    .join("");
  el.runHistory.querySelectorAll(".history-menu-button").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      openHistoryMenu(button, button.closest(".history-item")?.dataset.runId || "");
    });
  });
  el.runHistory.querySelectorAll(".history-item").forEach((item) => {
    item.addEventListener("click", (event) => {
      if (event.target.closest("button, input")) return;
      acknowledgeHistoryItem(item.dataset.runId || "");
      loadConversation(item.dataset.runId || "");
    });
  });
  el.runHistory.querySelectorAll(".history-title").forEach((title) => {
    title.addEventListener("dblclick", () => startHistoryRename(title.closest(".history-item")?.dataset.runId || ""));
  });
  el.runHistory.querySelectorAll(".history-rename-input").forEach((input) => {
    input.addEventListener("keydown", handleHistoryRenameKeydown);
    input.addEventListener("blur", () => {
      if (input.dataset.cancelRename === "true") return;
      commitHistoryRename(input.closest(".history-item")?.dataset.runId || "", input.value);
    });
  });
}

function acknowledgeHistoryItem(runId) {
  const item = state.runHistory.find((entry) => entry.runId === runId);
  if (!item || item.mode === "running" || item.unread !== true) {
    return;
  }
  item.unread = false;
  renderHistory();
}

function startHistoryRename(runId) {
  const row = el.runHistory.querySelector(`[data-run-id="${cssEscape(runId)}"]`);
  if (!row) return;
  row.classList.add("editing");
  const input = row.querySelector(".history-rename-input");
  input?.classList.remove("hidden");
  input?.focus();
  input?.select();
}

function handleHistoryRenameKeydown(event) {
  const runId = event.currentTarget.closest(".history-item")?.dataset.runId || "";
  if (event.key === "Enter") {
    event.preventDefault();
    commitHistoryRename(runId, event.currentTarget.value);
  }
  if (event.key === "Escape") {
    event.preventDefault();
    event.currentTarget.dataset.cancelRename = "true";
    renderHistory();
  }
}

async function commitHistoryRename(runId, rawTitle) {
  const item = state.runHistory.find((entry) => entry.runId === runId);
  if (!item) return;
  const title = String(rawTitle || "").trim();
  if (title) {
    item.title = title;
  }
  renderHistory();
  if (!title || !runId.startsWith("conv_")) {
    return;
  }
  try {
    const response = await fetch(`/api/data-agent/conversations/${encodeURIComponent(runId)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title }),
    });
    const payload = await response.json();
    if (!response.ok || !payload.success) {
      throw new Error(errorText(payload) || `HTTP ${response.status}`);
    }
    const conversation = payload.conversation || {};
    item.title = conversation.title || title;
    item.updatedAt = conversation.updated_at || item.updatedAt;
    renderHistory();
  } catch (error) {
    setApiStatus("error", `重命名失败：${String(error.message || error)}`);
    loadConversations();
  }
}

async function renameConversationFromPrompt(runId) {
  if (!runId || !runId.startsWith("conv_")) return;
  const item = state.runHistory.find((entry) => entry.runId === runId)
    || state.projectConversations.find((entry) => entry.runId === runId);
  const rawTitle = window.prompt("对话名称", item?.title || item?.question || "未命名对话");
  const title = String(rawTitle || "").trim();
  if (!title) return;
  try {
    const response = await fetch(`/api/data-agent/conversations/${encodeURIComponent(runId)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title }),
    });
    const payload = await response.json();
    if (!response.ok || !payload.success) {
      throw new Error(errorText(payload) || `HTTP ${response.status}`);
    }
    const conversation = payload.conversation || {};
    updateConversationTitleState(runId, conversation.title || title, conversation.updated_at || "");
    await loadConversations();
    if (state.projectId) {
      await loadProjectWorkspace(state.projectId);
    }
    setApiStatus("ready", "对话已重命名");
  } catch (error) {
    setApiStatus("error", `重命名失败：${String(error.message || error)}`);
  }
}

function updateConversationTitleState(runId, title, updatedAt) {
  const apply = (item) => {
    item.title = title || item.title;
    item.updatedAt = updatedAt || item.updatedAt;
    return item;
  };
  state.runHistory = state.runHistory.map((item) => (item.runId === runId ? apply(item) : item));
  state.projectConversations = state.projectConversations.map((item) => (item.runId === runId ? apply(item) : item));
  renderHistory();
  renderProjectHome();
}

async function toggleHistoryPinned(runId, pinned) {
  if (!runId || !runId.startsWith("conv_")) return;
  const existing = state.runHistory.find((entry) => entry.runId === runId);
  if (existing) {
    existing.pinned = Boolean(pinned);
    existing.pinnedAt = pinned ? new Date().toISOString() : "";
    state.runHistory = sortHistoryItems(state.runHistory);
    renderHistory();
  }
  try {
    const response = await fetch(`/api/data-agent/conversations/${encodeURIComponent(runId)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ pinned: Boolean(pinned) }),
    });
    const payload = await response.json();
    if (!response.ok || !payload.success) {
      throw new Error(errorText(payload) || `HTTP ${response.status}`);
    }
    const conversation = payload.conversation || {};
    updateConversationPinState(runId, Boolean(conversation.pinned), conversation.pinned_at || "");
    await loadConversations();
    if (state.projectId) {
      await loadProjectWorkspace(state.projectId);
    }
    setApiStatus("ready", conversation.pinned ? "对话已置顶" : "对话已取消置顶");
  } catch (error) {
    setApiStatus("error", `置顶失败：${String(error.message || error)}`);
    await loadConversations();
    if (state.projectId) {
      await loadProjectWorkspace(state.projectId);
    }
  }
}

function updateConversationPinState(runId, pinned, pinnedAt) {
  const apply = (item) => {
    item.pinned = Boolean(pinned);
    item.pinnedAt = pinnedAt || "";
    return item;
  };
  state.runHistory = sortHistoryItems(state.runHistory.map((item) => (item.runId === runId ? apply(item) : item)));
  state.projectConversations = sortHistoryItems(state.projectConversations.map((item) => (item.runId === runId ? apply(item) : item)));
  renderHistory();
  renderProjectHome();
}

async function createProjectForHistory(runId) {
  if (!runId || !runId.startsWith("conv_")) return;
  try {
    const response = await fetch("/api/data-agent/projects", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: "新项目" }),
    });
    const payload = await response.json();
    if (!response.ok || !payload.success) {
      throw new Error(errorText(payload) || `HTTP ${response.status}`);
    }
    const projectId = payload.project?.project_id || "";
    await loadProjects();
    await assignHistoryToProject(runId, projectId);
  } catch (error) {
    setApiStatus("error", `Project 创建失败：${String(error.message || error)}`);
  }
}

async function assignHistoryToProject(runId, targetProjectId) {
  if (!runId || !runId.startsWith("conv_")) return;
  const safeProjectId = String(targetProjectId || "").trim();
  if (!safeProjectId) return;
  try {
    const response = await fetch(`/api/data-agent/conversations/${encodeURIComponent(runId)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ project_id: safeProjectId }),
    });
    const payload = await response.json();
    if (!response.ok || !payload.success) {
      throw new Error(errorText(payload) || `HTTP ${response.status}`);
    }
    const conversation = payload.conversation || {};
    const item = state.runHistory.find((entry) => entry.runId === runId);
    if (item) {
      item.projectId = conversation.project_id || safeProjectId;
      item.updatedAt = conversation.updated_at || item.updatedAt;
      item.pinned = Boolean(conversation.pinned);
      item.pinnedAt = conversation.pinned_at || item.pinnedAt || "";
    }
    const shouldRefreshProjectHome = state.projectId === (conversation.project_id || safeProjectId);
    if (shouldRefreshProjectHome) {
      await loadProjectWorkspace(conversation.project_id || safeProjectId);
    } else {
      await loadProjects();
    }
    await loadConversations();
    setApiStatus("ready", "对话已放入 Project");
  } catch (error) {
    setApiStatus("error", `加入 Project 失败：${String(error.message || error)}`);
  }
}

async function deleteHistoryConversation(runId) {
  if (!runId) return;
  const item = state.runHistory.find((entry) => entry.runId === runId);
  const projectItem = state.projectConversations.find((entry) => entry.runId === runId);
  const title = item?.title || item?.question || projectItem?.title || "未命名对话";
  if (!window.confirm(`删除对话「${title}」？`)) return;
  if (!runId.startsWith("conv_")) {
    state.runHistory = state.runHistory.filter((entry) => entry.runId !== runId);
    state.projectConversations = state.projectConversations.filter((entry) => entry.runId !== runId);
    renderHistory();
    renderProjectHome();
    return;
  }
  try {
    const response = await fetch(`/api/data-agent/conversations/${encodeURIComponent(runId)}`, {
      method: "DELETE",
    });
    const payload = await response.json();
    if (!response.ok || !payload.success) {
      throw new Error(errorText(payload) || `HTTP ${response.status}`);
    }
    state.runHistory = state.runHistory.filter((entry) => entry.runId !== runId);
    if (state.conversationId === runId) {
      resetConversation();
    }
    state.projectConversations = state.projectConversations.filter((entry) => entry.runId !== runId);
    await loadProjects();
    if (state.projectId) {
      await loadProjectWorkspace(state.projectId);
    }
    await loadConversations();
    setApiStatus("ready", "对话已删除");
  } catch (error) {
    setApiStatus("error", `对话删除失败：${String(error.message || error)}`);
  }
}

async function loadConversations() {
  try {
    const query = new URLSearchParams({ limit: "30" });
    const response = await fetch(`/api/data-agent/conversations?${query.toString()}`);
    const payload = await response.json();
    if (!response.ok || !payload.success) {
      throw new Error(errorText(payload) || `HTTP ${response.status}`);
    }
    const existingById = new Map(state.runHistory.map((item) => [item.runId, item]));
    const loadedHistory = (payload.conversations || []).map((item) => {
      const existing = existingById.get(item.conversation_id);
      return {
        runId: item.conversation_id,
        success: true,
        answer: item.last_message || "",
        question: item.last_message || "",
        title: item.title || "未命名对话",
        mode: item.last_answer_type === "chat" ? "chat" : "analysis",
        unread: existing?.unread === true,
        updatedAt: item.updated_at,
        pinned: Boolean(item.pinned),
        pinnedAt: item.pinned_at || "",
        messageCount: item.message_count || 0,
        datasetId: item.dataset_id || "",
        projectId: item.project_id || "",
      };
    });
    const loadedIds = new Set(loadedHistory.map((item) => item.runId));
    const localUnreadHistory = state.runHistory.filter((item) => item.unread === true && !loadedIds.has(item.runId));
    state.runHistory = sortHistoryItems([...localUnreadHistory, ...loadedHistory]).slice(0, 30);
    renderHistory();
  } catch {
    renderHistory();
  }
}

async function loadConversation(conversationId) {
  if (!conversationId || !conversationId.startsWith("conv_")) return;
  try {
    const response = await fetch(`/api/data-agent/conversations/${encodeURIComponent(conversationId)}`);
    const payload = await response.json();
    if (!response.ok || !payload.success) {
      throw new Error(errorText(payload) || `HTTP ${response.status}`);
    }
    await restoreConversation(payload.conversation || {});
    setApiStatus("ready", "历史已载入");
  } catch (error) {
    setApiStatus("error", `历史载入失败：${String(error.message || error)}`);
  }
}

async function restoreConversation(conversation) {
  state.conversationId = conversation.conversation_id || "";
  state.projectId = conversation.project_id || "";
  state.projectDetails = null;
  state.projectConversations = [];
  state.projectDraftActive = false;
  state.datasetId = conversation.dataset_id || "";
  state.profile = null;
  state.selectedTable = "";
  state.fileRecords = [];
  state.hasPendingUpload = false;
  state.activeHistoryRunId = "";
  state.userRuleFileId = "";
  state.autoRuleFileIds = [];
  state.hasPendingRuleUpload = false;
  state.benchmarkRuleFileId = "";
  state.hasPendingBenchmarkRuleUpload = false;
  el.fileInput.value = "";
  clearRestoredFileRecords();
  [...el.chatMessages.querySelectorAll(".user-message, .assistant-result-message")].forEach((message) => message.remove());
  bindResultMessage(el.resultTemplate);
  el.resultMessage.classList.add("hidden");
  el.projectHome?.classList.add("hidden");
  const messages = conversation.messages || [];
  if (state.projectId) {
    await loadProjectWorkspace(state.projectId);
  }
  renderProjects();
  el.welcomeMessage?.classList.toggle("hidden", Boolean(messages.length) || Boolean(state.projectId));
  for (const message of messages) {
    if (message.role === "user") {
      appendUserMessage(message.content || "");
    } else if (message.payload) {
      const assistantMessage = createAssistantResultMessage();
      bindResultMessage(assistantMessage);
      el.chatMessages.append(el.resultMessage);
      renderResult(message.payload, { updateHistory: false });
    }
  }
  if (state.datasetId) {
    await restoreDatasetProfile(state.datasetId);
  } else {
    renderProfile();
    el.datasetChip.textContent = "未上传数据";
    el.datasetStatus.textContent = "等待上传数据集";
  }
  renderHistory();
  renderProjectHome();
  scrollToLatest();
}

async function restoreDatasetProfile(datasetId) {
  try {
    const response = await fetch(`/api/data-agent/datasets/${encodeURIComponent(datasetId)}/profile`);
    const profile = await response.json();
    if (!response.ok || !profile.success) {
      throw new Error(errorText(profile) || `HTTP ${response.status}`);
    }
    state.profile = profile;
    state.datasetId = profile.dataset_id || datasetId;
    state.autoRuleFileIds = profile.auto_bound_user_rule_file_ids || [];
    state.userRuleFileId = state.autoRuleFileIds[0] || "";
    state.selectedTable = profile.tables?.[0]?.table_name || "";
    renderProfile();
    applyRestoredFileRecords(profile);
    setApiStatus("ready", "数据集已就绪");
  } catch {
    state.profile = null;
    clearRestoredFileRecords();
    renderProfile();
    el.datasetChip.textContent = state.datasetId ? "数据记录已关联" : "未上传数据";
    el.datasetStatus.textContent = state.datasetId ? `${state.datasetId} / 需重新上传后继续分析` : "等待上传数据集";
  }
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
  if (state.projectId) {
    state.projectDraftActive = true;
    updateShellMode(false);
  }
  el.welcomeMessage?.classList.add("hidden");
  el.projectHome?.classList.add("hidden");
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
  state.conversationId = "";
  state.profile = null;
  state.selectedTable = "";
  state.fileRecords = [];
  state.hasPendingUpload = false;
  state.ruleModeEnabled = false;
  state.hasPendingRuleUpload = false;
  state.userRuleFileId = "";
  state.benchmarkRuleFileId = "";
  state.hasPendingBenchmarkRuleUpload = false;
  state.activeResultMessage = null;
  state.activeHistoryRunId = "";
  el.fileInput.value = "";
  if (el.ruleModeToggle) el.ruleModeToggle.checked = false;
  if (el.ruleFileInput) el.ruleFileInput.value = "";
  if (el.benchmarkRuleInput) el.benchmarkRuleInput.value = "";
  if (el.ruleFileStatus) el.ruleFileStatus.textContent = "未上传用户分析规则";
  if (el.benchmarkStatus) el.benchmarkStatus.textContent = "内部 Benchmark 入口";
  el.ruleUploadPanel?.classList.add("hidden");
  [...el.chatMessages.querySelectorAll(".user-message, .assistant-result-message")].forEach((message) => message.remove());
  bindResultMessage(el.resultTemplate);
  el.welcomeMessage?.classList.toggle("hidden", Boolean(state.projectId));
  el.profileMessage.classList.add("hidden");
  el.resultMessage.classList.add("hidden");
  updateFileSummary();
  renderProfile();
  clearResult();
  setApiStatus("idle", "准备就绪");
  el.datasetChip.textContent = "未上传数据";
  el.datasetStatus.textContent = "等待上传数据集";
  setQuestionText("");
  updateRunButton();
  renderProjectHome();
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
  el.artifactPanel = message.querySelector(".artifact-panel");
  el.artifactList = message.querySelector(".artifact-list");
}

function startMonitorRun(question) {
  state.activeMonitorRunId = `mon_${Date.now()}_${Math.random().toString(16).slice(2, 10)}`;
  const record = {
    monitor_run_id: state.activeMonitorRunId,
    question,
    dataset_id: state.datasetId,
    conversation_id: state.conversationId,
    execution_mode: el.executionMode.value,
    agent_mode: el.agentMode.value,
    status: "running",
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  };
  try {
    window.localStorage.setItem(ACTIVE_MONITOR_RUN_KEY, JSON.stringify(record));
    upsertMonitorRunRecord(record);
  } catch {
    // Local storage is optional; backend monitor events remain authoritative.
  }
  return state.activeMonitorRunId;
}

function finishMonitorRun(result, question) {
  if (!state.activeMonitorRunId) return;
  upsertMonitorRunRecord({
    monitor_run_id: state.activeMonitorRunId,
    question,
    dataset_id: result.dataset_id || state.datasetId,
    conversation_id: result.conversation_id || state.conversationId,
    conversation_title: result.conversation?.title || "",
    answer: result.answer || "",
    answer_type: result.answer_type || "",
    status: result.success === false ? "failed" : "completed",
    updated_at: new Date().toISOString(),
  });
}

function failMonitorRun(question, errorMessage) {
  if (!state.activeMonitorRunId) return;
  upsertMonitorRunRecord({
    monitor_run_id: state.activeMonitorRunId,
    question,
    dataset_id: state.datasetId,
    conversation_id: state.conversationId,
    status: "failed",
    error: errorMessage,
    updated_at: new Date().toISOString(),
  });
}

function upsertMonitorRunRecord(record) {
  try {
    const existing = JSON.parse(window.localStorage.getItem(MONITOR_RUN_INDEX_KEY) || "[]");
    const records = Array.isArray(existing) ? existing : [];
    const index = records.findIndex((item) => item?.monitor_run_id === record.monitor_run_id);
    const nextRecord = {
      ...(index >= 0 ? records[index] : {}),
      ...record,
      created_at: record.created_at || (index >= 0 ? records[index].created_at : new Date().toISOString()),
    };
    if (index >= 0) {
      records[index] = nextRecord;
    } else {
      records.unshift(nextRecord);
    }
    records.sort((a, b) => String(b.updated_at || b.created_at || "").localeCompare(String(a.updated_at || a.created_at || "")));
    window.localStorage.setItem(MONITOR_RUN_INDEX_KEY, JSON.stringify(records.slice(0, MAX_MONITOR_RUN_RECORDS)));
    window.localStorage.setItem(ACTIVE_MONITOR_RUN_KEY, JSON.stringify(nextRecord));
  } catch {
    // Local storage is optional; monitoring still works through SSE.
  }
}

function setApiStatus(status, text) {
  el.apiStatus.className = `status-pill ${status}`;
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

function formatFileSize(value) {
  const size = Number(value);
  if (!Number.isFinite(size) || size <= 0) return "";
  if (size >= 1024 * 1024) return `${(size / 1024 / 1024).toFixed(size >= 10 * 1024 * 1024 ? 0 : 1)} MB`;
  if (size >= 1024) return `${Math.round(size / 1024)} KB`;
  return `${size} B`;
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

function cssEscape(value) {
  if (window.CSS?.escape) return window.CSS.escape(value);
  return String(value).replace(/["\\]/g, "\\$&");
}
