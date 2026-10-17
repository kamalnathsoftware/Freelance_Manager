import type {
  AnalyticsOverview, ApiErrorBody, ApiKeyInfo, GoalProgress, OpsOverview, TeamMember, Workspace, AutomationMeta, AutomationRule, AutomationRun, Briefing, FormDef, FormSubmission, PublicForm, Requirements, CalendarItem, EarningsReport, Expense, FinanceSummary, Invoice, InvoiceItem, Order, Payment, Project, Task, TimeEntry, AppNotification, ChannelInfo, Delivery, NotificationPrefs, CannedResponse, ChatMessage, Client, ClientInput, ConvStatus, Conversation, AuditEntry, Completeness, Gig, GigInput, Job, JobInput, LoginOut, MasterProfile, PlatformAccount, PlatformInfo,
  PlatformEvent, PlatformProfile, Proposal, SearchResults, SendResult, SlaAlerts, ProposalAnalytics, ProposalTemplate, SavedSearch, SessionInfo, Stage, SubmitResult,
  RealtimeEvent, Suggestion, SyncLog, TokenPair, User,
} from "./types";
import type { JobStatus, OutreachChannel, PFDraft, PFGoal, PFJob, PFJobQuery, PFLead, PFLeadInput, PFLeadPatch, PFSettings, PFInvoice, PFInvoiceInput, PFProposal, PFProposalInput, PFRefreshResult, PFSettingsInput, PFStats, PFTzOverlap, PFSource, PFTemplate, PFTemplateInput } from "./project-finder";

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string, public details?: unknown) {
    super(message);
  }
}

export interface TokenStore {
  get(): Promise<TokenPair | null> | TokenPair | null;
  set(t: TokenPair | null): Promise<void> | void;
}

/** Framework-agnostic API client with transparent refresh-token rotation. Used by web and mobile. */
export class ApiClient {
  private refreshing: Promise<TokenPair | null> | null = null;
  constructor(private baseUrl: string, private store: TokenStore, private onLoggedOut?: () => void, private getWorkspace?: () => string | null) {}

  private async raw(path: string, init: RequestInit, token?: string): Promise<Response> {
    const headers: Record<string, string> = { "Content-Type": "application/json", ...(init.headers as object) };
    if (token) headers.Authorization = `Bearer ${token}`;
    const ws = /^\/(me|auth|team|api-keys)(\/|\?|$)/.test(path) ? null : this.getWorkspace?.(); // account/team calls always target you
    if (ws && token) headers["X-Workspace"] = ws; // act inside a workspace you were invited to
    return fetch(`${this.baseUrl}/api/v1${path}`, { ...init, headers });
  }

  private async refresh(): Promise<TokenPair | null> {
    if (!this.refreshing) {
      this.refreshing = (async () => {
        const cur = await this.store.get();
        if (!cur) return null;
        const r = await this.raw("/auth/refresh", { method: "POST", body: JSON.stringify({ refresh_token: cur.refresh_token }) });
        if (!r.ok) { await this.store.set(null); this.onLoggedOut?.(); return null; }
        const t = (await r.json()) as TokenPair;
        await this.store.set(t);
        return t;
      })().finally(() => { this.refreshing = null; });
    }
    return this.refreshing;
  }

  async request<T>(path: string, init: RequestInit = {}, auth = true): Promise<T> {
    let tokens = auth ? await this.store.get() : null;
    let res = await this.raw(path, init, tokens?.access_token);
    if (res.status === 401 && auth && tokens) {
      tokens = await this.refresh();
      if (tokens) res = await this.raw(path, init, tokens.access_token);
    }
    if (!res.ok) {
      let body: ApiErrorBody | null = null;
      try { body = await res.json(); } catch { /* non-JSON error */ }
      throw new ApiError(res.status, body?.error.code ?? "unknown", body?.error.message ?? res.statusText, body?.error.details);
    }
    return (res.status === 204 ? undefined : await res.json()) as T;
  }

