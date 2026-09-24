"""Who is linked to whom: students and their parents (institute), children reached through a guardian."""

from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from wam.models import Contact, ContactLink, Group, GroupMember

MAX_PARENTS = 2


async def parents_of(session: AsyncSession, contact: Contact) -> list[Contact]:
    """The contact's guardian plus linked parents (deduplicated, in link order)."""
    out: list[Contact] = []
    if contact.guardian is not None:
        out.append(contact.guardian)
    links = (
        (
            await session.execute(
                select(ContactLink)
                .where(ContactLink.contact_id == contact.id, ContactLink.relation == "parent")
                .order_by(ContactLink.id)
            )
        )
        .scalars()
        .all()
    )
    for link in links:
        if all(p.id != link.linked_id for p in out):
            out.append(link.linked)
    return out


async def children_of(session: AsyncSession, parent: Contact) -> list[Contact]:
    """Students whose parent (or guardian) is this contact."""
    linked_ids = select(ContactLink.contact_id).where(
        ContactLink.linked_id == parent.id, ContactLink.relation == "parent"
    )
    rows = (
        (
            await session.execute(
                select(Contact)
                .where(
                    Contact.business_id == parent.business_id,
                    or_(Contact.guardian_id == parent.id, Contact.id.in_(linked_ids)),
                )
                .order_by(Contact.id)
            )
        )
        .scalars()
        .unique()
        .all()
    )
    return list(rows)


async def link_parent(session: AsyncSession, student: Contact, parent: Contact) -> bool:
    """Link a parent to a student (max two). Returns False if already linked or the limit is reached."""
    if parent.id == student.id:
        return False
    current = await parents_of(session, student)
    if any(p.id == parent.id for p in current):
        return False
    if len(current) >= MAX_PARENTS:
        return False
    session.add(ContactLink(business_id=student.business_id, contact_id=student.id, linked_id=parent.id))
    await session.flush()
    return True


async def groups_of(
    session: AsyncSession, contact_ids: Iterable[int], kind: str | None = "batch"
) -> list[Group]:
    ids = list(contact_ids)
    if not ids:
        return []
    stmt = (
        select(Group)
        .join(GroupMember, GroupMember.group_id == Group.id)
        .where(GroupMember.contact_id.in_(ids))
        .order_by(Group.name)
    )
    if kind:
        stmt = stmt.where(Group.kind == kind)
    return list((await session.execute(stmt)).scalars().unique().all())


async def members_of(session: AsyncSession, group_id: int) -> list[Contact]:
    return list(
        (
            await session.execute(
                select(Contact)
                .join(GroupMember, GroupMember.contact_id == Contact.id)
                .where(GroupMember.group_id == group_id)
                .order_by(Contact.name, Contact.id)
            )
        )
        .scalars()
        .unique()
        .all()
    )


async def reach_for_family(session: AsyncSession, contact: Contact) -> list[Contact]:
    """Who to message about a student: their parents if any, else the student themself."""
    parents = [p for p in await parents_of(session, contact) if p.phone]
    if parents:
        return parents
    return [contact] if contact.phone else []


def fmt_inr(amount: Decimal | float | int | None) -> str:
    """Indian digit grouping: 120000 -> '₹1,20,000'."""
    if amount is None:
        return ""
    value = Decimal(amount).quantize(Decimal("0.01"))
    rupees = int(value)
    paise = int((value - rupees) * 100)
    digits = str(abs(rupees))
    if len(digits) > 3:
        head, tail = digits[:-3], digits[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        digits = ",".join(groups) + "," + tail
    sign = "-" if rupees < 0 else ""
    return f"{sign}₹{digits}" + (f".{paise:02d}" if paise else "")
