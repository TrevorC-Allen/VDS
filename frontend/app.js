const MONITOR_RUN_INDEX_KEY = "vds-monitor-runs";
const ACTIVE_MONITOR_RUN_KEY = "vds-active-monitor-run";
const PROJECT_PANEL_COLLAPSED_KEY = "vds-project-panel-collapsed";
const MAX_MONITOR_RUN_RECORDS = 80;
const ACTIVITY_EVENT_TYPES = [
  "monitor_connected",
  "message_requested",
  "analysis_requested",
  "workflow_started",
  "agent_started",
  "agent_completed",
  "agent_failed",
  "correction_rerun_started",
  "activity_trace_delta",
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
  projectPanelCollapsed: false,
  profile: null,
  selectedTable: "",
  fileRecords: [],
  runHistory: [],
  progressTimer: null,
  thinkingElapsedTimer: null,
  progressStep: 0,
  thinkingStartedAt: 0,
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
  liveActivityTrace: [],
  latestActivityResult: null,
  drawerResult: null,
  drawerTriggerSummary: null,
  textDialogResolve: null,
  chatSearchQuery: "",
};

const el = {
  chatMessages: document.querySelector("#chat-messages"),
  welcomeMessage: document.querySelector(".welcome-message"),
  profileMessage: document.querySelector("#profile-message"),
  resultTemplate: document.querySelector("#result-message"),
  resultMessage: document.querySelector("#result-message"),
  newChatButton: document.querySelector("#new-chat-button"),
  chatSearchButton: document.querySelector("#chat-search-button"),
  chatSearchDialog: document.querySelector("#chat-search-dialog"),
  chatSearchInput: document.querySelector("#chat-search-input"),
  chatSearchCloseButton: document.querySelector("#chat-search-close-button"),
  chatSearchResults: document.querySelector("#chat-search-results"),
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
  activityBackdrop: document.querySelector("#activity-backdrop"),
  activityDrawer: document.querySelector("#activity-drawer"),
  activityDrawerClose: document.querySelector("#activity-drawer-close"),
  activityDrawerTitle: document.querySelector("#activity-drawer-title"),
  activityDrawerSummary: document.querySelector("#activity-drawer-summary"),
  activityDrawerList: document.querySelector("#activity-drawer-list"),
  artifactPanel: document.querySelector(".artifact-panel"),
  artifactList: document.querySelector(".artifact-list"),
  sourcePanel: document.querySelector(".answer-source-panel"),
  sourceList: document.querySelector(".answer-source-list"),
  runHistory: document.querySelector("#run-history"),
  historyCount: document.querySelector("#history-count"),
  projectPanel: document.querySelector(".project-panel"),
  projectCollapseButton: document.querySelector("#project-collapse-button"),
  projectSectionBody: document.querySelector("#project-section-body"),
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
  projectSourceUploadInput: document.querySelector("#project-source-upload-input"),
  projectSourceUploadDropzone: document.querySelector("#project-source-upload-dropzone"),
  projectSourceUploadStatus: document.querySelector("#project-source-upload-status"),
  contextMenu: document.querySelector("#context-menu"),
  textDialog: document.querySelector("#text-dialog"),
  textDialogForm: document.querySelector("#text-dialog .text-dialog-card"),
  textDialogTitle: document.querySelector("#text-dialog-title"),
  textDialogLabel: document.querySelector("#text-dialog-label"),
  textDialogInput: document.querySelector("#text-dialog-input"),
  textDialogCancel: document.querySelector("#text-dialog-cancel"),
  textDialogConfirm: document.querySelector("#text-dialog-confirm"),
};

el.fileInput.addEventListener("change", updateFileSummary);
el.fileSummary.addEventListener("click", toggleFilePanel);
document.addEventListener("click", closeFilePanelFromOutside);
document.addEventListener("click", closeContextMenuFromOutside);
document.addEventListener("keydown", handleGlobalKeydown);
window.addEventListener("resize", closeContextMenu);
window.addEventListener("scroll", closeContextMenu, true);
el.activityBackdrop?.addEventListener("click", closeActivityDrawer);
el.activityDrawerClose?.addEventListener("click", closeActivityDrawer);
el.ruleModeToggle?.addEventListener("change", updateRuleMode);
el.ruleFileInput?.addEventListener("change", updateRuleFileSummary);
el.ruleUploadButton?.addEventListener("click", uploadUserRule);
el.benchmarkRuleInput?.addEventListener("change", updateBenchmarkRuleSummary);
el.benchmarkRuleUploadButton?.addEventListener("click", uploadBenchmarkRule);
el.benchmarkRunButton?.addEventListener("click", runBenchmark);
el.newChatButton.addEventListener("click", startGlobalConversation);
el.chatSearchButton?.addEventListener("click", openChatSearch);
el.chatSearchCloseButton?.addEventListener("click", closeChatSearch);
el.chatSearchInput?.addEventListener("input", handleChatSearchInput);
el.chatSearchInput?.addEventListener("keydown", handleChatSearchKeydown);
el.chatSearchDialog?.addEventListener("click", (event) => {
  if (event.target === el.chatSearchDialog) closeChatSearch();
});
el.projectCollapseButton?.addEventListener("click", toggleProjectPanelCollapsed);
el.newProjectButton?.addEventListener("click", createProjectFromPrompt);
el.textDialogForm?.addEventListener("submit", submitTextDialog);
el.textDialogCancel?.addEventListener("click", () => closeTextDialog(null));
el.textDialog?.addEventListener("click", (event) => {
  if (event.target === el.textDialog) closeTextDialog(null);
});
el.textDialogInput?.addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    event.preventDefault();
    closeTextDialog(null);
  }
});
el.chatMessages?.addEventListener("click", handleThinkingSummaryClick);
el.chatMessages?.addEventListener("keydown", handleThinkingSummaryKeydown);
el.projectNewChatButton?.addEventListener("click", startProjectConversation);
el.projectTabChats?.addEventListener("click", () => setProjectTab("chats"));
el.projectTabSources?.addEventListener("click", () => setProjectTab("sources"));
el.projectSourceUploadInput?.addEventListener("change", () => uploadProjectSourceFiles([...el.projectSourceUploadInput.files]));
el.projectSourceUploadDropzone?.addEventListener("click", () => el.projectSourceUploadInput?.click());
el.projectSourceUploadDropzone?.addEventListener("keydown", handleProjectSourceUploadKeydown);
el.projectSourceUploadDropzone?.addEventListener("dragenter", handleProjectSourceDragEnter);
el.projectSourceUploadDropzone?.addEventListener("dragover", handleProjectSourceDragEnter);
el.projectSourceUploadDropzone?.addEventListener("dragleave", handleProjectSourceDragLeave);
el.projectSourceUploadDropzone?.addEventListener("drop", handleProjectSourceDrop);
el.uploadButton.addEventListener("click", uploadFiles);
el.runButton.addEventListener("click", runAnalysis);
el.questionInput.addEventListener("input", handleQuestionInput);
el.questionInput.addEventListener("paste", handleQuestionPaste);
el.questionInput.addEventListener("focus", updateQuestionEmptyState);
el.questionInput.addEventListener("keydown", handleQuestionKeydown);

updateFileSummary();
updateQuestionEmptyState();
loadProjectPanelCollapsed();
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

