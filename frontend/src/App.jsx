import { useEffect, useRef, useState } from "react";
import "./App.css";

const API = import.meta.env.VITE_API_URL
  ?? (import.meta.env.DEV ? "http://127.0.0.1:8000" : "");

async function requestJson(path, options) {
  const headers = new Headers(options?.headers);
  const accessToken = window.sessionStorage.getItem("nexus_access_token");
  if (accessToken) headers.set("Authorization", `Bearer ${accessToken}`);
  const response = await fetch(`${API}${path}`, { ...options, headers });
  const text = await response.text();
  let data = null;

  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = { detail: text };
    }
  }

  if (!response.ok) {
    throw new Error(data?.detail || data?.message || `Request failed (${response.status})`);
  }

  return data;
}

async function streamJsonEvents(path, onEvent) {
  const headers = new Headers({ Accept: "text/event-stream" });
  const accessToken = window.sessionStorage.getItem("nexus_access_token");
  if (accessToken) headers.set("Authorization", `Bearer ${accessToken}`);
  const response = await fetch(`${API}${path}`, { headers, cache: "no-store" });
  if (!response.ok || !response.body) {
    let detail = `Stream failed (${response.status})`;
    try { detail = (await response.json()).detail || detail; } catch { /* stream error */ }
    throw new Error(detail);
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
    const frames = buffer.split(/\r?\n\r?\n/);
    buffer = frames.pop() || "";
    for (const frame of frames) {
      const data = frame.split(/\r?\n/).filter((line) => line.startsWith("data: ")).map((line) => line.slice(6)).join("\n");
      if (data) onEvent(JSON.parse(data));
    }
    if (done) break;
  }
}

async function requestMedia(path) {
  const headers = new Headers();
  const accessToken = window.sessionStorage.getItem("nexus_access_token");
  if (accessToken) headers.set("Authorization", `Bearer ${accessToken}`);
  const response = await fetch(`${API}${path}`, { headers });
  if (!response.ok) {
    let detail = `Request failed (${response.status})`;
    try { detail = (await response.json()).detail || detail; } catch { /* binary response */ }
    throw new Error(detail);
  }
  return URL.createObjectURL(await response.blob());
}

