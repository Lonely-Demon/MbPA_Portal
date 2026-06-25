from __future__ import annotations

import datetime
from datetime import timedelta
from typing import Any

from django.contrib.auth import get_user_model

from .models import AuditEvent

User = get_user_model()


def compute_due_at(started_at: datetime.datetime, working_days: int) -> datetime.datetime:
    """
    Return a timezone-aware datetime exactly `working_days` business days after
    `started_at`, skipping weekends (Sat/Sun) and any date present in the Holiday
    table (which includes 2nd/4th Saturdays per seed data).

    Loads all Holiday dates in a generous window up front to avoid N+1 queries.
    """
    from apps.compliance.models import Holiday

    start_date = started_at.date()
    # Load holiday dates in a window generous enough to cover any realistic SLA.
    window_end = start_date + timedelta(days=working_days * 3 + 30)
    holiday_dates: set[datetime.date] = set(
        Holiday.objects.filter(date__gte=start_date, date__lte=window_end).values_list(
            "date", flat=True
        )
    )

    current = start_date
    days_counted = 0
    while days_counted < working_days:
        current += timedelta(days=1)
        if current.weekday() >= 5:  # Saturday=5, Sunday=6
            continue
        if current in holiday_dates:
            continue
        days_counted += 1

    return started_at.replace(year=current.year, month=current.month, day=current.day)


def record_audit_event(
    *,
    verb: str,
    target_type: str,
    target_id: int,
    actor: User | None = None,
    payload: dict[str, Any] | None = None,
    ip_address: str | None = None,
    user_agent: str = "",
) -> AuditEvent:
    """
    Insert one immutable audit event. Never call .save()/.update() on the returned object.
    """
    return AuditEvent.objects.create(
        actor=actor,
        verb=verb,
        target_type=target_type,
        target_id=target_id,
        payload=payload or {},
        ip_address=ip_address,
        user_agent=user_agent,
    )
