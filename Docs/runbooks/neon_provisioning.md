# Neon Database Provisioning Runbook

Execute these steps once per environment (staging / production).

## 1. Create a Neon project

1. Log into [console.neon.tech](https://console.neon.tech).
2. Click **New project** → name it `mbpa-portal-prod` (or `-staging`).
3. Choose a region close to your deployment (e.g. `aws-ap-south-1` for Mumbai).
4. Note the connection string: `postgres://neondb_owner:<password>@<host>/neondb`.

## 2. Create two roles

Neon creates `neondb_owner` (privileged) by default. Create the restricted app role:

```sql
-- Run as neondb_owner via the Neon SQL console or psql:
CREATE ROLE mbpa_app WITH LOGIN PASSWORD 'replace-with-strong-password';
```

Keep the `neondb_owner` credentials for migrations only. Wire `mbpa_app` as the
application's `DATABASE_URL`.

## 3. Run migrations (privileged role)

```bash
export DATABASE_URL="postgres://neondb_owner:<password>@<host>/neondb"
export DJANGO_SECRET_KEY="<key>"
export AADHAAR_PEPPER="<pepper>"

cd backend
python manage.py migrate
```

This applies all migrations including `0003_audit_event_immutable_trigger` which
installs the DB-level BEFORE UPDATE OR DELETE trigger on `compliance_audit_event`.

## 4. Apply the restricted-role SQL

```bash
psql "$DATABASE_URL" \
  -f ops/sql/restricted_role.sql \
  -v app_user=mbpa_app
```

Verify the output: `compliance_audit_event` should show only `INSERT` and `SELECT`
for `mbpa_app` — no `UPDATE` or `DELETE`.

## 5. Seed reference data

```bash
# Create a superuser first (needed for ConfigParameter seed):
python manage.py createsuperuser

# Seed streams, milestones, StreamMilestones, ConfigParameter placeholders, holidays:
python manage.py seed_reference_data
```

Review the WARNING about placeholder ConfigParameter values and replace them with
confirmed UPDR-2026 figures before going live (see Part 18 of the build plan).

## 6. Wire environment variables

Switch the application's `DATABASE_URL` to `mbpa_app`:

```
DATABASE_URL=postgres://mbpa_app:<password>@<host>/neondb
```

All other env vars remain unchanged. The application never needs `neondb_owner`.

## 7. Create officer accounts

```bash
python manage.py create_officer
```

Run once per officer. No credentials are committed to source code.

## 8. Smoke-test the deployment

```bash
python manage.py check --deploy
curl -f https://<your-domain>/healthz/
```
