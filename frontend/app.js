const MONITOR_RUN_INDEX_KEY = "vds-monitor-runs";
const ACTIVE_MONITOR_RUN_KEY = "vds-active-monitor-run";
const PROJECT_PANEL_COLLAPSED_KEY = "vds-project-panel-collapsed";
const WORKBENCH_SYNC_CHANNEL = "vds-workbench-sync";
const WORKBENCH_SYNC_PULSE_KEY = "vds-workbench-sync-pulse";
const LEGACY_MESSAGE_ENDPOINT = "/api/data-agent/message";
const JOB_MESSAGE_ENDPOINT = "/api/data-agent/message/jobs";
const SUPPORTED_AGENT_MODES = new Set(["multi_agent", "single_agent"]);
const SUPPORTED_EXECUTION_MODES = new Set(["auto", "dual", "pandas", "sql"]);
const MAX_MONITOR_RUN_RECORDS = 80;
const HISTORY_LOAD_BATCH = 30;
const SLOW_RUN_THRESHOLD_MS = 15000;
const DEFAULT_QUESTION_PLACEHOLDER = "向 VDS 提问，例如：哪个城市订单金额最高？";
const ATTACHED_FILE_QUESTION_PLACEHOLDER = "有问题，尽管问";
const CONTINUATION_PROMPT_LABELS = ["可继续提问", "可继续问", "继续提问", "后续提问", "后续问题"];
const RULE_FILE_STATUS_TONES = ["empty", "pending", "ready", "error"];
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
  runHistoryOffset: 0,
  runHistoryHasMore: true,
  runHistoryLoading: false,
  runHistoryRenderedCount: 0,
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
  activityDrawerAutoScroll: true,
  activityDrawerCloseTimer: null,
  activityDrawerScrollFrame: 0,
  activityDrawerScrollTimeout: null,
  textDialogResolve: null,
  chatSearchQuery: "",
  workspaceChannel: null,
  lastWorkspacePulseId: "",
  applyingUrlState: false,
  activeRun: null,
  activeRunPollTimer: 0,
  activeRunStartedAt: 0,
  activeRunQuestion: "",
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
  composer: document.querySelector(".composer"),
  composerFileTray: document.querySelector("#composer-file-tray"),
  fileStatusWrap: document.querySelector("#file-status-wrap"),
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
el.activityDrawerList?.addEventListener("scroll", handleActivityDrawerScroll);
el.runHistory?.addEventListener("scroll", handleRunHistoryScroll);
el.ruleModeToggle?.addEventListener("change", updateRuleMode);
el.ruleFileInput?.addEventListener("change", handleRuleFileSelection);
el.ruleUploadButton?.addEventListener("click", handleRuleUploadButtonClick);
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
initializeWorkspace();

function updateFileSummary() {
  const files = [...el.fileInput.files];
  if (!files.length) {
    state.hasPendingUpload = false;
    state.fileRecords = [];
    el.fileSummary.textContent = "查看文件";
    el.fileDetail.textContent = "未附加";
    el.uploadButton.disabled = true;
    renderFilePanel();
    updateRunButton();
    return;
  }
  state.hasPendingUpload = true;
  state.fileRecords = files.map((file) => fileRecordFromFile(file, "pending"));
  el.fileSummary.textContent = "查看文件";
  el.fileDetail.textContent = `${files.length} 个文件待发送`;
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
    el.fileSummary.textContent = "查看文件";
    el.fileDetail.textContent = `${state.fileRecords.length} 个文件已就绪`;
  } else {
    el.fileSummary.textContent = "查看文件";
    el.fileDetail.textContent = "文件信息不可用";
  }
  updateRunButton();
}

function clearRestoredFileRecords() {
  state.hasPendingUpload = false;
  state.fileRecords = [];
  el.uploadButton.disabled = true;
  renderFilePanel();
  el.fileSummary.textContent = "查看文件";
  el.fileDetail.textContent = state.datasetId ? "文件信息不可用" : "未附加";
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
  const hasRecords = Boolean(records.length);
  const showComposerFiles = state.hasPendingUpload && hasRecords;
  el.fileSummary.disabled = !records.length;
  el.fileStatusWrap?.classList.toggle("hidden", !hasRecords);
  el.composer?.classList.toggle("has-files", showComposerFiles);
  if (el.questionInput) {
    const placeholder = showComposerFiles ? ATTACHED_FILE_QUESTION_PLACEHOLDER : DEFAULT_QUESTION_PLACEHOLDER;
    el.questionInput.dataset.placeholder = placeholder;
    el.questionInput.setAttribute("aria-label", placeholder);
  }
  if (el.filePanelCount) el.filePanelCount.textContent = String(records.length);
  renderComposerFileTray(showComposerFiles ? records : []);
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

function renderComposerFileTray(records) {
  if (!el.composerFileTray) return;
  el.composerFileTray.classList.toggle("hidden", !records.length);
  if (!records.length) {
    el.composerFileTray.innerHTML = "";
    return;
  }
  el.composerFileTray.innerHTML = records
    .map(
      (file) => `
        <div class="composer-file-card" role="listitem" title="${escapeHtml(file.name)}">
          <span class="composer-file-icon" aria-hidden="true"></span>
          <span class="composer-file-copy">
            <strong title="${escapeHtml(file.name)}">${escapeHtml(file.name)}</strong>
            <span>${escapeHtml(fileCardTypeText(file))}</span>
          </span>
        </div>
      `,
    )
    .join("");
}

function fileCardTypeText(file) {
  const name = String(file?.name || "").toLowerCase();
  if (/\.(csv|xlsx|xls|parquet|arrow|feather)$/.test(name)) return "电子表格";
  if (/\.(json|yaml|yml)$/.test(name)) return "结构化文件";
  if (/\.(pdf|doc|docx|docm|rtf|odt|pages|md|txt|html|htm)$/.test(name)) return "规则/说明文件";
  return file?.meta || "文件";
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
  const uploadedRecords = backendUploadedFileRecords(profile);
  if (uploadedRecords.length) {
    return uploadedRecords.map((record) => {
      const file = fileByName.get(record.name);
      const tableCount = countTablesForSource(profile, record.name);
      const size = record.size || file?.size || 0;
      return {
        name: record.name,
        size,
        status: "ready",
        statusText: fileStatusText("ready"),
        meta: fileMetaText(size, tableCount, record.sourceType),
      };
    });
  }
  const sourceNames = uniqueSourceFileNames(profile);
  const ruleNames = boundRuleFileNames(profile);
  const names = uniqueNames([...(sourceNames.length ? sourceNames : files.map((file) => file.name)), ...ruleNames]);
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

function backendUploadedFileRecords(profile) {
  const records = [];
  const uploadedFiles = Array.isArray(profile?.uploaded_files) ? profile.uploaded_files : [];
  uploadedFiles.forEach((item) => {
    const name = String(item.file_name || item.name || "").trim();
    if (!name || records.some((record) => record.name === name)) return;
    const size = Number(item.size_bytes || item.size || 0);
    records.push({
      name,
      size: Number.isFinite(size) ? size : 0,
      sourceType: String(item.source_type || item.file_role || ""),
    });
  });
  return records;
}

function boundRuleFileNames(profile) {
  const boundFiles = Array.isArray(profile?.auto_bound_rule_files)
    ? profile.auto_bound_rule_files
    : Array.isArray(profile?.files)
      ? profile.files
      : [];
  return uniqueNames(
    boundFiles
      .map((file) => String(file.file_name || file.name || "").trim())
      .filter(Boolean),
  );
}

function uniqueNames(names) {
  const result = [];
  names.forEach((name) => {
    if (name && !result.includes(name)) result.push(name);
  });
  return result;
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

function fileMetaText(size, tableCount, sourceType = "") {
  const meta = [size ? formatFileSize(size) : "", tableCount ? `${tableCount} 张表` : ""].filter(Boolean).join(" / ");
  if (meta) return meta;
  if (sourceType === "table") return "表格文件";
  if (sourceType === "rule") return "规则/说明文件";
  if (sourceType === "source") return "说明文件";
  return "文件";
}

function fileStatusText(status) {
  if (status === "ready") return "已就绪";
  if (status === "failed") return "失败";
  return "待上传";
}

const RULE_FILE_EMPTY_HINT = "可选：上传规则文件可以补充语义模型、指标口径和计算方法";

function setRuleFileStatus(message, tone = "empty") {
  if (!el.ruleFileStatus) return;
  const safeTone = RULE_FILE_STATUS_TONES.includes(tone) ? tone : "empty";
  el.ruleFileStatus.textContent = message;
  el.ruleFileStatus.title = message;
  el.ruleFileStatus.classList.remove(...RULE_FILE_STATUS_TONES.map((item) => `is-${item}`));
  el.ruleFileStatus.classList.add(`is-${safeTone}`);
  el.ruleFileStatus.classList.toggle("hidden", safeTone === "empty" || !message);
}

function profileRuleFileIds(profile) {
  return uniqueRuleFileIds([
    ...(Array.isArray(profile?.auto_bound_user_rule_file_ids) ? profile.auto_bound_user_rule_file_ids : []),
    ...(Array.isArray(profile?.auto_bound_rule_files) ? profile.auto_bound_rule_files.map((file) => file?.file_id) : []),
  ]);
}

function ruleUploadFileIds(result) {
  return uniqueRuleFileIds([
    result?.file_id,
    ...(Array.isArray(result?.file_ids) ? result.file_ids : []),
    ...(Array.isArray(result?.files) ? result.files.map((file) => file?.file_id) : []),
    ...profileRuleFileIds(result),
  ]);
}

function uniqueRuleFileIds(values) {
  const ids = [];
  (values || []).forEach((value) => {
    const id = String(value || "").trim();
    if (id && !ids.includes(id)) ids.push(id);
  });
  return ids;
}

function applyUserRuleFileIds(ids, { replace = false } = {}) {
  const nextIds = uniqueRuleFileIds(replace ? ids : [...splitRuleFileIds(state.userRuleFileId), ...ids]);
  state.userRuleFileId = nextIds.join(",");
  state.autoRuleFileIds = uniqueRuleFileIds(replace ? ids : [...state.autoRuleFileIds, ...ids]);
  state.ruleModeEnabled = Boolean(state.userRuleFileId);
  return nextIds;
}

function splitRuleFileIds(value) {
  return uniqueRuleFileIds(String(value || "").split(","));
}

function ruleUploadFileNames(result, fallbackFiles = []) {
  const names = [
    result?.file_name,
    ...(Array.isArray(result?.files) ? result.files.map((file) => file?.file_name || file?.name) : []),
    ...(Array.isArray(result?.auto_bound_rule_files) ? result.auto_bound_rule_files.map((file) => file?.file_name || file?.name) : []),
  ]
    .map((name) => String(name || "").trim())
    .filter(Boolean);
  return uniqueNames(names.length ? names : fallbackFiles.map((file) => file.name));
}

function updateRuleMode() {
  state.ruleModeEnabled = Boolean(el.ruleModeToggle?.checked);
  el.ruleUploadPanel?.classList.toggle("hidden", !state.ruleModeEnabled);
  if (!state.ruleModeEnabled) {
    state.userRuleFileId = "";
    state.hasPendingRuleUpload = false;
    if (el.ruleFileInput) el.ruleFileInput.value = "";
    setRuleFileStatus(RULE_FILE_EMPTY_HINT, "empty");
  }
  updateRunButton();
  updateBenchmarkButtons();
}

async function initializeWorkspace() {
  initWorkspaceSync();
  await loadProjects();
  const restoredFromUrl = await applyWorkspaceFromUrl();
  await loadConversations();
  if (!restoredFromUrl) {
    syncUrlWithWorkspace({ replace: true });
  }
}

function initWorkspaceSync() {
  try {
    if ("BroadcastChannel" in window) {
      state.workspaceChannel = new BroadcastChannel(WORKBENCH_SYNC_CHANNEL);
      state.workspaceChannel.onmessage = (event) => handleWorkspaceInvalidation(event.data || {});
    }
  } catch {
    state.workspaceChannel = null;
  }
  window.addEventListener("storage", (event) => {
    if (event.key !== WORKBENCH_SYNC_PULSE_KEY || !event.newValue) return;
    try {
      handleWorkspaceInvalidation(JSON.parse(event.newValue));
    } catch {
      handleWorkspaceInvalidation({ kind: "unknown" });
    }
  });
  window.addEventListener("popstate", () => {
    applyWorkspaceFromUrl();
  });
}

function notifyWorkspaceMutation(kind, payload = {}) {
  const message = {
    id: `pulse_${Date.now()}_${Math.random().toString(16).slice(2)}`,
    kind,
    project_id: payload.project_id || state.projectId || "",
    conversation_id: payload.conversation_id || state.conversationId || "",
    run_id: payload.run_id || "",
    created_at: new Date().toISOString(),
  };
  try {
    state.workspaceChannel?.postMessage(message);
  } catch {
    // BroadcastChannel is an invalidation hint only.
  }
  try {
    window.localStorage.setItem(WORKBENCH_SYNC_PULSE_KEY, JSON.stringify(message));
    window.localStorage.removeItem(WORKBENCH_SYNC_PULSE_KEY);
  } catch {
    // storage event is an invalidation hint only.
  }
}

async function handleWorkspaceInvalidation(message = {}) {
  if (!message || message.id === state.lastWorkspacePulseId) return;
  state.lastWorkspacePulseId = message.id || "";
  await loadProjects();
  if (state.projectId) {
    await loadProjectWorkspace(state.projectId);
  }
  await loadConversations();
  if (message.conversation_id && message.conversation_id === state.conversationId) {
    await loadConversation(state.conversationId);
  }
}

async function applyWorkspaceFromUrl() {
  const params = new URLSearchParams(window.location.search || "");
  const projectId = String(params.get("project_id") || "").trim();
  const conversationId = String(params.get("conversation_id") || "").trim();
  if (!projectId && !conversationId) return false;
  state.applyingUrlState = true;
  try {
    if (conversationId) {
      await loadConversation(conversationId);
      if (projectId && !state.projectId) {
        state.projectId = projectId;
        await loadProjectWorkspace(projectId);
      }
      return true;
    }
    if (projectId) {
      state.projectId = projectId;
      state.projectViewTab = "chats";
      state.projectDraftActive = false;
      renderProjects();
      resetConversation({ preserveProject: true, skipUrlSync: true });
      await loadProjectWorkspace(projectId);
      setApiStatus("ready", "Project 已恢复");
      return true;
    }
  } finally {
    state.applyingUrlState = false;
  }
  return false;
}

function syncUrlWithWorkspace({ replace = true } = {}) {
  if (state.applyingUrlState) return;
  const params = new URLSearchParams();
  if (state.projectId) params.set("project_id", state.projectId);
  if (state.conversationId) params.set("conversation_id", state.conversationId);
  const nextUrl = params.toString() ? `/workbench?${params.toString()}` : "/workbench";
  const currentUrl = `${window.location.pathname}${window.location.search}`;
  if (currentUrl === nextUrl) return;
  const method = replace ? "replaceState" : "pushState";
  window.history[method]({}, "", nextUrl);
}

function handleRuleUploadButtonClick() {
  if (state.hasPendingRuleUpload) {
    void uploadUserRule();
    return;
  }
  el.ruleFileInput?.click();
}

function handleRuleFileSelection() {
  updateRuleFileSummary();
  if (state.hasPendingRuleUpload) {
    void uploadUserRule();
  }
}

function selectedRuleFiles() {
  return [...(el.ruleFileInput?.files || [])];
}

function updateRuleFileSummary() {
  const files = selectedRuleFiles();
  state.hasPendingRuleUpload = Boolean(files.length);
  state.userRuleFileId = state.hasPendingRuleUpload ? "" : state.userRuleFileId;
  state.ruleModeEnabled = state.hasPendingRuleUpload || Boolean(state.userRuleFileId);
  if (el.ruleUploadButton) {
    el.ruleUploadButton.disabled = false;
    el.ruleUploadButton.title = state.hasPendingRuleUpload
      ? `上传 ${files.length} 个规则文件`
      : "上传语义模型、指标口径或计算方法规则，后续分析会基于此规则";
  }
  const pendingText = files.length === 1 ? `待上传：${files[0].name}` : `待上传：${files.length} 个规则文件`;
  setRuleFileStatus(
    files.length ? pendingText : (state.userRuleFileId ? "规则文件已启用" : RULE_FILE_EMPTY_HINT),
    files.length ? "pending" : (state.userRuleFileId ? "ready" : "empty"),
  );
  updateRunButton();
}

async function uploadUserRule() {
  const files = selectedRuleFiles();
  if (!files.length) return null;
  setApiStatus("idle", files.length === 1 ? "上传规则中" : `上传 ${files.length} 个规则文件中`);
  setRuleFileStatus(files.length === 1 ? `上传中：${files[0].name}` : `上传中：${files.length} 个规则文件`, "pending");
  if (el.ruleUploadButton) el.ruleUploadButton.disabled = true;
  try {
    const payload = new FormData();
    const endpoint = files.length === 1 ? "/api/data-agent/upload" : "/api/data-agent/upload-batch";
    if (files.length === 1) {
      payload.append("file", files[0]);
    } else {
      files.forEach((file) => payload.append("files", file));
    }
    payload.append("file_role", "rule");
    payload.append("rule_scope", "user_analysis");
    if (state.datasetId) payload.append("bind_dataset_id", state.datasetId);
    const response = await fetch(endpoint, { method: "POST", body: payload });
    const result = await response.json();
    if (!response.ok || !result.success) {
      throw new Error(errorText(result) || `HTTP ${response.status}`);
    }
    const uploadedFileIds = Array.isArray(result.file_ids) ? result.file_ids : (result.file_id ? [result.file_id] : []);
    const uploadedFiles = Array.isArray(result.files) ? result.files : [];
    state.userRuleFileId = uploadedFileIds.join(",");
    state.hasPendingRuleUpload = false;
    state.ruleModeEnabled = Boolean(state.userRuleFileId);
    if (el.ruleFileInput) el.ruleFileInput.value = "";
    setRuleFileStatus(
      files.length === 1
        ? `${result.file_name || uploadedFiles[0]?.file_name || "规则文件"} 已启用`
        : `${uploadedFileIds.length || files.length} 个规则文件已启用`,
      "ready",
    );
    setApiStatus("ready", files.length === 1 ? "规则文件已启用" : "规则文件已启用");
    updateBenchmarkButtons();
    return result;
  } catch (error) {
    state.userRuleFileId = "";
    state.hasPendingRuleUpload = false;
    state.ruleModeEnabled = false;
    if (el.ruleFileInput) el.ruleFileInput.value = "";
    setRuleFileStatus(`规则上传失败：${String(error.message || error)}`, "error");
    setApiStatus("error", "规则上传失败");
    return null;
  } finally {
    if (el.ruleUploadButton) el.ruleUploadButton.disabled = false;
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
      : "/api/data-agent/upload-batch";
    files.forEach((file) => payload.append("files", file));
    if (state.datasetId) payload.append("bind_dataset_id", state.datasetId);
    const response = await fetch(endpoint, { method: "POST", body: payload });
    const profile = await response.json();
    if (!response.ok || !profile.success) {
      throw new Error(errorText(profile) || `HTTP ${response.status}`);
    }
    const ruleOnlyFileIds = profile?.file_role === "rule" ? ruleUploadFileIds(profile) : [];
    if (ruleOnlyFileIds.length) {
      applyUserRuleFileIds(ruleOnlyFileIds);
      state.fileRecords = buildReadyFileRecords(files, profile);
      state.hasPendingUpload = false;
      setRuleFileStatus(
        `${ruleUploadFileNames(profile, files).length || ruleOnlyFileIds.length} 个规则文件已自动识别并启用`,
        "ready",
      );
      setApiStatus("ready", "规则文件已自动识别并启用");
      renderFilePanel();
      el.fileSummary.textContent = "查看文件";
      el.fileDetail.textContent = `${files.length} 个文件已就绪`;
      updateBenchmarkButtons();
      return profile;
    }
    const hasDatasetProfile = Boolean(profile.dataset_id);
    const hasSourceOnlyProfile = hasDatasetProfile && (profile.dataset_kind === "uploaded_sources" || (profile.source_file_count && !(profile.tables || []).length));
    if (hasDatasetProfile) {
      state.profile = profile;
      state.datasetId = profile.dataset_id;
      const autoRuleFileIds = profileRuleFileIds(profile);
      if (autoRuleFileIds.length) {
        applyUserRuleFileIds(autoRuleFileIds, { replace: true });
      } else {
        state.autoRuleFileIds = [];
        state.userRuleFileId = "";
        state.ruleModeEnabled = false;
        setRuleFileStatus(RULE_FILE_EMPTY_HINT, "empty");
      }
      state.selectedTable = profile.tables?.[0]?.table_name || "";
    }
    state.fileRecords = buildReadyFileRecords(files, profile);
    state.hasPendingUpload = false;
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
    notifyWorkspaceMutation("source_uploaded", { project_id: state.projectId, conversation_id: state.conversationId });
    el.fileSummary.textContent = "查看文件";
    el.fileDetail.textContent = `${files.length} 个文件已就绪`;
    return profile;
  } catch (error) {
    setApiStatus("error", "上传失败");
    state.datasetId = "";
    state.profile = null;
    state.selectedTable = "";
    state.hasPendingUpload = true;
    state.fileRecords = files.map((file) => fileRecordFromFile(file, "failed"));
    el.fileSummary.textContent = "查看文件";
    el.fileDetail.textContent = `${files.length} 个文件上传失败`;
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
      const autoRuleFileIds = profileRuleFileIds(result);
      if (autoRuleFileIds.length) {
        applyUserRuleFileIds(autoRuleFileIds, { replace: true });
      } else {
        state.autoRuleFileIds = [];
        state.userRuleFileId = "";
        state.ruleModeEnabled = false;
        setRuleFileStatus(RULE_FILE_EMPTY_HINT, "empty");
      }
      state.selectedTable = result.tables?.[0]?.table_name || "";
      renderProfile();
    }
    await loadProjects();
    await loadProjectWorkspace(state.projectId);
    setProjectSourceUploadStatus(`${selectedFiles.length} 个来源已添加。`, "ready");
    setApiStatus("ready", result.dataset_id ? "项目数据源已添加" : "项目来源已添加");
    notifyWorkspaceMutation("source_uploaded", { project_id: state.projectId });
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
  const requestError = validateRunRequestState();
  if (requestError) {
    setApiStatus("error", requestError);
    renderUserFacingError("无法开始分析", requestError);
    updateRunButton();
    return;
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
    const response = await fetch(JOB_MESSAGE_ENDPOINT, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        dataset_id: state.datasetId,
        conversation_id: state.conversationId,
        project_id: messageProjectId,
        question,
        execution_mode: currentExecutionMode(),
        agent_mode: currentAgentMode(),
        user_rule_file_id: state.userRuleFileId || "",
        monitor_run_id: monitorRunId,
      }),
    });
    const job = await response.json();
    if (!response.ok || !job.success) {
      throw new Error(errorText(job) || `HTTP ${response.status}`);
    }
    const run = job.run || {};
    state.activeRun = run;
    state.activeRunStartedAt = thinkingStartedAt;
    state.activeRunQuestion = question;
    updateRunActionButtons(el.resultMessage, { run, mode: "running" });
    notifyWorkspaceMutation("run_started", { project_id: messageProjectId, conversation_id: state.conversationId, run_id: run.run_id });
    const result = await waitForRunResult(run.run_id, {
      question,
      startedAtMs: thinkingStartedAt,
      projectId: messageProjectId,
    });
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
    syncUrlWithWorkspace({ replace: true });
    notifyWorkspaceMutation("run_completed", { project_id: messageProjectId, conversation_id: result.conversation_id || state.conversationId, run_id: run.run_id });
  } catch (error) {
    const fallbackElapsedMs = Math.round(performance.now() - thinkingStartedAt);
    const cancelled = state.activeRun?.status === "cancelled" || /cancel|取消/i.test(String(error.message || error));
    stopProgress();
    closeActivityStream();
    failMonitorRun(question, String(error.message || error));
    markHistoryFailed(question, String(error.message || error), messageProjectId);
    setApiStatus("error", cancelled ? "任务已取消" : "分析失败");
    renderUserFacingError(cancelled ? "任务已取消" : "分析失败", String(error.message || error), { thinkingElapsedMs: fallbackElapsedMs, run: state.activeRun });
  } finally {
    state.isAnalyzing = false;
    state.activeRun = null;
    state.activeRunStartedAt = 0;
    state.activeRunQuestion = "";
    updateRunButton();
  }
}

