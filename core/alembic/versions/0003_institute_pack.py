"""institute pack

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-24 19:12:19.998861
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "subjects",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("business_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("aliases", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("chatwoot_team_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("business_id", "name", name="uq_subjects_business_name"),
    )
    op.create_table(
        "contact_links",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("business_id", sa.Integer(), nullable=False),
        sa.Column("contact_id", sa.Integer(), nullable=False),
        sa.Column("linked_id", sa.Integer(), nullable=False),
        sa.Column("relation", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("contact_id <> linked_id", name="ck_contact_links_not_self"),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["contact_id"], ["contacts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["linked_id"], ["contacts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("contact_id", "linked_id", name="uq_contact_links_pair"),
    )
    op.create_index("ix_contact_links_linked", "contact_links", ["linked_id"], unique=False)
    op.create_table(
        "doubts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("business_id", sa.Integer(), nullable=False),
        sa.Column("contact_id", sa.Integer(), nullable=False),
        sa.Column("subject_id", sa.Integer(), nullable=True),
        sa.Column("group_id", sa.Integer(), nullable=True),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column("chatwoot_conversation_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status IN ('open','closed')", name="ck_doubts_status"),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["contact_id"], ["contacts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["group_id"], ["groups.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["subject_id"], ["subjects.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_doubts_business_status", "doubts", ["business_id", "status"], unique=False)
    op.create_table(
        "timetable_entries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("business_id", sa.Integer(), nullable=False),
        sa.Column("group_id", sa.Integer(), nullable=False),
        sa.Column("weekday", sa.SmallInteger(), nullable=True),
        sa.Column("date", sa.Date(), nullable=True),
        sa.Column("start_time", sa.Time(), nullable=False),
        sa.Column("end_time", sa.Time(), nullable=True),
        sa.Column("subject", sa.String(length=80), nullable=False),
        sa.Column("teacher", sa.String(length=120), nullable=True),
        sa.Column("room", sa.String(length=60), nullable=True),
        sa.CheckConstraint("(weekday IS NOT NULL) <> (date IS NOT NULL)", name="ck_timetable_day"),
        sa.CheckConstraint("weekday IS NULL OR weekday BETWEEN 0 AND 6", name="ck_timetable_weekday"),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["group_id"], ["groups.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_timetable_group", "timetable_entries", ["group_id", "weekday"], unique=False)
    op.create_table(
        "group_staff",
        sa.Column("group_id", sa.Integer(), nullable=False),
        sa.Column("staff_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["group_id"], ["groups.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["staff_id"], ["staff.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("group_id", "staff_id"),
    )
    op.create_table(
        "imports",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("business_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("filename", sa.String(length=200), nullable=True),
        sa.Column("label", sa.String(length=200), nullable=True),
        sa.Column("group_id", sa.Integer(), nullable=True),
        sa.Column("rows", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("summary", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column("created_by_staff_id", sa.Integer(), nullable=True),
        sa.Column("created_by_admin_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("kind IN ('students','attendance','results','timetable')", name="ck_imports_kind"),
        sa.CheckConstraint("status IN ('preview','applied','cancelled')", name="ck_imports_status"),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_admin_id"], ["admin_users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by_staff_id"], ["staff.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["group_id"], ["groups.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "broadcast_recipients",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("broadcast_id", sa.Integer(), nullable=False),
        sa.Column("contact_id", sa.Integer(), nullable=False),
        sa.Column("phone", sa.String(length=32), nullable=True),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("chatwoot_conversation_id", sa.Integer(), nullable=True),
        sa.Column("chatwoot_message_id", sa.BigInteger(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["broadcast_id"], ["broadcasts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["contact_id"], ["contacts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("broadcast_id", "contact_id", name="uq_broadcast_recipients_contact"),
    )
    op.create_index(
        "ix_broadcast_recipients_status", "broadcast_recipients", ["broadcast_id", "status"], unique=False
    )
    op.create_table(
        "ptm_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("business_id", sa.Integer(), nullable=False),
        sa.Column("group_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("start_time", sa.Time(), nullable=False),
        sa.Column("end_time", sa.Time(), nullable=False),
        sa.Column("slot_minutes", sa.SmallInteger(), nullable=False),
        sa.Column("resource_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("broadcast_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("end_time > start_time", name="ck_ptm_events_range"),
        sa.CheckConstraint("slot_minutes BETWEEN 5 AND 60", name="ck_ptm_events_slot"),
        sa.ForeignKeyConstraint(["broadcast_id"], ["broadcasts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["group_id"], ["groups.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ptm_events_group_date", "ptm_events", ["group_id", "date"], unique=False)
    op.add_column("broadcasts", sa.Column("created_by_admin_id", sa.Integer(), nullable=True))
    op.add_column("broadcasts", sa.Column("message", sa.Text(), server_default="", nullable=False))
    op.add_column(
        "broadcasts", sa.Column("audience", sa.String(length=10), server_default="everyone", nullable=False)
    )
    op.add_column(
        "broadcasts", sa.Column("recipients_count", sa.Integer(), server_default="0", nullable=False)
    )
    op.add_column(
        "broadcasts", sa.Column("delivered_count", sa.Integer(), server_default="0", nullable=False)
    )
    op.add_column("broadcasts", sa.Column("failed_count", sa.Integer(), server_default="0", nullable=False))
    op.add_column("broadcasts", sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True))
    op.create_foreign_key(
        "fk_broadcasts_created_by_admin",
        "broadcasts",
        "admin_users",
        ["created_by_admin_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.add_column("contacts", sa.Column("external_id", sa.String(length=50), nullable=True))
    op.create_index(
        "uq_contacts_business_external_id",
        "contacts",
        ["business_id", "external_id"],
        unique=True,
        postgresql_where=sa.text("external_id IS NOT NULL"),
    )
    op.add_column(
        "schedule_templates", sa.Column("kind", sa.String(length=10), server_default="visit", nullable=False)
    )
    op.add_column("schedule_templates", sa.Column("amount", sa.Numeric(precision=12, scale=2), nullable=True))
    op.add_column("schedules", sa.Column("amount", sa.Numeric(precision=12, scale=2), nullable=True))
    op.create_check_constraint(
        "ck_schedule_templates_kind", "schedule_templates", "kind IN ('visit','payment')"
    )
    # Availability gains 'extra' (one-off hours, e.g. a parent-teacher meeting morning)
    op.drop_constraint("ck_availability_kind", "availability", type_="check")
    op.drop_constraint("ck_availability_shape", "availability", type_="check")
    op.create_check_constraint(
        "ck_availability_kind", "availability", "kind IN ('weekly','break','leave','extra')"
    )
    op.create_check_constraint(
        "ck_availability_shape",
        "availability",
        "(kind IN ('leave','extra') AND start_at IS NOT NULL AND end_at IS NOT NULL AND end_at > start_at) OR "
        "(kind IN ('weekly','break') AND start_time IS NOT NULL AND end_time IS NOT NULL AND end_time > start_time)",
    )


def downgrade() -> None:
    op.execute("DELETE FROM availability WHERE kind = 'extra'")
    op.drop_constraint("ck_availability_shape", "availability", type_="check")
    op.drop_constraint("ck_availability_kind", "availability", type_="check")
    op.create_check_constraint("ck_availability_kind", "availability", "kind IN ('weekly','break','leave')")
    op.create_check_constraint(
        "ck_availability_shape",
        "availability",
        "(kind = 'leave' AND start_at IS NOT NULL AND end_at IS NOT NULL AND end_at > start_at) OR "
        "(kind <> 'leave' AND start_time IS NOT NULL AND end_time IS NOT NULL AND end_time > start_time)",
    )
    op.drop_constraint("ck_schedule_templates_kind", "schedule_templates", type_="check")
    op.drop_column("schedules", "amount")
    op.drop_column("schedule_templates", "amount")
    op.drop_column("schedule_templates", "kind")
    op.drop_index(
        "uq_contacts_business_external_id",
        table_name="contacts",
        postgresql_where=sa.text("external_id IS NOT NULL"),
    )
    op.drop_column("contacts", "external_id")
    # WARNING: constraint name is None; this directive will fail as
    # rendered.  Add a name, or use a naming convention; see
    # https://alembic.sqlalchemy.org/en/latest/naming.html
    op.drop_constraint("fk_broadcasts_created_by_admin", "broadcasts", type_="foreignkey")
    op.drop_column("broadcasts", "sent_at")
    op.drop_column("broadcasts", "failed_count")
    op.drop_column("broadcasts", "delivered_count")
    op.drop_column("broadcasts", "recipients_count")
    op.drop_column("broadcasts", "audience")
    op.drop_column("broadcasts", "message")
    op.drop_column("broadcasts", "created_by_admin_id")
    op.drop_index("ix_ptm_events_group_date", table_name="ptm_events")
    op.drop_table("ptm_events")
    op.drop_index("ix_broadcast_recipients_status", table_name="broadcast_recipients")
    op.drop_table("broadcast_recipients")
    op.drop_table("imports")
    op.drop_table("group_staff")
    op.drop_index("ix_timetable_group", table_name="timetable_entries")
    op.drop_table("timetable_entries")
    op.drop_index("ix_doubts_business_status", table_name="doubts")
    op.drop_table("doubts")
    op.drop_index("ix_contact_links_linked", table_name="contact_links")
    op.drop_table("contact_links")
    op.drop_table("subjects")
