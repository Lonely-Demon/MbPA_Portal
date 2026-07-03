from apps.identity.models import User

from .models import MilestoneInstance


def officer_queue(officer: User):
    """
    AC-08: Return only the MilestoneInstances assigned to this officer that are
    currently IN_PROGRESS. Never fetch-all-then-filter — the queryset is the
    filter.
    """
    return (
        MilestoneInstance.objects.filter(
            assigned_officer=officer,
            status=MilestoneInstance.STATUS_IN_PROGRESS,
        )
        .select_related(
            "application",
            "stream_milestone__milestone",
            "stream_milestone__stream",
        )
        .order_by("due_at")
    )
