from concurrent.futures import ThreadPoolExecutor, as_completed
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.db import IntegrityError, connection

from apps.applications.models import (
    Application,
    ApplicationParty,
    Milestone,
    MilestoneInstance,
    Stream,
    StreamMilestone,
)
from apps.applications.services import (
    create_application,
    generate_application_number,
    submit_application,
)

User = get_user_model()


@pytest.mark.django_db
def test_generate_application_number_sequential():
    """Each call within a year returns the next sequential number."""
    year = 2026
    numbers = [generate_application_number(year=year) for _ in range(5)]
    assert numbers == [
        "MBPASPA20260001",
        "MBPASPA20260002",
        "MBPASPA20260003",
        "MBPASPA20260004",
        "MBPASPA20260005",
    ]


@pytest.mark.django_db
def test_generate_application_number_year_isolation():
    """Different years each start their own independent counter from 0001."""
    n2025 = generate_application_number(year=2025)
    n2026 = generate_application_number(year=2026)
    assert n2025 == "MBPASPA20250001"
    assert n2026 == "MBPASPA20260001"


@pytest.mark.django_db(transaction=True)
def test_generate_application_number_concurrent_no_duplicates():
    """
    Concurrent callers serialise on the counter row and each receive a unique
    number — no gaps, no duplicates.

    transaction=True is required: select_for_update() needs a real DB-level
    transaction, not the savepoint wrapping used in non-transactional test mode.

    SQLite uses a single-writer lock at the file level and cannot serve multiple
    concurrent connections, so this test is PostgreSQL-only.
    """
    if connection.vendor != "postgresql":
        pytest.skip("Concurrency test requires PostgreSQL; SQLite serialises at file level")

    year = 2026
    count = 30

    with ThreadPoolExecutor(max_workers=count) as pool:
        futures = [pool.submit(generate_application_number, year=year) for _ in range(count)]
        numbers = sorted(f.result() for f in as_completed(futures))

    assert len(numbers) == count, "Wrong number of results"
    assert len(set(numbers)) == count, (
        f"Duplicate application numbers under concurrency: "
        f"{sorted({n for n in numbers if numbers.count(n) > 1})}"
    )
    # Assert strict gaplessness: suffixes must form a contiguous range 1..count
    prefix = f"MBPASPA{year}"
    suffixes = sorted(int(n[len(prefix) :]) for n in numbers)
    assert suffixes == list(range(1, count + 1)), (
        f"Gaps detected in application number sequence: {suffixes}"
    )


@pytest.mark.django_db(transaction=True)
def test_generate_application_number_idempotent_across_years():
    """
    Calling for the same year a second time in a separate transaction still
    uses the counter row — counter is never reset within a year.
    """
    generate_application_number(year=2026)
    generate_application_number(year=2026)
    third = generate_application_number(year=2026)
    assert third == "MBPASPA20260003"


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_user(username="applicant1"):
    return User.objects.create_user(username=username, password="pass123")


def _make_stream(code="new_building"):
    return Stream.objects.create(code=code, name=f"Stream {code}")


def _make_milestone(code="S1", sla_days=21):
    return Milestone.objects.create(
        code=code, name=f"Milestone {code}", default_sla_working_days=sla_days
    )


def _make_stream_milestone(stream, milestone, sequence=1, deemed=True, role=""):
    return StreamMilestone.objects.create(
        stream=stream,
        milestone=milestone,
        sequence=sequence,
        deemed_clearance_eligible=deemed,
        required_officer_role=role,
    )


# ── AccountOfRecordUniquenessTests (AC-05) ───────────────────────────────────


