"""
Cross-cutting governance / security meta-tests.

  AC-31  sensitive-data log redaction
  AC-11  no CSRF-exempt views
  AC-12  no mass-assignment (fields = "__all__") serializers
  AC-33  critical state-changing service functions emit an audit event
"""

from __future__ import annotations

import ast
import inspect
import logging
import pathlib

import pytest

# ── AC-31: sensitive-data log redaction ───────────────────────────────────────
from apps.common.logging import REDACTED, SensitiveDataFilter, redact_sensitive


def test_redact_aadhaar_bare_number():
    assert "123412341234" not in redact_sensitive("user aadhaar 1234 1234 1234 verified")
    assert REDACTED in redact_sensitive("aadhaar 123412341234")
    assert REDACTED in redact_sensitive("id=1234-1234-1234")


def test_redact_keyed_secrets():
    for raw, secret in [
        ("password=hunter2", "hunter2"),
        ("otp: 482913", "482913"),
        ("token='abc.def.ghi'", "abc.def.ghi"),
        ("api_key=sk_live_51H", "sk_live_51H"),
        ("aadhaar_raw=987654321012", "987654321012"),
    ]:
        out = redact_sensitive(raw)
        assert secret not in out, f"{secret!r} leaked from {raw!r} -> {out!r}"
        assert REDACTED in out


def test_redact_preserves_non_sensitive_text():
    msg = "application MBPASPA20260001 moved to under_scrutiny"
    assert redact_sensitive(msg) == msg


def test_filter_scrubs_log_message():
    rec = logging.LogRecord(
        name="apps.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="login for aadhaar=%s with otp=%s",
        args=("123412341234", "482913"),
        exc_info=None,
    )
    SensitiveDataFilter().filter(rec)
    out = rec.getMessage()
    assert "123412341234" not in out
    assert "482913" not in out
    assert REDACTED in out


def test_filter_scrubs_exception_traceback():
    try:
        aadhaar = "123412341234"
        raise ValueError(f"boom while handling aadhaar={aadhaar}")
    except ValueError:
        import sys

        rec = logging.LogRecord(
            name="apps.test",
            level=logging.ERROR,
            pathname=__file__,
            lineno=1,
            msg="unhandled",
            args=(),
            exc_info=sys.exc_info(),
        )
    SensitiveDataFilter().filter(rec)
    assert rec.exc_text is not None
    assert "123412341234" not in rec.exc_text
    assert REDACTED in rec.exc_text


# ── Source-scan helpers for AC-11 / AC-12 ─────────────────────────────────────

_APPS_DIR = pathlib.Path(__file__).resolve().parent.parent  # backend/apps


def _production_py_files():
    """All .py files under apps/, excluding tests and migrations."""
    for path in _APPS_DIR.rglob("*.py"):
        parts = set(path.parts)
        if "migrations" in parts:
            continue
        if path.name.startswith("tests") or path.name == "conftest.py":
            continue
        yield path


def test_no_csrf_exempt_views():
    """AC-11: no production module may use csrf_exempt."""
    offenders = []
    for path in _production_py_files():
        text = path.read_text()
        if "csrf_exempt" in text:
            offenders.append(str(path.relative_to(_APPS_DIR)))
    assert not offenders, f"csrf_exempt found in: {offenders}"


def test_no_mass_assignment_serializers():
    """AC-12: no serializer may declare fields = "__all__"."""
    import re

    pattern = re.compile(r"""fields\s*=\s*['"]__all__['"]""")
    offenders = []
    for path in _production_py_files():
        if pattern.search(path.read_text()):
            offenders.append(str(path.relative_to(_APPS_DIR)))
    assert not offenders, f'fields = "__all__" found in: {offenders}'


# ── AC-33: critical actions are audited ───────────────────────────────────────


# Registry of state-changing service functions that MUST emit an audit event.
# Adding a new consequential service function without registering + auditing it
# is the drift this test exists to catch.
def _critical_service_functions():
    from apps.applications import services as app_svc
    from apps.certificates import services as cert_svc
    from apps.compliance import services as comp_svc
    from apps.fees import services as fee_svc

    return {
        "applications.submit_application": app_svc.submit_application,
        "applications.transition_milestone": app_svc.transition_milestone,
        "compliance.raise_applicant_complaint": comp_svc.raise_applicant_complaint,
        "compliance.raise_system_complaint": comp_svc.raise_system_complaint,
        "compliance.resolve_complaint": comp_svc.resolve_complaint,
        "compliance.create_conditional_clearance": comp_svc.create_conditional_clearance,
        "compliance.fulfill_clearance": comp_svc.fulfill_clearance,
        "compliance.create_erasure_request": comp_svc.create_erasure_request,
        "compliance.process_erasure_request": comp_svc.process_erasure_request,
        "fees.assess_fee": fee_svc.assess_fee,
        "fees.reassess_fee": fee_svc.reassess_fee,
        "fees.record_payment": fee_svc.record_payment,
        "fees.verify_payment": fee_svc.verify_payment,
        "certificates.generate_certificate": cert_svc.generate_certificate,
        "certificates.receive_signed_certificate": cert_svc.receive_signed_certificate,
        "certificates.compile_final_dossier": cert_svc.compile_final_dossier,
    }


@pytest.mark.parametrize("name", sorted(_critical_service_functions().keys()))
def test_critical_service_function_emits_audit_event(name):
    """
    AC-33: each registered critical function references record_audit_event in its
    own body (verified by AST so a comment mentioning it doesn't count).
    """
    import textwrap

    func = _critical_service_functions()[name]
    source = textwrap.dedent(inspect.getsource(func))
    tree = ast.parse(source)
    calls = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "record_audit_event" in calls, (
        f"{name} does not call record_audit_event() — every critical state change "
        f"must be audited (AC-33)."
    )