async function waitForRunResult(runId, context = {}) {
  if (!runId) throw new Error("Run ID 缺失");
  while (true) {
    const statusPayload = await fetchRunStatus(runId);
    const run = statusPayload.run || {};
    state.activeRun = run;
    updateRunActionButtons(el.resultMessage, { run, mode: run.status });
    renderRunStatusProgress(run, context);
    if (run.status === "completed") {
      const result = await fetchRunResult(runId);
      result.run_status = run;
      return result;
    }
    if (run.status === "failed" || run.status === "cancelled") {
      if (run.result_available) {
        const result = await fetchRunResult(runId);
        result.run_status = run;
        return result;
      }
      const message = run.failure_reason || run.error_message || (run.status === "cancelled" ? "任务已取消。" : "任务失败。");
      throw new Error(message);
    }
    await sleep(900);
  }
}

async function fetchRunStatus(runId) {
  const response = await fetch(`/api/data-agent/runs/${encodeURIComponent(runId)}`, { cache: "no-store" });
  const payload = await response.json();
  if (!response.ok || !payload.success) {
    throw new Error(errorText(payload) || `HTTP ${response.status}`);
  }
  return payload;
}

async function fetchRunResult(runId) {
  const response = await fetch(`/api/data-agent/runs/${encodeURIComponent(runId)}/result`, { cache: "no-store" });
  const payload = await response.json();
  if (!response.ok || !payload.success) {
    throw new Error(errorText(payload) || `HTTP ${response.status}`);
  }
  return payload.result || {};
}

function renderRunStatusProgress(run = {}, context = {}) {
  if (!state.isAnalyzing || !run?.run_id) return;
  const elapsedMs = Math.max(0, Math.round(performance.now() - (context.startedAtMs || state.activeRunStartedAt || performance.now())));
  if (elapsedMs < SLOW_RUN_THRESHOLD_MS && run.status !== "cancel_requested") return;
  const latest = run.latest_summary || state.activityEvents.at(-1)?.summary || "后端仍在执行。";
  const stage = run.latest_stage || run.status || "running";
  const status = run.status === "cancel_requested" ? "active" : run.status === "failed" ? "failed" : "active";
  const steps = [
    {
      title: run.status === "cancel_requested" ? "取消请求已发送" : "仍在执行",
      summary: `${latest} 已用时 ${formatThinkingDuration(elapsedMs)}。`,
      status,
    },
    {
      title: "当前阶段",
      summary: stage,
      status,
    },
  ];
  renderProcessItems(steps, `${latest} 已用时 ${formatThinkingDuration(elapsedMs)}。`, [], {
    collapse: false,
    liveSummary: true,
    activityTrace: normalizeActivityTrace(state.liveActivityTrace),
  });
}

function sleep(ms) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
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
  if (event.target.closest(".context-menu, .history-menu-button, .project-menu-button, .project-conversation-menu-button, .download-artifacts-button")) return;
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
    syncUrlWithWorkspace({ replace: true });
    notifyWorkspaceMutation("project_created", { project_id: state.projectId });
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
    notifyWorkspaceMutation("project_updated", { project_id: current.project_id });
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
    syncUrlWithWorkspace({ replace: true });
    notifyWorkspaceMutation("project_deleted", { project_id: current.project_id });
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
  syncUrlWithWorkspace({ replace: true });
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
  syncUrlWithWorkspace({ replace: true });
}

function startProjectConversation() {
  if (!state.projectId) return;
  state.projectDraftActive = true;
  resetConversation();
  syncUrlWithWorkspace({ replace: true });
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
    if (!state.conversationId && state.projectDetails?.default_dataset_id) {
      await restoreDatasetProfile(state.projectDetails.default_dataset_id);
    }
  } catch (error) {
    state.projectDetails = currentProject();
    state.projectConversations = [];
    setApiStatus("error", `Project 载入失败：${String(error.message || error)}`);
  }
  renderProjects();
  renderProjectHome();
}

async function loadProjectConversations(projectId) {
  const scopedQuery = new URLSearchParams({ limit: String(HISTORY_LOAD_BATCH), project_id: projectId });
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

function updateRunActionButtons(message, context = {}) {
  if (!message) return;
  if (context.run) {
    message.__vdsRunStatus = context.run;
  }
  const result = context.result || message.__vdsResult || null;
  const run = context.run || message.__vdsRunStatus || null;
  const mode = String(context.mode || run?.status || "");
  const saveButton = message.querySelector(".save-response-button");
  const downloadButton = message.querySelector(".download-artifacts-button");
  const cancelButton = message.querySelector(".cancel-run-button");
  const retryButton = message.querySelector(".retry-run-button");
  const hasResult = Boolean(result && (result.answer || result.result || result.chart));
  const canSave = Boolean(state.projectId && hasResult && result?.answer);
  const canDownload = hasDownloadableItems(message, result);
  saveButton?.classList.toggle("hidden", !canSave);
  saveButton?.toggleAttribute("disabled", !canSave);
  downloadButton?.classList.toggle("hidden", !canDownload);
  downloadButton?.toggleAttribute("disabled", !canDownload);
  const canCancel = ["starting", "queued", "running", "cancel_requested"].includes(mode) && Boolean(run?.run_id || state.activeRun?.run_id);
  cancelButton?.classList.toggle("hidden", !canCancel);
  cancelButton?.toggleAttribute("disabled", mode === "cancel_requested" || !canCancel);
  const canRetry = ["failed", "cancelled"].includes(mode) && Boolean(run?.run_id);
  retryButton?.classList.toggle("hidden", !canRetry);
  retryButton?.toggleAttribute("disabled", !canRetry);
}

function hasDownloadableItems(message, result) {
  if (!result) return false;
  return Boolean(
    (message?.querySelector(".chart-svg") || result?.chart?.image_data_uri)
      || downloadableResultRows(result).rows.length
      || artifactItems(result).length,
  );
}

async function saveAssistantResponseToProject(message) {
  const result = message?.__vdsResult;
  if (!state.projectId || !result?.answer) return;
  const content = [
    result.answer,
    compactResultSummary(result),
    result.insight?.summary ? `简要结论：${result.insight.summary}` : "",
    chartSummary(result),
  ].filter(Boolean).join("\n\n").trim();
  const metadata = {
    conversation_id: result.conversation_id || state.conversationId || "",
    message_id: result.message_id || message?.dataset?.messageId || "",
    run_id: result.run_id || "",
    dataset_id: result.dataset_id || state.datasetId || "",
    response_version: result.response_version || "",
    saved_at: new Date().toISOString(),
  };
  try {
    const response = await fetch(`/api/data-agent/projects/${encodeURIComponent(state.projectId)}/sources`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        source_type: "saved_response",
        title: shortLabel(result.question || "保存的回答", 70),
        content,
        dataset_id: result.dataset_id || state.datasetId || "",
        metadata,
      }),
    });
    const payload = await response.json();
    if (!response.ok || !payload.success) {
      throw new Error(errorText(payload) || `HTTP ${response.status}`);
    }
    await loadProjectWorkspace(state.projectId);
    notifyWorkspaceMutation("source_saved_response", { project_id: state.projectId, conversation_id: state.conversationId, run_id: result.run_id || "" });
    setApiStatus("ready", "回答已保存到 Project");
  } catch (error) {
    setApiStatus("error", `保存失败：${String(error.message || error)}`);
  }
}

function compactResultSummary(result = {}) {
  const { rows, columns } = downloadableResultRows(result);
  if (!rows.length || !columns.length) {
    const value = result?.result?.value;
    return value === undefined || value === null || value === "" ? "" : `结果值：${String(value)}`;
  }
  const previewRows = rows.slice(0, 5).map((row) => columns.map((column) => `${column}=${String(row?.[column] ?? "")}`).join("，"));
  return [`结果表：${rows.length} 行，${columns.length} 列。`, ...previewRows].join("\n");
}

function chartSummary(result = {}) {
  const chart = result.chart || {};
  if (!chart || (!chart.title && !chart.chart_type && !chart.x && !chart.y)) return "";
  const fields = [
    chart.title ? `标题=${chart.title}` : "",
    chart.chart_type ? `类型=${chart.chart_type}` : "",
    chart.x ? `X=${chart.x}` : "",
    chart.y ? `Y=${chart.y}` : "",
  ].filter(Boolean);
  return `图表：${fields.join("，")}`;
}