@pytest.mark.django_db
def test_account_of_record_uniqueness_enforced():
    """
    AC-05: Only one ApplicationParty with is_account_of_record=True is allowed
    per application. A second insert must raise IntegrityError (partial unique index).

    Note: SQLite supports partial indexes since 3.8.9. If the test environment
    uses an older SQLite, this will be skipped.
    """
    import sqlite3

    if connection.vendor == "sqlite":
        sqlite_ver = tuple(int(x) for x in sqlite3.sqlite_version.split("."))
        if sqlite_ver < (3, 8, 9):
            pytest.skip("Partial unique index requires SQLite >= 3.8.9")

    user = _make_user()
    stream = _make_stream()
    app = Application.objects.create(
        stream=stream, submitted_by=user, status=Application.STATUS_DRAFT
    )
    ApplicationParty.objects.create(
        application=app,
        user=user,
        party_role=ApplicationParty.ROLE_CO_OWNER,
        is_account_of_record=True,
    )
    with pytest.raises(IntegrityError):
        ApplicationParty.objects.create(
            application=app,
            user=user,
            party_role=ApplicationParty.ROLE_ARCHITECT,
            is_account_of_record=True,
        )


@pytest.mark.django_db
def test_non_account_of_record_not_constrained():
    """Multiple non-account-of-record parties are allowed on the same application."""
    user = _make_user()
    stream = _make_stream()
    app = Application.objects.create(
        stream=stream, submitted_by=user, status=Application.STATUS_DRAFT
    )
    ApplicationParty.objects.create(
        application=app,
        user=user,
        party_role=ApplicationParty.ROLE_ARCHITECT,
        is_account_of_record=False,
    )
    ApplicationParty.objects.create(
        application=app,
        user=user,
        party_role=ApplicationParty.ROLE_CO_OWNER,
        is_account_of_record=False,
    )
    assert ApplicationParty.objects.filter(application=app).count() == 2


# ── create_application ────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_create_application_creates_draft_with_account_of_record():
    user = _make_user()
    stream = _make_stream()
    app = create_application(stream_id=stream.pk, submitted_by=user)
    assert app.status == Application.STATUS_DRAFT
    assert app.application_number == ""
    assert ApplicationParty.objects.filter(application=app, is_account_of_record=True).count() == 1


# ── submit_application ────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_submit_creates_first_milestone_instance():
    """
    submit_application transitions the application to SUBMITTED and creates a
    sequence=1 MilestoneInstance with status=IN_PROGRESS and a due_at set
    beyond started_at.
    """
    user = _make_user()
    stream = _make_stream()
    milestone = _make_milestone("S1", sla_days=21)
    _make_stream_milestone(stream, milestone, sequence=1)

    app = create_application(stream_id=stream.pk, submitted_by=user)
    submitted = submit_application(application_id=app.pk, submitted_by=user)

    assert submitted.status == Application.STATUS_SUBMITTED
    assert submitted.application_number.startswith("MBPASPA")

    instances = MilestoneInstance.objects.filter(application=submitted)
    assert instances.count() == 1
    instance = instances.first()
    assert instance.status == MilestoneInstance.STATUS_IN_PROGRESS
    assert instance.started_at is not None
    assert instance.due_at is not None
    assert instance.due_at > instance.started_at
    assert instance.stream_milestone.sequence == 1


@pytest.mark.django_db
def test_submit_application_with_no_officer_for_role_leaves_unassigned():
    """
    When no active officer exists for the required role, assigned_officer must
    be NULL — submit_application must not raise.
    """
    user = _make_user()
    stream = _make_stream()
    milestone = _make_milestone("S1", sla_days=21)
    _make_stream_milestone(stream, milestone, sequence=1, role="junior_planner")

    app = create_application(stream_id=stream.pk, submitted_by=user)
    submitted = submit_application(application_id=app.pk, submitted_by=user)

    instance = MilestoneInstance.objects.get(application=submitted)
    assert instance.assigned_officer is None