function App() {
  const [system, setSystem] = useState(null);
  const [message, setMessage] = useState("");
  const [messages, setMessages] = useState([]);
  const [conversations, setConversations] = useState([]);
  const [conversationId, setConversationId] = useState(null);
  const [sidebarWidth, setSidebarWidth] = useState(() => {
    const stored = Number(window.localStorage.getItem("nexus_sidebar_width"));
    return Number.isFinite(stored) && stored >= 220 && stored <= 420 ? stored : 270;
  });
  const [sidebarCompact, setSidebarCompact] = useState(
    () => window.localStorage.getItem("nexus_sidebar_compact") === "true"
  );
  const [selectedConversationIds, setSelectedConversationIds] = useState(() => new Set());
  const [conversationSearch, setConversationSearch] = useState("");
  const [conversationView, setConversationView] = useState("active");
  const [conversationSort, setConversationSort] = useState(() => {
    const stored = window.localStorage.getItem("nexus_conversation_sort");
    return ["recent", "created", "title"].includes(stored) ? stored : "recent";
  });
  const [activePage, setActivePage] = useState("command");
  const [memories, setMemories] = useState([]);
  const [projects, setProjects] = useState([]);
  const [indexing, setIndexing] = useState(false);
  const [approvals, setApprovals] = useState([]);
  const [audit, setAudit] = useState([]);
  const [integrations, setIntegrations] = useState({ mcp: [], github: {} });
  const [providerConnections, setProviderConnections] = useState({ providers: [], persistent_available: false, write_enabled: false });
  const [modelCatalog, setModelCatalog] = useState({ models: [] });
  const [operations, setOperations] = useState({ services: [], models: [], state: "attention" });
  const [selectedModel, setSelectedModel] = useState("");
  const [mediaProviders, setMediaProviders] = useState([]);
  const [mediaJobs, setMediaJobs] = useState([]);
  const [runnerData, setRunnerData] = useState({ nodes: [], jobs: [], tools: [] });
  const [runnerPairing, setRunnerPairing] = useState(null);
  const [agentStatus, setAgentStatus] = useState({ agents: [], infrastructure: {} });
  const [orchestrationPlan, setOrchestrationPlan] = useState(null);
  const [orchestrationEvents, setOrchestrationEvents] = useState([]);
  const [research, setResearch] = useState(null);
  const [intentRoute, setIntentRoute] = useState(null);
  const [contactData, setContactData] = useState({ contacts: [], messages: [], smtp_configured: false });
  const [recording, setRecording] = useState(false);
  const [voicePlayback, setVoicePlayback] = useState(false);
  const [automations, setAutomations] = useState([]);
  const [automationHistory, setAutomationHistory] = useState([]);
  const recorderRef = useRef(null);
  const chunksRef = useRef([]);
  const cancelRecordingRef = useRef(false);
  const [memoryForm, setMemoryForm] = useState({
    category: "fact", key: "", content: "", importance: 5,
  });

  const [loading, setLoading] = useState(false);
  const [backendOnline, setBackendOnline] = useState(false);
  const [networkOnline, setNetworkOnline] = useState(() => navigator.onLine);
  const [initialLoading, setInitialLoading] = useState(true);
  const [pageLoading, setPageLoading] = useState("");
  const [appError, setAppError] = useState("");
  const [authRequired, setAuthRequired] = useState(null);
  const [demoMode, setDemoMode] = useState(false);
  const [accessToken, setAccessToken] = useState(
    () => window.sessionStorage.getItem("nexus_access_token") || ""
  );
  const [authError, setAuthError] = useState("");

  function showError(context, error) {
    const detail = error instanceof Error ? error.message : String(error);
    setAppError(`${context}: ${detail}`);
  }

  async function loadSystem() {
    try {
      const data = await requestJson("/api/system");
      setSystem(data);
      setBackendOnline(true);
    } catch (error) {
      setBackendOnline(false);
      throw error;
    }
  }

  async function loadConversations() {
    const data = await requestJson("/api/conversations?include_archived=true&include_deleted=true");
    setConversations(data.conversations || []);
  }

  async function loadConversation(id) {
    await runPageLoad("Loading conversation", async () => {
      const data = await requestJson(`/api/conversations/${id}`);
      setConversationId(id);
      setMessages(data.messages || []);
    });
  }

  async function loadMemories() {
    const data = await requestJson("/api/memories");
    setMemories(data.memories || []);
  }

  async function loadProjects() {
    const data = await requestJson("/api/projects");
    setProjects(data.projects || []);
  }

  async function indexProject() {
    setIndexing(true);
    setAppError("");
    try {
      await requestJson("/api/projects/index", { method: "POST" });
      await loadSafety();
      await loadProjects();
    } catch (error) {
      showError("Unable to request project indexing", error);
    } finally {
      setIndexing(false);
    }
  }

  async function loadSafety() {
    const [approvalData, auditData] = await Promise.all([
      requestJson("/api/approvals?state=pending"),
      requestJson("/api/audit"),
    ]);
    setApprovals(approvalData.approvals || []);
    setAudit(auditData.records || []);
  }

  async function loadIntegrations() {
    setIntegrations(await requestJson("/api/integrations"));
  }

  async function loadProviderConnections() {
    setProviderConnections(await requestJson("/api/provider-connections"));
  }

  async function connectProvider(event, provider) {
    event.preventDefault();
    const formElement = event.currentTarget;
    const form = new FormData(formElement);
    await runPageLoad(`Verifying ${provider} connection`, async () => {
      await requestJson(`/api/provider-connections/${encodeURIComponent(provider)}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          api_key: form.get("api_key"),
          model: form.get("model") || undefined,
          base_url: form.get("base_url") || undefined,
        }),
      });
      formElement.reset();
      await Promise.all([loadProviderConnections(), loadModels(), loadMedia(), loadOperations()]);
    });
  }

  async function disconnectProvider(provider) {
    if (!window.confirm(`Disconnect ${provider}? The UI-managed credential will be forgotten.`)) return;
    await runPageLoad(`Disconnecting ${provider}`, async () => {
      await requestJson(`/api/provider-connections/${encodeURIComponent(provider)}`, { method: "DELETE" });
      await Promise.all([loadProviderConnections(), loadModels(), loadMedia(), loadOperations()]);
    });
  }

  async function refreshMcp(name) {
    await runPageLoad(`Refreshing ${name} MCP`, async () => {
      await requestJson(`/api/integrations/mcp/${encodeURIComponent(name)}/refresh`, { method: "POST" });
      await loadIntegrations();
    });
  }

  async function loadAgents() {
    setAgentStatus(await requestJson("/api/agents"));
  }

  async function runSpecialist(slug, message) {
    const [provider, ...modelParts] = selectedModel.split(":");
    return requestJson(`/api/agents/${encodeURIComponent(slug)}/run`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message, provider: provider || undefined, model: modelParts.join(":") || undefined }),
    });
  }

  async function previewOrchestration(objective, specialists) {
    const [provider, ...modelParts] = selectedModel.split(":");
    const plan = await requestJson("/api/orchestration/plans", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ objective, specialists, provider: provider || undefined, model: modelParts.join(":") || undefined }),
    });
    setOrchestrationPlan(plan);
    const history = await requestJson(`/api/orchestration/plans/${plan.id}/events`);
    setOrchestrationEvents(history.events || []);
    return plan;
  }

  async function refreshOrchestration() {
    if (!orchestrationPlan?.id) return null;
    const [plan, history] = await Promise.all([
      requestJson(`/api/orchestration/plans/${orchestrationPlan.id}`),
      requestJson(`/api/orchestration/plans/${orchestrationPlan.id}/events`),
    ]);
    setOrchestrationPlan(plan);
    setOrchestrationEvents(history.events || []);
    return plan;
  }

  async function executeOrchestration() {
    if (!orchestrationPlan?.id) return null;
    const plan = await requestJson(`/api/orchestration/plans/${orchestrationPlan.id}/start`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ confirmed: true }),
    });
    setOrchestrationPlan(plan);
    const lastEventId = orchestrationEvents.at(-1)?.id || 0;
    await streamJsonEvents(
      `/api/orchestration/plans/${plan.id}/events/stream?after_id=${lastEventId}`,
      (event) => setOrchestrationEvents((current) => current.some((item) => item.id === event.id) ? current : [...current, event]),
    );
    const completed = await requestJson(`/api/orchestration/plans/${plan.id}`);
    setOrchestrationPlan(completed);
    return completed;
  }

  async function cancelOrchestration() {
    if (!orchestrationPlan?.id) return null;
    const plan = await requestJson(`/api/orchestration/plans/${orchestrationPlan.id}/cancel`, {
      method: "POST",
    });
    setOrchestrationPlan(plan);
    const history = await requestJson(`/api/orchestration/plans/${plan.id}/events`);
    setOrchestrationEvents(history.events || []);
    return plan;
  }

  async function loadModels() {
    const catalog = await requestJson("/api/models");
    setModelCatalog(catalog);
    setSelectedModel((current) => current || `${catalog.default_provider}:${catalog.default_model}`);
  }

  async function loadOperations() {
    setOperations(await requestJson("/api/operations"));
  }

  async function loadMedia() {
    const [providersData, jobsData] = await Promise.all([
      requestJson("/api/media/providers"),
      requestJson("/api/media/jobs"),
    ]);
    setMediaProviders(providersData.providers || []);
    setMediaJobs(jobsData.jobs || []);
  }

  async function loadRunner() {
    setRunnerData(await requestJson("/api/runner"));
  }

  async function runResearch(kind, query) {
    const result = await requestJson(`/api/research/${kind}`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query, limit: 8 }),
    });
    setResearch(result);
  }
  async function previewIntent(message) { setIntentRoute(await requestJson("/api/intent-routing/preview", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ message }) })); }

  async function loadContacts() {
    setContactData(await requestJson("/api/contacts"));
  }

  async function pairRunner(event) {
    event.preventDefault();
    const formElement = event.currentTarget;
    const form = new FormData(formElement);
    await runPageLoad("Pairing local runner", async () => {
      const result = await requestJson("/api/runner/nodes", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: form.get("name") }),
      });
      setRunnerPairing(result);
      formElement.reset();
      await loadRunner();
    });
  }

  async function createRunnerJob(event) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    await runPageLoad("Queueing local runner job", async () => {
      let args = {};
      if (form.get("tool") === "speak_text") {
        args = {
          text: String(form.get("speech_text") || "").trim(),
          rate: Number(form.get("speech_rate") || 170),
          volume: Number(form.get("speech_volume") || 1),
        };
        const voiceIndex = String(form.get("voice_index") || "").trim();
        if (voiceIndex) args.voice_index = Number(voiceIndex);
      } else if (form.get("tool") === "media_control") {
        args = {
          action: String(form.get("media_action") || ""),
          repeat: Number(form.get("media_repeat") || 1),
        };
      } else if (form.get("tool") === "launch_app") {
        args = { app_id: String(form.get("app_id") || "").trim() };
      } else if (form.get("tool") === "capture_screenshot") {
        args = {};
      } else {
        try { args = JSON.parse(form.get("arguments") || "{}"); } catch { throw new Error("Arguments must be valid JSON"); }
      }
      await requestJson("/api/runner/jobs", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ node_id: form.get("node_id"), tool: form.get("tool"), arguments: args }),
      });
      await Promise.all([loadRunner(), loadSafety()]);
    });
  }

  async function disableRunner(node) {
    if (!window.confirm(`Disable runner "${node.name}"? Its token will stop working.`)) return;
    await runPageLoad("Disabling local runner", async () => {
      await requestJson(`/api/runner/nodes/${node.id}`, {
        method: "PATCH", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ active: false }),
      });
      await loadRunner();
    });
  }

  async function loadAutomations() {
    const [jobsData, historyData] = await Promise.all([
      requestJson("/api/automations"),
      requestJson("/api/automations/history"),
    ]);
    setAutomations(jobsData.jobs || []);
    setAutomationHistory(historyData.history || []);
  }

  async function runPageLoad(label, task) {
    setPageLoading(label);
    setAppError("");
    try {
      await task();
    } catch (error) {
      showError(label, error);
    } finally {
      setPageLoading("");
    }
  }

  function openPage(page, loader) {
    setActivePage(page);
    if (loader) void runPageLoad(`Loading ${page}`, loader);
  }

  async function refreshAll() {
    setInitialLoading(true);
    setAppError("");
    const results = await Promise.allSettled([
      loadSystem(), loadConversations(), loadMemories(), loadProjects(),
      loadSafety(), loadIntegrations(), loadProviderConnections(), loadAgents(), loadAutomations(), loadModels(), loadMedia(), loadRunner(), loadOperations(),
      loadContacts(),
    ]);
    const failures = results.filter((result) => result.status === "rejected");
    if (failures.length) {
      const firstError = failures[0].reason;
      showError(`Unable to load ${failures.length} NEXUS data source${failures.length === 1 ? "" : "s"}`, firstError);
    }
    setInitialLoading(false);
  }

  async function bootstrap() {
    try {
      const config = await requestJson("/api/config");
      setAuthRequired(config.authentication_required);
      setDemoMode(Boolean(config.demo_mode));
      if (config.authentication_required && !window.sessionStorage.getItem("nexus_access_token")) {
        setInitialLoading(false);
        return;
      }
      await refreshAll();
    } catch (error) {
      showError("Unable to load NEXUS configuration", error);
      setInitialLoading(false);
    }
  }

  async function signIn(event) {
    event.preventDefault();
    const token = new FormData(event.currentTarget).get("access_token")?.toString().trim();
    if (!token) return;
    window.sessionStorage.setItem("nexus_access_token", token);
    setAuthError("");
    try {
      const data = await requestJson("/api/system");
      setSystem(data);
      setBackendOnline(true);
      setAccessToken(token);
      await refreshAll();
    } catch (error) {
      window.sessionStorage.removeItem("nexus_access_token");
      setAuthError(error.message);
    }
  }

  function signOut() {
    window.sessionStorage.removeItem("nexus_access_token");
    setAccessToken("");
    setBackendOnline(false);
    setMessages([]);
  }

  async function createAutomation(event) {
    event.preventDefault();
    const formElement = event.currentTarget;
    const form = new FormData(formElement);
    await runPageLoad("Creating automation", async () => {
      await requestJson("/api/automations", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(Object.fromEntries(form)),
      });
      formElement.reset();
      await loadAutomations();
    });
  }

  async function toggleAutomation(job) {
    await runPageLoad("Updating automation", async () => {
      await requestJson(`/api/automations/${job.id}`, {
        method: "PATCH", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled: !job.enabled }),
      });
      await loadAutomations();
    });
  }

  async function runAutomation(job) {
    await runPageLoad("Running automation", async () => {
      await requestJson(`/api/automations/${job.id}/run`, { method: "POST" });
      await Promise.all([loadAutomations(), loadSafety()]);
    });
  }

  async function decideApproval(id, approved) {
    await runPageLoad("Resolving approval", async () => {
      await requestJson(`/api/approvals/${id}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ approved }),
      });
      await Promise.all([loadSafety(), loadProjects()]);
    });
  }

  async function saveMemory(event) {
    event.preventDefault();
    await runPageLoad("Saving memory", async () => {
      await requestJson("/api/memories", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(memoryForm),
      });
      setMemoryForm({ category: "fact", key: "", content: "", importance: 5 });
      await loadMemories();
    });
  }

  async function deleteMemory(memory) {
    if (!window.confirm(`Forget memory "${memory.key}"? This cannot be undone.`)) return;
    await runPageLoad("Forgetting memory", async () => {
      await requestJson(`/api/memories/${memory.id}`, { method: "DELETE" });
      await loadMemories();
    });
  }

  function clearConversationSelection() {
    setSelectedConversationIds(new Set());
  }

  function toggleConversationSelection(conversationId) {
    setSelectedConversationIds((current) => {
      const next = new Set(current);
      if (next.has(conversationId)) {
        next.delete(conversationId);
      } else {
        next.add(conversationId);
      }
      return next;
    });
  }

  function selectVisibleConversations() {
    setSelectedConversationIds(new Set(visibleConversations.map((conversation) => conversation.id)));
  }

  function newConversation() {
    clearConversationSelection();
    setConversationId(null);
    setMessages([]);
    setMessage("");
  }

  function updateSidebarWidth(event) {
    const width = Math.min(420, Math.max(220, Number(event.target.value)));
    setSidebarWidth(width);
    window.localStorage.setItem("nexus_sidebar_width", String(width));
  }

  function toggleSidebarCompact() {
    setSidebarCompact((current) => {
      const next = !current;
      window.localStorage.setItem("nexus_sidebar_compact", String(next));
      return next;
    });
  }

  function switchConversationView(view) {
    clearConversationSelection();
    setConversationView(view);
  }

  async function deleteConversation(conversation) {
    if (!window.confirm(`Move conversation "${conversation.title}" to Recently deleted? It can be restored for 30 days.`)) return;
    await runPageLoad("Deleting conversation", async () => {
      await requestJson(`/api/conversations/${encodeURIComponent(conversation.id)}`, { method: "DELETE" });
      await loadConversations();
      clearConversationSelection();
      if (conversation.id === conversationId) newConversation();
    });
  }

  async function restoreDeletedConversation(conversation) {
    await runPageLoad("Restoring conversation", async () => {
      const data = await requestJson(`/api/conversations/${encodeURIComponent(conversation.id)}/restore`, { method: "POST" });
      setConversations((current) => current.map((item) => (
        item.id === conversation.id ? data.conversation : item
      )));
      clearConversationSelection();
    });
  }

  async function purgeConversation(conversation) {
    if (!window.confirm(`Permanently purge conversation "${conversation.title}" and all messages? This cannot be undone.`)) return;
    await runPageLoad("Purging conversation", async () => {
      await requestJson(`/api/conversations/${encodeURIComponent(conversation.id)}/purge`, { method: "DELETE" });
      setConversations((current) => current.filter((item) => item.id !== conversation.id));
      clearConversationSelection();
    });
  }

  function updateConversationSort(event) {
    const sort = event.target.value;
    setConversationSort(sort);
    window.localStorage.setItem("nexus_conversation_sort", sort);
  }

  async function updateConversation(conversation, changes) {
    await runPageLoad("Updating conversation", async () => {
      const data = await requestJson(`/api/conversations/${encodeURIComponent(conversation.id)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(changes),
      });
      setConversations((current) => current.map((item) => (
        item.id === conversation.id ? data.conversation : item
      )));
      if (changes.archived && conversation.id === conversationId) newConversation();
    });
  }

  async function patchConversationWithoutLoading(conversation, changes) {
    return requestJson(`/api/conversations/${encodeURIComponent(conversation.id)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(changes),
    });
  }

  async function restoreConversationWithoutLoading(conversation) {
    return requestJson(`/api/conversations/${encodeURIComponent(conversation.id)}/restore`, { method: "POST" });
  }

  async function trashConversationWithoutLoading(conversation) {
    return requestJson(`/api/conversations/${encodeURIComponent(conversation.id)}`, { method: "DELETE" });
  }

  async function purgeConversationWithoutLoading(conversation) {
    return requestJson(`/api/conversations/${encodeURIComponent(conversation.id)}/purge`, { method: "DELETE" });
  }

  async function bulkConversationAction(label, conversations, action) {
    if (conversations.length === 0) return;
    const affectsCurrentConversation = conversations.some((conversation) => conversation.id === conversationId);
    await runPageLoad(label, async () => {
      for (const conversation of conversations) {
        await action(conversation);
      }
      await loadConversations();
      clearConversationSelection();
      if (affectsCurrentConversation) newConversation();
    });
  }

  async function bulkArchiveConversations(conversations) {
    if (!window.confirm(`Archive ${conversations.length} conversation${conversations.length === 1 ? "" : "s"}?`)) return;
    await bulkConversationAction("Archiving conversations", conversations, (conversation) => patchConversationWithoutLoading(conversation, { archived: true }));
  }

  async function bulkRestoreConversations(conversations) {
    await bulkConversationAction("Restoring conversations", conversations, (conversation) => (
      conversation.deleted_at
        ? restoreConversationWithoutLoading(conversation)
        : patchConversationWithoutLoading(conversation, { archived: false })
    ));
  }

  async function bulkDeleteConversations(conversations) {
    if (!window.confirm(`Move ${conversations.length} conversation${conversations.length === 1 ? "" : "s"} to Recently deleted?`)) return;
    await bulkConversationAction("Deleting conversations", conversations, trashConversationWithoutLoading);
  }

  async function bulkPurgeConversations(conversations) {
    if (!window.confirm(`Permanently purge ${conversations.length} conversation${conversations.length === 1 ? "" : "s"}? This cannot be undone.`)) return;
    await bulkConversationAction("Purging conversations", conversations, purgeConversationWithoutLoading);
  }

  function renameConversation(conversation) {
    const title = window.prompt("Rename conversation", conversation.title)?.trim();
    if (!title || title === conversation.title) return;
    void updateConversation(conversation, { title });
  }

  async function sendMessage(transcribedMessage = null) {
    const text = typeof transcribedMessage === "string" ? transcribedMessage : message;
    if (!text.trim() || loading) return;

    const pendingId = `pending-${Date.now()}`;
    const userMessage = {
      id: pendingId,
      role: "user",
      content: text,
    };

    setMessages((current) => [
      ...current,
      userMessage,
    ]);

    const outgoingMessage = text;

    setMessage("");
    setLoading(true);
    setAppError("");

    try {
      const [provider, ...modelParts] = selectedModel.split(":");
      const data = await requestJson("/api/chat", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          message: outgoingMessage,
          conversation_id: conversationId,
          provider: provider || undefined,
          model: modelParts.join(":") || undefined,
        }),
      });

      setConversationId(data.conversation_id);

      setMessages((current) => [
        ...current.filter((item) => item.id !== pendingId),
        data.user_message,
        { ...data.assistant_message, model: `${data.provider} • ${data.model}` },
      ]);

      if (voicePlayback && "speechSynthesis" in window) {
        window.speechSynthesis.speak(new SpeechSynthesisUtterance(data.response));
      }

      await loadConversations();
    } catch (error) {
      setMessages((current) => [
        ...current,
        {
          role: "assistant",
          content: `Unable to complete the request: ${error.message}`,
        },
      ]);

      showError("Chat request failed", error);
    } finally {
      setLoading(false);
    }
  }

  function replaceChatMessage(updated) {
    setMessages((current) => current.map((item) => item.id === updated.id ? updated : item));
  }

  async function deleteChatMessage(item) {
    if (!conversationId || !item.id || !window.confirm("Delete this chat message? This cannot be undone.")) return;
    await runPageLoad("Deleting chat message", async () => {
      await requestJson(`/api/conversations/${encodeURIComponent(conversationId)}/messages/${item.id}`, { method: "DELETE" });
      setMessages((current) => current.filter((messageItem) => messageItem.id !== item.id));
    });
  }

  async function pinChatMessage(item) {
    if (!conversationId || !item.id) return;
    await runPageLoad("Pinning chat message", async () => {
      const result = await requestJson(`/api/conversations/${encodeURIComponent(conversationId)}/messages/${item.id}/pin`, { method: "POST" });
      replaceChatMessage(result.message);
      await loadMemories();
    });
  }

  async function addChatMessageToProject(item) {
    const project = projects[0];
    if (!conversationId || !item.id || !project) throw new Error("No approved project is available");
    await runPageLoad("Adding chat message to project", async () => {
      const result = await requestJson(`/api/conversations/${encodeURIComponent(conversationId)}/messages/${item.id}/project`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ project_id: project.id }),
      });
      replaceChatMessage(result.message);
      await loadProjects();
    });
  }

  async function integrateChatMessage(item, integration) {
    if (!conversationId || !item.id) throw new Error("Save the conversation before integrating this message");
    const result = await requestJson(`/api/conversations/${encodeURIComponent(conversationId)}/messages/${item.id}/integrate`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(integration),
    });
    if (result.state === "completed") {
      replaceChatMessage(result.source_message);
      setMessages((current) => [
        ...current,
        { ...result.message, model: `${result.provider} • ${result.model}` },
      ]);
      await loadConversations();
    }
    return result;
  }

  async function startRecording() {
    setAppError("");
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      chunksRef.current = [];
      cancelRecordingRef.current = false;
      const recorder = new MediaRecorder(stream);
      recorderRef.current = recorder;
      recorder.ondataavailable = (event) => chunksRef.current.push(event.data);
      recorder.onstop = async () => {
        stream.getTracks().forEach((track) => track.stop());
        setRecording(false);
        if (cancelRecordingRef.current) return;
        try {
          const blob = new Blob(chunksRef.current, { type: recorder.mimeType || "audio/webm" });
          const form = new FormData();
          form.append("audio", blob, "recording.webm");
          const data = await requestJson("/api/voice/transcribe", { method: "POST", body: form });
          setMessage(data.transcript);
          await sendMessage(data.transcript);
        } catch (error) {
          showError("Voice transcription failed", error);
        }
      };
      recorder.start();
      setRecording(true);
    } catch (error) {
      showError("Microphone access failed", error);
    }
  }

  function stopRecording(cancel = false) {
    cancelRecordingRef.current = cancel;
    recorderRef.current?.stop();
  }

  function handleKeyDown(event) {
    if (
      event.key === "Enter" &&
      !event.shiftKey
    ) {
      event.preventDefault();
      sendMessage();
    }
  }

  useEffect(() => {
    const initialRefresh = window.setTimeout(() => void bootstrap(), 0);

    const interval = setInterval(
      () => void loadSystem().catch(() => {}),
      5000
    );

    return () => {
      window.clearTimeout(initialRefresh);
      clearInterval(interval);
    };
  }, []);

  const normalizedConversationSearch = conversationSearch.trim().toLowerCase();
  const visibleConversations = conversations
    .filter((conversation) => {
      const matchesView = conversationView === "deleted"
        ? Boolean(conversation.deleted_at)
        : conversationView === "archived"
          ? Boolean(conversation.archived_at) && !conversation.deleted_at
          : !conversation.archived_at && !conversation.deleted_at;
      return matchesView && (
        !normalizedConversationSearch
        || conversation.title.toLowerCase().includes(normalizedConversationSearch)
      );
    })
    .sort((left, right) => {
      if (conversationView === "active" && left.pinned !== right.pinned) {
        return left.pinned ? -1 : 1;
      }
      if (conversationSort === "title") return left.title.localeCompare(right.title);
      if (conversationSort === "created") return right.created_at.localeCompare(left.created_at);
      return right.updated_at.localeCompare(left.updated_at);
    });
  const selectedVisibleConversations = visibleConversations.filter((conversation) => selectedConversationIds.has(conversation.id));

  useEffect(() => {
    const online = () => setNetworkOnline(true);
    const offline = () => setNetworkOnline(false);
    window.addEventListener("online", online);
    window.addEventListener("offline", offline);
    return () => {
      window.removeEventListener("online", online);
      window.removeEventListener("offline", offline);
    };
  }, []);

  if (authRequired && !accessToken) {
    return <AccessGate onSubmit={signIn} error={authError} />;
  }

  return (
    <div className="app">
      <aside
        className={sidebarCompact ? "sidebar sidebar-compact" : "sidebar"}
        style={{ "--sidebar-width": `${sidebarWidth}px` }}
      >
        <div className="brand">
          <div className="logo">N</div>

          <div>
            <h1>NEXUS</h1>
            <span>PERSONAL AI OS</span>
          </div>
        </div>

        <div className="sidebar-controls">
          <label>
            <span>WIDTH</span>
            <input
              type="range"
              min="220"
              max="420"
              step="10"
              value={sidebarWidth}
              onChange={updateSidebarWidth}
              disabled={sidebarCompact}
              aria-label="Sidebar width"
            />
          </label>
          <button onClick={toggleSidebarCompact} aria-pressed={sidebarCompact}>
            {sidebarCompact ? "Expand" : "Compact"}
          </button>
        </div>

        <button
          className="new-chat"
          onClick={newConversation}
        >
          + New Chat
        </button>

        <div className="conversation-list">
          <p className="sidebar-label">
            CONVERSATIONS
          </p>

          <div className="conversation-filters">
            <input
              type="search"
              value={conversationSearch}
              onChange={(event) => setConversationSearch(event.target.value)}
              placeholder="Search chats"
              aria-label="Search conversations"
            />
            <select
              value={conversationSort}
              onChange={updateConversationSort}
              aria-label="Sort conversations"
            >
              <option value="recent">Recent</option>
              <option value="created">Created</option>
              <option value="title">Title</option>
            </select>
          </div>

          <div className="conversation-view-tabs" aria-label="Conversation view">
            {[
              ["active", "Active"],
              ["archived", "Archive"],
              ["deleted", "Deleted"],
            ].map(([value, label]) => (
              <button
                key={value}
                className={conversationView === value ? "active" : ""}
                onClick={() => switchConversationView(value)}
                aria-pressed={conversationView === value}
              >
                {label}
              </button>
            ))}
          </div>

          <div className="conversation-toolbar">
            <span>
              {selectedVisibleConversations.length > 0
                ? `${selectedVisibleConversations.length} selected`
                : `${visibleConversations.length} visible`}
            </span>
            <div className="conversation-toolbar-actions">
              <button onClick={selectVisibleConversations} disabled={visibleConversations.length === 0}>
                Select all
              </button>
              <button onClick={clearConversationSelection} disabled={selectedConversationIds.size === 0}>
                Clear
              </button>
              {conversationView === "deleted" ? (
                <>
                  <button
                    onClick={() => void bulkRestoreConversations(selectedVisibleConversations)}
                    disabled={selectedVisibleConversations.length === 0}
                  >
                    Restore selected
                  </button>
                  <button
                    onClick={() => void bulkPurgeConversations(selectedVisibleConversations)}
                    disabled={selectedVisibleConversations.length === 0}
                  >
                    Purge selected
                  </button>
                </>
              ) : conversationView === "archived" ? (
                <>
                  <button
                    onClick={() => void bulkRestoreConversations(selectedVisibleConversations)}
                    disabled={selectedVisibleConversations.length === 0}
                  >
                    Restore selected
                  </button>
                  <button
                    onClick={() => void bulkDeleteConversations(selectedVisibleConversations)}
                    disabled={selectedVisibleConversations.length === 0}
                  >
                    Delete selected
                  </button>
                </>
              ) : (
                <>
                  <button
                    onClick={() => void bulkArchiveConversations(selectedVisibleConversations)}
                    disabled={selectedVisibleConversations.length === 0}
                  >
                    Archive selected
                  </button>
                  <button
                    onClick={() => void bulkDeleteConversations(selectedVisibleConversations)}
                    disabled={selectedVisibleConversations.length === 0}
                  >
                    Delete selected
                  </button>
                </>
              )}
            </div>
          </div>

          {visibleConversations.length === 0 && (
            <p className="empty-sidebar">
              {conversationView === "deleted"
                ? "No recently deleted conversations."
                : conversationView === "archived"
                  ? "No archived conversations."
                  : "No matching conversations."}
            </p>
          )}

          {visibleConversations.map((conversation) => (
            <div
              key={conversation.id}
              className={
                conversation.id === conversationId
                  ? selectedConversationIds.has(conversation.id)
                    ? "conversation-row active-conversation selected-conversation"
                    : "conversation-row active-conversation"
                  : selectedConversationIds.has(conversation.id)
                    ? "conversation-row selected-conversation"
                    : "conversation-row"
              }
            >
              <input
                className="conversation-select"
                type="checkbox"
                checked={selectedConversationIds.has(conversation.id)}
                onChange={() => toggleConversationSelection(conversation.id)}
                aria-label={`Select conversation ${conversation.title}`}
              />

              <button
                className="conversation-item"
                onClick={() => !conversation.deleted_at && loadConversation(conversation.id)}
                title={conversation.title}
                disabled={Boolean(conversation.deleted_at)}
              >
                {conversation.title}
              </button>
              <div className="conversation-actions">
                {conversation.deleted_at ? (
                  <>
                    <button
                      className="conversation-action"
                      onClick={() => void restoreDeletedConversation(conversation)}
                      aria-label={`Restore conversation ${conversation.title}`}
                      title="Restore conversation"
                    >↩</button>
                    <button
                      className="conversation-delete"
                      onClick={() => void purgeConversation(conversation)}
                      aria-label={`Permanently purge conversation ${conversation.title}`}
                      title="Permanently purge"
                    >×</button>
                  </>
                ) : (
                  <>
                    <button
                      className={conversation.pinned ? "conversation-action pinned" : "conversation-action"}
                      onClick={() => void updateConversation(conversation, { pinned: !conversation.pinned })}
                      aria-label={`${conversation.pinned ? "Unpin" : "Pin"} conversation ${conversation.title}`}
                      title={conversation.pinned ? "Unpin conversation" : "Pin conversation"}
                    >{conversation.pinned ? "★" : "☆"}</button>
                    <button
                      className="conversation-action"
                      onClick={() => renameConversation(conversation)}
                      aria-label={`Rename conversation ${conversation.title}`}
                      title="Rename conversation"
                    >✎</button>
                    <button
                      className="conversation-action"
                      onClick={() => void updateConversation(conversation, { archived: !conversation.archived_at })}
                      aria-label={`${conversation.archived_at ? "Restore" : "Archive"} conversation ${conversation.title}`}
                      title={conversation.archived_at ? "Restore conversation" : "Archive conversation"}
                    >{conversation.archived_at ? "↩" : "▱"}</button>
                    <button
                      className="conversation-delete"
                      onClick={() => void deleteConversation(conversation)}
                      aria-label={`Delete conversation ${conversation.title}`}
                      title="Move to recently deleted"
                    >×</button>
                  </>
                )}
              </div>
            </div>
          ))}
        </div>

        <nav>
          <button
            className={activePage === "command" ? "active" : ""}
            onClick={() => openPage("command")}
          >
            Command Center
          </button>

          <button
            className={activePage === "projects" ? "active" : ""}
            onClick={() => openPage("projects", loadProjects)}
          >Projects</button>
          <button
            className={activePage === "agents" ? "active" : ""}
            onClick={() => openPage("agents", loadAgents)}
          >Agents</button>
          <button
            className={activePage === "orchestration" ? "active" : ""}
            onClick={() => openPage("orchestration", loadAgents)}
          >Orchestration</button>
          <button
            className={activePage === "research" ? "active" : ""}
            onClick={() => openPage("research")}
          >Research</button>
          <button className={activePage === "routing" ? "active" : ""} onClick={() => openPage("routing")}>Intent routing</button>
          <button
            className={activePage === "contacts" ? "active" : ""}
            onClick={() => openPage("contacts", loadContacts)}
          >Contacts</button>
          <button onClick={() => openPage("command")}>System</button>
          <button
            className={activePage === "memory" ? "active" : ""}
            onClick={() => openPage("memory", loadMemories)}
          >Memory</button>
          <button
            className={activePage === "activity" ? "active" : ""}
            onClick={() => openPage("activity", loadSafety)}
          >Activity / Audit</button>
          <button
            className={activePage === "integrations" ? "active" : ""}
            onClick={() => openPage("integrations", loadIntegrations)}
          >Integrations</button>
          <button
            className={activePage === "connections" ? "active" : ""}
            onClick={() => openPage("connections", loadProviderConnections)}
          >Provider Connections</button>
          <button
            className={activePage === "voice" ? "active" : ""}
            onClick={() => openPage("voice")}
          >Voice Settings</button>
          <button
            className={activePage === "automations" ? "active" : ""}
            onClick={() => openPage("automations", loadAutomations)}
          >Automations</button>
          <button
            className={activePage === "media" ? "active" : ""}
            onClick={() => openPage("media", loadMedia)}
          >Media Studio</button>
          <button
            className={activePage === "runner" ? "active" : ""}
            onClick={() => openPage("runner", loadRunner)}
          >Local Runner</button>
          <button
            className={activePage === "operations" ? "active" : ""}
            onClick={() => openPage("operations", loadOperations)}
          >Operations</button>
        </nav>

        <div className="sidebar-status">
          <span
            className={
              backendOnline
                ? "status-dot online"
                : "status-dot offline"
            }
          />

          {backendOnline
            ? "NEXUS ONLINE"
            : "NEXUS OFFLINE"}
        </div>
        {authRequired && <button className="sign-out" onClick={signOut}>Sign out</button>}
      </aside>

      <main className="main">
        {!networkOnline && <section className="app-status error" aria-live="polite">Device offline. The installed NEXUS shell remains available and will reconnect automatically.</section>}
        {(initialLoading || pageLoading || appError) && (
          <section className={appError ? "app-status error" : "app-status loading"} aria-live="polite">
            <span>{appError || pageLoading || "Loading NEXUS data..."}</span>
            {appError && <button onClick={() => void refreshAll()}>Retry all</button>}
            {appError && <button className="dismiss" onClick={() => setAppError("")}>Dismiss</button>}
          </section>
        )}
        {activePage === "memory" ? (
          <MemoryPage
            memories={memories}
            form={memoryForm}
            setForm={setMemoryForm}
            onSave={saveMemory}
            onDelete={deleteMemory}
          />
        ) : activePage === "projects" ? (
          <ProjectsPage projects={projects} indexing={indexing} onIndex={indexProject} />
        ) : activePage === "activity" ? (
          <ActivityPage approvals={approvals} audit={audit} onDecide={decideApproval} />
        ) : activePage === "integrations" ? (
          <IntegrationsPage integrations={integrations} onRefreshMcp={refreshMcp} />
        ) : activePage === "connections" ? (
          <ProviderConnectionsPage data={providerConnections} onConnect={connectProvider} onDisconnect={disconnectProvider} />
        ) : activePage === "agents" ? (
          <AgentsPage status={agentStatus} onRun={runSpecialist} onError={showError} />
        ) : activePage === "orchestration" ? (
          <OrchestrationPage
            agents={agentStatus.agents || []}
            plan={orchestrationPlan}
            events={orchestrationEvents}
            models={modelCatalog.models || []}
            selectedModel={selectedModel}
            setSelectedModel={setSelectedModel}
            onPreview={previewOrchestration}
            onRefresh={refreshOrchestration}
            onExecute={executeOrchestration}
            onCancel={cancelOrchestration}
            onOpenActivity={() => openPage("activity", loadSafety)}
            onError={showError}
          />
        ) : activePage === "research" ? (
          <ResearchPage result={research} onSearch={runResearch} onError={showError} />
        ) : activePage === "routing" ? (
          <IntentRoutingPage route={intentRoute} onPreview={previewIntent} onError={showError} />
        ) : activePage === "contacts" ? (
          <ContactsPage data={contactData} onRefresh={loadContacts} onError={showError} />
        ) : activePage === "voice" ? (
          <VoiceSettings playback={voicePlayback} setPlayback={setVoicePlayback} />
        ) : activePage === "automations" ? (
          <AutomationsPage jobs={automations} history={automationHistory} onCreate={createAutomation} onToggle={toggleAutomation} onRun={runAutomation} />
        ) : activePage === "media" ? (
          <MediaPage providers={mediaProviders} jobs={mediaJobs} models={modelCatalog.models || []} onRefresh={loadMedia} onError={showError} />
        ) : activePage === "runner" ? (
          <RunnerPage data={runnerData} pairing={runnerPairing} onPair={pairRunner} onCreateJob={createRunnerJob} onDisable={disableRunner} onRefresh={loadRunner} />
        ) : activePage === "operations" ? (
          <OperationsPage data={operations} onRefresh={loadOperations} />
        ) : (
          <>
        <header className="header command-header">
          <div>
            <p className="eyebrow">
              V2.2 OPERATIONS MATRIX
            </p>

            <h2>NEXUS Command Center</h2>

            <p className="description">
              Local-first intelligence. Connected services. Human authority.
            </p>
            {demoMode && <p className="connection-notice attention">RECRUITER DEMO · READ-ONLY · NO TOKEN REQUIRED</p>}
          </div>

          <div className="vision-core" aria-label="NEXUS intelligence core">
            <span className="core-orbit orbit-one" />
            <span className="core-orbit orbit-two" />
            <span className="core-eye">N</span>
            <small>{operations.state === "operational" ? "SYNCHRONIZED" : "MONITORING"}</small>
          </div>

          <div className="runtime">
            <span
              className={
                backendOnline
                  ? "status-dot online"
                  : "status-dot offline"
              }
            />

            {backendOnline
              ? "SYSTEM ONLINE"
              : "SYSTEM OFFLINE"}
          </div>
        </header>

        <section className="metrics">
          <Metric
            title="CPU"
            value={
              system
                ? `${system.cpu.cpu_percent}%`
                : "--"
            }
          />

          <Metric
            title="MEMORY"
            value={
              system
                ? `${system.memory.percent_used}%`
                : "--"
            }
          />

          <Metric
            title="AVAILABLE RAM"
            value={
              system
                ? `${system.memory.available_gb} GB`
                : "--"
            }
          />

          <Metric
            title="FREE DISK"
            value={
              system
                ? `${system.disk.free_gb} GB`
                : "--"
            }
          />
        </section>

        <section className="assistant-panel">
          <div className="panel-heading">
            <div>
              <p className="eyebrow">
                AI AGENT
              </p>

              <h3>NEXUS Assistant</h3>
            </div>

            <label className="model-picker">
              <span>MODEL</span>
              <select value={selectedModel} onChange={(event) => setSelectedModel(event.target.value)}>
                {(modelCatalog.models || []).map((item) => (
                  <option key={item.id} value={item.id} disabled={!item.configured || !item.allowed}>
                    {item.label} • {item.cost_tier}{!item.configured ? " • setup required" : ""}
                  </option>
                ))}
              </select>
            </label>
          </div>

          <div className="conversation">
            {messages.length === 0 ? (
              <div className="nexus-message">
                NEXUS is ready.
              </div>
            ) : (
              messages.map((item, index) => (
                <ChatMessage
                  key={item.id || index}
                  item={item}
                  models={(modelCatalog.models || []).filter((modelItem) => modelItem.configured && modelItem.allowed)}
                  project={projects[0]}
                  onDelete={deleteChatMessage}
                  onPin={pinChatMessage}
                  onProject={addChatMessageToProject}
                  onIntegrate={integrateChatMessage}
                />
              ))
            )}

            {loading && (
              <div className="chat-message assistant-message">
                <span className="message-role">
                  NEXUS
                </span>

                <div className="message-content">
                  Thinking...
                </div>
              </div>
            )}
          </div>

          <div className="input-area">
            <button
              className={recording ? "mic-button recording" : "mic-button"}
              onClick={recording ? () => stopRecording(false) : startRecording}
              disabled={loading}
              title={recording ? "Stop and transcribe" : "Start push-to-talk"}
            >{recording ? "Stop" : "Mic"}</button>
            <textarea
              value={message}
              onChange={(event) =>
                setMessage(event.target.value)
              }
              onKeyDown={handleKeyDown}
              placeholder="Ask NEXUS anything..."
            />

            <button
              onClick={sendMessage}
              disabled={loading}
            >
              {loading ? "..." : "Send"}
            </button>
          </div>

          {recording && <button className="cancel-recording" onClick={() => stopRecording(true)}>Cancel recording</button>}

          <p className="hint">
            Enter to send • Shift + Enter for new line
          </p>
        </section>
          </>
        )}
      </main>
    </div>
  );
}

