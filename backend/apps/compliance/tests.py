from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import connection
from django.utils import timezone

from apps.applications.models import (
    Application,
    Milestone,
    MilestoneInstance,
    Stream,
    StreamMilestone,
)
from apps.compliance.models import AuditEvent
from apps.compliance.services import record_audit_event

User = get_user_model()


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_user(username="officer1"):
    return User.objects.create_user(username=username, password="testpass123")


def _make_stream(code="S1"):
    return Stream.objects.create(code=code, name=f"Stream {code}")


def _make_milestone(code="S1-RDO"):
    return Milestone.objects.create(code=code, name=f"Milestone {code}")


# ── AuditEvent: Layer 1 (model-level guard) ───────────────────────────────────


@pytest.mark.django_db
def test_audit_event_insert_succeeds():
    """Normal inserts must work — the guard only blocks mutations."""
    event = record_audit_event(verb="application.submitted", target_type="Application", target_id=1)
    assert event.pk is not None
    assert event.verb == "application.submitted"


@pytest.mark.django_db
def test_audit_event_model_blocks_update():
    """ORM .save() on an already-persisted AuditEvent must raise ValidationError."""
    event = record_audit_event(verb="test.event", target_type="Application", target_id=1)
    event.verb = "tampered"
    with pytest.raises(ValidationError, match="immutable"):
        event.save()


@pytest.mark.django_db
def test_audit_event_model_blocks_delete():
    """ORM .delete() on an AuditEvent must raise ValidationError."""
    event = record_audit_event(verb="test.event", target_type="Application", target_id=1)
    with pytest.raises(ValidationError, match="permanent"):
        event.delete()


@pytest.mark.django_db
def test_audit_event_queryset_update_bypasses_model_save_but_not_trigger():
    """
    QuerySet.update() bypasses model .save(), so the Python guard does NOT catch it.
    On PostgreSQL the DB trigger will reject it; on SQLite this test is skipped.
    On SQLite this is a known gap — the DB trigger is the actual enforcement.
    """
    if connection.vendor != "postgresql":
        pytest.skip("DB trigger only enforced on PostgreSQL; SQLite has no trigger support")

    event = record_audit_event(verb="qs.update.test", target_type="Application", target_id=1)

    from django.db import ProgrammingError

    with pytest.raises(ProgrammingError):
        AuditEvent.objects.filter(pk=event.pk).update(verb="tampered_via_qs")


# ── AuditEvent: Layer 2 (DB trigger) ─────────────────────────────────────────


@pytest.mark.django_db(transaction=True)
def test_audit_event_db_trigger_blocks_raw_update():
    """
    Raw SQL UPDATE on compliance_audit_event must be rejected by the
    BEFORE UPDATE OR DELETE trigger installed in migration 0003.

    transaction=True is required: the trigger raises an exception that
    aborts the current transaction; without a real transaction boundary
    the test DB state would be corrupted.
    """
    if connection.vendor != "postgresql":
        pytest.skip("DB-level trigger requires PostgreSQL")

    from django.db import ProgrammingError

    event = record_audit_event(verb="trigger.test", target_type="Application", target_id=1)

    with pytest.raises(ProgrammingError):
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE compliance_audit_event SET verb = %s WHERE id = %s",
                ["hacked", event.pk],
            )


@pytest.mark.django_db(transaction=True)
def test_audit_event_db_trigger_blocks_raw_delete():
    """
    Raw SQL DELETE on compliance_audit_event must be rejected by the DB trigger.
    """
    if connection.vendor != "postgresql":
        pytest.skip("DB-level trigger requires PostgreSQL")

    from django.db import ProgrammingError

    event = record_audit_event(verb="trigger.delete.test", target_type="Application", target_id=1)

    with pytest.raises(ProgrammingError):
        with connection.cursor() as cursor:
            cursor.execute(
                "DELETE FROM compliance_audit_event WHERE id = %s",
                [event.pk],
            )


# ── OC / S7: never auto-cleared ───────────────────────────────────────────────


