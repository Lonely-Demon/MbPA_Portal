"""
Migration: install the BEFORE UPDATE OR DELETE trigger on compliance_audit_event.

This is Layer 2 of the AuditEvent append-only guarantee (Layer 1 is the Python
model override; Layer 3 is the restricted DB role documented in the deployment
runbook below).

Layer 3 — Restricted DB role (cannot be done inside a migration; requires a
superuser connection during provisioning):

    -- Run once as a Postgres superuser during environment setup:
    CREATE ROLE mbpa_app LOGIN PASSWORD '...';
    GRANT SELECT, INSERT ON compliance_audit_event TO mbpa_app;
    GRANT ALL PRIVILEGES ON ALL OTHER TABLES IN SCHEMA public TO mbpa_app;
    -- Do NOT grant UPDATE or DELETE on compliance_audit_event to mbpa_app.

The application DATABASE_URL must reference mbpa_app, not a superuser role.
The migration connection (for CI / manage.py migrate) may use a superuser role
that bypasses the role restriction, which is acceptable because the trigger
(Layer 2) still fires regardless of which role runs the SQL.
"""

from django.db import migrations

CREATE_IMMUTABILITY_TRIGGER = """
CREATE OR REPLACE FUNCTION compliance_audit_event_immutable()
RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION
        'audit_event rows are immutable: % on compliance_audit_event is forbidden',
        TG_OP;
END;
$$;

CREATE TRIGGER audit_event_no_update_delete
BEFORE UPDATE OR DELETE ON compliance_audit_event
FOR EACH ROW EXECUTE FUNCTION compliance_audit_event_immutable();
"""

DROP_IMMUTABILITY_TRIGGER = """
DROP TRIGGER IF EXISTS audit_event_no_update_delete ON compliance_audit_event;
DROP FUNCTION IF EXISTS compliance_audit_event_immutable();
"""


def create_trigger(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute(CREATE_IMMUTABILITY_TRIGGER)


def drop_trigger(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute(DROP_IMMUTABILITY_TRIGGER)


class Migration(migrations.Migration):
    dependencies = [
        ("compliance", "0002_initial"),
    ]

    operations = [
        migrations.RunPython(create_trigger, reverse_code=drop_trigger),
    ]