function AccessGate({ onSubmit, error }) {
  return (
    <main className="access-gate">
      <section>
        <div className="logo">N</div>
        <p className="eyebrow">PRIVATE COMMAND CENTER</p>
        <h1>Access NEXUS</h1>
        <p className="description">Enter the personal access token stored in your cloud secret.</p>
        <form onSubmit={onSubmit}>
          <input name="access_token" type="password" autoComplete="current-password" required autoFocus placeholder="Access token" />
          <button type="submit">Unlock</button>
        </form>
        {error && <p className="access-error" role="alert">{error}</p>}
      </section>
    </main>
  );
}

function Metric({ title, value }) {
  return (
    <div className="metric-card">
      <span>{title}</span>
      <strong>{value}</strong>
    </div>
  );
}

function ChatMessage({ item, models, project, onDelete, onPin, onProject, onIntegrate }) {
  const isUser = item.role === "user";
  const [integrating, setIntegrating] = useState(false);
  const [preview, setPreview] = useState(null);
  const [working, setWorking] = useState(false);
  const [actionError, setActionError] = useState("");
  const actions = new Set((item.actions || []).map((action) => action.action));
  const persisted = Number.isInteger(item.id);

  async function previewIntegration(event) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const [provider, ...modelParts] = String(form.get("target") || "").split(":");
    setWorking(true);
    setActionError("");
    try {
      setPreview(await onIntegrate(item, {
        provider,
        model: modelParts.join(":"),
        instruction: form.get("instruction"),
        confirmed: false,
      }));
    } catch (error) {
      setActionError(error.message);
    } finally {
      setWorking(false);
    }
  }

  async function confirmIntegration() {
    setWorking(true);
    setActionError("");
    try {
      await onIntegrate(item, {
        provider: preview.provider,
        model: preview.model,
        instruction: preview.instruction,
        confirmed: true,
      });
      setIntegrating(false);
      setPreview(null);
    } catch (error) {
      setActionError(error.message);
    } finally {
      setWorking(false);
    }
  }

  return (
    <div
      className={
        isUser
          ? "chat-message user-message"
          : "chat-message assistant-message"
      }
    >
      <span className="message-role">
        {isUser ? "YOU" : "NEXUS"}
        {!isUser && item.model ? ` • ${item.model}` : ""}
      </span>

      <div className="message-content">
        {item.content}
      </div>
      {persisted && <div className="message-actions">
        <button onClick={() => void onDelete(item)}>Delete</button>
        <button onClick={() => void onPin(item)} disabled={actions.has("pinned")}>{actions.has("pinned") ? "Pinned" : "Pin"}</button>
        <button onClick={() => void onProject(item)} disabled={!project || actions.has("project")}>{actions.has("project") ? "Added to Project" : "Add to Project"}</button>
        <button onClick={() => { setIntegrating((current) => !current); setPreview(null); setActionError(""); }} disabled={!models.length}>Integrate</button>
      </div>}
      {integrating && <section className="message-integration">
        <strong>Integration handoff</strong>
        <p>Preview the exact provider, model, instruction, and message size before NEXUS sends this content outside the current chat route.</p>
        {!preview ? <form onSubmit={previewIntegration}>
          <select name="target" required defaultValue={models[0]?.id || ""}>{models.map((modelItem) => <option key={modelItem.id} value={modelItem.id}>{modelItem.label} · {modelItem.cost_tier}</option>)}</select>
          <textarea name="instruction" required maxLength="2000" defaultValue="Continue from this message and provide an actionable result." />
          <button disabled={working}>{working ? "Preparing..." : "Preview integration"}</button>
        </form> : <div className="integration-preview">
          <code>{preview.provider} · {preview.model} · {preview.cost_tier}</code>
          <p>{preview.content_characters} characters will be sent.</p>
          <p><strong>Instruction:</strong> {preview.instruction}</p>
          <blockquote>{preview.content_preview}{preview.content_characters > 500 ? "…" : ""}</blockquote>
          <div><button onClick={() => setPreview(null)} disabled={working}>Back</button><button onClick={() => void confirmIntegration()} disabled={working}>{working ? "Integrating..." : "Confirm integration"}</button></div>
        </div>}
        {actionError && <p className="action-error">{actionError}</p>}
      </section>}
    </div>
  );
}