  private post<T>(path: string, body?: unknown, auth = true) {
    return this.request<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) }, auth);
  }

  // auth
  signup = async (b: { email: string; password: string; full_name?: string }) => {
    const t = await this.post<TokenPair>("/auth/signup", b, false); await this.store.set(t); return t;
  };
  login = async (b: { email: string; password: string }) => {
    const r = await this.post<LoginOut>("/auth/login", b, false);
    if (r.tokens) await this.store.set(r.tokens);
    return r;
  };
  login2fa = async (mfa_token: string, code: string) => {
    const t = await this.post<TokenPair>("/auth/login/2fa", { mfa_token, code }, false); await this.store.set(t); return t;
  };
  logout = async () => { try { await this.post("/auth/logout"); } finally { await this.store.set(null); } };
  forgotPassword = (email: string) => this.post("/auth/forgot-password", { email }, false);
  resetPassword = (token: string, new_password: string) => this.post("/auth/reset-password", { token, new_password }, false);
  verifyEmail = (token: string) => this.post("/auth/verify-email", { token }, false);

  // account
  me = () => this.request<User>("/me");
  updateMe = (b: Partial<Pick<User, "full_name" | "timezone" | "locale" | "settings">>) =>
    this.request<User>("/me", { method: "PATCH", body: JSON.stringify(b) });
  sessions = () => this.request<SessionInfo[]>("/me/sessions");
  revokeSession = (id: string) => this.request(`/me/sessions/${id}`, { method: "DELETE" });
  auditLog = () => this.request<AuditEntry[]>("/me/audit-log");
  setup2fa = () => this.post<{ secret: string; otpauth_uri: string }>("/me/2fa/setup");
  enable2fa = (code: string) => this.post("/me/2fa/enable", { code });
  disable2fa = (code: string) => this.post("/me/2fa/disable", { code });
  exportData = () => this.request<Record<string, unknown>>("/me/export");

  // platforms
  platformCatalog = () => this.request<PlatformInfo[]>("/platforms/catalog");
  accounts = () => this.request<PlatformAccount[]>("/platforms/accounts");
  addAccount = (b: { platform: string; label?: string; username?: string; profile_url?: string }) => this.post<PlatformAccount>("/platforms/accounts", b);
  updateAccount = (id: string, b: Partial<Pick<PlatformAccount, "label" | "username" | "profile_url" | "stats">>) =>
    this.request<PlatformAccount>(`/platforms/accounts/${id}`, { method: "PATCH", body: JSON.stringify(b) });
  connectToken = (id: string, access_token: string) =>
    this.request<PlatformAccount>(`/platforms/accounts/${id}/token`, { method: "PUT", body: JSON.stringify({ access_token }) });
  removeAccount = (id: string) => this.request(`/platforms/accounts/${id}`, { method: "DELETE" });
  syncAccount = (id: string) => this.post<SyncLog>(`/platforms/accounts/${id}/sync`);
  syncLogs = (id: string) => this.request<SyncLog[]>(`/platforms/accounts/${id}/logs`);

  // profiles
  master = () => this.request<MasterProfile | null>("/profile/master");
  saveMaster = (b: MasterProfile) => this.request<MasterProfile>("/profile/master", { method: "PUT", body: JSON.stringify(b) });
  completeness = (platform?: string) => this.request<Completeness>(`/profile/completeness${platform ? `?platform=${platform}` : ""}`);
  platformProfiles = () => this.request<PlatformProfile[]>("/profile/platforms");
  derivePlatformProfile = (accountId: string) => this.post<PlatformProfile>(`/profile/platforms/${accountId}/derive`);
  editPlatformProfile = (accountId: string, b: Partial<Pick<PlatformProfile, "headline" | "bio" | "skills" | "hourly_rate">>) =>
    this.request<PlatformProfile>(`/profile/platforms/${accountId}`, { method: "PATCH", body: JSON.stringify(b) });

  // gigs
  gigs = () => this.request<Gig[]>("/gigs");
  createGig = (b: GigInput) => this.post<Gig>("/gigs", b);
  updateGig = (id: string, b: GigInput) => this.request<Gig>(`/gigs/${id}`, { method: "PUT", body: JSON.stringify(b) });
  deleteGig = (id: string) => this.request(`/gigs/${id}`, { method: "DELETE" });
  cloneGig = (id: string, account_ids: string[]) => this.post(`/gigs/${id}/clone`, { account_ids });

  // AI (suggestions only — caller must get user approval before saving)
  aiRewrite = (b: { kind: "headline" | "bio" | "gig_title" | "gig_description"; text: string; platform?: string; tone?: string; keywords?: string[] }) =>
    this.post<Suggestion>("/ai/rewrite", b);

  // jobs
  jobs = (q: { platform?: string; min_score?: number; q?: string } = {}) => {
    const qs = new URLSearchParams(Object.entries(q).filter(([, v]) => v !== undefined && v !== "").map(([k, v]) => [k, String(v)])).toString();
    return this.request<Job[]>(`/jobs${qs ? `?${qs}` : ""}`);
  };
  addJob = (b: JobInput) => this.post<Job>("/jobs", b);
  dismissJob = (id: string) => this.request<Job>(`/jobs/${id}/dismiss`, { method: "PATCH" });
  shortlistJob = (id: string) => this.post<{ proposal_id: string; stage: Stage }>(`/jobs/${id}/shortlist`);
  bidSuggestion = (id: string) => this.request<{ amount: number | null; rationale: string }>(`/jobs/${id}/bid-suggestion`);
  searches = () => this.request<SavedSearch[]>("/searches");
  addSearch = (b: Omit<SavedSearch, "id">) => this.post<SavedSearch>("/searches", b);
  deleteSearch = (id: string) => this.request(`/searches/${id}`, { method: "DELETE" });

  // proposals & pipeline
  templates = () => this.request<ProposalTemplate[]>("/proposal-templates");
  addTemplate = (b: Omit<ProposalTemplate, "id">) => this.post<ProposalTemplate>("/proposal-templates", b);
  pipeline = () => this.request<Record<Stage, Proposal[]>>("/pipeline");
  proposal = (id: string) => this.request<Proposal>(`/proposals/${id}`);
  updateProposal = (id: string, b: Partial<Pick<Proposal, "body" | "bid_amount" | "account_id" | "credits_used" | "follow_up_at">>) =>
    this.request<Proposal>(`/proposals/${id}`, { method: "PATCH", body: JSON.stringify(b) });
  draftProposal = (id: string, b: { template_id?: string; use_ai?: boolean; tone?: string }) => this.post<Proposal>(`/proposals/${id}/draft`, b);
  approveProposal = (id: string) => this.post<Proposal>(`/proposals/${id}/approve`);
  submitProposal = (id: string) => this.post<SubmitResult>(`/proposals/${id}/submit`);
  markSubmitted = (id: string) => this.post<Proposal>(`/proposals/${id}/mark-submitted`);
  moveProposal = (id: string, stage: Stage, lost_reason = "") =>
    this.request<Proposal>(`/proposals/${id}/move`, { method: "PATCH", body: JSON.stringify({ stage, lost_reason }) });
  proposalAnalytics = () => this.request<ProposalAnalytics>("/analytics/proposals");

  // ingestion
  apiKeys = () => this.request<ApiKeyInfo[]>("/api-keys");
  createApiKey = (name: string) => this.post<{ id: string; key: string; note: string }>("/api-keys", { name });
  revokeApiKey = (id: string) => this.request(`/api-keys/${id}`, { method: "DELETE" });
  events = (kind?: string) => this.request<PlatformEvent[]>(`/events${kind ? `?kind=${kind}` : ""}`);
  gmailAuthUrl = () => this.request<{ url: string }>("/ingest/gmail/auth-url");
  gmailConnect = (code: string) => this.post("/ingest/gmail/connect", { code });
  gmailPoll = () => this.post<{ seen: number; ingested: number }>("/ingest/gmail/poll");

  // inbox
  conversations = (q: { status?: ConvStatus; platform?: string; unread?: boolean; starred?: boolean; q?: string } = {}) => {
    const qs = new URLSearchParams(Object.entries(q).filter(([, v]) => v !== undefined && v !== "" && v !== false).map(([k, v]) => [k, String(v)])).toString();
    return this.request<Conversation[]>(`/conversations${qs ? `?${qs}` : ""}`);
  };
  unreadCounts = () => this.request<{ total: number; by_platform: Record<string, number> }>("/conversations/unread-counts");
  slaAlerts = () => this.request<SlaAlerts>("/conversations/sla-alerts");
  messages = (id: string) => this.request<ChatMessage[]>(`/conversations/${id}/messages`);
  patchConversation = (id: string, b: { starred?: boolean; labels?: string[]; status?: ConvStatus; snooze_minutes?: number }) =>
    this.request<Conversation>(`/conversations/${id}`, { method: "PATCH", body: JSON.stringify(b) });
  newConversation = (b: { platform: string; subject: string; client_name?: string; body?: string; platform_url?: string }) => this.post<Conversation>("/conversations", b);
  sendMessage = (id: string, b: { body: string; idempotency_key?: string; ai_generated?: boolean; approved?: boolean }) =>
    this.post<SendResult>(`/conversations/${id}/messages`, b);
  confirmSent = (messageId: string) => this.post<ChatMessage>(`/messages/${messageId}/confirm-sent`);
  suggestReply = (id: string, tone = "professional") => this.post<Suggestion>(`/conversations/${id}/suggest-reply?tone=${tone}`);
  summarize = (id: string) => this.post<Suggestion>(`/conversations/${id}/summary`);
  translate = (text: string, target_language = "English") => this.post<Suggestion>("/ai/translate", { text, target_language });
  canned = () => this.request<CannedResponse[]>("/canned-responses");
  addCanned = (b: { shortcut: string; body: string }) => this.post<CannedResponse>("/canned-responses", b);

  // CRM & search
  clients = (q?: string) => this.request<Client[]>(`/clients${q ? `?q=${encodeURIComponent(q)}` : ""}`);
  createClient = (b: Partial<ClientInput> & { name: string }) => this.post<Client>("/clients", b);
  updateClient = (id: string, b: ClientInput) => this.request<Client>(`/clients/${id}`, { method: "PUT", body: JSON.stringify(b) });
  mergeClients = (targetId: string, sourceId: string) => this.post<Client>(`/clients/${targetId}/merge`, { source_id: sourceId });
  search = (q: string) => this.request<SearchResults>(`/search?q=${encodeURIComponent(q)}`);

  /** Real-time events over WebSocket (message.new, conversation.updated, …). Reconnects with a fresh token. */
  connectRealtime = (onEvent: (e: RealtimeEvent) => void): (() => void) => {
    let stop = false;
    let ws: WebSocket | null = null;
    let retry = 1000;
    const open = async () => {
      const t = await this.store.get();
      if (stop || !t) return;
      ws = new WebSocket(`${this.baseUrl.replace(/^http/, "ws")}/api/v1/ws?token=${encodeURIComponent(t.access_token)}${this.getWorkspace?.() ? `&workspace=${this.getWorkspace?.()}` : ""}`);
      ws.onmessage = (m) => { retry = 1000; try { onEvent(JSON.parse(m.data) as RealtimeEvent); } catch { /* ignore */ } };
      ws.onclose = async (ev) => {
        if (stop) return;
        if (ev.code === 4401) { try { await this.me(); } catch { return; } } // expired token: any call triggers a refresh
        setTimeout(open, retry); retry = Math.min(retry * 2, 30_000);
      };
    };
    void open();
    return () => { stop = true; ws?.close(); };
  };

  // notifications
  notifications = (unread = false) => this.request<{ items: AppNotification[]; unread: number }>(`/notifications${unread ? "?unread=true" : ""}`);
  markRead = (id: string) => this.post<AppNotification>(`/notifications/${id}/read`);
  markAllRead = () => this.post("/notifications/read-all");
  deliveries = (status?: string) => this.request<Delivery[]>(`/notifications/deliveries${status ? `?status=${status}` : ""}`);
  retryDelivery = (id: string) => this.post<Delivery>(`/notifications/deliveries/${id}/retry`);
  notificationPrefs = () => this.request<NotificationPrefs>("/notifications/preferences");
  saveNotificationPrefs = (b: { matrix?: NotificationPrefs["matrix"]; quiet_start?: string; quiet_end?: string; digest_hour?: number }) =>
    this.request<NotificationPrefs>("/notifications/preferences", { method: "PUT", body: JSON.stringify(b) });
  channels = () => this.request<ChannelInfo[]>("/notifications/channels");
  saveChannel = (b: { channel: string; address: string; opted_in: boolean }) => this.request("/notifications/channels", { method: "PUT", body: JSON.stringify(b) });
  telegramLink = () => this.post<{ code: string; instructions: string }>("/notifications/channels/telegram/link");
  registerDevice = (b: { kind: "expo" | "webpush"; token: string; label?: string }) => this.post<{ id: string }>("/notifications/devices", b);
  testNotification = (channel: string) => this.post<{ status: string; error: string }>(`/notifications/test?channel=${channel}`);
  vapidKey = () => this.request<{ public_key: string }>("/notifications/vapid-key");

  // orders / projects / time
  orders = (status?: string) => this.request<Order[]>(`/orders${status ? `?status=${status}` : ""}`);
  createOrder = (b: { platform: string; title: string; amount?: number; currency?: string; due_at?: string | null; client_id?: string | null }) => this.post<Order>("/orders", b);
  orderStatus = (id: string, status: string) => this.post<Order>(`/orders/${id}/status?status=${status}`);
  patchOrder = (id: string, b: Partial<Pick<Order, "title" | "checklist" | "amount">> & { due_at?: string | null }) => this.request<Order>(`/orders/${id}`, { method: "PATCH", body: JSON.stringify(b) });
  addMilestone = (id: string, b: { title: string; amount: number; due_at?: string | null }) => this.post<Order>(`/orders/${id}/milestones`, b);
  milestoneAction = (id: string, mid: string, action: "submit" | "pay") => this.post<Order>(`/orders/${id}/milestones/${mid}/${action}`);
  orderProject = (id: string) => this.post<{ project_id: string }>(`/orders/${id}/project`);
  projects = () => this.request<Project[]>("/projects");
  createProject = (b: { name: string; hourly_rate?: number | null; client_id?: string | null }) => this.post<Project>("/projects", b);
  tasks = (pid: string) => this.request<Task[]>(`/projects/${pid}/tasks`);
  addTask = (pid: string, b: { title: string; status?: Task["status"]; due_at?: string | null }) => this.post<Task>(`/projects/${pid}/tasks`, b);
  updateTask = (id: string, b: { title: string; status: Task["status"]; priority?: string; due_at?: string | null }) => this.request<Task>(`/tasks/${id}`, { method: "PUT", body: JSON.stringify(b) });
  runningTimer = () => this.request<TimeEntry | null>("/time/running");
  startTimer = (b: { project_id?: string | null; note?: string }) => this.post<TimeEntry>("/time/start", b);
  stopTimer = () => this.post<TimeEntry>("/time/stop");
  timeEntries = (project_id?: string) => this.request<TimeEntry[]>(`/time${project_id ? `?project_id=${project_id}` : ""}`);

  // finance
  invoices = () => this.request<Invoice[]>("/finance/invoices");
  createInvoice = (b: { client_id?: string | null; currency?: string; due_date?: string | null; tax_pct?: number; items: InvoiceItem[]; notes?: string }) => this.post<Invoice>("/finance/invoices", b);
  invoiceFromTime = (project_id: string) => this.post<Invoice>("/finance/invoices/from-time", { project_id });
  invoiceAction = (id: string, action: "send" | "pay" | "void") => this.post<Invoice>(`/finance/invoices/${id}/${action}`);
  expenses = () => this.request<Expense[]>("/finance/expenses");
  addExpense = (b: { amount: number; category: string; description?: string; currency?: string }) => this.post<Expense>("/finance/expenses", b);
  payments = () => this.request<Payment[]>("/finance/payments");
  addPayment = (b: { platform: string; gross: number; currency?: string; note?: string }) => this.post<Payment>("/finance/payments", b);
  feeCalc = (platform: string, amount: number) => this.request<{ gross: number; fee: number; net: number }>(`/finance/fee-calculator?platform=${platform}&amount=${amount}`);
  report = (group_by: "month" | "platform" | "client" = "month") => this.request<EarningsReport>(`/finance/report?group_by=${group_by}`);
  financeSummary = () => this.request<FinanceSummary>("/finance/summary");
  /** Download helper: fetches with auth and returns a Blob (PDF/CSV/ICS). */
  async blob(path: string): Promise<Blob> {
    const t = await this.store.get();
    const ws = this.getWorkspace?.();
    const r = await fetch(`${this.baseUrl}/api/v1${path}`, { headers: { ...(t ? { Authorization: `Bearer ${t.access_token}` } : {}), ...(ws ? { "X-Workspace": ws } : {}) } });
    if (!r.ok) throw new ApiError(r.status, "download_failed", r.statusText);
    return r.blob();
  }

  // calendar
  calendar = () => this.request<CalendarItem[]>("/calendar");
  addCalendarEvent = (b: { title: string; kind?: string; starts_at: string; ends_at?: string | null }) => this.post("/calendar/events", b);
  calendarFeedUrl = () => this.request<{ url: string }>("/calendar/feed-url");
  googleCalendarAuthUrl = () => this.request<{ url: string }>("/calendar/google/auth-url");
  googleCalendarConnect = (code: string) => this.post("/calendar/google/connect", { code });
  googleCalendarSync = () => this.post<{ pushed: number; pulled: number }>("/calendar/google/sync");

  // forms
  formTemplates = () => this.request<{ key: string; title: string; kind: string; description: string; field_count: number }[]>("/forms/templates");
  forms = () => this.request<FormDef[]>("/forms");
  formFromTemplate = (key: string) => this.post<FormDef>(`/forms/from-template/${key}`);
  createForm = (b: Pick<FormDef, "title" | "description" | "kind" | "settings" | "fields">) => this.post<FormDef>("/forms", b);
  saveForm = (id: string, b: Pick<FormDef, "title" | "description" | "kind" | "settings" | "fields">) => this.request<FormDef>(`/forms/${id}`, { method: "PUT", body: JSON.stringify(b) });
  publishForm = (id: string, published: boolean) => this.post<FormDef>(`/forms/${id}/publish?published=${published}`);
  deleteForm = (id: string) => this.request(`/forms/${id}`, { method: "DELETE" });
  formSubmissions = (id: string) => this.request<FormSubmission[]>(`/forms/${id}/submissions`);

  // automations & assistant
  automationMeta = () => this.request<AutomationMeta>("/automations/meta");
  automations = () => this.request<AutomationRule[]>("/automations");
  saveAutomation = (b: Omit<AutomationRule, "id" | "run_count" | "last_run_at">, id?: string) =>
    id ? this.request<AutomationRule>(`/automations/${id}`, { method: "PUT", body: JSON.stringify(b) }) : this.post<AutomationRule>("/automations", b);
  toggleAutomation = (id: string) => this.post<AutomationRule>(`/automations/${id}/toggle`);
  deleteAutomation = (id: string) => this.request(`/automations/${id}`, { method: "DELETE" });
  testAutomation = (id: string, payload: Record<string, unknown>) => this.post<{ matched: boolean; actions: string[] }>(`/automations/${id}/test`, { payload });
  automationRuns = (id: string) => this.request<AutomationRun[]>(`/automations/${id}/runs`);
  briefing = (narrative = false) => this.request<Briefing>(`/assistant/briefing${narrative ? "?narrative=true" : ""}`);
  extractRequirements = (b: { text?: string; conversation_id?: string }) => this.post<Requirements>("/assistant/extract-requirements", b);
  assistantChat = (message: string, history: { role: string; content: string }[]) => this.post<{ text: string }>("/assistant/chat", { message, history });

  // team & workspaces
  workspaces = () => this.request<Workspace[]>("/me/workspaces");
  team = () => this.request<{ members: TeamMember[]; roles: Record<string, string> }>("/team");
  invite = (email: string, role: TeamMember["role"]) => this.post<TeamMember>("/team/invite", { email, role });
  acceptInvite = (token: string) => this.post("/team/accept", { token });
  setMemberRole = (id: string, role: TeamMember["role"]) => this.request<TeamMember>(`/team/${id}`, { method: "PATCH", body: JSON.stringify({ role }) });
  removeMember = (id: string) => this.request(`/team/${id}`, { method: "DELETE" });

  // analytics, goals, ops
  analytics = (days = 30, granularity: "day" | "week" | "month" = "day") => this.request<AnalyticsOverview>(`/analytics/overview?days=${days}&granularity=${granularity}`);
  goals = () => this.request<GoalProgress>("/goals");
  saveGoals = (b: { monthly_income: number; yearly_income: number; weekly_hours: number }) => this.request<GoalProgress>("/goals", { method: "PUT", body: JSON.stringify(b) });
  ops = () => this.request<OpsOverview>("/ops/overview");

  // project finder
  private pfSend<T>(method: string, path: string, body?: unknown) {
    return this.request<T>(`/project-finder${path}`, { method, body: body === undefined ? undefined : JSON.stringify(body) });
  }
  private static qs(q: Record<string, string | number | boolean | undefined | null>) {
    const p = new URLSearchParams();
    for (const [k, v] of Object.entries(q)) if (v !== undefined && v !== null && v !== "" && v !== false) p.set(k, String(v));
    const s = p.toString();
    return s ? `?${s}` : "";
  }
  pfSettings = () => this.pfSend<PFSettings>("GET", "/settings");
  pfSaveSettings = (b: PFSettingsInput) => this.pfSend<PFSettings>("PUT", "/settings", b);
  pfLeads = (q: { status?: string; q?: string; due?: boolean; country?: string } = {}) => this.pfSend<PFLead[]>("GET", `/leads${ApiClient.qs(q)}`);
  pfCreateLead = (b: PFLeadInput) => this.pfSend<PFLead>("POST", "/leads", b);
  pfUpdateLead = (id: string, b: PFLeadPatch) => this.pfSend<PFLead>("PATCH", `/leads/${id}`, b);
  pfDeleteLead = (id: string) => this.pfSend("DELETE", `/leads/${id}`);
  pfGoal = () => this.pfSend<PFGoal>("GET", "/outreach/goal");
  pfLogOutreach = (b: { lead_id?: string; channel?: OutreachChannel } = {}) => this.pfSend<PFGoal>("POST", "/outreach/log", b);
  pfUndoOutreach = () => this.pfSend<PFGoal>("DELETE", "/outreach/log/latest");
  pfTemplates = () => this.pfSend<PFTemplate[]>("GET", "/templates");
  pfTemplateVars = () => this.pfSend<Record<string, string>>("GET", "/templates/variables");
  pfCreateTemplate = (b: PFTemplateInput) => this.pfSend<PFTemplate>("POST", "/templates", b);
  pfUpdateTemplate = (id: string, b: Partial<PFTemplateInput>) => this.pfSend<PFTemplate>("PATCH", `/templates/${id}`, b);
  pfDeleteTemplate = (id: string) => this.pfSend("DELETE", `/templates/${id}`);
  pfAddStarters = () => this.pfSend<PFTemplate[]>("POST", "/templates/starters");
  pfRenderTemplate = (id: string, lead_id?: string) => this.pfSend<PFDraft>("POST", `/templates/${id}/render`, { lead_id });
  pfGenerateDraft = (id: string, lead_id: string, instructions = "") => this.pfSend<PFDraft>("POST", `/templates/${id}/generate`, { lead_id, instructions });
  pfSources = () => this.pfSend<PFSource[]>("GET", "/sources");
  pfAddSource = (b: { name: string; url: string; notes?: string }) => this.pfSend<PFSource>("POST", "/sources", b);
  pfUpdateSource = (id: string, b: Partial<Pick<PFSource, "name" | "url" | "status" | "notes">>) => this.pfSend<PFSource>("PATCH", `/sources/${id}`, b);
  pfMarkChecked = (id: string) => this.pfSend<PFSource>("POST", `/sources/${id}/mark-checked`);
  pfDeleteSource = (id: string) => this.pfSend("DELETE", `/sources/${id}`);
  pfJobs = (q: PFJobQuery = {}) => this.pfSend<PFJob[]>("GET", `/jobs${ApiClient.qs({ ...q })}`);
  pfRefreshJobs = (source?: string) => this.pfSend<PFRefreshResult[]>("POST", "/jobs/refresh", { source });
  pfUpdateJob = (id: string, status: JobStatus) => this.pfSend<PFJob>("PATCH", `/jobs/${id}`, { status });
  pfJobToLead = (id: string) => this.pfSend<PFLead>("POST", `/jobs/${id}/to-lead`);
  pfProposals = (q: { status?: string; source?: string; lead_id?: string; q?: string } = {}) => this.pfSend<PFProposal[]>("GET", `/proposals${ApiClient.qs(q)}`);
  pfCreateProposal = (b: PFProposalInput) => this.pfSend<PFProposal>("POST", "/proposals", b);
  pfUpdateProposal = (id: string, b: PFProposalInput) => this.pfSend<PFProposal>("PATCH", `/proposals/${id}`, b);
  pfDeleteProposal = (id: string) => this.pfSend("DELETE", `/proposals/${id}`);
  pfStats = (days?: number) => this.pfSend<PFStats>("GET", `/stats${ApiClient.qs({ days })}`);
  pfInvoices = (q: { lead_id?: string; firc?: "pending" | "received" } = {}) => this.pfSend<PFInvoice[]>("GET", `/invoices${ApiClient.qs(q)}`);
  pfCreateInvoice = (b: PFInvoiceInput) => this.pfSend<PFInvoice>("POST", "/invoices", b);
  pfUpdateInvoice = (id: string, b: Partial<Omit<PFInvoiceInput, "lead_id">>) => this.pfSend<PFInvoice>("PATCH", `/invoices/${id}`, b);
  pfDeleteInvoice = (id: string) => this.pfSend("DELETE", `/invoices/${id}`);
  pfForeignInfo = () => this.pfSend<{ disclaimer: string; payment_methods: string[] }>("GET", "/foreign/info");
  pfTzOverlap = (timezone: string) => this.pfSend<PFTzOverlap>("GET", `/foreign/tz-overlap${ApiClient.qs({ timezone })}`);
  pfTzSuggest = (country: string) => this.pfSend<{ timezone: string }>("GET", `/foreign/tz-suggest${ApiClient.qs({ country })}`);
}
