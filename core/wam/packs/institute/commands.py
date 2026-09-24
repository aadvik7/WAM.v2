"""Institute staff commands on WhatsApp.

Send to NEET-A2: Tomorrow's class starts at 8 AM        (announce; + "parents"/"students" after the batch)
Absent NEET-A2 Physics: 12, 15, 21                        (absence alerts to parents; roll numbers or names)
Aarav paid  /  Paid 12                                    (records the next fee installment)
Announcement status                                       (last announcement's delivery and read counts)
My batches
"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import select

from wam.models import Broadcast, Group, Import, PendingAction
from wam.packs.institute import batches as batch_mod
from wam.packs.institute import broadcasts, fees, imports
from wam.people import reach_for_family
from wam.staff.parser import Command, clean

_ANNOUNCE = re.compile(
    r"^(?:send|announce(?:ment)?|message|msg|broadcast)\s+(?:to\s+|for\s+)?(?P<target>[^:\n]+?)\s*:\s*(?P<msg>.+)$",
    re.I | re.S,
)
_ABSENT = re.compile(
    r"^(?:absent|absentees|absence)\s+(?:in\s+|for\s+)?(?P<target>[^:\n]+?)\s*:\s*(?P<list>.+)$", re.I | re.S
)
_PAID_1 = re.compile(
    r"^(?:paid|fees? paid|fees? received|received fees?(?: from)?)\s+(?:by\s+|for\s+|from\s+)?(?P<who>.+)$",
    re.I,
)
_PAID_2 = re.compile(r"^(?P<who>.+?)\s+(?:has\s+)?(?:paid(?:\s+(?:the\s+)?fees?)?|fees?\s+paid)$", re.I)
_STATUS = re.compile(
    r"^(?:(?:last\s+)?(?:announcement|broadcast)\s+status|last\s+announcement|announcement\s+stats?)$", re.I
)
_BATCHES = re.compile(r"^(?:my\s+)?batches$", re.I)
AUDIENCE_WORDS = {
    "parents": "parents",
    "parent": "parents",
    "students": "students",
    "student": "students",
    "everyone": "everyone",
    "all": "everyone",
    "both": "everyone",
}

HELP_TEXT = """WAM commands (institute):
• Send to NEET-A2: <message> — announcement to every student and parent of the batch (add "parents" or "students" after the batch name to narrow it). Needs YES + PIN
• Absent NEET-A2 Physics: 12, 15, 21 — absence alerts to those students' parents (roll numbers or names). Needs YES + PIN
• Aarav paid (or Paid 12) — records the next fee installment
• Announcement status — delivery and read counts of the last announcement
• My batches — your batches
• Today's list, Summary, Find <name>, help"""

REWRITE_FORMS = """- send to <batch>: <message> | send to <batch> parents: <message>
- absent <batch> <class>: <roll numbers or names, comma separated>
- <student name or roll number> paid
- announcement status
- my batches"""


def parse(text: str) -> Command | None:
    raw = text.strip()
    body = clean(raw)
    m = _ANNOUNCE.match(raw)
    if m:
        return Command("announce", {"target": m.group("target").strip(), "message": m.group("msg").strip()})
    m = _ABSENT.match(raw)
    if m:
        return Command("absent", {"target": m.group("target").strip(), "list": m.group("list").strip()})
    if _STATUS.match(body):
        return Command("announce_status")
    if _BATCHES.match(body):
        return Command("my_batches")
    m = _PAID_1.match(body) or _PAID_2.match(body)
    if m:
        return Command("paid", {"who": m.group("who").strip(" ,.")})
    return None


# Permission key per command (announce_status is visible to anyone who can announce).
PERMISSION = {
    "announce": "announce",
    "absent": "absent",
    "paid": "paid",
    "announce_status": "announce",
    "my_batches": "today",
}


def _split_audience(target: str) -> tuple[str, str]:
    words = target.split()
    if words and words[-1].lower() in AUDIENCE_WORDS:
        return " ".join(words[:-1]), AUDIENCE_WORDS[words[-1].lower()]
    if words and words[0].lower() in AUDIENCE_WORDS:
        return " ".join(words[1:]), AUDIENCE_WORDS[words[0].lower()]
    return target, "everyone"


