# Enterprise Build-Plan Reference: Django 5.2 + DRF Government Permission Portal (Certification-Ready)

## TL;DR
- The fixed stack is sound and current as of June 2026: target **Django 5.2 LTS** (security support to **April 30, 2028** — "at least three years after its release" per the official 5.2 release notes; released 2 April 2025; supports **Python 3.10, 3.11, 3.12, 3.13, and 3.14 as of 5.2.8** and **PostgreSQL 14+**), **DRF 3.16**, **drf-spectacular 0.29.x**, **django-storages 1.14.6 + boto3** for R2, **pyHanko 0.35.x** for DSC signing, **workalendar 17.0.0** for SLA math — all pinned, with deny-by-default security and DB-enforced audit/immutability.
- The two highest-risk compliance areas are (1) **Aadhaar handling** — store only an HMAC-SHA256 hash with a secrets-managed pepper plus last-4 digits, never the raw number (Aadhaar Act ss.29/37/38 carry personal criminal liability), and (2) **CERT-In/GIGW 3.0 posture** — WCAG 2.1 AA frontend, `manage.py check --deploy` clean, and a CERT-In-empanelled VAPT "safe-to-host" certificate.
- One version trap to design around now: **Content-Security-Policy is built into Django core only from 6.0 (released 3 Dec 2025); on 5.2 you must use django-csp.** Plan CSP via django-csp with a clean migration path to native `SECURE_CSP` at the eventual 6.x upgrade.

## Key Findings

1. **Versions are stable and certification-friendly.** Django 5.2 is the current LTS. It requires PostgreSQL 14+ and Python 3.10+. Neon (PG 15/16/17) and the rest of the stack are compatible.
2. **Architecture: HackSoft services/selectors + a `config` project package + domain apps + a separately built React SPA served as static files behind a same-domain reverse proxy** is the correct enterprise layout and the one that makes the session+CSRF model trivial.
3. **Atomic application numbers must use a dedicated Postgres SEQUENCE or `select_for_update` on a counter row — never `COUNT(*)+1`.** For gapless, year-resettable human-readable IDs, a counter-row-per-year with `select_for_update` (or `django-sequences`) is the safe pattern.
4. **DB-level append-only audit** is achieved with a restricted Postgres role (`REVOKE UPDATE, DELETE`) plus a `BEFORE UPDATE OR DELETE` trigger that `RAISE EXCEPTION`, a monotonic sequence for ordering, and plain `target_type`/`target_id` columns (not Django GenericForeignKey) to avoid cascade deletes.
5. **Money and fees must be snapshotted** as `Decimal` (never float) with a stored config-version reference, and rows frozen after the state transition via overridden `save()` and/or a DB trigger.

## Details

