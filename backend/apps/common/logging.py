"""
AC-31 — sensitive-data redaction for the logging pipeline.

This is a defence-in-depth backstop. The first line of defence is discipline:
``record_audit_event`` payloads are curated, and code should never log raw
Aadhaar numbers, OTP codes, passwords, or secrets in the first place. But a
single careless ``logger.info(f"...{aadhaar}...")`` or an uncaught exception
whose traceback happens to carry one of these values would otherwise write it
straight to the log sink — and under the Aadhaar Act / DPDP that is exactly the
kind of disclosure that carries statutory liability.

``SensitiveDataFilter`` attaches to every log handler and scrubs both the
rendered message AND any exception traceback text before it reaches a handler's
formatter, so the redaction holds regardless of how a record was produced.
"""

from __future__ import annotations

import logging
import re

REDACTED = "***REDACTED***"

# Keys whose value must never be logged, in key=value / key: value form.
# Matched case-insensitively as whole words.
_SENSITIVE_KEYS = (
    "password",
    "passwd",
    "pwd",
    "secret",
    "secret_key",
    "token",
    "access_key",
    "api_key",
    "apikey",
    "authorization",
    "aadhaar",
    "aadhar",
    "aadhaar_raw",
    "pan_number",
    "otp",
    "otp_code",
    "code_hash",
    "pepper",
)

# key=value or key: value, value optionally quoted. The value run stops at a
# comma, whitespace, closing brace/bracket, or quote so we redact only the value.
_KV_RE = re.compile(
    r"(?i)\b(" + "|".join(_SENSITIVE_KEYS) + r")\b(\s*[=:]\s*)"
    r"""(?P<quote>['"]?)(?P<value>[^\s,'"}\]]+)(?P=quote)"""
)

# A bare 12-digit Aadhaar number, with optional space/hyphen group separators.
_AADHAAR_RE = re.compile(r"\b\d{4}[-\s]?\d{4}[-\s]?\d{4}\b")


def redact_sensitive(text: str) -> str:
    """Return ``text`` with sensitive key-values and bare Aadhaar numbers masked."""
    if not text:
        return text

    def _kv(match: re.Match) -> str:
        quote = match.group("quote")
        return f"{match.group(1)}{match.group(2)}{quote}{REDACTED}{quote}"

    text = _KV_RE.sub(_kv, text)
    text = _AADHAAR_RE.sub(REDACTED, text)
    return text


class SensitiveDataFilter(logging.Filter):
    """
    Logging filter that redacts sensitive data from a record's message and
    exception traceback. Returns True always (it scrubs, never drops).
    """

    def filter(self, record: logging.LogRecord) -> bool:
        # Render the message (resolving %-args) once, then scrub and store it as a
        # plain string with no args so downstream formatters can't re-introduce
        # the raw values from record.args.
        try:
            rendered = record.getMessage()
        except Exception:
            rendered = str(record.msg)
        record.msg = redact_sensitive(rendered)
        record.args = ()

        # Pre-render and scrub the traceback so the handler's formatter reuses our
        # redacted text instead of re-formatting record.exc_info. (logging.Formatter
        # only formats exc_info when exc_text is empty.)
        if record.exc_info and not record.exc_text:
            record.exc_text = logging.Formatter().formatException(record.exc_info)
        if record.exc_text:
            record.exc_text = redact_sensitive(record.exc_text)

        return True