function openDownloadMenu(anchor, message) {
  const result = message?.__vdsResult;
  if (!result) return;
  const items = [];
  const currentSvgChart = message?.querySelector(".chart-svg");
  const fallbackImageDataUri = result.chart?.image_data_uri || "";
  const hasClientChartDownload = Boolean(currentSvgChart || fallbackImageDataUri);
  const canDownloadSvg = Boolean(currentSvgChart || String(fallbackImageDataUri).startsWith("data:image/svg"));
  if (canDownloadSvg) {
    items.push({
      label: "图表 SVG",
      className: "download-chart-svg",
      icon: downloadIcon(),
      action: () => downloadChartFromMessage(message, "svg"),
    });
  }
  if (hasClientChartDownload) {
    items.push({
      label: "图表 PNG",
      className: "download-chart-png",
      icon: downloadIcon(),
      action: () => downloadChartFromMessage(message, "png"),
    });
  }
  const table = downloadableResultRows(result);
  if (table.rows.length) {
    items.push({
      label: "结果表 CSV",
      className: "download-table-csv",
      icon: downloadIcon(),
      action: () => downloadTableCsvFromResult(result),
    });
  }
  artifactItems(result).filter((artifact) => {
    if (hasClientChartDownload && artifact.artifact_type === "chart") return false;
    if (table.rows.length && artifact.artifact_type === "result_table" && artifact.format === "csv") return false;
    return true;
  }).forEach((artifact) => {
    items.push({
      label: artifact.display_name || `${artifact.artifact_type || "产物"} ${artifact.format || ""}`,
      className: `download-artifact-${artifact.format || "file"}`,
      icon: downloadIcon(),
      action: () => downloadServerArtifact(artifact),
    });
  });
  if (!items.length) return;
  showContextMenu(anchor, items);
}

function artifactItems(result = {}) {
  const artifacts = result.artifacts_manifest?.artifacts;
  return Array.isArray(artifacts) ? artifacts.filter((artifact) => artifact?.download_url) : [];
}

function downloadableResultRows(result = {}) {
  const rows = rowsWithoutContinuationPrompts(result?.result?.rows || []).filter((row) => row && typeof row === "object");
  const columns = Array.isArray(result?.result?.columns) && result.result.columns.length
    ? result.result.columns.map(String)
    : Object.keys(rows[0] || {});
  return { rows, columns };
}

function downloadServerArtifact(artifact) {
  if (!artifact?.download_url) return;
  const link = document.createElement("a");
  link.href = artifact.download_url;
  link.download = artifact.download_name || artifact.file_name || artifact.display_name || "";
  document.body.append(link);
  link.click();
  link.remove();
}

async function downloadChartFromMessage(message, format) {
  const result = message?.__vdsResult || {};
  const svg = message?.querySelector(".chart-svg");
  if (svg) {
    const source = serializeSvg(svg);
    if (format === "svg") {
      downloadBlob(new Blob([source], { type: "image/svg+xml;charset=utf-8" }), downloadBaseName(result, "chart") + ".svg");
      return;
    }
    downloadSvgAsPng(source, downloadBaseName(result, "chart") + ".png");
    return;
  }
  const dataUri = result.chart?.image_data_uri;
  if (dataUri) {
    if (dataUri.startsWith("data:image/svg")) {
      try {
        const svgSource = normalizeSvgSourceForExport(await (await fetch(dataUri)).text());
        if (format === "svg") {
          downloadBlob(new Blob([svgSource], { type: "image/svg+xml;charset=utf-8" }), downloadBaseName(result, "chart") + ".svg");
        } else {
          downloadSvgAsPng(svgSource, downloadBaseName(result, "chart") + ".png");
        }
        return;
      } catch {
        // Fall back to downloading the original image data below.
      }
    }
    downloadDataUri(dataUri, downloadBaseName(result, "chart") + (dataUri.startsWith("data:image/svg") ? ".svg" : ".png"));
  }
}

function serializeSvg(svg) {
  const clone = svg.cloneNode(true);
  clone.setAttribute("xmlns", "http://www.w3.org/2000/svg");
  const viewBox = parseSvgViewBox(clone.getAttribute("viewBox"));
  if (viewBox) {
    clone.setAttribute("width", String(viewBox.width));
    clone.setAttribute("height", String(viewBox.height));
  }
  clone.querySelectorAll(".chart-hit.is-active").forEach((node) => node.classList.remove("is-active"));
  clone.querySelectorAll(".chart-hover-card, .chart-hover-guide").forEach((node) => node.remove());

  const style = document.createElementNS("http://www.w3.org/2000/svg", "style");
  style.textContent = chartSvgExportStyles();
  clone.insertBefore(style, clone.firstChild);

  const background = document.createElementNS("http://www.w3.org/2000/svg", "rect");
  background.setAttribute("class", "chart-export-background");
  background.setAttribute("x", viewBox ? String(viewBox.x) : "0");
  background.setAttribute("y", viewBox ? String(viewBox.y) : "0");
  background.setAttribute("width", viewBox ? String(viewBox.width) : "100%");
  background.setAttribute("height", viewBox ? String(viewBox.height) : "100%");
  clone.insertBefore(background, style.nextSibling);

  return `<?xml version="1.0" encoding="UTF-8"?>\n${new XMLSerializer().serializeToString(clone)}`;
}

function normalizeSvgSourceForExport(svgSource) {
  const parser = new DOMParser();
  const doc = parser.parseFromString(String(svgSource || ""), "image/svg+xml");
  if (doc.querySelector("parsererror") || doc.documentElement?.tagName?.toLowerCase() !== "svg") {
    return svgSource;
  }
  const svg = document.importNode(doc.documentElement, true);
  svg.classList.add("chart-svg");
  return serializeSvg(svg);
}

function parseSvgViewBox(viewBox) {
  const parts = String(viewBox || "")
    .trim()
    .split(/[\s,]+/)
    .map(Number);
  if (parts.length !== 4 || parts.some((part) => !Number.isFinite(part))) return null;
  const [x, y, width, height] = parts;
  if (width <= 0 || height <= 0) return null;
  return { x, y, width, height };
}

function chartSvgExportStyles() {
  return `
    .chart-svg {
      display: block;
      background: #ffffff;
      overflow: visible;
    }
    .chart-export-background {
      fill: #ffffff;
    }
    .chart-svg text {
      font-family: "Helvetica Neue", Arial, "PingFang SC", "Microsoft YaHei", sans-serif;
      font-synthesis: none;
      font-weight: 400 !important;
      letter-spacing: 0;
      stroke: none !important;
      text-rendering: optimizeLegibility;
    }
    .axis-line {
      stroke: #e5e7eb;
      stroke-width: 1;
    }
    .grid-line {
      stroke: #edf0f4;
      stroke-width: 1;
    }
    .axis-label,
    .value-label {
      fill: #1f2937;
      font-size: 11px;
      font-weight: 400 !important;
    }
    .axis-title {
      fill: #111827;
      font-size: 11px;
      font-weight: 400 !important;
    }
    .line-path {
      fill: none;
      stroke-width: 1.8;
      stroke-linecap: round;
      stroke-linejoin: round;
    }
    .line-dot {
      fill: #ffffff;
      stroke-width: 1.6;
    }
    .line-hit-area {
      fill: transparent;
      stroke: transparent;
    }
    .chart-hit {
      outline: none;
    }
    .chart-tooltip-bg {
      fill: rgba(17, 24, 39, 0.94);
      stroke: rgba(255, 255, 255, 0.2);
    }
    .chart-tooltip-label {
      fill: #d1d5db;
      font-size: 12px;
    }
    .chart-tooltip-value {
      fill: #ffffff;
      font-size: 13px;
      font-weight: 400;
    }
    .chart-legend-label {
      fill: #1f2937;
      font-size: 11px;
      font-weight: 400;
    }
  `;
}

function downloadSvgAsPng(svgSource, fileName) {
  const image = new Image();
  const svgBlob = new Blob([svgSource], { type: "image/svg+xml;charset=utf-8" });
  const url = URL.createObjectURL(svgBlob);
  image.onload = () => {
    const canvas = document.createElement("canvas");
    canvas.width = Math.max(1, image.naturalWidth || 1200);
    canvas.height = Math.max(1, image.naturalHeight || 720);
    const context = canvas.getContext("2d");
    context.fillStyle = "#ffffff";
    context.fillRect(0, 0, canvas.width, canvas.height);
    context.drawImage(image, 0, 0);
    URL.revokeObjectURL(url);
    canvas.toBlob((blob) => {
      if (blob) downloadBlob(blob, fileName);
    }, "image/png");
  };
  image.onerror = () => URL.revokeObjectURL(url);
  image.src = url;
}

function downloadTableCsvFromResult(result) {
  const { rows, columns } = downloadableResultRows(result);
  if (!rows.length || !columns.length) return;
  const lines = [
    columns.map(csvCell).join(","),
    ...rows.map((row) => columns.map((column) => csvCell(row?.[column])).join(",")),
  ];
  downloadBlob(new Blob(["\ufeff" + lines.join("\n")], { type: "text/csv;charset=utf-8" }), downloadBaseName(result, "result_table") + ".csv");
}

