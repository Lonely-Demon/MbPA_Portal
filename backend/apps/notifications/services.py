from __future__ import annotations

import logging

from django.core.mail import send_mail
from django.template.loader import render_to_string

logger = logging.getLogger("apps")


def send_email(to: str, template: str, context: dict) -> None:
    """
    Send a plain-text email rendered from notifications/{template}.txt.

    Swallows send errors and logs them — callers must not rely on exceptions
    from this function for control flow. The Resend 100/day production cap
    applies; see Docs/runbooks/resend_dns.md.
    """
    subject = context.get("subject", "MbPA Portal — Action Required")
    try:
        body = render_to_string(f"notifications/{template}.txt", context)
        send_mail(subject, body, None, [to], fail_silently=False)
    except Exception:
        logger.exception("Failed to send email template=%r to=%r", template, to)