@pytest.mark.django_db
def test_oc_milestone_never_auto_deemed():
    """
    An S7/OC MilestoneInstance that is past its SLA due date must NOT be
    auto-cleared by the SLA sweep. deemed_clearance_eligible=False is the
    DB-level guard; this test proves run_sla_sweep honours it.

    From the TDD: "S7/OC is NEVER auto-cleared — always requires affirmative
    Chairman action."
    """
    user = _make_user()
    stream = _make_stream("S7")
    milestone = _make_milestone("OC")

    oc_stream_milestone = StreamMilestone.objects.create(
        stream=stream,
        milestone=milestone,
        sequence=7,
        deemed_clearance_eligible=False,  # the invariant under test
    )
    app = Application.objects.create(
        stream=stream,
        submitted_by=user,
        status=Application.STATUS_UNDER_SCRUTINY,
        application_number="MBPASPA20260001",
    )
    now = timezone.now()
    instance = MilestoneInstance.objects.create(
        application=app,
        stream_milestone=oc_stream_milestone,
        status=MilestoneInstance.STATUS_IN_PROGRESS,
        started_at=now - timedelta(days=60),
        due_at=now - timedelta(days=30),  # well past SLA
    )

    call_command("run_sla_sweep", verbosity=0)

    instance.refresh_from_db()
    assert instance.status == MilestoneInstance.STATUS_IN_PROGRESS, (
        f"OC milestone was incorrectly auto-deemed by SLA sweep (status became {instance.status!r})"
    )
    assert not instance.is_deemed, "OC milestone was marked is_deemed=True by SLA sweep"
    assert instance.completed_at is None, "OC milestone got a completed_at timestamp from SLA sweep"


@pytest.mark.django_db
def test_eligible_milestone_is_auto_deemed():
    """
    Control: a non-OC overdue milestone WITH deemed_clearance_eligible=True
    IS cleared by the sweep — proving the sweep itself functions and the OC
    exception is specific, not a blanket no-op.
    """
    user = _make_user("officer2")
    stream = _make_stream("S1")
    milestone = _make_milestone("S1-RDO")

    sm = StreamMilestone.objects.create(
        stream=stream,
        milestone=milestone,
        sequence=1,
        deemed_clearance_eligible=True,
    )
    app = Application.objects.create(
        stream=stream,
        submitted_by=user,
        status=Application.STATUS_UNDER_SCRUTINY,
        application_number="MBPASPA20260002",
    )
    now = timezone.now()
    instance = MilestoneInstance.objects.create(
        application=app,
        stream_milestone=sm,
        status=MilestoneInstance.STATUS_IN_PROGRESS,
        started_at=now - timedelta(days=30),
        due_at=now - timedelta(days=5),  # overdue
    )

    call_command("run_sla_sweep", verbosity=0)

    instance.refresh_from_db()
    assert instance.status == MilestoneInstance.STATUS_DEEMED
    assert instance.is_deemed
    assert instance.completed_at is not None


@pytest.mark.django_db
def test_oc_milestone_never_auto_deemed_even_if_flag_is_wrong():
    """
    AC-18 redundancy: if deemed_clearance_eligible is accidentally set True on
    an OC StreamMilestone (data corruption, missed migration, admin error), the
    hardcoded OC_NEVER_DEEMED_CODES guard in run_sla_sweep must still refuse to
    auto-clear it.

    This is the test that the earlier version structurally could not cover —
    the previous test only proved the sweep respects a correctly-set False flag.
    This one proves the sweep refuses even when the flag says it's eligible.
    """
    user = _make_user("officer3")
    stream = _make_stream("S7B")
    milestone = _make_milestone("OC")  # code="OC" triggers the hardcoded guard

    # Deliberately corrupt: flag is True but code is "OC"
    corrupt_sm = StreamMilestone.objects.create(
        stream=stream,
        milestone=milestone,
        sequence=7,
        deemed_clearance_eligible=True,  # wrong — simulates data corruption
    )
    app = Application.objects.create(
        stream=stream,
        submitted_by=user,
        status=Application.STATUS_UNDER_SCRUTINY,
        application_number="MBPASPA20260003",
    )
    now = timezone.now()
    instance = MilestoneInstance.objects.create(
        application=app,
        stream_milestone=corrupt_sm,
        status=MilestoneInstance.STATUS_IN_PROGRESS,
        started_at=now - timedelta(days=60),
        due_at=now - timedelta(days=30),
    )

    call_command("run_sla_sweep", verbosity=0)

    instance.refresh_from_db()
    assert instance.status == MilestoneInstance.STATUS_IN_PROGRESS, (
        "Hardcoded OC guard failed: sweep auto-cleared an OC milestone "
        "even though OC_NEVER_DEEMED_CODES should have blocked it"
    )
    assert not instance.is_deemed
    assert instance.completed_at is None
