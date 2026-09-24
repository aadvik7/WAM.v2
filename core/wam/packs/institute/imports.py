"""Sheet uploads: students, attendance (absent students' parents get a message), test results (each parent
gets their child's score) and the timetable. Every upload is previewed first, then applied."""

from __future__ import annotations

import datetime as dt
import logging
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from wam import clock
from wam.jobs.queue import kick_jobs, schedule_job
from wam.messaging import Outgoing, send_to_contact
from wam.models import Business, Contact, Group, Import, TimetableEntry
from wam.packs.institute import batches as batch_mod
from wam.packs.institute.sheets import (
    SheetError,
    is_absent,
    parse_clock,
    parse_sheet_date,
    parse_weekday,
    read_sheet,
)
from wam.people import reach_for_family

log = logging.getLogger(__name__)

KINDS = ("students", "attendance", "results", "timetable")
SEND_BATCH = 40


class UploadError(Exception):
    pass


def _student_key(row: dict[str, str]) -> str:
    return (row.get("roll") or row.get("phone") or row.get("name") or "").strip()


def _label_for(row: dict[str, Any]) -> str:
    return row.get("student") or row.get("key") or f"row {row.get('row')}"


# --------------------------------------------------------------------------------------
# Preview
# --------------------------------------------------------------------------------------