@pytest.mark.django_db
def test_submit_application_assigns_officer_when_available():
    """
    When an active officer with the required role exists, assigned_officer is set.
    """
    from apps.identity.models import OfficerProfile

    user = _make_user()
    officer_user = User.objects.create_user(
        username="officer_s1", password="pass", user_type=User.USER_TYPE_OFFICER
    )
    OfficerProfile.objects.create(user=officer_user, role="junior_planner", is_active_officer=True)

    stream = _make_stream()
    milestone = _make_milestone("S1", sla_days=21)
    _make_stream_milestone(stream, milestone, sequence=1, role="junior_planner")

    app = create_application(stream_id=stream.pk, submitted_by=user)
    submitted = submit_application(application_id=app.pk, submitted_by=user)

    instance = MilestoneInstance.objects.get(application=submitted)
    assert instance.assigned_officer == officer_user


# ── transition_milestone ──────────────────────────────────────────────────────


def _make_officer(username="officer_act", role="junior_planner"):
    from apps.identity.models import OfficerProfile

    officer_user = User.objects.create_user(
        username=username, password="pass", user_type=User.USER_TYPE_OFFICER
    )
    OfficerProfile.objects.create(user=officer_user, role=role, is_active_officer=True)
    return officer_user


@pytest.mark.django_db
def test_transition_approve_creates_next_milestone():
    """Approving milestone sequence=1 creates sequence=2 MilestoneInstance."""
    from apps.applications.services import transition_milestone

    officer = _make_officer()
    user = _make_user("app_owner")
    stream = _make_stream()
    ms1 = _make_milestone("S1", sla_days=5)
    ms2 = _make_milestone("S2", sla_days=10)
    sm1 = _make_stream_milestone(stream, ms1, sequence=1)
    _make_stream_milestone(stream, ms2, sequence=2)

    app = create_application(stream_id=stream.pk, submitted_by=user)
    submit_application(application_id=app.pk, submitted_by=user)

    instance1 = MilestoneInstance.objects.get(application=app, stream_milestone=sm1)
    instance1.assigned_officer = officer
    instance1.save(update_fields=["assigned_officer"])

    with patch("apps.documents.services.default_storage"):
        transition_milestone(
            milestone_instance_id=instance1.pk,
            action="approve",
            acting_officer=officer,
            decision_note="Looks good",
        )

    instance1.refresh_from_db()
    assert instance1.status == MilestoneInstance.STATUS_APPROVED
    assert instance1.completed_at is not None

    next_instances = MilestoneInstance.objects.filter(application=app, stream_milestone__sequence=2)
    assert next_instances.count() == 1
    next_inst = next_instances.first()
    assert next_inst.status == MilestoneInstance.STATUS_IN_PROGRESS
    assert next_inst.due_at > next_inst.started_at


@pytest.mark.django_db
def test_transition_approve_last_milestone_marks_application_approved():
    """Approving the last milestone in the stream marks the application APPROVED."""
    from apps.applications.services import transition_milestone

    officer = _make_officer("officer_last")
    user = _make_user("app_owner2")
    stream = _make_stream("last_test_stream")
    ms = _make_milestone("OC_T", sla_days=5)
    sm = _make_stream_milestone(stream, ms, sequence=1)

    app = create_application(stream_id=stream.pk, submitted_by=user)
    submit_application(application_id=app.pk, submitted_by=user)

    instance = MilestoneInstance.objects.get(application=app, stream_milestone=sm)
    instance.assigned_officer = officer
    instance.save(update_fields=["assigned_officer"])

    transition_milestone(
        milestone_instance_id=instance.pk,
        action="approve",
        acting_officer=officer,
    )

    app.refresh_from_db()
    assert app.status == Application.STATUS_APPROVED


