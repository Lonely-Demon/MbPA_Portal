-- restricted_role.sql
-- Layer 3 of the audit-immutability primitive (see AuditEvent model docstring).
--
-- Run this AFTER `python manage.py migrate` with the privileged role.
-- Replace :app_db and :app_user with your actual Neon database and app user names.
--
-- Purpose: the application role (app_restricted) has INSERT-only on
-- compliance_audit_event so that even a compromised application process
-- cannot UPDATE or DELETE audit rows.
--
-- Usage:
--   psql "$DATABASE_URL_PRIVILEGED" -f restricted_role.sql \
--     -v app_db=mbpa_portal -v app_user=mbpa_app
--
-- Adjust :app_user to match the Neon role you created for the application.

-- ── Create the restricted application role ───────────────────────────────────

DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = :'app_user') THEN
        EXECUTE format('CREATE ROLE %I WITH LOGIN', :'app_user');
        RAISE NOTICE 'Created role %', :'app_user';
    ELSE
        RAISE NOTICE 'Role % already exists — skipping CREATE', :'app_user';
    END IF;
END
$$;

-- ── Grant usage on the schema ─────────────────────────────────────────────────

GRANT USAGE ON SCHEMA public TO :"app_user";

-- ── compliance_audit_event: INSERT only ──────────────────────────────────────
-- The application may insert new events but NEVER update or delete them.
-- The DB trigger (migration 0003) provides a second enforcement layer.

REVOKE ALL ON TABLE compliance_audit_event FROM :"app_user";
GRANT INSERT ON TABLE compliance_audit_event TO :"app_user";
-- SELECT is required for the ORM to return the created row.
GRANT SELECT ON TABLE compliance_audit_event TO :"app_user";

-- ── All other application tables: full CRUD ───────────────────────────────────

GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO :"app_user";
-- Re-apply the audit_event restriction (the GRANT above may have overridden it).
REVOKE UPDATE, DELETE ON TABLE compliance_audit_event FROM :"app_user";

-- ── Sequences ─────────────────────────────────────────────────────────────────

GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO :"app_user";

-- ── Future tables (applied at creation time) ──────────────────────────────────

ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO :"app_user";

ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO :"app_user";

-- ── Verify ────────────────────────────────────────────────────────────────────

SELECT
    table_name,
    privilege_type
FROM information_schema.role_table_grants
WHERE grantee = :'app_user'
  AND table_name IN ('compliance_audit_event')
ORDER BY table_name, privilege_type;
-- Expected output: INSERT and SELECT only (no UPDATE, no DELETE).
