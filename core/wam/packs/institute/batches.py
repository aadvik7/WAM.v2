"""Batches (groups of kind 'batch'), students and their parents, teachers per batch."""

from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from wam.models import Business, Contact, ContactLink, Group, GroupMember, GroupStaff, Staff
from wam.people import MAX_PARENTS, link_parent, parents_of
from wam.phone import normalize_phone

BATCH = "batch"


class StudentError(Exception):
    pass


def _key(name: str) -> str:
    return re.sub(r"[\s\-_./]+", "", name.lower())


async def list_batches(session: AsyncSession, business_id: int) -> list[Group]:
    return list(
        (
            await session.execute(
                select(Group)
                .where(Group.business_id == business_id, Group.kind == BATCH)
                .order_by(Group.name)
            )
        )
        .scalars()
        .all()
    )


def match_batch(text: str, batches: list[Group]) -> Group | None:
    """'neet a2', 'NEET-A2' and 'neeta2' all find the batch 'NEET-A2'."""
    key = _key(text)
    if not key:
        return None
    exact = [b for b in batches if _key(b.name) == key]
    if exact:
        return exact[0]
    starts = [b for b in batches if _key(b.name).startswith(key)]
    return starts[0] if len(starts) == 1 else None


def split_batch_prefix(text: str, batches: list[Group]) -> tuple[Group | None, str]:
    """Longest batch name at the start of the text: 'NEET-A2 Physics' -> (NEET-A2, 'Physics')."""
    words = text.split()
    for n in range(len(words), 0, -1):
        group = match_batch(" ".join(words[:n]), batches)
        if group is not None and _key(group.name) == _key(" ".join(words[:n])):
            return group, " ".join(words[n:]).strip()
    return None, text


async def get_or_create_batch(session: AsyncSession, business: Business, name: str) -> Group:
    name = name.strip()
    if not name:
        raise StudentError("Batch name is empty")
    existing = match_batch(name, await list_batches(session, business.id))
    if existing is not None and _key(existing.name) == _key(name):
        return existing
    group = Group(business_id=business.id, name=name[:120], kind=BATCH)
    session.add(group)
    await session.flush()
    return group


async def add_to_batch(session: AsyncSession, group: Group, contact: Contact) -> bool:
    exists = (
        await session.execute(
            select(GroupMember).where(GroupMember.group_id == group.id, GroupMember.contact_id == contact.id)
        )
    ).scalar_one_or_none()
    if exists is not None:
        return False
    session.add(GroupMember(group_id=group.id, contact_id=contact.id))
    await session.flush()
    return True


async def remove_from_batch(session: AsyncSession, group: Group, contact_id: int) -> None:
    await session.execute(
        delete(GroupMember).where(GroupMember.group_id == group.id, GroupMember.contact_id == contact_id)
    )


async def batch_teacher_ids(session: AsyncSession, group_id: int) -> list[int]:
    return list(
        (await session.execute(select(GroupStaff.staff_id).where(GroupStaff.group_id == group_id)))
        .scalars()
        .all()
    )


async def set_batch_teachers(session: AsyncSession, group: Group, staff_ids: list[int]) -> None:
    await session.execute(delete(GroupStaff).where(GroupStaff.group_id == group.id))
    for sid in dict.fromkeys(staff_ids):
        session.add(GroupStaff(group_id=group.id, staff_id=sid))
    await session.flush()


async def teacher_batches(session: AsyncSession, staff: Staff) -> list[Group]:
    return list(
        (
            await session.execute(
                select(Group)
                .join(GroupStaff, GroupStaff.group_id == Group.id)
                .where(GroupStaff.staff_id == staff.id, Group.kind == BATCH)
                .order_by(Group.name)
            )
        )
        .scalars()
        .all()
    )


async def contact_by_phone(session: AsyncSession, business_id: int, phone: str) -> Contact | None:
    return (
        await session.execute(
            select(Contact).where(
                Contact.business_id == business_id, Contact.phone == phone, Contact.guardian_id.is_(None)
            )
        )
    ).scalar_one_or_none()