@pytest.mark.django_db
def test_transition_reject_marks_application_rejected():
    """Rejecting a milestone marks both the milestone and application as rejected."""
    from apps.applications.services import transition_milestone

    officer = _make_officer("officer_rej")
    user = _make_user("app_owner3")
    stream = _make_stream("rej_stream")
    ms = _make_milestone("S1_R", sla_days=5)
    sm = _make_stream_milestone(stream, ms, sequence=1)

    app = create_application(stream_id=stream.pk, submitted_by=user)
    submit_application(application_id=app.pk, submitted_by=user)

    instance = MilestoneInstance.objects.get(application=app, stream_milestone=sm)
    instance.assigned_officer = officer
    instance.save(update_fields=["assigned_officer"])

    transition_milestone(
        milestone_instance_id=instance.pk,
        action="reject",
        acting_officer=officer,
        decision_note="Missing documents",
    )

    instance.refresh_from_db()
    app.refresh_from_db()
    assert instance.status == MilestoneInstance.STATUS_REJECTED
    assert app.status == Application.STATUS_REJECTED


@pytest.mark.django_db
def test_transition_return_for_correction_records_reason():
    """RETURN_FOR_CORRECTION records the reason without closing the milestone."""
    from apps.applications.services import transition_milestone

    officer = _make_officer("officer_ret")
    user = _make_user("app_owner4")
    stream = _make_stream("ret_stream")
    ms = _make_milestone("S1_C", sla_days=5)
    sm = _make_stream_milestone(stream, ms, sequence=1)

    app = create_application(stream_id=stream.pk, submitted_by=user)
    submit_application(application_id=app.pk, submitted_by=user)

    instance = MilestoneInstance.objects.get(application=app, stream_milestone=sm)
    instance.assigned_officer = officer
    instance.save(update_fields=["assigned_officer"])

    transition_milestone(
        milestone_instance_id=instance.pk,
        action="return_for_correction",
        acting_officer=officer,
        correction_reason="Plan drawings incomplete",
    )

    instance.refresh_from_db()
    assert instance.status == MilestoneInstance.STATUS_IN_PROGRESS
    assert "incomplete" in instance.officer_remarks


# ── SeparationOfDutiesTests (AC-09) ──────────────────────────────────────────


@pytest.mark.django_db
def test_separation_of_duties_blocks_party_officer():
    """
    AC-09: An officer who is listed as an ApplicationParty may not act on any
    milestone for that application.
    """
    from apps.applications.exceptions import SeparationOfDutiesError
    from apps.applications.services import transition_milestone

    officer = _make_officer("officer_party")
    user = _make_user("owner_sod")
    stream = _make_stream("sod_stream")
    ms = _make_milestone("S1_SOD", sla_days=5)
    sm = _make_stream_milestone(stream, ms, sequence=1)

    app = create_application(stream_id=stream.pk, submitted_by=user)
    submit_application(application_id=app.pk, submitted_by=user)

    # Add the officer as a party to the application
    ApplicationParty.objects.create(
        application=app,
        user=officer,
        party_role=ApplicationParty.ROLE_ARCHITECT,
        is_account_of_record=False,
    )

    instance = MilestoneInstance.objects.get(application=app, stream_milestone=sm)
    instance.assigned_officer = officer
    instance.save(update_fields=["assigned_officer"])

    with pytest.raises(SeparationOfDutiesError):
        transition_milestone(
            milestone_instance_id=instance.pk,
            action="approve",
            acting_officer=officer,
        )


# ── StrictMilestoneSequencingTests (AC-29) ───────────────────────────────────