async def _batch_for(ctx: Any, name: str) -> tuple[Group | None, str | None]:
    """Resolve a batch the staff member may message. Returns (group, error message)."""
    batches = await batch_mod.list_batches(ctx.session, ctx.business.id)
    group = batch_mod.match_batch(name, batches)
    if group is None:
        names = ", ".join(b.name for b in batches) or "none yet"
        return None, f"I don't know the batch '{name}'. Batches: {names}."
    commands = (ctx.staff.role.allowed_commands if ctx.staff.role else []) or []
    if "*" in commands or "announce_all" in commands:
        return group, None
    own = await batch_mod.teacher_batches(ctx.session, ctx.staff)
    if all(b.id != group.id for b in own):
        mine = ", ".join(b.name for b in own) or "none assigned"
        return None, f"You can only message your own batches ({mine})."
    return group, None


async def handle(ctx: Any, cmd: Command) -> bool:
    """Run an institute command. Returns False if the command isn't ours."""
    from wam.staff.commands import ask_confirmation  # imported lazily: core imports this module lazily too

    if cmd.key == "announce":
        name, audience = _split_audience(cmd.args["target"])
        group, error = await _batch_for(ctx, name)
        if group is None:
            await ctx.reply(error or "Unknown batch.")
            return True
        try:
            b = await broadcasts.create_broadcast(
                ctx.session, ctx.business, group, cmd.args["message"], audience, staff=ctx.staff
            )
        except broadcasts.BroadcastError as exc:
            await ctx.reply(str(exc))
            return True
        counts = b.params.get("counts", {})
        who = []
        if counts.get("students"):
            who.append(f"{counts['students']} students")
        if counts.get("parents"):
            who.append(f"{counts['parents']} parents")
        missing = (
            f"\n({counts['unreachable']} students have no number for this audience.)"
            if counts.get("unreachable")
            else ""
        )
        prompt = (
            f"Announcement to {group.name}: {b.recipients_count} people ({', '.join(who)}), each individually.\n"
            f'Preview:\n"{broadcasts.preview(group, b.message)}"{missing}\n\n'
            "Reply YES and your PIN (e.g. YES 1234) within 10 minutes to send, or NO."
        )
        await ask_confirmation(
            ctx, "announce", {"broadcast_id": b.id}, f"Announcement to {group.name}", prompt=prompt
        )
        return True

    if cmd.key == "absent":
        batches = await batch_mod.list_batches(ctx.session, ctx.business.id)
        group, cls = batch_mod.split_batch_prefix(cmd.args["target"], batches)
        if group is None:
            group = batch_mod.match_batch(cmd.args["target"], batches)
            cls = ""
        if group is None:
            names = ", ".join(b.name for b in batches) or "none yet"
            await ctx.reply(
                f"Start with the batch name, e.g. 'Absent NEET-A2 Physics: 12, 15'. Batches: {names}."
            )
            return True
        allowed_group, error = await _batch_for(ctx, group.name)
        if allowed_group is None:
            await ctx.reply(error or "Not allowed.")
            return True
        raw_list = cmd.args["list"]
        parts = (
            [p.strip() for p in re.split(r",|\band\b|\n", raw_list)]
            if ("," in raw_list or "\n" in raw_list)
            else raw_list.split()
        )
        keys = [p for p in parts if p]
        rows: list[dict[str, Any]] = []
        found, missing = [], []
        for n, key in enumerate(keys, start=1):
            student = await batch_mod.find_student(ctx.session, ctx.business.id, key, group.id)
            if student is None:
                missing.append(key)
                rows.append({"row": n, "key": key, "absent": True, "error": "student not found"})
                continue
            reach = await reach_for_family(ctx.session, student)
            found.append(
                f"{student.name or key} ({student.external_id})"
                if student.external_id
                else (student.name or key)
            )
            rows.append(
                {
                    "row": n,
                    "key": key,
                    "absent": True,
                    "student_id": student.id,
                    "student": student.name or key,
                    "recipients": len(reach),
                    "pending": bool(reach),
                    "class": cls or group.name,
                }
            )
        if not found:
            await ctx.reply(
                f"I couldn't match any of {', '.join(keys)} in {group.name}. Use roll numbers or full names."
            )
            return True
        imp = Import(
            business_id=ctx.business.id,
            kind="attendance",
            filename=None,
            label=cls or group.name,
            group_id=group.id,
            rows=rows,
            summary={
                "absent": len(found),
                "unmatched": len(missing),
                "messages": sum(r.get("recipients", 0) for r in rows),
            },
            status="preview",
            created_by_staff_id=ctx.staff.id,
        )
        ctx.session.add(imp)
        await ctx.session.flush()
        note = f"\nNot found: {', '.join(missing)}." if missing else ""
        prompt = (
            f"Send absence alerts for {cls or group.name} ({group.name}) to the parents of: {', '.join(found)}."
            f"{note}\nReply YES and your PIN within 10 minutes to send, or NO."
        )
        await ask_confirmation(ctx, "absent", {"import_id": imp.id}, "Absence alerts", prompt=prompt)
        return True

    if cmd.key == "paid":
        student = await batch_mod.find_student(ctx.session, ctx.business.id, cmd.args["who"])
        if student is None:
            await ctx.reply(
                f"I couldn't find a student '{cmd.args['who']}'. Use the roll number or full name."
            )
            return True
        plans = await fees.fee_plans(ctx.session, student)
        plans = [p for p in plans if p.contact_id == student.id]
        if not plans:
            await ctx.reply(f"{student.name or cmd.args['who']} has no active fee plan.")
            return True
        message = await fees.record_payment(ctx.session, ctx.business, plans[0])
        await ctx.audit("fee_paid", {"schedule_id": plans[0].id, "contact_id": student.id})
        await ctx.reply(message)
        return True

    if cmd.key == "announce_status":
        stmt = select(Broadcast).where(Broadcast.business_id == ctx.business.id)
        commands = (ctx.staff.role.allowed_commands if ctx.staff.role else []) or []
        if "*" not in commands and "announce_all" not in commands:
            stmt = stmt.where(Broadcast.sender_staff_id == ctx.staff.id)
        last = (await ctx.session.execute(stmt.order_by(Broadcast.id.desc()).limit(1))).scalar_one_or_none()
        if last is None:
            await ctx.reply("No announcements yet.")
            return True
        batch = last.params.get("batch", "")
        await ctx.reply(
            f"Last announcement to {batch} ({last.status}): {last.sent_count} of {last.recipients_count} sent, "
            f"{last.delivered_count} delivered, {last.read_count} read"
            + (f", {last.failed_count} failed" if last.failed_count else "")
            + "."
        )
        return True

    if cmd.key == "my_batches":
        own = await batch_mod.teacher_batches(ctx.session, ctx.staff)
        await ctx.reply(
            "Your batches: "
            + (", ".join(b.name for b in own) if own else "none assigned yet (ask the coordinator).")
        )
        return True
    return False


async def execute_pending(ctx: Any, pending: PendingAction) -> bool:
    if pending.action == "announce":
        b = await ctx.session.get(Broadcast, int(pending.payload["broadcast_id"]))
        if b is None or b.status != "draft":
            await ctx.reply("That announcement was already sent or cancelled.")
            return True
        await broadcasts.start(ctx.session, ctx.business, b)
        await ctx.audit(
            "announce",
            {"broadcast_id": b.id, "batch": b.params.get("batch"), "recipients": b.recipients_count},
        )
        await ctx.reply(f"Sending to {b.recipients_count} people now. I'll tell you when it's done.")
        return True
    if pending.action == "absent":
        imp = await ctx.session.get(Import, int(pending.payload["import_id"]))
        if imp is None or imp.status != "preview":
            await ctx.reply("Those alerts were already sent or cancelled.")
            return True
        await imports.apply(ctx.session, ctx.business, imp)
        await ctx.audit("absence_alerts", {"import_id": imp.id, "absent": imp.summary.get("absent")})
        await ctx.reply(f"Sending absence alerts to the parents of {imp.summary.get('absent', 0)} students.")
        return True
    return False