function MemoryPage({ memories, form, setForm, onSave, onDelete }) {
  return (
    <>
      <header className="header">
        <div>
          <p className="eyebrow">LONG-TERM CONTEXT</p>
          <h2>Memory</h2>
          <p className="description">Inspect and manage durable NEXUS knowledge.</p>
        </div>
      </header>
      <form className="memory-form" onSubmit={onSave}>
        <select value={form.category} onChange={(event) => setForm({ ...form, category: event.target.value })}>
          {['fact', 'preference', 'project', 'environment', 'architecture', 'note'].map((item) => <option key={item}>{item}</option>)}
        </select>
        <input required placeholder="Key" value={form.key} onChange={(event) => setForm({ ...form, key: event.target.value })} />
        <input required placeholder="Memory content" value={form.content} onChange={(event) => setForm({ ...form, content: event.target.value })} />
        <input type="number" min="1" max="10" value={form.importance} onChange={(event) => setForm({ ...form, importance: Number(event.target.value) })} />
        <button type="submit">Remember</button>
      </form>
      <section className="memory-grid">
        {memories.map((memory) => (
          <article className="memory-card" key={memory.id}>
            <div><span>{memory.category}</span><strong>{memory.key}</strong></div>
            <p>{memory.content}</p>
            <footer>Importance {memory.importance} · {memory.source}<button onClick={() => onDelete(memory)}>Forget</button></footer>
          </article>
        ))}
        {memories.length === 0 && <p className="description">No long-term memories stored.</p>}
      </section>
    </>
  );
}

