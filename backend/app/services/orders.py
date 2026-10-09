"""Order lifecycle + side effects (payments, client stats) and platform-event -> order linking."""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Client,
    Milestone,
    Order,
    Payment,
    PlatformAccount,
    PlatformEvent,
    User,
)
from app.models.work import ORDER_STATUSES
from app.services import automation, finance


async def record_payment(
    db: AsyncSession, user: User, *, source: str, source_id: str, platform: str, gross: float, currency: str,
    client_id: uuid.UUID | None = None, fee: float | None = None, note: str = "", received_on: Any = None,
) -> tuple[Payment, bool]:  # fmt: skip
    """Idempotent per (source, source_id)."""
    existing = (
        await db.execute(
            select(Payment).where(
                Payment.user_id == user.id, Payment.source == source, Payment.source_id == source_id
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing, False
    fee_amt = finance.fee_for(user, platform, gross) if fee is None else fee
    p = Payment(
        user_id=user.id,
        client_id=client_id,
        platform=platform,
        source=source,
        source_id=source_id,
        gross=gross,
        fee=fee_amt,
        net=round(gross - fee_amt, 2),
        currency=currency,
        note=note,
    )
    if received_on:
        p.received_on = received_on
    db.add(p)
    await db.flush()
    await automation.fire(
        db, user.id, "payment.received",
        {"platform": platform, "amount": gross, "net": p.net, "currency": currency, "source": source, "client_id": str(client_id or "")},
        dedupe_key=f"pay:{p.id}",
    )  # fmt: skip
    return p, True


async def _bump_client(db: AsyncSession, order: Order, amount_net: float) -> None:
    if order.client_id:
        c = await db.get(Client, order.client_id)
        if c:
            c.total_earned += amount_net
            c.completed_orders += 1


async def set_status(db: AsyncSession, order: Order, status: str) -> None:
    if status not in ORDER_STATUSES:
        raise ValueError(f"status must be one of {ORDER_STATUSES}")
    if status == order.status:
        return
    now = datetime.now(UTC)
    order.status = status
    if status == "delivered":
        order.delivered_at = now
    elif status == "revision":
        order.revisions_used += 1
    elif status == "completed":
        order.completed_at = now
        user = await db.get(User, order.user_id)
        assert user is not None
        paid = sum(
            m.amount
            for m in (
                await db.execute(
                    select(Milestone).where(
                        Milestone.order_id == order.id, Milestone.status == "paid"
                    )
                )
            ).scalars()
        )
        remaining = round(order.amount - paid, 2)
        net = 0.0
        if remaining > 0:
            p, created = await record_payment(
                db, user, source="order", source_id=str(order.id), platform=order.platform, gross=remaining, currency=order.currency,
                client_id=order.client_id, note=order.title,
            )  # fmt: skip
            net = p.net if created else 0.0
        await _bump_client(db, order, net + paid)
    await automation.fire(
        db, order.user_id, "order.status_changed",
        {"order_id": str(order.id), "status": status, "platform": order.platform, "title": order.title, "client_id": str(order.client_id or ""), "amount": order.amount},
        dedupe_key=f"order:{order.id}:{status}:{order.revisions_used}",
    )  # fmt: skip


async def pay_milestone(db: AsyncSession, order: Order, m: Milestone) -> Payment | None:
    if m.status == "paid":
        return None
    m.status, m.paid_at = "paid", datetime.now(UTC)
    user = await db.get(User, order.user_id)
    assert user is not None
    p, _ = await record_payment(
        db, user, source="milestone", source_id=str(m.id), platform=order.platform, gross=m.amount, currency=order.currency,
        client_id=order.client_id, note=f"{order.title} - {m.title}",
    )  # fmt: skip
    return p


async def apply_platform_event(db: AsyncSession, user_id: uuid.UUID, ev: PlatformEvent) -> None:
    """Parsed notification emails keep orders up to date (create / deliver / complete / revise / paid)."""
    from app.services import inbox

    user = await db.get(User, user_id)
    if user is None:
        return
    ref = str(ev.meta.get("order_id") or "")
    amount = float(ev.meta.get("amount") or 0)
    cur = str(ev.meta.get("currency") or "USD")
    if ev.kind == "payment" and amount > 0:
        await record_payment(
            db,
            user,
            source="email",
            source_id=str(ev.id),
            platform=ev.platform,
            gross=amount,
            currency=cur,
            fee=0.0,
            note=ev.title,
        )
        return
    if ev.kind not in ("order", "order_delivered", "revision") or not ref:
        return
    order = (
        await db.execute(
            select(Order).where(
                Order.user_id == user_id, Order.platform == ev.platform, Order.external_ref == ref
            )
        )
    ).scalar_one_or_none()
    if order is None:
        if ev.kind != "order":
            return
        who = str(ev.meta.get("counterparty") or "")
        client = (
            await inbox.resolve_client(db, user_id, ev.platform, who, name=who) if who else None
        )
        acc = (
            await db.execute(
                select(PlatformAccount)
                .where(PlatformAccount.user_id == user_id, PlatformAccount.platform == ev.platform)
                .limit(1)
            )
        ).scalar_one_or_none()
        db.add(
            Order(
                user_id=user_id,
                platform=ev.platform,
                external_ref=ref,
                title=ev.title[:300],
                amount=amount,
                currency=cur,
                client_id=client.id if client else None,
                account_id=acc.id if acc else None,
                source="email",
            )
        )
        await db.flush()
        return
    if ev.kind == "order_delivered":
        await set_status(
            db,
            order,
            "completed"
            if "complet" in ev.title.lower() or "accept" in ev.title.lower()
            else "delivered",
        )
    elif ev.kind == "revision":
        await set_status(db, order, "revision")
