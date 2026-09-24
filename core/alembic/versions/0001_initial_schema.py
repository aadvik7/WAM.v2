"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-09-24 17:24:50.548757
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")
    op.create_table(
        "businesses",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("type", sa.String(length=20), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("language", sa.String(length=10), nullable=False),
        sa.Column("phone", sa.String(length=32), nullable=True),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("maps_url", sa.String(length=500), nullable=True),
        sa.Column("emergency_number", sa.String(length=32), nullable=True),
        sa.Column("hours", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("settings", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("chatwoot_account_id", sa.Integer(), nullable=True),
        sa.Column("chatwoot_inbox_id", sa.Integer(), nullable=True),
        sa.Column("chatwoot_api_token", sa.String(length=200), nullable=True),
        sa.Column("chatwoot_bot_token", sa.String(length=200), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("type IN ('clinic','institute','business')", name="ck_businesses_type"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("chatwoot_account_id", "chatwoot_inbox_id", name="uq_businesses_chatwoot_inbox"),
    )
    op.create_table(
        "admin_users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(length=200), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=True),
        sa.Column("password_hash", sa.String(length=200), nullable=False),
        sa.Column("business_id", sa.Integer(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
    )
    op.create_table(
        "contacts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("business_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=True),
        sa.Column("phone", sa.String(length=32), nullable=True),
        sa.Column("language", sa.String(length=10), nullable=True),
        sa.Column("date_of_birth", sa.Date(), nullable=True),
        sa.Column("guardian_id", sa.Integer(), nullable=True),
        sa.Column("consent_notice_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("consent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("opted_out", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("needs_staff", sa.Boolean(), nullable=False),
        sa.Column("last_inbound_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("chatwoot_contact_id", sa.Integer(), nullable=True),
        sa.Column("chatwoot_source_id", sa.String(length=200), nullable=True),
        sa.Column("chatwoot_conversation_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["guardian_id"], ["contacts.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_contacts_business_name", "contacts", ["business_id", "name"], unique=False)
    op.create_index(
        "uq_contacts_business_phone",
        "contacts",
        ["business_id", "phone"],
        unique=True,
        postgresql_where=sa.text("phone IS NOT NULL AND guardian_id IS NULL"),
    )
    op.create_table(
        "faqs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("business_id", sa.Integer(), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("keywords", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "groups",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("business_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("kind", sa.String(length=30), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("business_id", "name", name="uq_groups_business_name"),
    )
    op.create_table(
        "jobs",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("business_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=50), nullable=False),
        sa.Column("run_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("dedupe_key", sa.String(length=200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('scheduled','running','done','failed','cancelled')", name="ck_jobs_status"
        ),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dedupe_key"),
    )
    op.create_index("ix_jobs_due", "jobs", ["status", "run_at"], unique=False)
    op.create_table(
        "roles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("business_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=50), nullable=False),
        sa.Column("allowed_commands", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("business_id", "name", name="uq_roles_business_name"),
    )
    op.create_table(
        "schedule_templates",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("business_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("specialty", sa.String(length=60), nullable=True),
        sa.Column("session_count", sa.Integer(), nullable=True),
        sa.Column("gap_days", sa.Integer(), nullable=False),
        sa.Column("offsets_days", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("session_labels", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("duration_minutes", sa.SmallInteger(), nullable=True),
        sa.Column("reminder_rules", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("aliases", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("gap_days >= 0", name="ck_schedule_templates_gap"),
        sa.CheckConstraint("session_count IS NULL OR session_count >= 1", name="ck_schedule_templates_count"),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("business_id", "name", name="uq_schedule_templates_business_name"),
    )
    op.create_table(
        "group_members",
        sa.Column("group_id", sa.Integer(), nullable=False),
        sa.Column("contact_id", sa.Integer(), nullable=False),
        sa.Column("added_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["contact_id"], ["contacts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["group_id"], ["groups.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("group_id", "contact_id"),
    )
    op.create_table(
        "staff",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("business_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("phone", sa.String(length=32), nullable=False),
        sa.Column("role_id", sa.Integer(), nullable=True),
        sa.Column("pin_hash", sa.String(length=200), nullable=True),
        sa.Column("pin_failed_count", sa.Integer(), nullable=False),
        sa.Column("pin_locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("permissions", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("receives_eod_list", sa.Boolean(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("last_inbound_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("chatwoot_contact_id", sa.Integer(), nullable=True),
        sa.Column("chatwoot_source_id", sa.String(length=200), nullable=True),
        sa.Column("chatwoot_conversation_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["role_id"], ["roles.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("business_id", "phone", name="uq_staff_business_phone"),
    )
    op.create_table(
        "audit_log",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("business_id", sa.Integer(), nullable=True),
        sa.Column("staff_id", sa.Integer(), nullable=True),
        sa.Column("admin_user_id", sa.Integer(), nullable=True),
        sa.Column("phone", sa.String(length=32), nullable=True),
        sa.Column("action", sa.String(length=80), nullable=False),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["admin_user_id"], ["admin_users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["staff_id"], ["staff.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_audit_log_business_created", "audit_log", ["business_id", "created_at"], unique=False)
    op.create_table(
        "broadcasts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("business_id", sa.Integer(), nullable=False),
        sa.Column("group_id", sa.Integer(), nullable=True),
        sa.Column("template_name", sa.String(length=100), nullable=False),
        sa.Column("params", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("sender_staff_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("sent_count", sa.Integer(), nullable=False),
        sa.Column("read_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["group_id"], ["groups.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["sender_staff_id"], ["staff.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "conversation_states",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("business_id", sa.Integer(), nullable=False),
        sa.Column("contact_id", sa.Integer(), nullable=True),
        sa.Column("staff_id", sa.Integer(), nullable=True),
        sa.Column("key", sa.String(length=50), nullable=False),
        sa.Column("data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["contact_id"], ["contacts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["staff_id"], ["staff.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_conversation_states_contact", "conversation_states", ["contact_id", "key"], unique=False
    )
    op.create_index("ix_conversation_states_staff", "conversation_states", ["staff_id", "key"], unique=False)
    op.create_table(
        "message_log",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("business_id", sa.Integer(), nullable=False),
        sa.Column("contact_id", sa.Integer(), nullable=True),
        sa.Column("staff_id", sa.Integer(), nullable=True),
        sa.Column("direction", sa.String(length=3), nullable=False),
        sa.Column("phone", sa.String(length=32), nullable=True),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("template_name", sa.String(length=100), nullable=True),
        sa.Column("audience", sa.String(length=10), nullable=False),
        sa.Column("handled_by", sa.String(length=10), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("chatwoot_conversation_id", sa.Integer(), nullable=True),
        sa.Column("chatwoot_message_id", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("direction IN ('in','out')", name="ck_message_log_direction"),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["contact_id"], ["contacts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["staff_id"], ["staff.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_message_log_business_created", "message_log", ["business_id", "created_at"], unique=False
    )
    op.create_index(
        "ix_message_log_contact_created", "message_log", ["contact_id", "created_at"], unique=False
    )
    op.create_index(
        "uq_message_log_chatwoot_in",
        "message_log",
        ["business_id", "chatwoot_message_id"],
        unique=True,
        postgresql_where=sa.text("direction = 'in' AND chatwoot_message_id IS NOT NULL"),
    )
    op.create_table(
        "pending_actions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("business_id", sa.Integer(), nullable=False),
        sa.Column("staff_id", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(length=50), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["staff_id"], ["staff.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "resources",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("business_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("kind", sa.String(length=30), nullable=False),
        sa.Column("specialty", sa.String(length=60), nullable=True),
        sa.Column("slot_minutes", sa.SmallInteger(), nullable=False),
        sa.Column("staff_id", sa.Integer(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("slot_minutes BETWEEN 5 AND 480", name="ck_resources_slot_minutes"),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["staff_id"], ["staff.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "availability",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("resource_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=10), nullable=False),
        sa.Column("weekday", sa.SmallInteger(), nullable=True),
        sa.Column("start_time", sa.Time(), nullable=True),
        sa.Column("end_time", sa.Time(), nullable=True),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("end_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reason", sa.String(length=200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "(kind = 'leave' AND start_at IS NOT NULL AND end_at IS NOT NULL AND end_at > start_at) OR (kind <> 'leave' AND start_time IS NOT NULL AND end_time IS NOT NULL AND end_time > start_time)",
            name="ck_availability_shape",
        ),
        sa.CheckConstraint("kind <> 'weekly' OR weekday IS NOT NULL", name="ck_availability_weekly_weekday"),
        sa.CheckConstraint("kind IN ('weekly','break','leave')", name="ck_availability_kind"),
        sa.CheckConstraint("weekday IS NULL OR weekday BETWEEN 0 AND 6", name="ck_availability_weekday"),
        sa.ForeignKeyConstraint(["resource_id"], ["resources.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_availability_resource", "availability", ["resource_id", "kind"], unique=False)
    op.create_table(
        "schedules",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("business_id", sa.Integer(), nullable=False),
        sa.Column("contact_id", sa.Integer(), nullable=False),
        sa.Column("template_id", sa.Integer(), nullable=False),
        sa.Column("resource_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("anchor_date", sa.Date(), nullable=False),
        sa.Column("sessions_done", sa.Integer(), nullable=False),
        sa.Column("sessions_total", sa.Integer(), nullable=True),
        sa.Column("next_due_date", sa.Date(), nullable=True),
        sa.Column("nudge_count", sa.Integer(), nullable=False),
        sa.Column("last_nudged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("missed_count", sa.Integer(), nullable=False),
        sa.Column("needs_staff", sa.Boolean(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by_staff_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('active','paused','completed','cancelled')", name="ck_schedules_status"
        ),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["contact_id"], ["contacts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_staff_id"], ["staff.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["resource_id"], ["resources.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["template_id"], ["schedule_templates.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_schedules_contact", "schedules", ["contact_id"], unique=False)
    op.create_index("ix_schedules_due", "schedules", ["business_id", "status", "next_due_date"], unique=False)
    op.create_table(
        "appointments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("business_id", sa.Integer(), nullable=False),
        sa.Column("resource_id", sa.Integer(), nullable=False),
        sa.Column("contact_id", sa.Integer(), nullable=False),
        sa.Column("schedule_id", sa.Integer(), nullable=True),
        sa.Column("session_number", sa.Integer(), nullable=True),
        sa.Column("service", sa.String(length=120), nullable=True),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("recovered", sa.Boolean(), nullable=False),
        sa.Column("rebooked_from_id", sa.Integer(), nullable=True),
        sa.Column("reminder_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("marked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_reason", sa.String(length=200), nullable=True),
        sa.Column("followup_count", sa.Integer(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "status IN ('booked','confirmed','done','missed','cancelled')", name="ck_appointments_status"
        ),
        sa.CheckConstraint("end_at > start_at", name="ck_appointments_range"),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["contact_id"], ["contacts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["rebooked_from_id"], ["appointments.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["resource_id"], ["resources.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["schedule_id"], ["schedules.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_appointments_business_start", "appointments", ["business_id", "start_at"], unique=False
    )
    op.create_index("ix_appointments_contact", "appointments", ["contact_id"], unique=False)
    op.create_index(
        "ix_appointments_resource_start", "appointments", ["resource_id", "start_at"], unique=False
    )
    # No two active appointments may overlap for the same resource (backs up the row lock in engine.book).
    op.execute(
        "ALTER TABLE appointments ADD CONSTRAINT ex_appointments_no_overlap "
        "EXCLUDE USING gist (resource_id WITH =, tstzrange(start_at, end_at) WITH &&) "
        "WHERE (status IN ('booked','confirmed'))"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE appointments DROP CONSTRAINT IF EXISTS ex_appointments_no_overlap")
    op.drop_index("ix_appointments_resource_start", table_name="appointments")
    op.drop_index("ix_appointments_contact", table_name="appointments")
    op.drop_index("ix_appointments_business_start", table_name="appointments")
    op.drop_table("appointments")
    op.drop_index("ix_schedules_due", table_name="schedules")
    op.drop_index("ix_schedules_contact", table_name="schedules")
    op.drop_table("schedules")
    op.drop_index("ix_availability_resource", table_name="availability")
    op.drop_table("availability")
    op.drop_table("resources")
    op.drop_table("pending_actions")
    op.drop_index(
        "uq_message_log_chatwoot_in",
        table_name="message_log",
        postgresql_where=sa.text("direction = 'in' AND chatwoot_message_id IS NOT NULL"),
    )
    op.drop_index("ix_message_log_contact_created", table_name="message_log")
    op.drop_index("ix_message_log_business_created", table_name="message_log")
    op.drop_table("message_log")
    op.drop_index("ix_conversation_states_staff", table_name="conversation_states")
    op.drop_index("ix_conversation_states_contact", table_name="conversation_states")
    op.drop_table("conversation_states")
    op.drop_table("broadcasts")
    op.drop_index("ix_audit_log_business_created", table_name="audit_log")
    op.drop_table("audit_log")
    op.drop_table("staff")
    op.drop_table("group_members")
    op.drop_table("schedule_templates")
    op.drop_table("roles")
    op.drop_index("ix_jobs_due", table_name="jobs")
    op.drop_table("jobs")
    op.drop_table("groups")
    op.drop_table("faqs")
    op.drop_index(
        "uq_contacts_business_phone",
        table_name="contacts",
        postgresql_where=sa.text("phone IS NOT NULL AND guardian_id IS NULL"),
    )
    op.drop_index("ix_contacts_business_name", table_name="contacts")
    op.drop_table("contacts")
    op.drop_table("admin_users")
    op.drop_table("businesses")