function ProjectsPage({ projects, indexing, onIndex }) {
  return (
    <>
      <header className="header">
        <div>
          <p className="eyebrow">LOCAL KNOWLEDGE</p>
          <h2>Projects</h2>
          <p className="description">Approved repositories available for local retrieval.</p>
        </div>
        <button className="page-action" onClick={onIndex} disabled={indexing}>
          {indexing ? "Indexing..." : "Re-index"}
        </button>
      </header>
      <section className="project-grid">
        {projects.map((project) => (
          <article className="project-card" key={project.id}>
            <div className="project-title"><strong>{project.name}</strong><span>{project.status}</span></div>
            <code>{project.root_path}</code>
            <div className="project-stats"><span>{project.indexed_file_count} indexed files</span><span>{project.last_indexed_at || "Never indexed"}</span></div>
          </article>
        ))}
      </section>
    </>
  );
}

function ActivityPage({ approvals, audit, onDecide }) {
  return (
    <>
      <header className="header"><div><p className="eyebrow">SAFETY CONTROL</p><h2>Activity & Audit</h2><p className="description">Review paused actions and tool execution history.</p></div></header>
      <h3 className="section-title">Pending approvals</h3>
      <section className="approval-grid">
        {approvals.map((item) => (
          <article className="approval-card" key={item.id}>
            <div><span>{item.risk_level}</span><strong>{item.proposed_action}</strong></div>
            <code>{item.tool} {JSON.stringify(item.arguments)}</code>
            <div className="approval-actions"><button onClick={() => onDecide(item.id, false)}>Deny</button><button className="approve" onClick={() => onDecide(item.id, true)}>Approve</button></div>
          </article>
        ))}
        {approvals.length === 0 && <p className="description">No actions are waiting for approval.</p>}
      </section>
      <h3 className="section-title">Audit log</h3>
      <section className="audit-list">
        {audit.map((item) => <div key={item.id}><span>{item.timestamp}</span><strong>{item.tool}</strong><code>{item.approval_state}</code></div>)}
      </section>
    </>
  );
}

