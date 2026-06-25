from django.db import transaction
from django.utils import timezone

from .models import Application, ApplicationCounter


def generate_application_number(year: int | None = None, prefix: str = "MBPASPA") -> str:
    """
    Return the next gapless application number for the given calendar year.

    Uses SELECT FOR UPDATE on ApplicationCounter so concurrent submissions
    within the same year serialise here — no gaps, no duplicates.
    Must be called inside an open transaction (the caller's or an atomic block).

    Format: {prefix}{YYYY}{NNNN}  e.g. MBPASPA20260061
    """
    if year is None:
        year = timezone.now().astimezone().year

    with transaction.atomic():
        counter, _ = ApplicationCounter.objects.select_for_update().get_or_create(
            year=year,
            prefix=prefix,
            defaults={"next_value": 1},
        )
        number = f"{prefix}{year}{counter.next_value:04d}"
        counter.next_value += 1
        counter.save(update_fields=["next_value"])
    return number


def assign_application_number(application: Application) -> Application:
    """
    Assign a gapless application number to a draft application on submission.
    Idempotent: if the application already has a number, it is returned unchanged.
    """
    if application.application_number:
        return application
    year = timezone.now().astimezone().year
    application.application_number = generate_application_number(year=year)
    application.save(update_fields=["application_number"])
    return application
