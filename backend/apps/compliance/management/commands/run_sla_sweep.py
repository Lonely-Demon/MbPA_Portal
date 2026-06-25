"""
OS-cron SLA sweep — invoked nightly by cron, not Celery.

Cron entry (example):
  0 1 * * 1-5  /app/venv/bin/python /app/manage.py run_sla_sweep >> /var/log/sla_sweep.log 2>&1

For each in-progress MilestoneInstance whose due_at has passed and whose
StreamMilestone is deemed_clearance_eligible, this command:
  1. Marks the instance as deemed-cleared.
  2. Writes an AuditEvent.

S7/OC is NEVER auto-cleared — two independent guards enforce this:
  Layer 1 (DB flag): stream_milestone__deemed_clearance_eligible=True in queryset.
  Layer 2 (hardcoded): OC_NEVER_DEEMED_CODES check inside the loop, which fires
    even if the flag is wrong in the database (data corruption, missed migration,
    admin edit). This is the AC-18 redundancy from the build plan.
"""
import logging

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.applications.models import MilestoneInstance
from apps.compliance.services import record_audit_event

logger = logging.getLogger("apps")

# Milestone codes that must NEVER be auto-cleared regardless of the DB flag.
# Update this set when new permanent-review milestones are added to the domain.
OC_NEVER_DEEMED_CODES: frozenset[str] = frozenset({"OC"})


class Command(BaseCommand):
    help = "Auto-clear milestone instances past their SLA due date (deemed clearance)."

    def handle(self, *args, **options):
        now = timezone.now()
        # Layer 1: filter by the DB flag.
        overdue = MilestoneInstance.objects.select_related(
            "stream_milestone__milestone", "application"
        ).filter(
            status=MilestoneInstance.STATUS_IN_PROGRESS,
            due_at__lt=now,
            stream_milestone__deemed_clearance_eligible=True,
        )

        cleared = 0
        skipped_protected = 0
        for instance in overdue:
            milestone_code = instance.stream_milestone.milestone.code

            # Layer 2: hardcoded guard independent of the DB flag.
            # If this fires, the DB flag is wrong — log loudly and skip.
            if milestone_code in OC_NEVER_DEEMED_CODES:
                logger.error(
                    "SLA sweep: milestone %s (pk=%s) has deemed_clearance_eligible=True "
                    "but its code %r is in OC_NEVER_DEEMED_CODES — flag mismatch detected. "
                    "Refusing to auto-clear. Fix the StreamMilestone row immediately.",
                    milestone_code,
                    instance.stream_milestone.pk,
                    milestone_code,
                )
                skipped_protected += 1
                continue

            try:
                with transaction.atomic():
                    instance.status = MilestoneInstance.STATUS_DEEMED
                    instance.is_deemed = True
                    instance.completed_at = now
                    instance.save(update_fields=["status", "is_deemed", "completed_at"])

                    record_audit_event(
                        verb="milestone.deemed_cleared",
                        target_type="MilestoneInstance",
                        target_id=instance.pk,
                        payload={
                            "application": instance.application.application_number,
                            "milestone": milestone_code,
                            "due_at": instance.due_at.isoformat(),
                            "cleared_at": now.isoformat(),
                        },
                    )
                cleared += 1
            except Exception as exc:
                logger.error(
                    "SLA sweep failed for MilestoneInstance %s: %s", instance.pk, exc,
                    exc_info=True,
                )

        self.stdout.write(
            self.style.SUCCESS(
                f"SLA sweep complete: {cleared} deemed-cleared, "
                f"{skipped_protected} protected milestone(s) skipped."
            )
        )
        logger.info(
            "SLA sweep complete: %d deemed-cleared, %d protected skipped.",
            cleared, skipped_protected,
        )