function IntegrationsPage({ integrations, onRefreshMcp }) {
  return (
    <>
      <header className="header"><div><p className="eyebrow">PROVIDER ADAPTERS</p><h2>Integrations</h2><p className="description">Read-only external context configured through environment variables.</p></div></header>
      <section className="integration-grid">
        <article className="integration-card"><strong>GitHub</strong><span>{integrations.github?.configured ? "Configured" : "Not configured"}</span><p>{integrations.github?.repository || "Set NEXUS_GITHUB_REPOSITORY"}</p><code>{integrations.github?.authenticated ? "Authenticated read-only" : "Public read-only"}</code></article>
        {(integrations.mcp || []).map((server) => <article className="integration-card" key={server.name}><strong>{server.name}</strong><span>{server.status}</span><p>{server.transport} · {server.read_only ? "read-only" : "approval-gated writes"}</p><code>{server.endpoint}</code><p>{server.tool_count} allowed tools discovered{server.last_error ? ` · ${server.last_error}` : ""}</p><button className="page-action" onClick={() => onRefreshMcp(server.name)} disabled={!server.enabled || !server.auth_configured}>Discover tools</button></article>)}
        {(integrations.mcp || []).length === 0 && <article className="integration-card"><strong>MCP</strong><span>Not configured</span><p>Register servers with NEXUS_MCP_SERVERS.</p></article>}
      </section>
    </>
  );
}

function ProviderConnectionsPage({ data, onConnect, onDisconnect }) {
  return (
    <>
      <header className="header"><div><p className="eyebrow">MANUAL PROVIDER LINK</p><h2>Provider Connections</h2><p className="description">Paste a provider key, verify it through a real read-only API call, and make it immediately available to NEXUS.</p></div></header>
      <section className={`connection-notice ${data.persistent_available ? "ready" : "attention"}`}>
        <strong>{data.persistent_available ? "Encrypted persistence enabled" : "Session-only credential storage"}</strong>
        <p>{data.persistent_available ? "UI-managed keys are encrypted before database storage." : "Set NEXUS_PROVIDER_SECRET_ENCRYPTION_KEY to retain UI-managed keys across server restarts."}</p>
        {!data.write_enabled && <p>Set <code>NEXUS_ACCESS_TOKEN</code> before the Connect action is enabled.</p>}
      </section>
      <section className="provider-connection-grid">
        {(data.providers || []).map((provider) => (
          <article className={`provider-connection-card ${provider.configured ? "connected" : ""}`} key={provider.provider}>
            <header><div><strong>{provider.label}</strong><span>{provider.capabilities.join(" · ")}</span></div><em>{provider.configured ? `Connected · ${provider.mode}` : "Not connected"}</em></header>
            <p>{provider.configured ? `Credential ${provider.secret}${provider.verified_at ? ` · verified ${new Date(provider.verified_at).toLocaleString()}` : ""}` : "No provider secret is exposed to the browser."}</p>
            <code>{provider.base_url || "Custom allow-listed HTTPS endpoint"}</code>
            <form onSubmit={(event) => void onConnect(event, provider.provider)} autoComplete="off">
              <input name="api_key" type="password" required minLength="8" maxLength="4096" placeholder={provider.configured ? "Paste replacement key to rotate" : "Paste API / secret key"} autoComplete="new-password" />
              {provider.models.length > 0 ? <select name="model" defaultValue={provider.model || provider.models[0]}>{provider.models.map((model) => <option key={model} value={model}>{model}</option>)}</select> : provider.provider === "compatible" ? <input name="model" required maxLength="200" placeholder="Model ID" defaultValue={provider.model || ""} /> : null}
              {provider.custom_endpoint && <input name="base_url" type="url" required placeholder="https://allow-listed.example/v1" defaultValue={provider.base_url || ""} />}
              <button disabled={!data.write_enabled}>{provider.configured ? "Verify & rotate" : "Verify & connect"}</button>
            </form>
            <footer>
              {provider.setup_url && <a href={provider.setup_url} target="_blank" rel="noreferrer">Get provider key</a>}
              {provider.disconnectable && <button className="danger-link" onClick={() => void onDisconnect(provider.provider)}>Disconnect</button>}
            </footer>
          </article>
        ))}
      </section>
    </>
  );
}

function AgentsPage({ status, onRun, onError }) {
  const [tasks, setTasks] = useState({});
  const [results, setResults] = useState({});
  const [running, setRunning] = useState("");

  async function submit(agent) {
    const message = tasks[agent.slug]?.trim();
    if (!message) return;
    setRunning(agent.slug);
    try {
      const result = await onRun(agent.slug, message);
      setResults((current) => ({ ...current, [agent.slug]: result }));
    } catch (error) {
      onError(`${agent.name} failed`, error);
    } finally { setRunning(""); }
  }

  return (
    <>
      <header className="header"><div><p className="eyebrow">NEXUS ORCHESTRATION</p><h2>Specialist Agents</h2><p className="description">Bounded specialists selected by NEXUS for focused tasks.</p></div></header>
      <section className="agent-grid">
        {(status.agents || []).map((agent) => <article className="agent-card" key={agent.name}><strong>{agent.name}</strong><span>{agent.status} · {agent.orchestrator} controlled</span><p>{agent.description}</p><div>{agent.capabilities.join(" · ")}</div><textarea value={tasks[agent.slug] || ""} onChange={(event) => setTasks({ ...tasks, [agent.slug]: event.target.value })} placeholder={`Give ${agent.name} a bounded task`} /><button onClick={() => void submit(agent)} disabled={running === agent.slug}>{running === agent.slug ? "Running..." : "Run agent"}</button>{results[agent.slug] && <pre>{results[agent.slug].response}\n\n{results[agent.slug].provider} · {results[agent.slug].model}</pre>}</article>)}
      </section>
      <h3 className="section-title">Infrastructure adapters</h3>
      <section className="infra-grid">
        {Object.entries(status.infrastructure || {}).map(([name, item]) => <article key={name}><strong>{name}</strong><span className={item.available ? "available" : "unavailable"}>{item.available ? "Available" : "Not installed"}</span><code>{item.mode}</code></article>)}
      </section>
    </>
  );
}

function OrchestrationPage({ agents, plan, events, models, selectedModel, setSelectedModel, onPreview, onRefresh, onExecute, onCancel, onOpenActivity, onError }) {
  const [objective, setObjective] = useState("Compare the repository architecture and propose a safe implementation plan with supporting evidence.");
  const [selected, setSelected] = useState(["research", "developer"]);
  const [working, setWorking] = useState("");
  const availableModels = models.filter((model) => model.configured && model.allowed && model.capabilities?.includes("text"));

  function toggle(slug) {
    setSelected((current) => current.includes(slug) ? current.filter((item) => item !== slug) : current.length < 4 ? [...current, slug] : current);
  }

  async function preview(event) {
    event.preventDefault();
    setWorking("Creating immutable preview...");
    try { await onPreview(objective, selected); }
    catch (error) { onError("Unable to create orchestration plan", error); }
    finally { setWorking(""); }
  }

  async function refresh() {
    setWorking("Refreshing approval state...");
    try { await onRefresh(); }
    catch (error) { onError("Unable to refresh orchestration plan", error); }
    finally { setWorking(""); }
  }

  async function execute() {
    setWorking("Running bounded specialists...");
    try { await onExecute(); }
    catch (error) { onError("Unable to execute orchestration plan", error); }
    finally { setWorking(""); }
  }

  async function cancel() {
    setWorking("Stopping bounded execution...");
    try { await onCancel(); }
    catch (error) { onError("Unable to stop orchestration plan", error); }
    finally { setWorking(""); }
  }

  const executable = plan && (plan.state === "previewed" || plan.state === "authorized") && plan.risk_level !== "DESTRUCTIVE";
  return <>
    <header className="header"><div><p className="eyebrow">BOUNDED MULTI-AGENT CONTROL</p><h2>Orchestration Plans</h2><p className="description">Preview an immutable plan, verify its safety boundary, then explicitly run up to four read-only specialists with no tools or recursive delegation.</p></div></header>
    <form className="orchestration-form" onSubmit={preview}>
      <textarea value={objective} maxLength="4000" onChange={(event) => setObjective(event.target.value)} required />
      <select value={selectedModel} onChange={(event) => setSelectedModel(event.target.value)}>{availableModels.map((model) => <option key={model.id} value={model.id}>{model.label} · {model.cost_tier}</option>)}</select>
      <fieldset><legend>Specialists · choose up to four</legend>{agents.map((agent) => <label key={agent.slug}><input type="checkbox" checked={selected.includes(agent.slug)} onChange={() => toggle(agent.slug)} /> {agent.name}</label>)}</fieldset>
      <button disabled={Boolean(working)}>{working || "Preview plan"}</button>
    </form>
    {plan && <section className="orchestration-plan">
      <header><div><strong>Plan {plan.id.slice(0, 8)}</strong><span>{plan.state.replaceAll("_", " ")}</span></div><code>{plan.risk_level} · {plan.provider}:{plan.model}</code></header>
      <p>{plan.objective}</p>
      <div className="plan-limits"><span>{plan.steps.length} steps</span><span>{plan.limits.max_provider_calls} calls max</span><span>{plan.limits.timeout_seconds}s timeout</span><span>tools blocked</span><span>recursion blocked</span></div>
      <ol>{plan.steps.map((step) => <li key={step.specialist}><strong>{step.name}</strong><span>{step.risk_level} · analysis only</span><p>{step.instruction}</p></li>)}</ol>
      {plan.state === "blocked" && <p className="app-status error">Destructive orchestration objectives are blocked by policy.</p>}
      {plan.state === "approval_pending" && <div className="orchestration-actions"><button onClick={onOpenActivity}>Review approval</button><button onClick={() => void refresh()} disabled={Boolean(working)}>Refresh state</button></div>}
      {executable && <div className="orchestration-actions"><button onClick={() => void execute()} disabled={Boolean(working)}>{working || "Confirm & execute plan"}</button></div>}
      {["queued", "running", "cancellation_requested"].includes(plan.state) && <div className="orchestration-actions"><span className="live-indicator">{plan.state === "cancellation_requested" ? "Stop requested" : "Live execution connected"}</span><button onClick={() => void refresh()} disabled={Boolean(working)}>Refresh snapshot</button>{plan.cancellable && <button className="cancel-execution" onClick={() => void cancel()} disabled={working === "Stopping bounded execution..."}>Stop execution</button>}</div>}
      <h3>Live event timeline</h3>
      <div className="orchestration-events">{events.map((event) => <div key={event.id}><time>{new Date(event.timestamp).toLocaleTimeString()}</time><strong>{event.event_type.replaceAll("_", " ")}</strong><span>{event.specialist || event.state}</span><p>{event.detail}</p></div>)}</div>
      {plan.summary && <p className="orchestration-summary">{plan.summary}</p>}
      {(plan.results || []).map((result) => <article className="orchestration-result" key={`${result.position}-${result.specialist}`}><header><strong>{result.name}</strong><span>{result.status}</span></header>{result.response && <pre>{result.response}</pre>}{result.error && <code>{result.error}</code>}</article>)}
    </section>}
  </>;
}