@pytest.mark.django_db
def test_strict_milestone_sequencing_blocks_out_of_order_action():
    """
    AC-29: An officer cannot approve milestone sequence=2 before sequence=1
    is cleared (APPROVED or DEEMED).
    """
    from apps.applications.exceptions import InvalidTransitionError
    from apps.applications.services import transition_milestone

    officer = _make_officer("officer_seq")
    user = _make_user("owner_seq")
    stream = _make_stream("seq_stream")
    ms1 = _make_milestone("S1_SEQ", sla_days=5)
    ms2 = _make_milestone("S2_SEQ", sla_days=5)
    sm1 = _make_stream_milestone(stream, ms1, sequence=1)
    sm2 = _make_stream_milestone(stream, ms2, sequence=2)

    app = create_application(stream_id=stream.pk, submitted_by=user)
    submit_application(application_id=app.pk, submitted_by=user)

    # Manually create instance2 (skipping sequence=1 completion)
    instance2 = MilestoneInstance.objects.create(
        application=app,
        stream_milestone=sm2,
        assigned_officer=officer,
        status=MilestoneInstance.STATUS_IN_PROGRESS,
        started_at=None,
        due_at=None,
    )

    # sequence=1 is still IN_PROGRESS, not cleared — should raise
    instance1 = MilestoneInstance.objects.get(application=app, stream_milestone=sm1)
    assert instance1.status == MilestoneInstance.STATUS_IN_PROGRESS

    with pytest.raises(InvalidTransitionError, match="prior-sequence"):
        transition_milestone(
            milestone_instance_id=instance2.pk,
            action="approve",
            acting_officer=officer,
        )


# ── IdorOfficerQueueTests (AC-08) ─────────────────────────────────────────────


@pytest.mark.django_db
def test_officer_queue_only_shows_own_milestones():
    """
    AC-08: officer_queue returns only milestones assigned to the requesting
    officer, not those of other officers.
    """
    from apps.applications.selectors import officer_queue

    officer1 = _make_officer("officer_q1")
    officer2 = _make_officer("officer_q2")
    user = _make_user("owner_q")
    stream = _make_stream("q_stream")
    ms = _make_milestone("S1_Q", sla_days=5)
    sm = _make_stream_milestone(stream, ms, sequence=1)

    app = create_application(stream_id=stream.pk, submitted_by=user)
    submit_application(application_id=app.pk, submitted_by=user)

    instance = MilestoneInstance.objects.get(application=app, stream_milestone=sm)
    instance.assigned_officer = officer1
    instance.save(update_fields=["assigned_officer"])

    assert officer_queue(officer1).count() == 1
    assert officer_queue(officer2).count() == 0


@pytest.mark.django_db
def test_officer_queue_excludes_completed_milestones():
    """Completed (APPROVED/REJECTED/DEEMED) milestones are not in the queue."""
    from apps.applications.selectors import officer_queue
    from apps.applications.services import transition_milestone

    officer = _make_officer("officer_done")
    user = _make_user("owner_done")
    stream = _make_stream("done_stream")
    ms = _make_milestone("S1_D", sla_days=5)
    sm = _make_stream_milestone(stream, ms, sequence=1)

    app = create_application(stream_id=stream.pk, submitted_by=user)
    submit_application(application_id=app.pk, submitted_by=user)

    instance = MilestoneInstance.objects.get(application=app, stream_milestone=sm)
    instance.assigned_officer = officer
    instance.save(update_fields=["assigned_officer"])

    assert officer_queue(officer).count() == 1

    transition_milestone(
        milestone_instance_id=instance.pk,
        action="approve",
        acting_officer=officer,
    )
    # After approval, original instance is gone from queue (it's APPROVED)
    assert officer_queue(officer).count() == 0


# ── Concurrent transition (AC-02, PostgreSQL-gated) ──────────────────────────


