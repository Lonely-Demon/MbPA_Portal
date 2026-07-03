"""
M-2: codify the manual "run restricted_role.sql" provisioning step as an
automated, repeatable check.

The audit log's append-only guarantee has three layers (see AuditEvent's
docstring and ops/sql/restricted_role.sql):
  1. Python model save()/delete() overrides (bypassable via .update()).
  2. A Postgres BEFORE UPDATE OR DELETE trigger (migration 0003).
  3. A restricted DB role with no UPDATE/DELETE grant on
     compliance_audit_event, applied by a superuser running
     ops/sql/restricted_role.sql during provisioning.

Layer 3 was previously verified only by eyeballing the SELECT at the bottom
of that SQL script, once, by hand. Nothing re-checked it afterwards — a role
grant added later, a migration run as the wrong user, or a fresh environment
where the script was simply never run would all go unnoticed. This command
re-verifies layers 2 and 3 against the live database and exits non-zero if
either is missing, so it can be run in a deploy pipeline or on a schedule
instead of trusted as a one-time manual step.

Usage:
    python manage.py verify_audit_protections
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.db import connection

TABLE = "compliance_audit_event"
TRIGGER = "audit_event_no_update_delete"


class Command(BaseCommand):
    help = "Verify the audit log's Postgres trigger and restricted-role protections are in place."

    def handle(self, *args, **options):
        if connection.vendor != "postgresql":
            self.stdout.write(
                self.style.WARNING(
                    f"Skipping: connection.vendor={connection.vendor!r}, not postgresql. "
                    "Layers 2/3 are Postgres-only; this check has nothing to verify here."
                )
            )
            return

        errors = []

        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT 1 FROM pg_trigger
                WHERE tgname = %s AND tgrelid = %s::regclass
                """,
                [TRIGGER, TABLE],
            )
            if cursor.fetchone() is None:
                errors.append(
                    f"Layer 2 missing: trigger {TRIGGER!r} not found on {TABLE}. "
                    "Has migration compliance.0003_audit_event_immutable_trigger run?"
                )

            cursor.execute(
                "SELECT has_table_privilege(current_user, %s, 'UPDATE')",
                [TABLE],
            )
            can_update = cursor.fetchone()[0]
            cursor.execute(
                "SELECT has_table_privilege(current_user, %s, 'DELETE')",
                [TABLE],
            )
            can_delete = cursor.fetchone()[0]
            if can_update or can_delete:
                cursor.execute("SELECT current_user")
                current_user = cursor.fetchone()[0]
                errors.append(
                    f"Layer 3 missing: role {current_user!r} (the app's own DB connection) "
                    f"can still UPDATE={can_update}/DELETE={can_delete} on {TABLE}. "
                    "Run ops/sql/restricted_role.sql as a superuser against this database, "
                    "and confirm DATABASE_URL points at the restricted role, not a superuser."
                )

        if errors:
            raise CommandError("\n".join(errors))

        self.stdout.write(
            self.style.SUCCESS(
                f"OK: {TRIGGER} trigger present and current role cannot UPDATE/DELETE {TABLE}."
            )
        )