### 1. Project structure & settings split
Adopt the **HackSoft Django Styleguide** layering (github.com/HackSoftware/Django-Styleguide), the most widely cited enterprise convention:
- **`services.py`** — functions that *write* (business logic spanning models, wrapped in `transaction.atomic()`).
- **`selectors.py`** — functions that *read* (complex queries, visibility/permission-aware fetching).
- Keep business logic **out of** APIs/views, serializers/forms, and (mostly) the model `save()`. Use the model `clean()` only for simple multi-field validation; push complex validation to services; prefer DB `constraints` where possible.
- Class-based services are acceptable as a namespace (the styleguide's `FileStandardUploadService` is the canonical example).

**Project package:** put Django config in a `config/` package (HackSoft uses `config/django/` or `config/settings/`) separate from domain apps. Split settings into `base.py`, `local.py`, `staging.py`, `production.py` using **django-environ** (`env = environ.Env()`, read from `.env`). HackSoft convention: prefix Django-specific env vars with `DJANGO_` (`DJANGO_SETTINGS_MODULE`, `DJANGO_DEBUG`, `DJANGO_ALLOWED_HOSTS`); leave third-party (AWS, etc.) unprefixed but be consistent. Integration-specific settings go in their own module gated by a `USE_X` boolean defaulting to `False`.

**Directory convention** (recommended):
```
backend/
  config/            # settings/, urls.py, wsgi.py, asgi.py
    settings/base.py local.py staging.py production.py
  apps/              # domain apps: applications/, fees/, audit/, identity/, ...
    <app>/models.py services.py selectors.py apis.py serializers.py
          permissions.py tests/ migrations/ factories.py
  manage.py
frontend/            # Vite + TS + Tailwind + shadcn/ui (built to /dist)
```
The React SPA is built with Vite to static assets; the reverse proxy (nginx) serves `/` (the SPA) and proxies `/api/` to Gunicorn — **same origin**, which is what makes session-cookie + CSRF clean (no CORS credentials gymnastics).

### 2. Django 5.x specifics affecting model/service design
- **Django 5.2 (LTS, current):** per the official release notes, "Django 5.2 supports Python 3.10, 3.11, 3.12, 3.13, and 3.14 (as of 5.2.8)" and "supports PostgreSQL 14 and higher." Adds **`CompositePrimaryKey`** (`pk = models.CompositePrimaryKey("a_id","b_id")`) — but it **does not work as a FK target, in generic relations, or in the Django admin**, and you cannot migrate an existing table to/from a composite PK (use `--fake`/`SeparateDatabaseAndState`). For a permission portal, prefer surrogate PKs and **enforce uniqueness with `UniqueConstraint`** to keep admin/FK/DRF compatibility. Use `_meta.pk_fields` (not `field.primary_key`) if you ever introspect.
- **`GeneratedField`** (5.0+): DB-computed stored/virtual columns; 5.2 adds validation of constraints that reference a GeneratedField. Good for derived columns that must never drift.
- **`db_default`** (5.0+): database-level default expressions (e.g. `db_default=Now()`), distinct from Python-side `default`.
- **Field `choices`** (5.0+) accept callables and can be derived from enums/mappings — use `TextChoices`/`IntegerChoices` enums for milestone/status fields.
- **Async**: ORM and views have async support, but session auth, DRF, pyHanko, and the management-command cron jobs here are synchronous; run under Gunicorn sync/gthread workers. No async needed for this design.

### 3. Session-cookie + CSRF auth for the SPA (same origin)
Because the SPA and API are same-origin behind the proxy, use Django **SessionAuthentication** with CSRF. Reference: DRF "AJAX, CSRF & CORS" (django-rest-framework.org/topics/ajax-csrf-cors/).
- DRF `SessionAuthentication` enforces CSRF for unsafe methods (POST/PUT/PATCH/DELETE). Note DRF's `APIView`/`ViewSet` are `csrf_exempt` by default and re-enable CSRF *only* via SessionAuthentication — this is the intended path here.
- Settings:
```python
SESSION_COOKIE_HTTPONLY = True      # JS cannot read session id
SESSION_COOKIE_SECURE = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SECURE = True
CSRF_COOKIE_HTTPONLY = False        # JS MUST read csrftoken to echo it
CSRF_COOKIE_SAMESITE = "Lax"
CSRF_TRUSTED_ORIGINS = ["https://portal.example.gov"]
```
- The CSRF cookie must be readable by JS (`CSRF_COOKIE_HTTPONLY=False`); the React client reads `csrftoken` and sends it in the **`X-CSRFToken`** header on unsafe requests. A small fetch wrapper should attach the header and use `credentials: "include"` (only strictly needed cross-origin, harmless same-origin). Expose a `GET /api/csrf/` view calling `django.middleware.csrf.get_token(request)` to prime the cookie on first load.
- **Pitfalls:** (a) the login endpoint is itself CSRF-relevant — protect it; (b) the CSRF token can rotate (e.g. on login) — the wrapper should refresh on a 403 and retry; (c) don't set `SameSite=None` unless truly cross-site.
- **Officer (45 min) vs applicant (6 hour) session TTL:** Django has one global `SESSION_COOKIE_AGE`. Implement role-differentiated TTL by calling **`request.session.set_expiry(seconds)`** at login based on the authenticated role (officer→2700, applicant→21600), optionally combined with `SESSION_EXPIRE_AT_BROWSER_CLOSE` for officers. A thin custom middleware can also enforce idle-timeout by stamping `last_activity` in the session and expiring officers after 45 min of inactivity. This is cleaner than two session backends.

### 4. DRF patterns (3.16)
- **Serializers:** split **read vs write** serializers (HackSoft + drf-spectacular both favor this; `COMPONENT_SPLIT_REQUEST` in spectacular models it accurately). Keep field-level/`validate_<field>` and object-level `validate()` in serializers for request-shape validation; push business rules to services.
- **Views:** for an enterprise codebase prefer **explicit `APIView`/generic views with service calls** over fat `ModelViewSet`s (HackSoft's position) — it keeps business logic traceable. ViewSets are fine for simple CRUD reference data.
- **Permissions — deny-by-default:** set the global default to authenticated:
```python
REST_FRAMEWORK = {
  "DEFAULT_AUTHENTICATION_CLASSES": ["rest_framework.authentication.SessionAuthentication"],
  "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
  "DEFAULT_THROTTLE_CLASSES": ["rest_framework.throttling.ScopedRateThrottle"],
  "DEFAULT_THROTTLE_RATES": {"login":"5/min","otp":"5/min","otp_resend":"3/min"},
  "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.LimitOffsetPagination",
  "PAGE_SIZE": 25,
  "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
}
```
Write custom **object-level permissions** (`has_object_permission`) for officer-vs-applicant access to a specific application.
- **Throttling OTP/auth:** use **`ScopedRateThrottle`** with `throttle_scope` per view (`"otp"`, `"login"`), or a custom `SimpleRateThrottle` keyed on IP+username to throttle wrong-OTP abuse specifically. DRF throttling uses the Django cache backend (use Redis/Memcached in prod). DRF docs warn throttling is not a complete security control — pair with django-axes (see §15).
- **drf-spectacular:** add `drf_spectacular` to `INSTALLED_APPS`, set the schema class above, define `SPECTACULAR_SETTINGS = {"TITLE":..., "VERSION":..., "SERVE_INCLUDE_SCHEMA": False}`, decorate non-obvious views with `@extend_schema`. Pin the version (project stays <1.0 and "every new version may break you"); for air-gapped/offline gov environments use **drf-spectacular-sidecar** to serve Swagger UI/Redoc locally rather than from a CDN. Default OAS version is 3.0.3 (3.1.0 supported via `OAS_VERSION`).

### 5. Atomic sequence generation for human-readable application numbers
Target format e.g. `MBPASPA2026061` = prefix + year + zero-padded sequence.
- **`COUNT(*)+1` is broken** under concurrency: two workers reading the same count produce duplicates; it's a race even inside a transaction unless you lock, and deleted rows make counts non-monotonic.
- **Option A — dedicated Postgres `SEQUENCE`** (`nextval()`): fast, concurrency-safe, no row locking, but **gappy** (rolled-back txns and replica promotion consume/skip values) and resetting per year requires `ALTER SEQUENCE ... RESTART`. Use if gaps are acceptable.
- **Option B — counter row + `select_for_update`** (recommended for gapless + year reset): a `Counter(year, prefix, value)` table with a **unique constraint on `(year, prefix)`**; in a `transaction.atomic()` block, `select_for_update()` the row, increment, save, format the number. Django lacks `UPDATE ... RETURNING`, so the row-model + lock approach is the idiomatic way. Year rollover = a new row per year (the unique constraint serializes the first insert). This is exactly the pattern documented by Julien Enselme for daily-reset sequences.
- **`django-sequences` (3.0)** is a vetted library implementing gapless sequences via DB transactional integrity with `get_next_value("scope")` and `reset_value`/looping — a good drop-in for Option B; in multi-DB setups you need a router so its tables live with the data.
- Bind number generation to the same `transaction.atomic()` as the application-creation write so a rollback doesn't strand a number (accepting that Option B keeps it gapless, Option A may gap).

### 6. DB-level append-only audit table on Postgres
- **Enforce INSERT-only at the DB**, two complementary mechanisms (use both for defense in depth, per PostgreSQL wiki "Audit trigger"):
  1. **Role/GRANTs:** `REVOKE ALL ON audit.logged_actions FROM PUBLIC; GRANT INSERT ON audit.logged_actions TO app_user; REVOKE UPDATE, DELETE ON audit.logged_actions FROM app_user;`
  2. **Trigger guard:** `CREATE TRIGGER protect_audit BEFORE UPDATE OR DELETE ON audit.logged_actions FOR EACH ROW EXECUTE FUNCTION audit.protect_audit_log();` where the function does `RAISE EXCEPTION 'Direct modification of audit logs is forbidden';`
- **Restricted role for the app, privileged role for migrations:** configure **two entries in `DATABASES`** (e.g. `default` using a restricted login with only INSERT/SELECT on the audit table, and a `migrations`/admin alias using the owner role). Run `migrate` against the privileged connection (`--database=migrations`) and route normal traffic to the restricted connection via a **database router**. The app role must not own the audited tables and must not be superuser (PostgreSQL wiki: in-database auditing can't be trusted against the table owner/superuser).
- **Non-cascading "generic FK":** store **plain `target_type` (text) + `target_id` (bigint/uuid)** columns — *not* Django's `GenericForeignKey`/`contenttypes` GFK — so deleting a target row never cascades into / orphans audit history. This keeps audit rows permanent and decoupled.
- **Ordering by a monotonic sequence, not wall clock:** add a `BIGINT` column defaulted from a dedicated `SEQUENCE` (or `BIGSERIAL`) and order audit events by it; wall-clock timestamps can collide or go backwards (NTP, same-transaction `current_timestamp`). Keep a timestamp column too, for human reading, but order by the sequence.
- **Atomicity:** wrap the business state change and its audit insert in a single **`transaction.atomic()`** so they commit or roll back together.

### 7. Working-day / SLA computation
- **Library: `workalendar` (17.0.0)** — has India support and the working-day primitives `add_working_days(start, n)`, `is_working_day(d)`, `get_working_days_delta(a,b)`. Per its official docs it pre-computes astronomical/variable holidays for the year range **1991 to 2051** and requires Python 3.7+. Alternatives: `python-holidays` (rich India holiday data but no add-working-days helper), `numpy.busday_count`/`busday_offset` (fast, custom holiday list, weekend mask), `python-bizdays` (financial calendars).
- **India "second Saturday" rule:** no library models the *second & fourth Saturday* bank-holiday rule out of the box. Implement a **custom Holiday reference table** (DB-driven, editable by admins) plus a small rule for 2nd/4th Saturdays, and feed it as the holiday set to `numpy.busday_offset` or a custom calendar subclass. A DB-backed holiday table is the certification-friendly choice (auditable, no code deploy to add a holiday).
- **Store `due_at` as a computed timestamp at transition time** (snapshot), not recomputed on read — so later holiday-table edits don't silently move past deadlines.
- **IST + `USE_TZ=True`:** store UTC in the DB, set `TIME_ZONE="Asia/Kolkata"` for display/business logic. **Day-boundary pitfall:** "N working days" is a *date* concept; compute deadlines in IST local dates, then materialize `due_at` as the end-of-business-day IST converted to UTC. 23:58 IST is still "today" in IST but is already *tomorrow 18:28 UTC* — so always convert to IST before taking the calendar date, or you will mis-bucket near-midnight events. Use `django.utils.timezone.localtime()`/`zoneinfo` for the conversion.

### 8. Fee snapshot immutability
- **Snapshot computed amounts**: when a fee is assessed, persist the **computed `Decimal` amounts** plus a **`fee_config_version` reference** (FK or version string) to the rate table row/version used. Later rate changes create a new config version and never touch existing assessments.
- **Decimal, never float:** use Python `decimal.Decimal` for all money; quantize with an explicit context (e.g. `amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)`). Django `DecimalField(max_digits=12, decimal_places=2)` is a sensible INR convention (supports up to ~10 crore with paise); size `max_digits` to the largest possible fee. Note Django 5.2 made `BaseDatabaseOperations.adapt_decimalfield_value()` a no-op (returns the value), so decimals round-trip cleanly.
- **Immutability after transition:** make the assessment row immutable once the application transitions (e.g. to "fee assessed"/"paid") by (a) overriding `save()` to raise if the instance already exists and is locked, and/or (b) a Postgres `BEFORE UPDATE` trigger on the fee table that rejects changes to frozen rows. Combine with the audit trigger pattern from §6.

### 9. Aadhaar hash + pepper (dedup only)
**Compliance backdrop (must drive the design):** Aadhaar Act 2016 — **s.29** restricts use/sharing of identity information; **s.37** penalizes intentional disclosure. The verbatim statutory text (UIDAI): unauthorized disclosure of identity information "shall be punishable with imprisonment for a term which may extend to three years or with a fine which may extend to ten thousand rupees or, in the case of a company, with a fine which may extend to one lakh rupees or with both." **s.38** penalizes unauthorized access (up to 10 years for CIDR tampering); **s.42** and related provisions create **personal criminal liability**. Storing raw Aadhaar numbers in registers/databases is widely held to be impermissible. UIDAI's **Offline Paperless e-KYC / Secure QR** lets you verify a UIDAI-**digitally-signed** XML/QR **offline** against UIDAI's public certificate **without an AUA/KUA licence** — this is the lawful verification path for a portal. **DPDP Act 2023 + DPDP Rules 2025** (notified in the Gazette **14 Nov 2025**, with an **18-month phased compliance** runway, i.e. full deadline ~13 May 2027) add data-fiduciary duties: itemized consent notice; **erasure/grievance requests addressed within 90 days (Rule 14)**; **48-hour pre-erasure notice**; breach notification (to the Board "without delay" and to affected Data Principals **within 72 hours**); and security safeguards. The Schedule penalties are severe — **₹250 crore for failure to implement reasonable security safeguards (s.8(5))** and **₹200 crore for breach-notification failures**.

**Secure handling for dedup only:**
- Compute **HMAC-SHA256(aadhaar, pepper)** — a keyed hash — and store **only the hash + last 4 digits** (last-4 for human disambiguation/support). Never store the 12-digit number.
- **Why not a per-row random salt:** a random per-row salt makes two records of the same Aadhaar hash to *different* values → **dedup breaks** (you can't match). Dedup requires a *deterministic* transform.
- **Why a static salt is weak:** the Aadhaar input space is only ~10¹² (and the first 11 digits + Verhoeff checksum shrink it further); a plain SHA-256 (even with a known/static salt) is brute-forceable — an attacker can hash all 10¹² candidates and reverse the hash.
- **Why a secret pepper (HMAC key) is the mitigation:** the pepper is a high-entropy secret **not stored in the database**; without it, the offline brute-force is infeasible. It must live in **secrets management** (env/KMS/secret store), rotated under a documented procedure (rotation requires re-hashing, so plan a version column).
- Keep the Aadhaar hash column out of logs, serializers, and the OpenAPI schema; restrict DB column access.

### 10. pyHanko DSC signing/verification
**Version: pyHanko 0.35.x**, Python 3.10+. The CLI is now a separate `pyhanko-cli` package; the core is library-only. Install `pip install 'pyHanko[pkcs11,image-support,opentype,qr]'`. `ValidationContext` comes from the **separate `pyhanko_certvalidator`** package (add to deps). Supports PAdES B-B/B-T/B-LT/B-LTA and RFC-3161 timestamps.

**(a/b) Generate + sign a PDF certificate** (`pyhanko.sign.signers`):
```python
from pyhanko.sign import signers
from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter

cms_signer = signers.SimpleSigner.load(
    "key.pem", "cert.pem", ca_chain_files=("chain.pem",), key_passphrase=b"...")
with open("unsigned.pdf","rb") as doc:
    w = IncrementalPdfFileWriter(doc)
    signed = signers.sign_pdf(
        w, signers.PdfSignatureMetadata(field_name="Signature1"),
        signer=cms_signer)
```
For **Class-3 DSC USB tokens** use PKCS#11:
```python
from pyhanko.sign.pkcs11 import PKCS11Signer, open_pkcs11_session, TokenCriteria
session = open_pkcs11_session("/path/vendor_pkcs11.so", user_pin="****",
            token_criteria=TokenCriteria(label="MyToken"))
signer = PKCS11Signer(session, cert_label="signer-cert")
```
(`token_label=` is deprecated since 0.14.0 in favour of `TokenCriteria`.)

**(c) "Verify signature on receipt" flow** (`pyhanko.sign.validation`):
```python
from pyhanko.keys import load_cert_from_pemder
from pyhanko_certvalidator import ValidationContext
from pyhanko.pdf_utils.reader import PdfFileReader
from pyhanko.sign.validation import validate_pdf_signature

vc = ValidationContext(trust_roots=[load_cert_from_pemder("ca_root.pem")])
with open("incoming_signed.pdf","rb") as doc:
    sig = PdfFileReader(doc).embedded_signatures[0]
    status = validate_pdf_signature(sig, vc)
    ok = status.bottom_line             # yes/no
    print(status.pretty_print_details())
```
Useful status attrs: `bottom_line`, `modification_level`, `docmdp_ok`, `coverage`. For long-term verifiability use `validate_pdf_ltv_signature(..., RevocationInfoValidationType.PADES_LTA, validation_context_kwargs={"trust_roots":[...]})`. Note pyHanko by default requires the **non-repudiation** key-usage bit; relax via `KeyUsageConstraints` if a CA's certs differ. Trust roots = the **CCA-licensed CA** chains (eMudhra, (n)Code, Capricorn, etc.).

**India context:** signing uses **Class-3 DSC** tokens issued by **CCA-licensed CAs**; local/desktop signing is the established precedent for **GST, MCA (RoC filings) and Income-Tax** e-filing. **Aadhaar eSign** (OTP/biometric-triggered signing by an ESP/CA) is the alternative when physical tokens aren't practical, producing a comparable PKCS#7 signature you can verify the same way.

**Docs:** docs.pyhanko.eu/en/latest/lib-guide/signing.html, .../lib-guide/validation.html, .../api-docs/pyhanko.sign.signers.html, .../api-docs/pyhanko.sign.validation.html.

### 11. Cloudflare R2 + Django
- **Use django-storages 1.14.6 + boto3** with the S3 backend pointed at R2's S3-compatible endpoint. Django 4.2+/5.x uses the **`STORAGES`** setting:
```python
STORAGES = {
  "default": {"BACKEND":"storages.backends.s3.S3Storage",
    "OPTIONS": {
      "bucket_name": env("R2_BUCKET"),
      "endpoint_url": f"https://{ACCOUNT_ID}.r2.cloudflarestorage.com",
      "region_name": "auto",          # REQUIRED or boto3 errors
      "signature_version": "s3v4",
      "access_key": env("R2_ACCESS_KEY_ID"),
      "secret_key": env("R2_SECRET_ACCESS_KEY"),
      "default_acl": None,            # R2 buckets are private only
      "querystring_auth": True,       # presign downloads
    }},
  "staticfiles": {"BACKEND":"django.contrib.staticfiles.storage.StaticFilesStorage"},
}
```
- **R2 buckets are private** — every object access is via a **time-limited presigned GET URL** (`generate_presigned_url("get_object", Params={...}, ExpiresIn=...)`). Treat presigned URLs as bearer tokens; use short expiries for sensitive documents. Presigned URLs work on the S3 endpoint, **not** custom domains.
- **Never store the file in the DB** — store only the **object key** (a `CharField`/`FileField` name); generate presigned URLs on demand in a selector/service. Keep static assets off R2 (private-only) or behind a separate public bucket/custom domain.
- Docs: django-storages.readthedocs.io (Amazon S3 + Cloudflare R2 pages), developers.cloudflare.com/r2/api/s3/presigned-urls/.

### 12. Resend + Django
- **Two integration options:** (a) the **SMTP backend** — official Resend guide sets `EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend"`, `RESEND_SMTP_HOST="smtp.resend.com"`, `RESEND_SMTP_PORT=587`, `RESEND_SMTP_USERNAME="resend"`, password = API key; or (b) a **custom email backend** wrapping Resend's REST API/SDK (lets `send_mail`/`EmailMultiAlternatives` work unchanged). The SMTP backend is the lowest-friction, certification-friendly choice (standard Django mail path, easy to swap).
- **Domain verification:** add **SPF, DKIM, and DMARC** DNS records for the sending domain (required for deliverability/anti-spoofing — important for a `.gov` sender).
- **Templating:** render Django templates (HTML + text alternative) and send via `EmailMultiAlternatives`. Keep transactional templates (OTP, status change, decision) versioned in the repo.
- **Free tier / daily cap:** per Resend's docs (resend.com/docs — account quotas and limits), the **free tier is 100 emails/day and 3,000 emails/month**; the **Pro plan ($20/mo, 50,000 emails) removes the daily cap**. For a government portal with bursty OTP/notification volume the 100/day free cap is a hard blocker — move to a paid tier before go-live and **monitor the daily cap** so OTP emails never silently fail; queue/retry on cap-exceeded and alert ops.

### 13. Testing strategy (Django/DRF built-in + factory_boy; NOT pytest)
- Use **`django.test.TestCase`** and **`rest_framework.test.APITestCase`** with **factory_boy** factories per entity (`applications/factories.py`, etc.). HackSoft's repo demonstrates fakes+factories with the built-in runner.
- **Unit tests for the service/selector layer:** fee calculation (Decimal edge cases, rounding), SLA sweep (working-day math), milestone-transition validation — call services directly, hit the DB, mock anything external (Resend, R2).
- **Integration tests for the officer approve/reject workflow** through the API with `APITestCase`/`APIClient`, asserting status transitions, permissions (officer vs applicant), and audit-row creation.
- **Time-dependent logic** (SLA sweep, due-date): use **freezegun** (`@freeze_time`) or Django's own utilities to pin "now"; assert IST day-boundary behavior explicitly.
- **Concurrency / race conditions** (application-number sequence): use **`TransactionTestCase`** (not `TestCase`) because `TestCase` wraps each test in a transaction that **breaks `select_for_update`/`transaction.atomic` semantics and real commit behavior**; `TransactionTestCase` truncates tables between tests and lets you exercise real locking (threads/multiple connections).
- **Coverage:** measure with **coverage.py** (`coverage run manage.py test && coverage report --fail-under=NN`); gate in CI.

### 14. CI/CD with GitHub Actions (Django + React monorepo)
Pipeline stages (all on `ubuntu-latest`, mindful of the **2,000 free Linux minutes/month** — split into parallel jobs but cache aggressively with `actions/setup-python`/`setup-node` caching and `actions/cache` for pip/npm):
- **Lint/format (Python):** **ruff** (lint) + **ruff format** (or black) — fast, single tool.
- **Type-check:** **mypy** + **django-stubs 6.x** (use the `[compatible-mypy]` extra, which pins a compatible mypy, currently ~1.20) + **djangorestframework-stubs 3.16.x**; configure the plugin in `pyproject.toml` (`[tool.mypy] plugins=["mypy_django_plugin.main","mypy_drf_plugin.main"]`, `[tool.django-stubs] django_settings_module=...`).
- **Migrations check:** `python manage.py makemigrations --check --dry-run` (fail if models drift from migrations).
- **Tests + coverage gate** against a **Postgres service container** (`services: postgres:16`) so `select_for_update`/triggers behave like prod.
- **Security scanning:** **pip-audit** (Python deps), **npm audit** (frontend), **Bandit** (Python SAST), **gitleaks**/**trufflehog** (secret scanning), **Dependabot** (dependency PRs). These map directly to CERT-In/GIGW security expectations.
- **Frontend:** `npm ci && npm run build` (Vite) — type-check with `tsc`, lint with eslint.
- **Deploy:** build artifacts, run `manage.py check --deploy` as a gate, then deploy.

### 15. Security hardening (CERT-In / GIGW 3.0 posture)
**Django production settings** (all in `SecurityMiddleware`; target zero warnings from `manage.py check --deploy`):
```python
SECURE_SSL_REDIRECT = True
SECURE_HSTS_SECONDS = 31536000           # 1 year (ramp up from a small value first)
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")  # behind proxy; proxy MUST strip client value
SECURE_CONTENT_TYPE_NOSNIFF = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
X_FRAME_OPTIONS = "DENY"                  # + XFrameOptionsMiddleware
ALLOWED_HOSTS = ["portal.example.gov"]    # never ["*"]
```
`check --deploy` flags include W004 (HSTS), W006 (nosniff), W008 (SSL redirect), W009 (weak SECRET_KEY), W012/W016 (cookie secure), W018 (DEBUG), W019/W020 (X-Frame/ALLOWED_HOSTS). Run it in CI. **Caveat on `SECURE_PROXY_SSL_HEADER`:** only set it if the proxy *strips* any client-supplied `X-Forwarded-Proto` and sets it itself, otherwise it is spoofable.
- **CSP — version trap:** native CSP (`django.middleware.csp.ContentSecurityPolicyMiddleware`, `SECURE_CSP`/`SECURE_CSP_REPORT_ONLY`, `from django.utils.csp import CSP`) is **new in Django 6.0 (released 3 Dec 2025)** — the 6.0 CSP reference page literally states "New in Django 6.0." **On Django 5.2 you must use the `django-csp` package** (`csp.middleware.CSPMiddleware`, `CSP_DEFAULT_SRC`, `CSP_INCLUDE_NONCE_IN`, etc.). Plan a migration to native CSP at the eventual 6.x upgrade.
- **Brute-force/login lockout:** **django-axes 8.x** (`AXES_FAILURE_LIMIT`, `AXES_COOLOFF_TIME`, `AXES_LOCKOUT_PARAMETERS`; default lockout response 429). v6+ replaced the old per-combination flags with `AXES_LOCKOUT_PARAMETERS`. Pair with DRF throttling on OTP/login.
- **Structured logging/audit:** JSON logs, plus the DB-level audit table (§6) for the legal trail.
- **OWASP:** GIGW 3.0's security chapter is authored by CERT-In and aligns with **ISO 27001, OWASP ASVS, OWASP Top 10, and CIS benchmarks**.
- **GIGW 3.0 / accessibility:** per guidelines.india.gov.in (NIC), GIGW 3.0 "ensures conformity with Level AA of WCAG 2.1" and "In all 17 new success criteria have been added," with a CERT-In-authored cybersecurity chapter (STQC SETL-1 auditors map this to ~50 WCAG 2.1 AA criteria). It also references IS 17802 and the RPwD Act 2016 (s.42). The React/shadcn frontend must meet WCAG 2.1 AA (alt text, semantic structure, keyboard navigation, contrast, reflow, captions) — test with NVDA/JAWS/VoiceOver + automated scanners.
- **CERT-In VAPT:** obtain a **"safe-to-host" certificate from a CERT-In/STQC-empanelled auditor** and target a **Certified Quality Website (CQW)** from STQC; CERT-In advisories (and the 6-hour incident-reporting directive) apply continuously.

### 16. Database migrations & data integrity
- **Zero-downtime migrations:** make schema changes **additive and backwards-compatible** (add nullable column → backfill via separate data migration → add constraint/NOT NULL in a later migration); avoid locking rewrites on large tables; separate **schema migrations from data migrations** (use `RunPython` for data).
- **Constraints at the DB, not just the app:**
  - **`CheckConstraint`** for invariants (e.g. `amount >= 0`, valid status enum).
  - **`UniqueConstraint`** (incl. functional and **conditional/partial**) for business uniqueness — and note that **non-conditional `UniqueConstraint`s integrate with `validate_unique()`** (two-stage validation), while partial (conditional) ones surface as DB IntegrityError.
  - **"Exactly one TRUE per group" pattern** (e.g. exactly one `is_account_of_record` per application): use a **partial unique index** — `UniqueConstraint(fields=["application"], condition=Q(is_account_of_record=True), name="one_account_of_record_per_application")` — which permits many FALSE rows but only one TRUE per application. This is the canonical Postgres partial-unique-index technique.
- **`db_index`:** add on FK/lookup columns used in filters; don't over-index (write cost). Use `UniqueConstraint`/`Index` in `Meta.constraints`/`Meta.indexes` rather than field-level `unique=True` for non-trivial cases.
- Keep the migration-runner on the **privileged DB role** (§6) so it can create the restricted-role grants, triggers, and audit schema.

## Recommendations
1. **Pin everything now and lock the baseline:** Django 5.2.x, DRF 3.16, drf-spectacular 0.29.x (+ sidecar), django-storages 1.14.6, boto3, pyHanko 0.35.x + pyhanko-certvalidator + python-pkcs11, workalendar 17.0.0, django-axes 8.x, django-csp, django-environ, factory_boy, coverage. Record exact versions in `requirements.txt`/lock and do a schema-diff review on every dependency bump.
2. **Stand up the security gate first:** wire `manage.py check --deploy`, ruff, mypy+stubs, Bandit, pip-audit/npm audit, gitleaks, and the Postgres-service test job into GitHub Actions before feature work — so certification posture is enforced from commit one.
3. **Implement the three "hard" integrity primitives early** (they're cross-cutting): (a) the gapless year-resetting application-number service (`select_for_update` or django-sequences), (b) the append-only audit schema with restricted role + trigger + monotonic sequence, (c) the Aadhaar HMAC+pepper dedup with the pepper in secrets management. These are the pieces auditors scrutinize and the hardest to retrofit.
4. **Treat Aadhaar minimally:** prefer **UIDAI Offline e-KYC / Secure QR** verification (offline signature check, no AUA/KUA licence); store only hash + last-4; document DPDP erasure (90-day Rule 14), 48-hour pre-erasure-notice, and 72-hour breach-notification workflows in ops runbooks.
5. **Plan the CSP path:** ship django-csp on 5.2 now; schedule native `SECURE_CSP` adoption when you move to Django 6.x.
6. **Engage a CERT-In/STQC-empanelled auditor early** for a gap assessment against GIGW 3.0's four pillars (Quality, Accessibility WCAG 2.1 AA, Security, Lifecycle) and budget for the VAPT "safe-to-host" + CQW certification cycle.

**Thresholds that change the plan:** if the SPA must be served from a *different* domain than the API, you lose the clean same-origin session model — you'd need `SESSION_COOKIE_SAMESITE="None"`, CORS with credentials, and `CSRF_TRUSTED_ORIGINS` updates (avoid if possible). If application-number gaps become acceptable, switch from the locking counter to a bare Postgres sequence for throughput. If email volume exceeds Resend's 100/day free cap (it will), move to the Pro tier or a queue with backpressure before go-live.

## Caveats
- **Secondary-sourced specifics to re-verify against primary docs before locking:** exact pyHanko 0.35.x point-release API signatures (verify on docs.pyhanko.eu for the pinned version); django-axes exact current minor version. The Django 6.0 release date (3 Dec 2025) and "CSP new in 6.0" are confirmed by official release notes; CSP is definitively **not** in 5.2.
- **CompositePrimaryKey (5.2)** is deliberately *not* recommended here due to admin/FK/DRF limitations — use surrogate PKs + UniqueConstraint.
- **In-database audit cannot protect against the table owner or a superuser** — enforce the restricted-role separation rigorously; the audit guarantee is only as strong as the role hygiene.
- **Legal interpretations of the Aadhaar Act** (especially around any storage of derived identifiers) should be confirmed with counsel; this report summarizes the technical mitigations and the statutory provisions (ss.29/37/38/42) but is not legal advice.
- **GIGW/CERT-In certification is point-in-time**; maintain continuous conformance (every release) and re-audit per CERT-In advisories.
- **DPDP timelines** reflect the Rules notified 14 Nov 2025 with an 18-month phased rollout; confirm which obligations are in force at your go-live date, as some provisions (e.g. Consent Manager registration) commence on different schedules.