@pytest.mark.django_db(transaction=True)
def test_concurrent_milestone_transition_serialized():
    """
    AC-02: Two concurrent attempts to transition the same MilestoneInstance
    must not both succeed. The second must raise ConcurrentModificationError.

    PostgreSQL-gated: SQLite doesn't support concurrent connections.
    """
    if connection.vendor != "postgresql":
        pytest.skip("Concurrency test requires PostgreSQL")

    from concurrent.futures import ThreadPoolExecutor

    from apps.applications.exceptions import ConcurrentModificationError
    from apps.applications.services import transition_milestone

    officer = _make_officer("officer_con")
    user = _make_user("owner_con")
    stream = _make_stream("con_stream")
    ms = _make_milestone("S1_CON", sla_days=5)
    sm = _make_stream_milestone(stream, ms, sequence=1)

    app = create_application(stream_id=stream.pk, submitted_by=user)
    submit_application(application_id=app.pk, submitted_by=user)

    instance = MilestoneInstance.objects.get(application=app, stream_milestone=sm)
    instance.assigned_officer = officer
    instance.save(update_fields=["assigned_officer"])

    results = []

    def do_transition():
        try:
            transition_milestone(
                milestone_instance_id=instance.pk,
                action="reject",
                acting_officer=officer,
                decision_note="concurrent",
            )
            results.append("ok")
        except ConcurrentModificationError:
            results.append("concurrent_error")
        except Exception as exc:
            results.append(f"other:{exc}")

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(do_transition) for _ in range(2)]
        for f in futures:
            f.result()

    assert "ok" in results, "Neither transition succeeded"
    assert "concurrent_error" in results, (
        "Both transitions succeeded — concurrent modification not detected"
    )


# ── test_sla_sweep_against_seeded_reference_data ──────────────────────────────


@pytest.mark.django_db
def test_sla_sweep_against_seeded_reference_data():
    """
    Integration test: run_sla_sweep against seeded reference data.
    - A non-OC MilestoneInstance past its due_at with deemed_clearance_eligible=True
      must be marked DEEMED by the sweep.
    - An OC MilestoneInstance past its due_at must NOT be auto-cleared (AC-18).
    """
    from datetime import timedelta

    from django.core.management import call_command
    from django.utils import timezone

    from apps.applications.models import Milestone, Stream, StreamMilestone

    # Seed reference data (streams + milestones + holidays; no ConfigParameter without superuser)
    call_command("seed_reference_data", verbosity=0)

    officer = _make_officer("officer_sweep")
    user = _make_user("owner_sweep")

    # Use the seeded new_building stream
    stream = Stream.objects.get(code="new_building")
    sm_s1 = StreamMilestone.objects.get(stream=stream, sequence=1)
    oc_milestone = Milestone.objects.get(code="OC")
    stream_oc = Stream.objects.get(code="addition")
    sm_oc = StreamMilestone.objects.get(stream=stream_oc, milestone=oc_milestone)

    now = timezone.now()

    # Application 1: non-OC milestone past SLA, deemed_clearance_eligible=True
    app1 = Application.objects.create(
        stream=stream,
        submitted_by=user,
        status=Application.STATUS_UNDER_SCRUTINY,
        application_number="MBPASPA20260901",
    )
    eligible_instance = MilestoneInstance.objects.create(
        application=app1,
        stream_milestone=sm_s1,
        assigned_officer=officer,
        status=MilestoneInstance.STATUS_IN_PROGRESS,
        started_at=now - timedelta(days=60),
        due_at=now - timedelta(days=10),
    )

    # Application 2: OC milestone past SLA — must NOT be auto-cleared
    app2 = Application.objects.create(
        stream=stream_oc,
        submitted_by=user,
        status=Application.STATUS_UNDER_SCRUTINY,
        application_number="MBPASPA20260902",
    )
    oc_instance = MilestoneInstance.objects.create(
        application=app2,
        stream_milestone=sm_oc,
        assigned_officer=officer,
        status=MilestoneInstance.STATUS_IN_PROGRESS,
        started_at=now - timedelta(days=60),
        due_at=now - timedelta(days=10),
    )

    call_command("run_sla_sweep", verbosity=0)

    eligible_instance.refresh_from_db()
    oc_instance.refresh_from_db()

    assert eligible_instance.status == MilestoneInstance.STATUS_DEEMED, (
        f"Non-OC eligible instance was not deemed by sweep (status: {eligible_instance.status!r})"
    )
    assert oc_instance.status == MilestoneInstance.STATUS_IN_PROGRESS, (
        f"OC instance was incorrectly auto-deemed (status: {oc_instance.status!r})"
    )