function handleGlobalKeydown(event) {
  if (event.key === "Escape" && isChatSearchOpen()) {
    event.preventDefault();
    closeChatSearch();
    return;
  }
  if (event.key === "Escape" && !el.activityDrawer?.classList.contains("hidden")) {
    event.preventDefault();
    closeActivityDrawer();
  }
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
    const hasSourceOnlyProfile = hasDatasetProfile && (profile.dataset_kind === "uploaded_sources" || (profile.source_file_count && !(profile.tables || []).length));
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
        ? hasSourceOnlyProfile
          ? "来源文件已就绪"
          : state.autoRuleFileIds.length
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

function handleProjectSourceUploadKeydown(event) {
  if (event.key !== "Enter" && event.key !== " ") return;
  event.preventDefault();
  el.projectSourceUploadInput?.click();
}

function handleProjectSourceDragEnter(event) {
  if (!state.projectId) return;
  event.preventDefault();
  el.projectSourceUploadDropzone?.classList.add("drag-over");
}

function handleProjectSourceDragLeave(event) {
  event.preventDefault();
  const relatedTarget = event.relatedTarget;
  if (relatedTarget instanceof Node && event.currentTarget?.contains(relatedTarget)) return;
  el.projectSourceUploadDropzone?.classList.remove("drag-over");
}

function handleProjectSourceDrop(event) {
  event.preventDefault();
  el.projectSourceUploadDropzone?.classList.remove("drag-over");
  uploadProjectSourceFiles([...(event.dataTransfer?.files || [])]);
}

function setProjectSourceUploadStatus(message, stateName = "idle") {
  if (!el.projectSourceUploadStatus) return;
  el.projectSourceUploadStatus.textContent = message;
  el.projectSourceUploadStatus.classList.toggle("hidden", !message);
  el.projectSourceUploadStatus.classList.toggle("ready", stateName === "ready");
  el.projectSourceUploadStatus.classList.toggle("error", stateName === "error");
}

function setProjectSourceUploadBusy(isBusy) {
  el.projectSourceUploadDropzone?.classList.toggle("uploading", isBusy);
  el.projectSourceUploadDropzone?.toggleAttribute("disabled", isBusy);
  el.projectSourceUploadDropzone?.setAttribute("aria-busy", String(isBusy));
}

async function uploadProjectSourceFiles(files) {
  const selectedFiles = files.filter(Boolean);
  if (!selectedFiles.length) return null;
  if (!state.projectId) {
    setProjectSourceUploadStatus("请先打开一个 Project。", "error");
    setApiStatus("error", "请先打开 Project");
    return null;
  }
  state.isUploading = true;
  setProjectSourceUploadBusy(true);
  setProjectSourceUploadStatus(`正在上传 ${selectedFiles.length} 个来源。`);
  setApiStatus("idle", "添加来源中");
  updateRunButton();
  try {
    const payload = new FormData();
    selectedFiles.forEach((file) => payload.append("files", file));
    const endpoint = `/api/data-agent/projects/${encodeURIComponent(state.projectId)}/sources/upload`;
    const response = await fetch(endpoint, { method: "POST", body: payload });
    const result = await response.json();
    if (!response.ok || !result.success) {
      throw new Error(errorText(result) || `HTTP ${response.status}`);
    }
    if (result.dataset_id) {
      state.profile = result;
      state.datasetId = result.dataset_id;
      state.autoRuleFileIds = result.auto_bound_user_rule_file_ids || [];
      state.userRuleFileId = state.autoRuleFileIds[0] || state.userRuleFileId || "";
      state.selectedTable = result.tables?.[0]?.table_name || "";
      renderProfile();
    }
    await loadProjects();
    await loadProjectWorkspace(state.projectId);
    setProjectSourceUploadStatus(`${selectedFiles.length} 个来源已添加。`, "ready");
    setApiStatus("ready", result.dataset_id ? "项目数据源已添加" : "项目来源已添加");
    return result;
  } catch (error) {
    setProjectSourceUploadStatus(`来源上传失败：${String(error.message || error)}`, "error");
    setApiStatus("error", "来源上传失败");
    return null;
  } finally {
    state.isUploading = false;
    setProjectSourceUploadBusy(false);
    if (el.projectSourceUploadInput) el.projectSourceUploadInput.value = "";
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
  const submittedAt = new Date().toISOString();
  const thinkingStartedAt = performance.now();
  const monitorRunId = startMonitorRun(question);
  state.liveActivityTrace = [];
  state.latestActivityResult = null;
  state.drawerResult = null;
  const liveActivity = Boolean(window.EventSource && monitorRunId);
  const messageProjectId = currentMessageProjectId();
  markHistoryRunning(question, monitorRunId, messageProjectId);
  appendUserMessage(question, { createdAt: submittedAt });
  setQuestionText("");
  renderProgress(question, { liveActivity, startedAtMs: thinkingStartedAt, createdAt: submittedAt });
  if (liveActivity) connectActivityStream(monitorRunId);
  setApiStatus("idle", "处理中");
  try {
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
    const fallbackElapsedMs = Math.round(performance.now() - thinkingStartedAt);
    renderResult(result, { thinkingElapsedMs: resolveThinkingElapsedMs(result, fallbackElapsedMs) });
    finishMonitorRun(result, question);
    const isChat = result.answer_type === "chat" || result.debug?.agent_mode === "chat_without_dataset" || result.debug?.agent_mode === "chat_with_dataset";
    setApiStatus(result.success ? "ready" : "error", result.success ? (isChat ? "已回复" : "分析完成") : "需要继续确认");
    if (state.projectId) {
      await loadProjects();
      await loadProjectWorkspace(state.projectId);
    }
    await loadConversations();
  } catch (error) {
    const fallbackElapsedMs = Math.round(performance.now() - thinkingStartedAt);
    stopProgress();
    closeActivityStream();
    failMonitorRun(question, String(error.message || error));
    markHistoryFailed(question, String(error.message || error), messageProjectId);
    setApiStatus("error", "分析失败");
    renderUserFacingError("分析失败", String(error.message || error), { thinkingElapsedMs: fallbackElapsedMs });
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
  if (project?.sources?.length) {
    return buildProjectSourceRows(project.sources).filter((row) => row.kind !== "dataset-group").length;
  }
  return Number(project?.source_count ?? project?.sources?.length ?? 0);
}

function projectMemoryCount(project) {
  return Number(project?.memory_count ?? project?.memories?.length ?? 0);
}

function loadProjectPanelCollapsed() {
  try {
    state.projectPanelCollapsed = window.localStorage.getItem(PROJECT_PANEL_COLLAPSED_KEY) === "true";
  } catch {
    state.projectPanelCollapsed = false;
  }
  renderProjectPanelCollapsed();
}

function toggleProjectPanelCollapsed() {
  state.projectPanelCollapsed = !state.projectPanelCollapsed;
  try {
    window.localStorage.setItem(PROJECT_PANEL_COLLAPSED_KEY, String(state.projectPanelCollapsed));
  } catch {
    // UI preference only; ignore storage failures.
  }
  renderProjectPanelCollapsed();
}

function renderProjectPanelCollapsed() {
  el.projectPanel?.classList.toggle("collapsed", state.projectPanelCollapsed);
  el.projectSectionBody?.classList.toggle("hidden", state.projectPanelCollapsed);
  el.projectCollapseButton?.setAttribute("aria-expanded", String(!state.projectPanelCollapsed));
}

function openTextDialog({ title, label, value = "", confirmText = "确认" }) {
  if (!el.textDialog || !el.textDialogInput) return Promise.resolve(null);
  closeContextMenu();
  if (state.textDialogResolve) {
    state.textDialogResolve(null);
  }
  if (el.textDialogTitle) el.textDialogTitle.textContent = title || "名称";
  if (el.textDialogLabel) el.textDialogLabel.textContent = label || title || "名称";
  if (el.textDialogConfirm) el.textDialogConfirm.textContent = confirmText;
  el.textDialogInput.value = value || "";
  el.textDialog.classList.remove("hidden");
  document.body.classList.add("dialog-open");
  requestAnimationFrame(() => {
    el.textDialogInput.focus();
    el.textDialogInput.select();
  });
  return new Promise((resolve) => {
    state.textDialogResolve = resolve;
  });
}

function submitTextDialog(event) {
  event.preventDefault();
  closeTextDialog(el.textDialogInput?.value || "");
}

function closeTextDialog(value) {
  if (!el.textDialog) return;
  const resolve = state.textDialogResolve;
  state.textDialogResolve = null;
  el.textDialog.classList.add("hidden");
  document.body.classList.remove("dialog-open");
  resolve?.(value);
}

function isChatSearchOpen() {
  return Boolean(el.chatSearchDialog && !el.chatSearchDialog.classList.contains("hidden"));
}

function openChatSearch() {
  if (!el.chatSearchDialog || !el.chatSearchInput) return;
  closeContextMenu();
  closeTextDialog(null);
  closeActivityDrawer();
  state.chatSearchQuery = "";
  el.chatSearchInput.value = "";
  renderChatSearchResults();
  el.chatSearchDialog.classList.remove("hidden");
  document.body.classList.add("dialog-open");
  requestAnimationFrame(() => {
    el.chatSearchInput?.focus();
  });
  refreshChatSearchConversations();
}

function closeChatSearch() {
  if (!el.chatSearchDialog) return;
  el.chatSearchDialog.classList.add("hidden");
  document.body.classList.remove("dialog-open");
  state.chatSearchQuery = "";
  if (el.chatSearchInput) el.chatSearchInput.value = "";
}

async function refreshChatSearchConversations() {
  await loadConversations();
  if (state.projectId) {
    await loadProjectWorkspace(state.projectId);
  }
  if (isChatSearchOpen()) {
    renderChatSearchResults();
  }
}

function handleChatSearchInput(event) {
  state.chatSearchQuery = event.currentTarget.value || "";
  renderChatSearchResults();
}

function handleChatSearchKeydown(event) {
  if (event.key === "Escape") {
    event.preventDefault();
    closeChatSearch();
    return;
  }
  if (event.key === "Enter" && !event.isComposing) {
    const firstResult = el.chatSearchResults?.querySelector(".chat-search-result");
    if (!firstResult) return;
    event.preventDefault();
    openChatSearchConversation(firstResult.dataset.runId || "");
  }
}

function renderChatSearchResults() {
  if (!el.chatSearchResults) return;
  const items = getChatSearchItems();
  const query = normalizeSearchText(state.chatSearchQuery);
  const filteredItems = query ? items.filter((item) => chatSearchMatches(item, query)) : items;
  const content = [
    `
      <button id="chat-search-new-chat" class="chat-search-new-chat" type="button">
        ${editIcon()}
        <span>新聊天</span>
      </button>
    `,
  ];
  if (!filteredItems.length) {
    content.push(`<div class="chat-search-empty">${query ? "没有匹配的聊天" : "暂无聊天"}</div>`);
  } else {
    let currentGroup = "";
    filteredItems.forEach((item) => {
      const group = chatSearchGroupLabel(item.updatedAt);
      if (group !== currentGroup) {
        currentGroup = group;
        content.push(`<div class="chat-search-section-label">${escapeHtml(group)}</div>`);
      }
      const title = item.title || item.question || "未命名对话";
      content.push(`
        <button class="chat-search-result${item.runId === state.conversationId ? " active" : ""}" type="button" data-run-id="${escapeHtml(item.runId || "")}">
          <span class="chat-search-result-icon" aria-hidden="true">${chatBubbleIcon()}</span>
          <span class="chat-search-result-title">${escapeHtml(title)}</span>
        </button>
      `);
    });
  }
  el.chatSearchResults.innerHTML = content.join("");
  el.chatSearchResults.querySelector("#chat-search-new-chat")?.addEventListener("click", startChatFromSearch);
  el.chatSearchResults.querySelectorAll(".chat-search-result").forEach((button) => {
    button.addEventListener("click", () => openChatSearchConversation(button.dataset.runId || ""));
  });
}

function getChatSearchItems() {
  const byId = new Map();
  [...(state.runHistory || []), ...(state.projectConversations || [])].forEach((item) => {
    if (!item?.runId || !item.runId.startsWith("conv_")) return;
    byId.set(item.runId, { ...item });
  });
  return sortHistoryItems([...byId.values()]);
}

function chatSearchMatches(item, query) {
  const searchable = [
    item.title,
    item.question,
    item.answer,
    item.projectId ? projectNameById(item.projectId) : "",
  ]
    .map(normalizeSearchText)
    .join(" ");
  return query
    .split(/\s+/)
    .filter(Boolean)
    .every((part) => searchable.includes(part));
}

function normalizeSearchText(value) {
  return String(value || "").trim().toLocaleLowerCase("zh-CN");
}

function projectNameById(projectId) {
  return state.projects.find((project) => project.project_id === projectId)?.name || "";
}

function chatSearchGroupLabel(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "较早";
  const today = new Date();
  const todayStart = new Date(today.getFullYear(), today.getMonth(), today.getDate()).getTime();
  const dateStart = new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime();
  const dayDelta = Math.round((todayStart - dateStart) / 86400000);
  if (dayDelta === 0) return "今天";
  if (dayDelta === 1) return "昨天";
  return date.getFullYear() === today.getFullYear()
    ? `${date.getMonth() + 1}月${date.getDate()}日`
    : `${date.getFullYear()}年${date.getMonth() + 1}月${date.getDate()}日`;
}

function startChatFromSearch() {
  closeChatSearch();
  if (state.projectId) {
    startProjectConversation();
    return;
  }
  startGlobalConversation();
}

function openChatSearchConversation(runId) {
  if (!runId) return;
  closeChatSearch();
  acknowledgeHistoryItem(runId);
  loadConversation(runId);
}

function chatBubbleIcon() {
  return `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M21 11.5a8.4 8.4 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.4 8.4 0 0 1-3.8-.9L3 21l1.9-5.7A8.4 8.4 0 0 1 4 11.5a8.5 8.5 0 0 1 17 0Z"></path></svg>`;
}

async function createProjectFromPrompt() {
  const rawName = await openTextDialog({
    title: "新项目",
    label: "项目名称",
    value: "新项目",
    confirmText: "创建",
  });
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
  const rawName = await openTextDialog({
    title: "重命名项目",
    label: "项目名称",
    value: current.name || "未命名 Project",
    confirmText: "保存",
  });
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
    if (isChatSearchOpen()) renderChatSearchResults();
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
  if (isChatSearchOpen()) renderChatSearchResults();
}

function renderProjectSourceList() {
  const project = state.projectDetails || {};
  const sourceRows = buildProjectSourceRows(project.sources || []);
  renderProjectSourceRows(el.projectSourceList, sourceRows, "上传共享文件后会显示在这里。");
  renderProjectMemoryRows(el.projectMemoryList, project.memories || [], "保存的 Project memory 会显示在这里。", deleteProjectMemory);
}

function renderProjectSourceRows(listEl, records, emptyText) {
  if (!listEl) return;
  if (!records.length) {
    listEl.innerHTML = `<li class="project-home-empty">${escapeHtml(emptyText)}</li>`;
    return;
  }
  listEl.innerHTML = records
    .map((row) => {
      const itemClass = row.kind === "dataset-group" ? " dataset-group" : row.kind === "file" ? " file-source" : "";
      const actionButton = row.sourceId
        ? `<button class="project-source-menu-button" type="button" title="来源选项" aria-label="来源选项">${ellipsisIcon()}</button>`
        : "";
      return `
        <li class="project-source-item${itemClass}" data-source-id="${escapeHtml(row.sourceId || "")}">
          <span class="project-source-row-icon ${escapeHtml(row.iconClass || "")}" aria-hidden="true">${row.icon || fileSourceIcon()}</span>
          <div class="project-source-main">
            <strong title="${escapeHtml(row.title)}">${escapeHtml(row.title)}</strong>
            <span>${escapeHtml(row.meta || "")}</span>
          </div>
          ${actionButton}
        </li>
      `;
    })
    .join("");
  listEl.querySelectorAll(".project-source-menu-button").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      openProjectSourceMenu(button, button.closest(".project-source-item")?.dataset.sourceId || "");
    });
  });
}

