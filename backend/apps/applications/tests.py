from concurrent.futures import ThreadPoolExecutor, as_completed

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