function VoiceSettings({ playback, setPlayback }) {
  return (
    <>
      <header className="header"><div><p className="eyebrow">LOCAL-FIRST AUDIO</p><h2>Voice Settings</h2><p className="description">Push-to-talk by default, with an explicitly launched offline wake-word companion.</p></div></header>
      <section className="voice-settings">
        <label><input type="checkbox" checked={playback} onChange={(event) => setPlayback(event.target.checked)} /> Speak NEXUS responses using browser speech synthesis</label>
        <p>Speech-to-text audio is sent only to the local NEXUS backend. Configure <code>NEXUS_VOICE_STT_PROVIDER=faster-whisper</code> for local transcription.</p>
        <div className="wakeword-card">
          <div><span className="status-dot ready" /><strong>Optional offline companion</strong></div>
          <p>The companion listens only after you launch it with <code>--enable</code>. It uses the allow-listed <code>hey_jarvis</code> ONNX model at 16 kHz, retains no microphone frames, uploads no audio, and never runs a command.</p>
          <code>.venv\Scripts\python.exe scripts\nexus_wakeword.py --enable --open-command-center</code>
        </div>
      </section>
    </>
  );
}

function AutomationsPage({ jobs, history, onCreate, onToggle, onRun }) {
  return (
    <>
      <header className="header"><div><p className="eyebrow">CONTROLLED BACKGROUND WORK</p><h2>Automations</h2><p className="description">Persistent allow-listed jobs governed by tool safety policy.</p></div></header>
      <form className="automation-form" onSubmit={onCreate}>
        <input name="name" required placeholder="Task name" />
        <input name="description" placeholder="Description or reminder text" />
        <select name="job_type" defaultValue="system_health"><option value="system_health">System health</option><option value="project_health">Project health</option><option value="git_status">Git status</option><option value="docker_status">Docker status</option><option value="infrastructure_check">Infrastructure check</option><option value="research">Research</option><option value="reminder">Reminder</option></select>
        <input name="schedule" required defaultValue="interval:3600" />
        <input name="agent" defaultValue="NEXUS" />
        <button type="submit">Schedule</button>
      </form>
      <section className="automation-list">
        {jobs.map((job) => <article key={job.id}><div><strong>{job.name}</strong><span>{job.status}</span></div><p>{job.description}</p><code>{job.job_type} · {job.schedule} · next {job.next_run}</code><footer><button onClick={() => onToggle(job)}>{job.enabled ? "Disable" : "Enable"}</button><button onClick={() => onRun(job)} disabled={!job.enabled}>Run now</button></footer></article>)}
        {jobs.length === 0 && <p className="description">No automations configured.</p>}
      </section>
      <h3 className="section-title">Execution logs</h3>
      <section className="audit-list">{history.map((item) => <div key={item.id}><span>{item.started_at}</span><strong>{item.job_id}</strong><code>{item.status}</code></div>)}</section>
    </>
  );
}

function MediaPage({ providers, jobs, models, onRefresh, onError }) {
  const configured = providers.filter((provider) => provider.configured && provider.allowed);
  const visionModels = models.filter((model) => model.configured && model.allowed && model.capabilities?.includes("vision"));
  const [working, setWorking] = useState("");
  const [analysis, setAnalysis] = useState("");
  const [preview, setPreview] = useState(null);

  useEffect(() => () => {
    if (preview?.url) URL.revokeObjectURL(preview.url);
  }, [preview]);

  async function analyzeImage(event) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const [provider, ...modelParts] = String(form.get("vision_model") || "").split(":");
    form.delete("vision_model");
    if (provider) form.set("provider", provider);
    if (modelParts.length) form.set("model", modelParts.join(":"));
    setWorking("Understanding image...");
    try {
      const result = await requestJson("/api/media/understand", { method: "POST", body: form });
      setAnalysis(`${result.response}\n\n${result.provider} · ${result.model}`);
    } catch (error) {
      onError("Image understanding failed", error);
    } finally { setWorking(""); }
  }

  async function generate(event, kind) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const body = Object.fromEntries(form);
    if (kind === "images") {
      body.width = Number(body.width);
      body.height = Number(body.height);
    } else {
      body.duration = Number(body.duration);
    }
    setWorking(kind === "images" ? "Generating image..." : "Submitting video...");
    try {
      const job = await requestJson(`/api/media/${kind}`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
      });
      await onRefresh();
      if (job.asset_url) await openAsset(job);
    } catch (error) {
      onError(`${kind === "images" ? "Image" : "Video"} generation failed`, error);
    } finally { setWorking(""); }
  }

  async function openAsset(job) {
    setWorking("Loading protected media...");
    try {
      const url = await requestMedia(job.asset_url);
      setPreview({ url, kind: job.kind, prompt: job.prompt });
    } catch (error) {
      onError("Unable to load media", error);
    } finally { setWorking(""); }
  }

  const defaultProvider = configured[0];
  return (
    <>
      <header className="header"><div><p className="eyebrow">MULTIMODAL WORKSPACE</p><h2>Media Studio</h2><p className="description">Understand images with vision models, or create images and asynchronous videos through configured providers.</p></div><button className="page-action" onClick={() => void onRefresh()}>Refresh jobs</button></header>
      {working && <p className="media-working">{working}</p>}
      <section className="media-grid">
        <form className="media-form" onSubmit={analyzeImage}>
          <h3>Image to text</h3>
          <input name="image" type="file" accept="image/png,image/jpeg,image/webp" required />
          <textarea name="prompt" defaultValue="Describe this image and extract all visible text." />
          <select name="vision_model" required defaultValue={visionModels[0] ? `${visionModels[0].provider}:${visionModels[0].model}` : ""}>
            {visionModels.length === 0 && <option value="">No configured vision model</option>}
            {visionModels.map((model) => <option key={`${model.provider}:${model.model}`} value={`${model.provider}:${model.model}`}>{model.label} · {model.cost_tier}</option>)}
          </select>
          <button disabled={!visionModels.length || Boolean(working)}>Understand image</button>
          {analysis && <pre className="media-analysis">{analysis}</pre>}
        </form>
        <form className="media-form" onSubmit={(event) => generate(event, "images")}>
          <h3>Image generator</h3>
          <textarea name="prompt" required placeholder="Describe the image to create" />
          <ProviderFields providers={configured} kind="image" />
          <div className="media-size"><select name="width" defaultValue="1024"><option>512</option><option>768</option><option>1024</option><option>1280</option><option>1536</option></select><select name="height" defaultValue="1024"><option>512</option><option>768</option><option>1024</option><option>1280</option><option>1536</option></select></div>
          <button disabled={!defaultProvider || Boolean(working)}>Generate image</button>
          {!configured.length && <p>Add a Pollinations key for free credits, or explicitly enable a paid provider.</p>}
        </form>
        <form className="media-form" onSubmit={(event) => generate(event, "videos")}>
          <h3>Video generator</h3>
          <textarea name="prompt" required placeholder="Describe the video to create" />
          <ProviderFields providers={configured} kind="video" />
          <div className="media-size"><input name="duration" type="number" min="2" max="20" defaultValue="4" /><select name="aspect_ratio" defaultValue="16:9"><option>16:9</option><option>9:16</option></select></div>
          <button disabled={!defaultProvider || Boolean(working)}>Queue video</button>
          <p>Video generation runs in the background; refresh jobs to see completion.</p>
        </form>
      </section>
      {preview && <section className="media-preview"><h3>Protected preview</h3><p>{preview.prompt}</p>{preview.kind === "video" ? <video src={preview.url} controls /> : <img src={preview.url} alt={preview.prompt} />}</section>}
      <h3 className="section-title">Generation jobs</h3>
      <section className="media-jobs">
        {jobs.map((job) => <article key={job.id}><div><strong>{job.kind} · {job.model}</strong><span>{job.status}</span></div><p>{job.prompt}</p>{job.error && <code>{job.error}</code>}{job.asset_url && <button onClick={() => void openAsset(job)}>Open protected asset</button>}</article>)}
        {!jobs.length && <p className="description">No media has been generated yet.</p>}
      </section>
    </>
  );
}

function ProviderFields({ providers, kind }) {
  const options = providers.flatMap((provider) => (kind === "image" ? provider.image_models : provider.video_models).map((model) => ({ provider: provider.provider, model, cost: provider.cost_tier })));
  const first = options[0];
  const [selection, setSelection] = useState(first ? `${first.provider}:${first.model}` : "");
  const [provider, ...modelParts] = selection.split(":");
  return <><select value={selection} onChange={(event) => setSelection(event.target.value)} disabled={!options.length}>{!options.length && <option value="">No configured provider</option>}{options.map((item) => <option key={`${item.provider}:${item.model}`} value={`${item.provider}:${item.model}`}>{item.provider} · {item.model} · {item.cost}</option>)}</select><input type="hidden" name="provider" value={provider} /><input type="hidden" name="model" value={modelParts.join(":")} /></>;
}

function IntentRoutingPage({ route, onPreview, onError }) {
  const [message, setMessage] = useState("Search current news about local AI");
  async function submit(event) { event.preventDefault(); try { await onPreview(message); } catch (error) { onError("Unable to preview route", error); } }
  const nodes = route?.nodes || ["message", "intent_classifier", "safety_policy", "destination"];
  return <><header className="header"><div><p className="eyebrow">EXPLAINABLE, NON-EXECUTING</p><h2>Intent routing</h2><p className="description">Preview how NEXUS will classify a request before any action is taken.</p></div></header><form className="media-form" onSubmit={submit}><textarea value={message} maxLength="2000" onChange={(event) => setMessage(event.target.value)} /><button>Preview route</button></form><section className="media-jobs"><article><div>{nodes.map((node, index) => <span key={node}>{index ? " → " : ""}<strong>{node.replaceAll("_", " ")}</strong></span>)}</div>{route && <><p>{route.detail}</p><code>{route.risk_level} · {route.approval_required ? "approval required" : "automatic read-only"}</code></>}</article></section></>;
}

