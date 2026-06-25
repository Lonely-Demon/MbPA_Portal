# Verify PostgreSQL-Gated Tests Against Live Neon

Four test classes in the suite are marked `pytest.skip` on SQLite and only run
against a real PostgreSQL connection. This runbook proves the production-shaped
connection, not just CI's ephemeral container.

## Prerequisites

- Neon project provisioned (see `neon_provisioning.md`).
- Migrations applied with `neondb_owner`.
- `restricted_role.sql` applied.

## Run the gated tests

```bash
export DATABASE_URL="postgres://neondb_owner:<password>@<host>/neondb?sslmode=require"
export DJANGO_SECRET_KEY="<key>"
export AADHAAR_PEPPER="<pepper>"

cd backend
pytest -v \
  -k "test_audit_event_queryset_update_bypasses_model_save_but_not_trigger \
      or test_audit_event_db_trigger_blocks_raw_update \
      or test_audit_event_db_trigger_blocks_raw_delete \
      or test_generate_application_number_concurrent_no_duplicates \
      or test_concurrent_milestone_transition_serialized \
      or test_account_of_record_uniqueness_enforced"
```

## Expected outcomes

| Test | Expected result |
|------|-----------------|
| `test_audit_event_queryset_update_bypasses_model_save_but_not_trigger` | PASS — `ProgrammingError` from DB trigger |
| `test_audit_event_db_trigger_blocks_raw_update` | PASS — `ProgrammingError` from trigger |
| `test_audit_event_db_trigger_blocks_raw_delete` | PASS — `ProgrammingError` from trigger |
| `test_generate_application_number_concurrent_no_duplicates` | PASS — 30 unique gapless numbers |
| `test_concurrent_milestone_transition_serialized` | PASS — one `ok`, one `concurrent_error` |
| `test_account_of_record_uniqueness_enforced` | PASS — `IntegrityError` on second insert |

Any FAIL here indicates a problem with the DB connection, migration order, or
trigger installation — fix before accepting traffic.

## Verify the restricted role separately

Connect as `mbpa_app` and confirm the trigger still fires:

```bash
export DATABASE_URL="postgres://mbpa_app:<password>@<host>/neondb?sslmode=require"

pytest -v \
  -k "test_audit_event_db_trigger_blocks_raw_update \
      or test_audit_event_db_trigger_blocks_raw_delete"
```

Both should PASS — the trigger fires regardless of which role executes the statement.