async def find_student(
    session: AsyncSession, business_id: int, key: str, group_id: int | None = None
) -> Contact | None:
    """By roll number, then phone, then name: exact, or a unique first-name match ("Aarav" → "Aarav Shah").
    Name matches are limited to the batch when one is given."""
    key = str(key or "").strip()
    if not key:
        return None
    by_roll = (
        await session.execute(
            select(Contact).where(
                Contact.business_id == business_id, func.lower(Contact.external_id) == key.lower()
            )
        )
    ).scalar_one_or_none()
    if by_roll is not None:
        return by_roll
    phone = normalize_phone(key)
    if phone is not None and re.fullmatch(r"[+\d\s\-()]{8,}", key):
        found = await contact_by_phone(session, business_id, phone)
        if found is not None:
            return found
    for condition in (func.lower(Contact.name) == key.lower(), Contact.name.ilike(f"{key} %")):
        stmt = select(Contact).where(Contact.business_id == business_id, condition)
        if group_id is not None:
            stmt = stmt.join(GroupMember, GroupMember.contact_id == Contact.id).where(
                GroupMember.group_id == group_id
            )
        else:
            # without a batch, only people who are in some batch count as students
            stmt = stmt.where(Contact.id.in_(select(GroupMember.contact_id)))
        matches = list((await session.execute(stmt.limit(2))).scalars().unique().all())
        if matches:
            return matches[0] if len(matches) == 1 else None
    return None


@dataclass
class StudentInput:
    name: str | None = None
    roll: str | None = None
    phone: str | None = None
    parent_phones: tuple[str | None, ...] = ()
    parent_names: tuple[str | None, ...] = ()


async def _parent_contact(session: AsyncSession, business: Business, phone: str, name: str | None) -> Contact:
    parent = await contact_by_phone(session, business.id, phone)
    if parent is None:
        parent = Contact(business_id=business.id, phone=phone, name=name or None)
        session.add(parent)
        await session.flush()
        await session.refresh(parent, ["guardian"])
    elif name and not parent.name:
        parent.name = name
    return parent


async def upsert_student(
    session: AsyncSession, business: Business, data: StudentInput
) -> tuple[Contact, bool, list[str]]:
    """Create or update a student (matched by roll number, then own phone). Returns (student, created, notes)."""
    notes: list[str] = []
    roll = (data.roll or "").strip() or None
    phone = normalize_phone(data.phone) if data.phone else None
    if data.phone and phone is None:
        notes.append(f"invalid student phone '{data.phone}'")
    parents: list[tuple[str, str | None]] = []
    for raw, pname in zip(data.parent_phones, list(data.parent_names) + [None] * 2, strict=False):
        if not raw:
            continue
        p = normalize_phone(raw)
        if p is None:
            notes.append(f"invalid parent phone '{raw}'")
        elif p not in [x for x, _ in parents]:
            parents.append((p, pname))
    parents = parents[:MAX_PARENTS]
    # A student who uses a parent's phone is reached through the parent, not stored with that number.
    if phone is not None and phone in [p for p, _ in parents]:
        phone = None

    student: Contact | None = None
    if roll:
        student = (
            await session.execute(
                select(Contact).where(
                    Contact.business_id == business.id, func.lower(Contact.external_id) == roll.lower()
                )
            )
        ).scalar_one_or_none()
    if student is None and phone is not None:
        student = await contact_by_phone(session, business.id, phone)
    created = student is None
    if student is None:
        if not data.name and not roll:
            raise StudentError("A student needs a name or roll number")
        if phone is None and not parents:
            raise StudentError(f"{data.name or roll}: needs a student or parent WhatsApp number")
        student = Contact(business_id=business.id, name=data.name or None, external_id=roll, phone=phone)
        session.add(student)
        await session.flush()
        await session.refresh(student, ["guardian"])
    else:
        if data.name:
            student.name = data.name
        if roll and not student.external_id:
            student.external_id = roll
        if phone and not student.phone:
            clash = await contact_by_phone(session, business.id, phone)
            if clash is None:
                student.phone = phone
    for p, pname in parents:
        parent = await _parent_contact(session, business, p, pname)
        if parent.id == student.id:
            continue
        linked = await link_parent(session, student, parent)
        if not linked and all(x.id != parent.id for x in await parents_of(session, student)):
            notes.append(f"already has {MAX_PARENTS} parent numbers; {p} not added")
    return student, created, notes


async def student_summary(session: AsyncSession, student: Contact) -> dict:
    parents = await parents_of(session, student)
    return {
        "id": student.id,
        "name": student.name,
        "roll": student.external_id,
        "phone": student.phone,
        "parents": [{"id": p.id, "name": p.name, "phone": p.phone} for p in parents],
        "opted_out": student.opted_out,
    }


async def unlink_parent(session: AsyncSession, student: Contact, parent_id: int) -> None:
    await session.execute(
        delete(ContactLink).where(ContactLink.contact_id == student.id, ContactLink.linked_id == parent_id)
    )
    if student.guardian_id == parent_id:
        student.guardian_id = None