function renderProjectMemoryRows(listEl, records, emptyText, deleteHandler) {
  if (!listEl) return;
  if (!records.length) {
    listEl.innerHTML = `<li class="project-home-empty">${escapeHtml(emptyText)}</li>`;
    return;
  }
  listEl.innerHTML = records
    .map((record) => {
      const id = record.memory_id || "";
      const title = record.title || sourceTypeLabel(record.memory_type || "source");
      const meta = projectSourceMeta(record);
      return `
        <li class="project-source-item memory-source" data-record-id="${escapeHtml(id)}">
          <span class="project-source-row-icon note" aria-hidden="true">${noteSourceIcon()}</span>
          <div class="project-source-main">
            <strong>${escapeHtml(title)}</strong>
            <span>${escapeHtml(meta)}</span>
          </div>
          <button class="project-source-delete-button" type="button" title="删除" aria-label="删除">${trashIcon()}</button>
        </li>
      `;
    })
    .join("");
  listEl.querySelectorAll(".project-source-delete-button").forEach((button) => {
    button.addEventListener("click", () => deleteHandler(button.closest(".project-source-item")?.dataset.recordId || ""));
  });
}

function buildProjectSourceRows(records) {
  const rows = [];
  records.forEach((record) => {
    const sourceId = record.source_id || "";
    const type = record.source_type || "source";
    if (type === "dataset") {
      const fileNames = projectSourceFileNames(record);
      rows.push({
        kind: "dataset-group",
        sourceId,
        title: projectDatasetTitle(record),
        meta: formatSourceDate(record.created_at),
        icon: folderIcon(),
        iconClass: "folder",
      });
      fileNames.forEach((name) => {
        rows.push({
          kind: "file",
          sourceId: "",
          title: name,
          meta: "文件内容可能无法访问",
          icon: sourceFileIcon(name),
          iconClass: sourceFileIconClass(name),
        });
      });
      return;
    }
    rows.push({
      kind: type,
      sourceId,
      title: record.title || sourceTypeLabel(type),
      meta: projectSourceMeta(record),
      icon: type === "note" ? noteSourceIcon() : fileSourceIcon(),
      iconClass: type === "note" ? "note" : "file",
    });
  });
  return rows;
}

function projectSourceFileNames(record) {
  const names = [];
  (record.metadata?.tables || []).forEach((table) => {
    const name = String(table.source_file || table.file_name || table.table_name || "").trim();
    if (name && !names.includes(name)) names.push(name);
  });
  if (!names.length && record.title?.includes(":")) {
    record.title
      .split(":")
      .slice(1)
      .join(":")
      .split(",")
      .map((name) => name.trim())
      .filter(Boolean)
      .forEach((name) => {
        if (!names.includes(name)) names.push(name);
      });
  }
  if (!names.length && record.title) names.push(record.title);
  return names;
}

function projectDatasetTitle(record) {
  const rawTitle = String(record.title || "").trim();
  if (!rawTitle) return "上传的数据源";
  return rawTitle.includes(":") ? rawTitle.split(":")[0].trim() || "上传的数据源" : rawTitle;
}

function formatSourceDate(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return `${date.getFullYear()}年${date.getMonth() + 1}月${date.getDate()}日`;
}

function openProjectSourceMenu(anchor, sourceId) {
  if (!sourceId) return;
  showContextMenu(anchor, [
    {
      label: "删除",
      className: "project-source-delete-button danger",
      icon: trashIcon(),
      action: () => deleteProjectSource(sourceId),
    },
  ]);
}

function sourceFileIconClass(fileName) {
  const ext = String(fileName || "").split(".").pop()?.toLowerCase() || "";
  if (["csv", "xlsx", "xls", "parquet", "arrow", "feather"].includes(ext)) return "spreadsheet";
  if (["md", "txt", "yaml", "yml"].includes(ext)) return "note";
  return "file";
}

function sourceFileIcon(fileName) {
  const iconClass = sourceFileIconClass(fileName);
  if (iconClass === "spreadsheet") return spreadsheetSourceIcon();
  if (iconClass === "note") return noteSourceIcon();
  return fileSourceIcon();
}

function spreadsheetSourceIcon() {
  return `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 5h12a1 1 0 0 1 1 1v12a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1Z"></path><path d="M5 10h14M10 5v14"></path></svg>`;
}

function noteSourceIcon() {
  return `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7 3h7l5 5v13H7z"></path><path d="M14 3v5h5"></path><path d="M9 13h6M9 17h6"></path></svg>`;
}