function csvCell(value) {
  const text = String(value ?? "");
  const safe = /^[=+\-@]/.test(text) ? `'${text}` : text;
  return /[",\n]/.test(safe) ? `"${safe.replaceAll('"', '""')}"` : safe;
}

function downloadDataUri(dataUri, fileName) {
  const link = document.createElement("a");
  link.href = dataUri;
  link.download = fileName;
  document.body.append(link);
  link.click();
  link.remove();
}

function downloadBlob(blob, fileName) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = fileName;
  document.body.append(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function downloadBaseName(result, fallback) {
  const runId = String(result?.run_id || "").replace(/[^\w-]+/g, "_");
  return runId ? `vds_${fallback}_${runId}` : `vds_${fallback}`;
}

async function cancelRunFromMessage(message) {
  const runId = message?.__vdsRunStatus?.run_id || state.activeRun?.run_id;
  if (!runId) return;
  try {
    const response = await fetch(`/api/data-agent/runs/${encodeURIComponent(runId)}/cancel`, { method: "POST" });
    const payload = await response.json();
    if (!response.ok || !payload.success) {
      throw new Error(errorText(payload) || `HTTP ${response.status}`);
    }
    message.__vdsRunStatus = payload.run || message.__vdsRunStatus;
    updateRunActionButtons(message, { run: payload.run, mode: "cancel_requested" });
    setApiStatus("idle", "正在取消");
  } catch (error) {
    setApiStatus("error", `取消失败：${String(error.message || error)}`);
  }
}

async function retryRunFromMessage(message) {
  const runId = message?.__vdsRunStatus?.run_id;
  if (!runId || state.isAnalyzing) return;
  try {
    const response = await fetch(`/api/data-agent/runs/${encodeURIComponent(runId)}/retry`, { method: "POST" });
    const payload = await response.json();
    if (!response.ok || !payload.success) {
      throw new Error(errorText(payload) || `HTTP ${response.status}`);
    }
    const run = payload.run || {};
    state.isAnalyzing = true;
    state.activeRun = run;
    state.activeRunStartedAt = performance.now();
    bindResultMessage(message);
    message.classList.add("thinking-only");
    updateRunActionButtons(message, { run, mode: "running" });
    setApiStatus("idle", "重试中");
    const result = await waitForRunResult(run.run_id, { startedAtMs: state.activeRunStartedAt });
    stopProgress();
    renderResult(result, { thinkingElapsedMs: Math.round(performance.now() - state.activeRunStartedAt) });
    setApiStatus(result.success ? "ready" : "error", result.success ? "分析完成" : "需要继续确认");
    await loadConversations();
  } catch (error) {
    renderUserFacingError("重试失败", String(error.message || error), { run: state.activeRun });
  } finally {
    state.isAnalyzing = false;
    state.activeRun = null;
    updateRunButton();
  }
}

function downloadIcon() {
  return `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3v12"></path><path d="m7 10 5 5 5-5"></path><path d="M5 21h14"></path></svg>`;
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
    notifyWorkspaceMutation("source_deleted", { project_id: state.projectId });
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
    notifyWorkspaceMutation("memory_deleted", { project_id: state.projectId });
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

function currentAgentMode() {
  const value = el.agentMode?.value || "multi_agent";
  return SUPPORTED_AGENT_MODES.has(value) ? value : "";
}

function currentExecutionMode() {
  const value = el.executionMode?.value || "dual";
  return SUPPORTED_EXECUTION_MODES.has(value) ? value : "";
}

function validateRunRequestState() {
  if (!currentAgentMode()) {
    return "Agent 模式不支持，请选择 multi_agent 或 single_agent。";
  }
  if (!currentExecutionMode()) {
    return "执行模式不支持，请选择 auto、dual、pandas 或 sql。";
  }
  if (state.datasetId) {
    const profileDatasetId = state.profile?.dataset_id || "";
    const datasetReady = state.profile && state.profile.can_analyze !== false && (!profileDatasetId || profileDatasetId === state.datasetId);
    if (!datasetReady) {
      return "当前数据记录不可用，请重新上传数据文件。";
    }
  }
  return "";
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
  const requestError = validateRunRequestState();
  if (requestError) {
    if (el.benchmarkStatus) el.benchmarkStatus.textContent = requestError;
    setApiStatus("error", requestError);
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
        execution_mode: currentExecutionMode(),
        agent_mode: currentAgentMode(),
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
    const roleMeta = table.table_role ? ` / ${tableRoleLabel(table.table_role)}` : "";
    const rangeMeta = table.range_ref ? ` / ${table.range_ref}` : "";
    button.innerHTML = `
      <span>
        <strong>${escapeHtml(table.table_name || "-")}</strong>
        <span class="table-meta">${escapeHtml(table.source_file || "-")} / ${escapeHtml(table.sheet || "sheet: -")}${escapeHtml(roleMeta)}${escapeHtml(rangeMeta)}</span>
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
  el.datasetStatus.classList.remove("ready", "error");
}

function setDatasetHeaderStatus(message, tone = "ready") {
  if (!el.datasetStatus) return;
  const text = String(message || "").trim();
  el.datasetStatus.textContent = text;
  el.datasetStatus.classList.toggle("hidden", !text);
  el.datasetStatus.setAttribute("aria-hidden", text ? "false" : "true");
  el.datasetStatus.classList.toggle("ready", tone === "ready");
  el.datasetStatus.classList.toggle("error", tone === "error");
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
  const runStatus = result.run_status || result.runStatus || null;
  el.resultMessage.__vdsRunStatus = runStatus;
  if (result.message_id) {
    el.resultMessage.dataset.messageId = result.message_id;
  }
  if (result.conversation_id) {
    state.conversationId = result.conversation_id;
  }
  if (result.dataset_id) {
    state.datasetId = result.dataset_id;
  }
  const rawRows = result.result?.rows || [];
  const rows = rowsWithoutContinuationPrompts(rawRows);
  const columns = result.result?.columns || [];
  const isChat = result.answer_type === "chat" || result.debug?.agent_mode === "chat_without_dataset" || result.debug?.agent_mode === "chat_with_dataset";
  const isOverviewShaped = Boolean(result.debug?.user_experience_shaping?.applied);
  el.resultMessage.classList.remove("thinking-only");
  el.resultTitle.textContent = isChat ? "VDS" : "分析结果";
  el.answer.textContent = answerWithCorrectionSummary(result);
  el.resultStatus.textContent = isChat ? "已回复" : result.success ? "已完成" : "需要继续确认";
  renderRows(rows, columns, result);
  renderChart(isOverviewShaped ? null : result.chart, rows, columns, result.answer);
  renderInsight(!isChat && result.success ? result.insight : null, result);
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
  updateRunActionButtons(el.resultMessage, {
    result,
    run: runStatus,
    mode: runStatus?.status || (result.success ? "completed" : "failed"),
  });
  if (options.updateHistory !== false) {
    pushHistory(result);
  }
  syncUrlWithWorkspace({ replace: true });
  revealMessage(el.resultMessage, "start");
}

function tableRoleLabel(role) {
  const labels = {
    data_table: "可分析表",
    field_dictionary: "字段说明",
    rule_or_notes: "规则/说明",
    notes_or_metadata: "说明/元数据",
    empty_sheet: "空 sheet",
  };
  return labels[role] || role;
}

function answerWithCorrectionSummary(result) {
  const answer = result.answer || "-";
  const summary = result.correction_context?.difference_summary;
  if (!summary) return answer;
  return `${answer}\n\n口径修正：${summary}`;
}

function renderRows(rows, columns, result = {}) {
  if (!rows.length || !shouldRenderRows(rows, columns, result)) {
    el.resultTable.className = "result-table hidden";
    el.resultTable.textContent = "";
    return;
  }
  const safeColumns = columns.length ? columns : Object.keys(rows[0]);
  const displayRows = Array.isArray(result?.result?.display_rows) && result.result.display_rows.length ? result.result.display_rows : rows;
  el.resultTable.className = "result-table";
  el.resultTable.innerHTML = `
    <table>
      <thead><tr>${safeColumns.map((column) => `<th>${escapeHtml(column)}</th>`).join("")}</tr></thead>
      <tbody>
        ${displayRows
          .slice(0, 50)
          .map((row, index) => `<tr>${safeColumns.map((column) => `<td>${escapeHtml(formatTableCellValue(column, row?.[column] ?? rows[index]?.[column]))}</td>`).join("")}</tr>`)
          .join("")}
      </tbody>
    </table>
  `;
}

function rowsWithoutContinuationPrompts(rows) {
  if (!Array.isArray(rows)) return [];
  return rows.filter((row) => !isContinuationPromptRow(row));
}

function isContinuationPromptRow(row = {}) {
  if (!row || typeof row !== "object") return false;
  const entries = Object.entries(row);
  if (!entries.length) return false;
  return entries.some(([column, value], index) => {
    if (isContinuationPromptLabel(column)) return true;
    if (!isContinuationPromptLabel(value)) return false;
    return index === 0 || isRowDescriptorColumn(column);
  });
}

function isContinuationPromptLabel(value) {
  const compact = String(value ?? "").replace(/[：:；;\s]/g, "");
  return CONTINUATION_PROMPT_LABELS.some((label) => compact === label);
}

function isRowDescriptorColumn(column) {
  const compact = String(column || "").replace(/\s+/g, "").toLowerCase();
  return ["指标", "项目", "类型", "类别", "说明", "label", "name", "category", "type"].includes(compact);
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
	      ["表名", "行数", "类型", "主要作用", "关键字段"],
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
  if (type === "combo_column_line") {
    el.chartPanel.className = "chart-panel";
    el.chartPanel.innerHTML = renderComboColumnLineChart(rows, chart, x, fallbackColumns);
    bindChartInteractions(el.chartPanel);
    return;
  }
  if (type === "stacked_column") {
    el.chartPanel.className = "chart-panel";
    el.chartPanel.innerHTML = renderStackedColumnChart(rows, chart, x, fallbackColumns);
    bindChartInteractions(el.chartPanel);
    return;
  }
  if (type === "stacked_area") {
    el.chartPanel.className = "chart-panel";
    el.chartPanel.innerHTML = renderStackedAreaChart(rows, chart, x, fallbackColumns);
    bindChartInteractions(el.chartPanel);
    return;
  }
  if (type === "dual_axis_line") {
    el.chartPanel.className = "chart-panel";
    el.chartPanel.innerHTML = renderDualAxisLineChart(rows, chart, x, fallbackColumns);
    bindChartInteractions(el.chartPanel);
    return;
  }
  if (type === "line") {
    const seriesValues = resolveLineSeries(chart, rows, x, y, fallbackColumns);
    if (!seriesValues.length) {
      if (chart?.image_data_uri) {
        el.chartPanel.className = "chart-panel";
        el.chartPanel.innerHTML = renderChartImage(chart);
        return;
      }
      el.chartPanel.className = "chart-panel hidden";
      return;
    }
    el.chartPanel.className = "chart-panel";
    el.chartPanel.innerHTML = renderLineChart(seriesValues, chart);
    bindChartInteractions(el.chartPanel);
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
  if (type === "pie" || type === "donut") {
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

function resolveLineSeries(chart, rows, xColumn, yColumn, fallbackColumns) {
  const requestedColumns = [];
  for (const series of chart?.series || []) {
    const column = String(series?.y || "");
    if (column && column !== xColumn && !requestedColumns.includes(column)) {
      requestedColumns.push(column);
    }
  }
  if (yColumn && !requestedColumns.includes(yColumn)) {
    requestedColumns.unshift(yColumn);
  }
  const fallbackNumericColumns = fallbackColumns.filter((column) => column !== xColumn && rows.some((row) => Number.isFinite(Number(row?.[column]))));
  const candidateColumns = (requestedColumns.length ? requestedColumns : fallbackNumericColumns).filter((column) =>
    rows.some((row) => Number.isFinite(Number(row?.[column]))),
  );
  return candidateColumns
    .map((column) => {
      const points = rows
        .map((row) => ({ label: String(row[xColumn] ?? ""), value: Number(row[column]) }))
        .filter((item) => item.label && Number.isFinite(item.value));
      return { name: column, points };
    })
    .filter((series) => series.points.length > 1);
}

function resolveStackColumns(chart, rows, xColumn, fallbackColumns) {
  const requested = uniqueStrings(
    (chart?.series || [])
      .map((series) => String(series?.y || ""))
      .filter((column) => column && column !== xColumn),
  ).filter((column) => rows.some((row) => Number.isFinite(Number(row?.[column]))));
  if (requested.length >= 2) return requested;
  const encoded = uniqueStrings((chart?.encoding?.stack || []).map((column) => String(column || ""))).filter(
    (column) => column && column !== xColumn && rows.some((row) => Number.isFinite(Number(row?.[column]))),
  );
  if (encoded.length >= 2) return encoded;
  return fallbackColumns.filter((column) => column !== xColumn && rows.some((row) => Number.isFinite(Number(row?.[column]))));
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

function renderComboColumnLineChart(rows, chart, xColumn, fallbackColumns) {
  const width = 860;
  const height = 460;
  const left = 76;
  const right = 84;
  const top = 34;
  const bottom = 76;
  const plotWidth = width - left - right;
  const plotHeight = height - top - bottom;
  const series = Array.isArray(chart?.series) ? chart.series : [];
  const leftColumns = uniqueStrings(
    series.filter((item) => String(item?.type || "bar") === "bar").map((item) => String(item?.y || "")),
  ).filter((column) => column && rows.some((row) => Number.isFinite(Number(row?.[column]))));
  const rightColumns = uniqueStrings(
    series.filter((item) => String(item?.type || "") === "line").map((item) => String(item?.y || "")),
  ).filter((column) => column && rows.some((row) => Number.isFinite(Number(row?.[column]))));
  const fallbackNumeric = fallbackColumns.filter((column) => column !== xColumn && rows.some((row) => Number.isFinite(Number(row?.[column]))));
  const barColumns = (leftColumns.length ? leftColumns : fallbackNumeric.filter((column) => !looksLikeRateField(column)).slice(0, 2)).slice(0, 2);
  const lineColumns = (rightColumns.length ? rightColumns : fallbackNumeric.filter((column) => looksLikeRateField(column)).slice(0, 1)).slice(0, 1);
  if (!barColumns.length || !lineColumns.length) {
    return renderChartImage(chart);
  }
  const displayRows = rows.slice(0, 18);
  const leftValues = displayRows.flatMap((row) => barColumns.map((column) => Number(row?.[column]))).filter(Number.isFinite);
  const rightValues = displayRows.flatMap((row) => lineColumns.map((column) => Number(row?.[column]))).filter(Number.isFinite);
  const leftDomain = chartNumberDomain(leftValues.map((value) => ({ value })), true);
  const rightDomain = chartNumberDomain(rightValues.map((value) => ({ value })), true);
  rightDomain.min = Math.min(0, rightDomain.min);
  const leftTicks = chartTicks(leftDomain.min, leftDomain.max, 5);
  const rightTicks = chartTicks(rightDomain.min, rightDomain.max, 5);
  const groupWidth = plotWidth / Math.max(displayRows.length, 1);
  const gap = Math.min(12, groupWidth * 0.14);
  const barWidth = Math.max(14, Math.min(28, (groupWidth * 0.66 - gap * Math.max(barColumns.length - 1, 0)) / Math.max(barColumns.length, 1)));
  const zeroY = chartScale(0, leftDomain.min, leftDomain.max, top + plotHeight, top);
  const colors = ["#2563eb", "#0ea5e9", "#f59e0b"];
  const bandMarkup = displayRows
    .map((row, index) => {
      const centerX = left + groupWidth * index + groupWidth / 2;
      const previousX = index === 0 ? left : left + groupWidth * index - groupWidth / 2;
      const nextX = index === displayRows.length - 1 ? left + plotWidth : left + groupWidth * index + groupWidth * 1.5;
      const tooltipLines = [
        ...barColumns.map((column) => `${column}: ${formatNumber(row?.[column])}`),
        ...lineColumns.map((column) => `${column}: ${looksLikeRateField(column) ? formatPercent(Number(row?.[column])) : formatNumber(row?.[column])}`),
      ];
      return `
        <g class="chart-hit" tabindex="0" focusable="true">
          <rect x="${previousX.toFixed(1)}" y="${top}" width="${Math.max(12, nextX - previousX).toFixed(1)}" height="${plotHeight}" fill="transparent"></rect>
          <line x1="${centerX.toFixed(1)}" y1="${top}" x2="${centerX.toFixed(1)}" y2="${top + plotHeight}" class="chart-hover-guide"></line>
          ${chartTooltipMulti({
            title: `${xColumn}: ${row?.[xColumn] ?? "-"}`,
            lines: tooltipLines,
            x: centerX - 90,
            y: top + 8,
            width,
          })}
        </g>
      `;
    })
    .join("");
  const barMarkup = displayRows
    .map((row, rowIndex) => {
      const centerX = left + groupWidth * rowIndex + groupWidth / 2;
      return barColumns
        .map((column, columnIndex) => {
          const value = Number(row?.[column]);
          if (!Number.isFinite(value)) return "";
          const x = centerX - ((barColumns.length * barWidth + (barColumns.length - 1) * gap) / 2) + columnIndex * (barWidth + gap);
          const valueY = chartScale(value, leftDomain.min, leftDomain.max, top + plotHeight, top);
          const y = Math.min(zeroY, valueY);
          const heightValue = Math.max(2, Math.abs(zeroY - valueY));
          return `<rect x="${x.toFixed(1)}" y="${y.toFixed(1)}" width="${barWidth.toFixed(1)}" height="${heightValue.toFixed(1)}" fill="${colors[columnIndex % colors.length]}" rx="5"></rect>`;
        })
        .join("");
    })
    .join("");
  const lineMarkup = lineColumns
    .map((column, lineIndex) => {
      const color = colors[(lineIndex + barColumns.length) % colors.length];
      const points = displayRows
        .map((row, index) => {
          const value = Number(row?.[column]);
          if (!Number.isFinite(value)) return null;
          return {
            x: left + groupWidth * index + groupWidth / 2,
            y: chartScale(value, rightDomain.min, rightDomain.max, top + plotHeight, top),
          };
        })
        .filter(Boolean);
      if (points.length <= 1) return "";
      return `
        <polyline points="${points.map((point) => `${point.x.toFixed(1)},${point.y.toFixed(1)}`).join(" ")}" class="line-path" style="stroke:${color}"></polyline>
        ${points.map((point) => `<circle cx="${point.x.toFixed(1)}" cy="${point.y.toFixed(1)}" r="4.5" class="line-dot" style="stroke:${color}"></circle>`).join("")}
      `;
    })
    .join("");
  const grid = leftTicks
    .map((tick) => {
      const y = chartScale(tick, leftDomain.min, leftDomain.max, top + plotHeight, top);
      return `
        <line x1="${left}" y1="${y.toFixed(1)}" x2="${left + plotWidth}" y2="${y.toFixed(1)}" class="grid-line"></line>
        <text x="${left - 10}" y="${(y + 4).toFixed(1)}" text-anchor="end" class="axis-label">${formatAxisNumber(tick)}</text>
      `;
    })
    .join("");
  const rightLabels = rightTicks
    .map((tick) => {
      const y = chartScale(tick, rightDomain.min, rightDomain.max, top + plotHeight, top);
      return `<text x="${left + plotWidth + 10}" y="${(y + 4).toFixed(1)}" class="axis-label">${looksLikeRateField(lineColumns[0]) ? formatPercent(Number(tick)) : formatAxisNumber(tick)}</text>`;
    })
    .join("");
  const xLabels = displayRows
    .map((row, index) => {
      const centerX = left + groupWidth * index + groupWidth / 2;
      return `<text x="${centerX.toFixed(1)}" y="${top + plotHeight + 26}" text-anchor="middle" class="axis-label">${escapeHtml(shortLabel(row?.[xColumn] ?? "-", 8))}</text>`;
    })
    .join("");
  const legendItems = [...barColumns, ...lineColumns]
    .map((column, index) => {
      const color = colors[index % colors.length];
      const y = top + 12 + index * 26;
      if (index < barColumns.length) {
        return `
          <g class="chart-legend-item">
            <rect x="${left + plotWidth + 18}" y="${(y - 10).toFixed(1)}" width="14" height="14" rx="4" fill="${color}"></rect>
            <text x="${left + plotWidth + 40}" y="${(y + 2).toFixed(1)}" class="chart-legend-label">${escapeHtml(shortLabel(column, 12))}</text>
          </g>
        `;
      }
      return `
        <g class="chart-legend-item">
          <line x1="${left + plotWidth + 18}" y1="${y.toFixed(1)}" x2="${left + plotWidth + 34}" y2="${y.toFixed(1)}" style="stroke:${color};stroke-width:1.8"></line>
          <circle cx="${left + plotWidth + 26}" cy="${y.toFixed(1)}" r="3.5" fill="#fff" style="stroke:${color};stroke-width:1.6"></circle>
          <text x="${left + plotWidth + 40}" y="${(y + 2).toFixed(1)}" class="chart-legend-label">${escapeHtml(shortLabel(column, 12))}</text>
        </g>
      `;
    })
    .join("");
  return `
    <div class="chart-title">${escapeHtml(chart?.title || "柱线组合图")}</div>
    <svg class="chart-svg" viewBox="0 0 ${width} ${height}" role="img">
      ${grid}
      ${rightLabels}
      <line x1="${left}" y1="${top}" x2="${left}" y2="${top + plotHeight}" class="axis-line"></line>
      <line x1="${left + plotWidth}" y1="${top}" x2="${left + plotWidth}" y2="${top + plotHeight}" class="axis-line"></line>
      <line x1="${left}" y1="${zeroY.toFixed(1)}" x2="${left + plotWidth}" y2="${zeroY.toFixed(1)}" class="axis-line"></line>
      <text x="${left + plotWidth / 2}" y="${height - 18}" text-anchor="middle" class="axis-title">${escapeHtml(xColumn)}</text>
      <text transform="translate(18 ${top + plotHeight / 2}) rotate(-90)" text-anchor="middle" class="axis-title">${escapeHtml(barColumns.join(" / "))}</text>
      <text x="${left + plotWidth}" y="${top - 10}" text-anchor="end" class="axis-title">${escapeHtml(lineColumns[0])}</text>
      ${xLabels}
      ${barMarkup}
      ${lineMarkup}
      ${legendItems}
      ${bandMarkup}
    </svg>
  `;
}

function renderStackedColumnChart(rows, chart, xColumn, fallbackColumns) {
  const width = 860;
  const height = 440;
  const left = 76;
  const right = 160;
  const top = 34;
  const bottom = 76;
  const plotWidth = width - left - right;
  const plotHeight = height - top - bottom;
  const stackColumns = resolveStackColumns(chart, rows, xColumn, fallbackColumns);
  if (stackColumns.length < 2) return renderChartImage(chart);
  const displayRows = rows.slice(0, 18);
  const totals = displayRows.map((row) => stackColumns.reduce((sum, column) => sum + Math.max(Number(row?.[column]) || 0, 0), 0));
  const domain = chartNumberDomain(totals.map((value) => ({ value })), true);
  const ticks = chartTicks(domain.min, domain.max, 5);
  const colors = ["#2563eb", "#0ea5e9", "#14b8a6", "#f59e0b", "#4f46e5", "#64748b"];
  const gap = 10;
  const barWidth = Math.max(20, (plotWidth - gap * (displayRows.length - 1)) / Math.max(displayRows.length, 1));
  const grid = ticks
    .map((tick) => {
      const y = chartScale(tick, domain.min, domain.max, top + plotHeight, top);
      return `
        <line x1="${left}" y1="${y.toFixed(1)}" x2="${left + plotWidth}" y2="${y.toFixed(1)}" class="grid-line"></line>
        <text x="${left - 10}" y="${(y + 4).toFixed(1)}" text-anchor="end" class="axis-label">${formatAxisNumber(tick)}</text>
      `;
    })
    .join("");
  const bars = displayRows
    .map((row, rowIndex) => {
      const x = left + rowIndex * (barWidth + gap);
      let cumulative = 0;
      const segments = stackColumns
        .map((column, columnIndex) => {
          const value = Math.max(Number(row?.[column]) || 0, 0);
          const segmentTop = cumulative + value;
          const y = chartScale(segmentTop, domain.min, domain.max, top + plotHeight, top);
          const baseY = chartScale(cumulative, domain.min, domain.max, top + plotHeight, top);
          cumulative = segmentTop;
          return `<rect x="${x.toFixed(1)}" y="${y.toFixed(1)}" width="${barWidth.toFixed(1)}" height="${Math.max(2, baseY - y).toFixed(1)}" fill="${colors[columnIndex % colors.length]}" rx="5"></rect>`;
        })
        .join("");
      const lines = stackColumns.map((column) => `${column}: ${formatNumber(row?.[column])}`);
      return `
        <g class="chart-hit" tabindex="0" focusable="true">
          ${segments}
          <text x="${(x + barWidth / 2).toFixed(1)}" y="${(top + plotHeight + 24).toFixed(1)}" text-anchor="middle" class="axis-label">${escapeHtml(shortLabel(row?.[xColumn] ?? "-", 8))}</text>
          ${chartTooltipMulti({ title: `${xColumn}: ${row?.[xColumn] ?? "-"}`, lines, x: x - 18, y: top + 8, width })}
        </g>
      `;
    })
    .join("");
  const legend = stackColumns
    .map((column, index) => `
      <g class="chart-legend-item">
        <rect x="${left + plotWidth + 24}" y="${(top + index * 26 - 10).toFixed(1)}" width="14" height="14" rx="4" fill="${colors[index % colors.length]}"></rect>
        <text x="${left + plotWidth + 46}" y="${(top + index * 26 + 2).toFixed(1)}" class="chart-legend-label">${escapeHtml(shortLabel(column, 12))}</text>
      </g>
    `)
    .join("");
  return `
    <div class="chart-title">${escapeHtml(chart?.title || "堆叠柱状图")}</div>
    <svg class="chart-svg" viewBox="0 0 ${width} ${height}" role="img">
      ${grid}
      <line x1="${left}" y1="${top}" x2="${left}" y2="${top + plotHeight}" class="axis-line"></line>
      <line x1="${left}" y1="${top + plotHeight}" x2="${left + plotWidth}" y2="${top + plotHeight}" class="axis-line"></line>
      ${bars}
      ${legend}
    </svg>
  `;
}

function renderStackedAreaChart(rows, chart, xColumn, fallbackColumns) {
  const width = 860;
  const height = 440;
  const left = 76;
  const right = 160;
  const top = 34;
  const bottom = 76;
  const plotWidth = width - left - right;
  const plotHeight = height - top - bottom;
  const stackColumns = resolveStackColumns(chart, rows, xColumn, fallbackColumns);
  if (stackColumns.length < 2) return renderChartImage(chart);
  const displayRows = rows.slice(0, 24);
  const totals = displayRows.map((row) => stackColumns.reduce((sum, column) => sum + Math.max(Number(row?.[column]) || 0, 0), 0));
  const domain = chartNumberDomain(totals.map((value) => ({ value })), true);
  const ticks = chartTicks(domain.min, domain.max, 5);
  const colors = ["#2563eb", "#0ea5e9", "#14b8a6", "#f59e0b", "#4f46e5", "#64748b"];
  const grid = ticks
    .map((tick) => {
      const y = chartScale(tick, domain.min, domain.max, top + plotHeight, top);
      return `
        <line x1="${left}" y1="${y.toFixed(1)}" x2="${left + plotWidth}" y2="${y.toFixed(1)}" class="grid-line"></line>
        <text x="${left - 10}" y="${(y + 4).toFixed(1)}" text-anchor="end" class="axis-label">${formatAxisNumber(tick)}</text>
      `;
    })
    .join("");
  const xPoints = displayRows.map((row, index) => ({
    x: left + (index / Math.max(displayRows.length - 1, 1)) * plotWidth,
    label: String(row?.[xColumn] ?? ""),
  }));
  const cumulative = new Array(displayRows.length).fill(0);
  const areas = stackColumns
    .map((column, seriesIndex) => {
      const upper = [];
      const lower = [];
      displayRows.forEach((row, index) => {
        const value = Math.max(Number(row?.[column]) || 0, 0);
        const topValue = cumulative[index] + value;
        upper.push(`${xPoints[index].x.toFixed(1)},${chartScale(topValue, domain.min, domain.max, top + plotHeight, top).toFixed(1)}`);
        lower.push(`${xPoints[index].x.toFixed(1)},${chartScale(cumulative[index], domain.min, domain.max, top + plotHeight, top).toFixed(1)}`);
        cumulative[index] = topValue;
      });
      return `<polygon points="${upper.concat(lower.reverse()).join(" ")}" fill="${colors[seriesIndex % colors.length]}" fill-opacity="0.72"></polygon>`;
    })
    .join("");
  const xLabels = xPoints
    .map((point, index) =>
      index % Math.max(1, Math.ceil(xPoints.length / 6)) === 0 || index === xPoints.length - 1
        ? `<text x="${point.x.toFixed(1)}" y="${(top + plotHeight + 24).toFixed(1)}" text-anchor="middle" class="axis-label">${escapeHtml(shortLabel(point.label, 8))}</text>`
        : "",
    )
    .join("");
  const hitBands = xPoints
    .map((point, index) => {
      const previousX = index === 0 ? left : (xPoints[index - 1].x + point.x) / 2;
      const nextX = index === xPoints.length - 1 ? left + plotWidth : (point.x + xPoints[index + 1].x) / 2;
      const lines = stackColumns.map((column) => `${column}: ${formatNumber(displayRows[index]?.[column])}`);
      return `
        <g class="chart-hit" tabindex="0" focusable="true">
          <rect x="${previousX.toFixed(1)}" y="${top}" width="${Math.max(12, nextX - previousX).toFixed(1)}" height="${plotHeight}" fill="transparent"></rect>
          <line x1="${point.x.toFixed(1)}" y1="${top}" x2="${point.x.toFixed(1)}" y2="${top + plotHeight}" class="chart-hover-guide"></line>
          ${chartTooltipMulti({ title: `${xColumn}: ${point.label}`, lines, x: point.x - 90, y: top + 8, width })}
        </g>
      `;
    })
    .join("");
  const legend = stackColumns
    .map((column, index) => `
      <g class="chart-legend-item">
        <rect x="${left + plotWidth + 24}" y="${(top + index * 26 - 10).toFixed(1)}" width="14" height="14" rx="4" fill="${colors[index % colors.length]}"></rect>
        <text x="${left + plotWidth + 46}" y="${(top + index * 26 + 2).toFixed(1)}" class="chart-legend-label">${escapeHtml(shortLabel(column, 12))}</text>
      </g>
    `)
    .join("");
  return `
    <div class="chart-title">${escapeHtml(chart?.title || "堆叠面积图")}</div>
    <svg class="chart-svg" viewBox="0 0 ${width} ${height}" role="img">
      ${grid}
      <line x1="${left}" y1="${top}" x2="${left}" y2="${top + plotHeight}" class="axis-line"></line>
      <line x1="${left}" y1="${top + plotHeight}" x2="${left + plotWidth}" y2="${top + plotHeight}" class="axis-line"></line>
      ${areas}
      ${xLabels}
      ${hitBands}
      ${legend}
    </svg>
  `;
}

function renderDualAxisLineChart(rows, chart, xColumn, fallbackColumns) {
  const width = 860;
  const height = 440;
  const left = 76;
  const right = 84;
  const top = 34;
  const bottom = 76;
  const plotWidth = width - left - right;
  const plotHeight = height - top - bottom;
  const series = Array.isArray(chart?.series) ? chart.series : [];
  const leftColumns = uniqueStrings(series.filter((item) => String(item?.axis || "left") === "left").map((item) => String(item?.y || ""))).filter(Boolean);
  const rightColumns = uniqueStrings(series.filter((item) => String(item?.axis || "") === "right").map((item) => String(item?.y || ""))).filter(Boolean);
  const fallbackNumeric = fallbackColumns.filter((column) => column !== xColumn && rows.some((row) => Number.isFinite(Number(row?.[column]))));
  const leftSeries = (leftColumns.length ? leftColumns : fallbackNumeric.slice(0, 1)).slice(0, 1);
  const rightSeries = (rightColumns.length ? rightColumns : fallbackNumeric.slice(1, 2)).slice(0, 1);
  if (!leftSeries.length || !rightSeries.length) return renderChartImage(chart);
  const displayRows = rows.slice(0, 24);
  const leftValues = displayRows.map((row) => Number(row?.[leftSeries[0]])).filter(Number.isFinite);
  const rightValues = displayRows.map((row) => Number(row?.[rightSeries[0]])).filter(Number.isFinite);
  const leftDomain = chartNumberDomain(leftValues.map((value) => ({ value })), true);
  const rightDomain = chartNumberDomain(rightValues.map((value) => ({ value })), true);
  const leftTicks = chartTicks(leftDomain.min, leftDomain.max, 5);
  const rightTicks = chartTicks(rightDomain.min, rightDomain.max, 5);
  const grid = leftTicks
    .map((tick) => {
      const y = chartScale(tick, leftDomain.min, leftDomain.max, top + plotHeight, top);
      return `
        <line x1="${left}" y1="${y.toFixed(1)}" x2="${left + plotWidth}" y2="${y.toFixed(1)}" class="grid-line"></line>
        <text x="${left - 10}" y="${(y + 4).toFixed(1)}" text-anchor="end" class="axis-label">${formatAxisNumber(tick)}</text>
      `;
    })
    .join("");
  const rightLabels = rightTicks
    .map((tick) => {
      const y = chartScale(tick, rightDomain.min, rightDomain.max, top + plotHeight, top);
      return `<text x="${left + plotWidth + 10}" y="${(y + 4).toFixed(1)}" class="axis-label">${formatAxisNumber(tick)}</text>`;
    })
    .join("");
  const lineMarkup = [leftSeries[0], rightSeries[0]]
    .map((column, index) => {
      const domain = index === 0 ? leftDomain : rightDomain;
      const color = index === 0 ? "#2563eb" : "#f59e0b";
      const points = displayRows.map((row, pointIndex) => ({
        x: left + (pointIndex / Math.max(displayRows.length - 1, 1)) * plotWidth,
        y: chartScale(Number(row?.[column]) || 0, domain.min, domain.max, top + plotHeight, top),
      }));
      return `
        <polyline points="${points.map((point) => `${point.x.toFixed(1)},${point.y.toFixed(1)}`).join(" ")}" class="line-path" style="stroke:${color}"></polyline>
        ${points.map((point) => `<circle cx="${point.x.toFixed(1)}" cy="${point.y.toFixed(1)}" r="4.5" class="line-dot" style="stroke:${color}"></circle>`).join("")}
      `;
    })
    .join("");
  const xLabels = displayRows
    .map((row, index) => {
      const x = left + (index / Math.max(displayRows.length - 1, 1)) * plotWidth;
      return index % Math.max(1, Math.ceil(displayRows.length / 6)) === 0 || index === displayRows.length - 1
        ? `<text x="${x.toFixed(1)}" y="${(top + plotHeight + 24).toFixed(1)}" text-anchor="middle" class="axis-label">${escapeHtml(shortLabel(row?.[xColumn] ?? "-", 8))}</text>`
        : "";
    })
    .join("");
  const hits = displayRows
    .map((row, index) => {
      const x = left + (index / Math.max(displayRows.length - 1, 1)) * plotWidth;
      const prevX = index === 0 ? left : left + ((index - 0.5) / Math.max(displayRows.length - 1, 1)) * plotWidth;
      const nextX = index === displayRows.length - 1 ? left + plotWidth : left + ((index + 0.5) / Math.max(displayRows.length - 1, 1)) * plotWidth;
      const lines = [`${leftSeries[0]}: ${formatNumber(row?.[leftSeries[0]])}`, `${rightSeries[0]}: ${formatNumber(row?.[rightSeries[0]])}`];
      return `
        <g class="chart-hit" tabindex="0" focusable="true">
          <rect x="${prevX.toFixed(1)}" y="${top}" width="${Math.max(12, nextX - prevX).toFixed(1)}" height="${plotHeight}" fill="transparent"></rect>
          <line x1="${x.toFixed(1)}" y1="${top}" x2="${x.toFixed(1)}" y2="${top + plotHeight}" class="chart-hover-guide"></line>
          ${chartTooltipMulti({ title: `${xColumn}: ${row?.[xColumn] ?? "-"}`, lines, x: x - 90, y: top + 8, width })}
        </g>
      `;
    })
    .join("");
  return `
    <div class="chart-title">${escapeHtml(chart?.title || "双轴折线图")}</div>
    <svg class="chart-svg" viewBox="0 0 ${width} ${height}" role="img">
      ${grid}
      ${rightLabels}
      <line x1="${left}" y1="${top}" x2="${left}" y2="${top + plotHeight}" class="axis-line"></line>
      <line x1="${left + plotWidth}" y1="${top}" x2="${left + plotWidth}" y2="${top + plotHeight}" class="axis-line"></line>
      <line x1="${left}" y1="${top + plotHeight}" x2="${left + plotWidth}" y2="${top + plotHeight}" class="axis-line"></line>
      ${lineMarkup}
      ${xLabels}
      ${hits}
    </svg>
  `;
}

function renderLineChart(seriesValues, chart) {
  const width = 820;
  const height = 450;
  const left = 112;
  const right = seriesValues.length > 1 ? 160 : 44;
  const top = 70;
  const bottom = 86;
  const plotWidth = width - left - right;
  const plotHeight = height - top - bottom;
  const displaySeries = seriesValues.slice(0, 8).map((series) => ({ ...series, points: series.points.slice(0, 30) }));
  const allPoints = displaySeries.flatMap((series) => series.points);
  const domain = chartNumberDomain(allPoints, displaySeries.length > 1);
  const ticks = chartTicks(domain.min, domain.max, 5);
  const { xName } = chartAxisMeta(chart);
  const yName = resolveLineYAxisName(chart, displaySeries);
  const colors = ["#2563eb", "#0ea5e9", "#14b8a6", "#f59e0b", "#4f46e5", "#64748b", "#22c55e", "#ef4444"];
  const plottedSeries = displaySeries.map((series, seriesIndex) => ({
    ...series,
    color: colors[seriesIndex % colors.length],
    points: series.points.map((item, index, list) => {
      const x = left + (index / Math.max(list.length - 1, 1)) * plotWidth;
      const y = chartScale(item.value, domain.min, domain.max, top + plotHeight, top);
      return { x, y, label: item.label, value: item.value };
    }),
  }));
  const grid = ticks
    .map((tick) => {
      const y = chartScale(tick, domain.min, domain.max, top + plotHeight, top);
      return `
        <line x1="${left}" y1="${y.toFixed(1)}" x2="${left + plotWidth}" y2="${y.toFixed(1)}" class="grid-line"></line>
        <text x="${left - 14}" y="${(y + 4).toFixed(1)}" text-anchor="end" class="axis-label">${formatAxisNumber(tick)}</text>
      `;
    })
    .join("");
  const xPoints = plottedSeries[0]?.points || [];
  const step = Math.max(1, Math.ceil(xPoints.length / 6));
  const xLabels = xPoints
    .map((point, index) =>
      index % step === 0 || index === xPoints.length - 1
        ? `<text x="${point.x.toFixed(1)}" y="${top + plotHeight + 32}" text-anchor="middle" class="axis-label">${escapeHtml(shortLabel(point.label, 8))}</text>`
        : "",
    )
    .join("");
  const seriesMarkup = plottedSeries
    .map((series) => {
      const path = series.points.map((point) => `${point.x.toFixed(1)},${point.y.toFixed(1)}`).join(" ");
      return `
        <polyline points="${path}" class="line-path" style="stroke:${series.color}"></polyline>
        ${series.points
          .map((point) => `<circle cx="${point.x.toFixed(1)}" cy="${point.y.toFixed(1)}" r="5" class="line-dot" style="stroke:${series.color}"></circle>`)
          .join("")}
      `;
    })
    .join("");
  const hitBands = xPoints
    .map((point, index) => {
      const previousX = index === 0 ? left : (xPoints[index - 1].x + point.x) / 2;
      const nextX = index === xPoints.length - 1 ? left + plotWidth : (point.x + xPoints[index + 1].x) / 2;
      const lines = plottedSeries
        .map((series) => {
          const matched = series.points[index];
          if (!matched) return "";
          return `${series.name}: ${looksLikeRateField(series.name) ? formatPercent(matched.value) : formatNumber(matched.value)}`;
        })
        .filter(Boolean);
      return `
        <g class="chart-hit" tabindex="0" focusable="true">
          <rect x="${previousX.toFixed(1)}" y="${top}" width="${Math.max(12, nextX - previousX).toFixed(1)}" height="${plotHeight}" fill="transparent"></rect>
          <line x1="${point.x.toFixed(1)}" y1="${top}" x2="${point.x.toFixed(1)}" y2="${top + plotHeight}" class="chart-hover-guide"></line>
          ${chartTooltipMulti({
            title: `${xName}: ${point.label}`,
            lines,
            x: point.x - 94,
            y: top + 8,
            width,
          })}
        </g>
      `;
    })
    .join("");
  const legend = plottedSeries.length > 1
    ? plottedSeries
        .map((series, index) => {
          const y = top + 10 + index * 28;
          return `
            <g class="chart-legend-item">
              <line x1="${left + plotWidth + 24}" y1="${y}" x2="${left + plotWidth + 42}" y2="${y}" style="stroke:${series.color};stroke-width:1.8"></line>
              <circle cx="${left + plotWidth + 33}" cy="${y}" r="3.5" fill="#fff" style="stroke:${series.color};stroke-width:1.6"></circle>
              <text x="${left + plotWidth + 50}" y="${y + 4}" class="chart-legend-label">${escapeHtml(shortLabel(series.name, 10))}</text>
            </g>
          `;
        })
        .join("")
    : "";
  return `
    <div class="chart-title">${escapeHtml(chart?.title || "趋势图")}</div>
    <svg class="chart-svg" viewBox="0 0 ${width} ${height}" role="img">
      ${grid}
      <line x1="${left}" y1="${top}" x2="${left}" y2="${top + plotHeight}" class="axis-line"></line>
      <line x1="${left}" y1="${top + plotHeight}" x2="${left + plotWidth}" y2="${top + plotHeight}" class="axis-line"></line>
      <text x="${left + plotWidth / 2}" y="${height - 20}" text-anchor="middle" class="axis-title">${escapeHtml(xName)}</text>
      <text x="${left}" y="${top - 34}" text-anchor="start" class="axis-title">${escapeHtml(yName)}</text>
      ${xLabels}
      ${seriesMarkup}
      ${hitBands}
      ${legend}
    </svg>
  `;
}

function resolveLineYAxisName(chart, displaySeries) {
  const text = `${chart?.title || ""} ${chart?.reason || ""}`.toLowerCase();
  if (/分销金额|金额|销售额|收入|gmv|revenue|amount/.test(text)) return "分销金额";
  if (/占比|比例|率|percent|percentage|rate|ratio/.test(text)) return "比例";
  if (displaySeries.length > 1) return "数值";
  return displaySeries[0]?.name || chartAxisMeta(chart).yName;
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
  const activateFromEvent = (event) => {
    const hit = event.target?.closest?.(".chart-hit");
    if (!hit || !panel.contains(hit)) return;
    clearActive(hit);
    hit.classList.add("is-active");
  };
  panel.addEventListener("pointerover", activateFromEvent);
  panel.addEventListener("click", activateFromEvent);
  panel.addEventListener("focusin", activateFromEvent);
  panel.addEventListener("pointerleave", () => clearActive());
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
  const tooltipWidth = 172;
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

function chartTooltipMulti({ title, lines, x, y, width }) {
  const safeLines = Array.isArray(lines) ? lines.filter(Boolean).slice(0, 3) : [];
  const tooltipWidth = 188;
  const tooltipHeight = 34 + safeLines.length * 18;
  const safeX = Math.min(Math.max(4, x), width - tooltipWidth - 4);
  const safeY = Math.max(4, y);
  return `
    <g class="chart-hover-card" transform="translate(${safeX.toFixed(1)} ${safeY.toFixed(1)})">
      <rect class="chart-tooltip-bg" width="${tooltipWidth}" height="${tooltipHeight}" rx="8"></rect>
      <text x="10" y="20" class="chart-tooltip-label">${escapeHtml(title)}</text>
      ${safeLines.map((line, index) => `<text x="10" y="${38 + index * 18}" class="chart-tooltip-value">${escapeHtml(line)}</text>`).join("")}
    </g>
  `;
}

function looksLikeRateField(value) {
  return /rate|ratio|share|percent|pct|%|达成率|完成率|占比|比例/i.test(String(value || ""));
}

function formatAxisNumber(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return String(value ?? "-");
  return number.toLocaleString("zh-CN", { maximumFractionDigits: Math.abs(number) >= 1000 ? 0 : 1 });
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

function renderInsight(insight, result = {}) {
  const hasInsightPayload = Boolean(insight && typeof insight === "object");
  const suggestions = resolveInsightAdviceCandidates(insight);
  const findings = [...(insight?.anomaly_findings || []), ...(insight?.volatility_findings || [])]
    .map((item) => item?.message)
    .filter(isUserFacingInsightText);
  const caveats = (insight?.caveats || []).filter(isUserFacingInsightText);
  const nextQuestions = hasInsightPayload ? resolveInsightNextQuestions(insight?.next_questions || [], result, insight?.next_actions || []).slice(0, 2) : [];
  const summary = cleanInsightSummary(insight?.summary || "") || buildContextualInsightSummary(result);
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

function resolveInsightAdviceCandidates(insight = {}) {
  const directSuggestions = [insight?.next_step, ...(Array.isArray(insight?.suggestions) ? insight.suggestions : [])].filter(isUserFacingInsightText);
  const businessSuggestions = (Array.isArray(insight?.business_suggestions) ? insight.business_suggestions : []).filter(isUserFacingInsightText);
  return uniqueStrings([...directSuggestions, ...businessSuggestions]);
}

function pickInsightAdvice(suggestions, findings, caveats) {
  const candidates = [...suggestions, ...findings, ...caveats];
  return candidates.find(isUserFacingInsightText) || "";
}

function resolveInsightNextQuestions(nextQuestions, result = {}, nextActions = []) {
  const actionQuestions = resolveInsightActionQuestions(nextActions);
  const cleaned = uniqueStrings((Array.isArray(nextQuestions) ? nextQuestions : []).filter(isUserFacingInsightText));
  if (actionQuestions.length) return uniqueStrings([...actionQuestions, ...cleaned]);
  const contextual = buildContextualNextQuestions(result);
  if (!cleaned.length) return contextual;
  if (isGenericNextQuestionSet(cleaned)) return contextual;
  return uniqueStrings([...cleaned, ...contextual]);
}

function resolveInsightActionQuestions(nextActions = []) {
  return uniqueStrings(
    (Array.isArray(nextActions) ? nextActions : [])
      .filter((action) => action && typeof action === "object" && action.status !== "unsupported")
      .map((action) => String(action.question || "").trim())
      .filter(isUserFacingInsightText),
  );
}

function isGenericNextQuestionSet(nextQuestions) {
  const normalized = nextQuestions.map((item) => String(item || "").replace(/[?？。；;\s]/g, ""));
  const genericPatterns = [
    "异常值来自哪些明细记录",
    "这个结果按时间趋势是否稳定",
    "是否需要对Top结果继续下钻",
    "把这个结论按关键维度下钻",
    "检查是否存在异常值或质量问题影响结果",
    "生成可复核的结果表和图表",
    "是否需要按维度展开明细",
  ];
  return Boolean(normalized.length && normalized.every((item) => genericPatterns.some((pattern) => item.includes(pattern))));
}

function buildContextualNextQuestions(result = {}) {
  const rows = resultRowsForSuggestions(result);
  const columns = resultColumnsForSuggestions(result, rows);
  const logic = result?.logic_form || {};
  const parameters = logic.parameters && typeof logic.parameters === "object" ? logic.parameters : {};
  const timeWindow = logic.time_window && typeof logic.time_window === "object" ? logic.time_window : {};
  const question = String(result?.question || "");
  const operation = [logic.operation, logic.task_type, result?.debug?.operation, result?.answer_type].filter(Boolean).join(" ").toLowerCase();
  const metric = firstText(logic.metric, parameters.metric, result?.chart?.y, firstNumericColumn(rows, columns), "核心指标");
  const dimension = firstText(logic.group_by, parameters.dimension, parameters.group_by, chartDimension(result?.chart), firstDimensionColumn(rows, columns), "关键维度");
  const timeColumn = firstText(firstTimeColumn(columns), parameters.time_column, timeWindow.column, chartTimeColumn(result?.chart), "时间");
  const hasTimeColumn = timeColumn !== "时间";
  const text = `${question} ${operation}`.toLowerCase().replace(/\s+/g, "");
  let candidates;
  if (looksLikeCleaningOrQuality(text)) {
    candidates = [
      `列出影响${metric}的缺失、重复和异常记录？`,
      `模拟清洗前后${metric}会差多少？`,
      `按${dimension}看哪些分组受质量问题影响最大？`,
    ];
  } else if (looksLikeShareOrRateQuestion(text)) {
    candidates = [
      `按${dimension}拆分这个占比，找出贡献最大的分组？`,
      `看这个比例在${timeColumn}上是否稳定？`,
      "检查分子、分母口径是否有过滤条件或缺失值影响？",
    ];
  } else if (looksLikeTrendQuestion(text)) {
    candidates = [
      `把${metric}的峰值、低点和最大波动期标出来？`,
      `按${dimension}拆分同一趋势，看看是谁拉动变化？`,
      `检查最近一期${timeColumn}是否完整、是否影响趋势判断？`,
    ];
  } else if (looksLikeRankingQuestion(text)) {
    candidates = [
      `比较 Top 结果之间的${metric}差距有多大？`,
      hasTimeColumn ? `把排名靠前的${dimension}按${timeColumn}继续下钻？` : `把排名靠前的${dimension}按其他维度继续下钻？`,
      "看低排名对象是否受缺失值、异常值或样本量影响？",
    ];
  } else {
    candidates = rows.length
      ? [
          `按${dimension}继续拆解${metric}的构成和集中度？`,
          `按${timeColumn}看${metric}的趋势和波动？`,
          `检查${metric}是否存在异常值或质量问题影响结论？`,
        ]
      : [`补充${metric}、${dimension}或${timeColumn}后重新计算？`, "需要先确认用哪张表和哪些字段作为口径？"];
  }
  return uniqueStrings(candidates.filter(isUserFacingInsightText));
}

function buildContextualInsightSummary(result = {}) {
  const rows = resultRowsForSuggestions(result);
  if (!rows.length) return "";
  const columns = resultColumnsForSuggestions(result, rows);
  const logic = result?.logic_form || {};
  const parameters = logic.parameters && typeof logic.parameters === "object" ? logic.parameters : {};
  const question = String(result?.question || "");
  const operation = [logic.operation, logic.task_type, result?.debug?.operation, result?.answer_type].filter(Boolean).join(" ").toLowerCase();
  const metric = firstText(logic.metric, parameters.metric, result?.chart?.y, firstNumericColumn(rows, columns), "");
  const dimension = firstText(logic.group_by, parameters.dimension, parameters.group_by, chartDimension(result?.chart), firstDimensionColumn(rows, columns), "");
  const firstRow = rows[0] || {};
  if (looksLikeRankingQuestion(`${question} ${operation}`.toLowerCase()) && metric && dimension && firstRow[dimension] !== undefined && firstRow[metric] !== undefined) {
    return `排名结果里第 1 位是 ${formatInsightValue(firstRow[dimension])}，${metric} 为 ${formatInsightValue(firstRow[metric])}。`;
  }
  return "";
}

function formatInsightValue(value) {
  const number = Number(value);
  if (value !== null && value !== "" && Number.isFinite(number)) {
    return Math.abs(number) >= 1000 ? number.toLocaleString("zh-CN", { maximumFractionDigits: 2 }) : String(Number(number.toFixed(2)));
  }
  return String(value ?? "-");
}

function resultRowsForSuggestions(result = {}) {
  const rows = result?.result?.rows;
  if (Array.isArray(rows)) return rowsWithoutContinuationPrompts(rows).filter((row) => row && typeof row === "object");
  const chartData = result?.chart?.data;
  if (Array.isArray(chartData)) return chartData.filter((row) => row && typeof row === "object");
  return [];
}

function resultColumnsForSuggestions(result = {}, rows = []) {
  const columns = Array.isArray(result?.result?.columns) ? result.result.columns.map(String).filter(Boolean) : [];
  if (columns.length) return columns;
  if (rows[0]) return Object.keys(rows[0]);
  return [result?.chart?.x, result?.chart?.y].map((item) => String(item || "").trim()).filter(Boolean);
}

function firstText(...values) {
  for (const value of values) {
    const text = String(value || "").trim();
    if (text) return text;
  }
  return "";
}

function firstNumericColumn(rows, columns) {
  return columns.find((column) => rows.some((row) => Number.isFinite(Number(row?.[column])))) || "";
}

function firstDimensionColumn(rows, columns) {
  const numeric = new Set(columns.filter((column) => rows.some((row) => Number.isFinite(Number(row?.[column])))));
  const timeColumn = firstTimeColumn(columns);
  return columns.find((column) => column !== timeColumn && !numeric.has(column)) || "";
}

function firstTimeColumn(columns) {
  return columns.find((column) => /date|day|month|year|week|time|日期|时间|月份|年份|周/i.test(column)) || "";
}

function chartDimension(chart = {}) {
  const x = String(chart?.x || "").trim();
  return x && !firstTimeColumn([x]) ? x : "";
}

function chartTimeColumn(chart = {}) {
  const x = String(chart?.x || "").trim();
  return x && firstTimeColumn([x]) ? x : "";
}

function looksLikeTrendQuestion(text) {
  return /trend|mom|yoy|趋势|波动|环比|同比|增长|下降/.test(text);
}

function looksLikeRankingQuestion(text) {
  return /ranking|topn|top|rank|排名|最高|最低|最大|最小|第一|前/.test(text);
}

function looksLikeShareOrRateQuestion(text) {
  return /percent|percentage|rate|ratio|share|占比|比例|率/.test(text);
}

function looksLikeCleaningOrQuality(text) {
  return /clean|quality|缺失|重复|异常|离群|质量|清洗|填充|删除/.test(text);
}

function renderInsightBody(summary, advice, nextQuestions) {
  const paragraphs = [];
  if (summary) paragraphs.push(escapeHtml(summary));
  if (advice) {
    const parsed = parseInsightText(advice);
    const action = isActionableInsightAdvice(parsed.action) ? parsed.action : "";
    const fallback = isDistinctInsightText(parsed.observation, summary) ? parsed.observation : "";
    const rawAdvice = isActionableInsightAdvice(advice) ? advice : "";
    const headline = action || fallback || rawAdvice;
    if (isDistinctInsightText(headline, summary)) paragraphs.push(`<strong>下一步：</strong>${escapeHtml(headline)}`);
  }
  if (nextQuestions.length) {
    paragraphs.push(`<strong>可继续问：</strong>${nextQuestions.map((question) => escapeHtml(question)).join("；")}`);
  }
  return paragraphs.map((paragraph) => `<p>${paragraph}</p>`).join("");
}

function isDistinctInsightText(text, summary = "") {
  const value = String(text || "").trim();
  if (!isUserFacingInsightText(value)) return false;
  return normalizeInsightText(value) !== normalizeInsightText(summary);
}

function normalizeInsightText(text) {
  return String(text || "").replace(/[，。；;,.!?！？\s]/g, "").trim();
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
  updateRunActionButtons(el.resultMessage, { mode: "starting" });
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
      setApiStatus("idle", "实时过程重连中");
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
  const specificSummary = liveActivitySummaryFromEvent(event, type, status);
  return {
    eventId: event.event_id || `${type}_${state.activityEvents.length}`,
    title: titleByType[type],
    summary: specificSummary || summaryByType[type] || cleanActivityText(event.summary) || "正在处理。",
    status,
  };
}

function liveActivitySummaryFromEvent(event, type, status) {
  const payload = event.payload || {};
  const role = String(event.role || payload.role || "");
  const result = payload.result?.output_payload || payload.result || {};
  const before = payload.state_before || {};
  const after = payload.state_after || payload.state_after_correction || {};
  const question = cleanActivityText(payload.question || before.question || "");
  const dataset = cleanActivityText(payload.dataset_id || before.dataset_id || after.dataset_id || "");
  if (type === "message_requested") {
    return question ? `收到问题“${question}”，正在判断它是普通对话、数据概览，还是需要读取数据后计算。` : "";
  }
  if (type === "analysis_requested") {
    return dataset ? `已锁定数据集 ${dataset}，开始读取表结构、字段名和样例值，避免拿错文件回答。` : "开始读取上传数据的表结构、字段名和样例值，准备选择正确的数据路径。";
  }
  if (type === "workflow_started") {
    return "后端分析流程已开始：先理解问题和数据，再计算、校验，最后组织成用户可读的回答。";
  }
  if (type === "agent_started") {
    return activityRoleStartSummary(role);
  }
  if (type === "agent_completed") {
    return activityRoleCompletionSummary(role, result, before, after);
  }
  if (type === "agent_failed") {
    return `${monitorRoleName(role)}遇到问题，正在保留可读错误并避免把不可靠结果直接当答案。`;
  }
  if (type === "workflow_completed") {
    return "计算、校验和回答组装已经完成，正在把最终结果同步到聊天页面。";
  }
  if (type === "response_ready") {
    const answer = cleanActivityText(payload.response?.answer || payload.answer || "");
    return answer ? `最终回答已生成：${answer}` : "最终回答已生成，正在展示主答案、图表和处理过程。";
  }
  if (type === "activity_trace_delta" && event.payload?.node) {
    const node = normalizeActivityNode(event.payload.node);
    return activityNodePlainSummary(node) || "";
  }
  if (status === "failed") return cleanActivityText(event.summary) || "当前步骤失败，正在返回可读错误。";
  return "";
}

function activityRoleStartSummary(role) {
  const labels = {
    planner: "计划节点开始把问题拆成分析口径：确认要用哪些表、看哪个指标、按什么维度或时间范围比较。",
    data_engineer: "数据理解节点开始检查上传文件：看表、字段、样例值和数据质量，给后续计算做准备。",
    pandas_executor: "Pandas 计算节点开始按计划执行主计算，先产出可用于回答的结构化结果。",
    sql_executor: "SQL 复算节点开始判断是否能用只读 SQL 交叉核对，不能支持时会说明跳过原因。",
    verifier: "校验节点开始核对结果是否成功、口径是否一致，避免错误结果直接进入回答。",
    correction: "修正节点开始判断是否需要有边界地调整口径并重跑计算。",
    insight: "洞察节点开始把已验证结果整理成普通用户能读懂的业务结论。",
    visualization: "图表节点开始判断结果是否适合画图，并选择横轴、纵轴和图表类型。",
    response_builder: "回答组装节点开始把结果、图表、来源和提示整理成最终页面回答。",
  };
  return labels[role] || `${monitorRoleName(role)}开始处理当前步骤。`;
}

function activityRoleCompletionSummary(role, result = {}, before = {}, after = {}) {
  if (role === "planner") {
    const logic = result.logic_form || after.logic_form || {};
    const tables = normalizeStringList(logic.source_tables || after.source_tables);
    const operation = activityOperationLabel(logic.operation || after.operation);
    return `计划节点已确定分析口径：${operation}${tables.length ? `，使用 ${tables.join("、")}` : ""}，下一步交给计算节点。`;
  }
  if (role === "data_engineer") {
    const tables = activityTableNames(result.tables || after.source_tables || before.source_tables);
    return tables.length ? `数据理解节点已看完可用表和字段：重点使用 ${tables.slice(0, 3).join("、")}，并把字段画像交给后续节点。` : "数据理解节点已完成表结构和字段画像检查，后续节点会按这些信息选表和匹配字段。";
  }
  if (role === "pandas_executor") {
    return activityExecutionSummary("Pandas", result || after.pandas || {});
  }
  if (role === "sql_executor") {
    return activityExecutionSummary("SQL", result || after.sql || {});
  }
  if (role === "verifier") {
    const verification = result.verification || after.verification || {};
    if (verification.passed === false) return "校验节点发现结果还不能直接使用，正在把问题交给修正或错误处理。";
    return "校验节点已确认计算结果可以用于回答，并检查了执行状态和一致性。";
  }
  if (role === "correction") {
    return result.needs_correction ? "修正节点已给出调整方向，准备让执行节点按新口径重算。" : "修正节点确认本次不需要重跑，流程可以继续整理结论。";
  }
  if (role === "insight") {
    const summary = cleanActivityText(result.insight?.summary || result.summary || after.insight?.summary || "");
    return summary ? `洞察节点已提炼业务结论：${summary}` : "洞察节点已把验证后的结果整理成业务结论、建议和限制说明。";
  }
  if (role === "visualization") {
    const chart = result.chart || after.chart || {};
    return chart.chart_type ? `图表节点已选择 ${chart.chart_type} 展示，并确认要使用的横轴和指标。` : "图表节点已判断本次结果是否适合画图，并把展示方式交给前端。";
  }
  if (role === "response_builder") {
    return "回答组装节点已把主答案、图表、来源和处理过程整理成页面可展示的结果。";
  }
  return cleanActivityText(result.summary || "");
}

function activityExecutionSummary(label, result = {}) {
  if (result.skipped) {
    const reason = cleanActivityText(result.reason || "");
    return `${label} 路径已跳过${reason ? `：${reason}` : ""}，不会拿不适合的计算结果回答。`;
  }
  if (result.success === false) return `${label} 计算失败，后续会返回可读错误或触发修正。`;
  const value = activityReadableValue(result.value ?? result.answer);
  return value ? `${label} 已按计划完成计算，得到结果摘要：${value}，接下来进入校验。` : `${label} 已按计划完成计算，结构化结果会交给校验节点。`;
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
  cancelActivityDrawerClose();
  state.drawerResult = result || state.latestActivityResult || {};
  state.drawerTriggerSummary = triggerSummary || null;
  state.activityDrawerAutoScroll = true;
  el.activityDrawer?.classList.remove("hidden");
  el.activityBackdrop?.classList.remove("hidden");
  requestAnimationFrame(() => {
    el.activityDrawer?.classList.add("is-active");
    el.activityBackdrop?.classList.add("is-active");
  });
  el.activityDrawer?.setAttribute("aria-hidden", "false");
  document.body.classList.add("activity-drawer-open");
  updateThinkingSummaryExpanded(true);
  renderActivityDrawer(state.drawerResult, { scrollToLatest: true });
}

function closeActivityDrawer() {
  cancelActivityDrawerClose();
  el.activityDrawer?.classList.remove("is-active");
  el.activityBackdrop?.classList.remove("is-active");
  el.activityDrawer?.setAttribute("aria-hidden", "true");
  document.body.classList.remove("activity-drawer-open");
  updateThinkingSummaryExpanded(false);
  state.drawerTriggerSummary = null;
  state.activityDrawerAutoScroll = true;
  state.activityDrawerCloseTimer = window.setTimeout(() => {
    el.activityDrawer?.classList.add("hidden");
    el.activityBackdrop?.classList.add("hidden");
    state.activityDrawerCloseTimer = null;
  }, 240);
}

function cancelActivityDrawerClose() {
  if (state.activityDrawerCloseTimer) {
    clearTimeout(state.activityDrawerCloseTimer);
    state.activityDrawerCloseTimer = null;
  }
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

function renderActivityDrawer(result = {}, options = {}) {
  if (!el.activityDrawerList) return;
  const shouldScrollToLatest =
    Boolean(options.scrollToLatest) || (isActivityDrawerVisible() && state.activityDrawerAutoScroll && isActivityDrawerNearLatest());
  const sections = buildActivityDrawerSections(result);
  const trace = sections.flatMap((section) => section.nodes);
  if (el.activityDrawerTitle) el.activityDrawerTitle.textContent = "思考与执行链路";
  if (el.activityDrawerSummary) el.activityDrawerSummary.textContent = drawerSummary(result, trace);
  if (!sections.length) {
    el.activityDrawerList.innerHTML = `<li class="activity-drawer-empty">暂无活动。</li>`;
    if (shouldScrollToLatest) scrollActivityDrawerToLatest();
    return;
  }
  el.activityDrawerList.innerHTML = sections.map(renderActivityDrawerSection).join("");
  if (shouldScrollToLatest) scrollActivityDrawerToLatest();
}

function isActivityDrawerVisible() {
  return Boolean(el.activityDrawer && !el.activityDrawer.classList.contains("hidden"));
}

function isActivityDrawerNearLatest() {
  if (!el.activityDrawerList) return true;
  const remaining = el.activityDrawerList.scrollHeight - el.activityDrawerList.clientHeight - el.activityDrawerList.scrollTop;
  return remaining <= 96;
}

function scrollActivityDrawerToLatest() {
  if (!el.activityDrawerList || !isActivityDrawerVisible()) return;
  if (state.activityDrawerScrollFrame) {
    cancelAnimationFrame(state.activityDrawerScrollFrame);
    state.activityDrawerScrollFrame = 0;
  }
  if (state.activityDrawerScrollTimeout) {
    clearTimeout(state.activityDrawerScrollTimeout);
    state.activityDrawerScrollTimeout = null;
  }
  const scrollToLatestNode = (behavior = "auto") => {
    if (!el.activityDrawerList || !isActivityDrawerVisible()) return;
    const sectionLists = el.activityDrawerList.querySelectorAll(".activity-section-list");
    const latestList = sectionLists.length ? sectionLists[sectionLists.length - 1] : null;
    const latestNode = latestList?.lastElementChild;
    if (latestNode instanceof HTMLElement) {
      latestNode.scrollIntoView({ block: "end", behavior });
      const listRect = el.activityDrawerList.getBoundingClientRect();
      const nodeRect = latestNode.getBoundingClientRect();
      const delta = nodeRect.bottom - listRect.bottom;
      if (Math.abs(delta) > 1) {
        el.activityDrawerList.scrollTop += delta;
      }
    } else {
      el.activityDrawerList.scrollTop = el.activityDrawerList.scrollHeight;
    }
    state.activityDrawerAutoScroll = true;
  };
  state.activityDrawerScrollFrame = requestAnimationFrame(() => {
    state.activityDrawerScrollFrame = requestAnimationFrame(() => {
      scrollToLatestNode();
      state.activityDrawerScrollFrame = 0;
    });
  });
  state.activityDrawerScrollTimeout = window.setTimeout(() => {
    scrollToLatestNode();
    state.activityDrawerScrollTimeout = null;
  }, 180);
}

function handleActivityDrawerScroll() {
  if (!isActivityDrawerVisible()) return;
  state.activityDrawerAutoScroll = isActivityDrawerNearLatest();
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

function renderActivityDrawerNode(node, index = 0, nodes = []) {
  const actions = normalizeStringList(node.actions);
  const toolCalls = Array.isArray(node.tool_calls) ? node.tool_calls : [];
  const artifacts = normalizeActivityArtifacts(node.artifacts);
  const digest = activityNodeDigest(node, index, nodes);
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
        ${renderActivityNodeDigest(digest)}
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
        ${nodes.map((node, index) => renderActivityDrawerNode(node, index, nodes)).join("")}
      </ol>
    </li>
  `;
}

function renderActivityNodeDigest(digest) {
  if (!digest || !digest.hasContent) return "";
  return `
    <div class="activity-node-transfer" aria-label="节点流转">
      <span>上游：${escapeHtml(digest.upstream)}</span>
      <span>当前：${escapeHtml(digest.current)}</span>
      <span>下游：${escapeHtml(digest.downstream)}</span>
    </div>
    <div class="activity-node-columns">
      ${renderActivityNodeBox("收到什么（输入）", digest.received)}
      ${renderActivityNodeBox("干了什么（处理）", digest.did)}
      ${renderActivityNodeBox("发出什么（输出）", digest.sent)}
    </div>
    ${digest.note ? `<p class="activity-node-note">${escapeHtml(digest.note)}</p>` : ""}
  `;
}

function renderActivityNodeBox(title, lines) {
  const items = normalizeStringList(lines).slice(0, 5);
  return `
    <section class="activity-node-box">
      <h4>${escapeHtml(title)}</h4>
      ${
        items.length
          ? `<ul>${items.map((line) => `<li>${escapeHtml(line)}</li>`).join("")}</ul>`
          : `<p>没有新的可读信息。</p>`
      }
    </section>
  `;
}

function activityNodeDigest(node, index, nodes) {
  const role = String(node.role || "");
  const supportedRoles = new Set(["planner", "data_engineer", "pandas_executor", "sql_executor", "verifier", "correction", "insight", "visualization", "response_builder", "single_agent"]);
  if (!supportedRoles.has(role)) {
    return { hasContent: false };
  }
  const inputs = node.inputs_summary || {};
  const outputs = node.outputs_summary || {};
  const actions = normalizeStringList(node.actions);
  const upstream = index === 0 ? "用户问题 / 上传数据" : activityNodeDisplayName(nodes[index - 1]);
  const downstream = index === nodes.length - 1 ? "最终页面 / API" : activityNodeDisplayName(nodes[index + 1]);
  const base = {
    upstream,
    current: activityNodeDisplayName(node),
    downstream,
    received: activityInputLines(inputs),
    did: [activityNodePlainSummary(node), ...actions.slice(0, 3)],
    sent: activityOutputLines(outputs),
    note: "",
  };

  if (role === "planner") {
    const tables = normalizeStringList(outputs.source_tables);
    const joinLine = activityJoinPlanLine(outputs.join_plan);
    base.received.push("用户问题、表结构、字段名、样例值和当前执行模式。");
    base.did = [
      outputs.operation ? `判断分析类型：${activityOperationLabel(outputs.operation)}` : activityNodePlainSummary(node),
      tables.length ? `选择要用的数据表：${tables.join("、")}` : "",
      joinLine || "把指标、维度和候选范围拆成后续节点能执行的口径。",
    ];
    base.sent = [
      outputs.operation ? `分析口径：${activityOperationLabel(outputs.operation)}` : "",
      tables.length ? `交给执行节点的数据表：${tables.join("、")}` : "",
      joinLine,
    ];
    base.note = "计划节点决定后面按什么口径计算，但不直接产出最终答案。";
  } else if (role === "data_engineer") {
    const tables = activityTableNames(outputs.source_tables);
    base.received.push("上传文件、表名、字段类型、样例值和数据质量摘要。");
    base.did = [tables.length ? `检查可用表：${tables.join("、")}` : activityNodePlainSummary(node), activityQualityLine(outputs.quality)];
    base.sent = [tables.length ? `可用数据表：${tables.join("、")}` : "", activityQualityLine(outputs.quality) || "把数据画像交给计划和计算节点。"];
    base.note = "数据理解节点不回答问题，只说明数据长什么样、哪些字段能用。";
  } else if (role === "pandas_executor" || role === "sql_executor") {
    const label = role === "pandas_executor" ? "Pandas" : "SQL";
    base.received.push("计划节点给出的表、指标、维度、筛选条件和排序方式。");
    base.did = [
      outputs.skipped ? `${label} 不适合本题或当前模式，已跳过。` : `用 ${label} 执行受控计算。`,
      outputs.reason ? `原因：${cleanActivityText(outputs.reason)}` : "",
      activityReadableValue(outputs.value ?? outputs.answer) ? `结果摘要：${activityReadableValue(outputs.value ?? outputs.answer)}` : "",
    ];
    base.sent = [
      outputs.skipped ? `${label} 状态：跳过` : outputs.success === false ? `${label} 状态：失败` : `${label} 状态：完成`,
      activityReadableValue(outputs.value ?? outputs.answer) ? `计算结果：${activityReadableValue(outputs.value ?? outputs.answer)}` : "",
    ];
    base.note = `${label} 节点只负责按计划计算，不单独决定业务结论。`;
  } else if (role === "verifier") {
    base.received = [
      inputs.pandas ? `Pandas 结果：${inputs.pandas}` : "",
      inputs.sql ? `SQL 结果：${inputs.sql}` : "",
      "计划口径和执行结果。",
    ];
    base.did = [
      outputs.passed === false ? "检查到结果还不能直接使用。" : "检查计算是否成功、是否一致、是否符合问题口径。",
      outputs.pandas_sql_consistent !== undefined ? `Pandas/SQL 是否一致：${outputs.pandas_sql_consistent ? "一致" : "不一致"}` : "",
    ];
    base.sent = [
      outputs.passed === false ? "校验结论：需要修正或提示错误。" : "校验结论：可以进入最终回答。",
      Array.isArray(outputs.issues) && outputs.issues.length ? `问题：${outputs.issues.slice(0, 2).join("；")}` : "",
    ];
    base.note = "校验节点是防止错口径、错结果进入最终回答的关口。";
  } else if (role === "correction") {
    base.received.push("校验节点发现的问题和上一轮计划。");
    base.did = [outputs.action ? `修正动作：${cleanActivityText(outputs.action)}` : activityNodePlainSummary(node), outputs.reasoning_summary || outputs.summary || ""];
    base.sent = [outputs.correction_attempts ? `修正尝试：${activityReadableValue(outputs.correction_attempts)}` : "", "决定是否让执行节点按新口径重跑。"];
    base.note = "修正节点只做有边界的口径调整，不访问标准答案。";
  } else if (role === "insight") {
    base.received.push("已经通过校验的结果和图表信息。");
    base.did = [outputs.summary ? `提炼结论：${cleanActivityText(outputs.summary)}` : activityNodePlainSummary(node)];
    base.sent = [outputs.summary ? "业务结论已交给最终回答节点。" : "", Array.isArray(outputs.suggestions) && outputs.suggestions.length ? `建议：${outputs.suggestions.slice(0, 2).join("；")}` : ""];
    base.note = "洞察节点只解释已验证结果，不重新计算。";
  } else if (role === "visualization") {
    base.received.push("可展示的结果数据、指标字段和维度字段。");
    base.did = [outputs.chart_type ? `选择图表：${outputs.chart_type}` : activityNodePlainSummary(node), outputs.title ? `图表标题：${cleanActivityText(outputs.title)}` : ""];
    base.sent = [outputs.chart_type ? `图表配置：${outputs.chart_type}` : "没有生成图表配置。", outputs.reason || outputs.fallback_reason || ""];
    base.note = "图表节点输出展示配置，前端负责真正渲染。";
  } else if (role === "response_builder") {
    base.received.push("已验证的计算结果、洞察、图表配置、来源和提示。");
    base.did = ["把内部结果整理成稳定的页面回答和 API 响应。", ...actions.slice(0, 1)];
    base.sent = [outputs.success === false ? "返回状态：需要继续确认" : "返回状态：已完成", outputs.answer_type ? `回答类型：${outputs.answer_type}` : ""];
    base.note = "这是返回给聊天页和外部接口前的最后一道格式化节点。";
  } else if (role === "single_agent") {
    base.received.push("用户问题、上传数据上下文和可用工具。");
    base.did = [activityNodePlainSummary(node), ...actions.slice(0, 2)];
    base.sent = activityOutputLines(outputs);
    base.note = "单 Agent 链路会在一个节点里完成理解、执行、校验和回答。";
  }

  base.received = normalizeStringList(base.received);
  base.did = normalizeStringList(base.did);
  base.sent = normalizeStringList(base.sent);
  return { ...base, hasContent: Boolean(base.received.length || base.did.length || base.sent.length) };
}

function activityNodeDisplayName(node = {}) {
  return monitorRoleName(node.role || node.kind || node.title);
}

function activityInputLines(inputs = {}) {
  const lines = [];
  if (inputs.question) lines.push(`用户问题：${cleanActivityText(inputs.question)}`);
  if (inputs.dataset_id) lines.push(`数据集：${cleanActivityText(inputs.dataset_id)}`);
  if (inputs.pandas) lines.push(`Pandas 结果：${cleanActivityText(inputs.pandas)}`);
  if (inputs.sql) lines.push(`SQL 结果：${cleanActivityText(inputs.sql)}`);
  return lines;
}

function activityTableNames(value) {
  const items = Array.isArray(value) ? value : value ? [value] : [];
  return items
    .map((item) => (item && typeof item === "object" ? item.table_name || item.name || item.id || "" : item))
    .map((item) => cleanActivityText(item))
    .filter(Boolean);
}

function activityOutputLines(outputs = {}) {
  const lines = [];
  if (outputs.operation) lines.push(`分析类型：${activityOperationLabel(outputs.operation)}`);
  if (Array.isArray(outputs.source_tables) && outputs.source_tables.length) lines.push(`数据表：${outputs.source_tables.join("、")}`);
  if (outputs.success !== undefined) lines.push(`执行状态：${outputs.success ? "成功" : "失败"}`);
  if (outputs.skipped) lines.push(`跳过原因：${cleanActivityText(outputs.reason || "当前问题不适合这个路径")}`);
  const value = activityReadableValue(outputs.value ?? outputs.answer ?? outputs.candidate_table);
  if (value) lines.push(`结果摘要：${value}`);
  const joinLine = activityJoinPlanLine(outputs.join_plan);
  if (joinLine) lines.push(joinLine);
  return lines;
}

function activityNodePlainSummary(node = {}) {
  return cleanActivityText(node.summary || "");
}

function activityJoinPlanLine(joinPlan = {}) {
  if (!joinPlan || typeof joinPlan !== "object" || !joinPlan.trusted) return "";
  const left = cleanActivityText(joinPlan.left_table || "左表");
  const right = cleanActivityText(joinPlan.right_table || "右表");
  const key = joinPlan.left_key && joinPlan.right_key && joinPlan.left_key === joinPlan.right_key ? joinPlan.left_key : `${joinPlan.left_key || "-"} / ${joinPlan.right_key || "-"}`;
  return `需要关联：${left} 和 ${right} 按 ${cleanActivityText(key)} 对齐。`;
}

function activityQualityLine(quality = {}) {
  if (!quality || typeof quality !== "object") return "";
  if (quality.summary) return `数据质量：${cleanActivityText(quality.summary)}`;
  if (quality.issue_count !== undefined) return `数据质量问题数：${quality.issue_count}`;
  return "";
}

function activityReadableValue(value) {
  if (value === undefined || value === null || value === "") return "";
  if (Array.isArray(value)) {
    return value.length ? `${value.length} 条结果，示例 ${activityCompactValue(value[0], 90)}` : "空结果";
  }
  if (typeof value === "object") {
    if (value.answer) return cleanActivityText(value.answer);
    if (Array.isArray(value.candidate_table)) return activityReadableValue(value.candidate_table);
    return activityCompactValue(value, 120);
  }
  if (typeof value === "number") return formatNumber(value);
  return cleanActivityText(value);
}

function activityCompactValue(value, limit = 120) {
  let text = "";
  try {
    text = JSON.stringify(redactActivityObject(value), null, 0);
  } catch {
    text = String(value || "");
  }
  return shortLabel(text, limit);
}

function activityOperationLabel(operation) {
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
    inputs_summary: safeNode.inputs_summary && typeof safeNode.inputs_summary === "object" ? redactActivityObject(safeNode.inputs_summary) : {},
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
    planner: "计划节点 (Planner)",
    data_engineer: "数据理解节点",
    pandas_executor: "Pandas 计算节点",
    sql_executor: "SQL 复算节点",
    executor: "执行节点",
    verifier: "校验节点",
    correction: "修正节点",
    insight: "洞察节点",
    visualization: "图表节点",
    response_builder: "回答节点",
    code_artifact: "复现代码",
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
  const firstSentence = text.match(/^(.{1,132}?[。！？!?])(?:\s|$)/)?.[1] || text.split(/[；;]/)[0] || text;
  return shortLabel(firstSentence, 132);
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
  const runStatus = options.run || state.activeRun || null;
  el.resultMessage.__vdsResult = null;
  el.resultMessage.__vdsRunStatus = runStatus;
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
  updateRunActionButtons(el.resultMessage, { run: runStatus, mode: runStatus?.status || "failed" });
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
  state.runHistory = sortHistoryItems(state.runHistory);
  if (!state.runHistoryRenderedCount) {
    state.runHistoryRenderedCount = Math.min(HISTORY_LOAD_BATCH, state.runHistory.length);
  }
  if (state.runHistoryRenderedCount > state.runHistory.length) {
    state.runHistoryRenderedCount = state.runHistory.length;
  }
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
  state.runHistory = sortHistoryItems(state.runHistory);
  if (!state.runHistoryRenderedCount) {
    state.runHistoryRenderedCount = Math.min(HISTORY_LOAD_BATCH, state.runHistory.length);
  }
  if (state.runHistoryRenderedCount > state.runHistory.length) {
    state.runHistoryRenderedCount = state.runHistory.length;
  }
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
  state.runHistory = sortHistoryItems(state.runHistory);
  if (!state.runHistoryRenderedCount) {
    state.runHistoryRenderedCount = Math.min(HISTORY_LOAD_BATCH, state.runHistory.length);
  }
  if (state.runHistoryRenderedCount > state.runHistory.length) {
    state.runHistoryRenderedCount = state.runHistory.length;
  }
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
  const visibleCount = Math.min(state.runHistoryRenderedCount || 0, state.runHistory.length);
  if (!state.runHistory.length) {
    el.runHistory.innerHTML = `<li class="history-empty">上传数据并提问后，这里会显示最近的分析记录。</li>`;
    if (isChatSearchOpen()) renderChatSearchResults();
    return;
  }
  const visibleHistory = state.runHistory.slice(0, visibleCount || state.runHistory.length);
  el.runHistory.innerHTML = visibleHistory
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
    notifyWorkspaceMutation("conversation_renamed", { conversation_id: runId, project_id: state.projectId });
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
    notifyWorkspaceMutation("conversation_pinned", { conversation_id: runId, project_id: state.projectId });
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
    notifyWorkspaceMutation("conversation_moved", { conversation_id: runId, project_id: conversation.project_id || safeProjectId });
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
    syncUrlWithWorkspace({ replace: true });
    notifyWorkspaceMutation("conversation_deleted", { conversation_id: runId, project_id: state.projectId });
    setApiStatus("ready", "对话已删除");
  } catch (error) {
    setApiStatus("error", `对话删除失败：${String(error.message || error)}`);
  }
}

function handleRunHistoryScroll() {
  if (!el.runHistory || state.runHistoryLoading || state.runHistory.length === 0) return;
  const remaining = el.runHistory.scrollHeight - el.runHistory.clientHeight - el.runHistory.scrollTop;
  if (remaining > 20) return;
  if (state.runHistoryRenderedCount < state.runHistory.length) {
    state.runHistoryRenderedCount = Math.min(state.runHistoryRenderedCount + HISTORY_LOAD_BATCH, state.runHistory.length);
    renderHistory();
    return;
  }
  if (!state.runHistoryHasMore) return;
  loadConversations({ append: true });
}

async function loadConversations({ append = false } = {}) {
  if (state.runHistoryLoading) return;
  const requestOffset = append ? state.runHistoryOffset : 0;
  if (!append) {
    state.runHistoryOffset = 0;
    state.runHistoryHasMore = true;
    state.runHistoryRenderedCount = 0;
  }
  state.runHistoryLoading = true;
  try {
    const previousRenderedCount = state.runHistoryRenderedCount;
    const previousLength = state.runHistory.length;
    const query = new URLSearchParams({ limit: String(HISTORY_LOAD_BATCH), offset: String(requestOffset) });
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
    if (append) {
      const merged = [...state.runHistory];
      loadedHistory.forEach((item) => {
        if (!existingById.has(item.runId)) {
          merged.push(item);
        }
      });
      state.runHistory = sortHistoryItems(merged);
      if (previousRenderedCount >= previousLength) {
        state.runHistoryRenderedCount = Math.min(state.runHistoryRenderedCount + HISTORY_LOAD_BATCH, state.runHistory.length);
      }
    } else {
      const localUnreadHistory = state.runHistory.filter((item) => item.unread === true && !item.projectId && !loadedIds.has(item.runId));
      state.runHistory = sortHistoryItems([...localUnreadHistory, ...loadedHistory]);
      state.runHistoryRenderedCount = Math.min(HISTORY_LOAD_BATCH, state.runHistory.length);
    }
    if (state.runHistoryRenderedCount > state.runHistory.length) {
      state.runHistoryRenderedCount = state.runHistory.length;
    }
    if (!state.runHistoryRenderedCount && state.runHistory.length) {
      state.runHistoryRenderedCount = Math.min(HISTORY_LOAD_BATCH, state.runHistory.length);
    }
    state.runHistoryOffset = requestOffset + loadedHistory.length;
    state.runHistoryHasMore = loadedHistory.length >= HISTORY_LOAD_BATCH;
    renderHistory();
  } catch {
    renderHistory();
  } finally {
    state.runHistoryLoading = false;
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
      assistantMessage.dataset.messageId = message.message_id || message.payload.message_id || "";
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
  syncUrlWithWorkspace({ replace: true });
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
    const autoRuleFileIds = profileRuleFileIds(profile);
    applyUserRuleFileIds(autoRuleFileIds, { replace: true });
    state.selectedTable = profile.tables?.[0]?.table_name || "";
    renderProfile();
    if (profile.can_analyze === false) {
      clearRestoredFileRecords();
      el.datasetChip.textContent = "需重新上传";
      setDatasetHeaderStatus(profile.restore_error || "数据记录存在，但源文件无法恢复，需要重新上传。", "error");
      setApiStatus("error", "数据需重新上传");
    } else {
      applyRestoredFileRecords(profile);
      setDatasetHeaderStatus(profile.restored_from_disk ? "已从本地存储恢复数据集。" : "", "ready");
      setApiStatus("ready", profile.restored_from_disk ? "数据集已恢复" : "数据集已就绪");
    }
    refreshRenderedAnswerSources();
  } catch {
    state.profile = null;
    clearRestoredFileRecords();
    renderProfile();
    el.datasetChip.textContent = state.datasetId ? "数据记录已关联" : "未上传数据";
    setDatasetHeaderStatus("数据记录存在但需重新上传。", "error");
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
  updateRunActionButtons(el.resultMessage, { mode: "idle" });
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

function resetConversation(options = {}) {
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
  setRuleFileStatus(RULE_FILE_EMPTY_HINT);
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
  if (!options.skipUrlSync) {
    syncUrlWithWorkspace({ replace: true });
  }
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
  el.saveResponseButton = message.querySelector(".save-response-button");
  el.downloadArtifactsButton = message.querySelector(".download-artifacts-button");
  el.cancelRunButton = message.querySelector(".cancel-run-button");
  el.retryRunButton = message.querySelector(".retry-run-button");
  if (el.copyReplyButton) {
    el.copyReplyButton.onclick = () => copyReplyFromMessage(message);
  }
  if (el.saveResponseButton) {
    el.saveResponseButton.onclick = () => saveAssistantResponseToProject(message);
  }
  if (el.downloadArtifactsButton) {
    el.downloadArtifactsButton.onclick = (event) => {
      event.stopPropagation();
      openDownloadMenu(event.currentTarget, message);
    };
  }
  if (el.cancelRunButton) {
    el.cancelRunButton.onclick = () => cancelRunFromMessage(message);
  }
  if (el.retryRunButton) {
    el.retryRunButton.onclick = () => retryRunFromMessage(message);
  }
}

function startMonitorRun(question) {
  state.activeMonitorRunId = `mon_${Date.now()}_${Math.random().toString(16).slice(2, 10)}`;
  const record = {
    monitor_run_id: state.activeMonitorRunId,
    question,
    dataset_id: state.datasetId,
    conversation_id: state.conversationId,
    execution_mode: currentExecutionMode() || "dual",
    agent_mode: currentAgentMode() || "multi_agent",
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
  const value = String(text || "").trim();
  if (!value.trim()) return false;
  if (!/[\u3400-\u9fff]/.test(value)) return false;
  if (
    ["数据质量", "高严重度", "quality_report", "verification", "warnings", "errors", "join trace", "Join / Verification"].some((token) =>
    value.includes(token),
    )
  ) {
    return false;
  }
  return !looksLikeEnglishProseLeak(value);
}

function isActionableInsightAdvice(text) {
  const value = String(text || "").trim();
  if (!isUserFacingInsightText(value)) return false;
  return /下一步|继续|先|按|比较|查看|检查|复核|确认|拆分|下钻|分析|生成|列出|看|追踪|对比|补充|选择|找出/.test(value);
}

function looksLikeEnglishProseLeak(text) {
  const value = String(text || "").trim();
  if (!value) return false;
  const segments = value
    .split(/[；;。！？!?]\s*|(?:观察|风险|边界|依据|建议|下一步)[:：]/)
    .map((segment) => segment.trim())
    .filter(Boolean);
  return (segments.length ? segments : [value]).some((segment) => segmentLooksLikeEnglishProseLeak(segment));
}

function segmentLooksLikeEnglishProseLeak(segment) {
  const cjkCount = (segment.match(/[\u3400-\u9fff]/g) || []).length;
  const latinWords = segment.match(/[A-Za-z][A-Za-z_'-]*/g) || [];
  if (!latinWords.length) return false;
  const proseTokens = new Set([
    "are",
    "based",
    "by",
    "compare",
    "countries",
    "country",
    "data",
    "followed",
    "full",
    "include",
    "includes",
    "is",
    "leading",
    "next",
    "not",
    "only",
    "present",
    "ranked",
    "ranking",
    "result",
    "results",
    "show",
    "shows",
    "step",
    "the",
    "this",
    "that",
  ]);
  const proseCount = latinWords.filter((word) => proseTokens.has(word.toLowerCase().replace(/^_+|_+$/g, ""))).length;
  if (cjkCount === 0) return proseCount >= 2 || (latinWords.length >= 5 && proseCount >= 1);
  return proseCount >= 3 && cjkCount < 6;
}

function stringifyIssue(issue) {
  if (typeof issue === "string") return issue;
  if (issue?.error_message) return issue.error_message;
  return JSON.stringify(issue);
}

function formatPercent(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return String(value ?? "-");
  return `${number.toFixed(number >= 10 ? 1 : 2)}%`;
}

function formatNumber(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return String(value ?? "-");
  return Math.abs(number) >= 1000 ? number.toLocaleString("zh-CN", { maximumFractionDigits: 1 }) : String(Number(number.toFixed(2)));
}

function formatTableCellValue(column, value) {
  if (value === null || value === undefined || value === "") return "-";
  if (typeof value === "string" && /%|,/.test(value)) return value;
  const number = Number(value);
  if (!Number.isFinite(number)) return String(value);
  if (looksLikeRateField(column)) return `${number.toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}%`;
  if (/count|数量|次数|记录数|行数|year|month|day|hour|minute/i.test(String(column || "")) && !/金额|销售额|收入|利润/i.test(String(column || ""))) {
    return number.toLocaleString("zh-CN", { maximumFractionDigits: 0 });
  }
  return number.toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
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
