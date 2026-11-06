// Formes JSON de l'API backend (Tasks 3, 5, 9, 10, 11). Dates = chaînes ISO 8601.

export type Category = "tt" | "important" | "action" | "info" | "news" | "pub" | "spam";
export type FolderRole = "inbox" | "drafts" | "sent" | "junk" | "archive" | "trash";

export interface AuthStatus { setup_done: boolean; authenticated: boolean; setup_token_required?: boolean }
export interface SessionUser { username: string; display_name: string }

// Accounts (Task 5)
export type Provider = "gmail" | "icloud" | "imap" | "outlook";
export interface Account {
  id: number; provider: Provider; label: string; email: string; enabled: boolean;
  status: string; status_message: string | null; last_sync_at: string | null; color: string;
  auth_type?: "password" | "oauth";
}
export interface OAuthProviders { google: boolean; microsoft: boolean }
export type OAuthProvider = keyof OAuthProviders;
export interface AccountCreate {
  provider: Provider; email: string; password: string;
  imap_host?: string; imap_port?: number; username?: string; label?: string;
}
export interface AccountPatch { enabled?: boolean; password?: string; label?: string }

// Boxes / folders / messages (Task 11)
export interface PriorityPreview { id: number; label: string; subject: string; category: Category }
export interface BoxSummary {
  id: "all" | number; label: string; email: string; color: string; unread: number;
  priority: PriorityPreview[];
}
export interface Folder { key: string; role: FolderRole | "custom"; label: string; unread: number }
export interface Message {
  id: number; account_id: number; account_color: string; from_name: string; from_addr: string;
  subject: string; preview: string; sent_at: string | null; seen: boolean;
  category: Category | null; priority: boolean; reason: string | null; summary: string | null;
}
export interface MessagePage { items: Message[]; next_before_id: number | null }
export interface MessageDetail extends Message {
  body_html: string | null; body_text: string | null; attachments: string[];
  open_url: "googlegmail://" | "message://" | null;
}
export type MessageAction = "read" | "unread" | "archive" | "trash" | "move" | "important";
export interface ActionRequest { ids: number[]; action: MessageAction; target_folder?: string }
export interface BatchResult { batch_id: string; count: number }

// Runs (Task 11)
export type RunKind = "light" | "full";
export type RunStatus = "running" | "ok" | "queued" | "error";
export type RunStep = "sync" | "bodies" | "classify" | "alerts";
export interface Run {
  id: number | null; kind: RunKind; trigger: string; status: RunStatus;
  started_at: string | null; finished_at: string | null; mails_count: number; error: string | null;
  step: RunStep | null; total: number;
}
export interface LatestRuns {
  light: Run | null; full: Run | null; next_full_at: string | null; next_light_at: string | null;
}

// Settings (Task 11)
export interface ScheduleSettings {
  full_times: string[]; light_interval_min: 15 | 30 | 60; light_start: string; light_end: string;
  days: number[]; // 0 = lundi
}
export interface AlertSettings {
  webpush: boolean; gotify: boolean; gotify_url: string | null;
  notify_tt: boolean; notify_important: boolean; notify_action: boolean; notify_summary: boolean;
  quiet_enabled: boolean; quiet_from: string; quiet_to: string; quiet_tt_bypass: boolean;
  gotify_token_set: boolean;
}
export type AlertSettingsUpdate = Omit<AlertSettings, "gotify_token_set"> & { gotify_token?: string | null };

// Push / alerts (Task 9)
export interface VapidKey { key: string }
export interface PushSubscribeBody { endpoint: string; keys: { p256dh: string; auth: string } }
export type AlertChannel = "webpush" | "gotify";

// Claude (Task 10)
export interface ClaudeStatus {
  connected: boolean; last_ok_at: string | null; last_error: string | null;
  token_set_at: string | null; expires_at: string | null; days_left: number | null; warn_days: number;
}
export interface OkDetail { ok: boolean; detail: string }
export interface ClaudeLoginStart { url: string }
