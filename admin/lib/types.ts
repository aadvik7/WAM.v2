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
