from __future__ import annotations

import logging

from django.core.mail import send_mail
from django.template.loader import render_to_string

from apps.common.exceptions import DomainError

logger = logging.getLogger("apps")


class EmailDeliveryError(DomainError):
    """Raised when send_email fails. See send_email's docstring."""


def send_email(to: str, template: str, context: dict) -> None:
    """
    Send a plain-text email rendered from notifications/{template}.txt.

    M-6: raises EmailDeliveryError on failure (after logging) rather than
    swallowing it — a caller for whom the email IS the outcome (e.g. OTP
    delivery) needs to know it didn't go out, rather than reporting success
    to a user who will never receive a code. Callers for whom the email is a
    secondary, best-effort side notification (a fraud alert, a "dossier
    ready" notice) should catch EmailDeliveryError locally and continue.
    The Resend 100/day production cap applies; see Docs/runbooks/resend_dns.md.
    """
    subject = context.get("subject", "MbPA Portal — Action Required")
    try:
        body = render_to_string(f"notifications/{template}.txt", context)
        send_mail(subject, body, None, [to], fail_silently=False)
    except Exception as exc:
        logger.exception("Failed to send email template=%r to=%r", template, to)
        raise EmailDeliveryError(f"Could not send {template!r} email to {to!r}.") from exc