async def _preview_students(
    session: AsyncSession, business: Business, rows: list[dict[str, str]], group: Group | None
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    out: list[dict[str, Any]] = []
    counts = {"rows": len(rows), "new": 0, "update": 0, "errors": 0}
    batches: set[str] = set()
    for n, row in enumerate(rows, start=2):
        item: dict[str, Any] = {
            "row": n,
            "roll": row.get("roll") or None,
            "name": row.get("name") or None,
            "phone": row.get("phone") or None,
            "parents": [p for p in (row.get("parent1"), row.get("parent2")) if p],
            "parent_names": [row.get("parent1_name") or None, row.get("parent2_name") or None],
            "batch": row.get("batch") or (group.name if group else None),
        }
        if not item["name"] and not item["roll"]:
            item["error"] = "needs a name or roll number"
        elif not item["phone"] and not item["parents"]:
            item["error"] = "needs a student or parent phone number"
        elif not item["batch"]:
            item["error"] = "no batch (add a Batch column or choose a batch)"
        if item.get("error"):
            counts["errors"] += 1
        else:
            existing = None
            if item["roll"]:
                existing = await batch_mod.find_student(session, business.id, item["roll"])
            item["action"] = "update" if existing else "new"
            counts[item["action"]] += 1
            batches.add(item["batch"])
        out.append(item)
    return out, {**counts, "batches": sorted(batches)}


async def _match_rows(
    session: AsyncSession, business: Business, rows: list[dict[str, str]], group: Group | None
) -> list[tuple[dict[str, str], Contact | None, int]]:
    matched = []
    for n, row in enumerate(rows, start=2):
        key = _student_key(row)
        student = (
            await batch_mod.find_student(session, business.id, key, group.id if group else None)
            if key
            else None
        )
        matched.append((row, student, n))
    return matched


async def _preview_attendance(
    session: AsyncSession,
    business: Business,
    rows: list[dict[str, str]],
    group: Group | None,
    columns: list[str],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    has_status = "status" in columns
    out: list[dict[str, Any]] = []
    counts = {"rows": len(rows), "absent": 0, "present": 0, "unmatched": 0, "messages": 0}
    for row, student, n in await _match_rows(session, business, rows, group):
        absent = is_absent(row.get("status", "")) if has_status else True
        item: dict[str, Any] = {"row": n, "key": _student_key(row), "absent": absent}
        if student is None:
            item["error"] = "student not found"
            counts["unmatched"] += 1
        elif absent is None:
            item["error"] = f"unclear status '{row.get('status')}' (use P or A)"
            counts["unmatched"] += 1
        else:
            item["student_id"] = student.id
            item["student"] = student.name or student.external_id
            if absent:
                reach = await reach_for_family(session, student)
                item["recipients"] = len(reach)
                item["pending"] = bool(reach)
                counts["absent"] += 1
                counts["messages"] += len(reach)
            else:
                counts["present"] += 1
        out.append(item)
    return out, {**counts, "status_column": has_status}


async def _preview_results(
    session: AsyncSession,
    business: Business,
    rows: list[dict[str, str]],
    group: Group | None,
    label: str | None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    out: list[dict[str, Any]] = []
    counts = {"rows": len(rows), "scores": 0, "unmatched": 0, "messages": 0}
    for row, student, n in await _match_rows(session, business, rows, group):
        score = (row.get("score") or "").strip()
        maximum = (row.get("max") or "").strip()
        test = (row.get("test") or label or "").strip()
        item: dict[str, Any] = {"row": n, "key": _student_key(row), "score": score, "test": test}
        if student is None:
            item["error"] = "student not found"
            counts["unmatched"] += 1
        elif not score:
            item["error"] = "no score"
            counts["unmatched"] += 1
        elif not test:
            item["error"] = "no test name (add a Test column or enter the test name)"
            counts["unmatched"] += 1
        else:
            item["score_text"] = f"{score}/{maximum}" if maximum and "/" not in score else score
            item["student_id"] = student.id
            item["student"] = student.name or student.external_id
            reach = await reach_for_family(session, student)
            item["recipients"] = len(reach)
            item["pending"] = bool(reach)
            counts["scores"] += 1
            counts["messages"] += len(reach)
        out.append(item)
    return out, counts


async def _preview_timetable(
    session: AsyncSession, business: Business, rows: list[dict[str, str]], group: Group | None
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    batches = await batch_mod.list_batches(session, business.id)
    out: list[dict[str, Any]] = []
    counts = {"rows": len(rows), "entries": 0, "errors": 0}
    names: set[str] = set()
    for n, row in enumerate(rows, start=2):
        item: dict[str, Any] = {"row": n}
        batch = batch_mod.match_batch(row["batch"], batches) if row.get("batch") else group
        weekday = parse_weekday(row.get("day", "")) if row.get("day") else None
        date = parse_sheet_date(row.get("date", "")) if row.get("date") else None
        start = parse_clock(row.get("start", ""))
        end = parse_clock(row.get("end", "")) if row.get("end") else None
        subject = (row.get("subject") or "").strip()
        if batch is None:
            item["error"] = f"unknown batch '{row.get('batch', '')}'" if row.get("batch") else "no batch"
        elif weekday is None and date is None:
            item["error"] = "needs a Day (Mon–Sun) or a Date"
        elif start is None:
            item["error"] = f"can't read start time '{row.get('start', '')}'"
        elif not subject:
            item["error"] = "no subject"
        elif end is not None and end <= start:
            item["error"] = "end time is before start time"
        if item.get("error"):
            counts["errors"] += 1
        else:
            assert batch is not None and start is not None
            item.update(
                group_id=batch.id,
                batch=batch.name,
                weekday=weekday if date is None else None,
                date=date.isoformat() if date else None,
                start=start.strftime("%H:%M"),
                end=end.strftime("%H:%M") if end else None,
                subject=subject[:80],
                teacher=(row.get("teacher") or None),
                room=(row.get("room") or None),
            )
            counts["entries"] += 1
            names.add(batch.name)
        out.append(item)
    return out, {**counts, "batches": sorted(names)}


async def create_import(
    session: AsyncSession,
    business: Business,
    kind: str,
    filename: str,
    data: bytes,
    *,
    label: str | None = None,
    group: Group | None = None,
    staff_id: int | None = None,
    admin_user_id: int | None = None,
) -> Import:
    if kind not in KINDS:
        raise UploadError(f"Unknown upload type '{kind}'")
    try:
        rows, columns = read_sheet(filename, data)
    except SheetError as exc:
        raise UploadError(str(exc)) from exc
    if not rows:
        raise UploadError("The sheet has a header row but no data rows.")
    if kind == "students":
        parsed, summary = await _preview_students(session, business, rows, group)
    elif kind == "attendance":
        if not label and "subject" not in columns:
            raise UploadError("Enter the class name (e.g. 'Physics') so parents know which class was missed.")
        parsed, summary = await _preview_attendance(session, business, rows, group, columns)
    elif kind == "results":
        if "score" not in columns:
            raise UploadError("Add a Marks (or Score) column.")
        parsed, summary = await _preview_results(session, business, rows, group, label)
    else:
        parsed, summary = await _preview_timetable(session, business, rows, group)
    if kind == "attendance" and "subject" in columns:
        for item, row in zip(parsed, rows, strict=False):
            item.setdefault("class", row.get("subject") or label)
    summary["columns"] = columns
    imp = Import(
        business_id=business.id,
        kind=kind,
        filename=(filename or "")[:200],
        label=(label or None),
        group_id=group.id if group else None,
        rows=parsed,
        summary=summary,
        status="preview",
        created_by_staff_id=staff_id,
        created_by_admin_id=admin_user_id,
    )
    session.add(imp)
    await session.flush()
    return imp


# --------------------------------------------------------------------------------------
# Apply
# --------------------------------------------------------------------------------------


async def apply(session: AsyncSession, business: Business, imp: Import) -> dict[str, Any]:
    if imp.status != "preview":
        raise UploadError("This upload was already applied or cancelled.")
    imp.status = "applied"
    imp.applied_at = clock.now()
    if imp.kind == "students":
        result = await _apply_students(session, business, imp)
    elif imp.kind == "timetable":
        result = await _apply_timetable(session, business, imp)
    else:
        # Messages go out through the worker, a batch at a time.
        await schedule_job(
            session,
            business.id,
            "import_send",
            clock.now(),
            {"import_id": imp.id},
            dedupe_key=f"import_send:{imp.id}:0",
        )
        await kick_jobs()
        result = {"queued": sum(1 for r in imp.rows if r.get("pending"))}
    imp.summary = {**imp.summary, "applied": result}
    return result


async def _apply_students(session: AsyncSession, business: Business, imp: Import) -> dict[str, Any]:
    created = updated = 0
    notes: list[str] = []
    for item in imp.rows:
        if item.get("error"):
            continue
        try:
            async with session.begin_nested():
                student, was_created, row_notes = await batch_mod.upsert_student(
                    session,
                    business,
                    batch_mod.StudentInput(
                        name=item.get("name"),
                        roll=item.get("roll"),
                        phone=item.get("phone"),
                        parent_phones=tuple(item.get("parents") or ()),
                        parent_names=tuple(item.get("parent_names") or ()),
                    ),
                )
                group = await batch_mod.get_or_create_batch(session, business, item["batch"])
                await batch_mod.add_to_batch(session, group, student)
        except batch_mod.StudentError as exc:
            notes.append(f"row {item['row']}: {exc}")
            continue
        created += int(was_created)
        updated += int(not was_created)
        notes.extend(f"row {item['row']}: {n}" for n in row_notes)
    return {"created": created, "updated": updated, "notes": notes[:50]}


async def _apply_timetable(session: AsyncSession, business: Business, imp: Import) -> dict[str, Any]:
    valid = [r for r in imp.rows if not r.get("error")]
    weekly_groups = {r["group_id"] for r in valid if r.get("weekday") is not None}
    dated = {(r["group_id"], r["date"]) for r in valid if r.get("date")}
    # A new weekly timetable replaces the old one for those batches; dated rows replace that day's entries.
    if weekly_groups:
        await session.execute(
            delete(TimetableEntry).where(
                TimetableEntry.group_id.in_(weekly_groups), TimetableEntry.weekday.is_not(None)
            )
        )
    for group_id, date in dated:
        await session.execute(
            delete(TimetableEntry).where(
                TimetableEntry.group_id == group_id, TimetableEntry.date == dt.date.fromisoformat(date)
            )
        )
    for r in valid:
        session.add(
            TimetableEntry(
                business_id=business.id,
                group_id=r["group_id"],
                weekday=r.get("weekday"),
                date=dt.date.fromisoformat(r["date"]) if r.get("date") else None,
                start_time=dt.time.fromisoformat(r["start"]),
                end_time=dt.time.fromisoformat(r["end"]) if r.get("end") else None,
                subject=r["subject"],
                teacher=r.get("teacher"),
                room=r.get("room"),
            )
        )
    await session.flush()
    return {"entries": len(valid), "batches": sorted({r["batch"] for r in valid})}


async def send_batch(session: AsyncSession, business: Business, imp: Import, limit: int = SEND_BATCH) -> bool:
    """Send attendance / result messages for up to `limit` students. Returns True if more remain."""
    rows = [dict(r) for r in imp.rows]
    done = 0
    sent = int(imp.summary.get("sent", 0))
    failed = int(imp.summary.get("failed", 0))
    for item in rows:
        if not item.get("pending"):
            continue
        if done >= limit:
            break
        done += 1
        item["pending"] = False
        student = await session.get(Contact, int(item["student_id"]))
        if student is None:
            continue
        name = (student.name or item.get("student") or "Your child").split(" ")[0]
        if imp.kind == "attendance":
            cls = item.get("class") or imp.label or "class"
            text = (
                f"Attendance alert: {name} was marked absent in {cls} today. Reply here if this is a mistake."
            )
            out_values = {"student": name, "class": cls}
            key = "absence_alert"
        else:
            test = item.get("test") or imp.label or "the test"
            text = f"Test result: {name} scored {item['score_text']} in {test}. Reply here to talk to the teacher."
            out_values = {"student": name, "score": item["score_text"], "test": test}
            key = "test_result"
        for target in await reach_for_family(session, student):
            row = await send_to_contact(
                session,
                business,
                target,
                Outgoing(text=text, template_key=key, template_values=out_values),
                handled_by="staff",
                proactive=True,
            )
            if row is not None and row.status in ("ok", "dry_run"):
                sent += 1
            else:
                failed += 1
    imp.rows = rows
    remaining = sum(1 for r in rows if r.get("pending"))
    imp.summary = {**imp.summary, "sent": sent, "failed": failed, "remaining": remaining}
    return remaining > 0


def summary_out(imp: Import, tz: str) -> dict[str, Any]:
    return {
        "id": imp.id,
        "kind": imp.kind,
        "filename": imp.filename,
        "label": imp.label,
        "group_id": imp.group_id,
        "status": imp.status,
        "summary": imp.summary,
        "created_at": clock.to_local(imp.created_at, tz).isoformat(),
        "applied_at": clock.to_local(imp.applied_at, tz).isoformat() if imp.applied_at else None,
    }


async def get_import(session: AsyncSession, business_id: int, import_id: int) -> Import | None:
    imp = (
        await session.execute(select(Import).where(Import.id == import_id, Import.business_id == business_id))
    ).scalar_one_or_none()
    return imp
