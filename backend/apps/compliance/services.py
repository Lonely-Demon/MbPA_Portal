from __future__ import annotations

from typing import Any

from django.contrib.auth import get_user_model
from django.utils import timezone

from .models import AuditEvent

User = get_user_model()


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
