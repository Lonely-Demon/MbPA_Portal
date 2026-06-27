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
# Matched case-insensitively as whole words (or with word-breaking non-alnum
# for hyphenated forms such as "api-key").
_SENSITIVE_KEYS = (
    "password",
    "passwd",
    "pwd",
    "secret",
    "secret_key",
    "token",
    "token_ref",
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

# Hyphenated equivalents that can't use \b on both sides because of the dash.
_SENSITIVE_KEYS_HYPHEN = (
    "api-key",
    "api-secret",
    "secret-key",
    "access-key",
    "auth-token",
)

# Match key=value or key: value where the key may itself be quoted (JSON-style
# "password": "hunter2"), so the separator group accepts an optional closing
# quote before the colon/equals. Value is optionally quoted; the value capture
# group stops at whitespace, comma, closing brace/bracket, or quote.
_KV_RE = re.compile(
    r"(?i)\b(" + "|".join(re.escape(k) for k in _SENSITIVE_KEYS) + r")\b"
    r"""(?P<sep>["']?\s*[=:]\s*)"""
    r"""(?P<quote>['"]?)(?P<value>[^\s,'"}\]]+)(?P=quote)"""
)

# Hyphenated keys — same separator/value pattern but no \b at the start of the
# key (the leading char is a letter, \b still fires there; we skip the trailing
# \b because the hyphen is non-word and breaks the boundary after the first word).
_KV_HYPHEN_RE = re.compile(
    r"(?i)(" + "|".join(re.escape(k) for k in _SENSITIVE_KEYS_HYPHEN) + r")"
    r"""(?P<sep2>["']?\s*[=:]\s*)"""
    r"""(?P<quote2>['"]?)(?P<value2>[^\s,'"}\]]+)(?P=quote2)"""
)

# HTTP Authorization header: "Authorization: Bearer <token>" or "Token <token>"
# The scheme word is kept; the credential after it is redacted.
_AUTH_HEADER_RE = re.compile(r"(?i)\bAuthorization\s*[:=]\s*(\S+)\s+\S+")

# A bare 12-digit Aadhaar number, with optional space / hyphen / dot separators.
_AADHAAR_RE = re.compile(r"\b\d{4}[-\s.]?\d{4}[-\s.]?\d{4}\b")


def redact_sensitive(text: str) -> str:
    """Return ``text`` with sensitive key-values and bare Aadhaar numbers masked."""
    if not text:
        return text

    def _kv(match: re.Match) -> str:
        quote = match.group("quote")
        return f"{match.group(1)}{match.group('sep')}{quote}{REDACTED}{quote}"

    def _kv_hyphen(match: re.Match) -> str:
        quote = match.group("quote2")
        return f"{match.group(1)}{match.group('sep2')}{quote}{REDACTED}{quote}"

    def _auth(match: re.Match) -> str:
        # Keep "Authorization: Bearer" but replace the credential token.
        full = match.group(0)
        scheme = match.group(1)
        # Reconstruct with the scheme visible and token redacted.
        prefix = full[: full.index(scheme) + len(scheme)]
        return f"{prefix} {REDACTED}"

    # ORDER MATTERS: redact grouped Aadhaar numbers FIRST. _KV_RE's value
    # capture stops at the first whitespace, so on "aadhaar=1234 5678 9012" it
    # would consume only "1234" and leave " 5678 9012" as plain text that the
    # (already-run) bare-Aadhaar pass can no longer recognise.
    text = _AADHAAR_RE.sub(REDACTED, text)
    text = _AUTH_HEADER_RE.sub(_auth, text)
    text = _KV_RE.sub(_kv, text)
    text = _KV_HYPHEN_RE.sub(_kv_hyphen, text)
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
