import datetime
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
from apps.compliance.models import AuditEvent, Holiday
from apps.compliance.services import compute_due_at, record_audit_event

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


# ── verify_audit_protections management command (M-2) ────────────────────────


def test_verify_audit_protections_skips_on_non_postgres():
    from unittest.mock import patch

    from django.core.management.base import CommandError

    from apps.compliance.management.commands.verify_audit_protections import Command

    with patch("apps.compliance.management.commands.verify_audit_protections.connection") as conn:
        conn.vendor = "sqlite"
        cmd = Command()
        try:
            cmd.handle()
        except CommandError:
            pytest.fail("must not raise when skipping a non-Postgres backend")
    conn.cursor.assert_not_called()


@pytest.mark.django_db(transaction=True)
def test_verify_audit_protections_detects_missing_trigger():
    if connection.vendor != "postgresql":
        pytest.skip("trigger presence is only meaningful on PostgreSQL")

    from django.core.management.base import CommandError

    with connection.cursor() as cursor:
        cursor.execute("DROP TRIGGER audit_event_no_update_delete ON compliance_audit_event")
    try:
        with pytest.raises(CommandError, match="Layer 2 missing"):
            call_command("verify_audit_protections")
    finally:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                CREATE TRIGGER audit_event_no_update_delete
                BEFORE UPDATE OR DELETE ON compliance_audit_event
                FOR EACH ROW EXECUTE FUNCTION compliance_audit_event_immutable();
                """
            )


@pytest.mark.django_db
def test_verify_audit_protections_detects_unrestricted_role():
    """
    The default test/dev DB connection owns the table (or is a superuser) and
    therefore always has UPDATE/DELETE, exactly the misconfiguration this
    command exists to catch — restricted_role.sql was never applied.
    """
    if connection.vendor != "postgresql":
        pytest.skip("role privileges are only meaningful on PostgreSQL")

    from django.core.management.base import CommandError

    with pytest.raises(CommandError, match="Layer 3 missing"):
        call_command("verify_audit_protections")


def test_verify_audit_protections_passes_when_both_layers_enforced():
    """Unit-tests the command's own decision logic against a mocked cursor,
    independent of whether a real restricted role exists in this environment."""
    from unittest.mock import MagicMock, patch

    from apps.compliance.management.commands.verify_audit_protections import Command

    fake_cursor = MagicMock()
    fake_cursor.__enter__.return_value = fake_cursor
    fake_cursor.__exit__.return_value = False
    # trigger exists, UPDATE=False, DELETE=False
    fake_cursor.fetchone.side_effect = [(1,), (False,), (False,)]

    with patch("apps.compliance.management.commands.verify_audit_protections.connection") as conn:
        conn.vendor = "postgresql"
        conn.cursor.return_value = fake_cursor
        Command().handle()  # must not raise


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


# ── compute_due_at ────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_compute_due_at_skips_weekends():
    # Monday 2026-01-05 + 5 working days = Monday 2026-01-12
    # (Tue 6, Wed 7, Thu 8, Fri 9, Mon 12 — skips Sat 10, Sun 11)
    started_at = datetime.datetime(2026, 1, 5, 9, 0, 0, tzinfo=datetime.UTC)
    result = compute_due_at(started_at, 5)
    assert result.date() == datetime.date(2026, 1, 12)
    assert result.hour == 9  # preserves time component


@pytest.mark.django_db
def test_compute_due_at_skips_holidays():
    # Monday 2026-01-05 + 3 working days, with Tuesday-Thursday in Holiday table
    started_at = datetime.datetime(2026, 1, 5, 10, 0, 0, tzinfo=datetime.UTC)
    Holiday.objects.create(date=datetime.date(2026, 1, 6), description="Holiday Tue")
    Holiday.objects.create(date=datetime.date(2026, 1, 7), description="Holiday Wed")
    Holiday.objects.create(date=datetime.date(2026, 1, 8), description="Holiday Thu")
    # Working days: Fri 9 (1), Mon 12 (2), Tue 13 (3)
    result = compute_due_at(started_at, 3)
    assert result.date() == datetime.date(2026, 1, 13)


@pytest.mark.django_db
def test_compute_due_at_skips_both_weekends_and_holidays():
    # Mon 2026-01-05 + 1 working day, with Tue in Holiday table → due Wed 7
    started_at = datetime.datetime(2026, 1, 5, 8, 0, 0, tzinfo=datetime.UTC)
    Holiday.objects.create(date=datetime.date(2026, 1, 6), description="Holiday Tue")
    result = compute_due_at(started_at, 1)
    assert result.date() == datetime.date(2026, 1, 7)


@pytest.mark.django_db
def test_compute_due_at_preserves_tzinfo():
    from django.utils import timezone as dj_timezone

    started_at = dj_timezone.now()
    result = compute_due_at(started_at, 1)
    assert result.tzinfo is not None
    assert result > started_at


# ── seed_reference_data ───────────────────────────────────────────────────────


@pytest.mark.django_db
def test_seed_reference_data_is_idempotent():
    from apps.applications.models import Milestone, Stream, StreamMilestone

    call_command("seed_reference_data", verbosity=0)
    stream_count_1 = Stream.objects.count()
    milestone_count_1 = Milestone.objects.count()
    sm_count_1 = StreamMilestone.objects.count()

    # Re-running must not create duplicates
    call_command("seed_reference_data", verbosity=0)
    assert Stream.objects.count() == stream_count_1
    assert Milestone.objects.count() == milestone_count_1
    assert StreamMilestone.objects.count() == sm_count_1


@pytest.mark.django_db
def test_seed_reference_data_oc_milestone_never_auto_deemed():
    """
    AC-18 guard #1: every StreamMilestone row linking to the OC milestone
    must have deemed_clearance_eligible=False after seeding.
    """
    from apps.applications.models import StreamMilestone

    call_command("seed_reference_data", verbosity=0)
    oc_rows = StreamMilestone.objects.filter(milestone__code="OC")
    assert oc_rows.exists(), "OC milestone not linked to any stream after seed"
    bad = oc_rows.filter(deemed_clearance_eligible=True)
    assert not bad.exists(), (
        f"AC-18 violated: {bad.count()} OC StreamMilestone row(s) "
        f"have deemed_clearance_eligible=True after seed"
    )


@pytest.mark.django_db
def test_seed_reference_data_seeds_all_streams():
    from apps.applications.models import Stream

    call_command("seed_reference_data", verbosity=0)
    expected = {
        "new_building",
        "addition",
        "layout",
        "reerection",
        "temporary",
        "special",
        "regularise",
    }
    actual = set(Stream.objects.values_list("code", flat=True))
    assert expected <= actual


@pytest.mark.django_db
def test_seed_reference_data_seeds_2nd_4th_saturdays():
    call_command("seed_reference_data", verbosity=0)
    # There should be 24 2nd/4th Saturday rows for 2026 (2 per month x 12 months)
    sat_count = Holiday.objects.filter(description__contains="Saturday").count()
    assert sat_count == 24, f"Expected 24 2nd/4th Saturday rows, got {sat_count}"


@pytest.mark.django_db
def test_seed_reference_data_stream_sequences_are_contiguous():
    from apps.applications.models import Stream, StreamMilestone

    call_command("seed_reference_data", verbosity=0)

    for stream in Stream.objects.all():
        sequences = list(
            StreamMilestone.objects.filter(stream=stream)
            .values_list("sequence", flat=True)
            .order_by("sequence")
        )
        assert sequences, f"Stream {stream.code!r} has no StreamMilestone rows"
        expected = list(range(1, len(sequences) + 1))
        assert sequences == expected, (
            f"Stream {stream.code!r} has non-contiguous sequences: "
            f"{sequences} (expected {expected})"
        )


# ── Phase 8 — Complaint & ConditionalClearance ────────────────────────────────


@pytest.mark.django_db
def test_raise_applicant_complaint_requires_raised_by():
    """AC-28 direction 1: applicant-origin complaint with raised_by=None must be rejected."""
    from apps.common.exceptions import DomainError
    from apps.compliance.services import raise_applicant_complaint

    user = _make_user("officer_p8a")
    stream = _make_stream("P8A")
    app = Application.objects.create(
        stream=stream,
        submitted_by=user,
        status=Application.STATUS_UNDER_SCRUTINY,
        application_number="MBPASPA20269001",
    )
    with pytest.raises(DomainError, match="AC-28"):
        raise_applicant_complaint(
            application=app,
            raised_by=None,
            subject="Test complaint",
            body="Test body",
        )


@pytest.mark.django_db
def test_raise_system_complaint_rejects_raised_by_set():
    """AC-28 direction 2: system-origin with a non-null actor must be rejected.

    Tests the helper directly — catches the future violation where a caller passes
    a default actor without checking origin first.
    """
    from apps.common.exceptions import DomainError
    from apps.compliance.models import Complaint
    from apps.compliance.services import _validate_complaint_raised_by

    user = _make_user("officer_p8b")
    with pytest.raises(DomainError, match="AC-28"):
        _validate_complaint_raised_by(Complaint.ORIGIN_SYSTEM, user)


@pytest.mark.django_db
def test_complaint_create_view_rejects_non_owner():
    """POST /api/compliance/complaints/ must not let an unrelated authenticated
    user file an applicant-origin complaint against someone else's application
    by guessing its id."""
    from rest_framework.test import APIClient

    from apps.compliance.models import Complaint

    owner = _make_user("complaint_owner")
    stranger = _make_user("complaint_stranger")
    stream = _make_stream("CXOWN")
    app = Application.objects.create(
        stream=stream,
        submitted_by=owner,
        status=Application.STATUS_UNDER_SCRUTINY,
        application_number="MBPASPA20269101",
    )

    client = APIClient()
    client.force_authenticate(user=stranger)
    response = client.post(
        "/api/compliance/complaints/",
        {"application_id": app.pk, "subject": "Not mine", "body": "Trying anyway"},
        format="json",
    )

    assert response.status_code == 404
    assert Complaint.objects.filter(application=app).count() == 0


@pytest.mark.django_db
def test_complaint_create_view_allows_owner():
    """The account of record can raise a complaint against their own application."""
    from rest_framework.test import APIClient

    from apps.compliance.models import Complaint

    owner = _make_user("complaint_owner2")
    stream = _make_stream("CXOWN2")
    app = Application.objects.create(
        stream=stream,
        submitted_by=owner,
        status=Application.STATUS_UNDER_SCRUTINY,
        application_number="MBPASPA20269102",
    )

    client = APIClient()
    client.force_authenticate(user=owner)
    response = client.post(
        "/api/compliance/complaints/",
        {"application_id": app.pk, "subject": "Document wrongly rejected", "body": "Details."},
        format="json",
    )

    assert response.status_code == 201
    assert Complaint.objects.filter(application=app, raised_by=owner).count() == 1


@pytest.mark.django_db
def test_resolve_complaint_sets_status_and_notes():
    """resolve_complaint transitions status to RESOLVED and persists resolution_notes."""
    from apps.compliance.models import Complaint
    from apps.compliance.services import raise_applicant_complaint, resolve_complaint

    user = _make_user("officer_p8c")
    stream = _make_stream("P8C")
    app = Application.objects.create(
        stream=stream,
        submitted_by=user,
        status=Application.STATUS_UNDER_SCRUTINY,
        application_number="MBPASPA20269002",
    )
    complaint = raise_applicant_complaint(
        application=app,
        raised_by=user,
        subject="Slow review",
        body="Application not reviewed in 30 days.",
    )
    assert complaint.status == Complaint.STATUS_OPEN

    updated = resolve_complaint(
        complaint=complaint,
        resolved_by=user,
        resolution_notes="Reviewed and resolved by officer.",
    )
    assert updated.status == Complaint.STATUS_RESOLVED
    assert updated.resolution_notes == "Reviewed and resolved by officer."
    assert updated.resolved_at is not None

    updated.refresh_from_db()
    assert updated.status == Complaint.STATUS_RESOLVED


@pytest.mark.django_db(transaction=True)
def test_run_sla_sweep_creates_complaint_on_deemed_clearance():
    """The SLA sweep must create a system-raised Complaint when it deems a milestone cleared."""
    from apps.compliance.models import Complaint

    user = _make_user("officer_p8d")
    stream = _make_stream("P8D")
    milestone = _make_milestone("S2P8D")

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
        application_number="MBPASPA20269003",
    )
    now = timezone.now()
    MilestoneInstance.objects.create(
        application=app,
        stream_milestone=sm,
        status=MilestoneInstance.STATUS_IN_PROGRESS,
        started_at=now - timedelta(days=30),
        due_at=now - timedelta(days=5),
    )

    call_command("run_sla_sweep", verbosity=0)

    complaints = Complaint.objects.filter(application=app, origin=Complaint.ORIGIN_SYSTEM)
    assert complaints.count() == 1
    complaint = complaints.first()
    assert "auto-cleared" in complaint.subject
    assert complaint.raised_by is None


@pytest.mark.django_db(transaction=True)
def test_run_sla_sweep_complaint_rolls_back_with_deemed_clearance():
    """If raise_system_complaint fails inside the atomic block, the entire transaction
    for that instance rolls back — no MilestoneInstance update, no AuditEvent."""
    from unittest.mock import patch

    user = _make_user("officer_p8e")
    stream = _make_stream("P8E")
    milestone = _make_milestone("S2P8E")

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
        application_number="MBPASPA20269004",
    )
    now = timezone.now()
    instance = MilestoneInstance.objects.create(
        application=app,
        stream_milestone=sm,
        status=MilestoneInstance.STATUS_IN_PROGRESS,
        started_at=now - timedelta(days=30),
        due_at=now - timedelta(days=5),
    )

    with patch(
        "apps.compliance.management.commands.run_sla_sweep.raise_system_complaint",
        side_effect=Exception("forced failure to test rollback"),
    ):
        call_command("run_sla_sweep", verbosity=0)

    instance.refresh_from_db()
    assert instance.status == MilestoneInstance.STATUS_IN_PROGRESS, (
        "MilestoneInstance was deemed-cleared despite raise_system_complaint failing — "
        "transaction rollback did not work"
    )
    assert not instance.is_deemed
    assert instance.completed_at is None
    assert not AuditEvent.objects.filter(
        target_type="MilestoneInstance", target_id=instance.pk
    ).exists()


@pytest.mark.django_db
def test_clearance_type_choices_cover_prd_authorities():
    """TYPE_CHOICES must cover all five PRD §2.3/§6.6 clearance authorities."""
    from apps.compliance.models import ConditionalClearance

    choice_values = {value for value, _ in ConditionalClearance.TYPE_CHOICES}
    expected = {
        ConditionalClearance.TYPE_RAILWAY,
        ConditionalClearance.TYPE_CRZ,
        ConditionalClearance.TYPE_HERITAGE_MHCC,
        ConditionalClearance.TYPE_AVIATION_AAI,
        ConditionalClearance.TYPE_POLLUTION_MPCB,
    }
    assert expected == choice_values, (
        f"TYPE_CHOICES mismatch. Missing: {expected - choice_values}; "
        f"Extra: {choice_values - expected}"
    )


@pytest.mark.django_db
def test_fulfill_clearance_records_doc_evidence():
    """fulfill_clearance attaches the evidence document and marks the clearance fulfilled."""
    from apps.compliance.models import ConditionalClearance
    from apps.compliance.services import create_conditional_clearance, fulfill_clearance
    from apps.documents.models import DocumentUpload

    user = _make_user("officer_p8f")
    stream = _make_stream("P8F")
    app = Application.objects.create(
        stream=stream,
        submitted_by=user,
        status=Application.STATUS_UNDER_SCRUTINY,
        application_number="MBPASPA20269005",
    )

    clearance = create_conditional_clearance(
        application=app,
        milestone_instance=None,
        clearance_type=ConditionalClearance.TYPE_RAILWAY,
        description="Railway NOC required for plot adjacent to track.",
        trigger_metadata={"agency": "Central Railway"},
        created_by=user,
    )
    assert not clearance.is_fulfilled
    assert clearance.clearance_doc is None

    doc = DocumentUpload.objects.create(
        application=app,
        uploaded_by=user,
        r2_object_key="clearances/railway_noc.pdf",
        original_filename="railway_noc.pdf",
        content_type="application/pdf",
        size_bytes=12345,
    )

    updated = fulfill_clearance(
        clearance=clearance,
        clearance_doc=doc,
        fulfilled_by=user,
    )
    assert updated.is_fulfilled
    assert updated.clearance_doc_id == doc.pk
    assert updated.fulfilled_by_id == user.pk
    assert updated.fulfilled_at is not None

    updated.refresh_from_db()
    assert updated.is_fulfilled
    assert updated.clearance_doc_id == doc.pk


# ── ErasureRequest / DPDP erasure (AC-32) ─────────────────────────────────────


def _make_applicant_with_profile(username="erasure_subject"):
    from apps.identity.models import ApplicantProfile

    user = User.objects.create_user(
        username=username, password="testpass123", email=f"{username}@example.com"
    )
    ApplicantProfile.objects.create(
        user=user,
        full_name="Real Name",
        pan_number="ABCDE1234F",
        aadhaar_hash="a" * 64,
        aadhaar_last4="1234",
        address="221B Baker Street",
    )
    return user


@pytest.mark.django_db
def test_create_erasure_request_sets_due_window_and_audits():
    from apps.compliance.models import ErasureRequest
    from apps.compliance.services import create_erasure_request

    subject = _make_applicant_with_profile("erase_due")
    req = create_erasure_request(subject=subject, requested_by=subject, reason="please erase")

    assert req.status == ErasureRequest.STATUS_PENDING
    delta = req.due_at - req.requested_at
    assert abs(delta.days - ErasureRequest.RESPONSE_WINDOW_DAYS) <= 1
    assert AuditEvent.objects.filter(
        verb="erasure.requested", target_type="ErasureRequest", target_id=req.pk
    ).exists()


@pytest.mark.django_db
def test_process_erasure_request_anonymises_subject():
    from apps.compliance.models import ErasureRequest
    from apps.compliance.services import create_erasure_request, process_erasure_request
    from apps.identity.models import ApplicantProfile

    subject = _make_applicant_with_profile("erase_ok")
    admin = User.objects.create_user(username="erase_admin", password="x", is_staff=True)

    # A terminal application does not block erasure.
    stream = _make_stream("erase_stream_done")
    Application.objects.create(
        stream=stream,
        submitted_by=subject,
        status=Application.STATUS_APPROVED,
        application_number="MBPASPA20269001",
    )

    req = create_erasure_request(subject=subject, requested_by=subject)
    updated = process_erasure_request(
        erasure_request=req, processed_by=admin, approve=True, resolution_notes="done"
    )

    assert updated.status == ErasureRequest.STATUS_COMPLETED
    assert updated.processed_by_id == admin.pk

    profile = ApplicantProfile.objects.get(user=subject)
    assert profile.full_name == "[ERASED]"
    assert profile.pan_number == ""
    assert profile.aadhaar_hash == ""
    assert profile.aadhaar_last4 == ""
    assert profile.address == ""

    subject.refresh_from_db()
    assert subject.is_active is False
    assert subject.email == f"erased.user.{subject.pk}@erased.invalid"
    assert subject.username == f"erased_user_{subject.pk}"
    assert not subject.has_usable_password()

    assert AuditEvent.objects.filter(verb="erasure.completed", target_id=req.pk).exists()


@pytest.mark.django_db
def test_process_erasure_request_blocked_by_active_application():
    from apps.common.exceptions import DomainError
    from apps.compliance.services import create_erasure_request, process_erasure_request
    from apps.identity.models import ApplicantProfile

    subject = _make_applicant_with_profile("erase_active")
    admin = User.objects.create_user(username="erase_admin2", password="x", is_staff=True)

    stream = _make_stream("erase_stream_active")
    Application.objects.create(
        stream=stream,
        submitted_by=subject,
        status=Application.STATUS_UNDER_SCRUTINY,
        application_number="MBPASPA20269002",
    )

    req = create_erasure_request(subject=subject, requested_by=subject)
    with pytest.raises(DomainError, match="active applications"):
        process_erasure_request(erasure_request=req, processed_by=admin, approve=True)

    # PII must remain intact when erasure is blocked.
    profile = ApplicantProfile.objects.get(user=subject)
    assert profile.full_name == "Real Name"


@pytest.mark.django_db
def test_process_erasure_request_reject_keeps_pii():
    from apps.compliance.models import ErasureRequest
    from apps.compliance.services import create_erasure_request, process_erasure_request
    from apps.identity.models import ApplicantProfile

    subject = _make_applicant_with_profile("erase_reject")
    admin = User.objects.create_user(username="erase_admin3", password="x", is_staff=True)

    req = create_erasure_request(subject=subject, requested_by=subject)
    updated = process_erasure_request(
        erasure_request=req,
        processed_by=admin,
        approve=False,
        resolution_notes="legal hold",
    )

    assert updated.status == ErasureRequest.STATUS_REJECTED
    profile = ApplicantProfile.objects.get(user=subject)
    assert profile.full_name == "Real Name"
    assert AuditEvent.objects.filter(verb="erasure.rejected", target_id=req.pk).exists()


@pytest.mark.django_db
def test_process_erasure_request_double_process_raises():
    from apps.common.exceptions import DomainError
    from apps.compliance.services import create_erasure_request, process_erasure_request

    subject = _make_applicant_with_profile("erase_double")
    admin = User.objects.create_user(username="erase_admin4", password="x", is_staff=True)

    req = create_erasure_request(subject=subject, requested_by=subject)
    process_erasure_request(erasure_request=req, processed_by=admin, approve=True)
    with pytest.raises(DomainError, match="already processed"):
        process_erasure_request(erasure_request=req, processed_by=admin, approve=True)


@pytest.mark.django_db
def test_erasure_request_overdue_property():
    from apps.compliance.services import create_erasure_request

    subject = _make_applicant_with_profile("erase_overdue")
    req = create_erasure_request(subject=subject, requested_by=subject)
    assert req.is_overdue is False

    # Force the deadline into the past.
    req.due_at = timezone.now() - timedelta(days=1)
    req.save(update_fields=["due_at"])
    assert req.is_overdue is True
