from concurrent.futures import ThreadPoolExecutor, as_completed

import pytest
from django.db import connection

from apps.applications.services import generate_application_number


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
        f"{sorted(set(n for n in numbers if numbers.count(n) > 1))}"
    )
    # Assert strict gaplessness: suffixes must form a contiguous range 1..count
    prefix = f"MBPASPA{year}"
    suffixes = sorted(int(n[len(prefix):]) for n in numbers)
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