function fileSourceIcon() {
  return `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7 3h7l5 5v13H7z"></path><path d="M14 3v5h5"></path></svg>`;
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

function formatMessageTime(value) {
  const date = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  const now = new Date();
  const datePart =
    date.getFullYear() === now.getFullYear()
      ? `${date.getMonth() + 1}月${date.getDate()}日`
      : `${date.getFullYear()}年${date.getMonth() + 1}月${date.getDate()}日`;
  return `${datePart}，${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}`;
}

function setMessageTime(message, value) {
  const node = message?.querySelector(".message-meta");
  if (!node) return;
  const label = value ? formatMessageTime(value) : "";
  node.textContent = label;
  if (value) {
    node.setAttribute("datetime", value instanceof Date ? value.toISOString() : String(value));
  } else {
    node.removeAttribute("datetime");
  }
  node.classList.toggle("hidden", !label);
}

function updateCopyReplyButton(message, text) {
  const button = message?.querySelector(".copy-reply-button");
  if (!button) return;
  const hasText = Boolean(String(text || "").trim());
  button.classList.toggle("hidden", !hasText);
  button.disabled = !hasText;
  if (hasText) {
    button.dataset.copyText = String(text || "").trim();
    resetCopyReplyButton(button);
  } else {
    delete button.dataset.copyText;
  }
}

async function copyReplyFromMessage(message) {
  const button = message?.querySelector(".copy-reply-button");
  const text = button?.dataset.copyText || message?.querySelector(".answer-box")?.textContent || "";
  const cleanText = String(text || "").trim();
  if (!button || !cleanText) return;
  const copied = await writeClipboardText(cleanText);
  const selected = copied ? false : selectReplyText(message);
  setCopyReplyButtonFeedback(button, copied, selected);
}

async function writeClipboardText(text) {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch {
    // Fall through to the textarea fallback below.
  }
  return writeClipboardTextFallback(text);
}

function writeClipboardTextFallback(text) {
  const textarea = document.createElement("textarea");
  textarea.value = text;
  textarea.setAttribute("readonly", "");
  textarea.className = "clipboard-fallback";
  document.body.append(textarea);
  textarea.select();
  let copied = false;
  try {
    copied = document.execCommand("copy");
  } catch {
    copied = false;
  }
  textarea.remove();
  return copied;
}

function selectReplyText(message) {
  const source = message?.querySelector(".answer-box");
  if (!source) return false;
  try {
    const range = document.createRange();
    range.selectNodeContents(source);
    const selection = window.getSelection();
    selection.removeAllRanges();
    selection.addRange(range);
    return true;
  } catch {
    return false;
  }
}

function setCopyReplyButtonFeedback(button, copied, selected = false) {
  const label = copied ? "已复制" : selected ? "已选中" : "复制失败";
  button.classList.toggle("copied", copied);
  button.classList.toggle("selected", selected && !copied);
  button.innerHTML = copied || selected ? checkReplyIcon() : copyReplyIcon();
  button.setAttribute("aria-label", label);
  button.setAttribute("title", label);
  button.dataset.tooltip = label;
  window.clearTimeout(Number(button.dataset.copyFeedbackTimer || 0));
  button.dataset.copyFeedbackTimer = String(window.setTimeout(() => resetCopyReplyButton(button), 1600));
}

function resetCopyReplyButton(button) {
  button.classList.remove("copied");
  button.classList.remove("selected");
  button.innerHTML = copyReplyIcon();
  button.setAttribute("aria-label", "复制回复");
  button.setAttribute("title", "复制回复");
  button.dataset.tooltip = "复制回复";
}

function copyReplyIcon() {
  return `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 8V6a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2h-2"></path><path d="M6 8h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2v-8a2 2 0 0 1 2-2Z"></path></svg>`;
}

function checkReplyIcon() {
  return `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m5 12 4 4L19 6"></path></svg>`;
}

function startThinkingElapsed(message, startedAtMs = performance.now()) {
  state.thinkingStartedAt = startedAtMs;
  setThinkingElapsed(message, 0);
  state.thinkingElapsedTimer = window.setInterval(() => {
    setThinkingElapsed(message, performance.now() - state.thinkingStartedAt);
  }, 500);
}

function setThinkingElapsed(message, elapsedMs) {
  const node = message?.querySelector(".thinking-elapsed");
  if (!node) return;
  if (elapsedMs === null || elapsedMs === undefined || elapsedMs === "") {
    node.textContent = "查看处理过程";
    return;
  }
  const milliseconds = Number(elapsedMs);
  if (!Number.isFinite(milliseconds) || milliseconds < 0) {
    node.textContent = "查看处理过程";
    return;
  }
  node.textContent = `已思考 ${formatThinkingDuration(milliseconds)}`;
}

function resolveThinkingElapsedMs(result = {}, fallbackMs) {
  const candidates = [
    result.thinking_elapsed_ms,
    result.elapsed_ms,
    result.elapsedMilliseconds,
    result.debug?.thinking_elapsed_ms,
    fallbackMs,
  ];
  for (const candidate of candidates) {
    const value = Number(candidate);
    if (Number.isFinite(value) && value >= 0) return value;
  }
  return null;
}

function formatThinkingDuration(milliseconds) {
  const totalSeconds = Math.max(0, Math.round(Number(milliseconds) / 1000));
  if (totalSeconds < 60) return `${totalSeconds}秒`;
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return seconds ? `${minutes}分${seconds}秒` : `${minutes}分钟`;
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
  clearDatasetHeaderStatus();
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

function clearDatasetHeaderStatus() {
  if (!el.datasetStatus) return;
  el.datasetStatus.textContent = "";
  el.datasetStatus.classList.add("hidden");
  el.datasetStatus.setAttribute("aria-hidden", "true");
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
  el.resultMessage.__vdsResult = result;
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
  renderExecutionArtifacts(result.execution_artifacts || []);
  renderAnswerSources(result);
  state.latestActivityResult = result;
  state.liveActivityTrace = normalizeActivityTrace(result.activity_trace_v2 || state.liveActivityTrace);
  if (el.activityDrawer && !el.activityDrawer.classList.contains("hidden")) {
    renderActivityDrawer(result);
  }
  setMessageTime(el.resultMessage, options.createdAt || result.responded_at || result.completed_at || result.conversation?.updated_at || result.created_at || new Date().toISOString());
  setThinkingElapsed(el.resultMessage, resolveThinkingElapsedMs(result, options.thinkingElapsedMs));
  updateCopyReplyButton(el.resultMessage, result.answer || "");
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
  const tokens = ["看一下", "看下", "看看", "总结", "概览", "总览", "主要讲什么", "讲什么", "有什么字段", "有哪些字段", "字段含义", "什么意思", "有什么区别", "区别", "这几张表", "这几个表", "这些表", "这些文件", "清洗", "影响行数", "影响比例", "修改原始数据"];
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
  const y = resolveChartY(rows, chart?.y, fallbackColumns);
  if (!rows.length || !x || !y) {
    if (chart?.image_data_uri) {
      el.chartPanel.className = "chart-panel";
      el.chartPanel.innerHTML = renderChartImage(chart);
      return;
    }
    el.chartPanel.className = "chart-panel hidden";
    return;
  }
  const values = rows
    .map((row) => ({ label: String(row[x] ?? ""), value: Number(row[y]) }))
    .filter((item) => item.label && Number.isFinite(item.value));
  if (values.length <= 1) {
    if (chart?.image_data_uri) {
      el.chartPanel.className = "chart-panel";
      el.chartPanel.innerHTML = renderChartImage(chart);
      return;
    }
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
  bindChartInteractions(el.chartPanel);
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
  const width = 680;
  const displayValues = values.slice(0, horizontal ? 18 : 16);
  const colors = ["#2563eb", "#0ea5e9", "#4f46e5", "#14b8a6", "#f59e0b", "#64748b"];
  const { xName, yName } = chartAxisMeta(chart);
  const domain = chartNumberDomain(displayValues, true);
  const ticks = chartTicks(domain.min, domain.max, 5);
  const bars = displayValues.map((item, index) => {
    if (horizontal) {
      return "";
    }
    const left = 72;
    const right = 28;
    const top = 28;
    const bottom = 74;
    const height = 340;
    const plotWidth = width - left - right;
    const plotHeight = height - top - bottom;
    const zeroY = chartScale(0, domain.min, domain.max, top + plotHeight, top);
    const gap = 8;
    const barWidth = Math.max(16, (plotWidth - gap * (displayValues.length - 1)) / displayValues.length);
    const x = left + index * (barWidth + gap);
    const valueY = chartScale(item.value, domain.min, domain.max, top + plotHeight, top);
    const y = Math.min(zeroY, valueY);
    const barHeight = Math.max(2, Math.abs(zeroY - valueY));
    const tooltip = chartTooltip({
      label: item.label,
      value: item.value,
      xName,
      yName,
      x: x + barWidth / 2 - 78,
      y: y - 66,
      width,
    });
    return `
      <g class="chart-hit" tabindex="0" focusable="true">
        <title>${escapeHtml(`${xName}: ${item.label}\n${yName}: ${formatNumber(item.value)}`)}</title>
        <rect x="${x.toFixed(1)}" y="${y.toFixed(1)}" width="${barWidth.toFixed(1)}" height="${barHeight.toFixed(1)}" fill="${colors[index % colors.length]}" rx="4"></rect>
        <text x="${(x + barWidth / 2).toFixed(1)}" y="${(top + plotHeight + 24).toFixed(1)}" text-anchor="middle" class="axis-label">${escapeHtml(shortLabel(item.label, 8))}</text>
        ${tooltip}
      </g>
    `;
  });
  if (horizontal) {
    return renderHorizontalBarChart(displayValues, chart, width, colors, domain, ticks, xName, yName);
  }
  const height = 340;
  const left = 72;
  const right = 28;
  const top = 28;
  const bottom = 74;
  const plotWidth = width - left - right;
  const plotHeight = height - top - bottom;
  const zeroY = chartScale(0, domain.min, domain.max, top + plotHeight, top);
  const grid = ticks
    .map((tick) => {
      const y = chartScale(tick, domain.min, domain.max, top + plotHeight, top);
      return `
        <line x1="${left}" y1="${y.toFixed(1)}" x2="${left + plotWidth}" y2="${y.toFixed(1)}" class="grid-line"></line>
        <text x="${left - 10}" y="${(y + 4).toFixed(1)}" text-anchor="end" class="axis-label">${formatNumber(tick)}</text>
      `;
    })
    .join("");
  return `
    <div class="chart-title">${escapeHtml(chart?.title || "自动图表")}</div>
    <svg class="chart-svg" viewBox="0 0 ${width} ${height}" role="img">
      ${grid}
      <line x1="${left}" y1="${top}" x2="${left}" y2="${top + plotHeight}" class="axis-line"></line>
      <line x1="${left}" y1="${zeroY.toFixed(1)}" x2="${left + plotWidth}" y2="${zeroY.toFixed(1)}" class="axis-line"></line>
      <text x="${left + plotWidth / 2}" y="${height - 18}" text-anchor="middle" class="axis-title">${escapeHtml(xName)}</text>
      <text transform="translate(18 ${top + plotHeight / 2}) rotate(-90)" text-anchor="middle" class="axis-title">${escapeHtml(yName)}</text>
      ${bars.join("")}
    </svg>
  `;
}

function renderHorizontalBarChart(displayValues, chart, width, colors, domain, ticks, xName, yName) {
  const left = 154;
  const right = 54;
  const top = 28;
  const rowHeight = 32;
  const bottom = 62;
  const height = Math.max(300, top + bottom + displayValues.length * rowHeight);
  const plotWidth = width - left - right;
  const plotHeight = displayValues.length * rowHeight;
  const zeroX = chartScale(0, domain.min, domain.max, left, left + plotWidth);
  const grid = ticks
    .map((tick) => {
      const x = chartScale(tick, domain.min, domain.max, left, left + plotWidth);
      return `
        <line x1="${x.toFixed(1)}" y1="${top - 6}" x2="${x.toFixed(1)}" y2="${top + plotHeight}" class="grid-line"></line>
        <text x="${x.toFixed(1)}" y="${top + plotHeight + 22}" text-anchor="middle" class="axis-label">${formatNumber(tick)}</text>
      `;
    })
    .join("");
  const bars = displayValues
    .map((item, index) => {
      const y = top + index * rowHeight + 5;
      const valueX = chartScale(item.value, domain.min, domain.max, left, left + plotWidth);
      const barX = Math.min(zeroX, valueX);
      const barWidth = Math.max(2, Math.abs(valueX - zeroX));
      const tooltip = chartTooltip({
        label: item.label,
        value: item.value,
        xName,
        yName,
        x: barX + barWidth + 10,
        y: y - 20,
        width,
      });
      return `
        <g class="chart-hit" tabindex="0" focusable="true">
          <title>${escapeHtml(`${xName}: ${item.label}\n${yName}: ${formatNumber(item.value)}`)}</title>
          <text x="${left - 12}" y="${y + 15}" text-anchor="end" class="axis-label">${escapeHtml(shortLabel(item.label, 18))}</text>
          <rect x="${barX.toFixed(1)}" y="${y}" width="${barWidth.toFixed(1)}" height="20" fill="${colors[index % colors.length]}" rx="4"></rect>
          ${tooltip}
        </g>
      `;
    })
    .join("");
  return `
    <div class="chart-title">${escapeHtml(chart?.title || "自动图表")}</div>
    <svg class="chart-svg" viewBox="0 0 ${width} ${height}" role="img">
      ${grid}
      <line x1="${zeroX.toFixed(1)}" y1="${top - 6}" x2="${zeroX.toFixed(1)}" y2="${top + plotHeight}" class="axis-line"></line>
      <line x1="${left}" y1="${top + plotHeight}" x2="${left + plotWidth}" y2="${top + plotHeight}" class="axis-line"></line>
      <text x="${left + plotWidth / 2}" y="${height - 16}" text-anchor="middle" class="axis-title">${escapeHtml(yName)}</text>
      <text transform="translate(18 ${top + plotHeight / 2}) rotate(-90)" text-anchor="middle" class="axis-title">${escapeHtml(xName)}</text>
      ${bars}
    </svg>
  `;
}

function renderLineChart(values, chart) {
  const width = 680;
  const height = 340;
  const left = 72;
  const right = 32;
  const top = 28;
  const bottom = 74;
  const plotWidth = width - left - right;
  const plotHeight = height - top - bottom;
  const displayValues = values.slice(0, 30);
  const domain = chartNumberDomain(displayValues, false);
  const ticks = chartTicks(domain.min, domain.max, 5);
  const { xName, yName } = chartAxisMeta(chart);
  const points = displayValues.map((item, index, list) => {
    const x = left + (index / Math.max(list.length - 1, 1)) * plotWidth;
    const y = chartScale(item.value, domain.min, domain.max, top + plotHeight, top);
    return { x, y, label: item.label, value: item.value };
  });
  const grid = ticks
    .map((tick) => {
      const y = chartScale(tick, domain.min, domain.max, top + plotHeight, top);
      return `
        <line x1="${left}" y1="${y.toFixed(1)}" x2="${left + plotWidth}" y2="${y.toFixed(1)}" class="grid-line"></line>
        <text x="${left - 10}" y="${(y + 4).toFixed(1)}" text-anchor="end" class="axis-label">${formatNumber(tick)}</text>
      `;
    })
    .join("");
  const step = Math.max(1, Math.ceil(points.length / 6));
  const xLabels = points
    .map((point, index) =>
      index % step === 0 || index === points.length - 1
        ? `<text x="${point.x.toFixed(1)}" y="${top + plotHeight + 24}" text-anchor="middle" class="axis-label">${escapeHtml(shortLabel(point.label, 8))}</text>`
        : "",
    )
    .join("");
  return `
    <div class="chart-title">${escapeHtml(chart?.title || "趋势图")}</div>
    <svg class="chart-svg" viewBox="0 0 ${width} ${height}" role="img">
      ${grid}
      <line x1="${left}" y1="${top}" x2="${left}" y2="${top + plotHeight}" class="axis-line"></line>
      <line x1="${left}" y1="${top + plotHeight}" x2="${left + plotWidth}" y2="${top + plotHeight}" class="axis-line"></line>
      <text x="${left + plotWidth / 2}" y="${height - 18}" text-anchor="middle" class="axis-title">${escapeHtml(xName)}</text>
      <text transform="translate(18 ${top + plotHeight / 2}) rotate(-90)" text-anchor="middle" class="axis-title">${escapeHtml(yName)}</text>
      ${xLabels}
      <polyline points="${points.map((point) => `${point.x.toFixed(1)},${point.y.toFixed(1)}`).join(" ")}" class="line-path"></polyline>
      ${points
        .map(
          (point) => `
            <g class="chart-hit" tabindex="0" focusable="true">
              <title>${escapeHtml(`${xName}: ${point.label}\n${yName}: ${formatNumber(point.value)}`)}</title>
              <line x1="${point.x.toFixed(1)}" y1="${top}" x2="${point.x.toFixed(1)}" y2="${top + plotHeight}" class="chart-hover-guide"></line>
              <circle cx="${point.x.toFixed(1)}" cy="${point.y.toFixed(1)}" r="5" class="line-dot"></circle>
              ${chartTooltip({
                label: point.label,
                value: point.value,
                xName,
                yName,
                x: point.x - 78,
                y: point.y - 72,
                width,
              })}
            </g>
          `,
        )
        .join("")}
    </svg>
  `;
}

function renderPieChart(values, chart, type) {
  const colors = ["#2563eb", "#0ea5e9", "#4f46e5", "#14b8a6", "#f59e0b", "#64748b", "#7c3aed", "#22c55e"];
  const total = values.reduce((sum, item) => sum + Math.max(item.value, 0), 0) || 1;
  const width = 640;
  const height = 260;
  const cx = 130;
  const cy = 126;
  const radius = 88;
  let start = -90;
  const slices = values.slice(0, 8).map((item, index) => {
    const pct = Math.max(item.value, 0) / total;
    const end = start + pct * 360;
    const mid = start + (end - start) / 2;
    const color = colors[index % colors.length];
    const path = pieSlicePath(cx, cy, radius, start, end);
    start = end;
    return { ...item, pct, color, path, mid };
  });
  return `
    <div class="chart-title">${escapeHtml(chart?.title || "构成图")}</div>
    <div class="pie-layout">
      <svg class="pie-svg" viewBox="0 0 ${width} ${height}" role="img">
        ${slices
          .map((slice) => {
            const tooltipX = cx + Math.cos((slice.mid * Math.PI) / 180) * (radius + 18);
            const tooltipY = cy + Math.sin((slice.mid * Math.PI) / 180) * (radius + 18);
            return `
              <g class="chart-hit pie-slice" tabindex="0" focusable="true">
                <title>${escapeHtml(`${slice.label}: ${formatNumber(slice.value)} (${formatPercent(slice.pct * 100)})`)}</title>
                <path d="${slice.path}" fill="${slice.color}"></path>
                ${chartTooltip({
                  label: slice.label,
                  value: `${formatNumber(slice.value)} / ${formatPercent(slice.pct * 100)}`,
                  xName: chart?.x || "分类",
                  yName: chart?.y || "值",
                  x: tooltipX,
                  y: tooltipY - 28,
                  width,
                })}
              </g>
            `;
          })
          .join("")}
        ${type === "donut" ? `<circle cx="${cx}" cy="${cy}" r="42" fill="#fff"></circle>` : ""}
      </svg>
      <ul class="pie-legend">
        ${slices
          .map((slice) => `<li class="pie-legend-item" title="${escapeHtml(`${slice.label}: ${formatNumber(slice.value)}`)}"><span style="background:${slice.color}"></span>${escapeHtml(shortLabel(slice.label, 16))} ${formatPercent(slice.pct * 100)}</li>`)
          .join("")}
      </ul>
    </div>
  `;
}

function chartAxisMeta(chart) {
  return {
    xName: String(chart?.x || chart?.encoding?.x || "X"),
    yName: String(chart?.y || chart?.encoding?.y || "Y"),
  };
}

function bindChartInteractions(panel) {
  if (!panel) return;
  const hits = [...panel.querySelectorAll(".chart-hit")];
  const clearActive = (except = null) => {
    hits.forEach((hit) => {
      if (hit !== except) hit.classList.remove("is-active");
    });
  };
  hits.forEach((hit) => {
    hit.addEventListener("pointerenter", () => {
      clearActive(hit);
      hit.classList.add("is-active");
    });
    hit.addEventListener("pointerleave", () => {
      hit.classList.remove("is-active");
    });
    hit.addEventListener("focus", () => {
      clearActive(hit);
      hit.classList.add("is-active");
    });
    hit.addEventListener("blur", () => {
      hit.classList.remove("is-active");
    });
    hit.addEventListener("click", () => {
      clearActive(hit);
      hit.classList.add("is-active");
    });
  });
}

function chartNumberDomain(values, includeZero) {
  const numbers = values.map((item) => Number(item.value)).filter(Number.isFinite);
  let min = Math.min(...numbers);
  let max = Math.max(...numbers);
  if (!Number.isFinite(min) || !Number.isFinite(max)) {
    min = 0;
    max = 1;
  }
  if (includeZero) {
    min = Math.min(0, min);
    max = Math.max(0, max);
  }
  if (min === max) {
    const pad = Math.max(Math.abs(max) * 0.2, 1);
    min -= pad;
    max += pad;
  }
  return { min, max, span: max - min };
}

function chartTicks(min, max, count) {
  if (!Number.isFinite(min) || !Number.isFinite(max) || count <= 1) return [0];
  return Array.from({ length: count }, (_, index) => min + ((max - min) * index) / (count - 1));
}

function chartScale(value, domainMin, domainMax, rangeMin, rangeMax) {
  const span = Math.max(domainMax - domainMin, Number.EPSILON);
  return rangeMin + ((Number(value) - domainMin) / span) * (rangeMax - rangeMin);
}

function chartTooltip({ label, value, xName, yName, x, y, width }) {
  const tooltipWidth = 156;
  const tooltipHeight = 54;
  const safeX = Math.min(Math.max(4, x), width - tooltipWidth - 4);
  const safeY = Math.max(4, y);
  return `
    <g class="chart-hover-card" transform="translate(${safeX.toFixed(1)} ${safeY.toFixed(1)})">
      <rect class="chart-tooltip-bg" width="${tooltipWidth}" height="${tooltipHeight}" rx="8"></rect>
      <text x="10" y="20" class="chart-tooltip-label">${escapeHtml(`${xName}: ${shortLabel(label, 18)}`)}</text>
      <text x="10" y="39" class="chart-tooltip-value">${escapeHtml(`${yName}: ${formatNumber(value)}`)}</text>
    </g>
  `;
}

function pieSlicePath(cx, cy, radius, startDeg, endDeg) {
  const start = polarPoint(cx, cy, radius, endDeg);
  const end = polarPoint(cx, cy, radius, startDeg);
  const largeArc = endDeg - startDeg <= 180 ? 0 : 1;
  return [`M ${cx} ${cy}`, `L ${start.x.toFixed(2)} ${start.y.toFixed(2)}`, `A ${radius} ${radius} 0 ${largeArc} 0 ${end.x.toFixed(2)} ${end.y.toFixed(2)}`, "Z"].join(" ");
}

function polarPoint(cx, cy, radius, angleDeg) {
  const angle = ((angleDeg - 90) * Math.PI) / 180;
  return {
    x: cx + radius * Math.cos(angle),
    y: cy + radius * Math.sin(angle),
  };
}

function renderInsight(insight) {
  const suggestions = (insight?.business_suggestions || insight?.suggestions || []).filter(isUserFacingInsightText);
  const findings = [...(insight?.anomaly_findings || []), ...(insight?.volatility_findings || [])]
    .map((item) => item?.message)
    .filter(isUserFacingInsightText);
  const caveats = (insight?.caveats || []).filter(isUserFacingInsightText);
  const nextQuestions = (insight?.next_questions || []).filter(isUserFacingInsightText).slice(0, 2);
  const summary = cleanInsightSummary(insight?.summary || "");
  const primaryAdvice = pickInsightAdvice(suggestions, findings, caveats);
  const hasInsight = Boolean(summary || primaryAdvice || nextQuestions.length);
  el.insightPanel?.classList.toggle("hidden", !hasInsight);
  if (!hasInsight) {
    el.insightSummary.textContent = "";
    el.insightList.innerHTML = "";
    return;
  }
  el.insightSummary.innerHTML = renderInsightBody(summary, primaryAdvice, nextQuestions);
  el.insightList.innerHTML = "";
}

function pickInsightAdvice(suggestions, findings, caveats) {
  const candidates = [...suggestions, ...findings, ...caveats];
  return candidates.find(isUserFacingInsightText) || "";
}

function renderInsightBody(summary, advice, nextQuestions) {
  const paragraphs = [];
  if (summary) paragraphs.push(escapeHtml(summary));
  if (advice) {
    const parsed = parseInsightText(advice);
    const headline = parsed.action || parsed.observation || advice;
    if (headline) paragraphs.push(`<strong>下一步：</strong>${escapeHtml(headline)}`);
  }
  if (nextQuestions.length) {
    paragraphs.push(`<strong>可继续问：</strong>${nextQuestions.map((question) => escapeHtml(question)).join("；")}`);
  }
  return paragraphs.map((paragraph) => `<p>${paragraph}</p>`).join("");
}

function parseInsightText(text) {
  const raw = String(text || "").trim();
  const observation = raw.match(/(?:观察|风险|边界)[:：]([^；;]+)/)?.[1]?.trim() || raw.split(/[；;]/)[0] || raw;
  const evidence = raw.match(/依据[:：]([^；;]+)/)?.[1]?.trim() || "";
  const action = raw.match(/(?:建议|下一步)[:：]([^；;]+)/)?.[1]?.trim() || "";
  return { observation, evidence, action };
}

function renderExecutionArtifacts(artifacts) {
  const safeArtifacts = Array.isArray(artifacts) ? artifacts.filter((item) => item && item.code) : [];
  el.artifactPanel?.classList.add("hidden");
  if (!el.artifactList) return;
  el.artifactList.innerHTML = "";
}

function renderAnswerSources(result, message = el.resultMessage) {
  const panel = message?.querySelector(".answer-source-panel") || el.sourcePanel;
  const list = message?.querySelector(".answer-source-list") || el.sourceList;
  const count = panel?.querySelector(".answer-source-count");
  if (!panel || !list) return;
  const sources = buildAnswerSourceRows(result);
  if (!sources.length) {
    panel.classList.add("hidden");
    if ("open" in panel) panel.open = false;
    if (count) count.textContent = "";
    list.innerHTML = "";
    return;
  }
  list.innerHTML = sources
    .map(
      (source) => {
        const meta = answerSourceMeta(source);
        return `
        <li>
          <span class="answer-source-icon ${escapeHtml(sourceFileIconClass(source.fileName || ""))}" aria-hidden="true">${sourceFileIcon(source.fileName || "")}</span>
          <span class="answer-source-copy">
            <strong title="${escapeHtml(source.fileName || "上传文件")}">${escapeHtml(source.fileName || "上传文件")}</strong>
            ${meta ? `<span>${escapeHtml(meta)}</span>` : ""}
          </span>
        </li>
      `;
      },
    )
    .join("");
  if (count) count.textContent = `${sources.length} 个文件`;
  if ("open" in panel) panel.open = false;
  panel.classList.remove("hidden");
}

function buildAnswerSourceRows(result) {
  if (!result) return [];
  const directSources = normalizeAnswerSourceReferences(result.source_references);
  if (directSources.length) return directSources;
  const isChat = result.answer_type === "chat" || result.debug?.agent_mode === "chat_without_dataset" || result.debug?.agent_mode === "chat_with_dataset";
  if (isChat) return [];
  return deriveAnswerSourcesFromProfile(result, state.profile);
}

function normalizeAnswerSourceReferences(references) {
  if (!Array.isArray(references)) return [];
  return references
    .map((reference) => {
      const fileName = String(reference?.file_name || reference?.source_file || reference?.title || "").trim();
      const tableItems = normalizeAnswerSourceTables(reference?.tables);
      const rowCount = Number(reference?.row_count || tableItems.reduce((sum, table) => sum + Number(table.rowCount || 0), 0));
      const columnCount = Number(reference?.column_count || (tableItems.length === 1 ? tableItems[0].columnCount : 0));
      return {
        fileName,
        tableNames: uniqueStrings(tableItems.map((table) => table.tableName)),
        tableCount: Number(reference?.table_count || tableItems.length || 0),
        rowCount: Number.isFinite(rowCount) && rowCount > 0 ? rowCount : 0,
        columnCount: Number.isFinite(columnCount) && columnCount > 0 ? columnCount : 0,
      };
    })
    .filter((source) => source.fileName || source.tableNames.length);
}

function normalizeAnswerSourceTables(tables) {
  if (!Array.isArray(tables)) return [];
  return tables
    .map((table) => {
      if (typeof table === "string") {
        return { tableName: table, rowCount: 0, columnCount: 0 };
      }
      return {
        tableName: String(table?.table_name || table?.name || "").trim(),
        rowCount: Number(table?.row_count || 0),
        columnCount: Number(table?.column_count || 0),
      };
    })
    .filter((table) => table.tableName);
}

function deriveAnswerSourcesFromProfile(result, profile) {
  const tables = Array.isArray(profile?.tables) ? profile.tables : [];
  if (!tables.length) return [];
  const wanted = extractResultSourceTableNames(result);
  let selected = wanted.length
    ? tables.filter((table) => profileTableMatchesSources(table, wanted))
    : [];
  if (!selected.length && shouldUseAllProfileSources(result, tables, wanted)) {
    selected = tables;
  }
  if (!selected.length) return [];
  return normalizeAnswerSourceReferences(groupProfileTablesBySourceFile(selected, profile));
}

function extractResultSourceTableNames(result) {
  const names = [];
  appendSourceNames(names, result?.debug?.source_tables);
  appendSourceNames(names, result?.logic_form?.source_tables);
  appendSourceNames(names, result?.logic_form?.parameters?.source_tables);
  appendSourceNames(names, result?.logic_form?.parameters?.tables);
  appendSourceNames(names, result?.logic_form?.parameters?.table);
  [result?.debug?.join_plan, result?.logic_form?.join_plan, result?.logic_form?.parameters?.join_plan].forEach((joinPlan) => {
    appendSourceNames(names, joinPlan?.left_table);
    appendSourceNames(names, joinPlan?.right_table);
  });
  return uniqueStrings(names.map((name) => String(name || "").trim()).filter(Boolean));
}

function appendSourceNames(names, value) {
  if (!value) return;
  if (Array.isArray(value)) {
    value.forEach((item) => appendSourceNames(names, item));
    return;
  }
  if (typeof value === "string") {
    names.push(value);
  }
}

function shouldUseAllProfileSources(result, tables, wanted) {
  if (wanted.length || result?.success === false || result?.answer_type === "chat") return false;
  return tables.length === 1 || result?.answer_type === "overview" || result?.answer_type === "cleaning_simulation" || result?.debug?.operation === "multi_table_dataset_overview";
}

function profileTableMatchesSources(table, sourceNames) {
  const sourceKeys = new Set(sourceNames.flatMap((name) => sourceMatchKeys(name)));
  return sourceMatchKeys(table?.table_name)
    .concat(sourceMatchKeys(table?.source_file), sourceMatchKeys(table?.file_name), sourceMatchKeys(table?.sheet))
    .some((key) => sourceKeys.has(key));
}

function sourceMatchKeys(value) {
  const text = String(value || "").trim().toLowerCase();
  if (!text) return [];
  const stem = text.replace(/\.[^.]+$/, "");
  return stem && stem !== text ? [text, stem] : [text];
}

function groupProfileTablesBySourceFile(tables, profile) {
  const grouped = new Map();
  tables.forEach((table) => {
    const fileName = String(table?.source_file || table?.file_name || profile?.file_name || table?.table_name || "上传文件").trim();
    if (!grouped.has(fileName)) grouped.set(fileName, { file_name: fileName, tables: [] });
    grouped.get(fileName).tables.push({
      table_name: table?.table_name || fileName,
      sheet: table?.sheet || "",
      row_count: table?.row_count || 0,
      column_count: table?.column_count || 0,
    });
  });
  return [...grouped.values()].map((reference) => ({
    ...reference,
    table_count: reference.tables.length,
    row_count: reference.tables.reduce((sum, table) => sum + Number(table.row_count || 0), 0),
    column_count: reference.tables.length === 1 ? Number(reference.tables[0].column_count || 0) : 0,
  }));
}

function answerSourceMeta(source) {
  const shapePart = [source.rowCount ? `${formatNumber(source.rowCount)} 行` : "", source.columnCount ? `${formatNumber(source.columnCount)} 列` : ""]
    .filter(Boolean)
    .join(" / ");
  return shapePart || (source.tableCount > 1 ? `${source.tableCount} 张表` : "");
}

function uniqueStrings(values) {
  const result = [];
  values.forEach((value) => {
    const text = String(value || "").trim();
    if (text && !result.includes(text)) result.push(text);
  });
  return result;
}

function refreshRenderedAnswerSources() {
  const messages = [el.resultTemplate, ...el.chatMessages.querySelectorAll(".assistant-result-message")].filter(Boolean);
  messages.forEach((message) => {
    if (message.__vdsResult) {
      renderAnswerSources(message.__vdsResult, message);
    }
  });
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
  renderAnswerSources(null);
  setMessageTime(el.resultMessage, options.createdAt || new Date().toISOString());
  startThinkingElapsed(el.resultMessage, options.startedAtMs);
  updateCopyReplyButton(el.resultMessage, "");
  el.chatMessages.append(el.resultMessage);
  revealMessage(el.resultMessage);

  const steps = buildLiveSteps(question, Boolean(state.datasetId));
  if (options.liveActivity) {
    renderProcessItems(
      [{ title: "接收实时过程", summary: "我先确认问题类型和可用数据，然后等待后端安全事件。", status: "active" }],
      "我先确认问题类型和可用数据。",
      [],
      { collapse: false, liveSummary: true, activityTrace: normalizeActivityTrace(state.liveActivityTrace) },
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
      { collapse: false, liveSummary: true },
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
  if (state.thinkingElapsedTimer) {
    window.clearInterval(state.thinkingElapsedTimer);
    state.thinkingElapsedTimer = null;
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
  const activityNode = activityNodeFromMonitorEvent(payload);
  if (activityNode) {
    mergeActivityTraceNode(activityNode);
  }
  if (Array.isArray(payload.payload?.activity_trace_v2) && payload.payload.activity_trace_v2.length) {
    state.liveActivityTrace = normalizeActivityTrace(payload.payload.activity_trace_v2);
  }
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
  renderProcessItems(timelineSteps, latest?.summary || "正在处理。", [], { collapse: false, liveSummary: true, activityTrace: normalizeActivityTrace(state.liveActivityTrace) });
  if (el.activityDrawer && !el.activityDrawer.classList.contains("hidden")) {
    renderActivityDrawer(state.latestActivityResult || {});
  }
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
    agent_failed: "步骤失败",
    correction_rerun_started: "修正重跑",
    activity_trace_delta: "活动更新",
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
    agent_failed: `${monitorRoleName(event.role)} 处理失败。`,
    correction_rerun_started: cleanActivityText(event.summary) || "修正节点触发重跑执行路径。",
    activity_trace_delta: cleanActivityText(event.summary) || "执行链路已更新。",
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

function activityNodeFromMonitorEvent(event) {
  const type = String(event.event_type || "");
  if (type === "activity_trace_delta" && event.payload?.node) {
    return normalizeActivityNode(event.payload.node);
  }
  if (Array.isArray(event.payload?.activity_trace_v2) && event.payload.activity_trace_v2.length) {
    return null;
  }
  if (["agent_started", "agent_completed", "agent_failed", "correction_rerun_started"].includes(type)) {
    const role = String(event.role || event.stage || "activity");
    const status = event.status === "failed" || type === "agent_failed" ? "failed" : event.status === "active" || type === "agent_started" || type === "correction_rerun_started" ? "active" : "completed";
    const payload = event.payload || {};
    const result = payload.result?.output_payload || {};
    const stateAfter = payload.state_after || payload.state_after_correction || {};
    return normalizeActivityNode({
      id: `live_${role}`,
      kind: role.includes("executor") ? "executor" : "agent",
      role,
      status,
      title: monitorRoleName(role),
      summary: cleanActivityText(event.summary) || `${monitorRoleName(role)} ${status === "active" ? "正在处理" : status === "failed" ? "处理失败" : "已完成"}。`,
      actions: activityActionsFromPayload(role, result, stateAfter),
      outputs_summary: result && Object.keys(result).length ? result : stateAfter,
      tool_calls: payload.new_tool_calls || [],
    });
  }
  if (type === "code_artifact_ready") {
    return normalizeActivityNode({
      id: "live_execution_artifacts",
      kind: "artifact",
      role: "code_artifact",
      status: "completed",
      title: "复现代码",
      summary: cleanActivityText(event.summary) || "复现代码已准备好。",
      outputs_summary: event.payload || {},
    });
  }
  return null;
}

function activityActionsFromPayload(role, result = {}, stateAfter = {}) {
  const actions = [];
  if (role === "planner") {
    const logic = result.logic_form || stateAfter.logic_form || {};
    if (logic.operation) actions.push(`分析类型：${logic.operation}`);
    if (logic.source_tables?.length) actions.push(`数据表：${logic.source_tables.join("、")}`);
    if (logic.metric || logic.parameters?.metric) actions.push(`指标：${logic.metric || logic.parameters.metric}`);
  } else if (role === "pandas_executor") {
    actions.push(result.success === false ? "Pandas 执行失败" : "按计划执行 Pandas 计算");
  } else if (role === "sql_executor") {
    actions.push(result.skipped ? `SQL skipped：${result.reason || "当前问题未走 SQL"}` : result.success === false ? "SQL 执行失败" : "执行 SQL 复算");
  } else if (role === "verifier") {
    const verification = result.verification || stateAfter.verification || {};
    if (verification.passed !== undefined) actions.push(`校验：${verification.passed ? "通过" : "未通过"}`);
    if (verification.pandas_sql_consistent !== undefined) actions.push(`Pandas/SQL 一致：${verification.pandas_sql_consistent}`);
  }
  return actions.filter(Boolean);
}

function mergeActivityTraceNode(node) {
  if (!node?.id) return;
  const nodes = normalizeActivityTrace(state.liveActivityTrace);
  const index = nodes.findIndex((item) => item.id === node.id);
  if (index >= 0) {
    nodes[index] = { ...nodes[index], ...node };
  } else {
    nodes.push(node);
  }
  state.liveActivityTrace = nodes.slice(-18);
}

function openActivityDrawer(result = {}, triggerSummary = null) {
  state.drawerResult = result || state.latestActivityResult || {};
  state.drawerTriggerSummary = triggerSummary || null;
  el.activityDrawer?.classList.remove("hidden");
  el.activityBackdrop?.classList.remove("hidden");
  el.activityDrawer?.setAttribute("aria-hidden", "false");
  document.body.classList.add("activity-drawer-open");
  updateThinkingSummaryExpanded(true);
  renderActivityDrawer(state.drawerResult);
}

function closeActivityDrawer() {
  el.activityDrawer?.classList.add("hidden");
  el.activityBackdrop?.classList.add("hidden");
  el.activityDrawer?.setAttribute("aria-hidden", "true");
  document.body.classList.remove("activity-drawer-open");
  updateThinkingSummaryExpanded(false);
  state.drawerTriggerSummary = null;
}

function handleThinkingSummaryClick(event) {
  const summary = event.target.closest?.(".process-details summary");
  if (!summary || !el.chatMessages?.contains(summary)) return;
  event.preventDefault();
  const message = summary.closest(".assistant-result-message, #result-message, .assistant-message");
  const details = summary.closest(".process-details");
  if (details) details.open = false;
  openActivityDrawer(message?.__vdsResult || state.latestActivityResult || {}, summary);
}

function handleThinkingSummaryKeydown(event) {
  if (event.key !== "Enter" && event.key !== " ") return;
  const summary = event.target.closest?.(".process-details summary");
  if (!summary || !el.chatMessages?.contains(summary)) return;
  event.preventDefault();
  const message = summary.closest(".assistant-result-message, #result-message, .assistant-message");
  const details = summary.closest(".process-details");
  if (details) details.open = false;
  openActivityDrawer(message?.__vdsResult || state.latestActivityResult || {}, summary);
}

function updateThinkingSummaryExpanded(expanded) {
  el.chatMessages?.querySelectorAll(".process-details summary").forEach((summary) => {
    summary.setAttribute("aria-expanded", String(expanded && summary === state.drawerTriggerSummary));
  });
}

function renderActivityDrawer(result = {}) {
  if (!el.activityDrawerList) return;
  const sections = buildActivityDrawerSections(result);
  const trace = sections.flatMap((section) => section.nodes);
  if (el.activityDrawerTitle) el.activityDrawerTitle.textContent = "思考与执行链路";
  if (el.activityDrawerSummary) el.activityDrawerSummary.textContent = drawerSummary(result, trace);
  if (!sections.length) {
    el.activityDrawerList.innerHTML = `<li class="activity-drawer-empty">暂无活动。</li>`;
    return;
  }
  el.activityDrawerList.innerHTML = sections.map(renderActivityDrawerSection).join("");
}

function buildActivityDrawerSections(result = {}) {
  const thoughtTrace = activityTraceFromProcessView(result);
  const executionTrace = buildDrawerActivityTrace(result, { includeProcessFallback: false });
  const sections = [];
  if (thoughtTrace.length) {
    sections.push({ title: "思考过程", nodes: thoughtTrace });
  }
  if (executionTrace.length) {
    sections.push({ title: "执行链路", nodes: executionTrace });
  }
  if (!sections.length) {
    const fallbackTrace = buildDrawerActivityTrace(result);
    if (fallbackTrace.length) sections.push({ title: "执行链路", nodes: fallbackTrace });
  }
  return sections;
}

function buildDrawerActivityTrace(result = {}, options = {}) {
  let trace = normalizeActivityTrace(result.activity_trace_v2);
  if (!trace.length && options.includeLiveFallback !== false) trace = normalizeActivityTrace(state.liveActivityTrace);
  if (!trace.length && options.includeProcessFallback !== false) trace = activityTraceFromProcessView(result);
  const artifacts = normalizeActivityArtifacts(result.execution_artifacts);
  const hasArtifactNode = trace.some((node) => node.artifacts?.length);
  if (artifacts.length && !hasArtifactNode) {
    trace.push(
      normalizeActivityNode({
        id: "execution_artifacts",
        kind: "artifact",
        role: "code_artifact",
        status: "completed",
        title: "Execution Artifacts",
        summary: `生成 ${artifacts.length} 个安全复现代码片段。`,
        artifacts,
      }),
    );
  }
  return trace;
}

function drawerSummary(result, trace) {
  if (result?.question) {
    return `围绕“${shortLabel(result.question, 36)}”展示思考过程、真实执行节点、工具调用和安全复现代码。`;
  }
  if (trace.some((node) => node.status === "active")) return "正在接收后端实时活动。";
  return "发送问题后，这里会显示思考过程、真实执行节点、工具调用和安全复现代码。";
}

function activityTraceFromProcessView(result = {}) {
  const steps = Array.isArray(result.process_view_v2?.steps) ? result.process_view_v2.steps : [];
  return steps.map((step, index) =>
    normalizeActivityNode({
      id: `process_${index}`,
      kind: "process",
      role: step.source || "",
      status: step.status || "completed",
      title: step.title || `Step ${index + 1}`,
      summary: step.summary || "",
      actions: [...normalizeStringList(step.evidence), ...normalizeStringList(step.assumptions), ...normalizeStringList(step.caveats)],
      outputs_summary: { mode: result.process_view_v2?.mode || "" },
    }),
  );
}

function renderActivityDrawerNode(node) {
  const actions = normalizeStringList(node.actions);
  const toolCalls = Array.isArray(node.tool_calls) ? node.tool_calls : [];
  const artifacts = normalizeActivityArtifacts(node.artifacts);
  return `
    <li class="activity-node ${escapeHtml(node.status || "completed")} ${escapeHtml(node.kind || "agent")}">
      <div class="activity-node-marker" aria-hidden="true"></div>
      <article>
        <header class="activity-node-header">
          <div>
            <span>${escapeHtml(activityRoleLabel(node.role || node.kind))}</span>
            <strong>${escapeHtml(node.title || node.role || "活动")}</strong>
          </div>
          <em>${escapeHtml(activityStatusLabel(node.status))}</em>
        </header>
        ${node.summary ? `<p class="activity-node-summary">${escapeHtml(node.summary)}</p>` : ""}
        ${actions.length ? `<ul class="activity-action-list">${actions.slice(0, 6).map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>` : ""}
        ${toolCalls.length ? renderActivityToolCalls(toolCalls) : ""}
        ${artifacts.length ? renderActivityArtifactCards(artifacts) : ""}
        ${node.safety_note ? `<small>${escapeHtml(node.safety_note)}</small>` : ""}
      </article>
    </li>
  `;
}

function renderActivityDrawerSection(section) {
  const nodes = normalizeActivityTrace(section.nodes);
  if (!nodes.length) return "";
  return `
    <li class="activity-drawer-section">
      <h3>${escapeHtml(section.title || "执行链路")}</h3>
      <ol class="activity-section-list">
        ${nodes.map(renderActivityDrawerNode).join("")}
      </ol>
    </li>
  `;
}

function renderActivityToolCalls(toolCalls) {
  return `
    <div class="activity-tool-list">
      ${toolCalls
    .slice(0, 6)
    .map(
      (tool) => `
        <div class="activity-tool-row ${tool.success === false ? "failed" : "completed"}">
          <strong>${escapeHtml(tool.tool_name || "tool_call")}</strong>
          <span>${escapeHtml(tool.success === false ? "失败" : "成功")}${tool.latency_ms ? ` / ${formatNumber(tool.latency_ms)}ms` : ""}</span>
          ${tool.arguments_summary ? `<p>参数：${escapeHtml(formatJsonPreview(tool.arguments_summary, 280))}</p>` : ""}
          ${tool.result_summary ? `<p>结果：${escapeHtml(formatJsonPreview(tool.result_summary, 280))}</p>` : ""}
        </div>
      `,
    )
    .join("")}
    </div>
  `;
}

function renderActivityArtifactCards(artifacts) {
  return `
    <div class="activity-artifact-list">
      ${artifacts
    .slice(0, 4)
    .map(
      (artifact) => `
        <article class="activity-artifact-card">
          <div class="artifact-card-header">
            <strong>${escapeHtml(artifact.title || artifact.language || "代码")}</strong>
            <span>${escapeHtml((artifact.language || "").toUpperCase())}</span>
          </div>
          ${artifact.purpose ? `<p>${escapeHtml(artifact.purpose)}</p>` : ""}
          <pre><code>${escapeHtml(artifact.code || "")}</code></pre>
          ${artifact.output_summary ? `<small>${escapeHtml(artifact.output_summary)}</small>` : ""}
        </article>
      `,
    )
    .join("")}
    </div>
  `;
}

function normalizeActivityTrace(trace) {
  return Array.isArray(trace) ? trace.map(normalizeActivityNode).filter((node) => node.title || node.summary || node.artifacts?.length) : [];
}

function normalizeActivityNode(node = {}) {
  const safeNode = node && typeof node === "object" ? node : {};
  return {
    id: String(safeNode.id || safeNode.node_id || safeNode.role || `activity_${Date.now()}`).slice(0, 96),
    kind: String(safeNode.kind || "agent").slice(0, 40),
    role: String(safeNode.role || "").slice(0, 80),
    status: ["active", "completed", "failed", "pending"].includes(String(safeNode.status)) ? String(safeNode.status) : "completed",
    title: cleanActivityText(safeNode.title || safeNode.role || safeNode.kind || "活动"),
    summary: cleanActivityText(safeNode.summary || ""),
    actions: normalizeStringList(safeNode.actions),
    outputs_summary: safeNode.outputs_summary && typeof safeNode.outputs_summary === "object" ? safeNode.outputs_summary : {},
    tool_calls: Array.isArray(safeNode.tool_calls) ? safeNode.tool_calls.map(normalizeActivityToolCall).filter(Boolean) : [],
    artifacts: normalizeActivityArtifacts(safeNode.artifacts),
    safety_note: cleanActivityText(safeNode.safety_note || ""),
  };
}

function normalizeActivityToolCall(tool) {
  if (!tool || typeof tool !== "object") return null;
  return {
    tool_name: cleanActivityText(tool.tool_name || ""),
    requested_by: cleanActivityText(tool.requested_by || ""),
    success: tool.success !== false,
    latency_ms: Number(tool.latency_ms || 0),
    arguments_summary: redactActivityObject(tool.arguments_summary || {}),
    result_summary: redactActivityObject(tool.result_summary || {}),
  };
}

function normalizeActivityArtifacts(artifacts) {
  return Array.isArray(artifacts)
    ? artifacts
        .filter((artifact) => artifact && artifact.code)
        .map((artifact) => ({
          artifact_id: cleanActivityText(artifact.artifact_id || ""),
          language: cleanActivityText(artifact.language || ""),
          title: cleanActivityText(artifact.title || artifact.language || "代码"),
          purpose: cleanActivityText(artifact.purpose || ""),
          code: cleanActivityCode(artifact.code || ""),
          output_summary: cleanActivityText(artifact.output_summary || ""),
        }))
    : [];
}

function normalizeStringList(values) {
  return (Array.isArray(values) ? values : values ? [values] : [])
    .map((value) => cleanActivityText(value))
    .filter(Boolean);
}

function activityRoleLabel(role) {
  return monitorRoleName(role) || "活动";
}

function activityStatusLabel(status) {
  if (status === "active") return "进行中";
  if (status === "failed") return "失败";
  if (status === "pending") return "等待";
  return "完成";
}

function redactActivityObject(value) {
  try {
    return JSON.parse(JSON.stringify(value || {}, (key, item) => (isBlockedActivityKey(key) ? undefined : typeof item === "string" ? cleanActivityText(item) : item)));
  } catch {
    return {};
  }
}

function isBlockedActivityKey(key) {
  const lowered = String(key || "").toLowerCase();
  return ["chain_of_thought", "raw_prompt", "raw_reasoning", "reasoning_tokens", "api_key", "task_id", "standard_answer", "hidden_answer", "public_proxy", "scorer"].some((token) =>
    lowered.includes(token),
  );
}

function cleanActivityCode(code) {
  let value = String(code || "");
  ["chain_of_thought", "raw_prompt", "raw_reasoning", "reasoning_tokens", "api_key", "task_id", "standard_answer", "hidden_answer", "public_proxy", "scorer"].forEach((token) => {
    value = value.replace(new RegExp(token, "gi"), "[redacted]");
  });
  return value.slice(0, 4000);
}

function cleanActivityText(text) {
  const value = String(text || "").trim();
  if (!value) return "";
  const lowered = value.toLowerCase();
  const blocked = ["chain_of_thought", "raw_prompt", "raw reasoning", "reasoning_tokens", "api_key", "task_id", "standard_answer", "hidden_answer", "public_proxy", "scorer"];
  if (blocked.some((token) => lowered.includes(token))) return "";
  return shortLabel(value.replace(/\s+/g, " "), 96);
}

function formatJsonPreview(value, limit = 600) {
  let text = "";
  try {
    text = JSON.stringify(redactActivityObject(value), null, 2);
  } catch {
    text = String(value || "");
  }
  return text.length > limit ? `${text.slice(0, limit - 1)}…` : text;
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
  const liveSummary = options.liveSummary ? oneLineProcessSummary(summary) : "";
  if (el.processSummary) {
    el.processSummary.textContent = liveSummary;
    el.processSummary.setAttribute("aria-hidden", liveSummary ? "false" : "true");
  }
  el.processDetails?.classList.toggle("has-live-summary", Boolean(liveSummary));
  if (options.collapse && el.processDetails) el.processDetails.open = false;
  const hasActiveStep = steps.some((step) => step.status === "active");
  const hasFailedStep = steps.some((step) => step.status === "failed");
  el.processPanel?.classList.toggle("is-active", hasActiveStep);
  el.processPanel?.classList.toggle("is-failed", hasFailedStep);
  if (!steps.length) {
    el.processTimeline.innerHTML = `<li class="muted-cell">提问后显示分析过程。</li>`;
    return;
  }
  const processHtml = steps
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
    .join("");
  el.processTimeline.innerHTML = processHtml + renderArtifactCards(artifacts);
}

function oneLineProcessSummary(summary) {
  const text = String(summary || "").replace(/\s+/g, " ").trim();
  if (!text) return "";
  const firstSentence = text.match(/^(.{1,96}?[。！？!?])(?:\s|$)/)?.[1] || text.split(/[；;]/)[0] || text;
  return shortLabel(firstSentence, 96);
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

function renderUserFacingError(title, message, options = {}) {
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
  renderAnswerSources(null);
  renderProcessItems([{ title, summary: message || "请检查上传文件或稍后重试。", status: "failed" }], "处理没有完成。");
  setMessageTime(el.resultMessage, options.createdAt || new Date().toISOString());
  setThinkingElapsed(el.resultMessage, options.thinkingElapsedMs);
  updateCopyReplyButton(el.resultMessage, title);
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
  if (item.projectId) {
    renderHistory();
    return;
  }
  state.runHistory.unshift(item);
  state.runHistory = sortHistoryItems(state.runHistory).slice(0, 8);
  renderHistory();
}

function markHistoryRunning(question, fallbackRunId, projectId = currentMessageProjectId()) {
  const runId = state.conversationId || fallbackRunId || `pending_${Date.now()}`;
  if (projectId) {
    state.activeHistoryRunId = "";
    state.runHistory = state.runHistory.filter((entry) => entry.runId !== runId);
    renderHistory();
    return;
  }
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

function markHistoryFailed(question, message, projectId = currentMessageProjectId()) {
  const runId = state.activeHistoryRunId || state.conversationId || `failed_${Date.now()}`;
  if (projectId) {
    state.activeHistoryRunId = "";
    state.runHistory = state.runHistory.filter((entry) => entry.runId !== runId);
    renderHistory();
    return;
  }
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
    if (isChatSearchOpen()) renderChatSearchResults();
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
  if (isChatSearchOpen()) renderChatSearchResults();
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
  const rawTitle = await openTextDialog({
    title: "重命名对话",
    label: "对话名称",
    value: item?.title || item?.question || "未命名对话",
    confirmText: "保存",
  });
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
    const loadedHistory = (payload.conversations || [])
      .filter((item) => !item.project_id)
      .map((item) => {
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
          projectId: "",
        };
      });
    const loadedIds = new Set(loadedHistory.map((item) => item.runId));
    const localUnreadHistory = state.runHistory.filter((item) => item.unread === true && !item.projectId && !loadedIds.has(item.runId));
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
      appendUserMessage(message.content || "", { createdAt: message.created_at });
    } else if (message.payload) {
      const assistantMessage = createAssistantResultMessage();
      bindResultMessage(assistantMessage);
      el.chatMessages.append(el.resultMessage);
      renderResult(message.payload, { updateHistory: false, createdAt: message.created_at });
    }
  }
  if (state.datasetId) {
    await restoreDatasetProfile(state.datasetId);
  } else {
    renderProfile();
    el.datasetChip.textContent = "未上传数据";
    clearDatasetHeaderStatus();
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
    refreshRenderedAnswerSources();
    setApiStatus("ready", "数据集已就绪");
  } catch {
    state.profile = null;
    clearRestoredFileRecords();
    renderProfile();
    el.datasetChip.textContent = state.datasetId ? "数据记录已关联" : "未上传数据";
    clearDatasetHeaderStatus();
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
  setMessageTime(el.resultMessage, "");
  setThinkingElapsed(el.resultMessage, null);
  updateCopyReplyButton(el.resultMessage, "");
  renderAnswerSources(null);
  if (el.resultMessage) el.resultMessage.__vdsResult = null;
  renderInsight(null);
  renderProcess([]);
}

function appendUserMessage(question, options = {}) {
  if (state.projectId) {
    state.projectDraftActive = true;
    updateShellMode(false);
  }
  const createdAt = options.createdAt || new Date().toISOString();
  el.welcomeMessage?.classList.add("hidden");
  el.projectHome?.classList.add("hidden");
  const message = document.createElement("article");
  message.className = "message user-message";
  message.innerHTML = `
    <div class="avatar" aria-hidden="true">你</div>
    <div class="message-content">
      <p>${escapeHtml(question)}</p>
      <time class="message-meta" datetime="${escapeHtml(createdAt)}">${escapeHtml(formatMessageTime(createdAt))}</time>
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
  clearDatasetHeaderStatus();
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
  el.processDetails = message.querySelector(".process-details");
  el.processSummary = message.querySelector(".process-summary-text, #process-summary");
  el.thinkingElapsed = message.querySelector(".thinking-elapsed");
  el.processTimeline = message.querySelector(".process-timeline");
  el.artifactPanel = message.querySelector(".artifact-panel");
  el.artifactList = message.querySelector(".artifact-list");
  el.sourcePanel = message.querySelector(".answer-source-panel");
  el.sourceList = message.querySelector(".answer-source-list");
  el.messageMeta = message.querySelector(".message-meta");
  el.copyReplyButton = message.querySelector(".copy-reply-button");
  if (el.copyReplyButton) {
    el.copyReplyButton.onclick = () => copyReplyFromMessage(message);
  }
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
