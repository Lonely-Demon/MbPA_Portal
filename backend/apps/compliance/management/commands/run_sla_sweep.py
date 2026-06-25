"""
OS-cron SLA sweep — invoked nightly by cron, not Celery.

Cron entry (example):
  0 1 * * 1-5  /app/venv/bin/python /app/manage.py run_sla_sweep >> /var/log/sla_sweep.log 2>&1

For each in-progress MilestoneInstance whose due_at has passed and whose
StreamMilestone is deemed_clearance_eligible, this command:
  1. Marks the instance as deemed-cleared.
  2. Advances the application to the next milestone.
  3. Writes an AuditEvent.

S7/OC is NEVER auto-cleared — the StreamMilestone.deemed_clearance_eligible=False
guard ensures this even if cron fires erroneously.
"""
import logging

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.applications.models import MilestoneInstance
from apps.compliance.services import record_audit_event

logger = logging.getLogger("apps")


class Command(BaseCommand):
    help = "Auto-clear milestone instances past their SLA due date (deemed clearance)."

    def handle(self, *args, **options):
        now = timezone.now()
        overdue = MilestoneInstance.objects.select_related(
            "stream_milestone", "application"
        ).filter(
            status=MilestoneInstance.STATUS_IN_PROGRESS,
            due_at__lt=now,
            stream_milestone__deemed_clearance_eligible=True,
        )

        cleared = 0
        for instance in overdue:
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
                            "milestone": instance.stream_milestone.milestone.code,
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
            self.style.SUCCESS(f"SLA sweep complete: {cleared} instance(s) deemed-cleared.")
        )
        logger.info("SLA sweep complete: %d instance(s) deemed-cleared.", cleared)