function ContactsPage({ data, onRefresh, onError }) {
  const [selected, setSelected] = useState("");
  const [preview, setPreview] = useState(null);

  async function addContact(event) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    try {
      const values = Object.fromEntries(form);
      values.consented_at = new Date(values.consented_at).toISOString();
      if (values.consent_expires_at) values.consent_expires_at = new Date(values.consent_expires_at).toISOString();
      await requestJson("/api/contacts", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(values) });
      event.currentTarget.reset(); await onRefresh();
    } catch (error) { onError("Unable to save contact", error); }
  }
  async function compose(event) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    try {
      const subject = String(form.get("subject") || "");
      const body = String(form.get("body") || "");
      const result = await requestJson(`/api/contacts/${selected}/messages`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ subject, body, confirmed: false }) });
      setPreview({ ...result, draft: { subject, body } });
    } catch (error) { onError("Unable to prepare email", error); }
  }
  async function requestApproval() {
    if (!preview?.draft || !selected) return;
    try {
      await requestJson(`/api/contacts/${selected}/messages`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ...preview.draft, confirmed: true }) });
      setPreview(null); await onRefresh();
    } catch (error) { onError("Unable to request delivery approval", error); }
  }
  async function optOut() {
    if (!selected || !window.confirm("Opt this contact out? Future sends will be blocked.")) return;
    try { await requestJson(`/api/contacts/${selected}/opt-out`, { method: "POST" }); setSelected(""); await onRefresh(); } catch (error) { onError("Unable to opt out contact", error); }
  }
  return <>
    <header className="header"><div><p className="eyebrow">CONSENT-BOUND MESSAGING</p><h2>Contacts & Email</h2><p className="description">Only documented opt-in contacts can receive a plain-text email, and every send needs final approval.</p></div></header>
    {!data.smtp_configured && <p className="app-status error">SMTP is not configured. Add protected NEXUS_SMTP_HOST and NEXUS_SMTP_FROM_ADDRESS settings before approving a delivery.</p>}
    <section className="media-grid"><form className="media-form" onSubmit={addContact}><h3>Add consented contact</h3><input name="name" required maxLength="100" placeholder="Name" /><input name="email" type="email" required maxLength="254" placeholder="Email" /><input name="consent_source" required maxLength="200" placeholder="Consent source (for example: signed form)" /><input name="consent_subject" required maxLength="300" placeholder="Permitted subject" /><input name="consented_at" type="datetime-local" required /><input name="consent_expires_at" type="datetime-local" /><button>Add opted-in contact</button></form><form className="media-form" onSubmit={(event) => void compose(event)}><h3>Prepare email</h3><select value={selected} required onChange={(event) => { setSelected(event.target.value); setPreview(null); }}><option value="" disabled>Select consented contact</option>{data.contacts.filter((contact) => contact.consent_state === "opted_in").map((contact) => <option key={contact.id} value={contact.id}>{contact.name} · {contact.email}</option>)}</select><input name="subject" required maxLength="160" placeholder="Subject" /><textarea name="body" required maxLength="5000" placeholder="Plain-text message" /><button disabled={!selected}>Preview send</button>{selected && <button type="button" className="danger-link" onClick={() => void optOut()}>Opt out selected contact</button>}</form></section>
    {preview && <section className="media-jobs"><article><div><strong>Confirmation required</strong><span>{preview.provider}</span></div><p>To {preview.contact.name} · {preview.contact.email}</p><p>{preview.subject} · {preview.body_characters} characters</p><code>Consent: {preview.consent.source} · {preview.consent.subject}</code><button onClick={() => void requestApproval()}>Request final approval</button></article></section>}
    <h3 className="section-title">Delivery history</h3><section className="media-jobs">{data.messages.map((message) => <article key={message.id}><div><strong>{message.subject}</strong><span>{message.state}</span></div><code>{message.created_at} · {message.body_characters} characters</code></article>)}{!data.messages.length && <p className="description">No delivery attempts.</p>}</section>
  </>;
}

function ResearchPage({ result, onSearch, onError }) {
  const [query, setQuery] = useState("");
  const [working, setWorking] = useState("");

  async function submit(event, kind) {
    event.preventDefault();
    if (query.trim().length < 2) return;
    setWorking(kind);
    try { await onSearch(kind, query.trim()); } catch (error) { onError("Research request failed", error); } finally { setWorking(""); }
  }

  return <>
    <header className="header"><div><p className="eyebrow">READ-ONLY EXTERNAL RESEARCH</p><h2>Structured Search & News</h2><p className="description">Public-provider summaries only. NEXUS never follows result links, submits credentials, or stores your query.</p></div></header>
    <section className="media-grid"><form className="media-form" onSubmit={(event) => void submit(event, "search")}><h3>Web search</h3><input value={query} onChange={(event) => setQuery(event.target.value)} minLength="2" maxLength="200" required placeholder="Research query" /><button disabled={Boolean(working)}>{working === "search" ? "Searching..." : "Search"}</button></form><form className="media-form" onSubmit={(event) => void submit(event, "news")}><h3>News search</h3><input value={query} onChange={(event) => setQuery(event.target.value)} minLength="2" maxLength="200" required placeholder="Research query" /><button disabled={Boolean(working)}>{working === "news" ? "Loading..." : "Get news"}</button></form></section>
    {result && <section className="media-jobs"><h3 className="section-title">{result.provider} · {result.query}</h3>{result.results.length ? result.results.map((item) => <article key={item.url}><div><strong>{item.title}</strong><span>{item.source}</span></div><p>{item.snippet || item.summary}</p>{item.published_at && <code>{item.published_at}</code>}<a href={item.url} target="_blank" rel="noreferrer">Open source</a></article>) : <p className="description">No structured results returned.</p>}</section>}
  </>;
}

function OperationsPage({ data, onRefresh }) {
  const readyCount = (data.services || []).filter((item) => item.state === "ready").length;
  return (
    <>
      <header className="header operations-header">
        <div><p className="eyebrow">REAL-WORLD READINESS</p><h2>Operations Matrix</h2><p className="description">Every service reports whether it is ready, blocked by policy, or needs setup.</p></div>
        <div className={`runtime ${data.state === "operational" ? "matrix-ready" : "matrix-attention"}`}><span className={`status-dot ${data.state === "operational" ? "online" : "warning"}`} />{String(data.state || "attention").toUpperCase()}</div>
      </header>
      <section className="ops-summary"><strong>{readyCount}</strong><span>services ready</span><code>{data.approval_policy}</code><button className="page-action" onClick={() => void onRefresh()}>Run readiness scan</button></section>
      <section className="operations-grid">
        {(data.services || []).map((service) => <article key={service.name} className={`operation-card ${service.state}`}><div><span className="service-glyph" /><strong>{service.name.replaceAll("-", " ")}</strong><em>{service.state.replaceAll("_", " ")}</em></div><p>{service.detail}</p>{service.setup_url && service.state !== "ready" && <a href={service.setup_url} target="_blank" rel="noreferrer">Open provider setup</a>}</article>)}
      </section>
      <h3 className="section-title">Model matrix</h3>
      <section className="model-matrix">
        {(data.models || []).map((model) => <article key={model.id}><div><strong>{model.label}</strong><span className={model.state}>{model.state.replaceAll("_", " ")}</span></div><p>{model.provider} · {model.cost_tier} · {model.capabilities.join(" / ")}</p><small>{model.notes}</small>{model.setup_url && model.state !== "ready" && <a href={model.setup_url} target="_blank" rel="noreferrer">Configure</a>}</article>)}
      </section>
    </>
  );
}

function RunnerPage({ data, pairing, onPair, onCreateJob, onDisable, onRefresh }) {
  const [selectedTool, setSelectedTool] = useState("");
  return (
    <>
      <header className="header"><div><p className="eyebrow">OUTBOUND-ONLY MACHINE BRIDGE</p><h2>Local Runner</h2><p className="description">Run allow-listed jobs on your approved local root without exposing an inbound port.</p></div><button className="page-action" onClick={() => void onRefresh()}>Refresh</button></header>
      <section className="runner-grid">
        <form className="media-form" onSubmit={onPair}>
          <h3>Pair a machine</h3>
          <input name="name" required placeholder="Development laptop" />
          <button>Generate one-time credentials</button>
          <p>The runner token is shown once. Store it locally, never in Git.</p>
        </form>
        <form className="media-form" onSubmit={onCreateJob}>
          <h3>Queue a job</h3>
          <select name="node_id" required defaultValue=""><option value="" disabled>Select runner</option>{data.nodes.map((node) => <option value={node.id} key={node.id}>{node.name}</option>)}</select>
          <select name="tool" required value={selectedTool} onChange={(event) => setSelectedTool(event.target.value)}><option value="" disabled>Select tool</option>{data.tools.map((tool) => <option value={tool.name} key={tool.name}>{tool.name} · {tool.risk_level}</option>)}</select>
          {selectedTool === "speak_text" ? <div className="runner-speech-fields">
            <textarea name="speech_text" required maxLength="2000" placeholder="Text for the local machine to speak" />
            <label>Rate <input name="speech_rate" type="number" min="120" max="220" defaultValue="170" /></label>
            <label>Volume <input name="speech_volume" type="number" min="0" max="1" step="0.1" defaultValue="1" /></label>
            <label>Voice index <input name="voice_index" type="number" min="0" max="20" placeholder="System default" /></label>
          </div> : selectedTool === "media_control" ? <div className="runner-speech-fields">
            <label>Fixed media action <select name="media_action" defaultValue="play_pause"><option value="play_pause">Play / pause</option><option value="next_track">Next track</option><option value="previous_track">Previous track</option><option value="stop">Stop</option><option value="volume_mute">Mute / unmute</option><option value="volume_down">Volume down</option><option value="volume_up">Volume up</option></select></label>
            <label>Repeat <input name="media_repeat" type="number" min="1" max="10" defaultValue="1" /></label>
          </div> : selectedTool === "launch_app" ? <div className="runner-speech-fields">
            <label>Allowlisted application ID <input name="app_id" required pattern="[a-z0-9][a-z0-9_-]{0,49}" placeholder="notepad" /></label>
            <p>The ID must already exist in the paired machine's local allowlist. Paths and arguments cannot be submitted here.</p>
          </div> : selectedTool === "capture_screenshot" ? <div className="runner-speech-fields">
            <p>Capture is approval-gated. The image is sent outbound over the runner's authenticated HTTPS connection and stored only as a protected media asset.</p>
          </div> : <textarea name="arguments" defaultValue="{}" aria-label="JSON arguments" />}
          <button disabled={!data.nodes.length}>Queue job</button>
          <p>Local speech, media controls, and safe writes appear in Activity for approval. Destructive tools do not exist in the runner.</p>
        </form>
      </section>
      {pairing && <section className="runner-secret"><h3>Copy these values now</h3><p>This token cannot be shown again.</p><code>NEXUS_RUNNER_ID={pairing.node.id}</code><code>NEXUS_RUNNER_TOKEN={pairing.runner_token}</code><code>NEXUS_URL={window.location.origin}</code></section>}
      <h3 className="section-title">Paired machines</h3>
      <section className="media-jobs">{data.nodes.map((node) => <article key={node.id}><div><strong>{node.name}</strong><span>{node.active ? "paired" : "disabled"}</span></div><p>{node.capabilities.join(" · ")}</p><code>Last seen: {node.last_seen_at || "Never"}</code>{node.active && <button onClick={() => onDisable(node)}>Disable runner</button>}</article>)}{!data.nodes.length && <p className="description">No local runner paired.</p>}</section>
      <h3 className="section-title">Runner jobs</h3>
      <section className="media-jobs">{data.jobs.map((job) => <article key={job.id}><div><strong>{job.tool}</strong><span>{job.state}</span></div><p>{JSON.stringify(job.arguments)}</p>{job.result && <pre className="media-analysis">{JSON.stringify(job.result, null, 2)}</pre>}</article>)}{!data.jobs.length && <p className="description">No runner jobs queued.</p>}</section>
    </>
  );
}

export default App;
