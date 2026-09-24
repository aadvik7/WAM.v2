export type Settings = Record<string, string | number | boolean | string[] | null>;

export interface Business {
  id: number;
  name: string;
  type: "clinic" | "institute" | "business";
  timezone: string;
  language: string;
  phone: string | null;
  address: string | null;
  maps_url: string | null;
  emergency_number: string | null;
  hours: Record<string, [string, string][]>;
  settings: Settings;
  chatwoot_account_id: number | null;
  chatwoot_inbox_id: number | null;
  chatwoot_api_token_set: boolean;
  chatwoot_bot_token_set: boolean;
  chatwoot_webhook_secret_set: boolean;
  is_active: boolean;
}

export interface AdminUser {
  id: number;
  email: string;
  name: string | null;
  business_id: number | null;
  is_active: boolean;
}

export interface Role {
  id: number;
  name: string;
  allowed_commands: string[];
}

export interface StaffMember {
  id: number;
  name: string;
  phone: string;
  role_id: number | null;
  role: string | null;
  pin_set: boolean;
  pin_locked: boolean;
  receives_eod_list: boolean;
  is_active: boolean;
}

export interface Resource {
  id: number;
  name: string;
  kind: string;
  specialty: string | null;
  slot_minutes: number;
  staff_id: number | null;
  is_active: boolean;
}

export interface AvailabilityBlock {
  id: number;
  kind: "weekly" | "break" | "leave";
  weekday: number | null;
  start: string | null;
  end: string | null;
  start_at: string | null;
  end_at: string | null;
  reason: string | null;
}

export interface Template {
  id: number;
  name: string;
  specialty: string | null;
  session_count: number | null;
  total_sessions: number | null;
  ongoing: boolean;
  gap_days: number;
  offsets_days: number[] | null;
  session_labels: string[] | null;
  duration_minutes: number | null;
  aliases: string[];
  is_active: boolean;
  kind: "visit" | "payment";
  amount: number | null;
  reminder_days_before: number | null;
}

export interface Faq {
  id: number;
  question: string;
  answer: string;
  keywords: string[];
}

export interface Contact {
  id: number;
  name: string | null;
  phone: string | null;
  roll?: string | null;
  guardian: { id: number; name: string | null; phone: string | null } | null;
  date_of_birth: string | null;
  language: string | null;
  notes: string | null;
  opted_out: boolean;
  needs_staff: boolean;
  consent_at: string | null;
  consent_notice_sent_at: string | null;
  last_inbound_at: string | null;
  created_at: string | null;
  active_plans?: number;
}

export interface Schedule {
  id: number;
  contact_id: number;
  contact_name: string | null;
  template_id: number;
  template: string | null;
  kind: "visit" | "payment";
  amount: number | null;
  resource_id: number | null;
  status: "active" | "paused" | "completed" | "cancelled";
  anchor_date: string;
  sessions_done: number;
  sessions_total: number | null;
  next_due_date: string | null;
  overdue: boolean;
  nudge_count: number;
  last_nudged_at: string | null;
  missed_count: number;
  needs_staff: boolean;
  notes: string | null;
  created_at: string | null;
  completed_at: string | null;
}

export interface Appointment {
  id: number;
  contact_id: number;
  contact_name: string | null;
  contact_phone: string | null;
  resource_id: number;
  resource_name: string | null;
  schedule_id: number | null;
  session_number: number | null;
  service: string | null;
  start_at: string;
  end_at: string;
  status: "booked" | "confirmed" | "done" | "missed" | "cancelled";
  source: string;
  recovered: boolean;
  reminder_sent: boolean;
  confirmed_at: string | null;
  cancelled_reason: string | null;
  notes: string | null;
  created_at: string | null;
}

export interface Message {
  id: number;
  contact_id: number | null;
  staff_id: number | null;
  direction: "in" | "out";
  phone: string | null;
  content: string | null;
  template_name: string | null;
  audience: string;
  handled_by: string | null;
  status: string;
  error: string | null;
  created_at: string;
}

export interface Slot {
  start_at: string;
  end_at: string;
  label: string;
}

export interface Meta {
  default_settings: Settings;
  command_keys: string[];
  packs: Record<string, { label: string; vocab: Record<string, string> }>;
  staff_help: string;
}

// ---- Institute pack ----

export interface Batch {
  id: number;
  name: string;
  students: number;
  teachers: number;
}

export interface Student {
  id: number;
  name: string | null;
  roll: string | null;
  phone: string | null;
  parents: { id: number; name: string | null; phone: string | null }[];
  opted_out: boolean;
}

export interface BatchDetail {
  id: number;
  name: string;
  students: Student[];
  teachers: { id: number; name: string; phone: string }[];
}

export interface Subject {
  id: number;
  name: string;
  aliases: string[];
  chatwoot_team_id: number | null;
}

export interface Doubt {
  id: number;
  contact_id: number;
  student: string | null;
  subject: string | null;
  batch: string | null;
  question: string;
  status: "open" | "closed";
  created_at: string;
  closed_at: string | null;
}

export interface BroadcastSummary {
  id: number;
  group_id: number | null;
  batch: string | null;
  message: string;
  audience: "everyone" | "parents" | "students";
  status: "draft" | "sending" | "sent" | "cancelled";
  recipients: number;
  sent: number;
  delivered: number;
  read: number;
  failed: number;
  counts: { students?: number; parents?: number; unreachable?: number };
  preview: string;
  created_at: string;
  sent_at: string | null;
}

export interface BroadcastRecipient {
  contact_id: number;
  name: string | null;
  phone: string;
  status: "queued" | "sent" | "delivered" | "read" | "failed" | "skipped";
  error: string | null;
}

export interface BroadcastDetail extends Omit<BroadcastSummary, "recipients"> {
  recipients: BroadcastRecipient[];
}

export interface UploadRow {
  row: number;
  error?: string;
  [key: string]: unknown;
}

export interface Upload {
  id: number;
  kind: "students" | "attendance" | "results" | "timetable";
  filename: string | null;
  label: string | null;
  group_id: number | null;
  status: "preview" | "applied" | "cancelled";
  summary: Record<string, unknown>;
  created_at: string;
  applied_at: string | null;
  rows?: UploadRow[];
}

export interface PtmEvent {
  id: number;
  group_id: number;
  batch: string | null;
  title: string;
  date: string;
  start: string;
  end: string;
  slot_minutes: number;
  resource_ids: number[];
  booked: number;
  free: number;
  broadcast_id: number | null;
}

export interface TimetableRow {
  id: number;
  group_id: number;
  weekday: number | null;
  date: string | null;
  start: string;
  end: string | null;
  subject: string;
  teacher: string | null;
  room: string | null;
}