# ── OfficerQueueView HTTP endpoint (Phase 9) ──────────────────────────────────


@pytest.mark.django_db
def test_officer_queue_returns_only_assigned_in_progress():
    """
    GET /api/officer/queue/ returns only IN_PROGRESS milestones assigned to the
    requesting officer; milestones of another officer are not returned.
    """
    from rest_framework.test import APIClient

    officer1 = _make_officer("http_oq_officer1")
    officer2 = _make_officer("http_oq_officer2")
    user = _make_user("http_oq_owner1")
    stream = _make_stream("http_oq_stream1")
    ms1 = _make_milestone("HTOQ_S1", sla_days=5)
    ms2 = _make_milestone("HTOQ_S2", sla_days=5)
    sm1 = _make_stream_milestone(stream, ms1, sequence=1)
    sm2 = _make_stream_milestone(stream, ms2, sequence=2)

    app = create_application(stream_id=stream.pk, submitted_by=user)
    submit_application(application_id=app.pk, submitted_by=user)

    inst1 = MilestoneInstance.objects.get(application=app, stream_milestone=sm1)
    inst1.assigned_officer = officer1
    inst1.save(update_fields=["assigned_officer"])

    # Second in-progress milestone for officer1
    inst2 = MilestoneInstance.objects.create(
        application=app,
        stream_milestone=sm2,
        assigned_officer=officer1,
        status=MilestoneInstance.STATUS_IN_PROGRESS,
        started_at=inst1.started_at,
        due_at=inst1.due_at,
    )

    # Third milestone belonging to officer2
    stream2 = _make_stream("http_oq_stream2")
    ms3 = _make_milestone("HTOQ_S3", sla_days=5)
    sm3 = _make_stream_milestone(stream2, ms3, sequence=1)
    app2 = create_application(stream_id=stream2.pk, submitted_by=user)
    submit_application(application_id=app2.pk, submitted_by=user)
    inst3 = MilestoneInstance.objects.get(application=app2, stream_milestone=sm3)
    inst3.assigned_officer = officer2
    inst3.save(update_fields=["assigned_officer"])

    client = APIClient()
    client.force_authenticate(user=officer1)
    response = client.get("/api/officer/queue/")

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    ids = {item["id"] for item in data}
    assert inst1.pk in ids
    assert inst2.pk in ids
    assert inst3.pk not in ids


@pytest.mark.django_db
def test_officer_queue_includes_document_count():
    """document_count in queue response reflects non-deleted documents only."""
    from rest_framework.test import APIClient

    from apps.documents.models import DocumentUpload

    officer = _make_officer("dc_oq_officer1")
    user = _make_user("dc_oq_owner1")
    stream = _make_stream("dc_oq_stream1")
    ms = _make_milestone("DCOQ_S1", sla_days=5)
    sm = _make_stream_milestone(stream, ms, sequence=1)

    app = create_application(stream_id=stream.pk, submitted_by=user)
    submit_application(application_id=app.pk, submitted_by=user)

    instance = MilestoneInstance.objects.get(application=app, stream_milestone=sm)
    instance.assigned_officer = officer
    instance.save(update_fields=["assigned_officer"])

    # 2 active + 1 soft-deleted — only active count should appear
    for i in range(2):
        DocumentUpload.objects.create(
            application=app,
            uploaded_by=user,
            original_filename=f"doc{i}.pdf",
            r2_object_key=f"uploads/doc{i}.pdf",
            content_type="application/pdf",
            size_bytes=1024,
            is_deleted=False,
        )
    DocumentUpload.objects.create(
        application=app,
        uploaded_by=user,
        original_filename="deleted.pdf",
        r2_object_key="uploads/deleted.pdf",
        content_type="application/pdf",
        size_bytes=1024,
        is_deleted=True,
    )

    client = APIClient()
    client.force_authenticate(user=officer)
    response = client.get("/api/officer/queue/")

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["document_count"] == 2


@pytest.mark.django_db
def test_officer_queue_requires_auth():
    """Unauthenticated GET /api/officer/queue/ returns 403."""
    from rest_framework.test import APIClient

    client = APIClient()
    response = client.get("/api/officer/queue/")
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# Phase 10 — Applicant views
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_stream_list_requires_no_auth():
    """GET /api/applications/streams/ is public."""
    from rest_framework.test import APIClient

    client = APIClient()
    response = client.get("/api/applications/streams/")
    assert response.status_code == 200


@pytest.mark.django_db
def test_stream_list_returns_active_streams():
    """Only is_active=True streams appear; inactive are excluded."""
    from rest_framework.test import APIClient

    active = _make_stream("P10_ACTIVE")
    inactive = Stream.objects.create(code="P10_INACTIVE", name="Inactive", is_active=False)

    client = APIClient()
    data = client.get("/api/applications/streams/").json()
    codes = [s["code"] for s in data]
    assert active.code in codes
    assert inactive.code not in codes


@pytest.mark.django_db
def test_status_lookup_requires_no_auth():
    """GET /api/applications/status/ is public."""
    from rest_framework.test import APIClient

    user = _make_user("p10_sl_user")
    stream = _make_stream("P10_SL_STR")
    app = create_application(stream_id=stream.pk, submitted_by=user)
    submit_application(application_id=app.pk, submitted_by=user)
    app.refresh_from_db()

    client = APIClient()
    response = client.get(
        "/api/applications/status/", {"application_number": app.application_number}
    )
    assert response.status_code == 200


@pytest.mark.django_db
def test_status_lookup_returns_milestones():
    """Response includes a milestones list."""
    from rest_framework.test import APIClient

    user = _make_user("p10_slm_user")
    stream = _make_stream("P10_SLM")
    _make_stream_milestone(stream, _make_milestone("P10SLM_M1", sla_days=3), sequence=1)
    app = create_application(stream_id=stream.pk, submitted_by=user)
    submit_application(application_id=app.pk, submitted_by=user)
    app.refresh_from_db()

    client = APIClient()
    data = client.get(
        "/api/applications/status/", {"application_number": app.application_number}
    ).json()
    assert "milestones" in data
    assert len(data["milestones"]) >= 1


@pytest.mark.django_db
def test_application_list_requires_auth():
    """Unauthenticated GET /api/applications/ returns 403."""
    from rest_framework.test import APIClient

    client = APIClient()
    assert client.get("/api/applications/").status_code == 403


@pytest.mark.django_db
def test_application_create_returns_blank_number():
    """POST /api/applications/ creates a draft with blank application_number."""
    from rest_framework.test import APIClient

    user = _make_user("p10_create_user")
    stream = _make_stream("P10_CREATE")

    client = APIClient()
    client.force_authenticate(user=user)
    response = client.post(
        "/api/applications/",
        {
            "stream_id": stream.pk,
            "plpn": "PLT-001",
            "plot_area_sqm": "500.00",
            "proposed_bua_sqm": "300.00",
            "existing_bua_sqm": "0.00",
            "zonal_rrr": "45000.00",
        },
        format="json",
    )
    assert response.status_code == 201
    assert response.json()["application_number"] == ""


@pytest.mark.django_db
def test_application_submit_assigns_number():
    """POST /api/applications/<pk>/submit/ assigns a non-blank application_number."""
    from rest_framework.test import APIClient

    user = _make_user("p10_submit_user")
    stream = _make_stream("P10_SUBMIT")
    app = create_application(stream_id=stream.pk, submitted_by=user)

    client = APIClient()
    client.force_authenticate(user=user)
    response = client.post(f"/api/applications/{app.pk}/submit/")
    assert response.status_code == 200
    number = response.json()["application_number"]
    assert number != ""
    assert number.startswith("MBPASPA")
