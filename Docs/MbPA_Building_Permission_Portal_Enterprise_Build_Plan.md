# MbPA Building Permission Portal
# Enterprise Engineering Build Plan

**Document type:** Engineering Build Plan (implementation-grade)
**Status:** v1.0 — ready to scaffold against
**Audience:** the engineer(s) actually writing the code (you, and whoever you onboard next)
**Upstream documents this plan implements, unchanged:** PRD v2.0, Technical Design Document v1.0, Data Requirements Document v1.0, Engineering Handoff v1.0
**Stack constraint:** the TDD's stack is treated as fixed and non-negotiable throughout — Django 5.2 LTS + DRF, React SPA (Vite/TS/Tailwind/shadcn-ui), Neon Postgres, Cloudflare R2, Resend, session-cookie+CSRF, OS cron, pyHanko, django-simple-history, GitHub Actions.
**Target standard:** every line of code shipped should already be at the bar a CERT-In/STQC/GIGW 3.0 audit expects — so that certification is a *review*, not a *rewrite*.

---

## How To Use This Document

This is not a restatement of the PRD/TDD/DRD — it assumes you've read them and answers the next question: *given those decisions, how do I actually write this, in what order, to what standard, and what will break if I'm not careful?*

Every section that introduces code or a structural decision carries a **Traces to** line pointing back at the PRD/TDD/DRD section it implements, and an **Adversarial check** where a failure mode is non-obvious. Where the upstream docs left something as an open MbPA-dependent question (UPDR-2026 values, IOD discretion, Aadhaar dedup necessity, multi-party filing, officer zone-splitting), this plan **builds the interface and stubs the value** — never guesses the value. That list is consolidated in Part 18 so nothing gets silently hardcoded by accident six months from now.

Code in this document is **real, idiomatic, meant to be copied and adapted** — not pseudocode. It is not guaranteed to run unmodified (it hasn't been executed against a live Neon instance), but it is written at production quality: typed, tested, documented, and consistent with the architectural decisions below. Treat every code block as a first draft you review, not a final draft you paste blindly.

**Document map:**

| Part | Content |
|---|---|
| 1 | Engineering principles & operating model — how decisions get made and reviewed |
| 2 | Adversarial threat & failure catalog — what breaks, system-wide, before we write a single model |
| 3 | Repository & project layout |
| 4 | Settings & configuration (full code) |
| 5 | Domain model — every Django app, every model |
| 6 | The three hard primitives — atomic numbering, append-only audit, fee snapshotting |
| 7 | Services & selectors layer — including `transition_milestone()` |
| 8 | API layer (DRF) — serializers, permissions, views, throttling |
| 9 | Authentication & session implementation |
| 10 | Frontend architecture |
| 11 | Testing strategy — concrete tests, not just a strategy statement |
| 12 | CI/CD pipeline |
| 13 | Security hardening checklist |
| 14 | Observability & operations |
| 15 | Migrations & data integrity practices |
| 16 | Phased delivery roadmap |
| 17 | Traceability matrix (PRD ↔ DRD ↔ TDD ↔ code) |
| 18 | Carried-forward open items — what must never be hardcoded |
| Appendix | Reference material index |

---

## Part 1 — Engineering Principles & Operating Model

### 1.1 Governing principles

These six rules recur throughout this plan. When a new situation isn't explicitly covered below, resolve it by these, in this order:

1. **The database enforces what code might forget.** Every invariant that *must* hold (append-only audit, exactly-one-account-of-record, non-negative amounts, valid status transitions) gets a DB-level constraint, trigger, or restricted grant — *in addition to* application-level validation, never instead of it. Application code is the first line of defense and the one a careless future PR can accidentally remove; the database is the one it can't.
2. **Explicit over magic.** This was the TDD's own stated principle (favoring Django's built-in TestCase over pytest-django's fixture injection, an explicit `transition_milestone()` over a state-machine library) and it's carried through this plan: no signals doing invisible side-effecting work, no metaclass magic, no implicit queryset mutation. A reviewer should be able to read a service function top-to-bottom and know everything it does.
3. **Snapshot, don't recompute.** Anything that was true at a legally or financially significant moment (a fee, a certificate, a milestone's SLA deadline) is captured as data at that moment and never silently recalculated from current config. This is the DRD's single most-repeated finding (§11, §15, §19) and it generalizes: **if recomputing it later could change the answer, snapshot it now.**
4. **Append-only, not "soft-delete everything."** The DRD explicitly rejected a blanket soft-delete base class (§20.2) because `Certificate`/`AuditEvent` must be *immutable*, `OtpToken`/erased-Aadhaar fields must be *hard-deletable*, and `Application` must be *soft-deleted*. Delete policy is a per-model decision, documented at the model, never inherited from a shared base by default.
5. **Deny by default.** DRF's global permission default is `IsAuthenticated`; every public endpoint (Stream & Fee Planner, status lookup, OTP request) is an explicit, reviewed exception — never a forgotten permission class.
6. **Every transition is one transaction.** A state change and the `AuditEvent` that records it commit together or not at all (DRD §20.1 — "the dual-write problem"). If you write a service function that changes state without wrapping it in `transaction.atomic()` alongside its audit call, that's a bug, not a style preference.

### 1.2 Definition of Done (per pull request)

A PR is not done — regardless of how urgent — until all of the following are true. This list is also reproduced as the GitHub PR template in Part 12.3.

- [ ] Traces to a named PRD/DRD/TDD section, or this build plan's Part 16 phase — stated in the PR description, not left implicit
- [ ] New/changed business logic lives in `services.py`/`selectors.py`, not in a view or serializer
- [ ] Every new model field that's a UPDR-2026-dependent value is sourced from `ConfigParameter`, not hardcoded — if you typed a number that came from MbPA's regulation, stop and check Part 18
- [ ] State transitions are wrapped in `transaction.atomic()` with their `AuditEvent`
- [ ] New DB constraints/triggers have a migration *and* a test that proves the DB (not just the app) rejects the bad case
- [ ] Unit tests for new service-layer logic; integration test for new API surface; both pass in CI
- [ ] `mypy` clean, `ruff` clean, `manage.py makemigrations --check --dry-run` clean
- [ ] No `print()`/`console.log` debug leftovers; structured logging used where logging is warranted
- [ ] New API surface has a `drf-spectacular` schema that renders without warnings
- [ ] No secret, credential, or Aadhaar-shaped literal in the diff (CI's gitleaks gate is the backstop, not the only check)
- [ ] If touching anything Aadhaar-, payment-, or signature-related: an explicit reviewer comment confirming the relevant Part 2 adversarial check was considered

### 1.3 Branching strategy & commit conventions

**Trunk-based development**, not GitFlow — appropriate for a small team and a system this plan's testing/CI gate is designed to keep `main` always deployable:

- `main` is always releasable. No long-lived `develop` branch.
- Feature branches: `feat/<phase>-<short-slug>` (e.g. `feat/p4-transition-milestone`), `fix/...`, `chore/...`, `security/...`.
- Branches live **days, not weeks** — if a feature is bigger than that, split it (e.g. ship `MilestoneInstance` model + migration before `transition_milestone()` logic that uses it).
- **Conventional Commits** (`feat:`, `fix:`, `refactor:`, `test:`, `docs:`, `chore:`, `security:`) — this is what drives the CHANGELOG (§1.7) and makes `git log` itself an audit trail, which matters for a government system under RTI/Public Records Act scrutiny.
- Squash-merge to `main`; the squashed commit message is the Conventional Commit summary + a link to the PRD/DRD section.

### 1.4 Code review standards

- **No self-merge**, even as a solo developer initially — open the PR, let CI run fully, re-read your own diff the next day before merging if there's no second reviewer yet. This isn't bureaucracy for its own sake: the DRD's own adversarial checks (race conditions, cascade-delete back doors) were found by a *second pass*, not a first one.
- **Required CI gates before merge** (enforced via GitHub branch protection, Part 12.2): lint, type-check, migrations-check, full test suite + coverage gate, security scan, frontend build.
- **Review checklist** (beyond the Definition of Done): does this change cross an audit/Aadhaar/fee/signature boundary? If yes, it needs a named second reviewer once the team is >1 person — flag this in `CODEOWNERS`.
- **`CODEOWNERS` file** at repo root assigning `apps/audit/`, `apps/identity/` (Aadhaar), `apps/fees/`, and `apps/certificates/` to whoever owns compliance-sensitive review, even if that's still just you wearing a second hat.

### 1.5 Architecture Decision Records (ADRs)

The TDD *is* ADR-0 — a single large decision record. Going forward, **new architectural decisions get a short ADR**, not a Slack message that evaporates:

`docs/adr/0001-record-architecture-decisions.md`, `0002-...`, etc. — one file per decision, using the standard Michael Nygard format (Context / Decision / Status / Consequences). Anything that *changes* a TDD decision (e.g. "we moved django-q2 in after all because X") gets an ADR that explicitly supersedes the relevant TDD section — never a silent drift between what the TDD says and what the code does.

### 1.6 Documentation-as-code

- Every `services.py`/`selectors.py` function gets a docstring whose first line states what it does and whose last line (or a `Traces to:` comment) cites the PRD/DRD section.
- Every Django app gets a `README.md` stating its bounded-context responsibility in one paragraph (Part 3.3 gives the starting text).
- The OpenAPI schema (drf-spectacular) **is** the API documentation — don't hand-maintain a separate API doc that will drift.

### 1.7 Versioning & release process

- **CalVer for the application** (`2026.07.1` = year.month.patch-within-month) rather than SemVer — appropriate for a government system with no external API consumers versioning against it; the date itself is meaningful for audit ("which build was live when this certificate issued").
- `CHANGELOG.md` auto-generated from Conventional Commit history per release (a simple script or `git-cliff`).
- Tag every production deploy; the tag plus the CalVer plus the git SHA goes into the `/healthz` endpoint response (Part 14.2) so "what's actually running" is never a guess during an incident.

---

## Part 2 — Adversarial Threat & Failure Catalog

This is the system-wide "how does this break" pass, done *before* the domain model so every model/service built in Parts 5–9 is built already knowing what it has to survive. Every row below is referenced by ID (`AC-xx`) from the relevant model/service section later in this document — when you see `AC-07` next to a field, this is where it's defined. Treat this table as living; add a row the moment you discover a new failure mode, don't let it live only in a PR comment.

### 2.1 Concurrency & race conditions

| ID | Scenario | Likelihood / Impact | Mitigation | Enforced where | Proven by |
|---|---|---|---|---|---|
| AC-01 | Two applicants submit at the exact same instant; `COUNT(*)+1` application-numbering produces a duplicate number | Low-frequency, **critical** impact (a duplicate legal reference number is a real-world incident) | Atomic counter row + `select_for_update()`, never `COUNT(*)` (Part 6.1) | `apps/applications/services.py::generate_application_number()` + DB unique constraint on `application_number` as a backstop | `ApplicationNumberConcurrencyTests` (Part 11.2) — `TransactionTestCase` with real threads |
| AC-02 | Two officers (or one officer double-clicking) approve the same `MilestoneInstance` concurrently — double-advance, double `AuditEvent`, certificate issued twice | Medium frequency, high impact | `transition_milestone()` takes a row lock (`select_for_update()`) on the `MilestoneInstance` before checking/changing status; the second concurrent call sees the already-`approved` state and raises a domain error instead of re-applying | `apps/milestones/services.py::transition_milestone()` | `ConcurrentApprovalTests` |
| AC-03 | The daily SLA sweep cron job fires twice (cron misconfiguration, manual re-run during an incident, overlapping deploy windows) — same application deemed-cleared twice, double `AuditEvent`, officer flagged twice for one delay | Medium frequency (operational, not adversarial), medium impact | Sweep is itself wrapped per-row in `select_for_update()` + an idempotency check (`if status != in_progress: skip`); a `SlaSweepRun` log row records start/end so a second concurrent run can detect and refuse to overlap | `apps/milestones/management/commands/run_sla_sweep.py` | `SlaSweepIdempotencyTests` |
| AC-04 | Applicant double-submits a payment-reference claim (e.g. browser back-button resubmit) — two `Payment` rows for one challan | Medium frequency, low-to-medium impact (officer confusion, not money loss — no live gateway) | `challan_reference` is indexed (not unique, per DRD §14 AC) but the service layer checks for an existing claim against the same `(application, fee_assessment, challan_reference)` tuple before creating a new row, and surfaces "already claimed, pending verification" instead of creating a duplicate | `apps/fees/services.py::record_payment()` | `DuplicatePaymentClaimTests` |
| AC-05 | Two requests race to set `is_account_of_record=True` for two different `ApplicationParty` rows on the same application | Low frequency, medium impact (ambiguous "who gets official comms") | DB-level **partial unique index** on `(application_id) WHERE is_account_of_record` (Part 15.2) — the database, not just the service layer, makes a second TRUE impossible | Migration `0xxx_one_account_of_record_per_application` | `AccountOfRecordUniquenessTests` |

### 2.2 Identity, auth & access control

| ID | Scenario | Likelihood / Impact | Mitigation | Enforced where | Proven by |
|---|---|---|---|---|---|
| AC-06 | Attacker brute-forces a 6-digit login/signup OTP (10^6 space, trivially fast without a limit) | High likelihood if unmitigated, critical impact (account takeover) | OTP `attempt_count` capped (5 attempts → token invalidated, must re-request); DRF `ScopedRateThrottle` on the verify endpoint (per-IP and per-identifier); OTP stored as `code_hash`, never plaintext | `apps/identity/models.py::OtpToken`, `apps/identity/services.py::verify_otp()`, throttle config (Part 8.5) | `OtpBruteForceTests` |
| AC-07 | Attacker brute-forces the 12-digit Aadhaar space against the dedup hash to de-anonymize a record (10^12 space — small enough to be a real threat against a *static* salt) | Low likelihood (requires DB access) but **critical** impact if it succeeds — this is the scenario the Aadhaar Act's criminal-liability provisions exist for | HMAC-SHA256 with an application-wide **secret pepper held in secrets management, never the DB** (Part 6.3/7.5); only hash + last-4 stored, full number never persisted anywhere | `apps/identity/services.py::hash_aadhaar()` | `AadhaarHashingTests` (verifies pepper is read from settings/secret store, never from a DB-stored value; verifies raw Aadhaar never appears in any model field, log line, or `AuditEvent.metadata`) |
| AC-08 | Officer A reads or acts on an application currently assigned to Officer B's queue (e.g. by guessing/incrementing an `application_number` in the URL) — classic IDOR | Medium likelihood (URLs are guessable, `application_number` is human-readable by design), high impact | Object-level permission (`IsAssignedOfficerOrReadOnlyHistory`) checks `MilestoneInstance.assigned_officer == request.user.officerprofile` for write actions; **list** endpoints are selector-filtered (never "fetch all, filter in the view") so an officer's queue query physically cannot return someone else's row | `apps/milestones/permissions.py`, `apps/milestones/selectors.py::officer_queue()` | `IdorOfficerQueueTests` |
| AC-09 | An officer who is also a registered applicant reviews (or is auto-assigned) their own application — separation-of-duties violation (DRD §3 adversarial check) | Low likelihood, high integrity impact | `transition_milestone()` explicitly checks whether `MilestoneInstance.application` has an `ApplicationParty` row matching the acting officer's `User`, and refuses the transition with a domain error if so — checked at **decision time**, not just assignment time, since assignment could predate the officer becoming a party | `apps/milestones/services.py::transition_milestone()` | `SeparationOfDutiesTests` |
| AC-10 | Applicant session (45 min) or officer session (6 hr) TTL is bypassed by a client that never lets the cookie expire (e.g. a script holding the cookie value and replaying it past expiry) | Low likelihood, medium impact | TTL is enforced **server-side** via `request.session.set_expiry()` at login — Django invalidates the session server-side at expiry regardless of what the client does; idle-timeout middleware additionally stamps and checks `last_activity` so officer sessions also time out on inactivity, not just absolute age | `apps/identity/middleware.py::IdleTimeoutMiddleware` | `SessionTtlEnforcementTests` |
| AC-11 | CSRF token theft/replay via a same-site subdomain compromise, or a missing CSRF header silently bypassed by a misconfigured exemption | Low likelihood, high impact | No view is ever `@csrf_exempt` except the documented webhook receivers (none currently planned); `CSRF_TRUSTED_ORIGINS` is an explicit allow-list, never derived from `Host` header; CI includes a static check that greps for `csrf_exempt` and fails the build if a new one appears without an explicit ADR reference in the same diff | `config/settings/production.py`, CI lint step | `CsrfExemptionAuditTests` (a meta-test that scans the codebase) |
| AC-12 | Mass assignment — a write serializer accepts a field the client shouldn't be able to set (e.g. `status=approved` sent directly in a `PATCH /applications/{id}/` body, bypassing `transition_milestone()` entirely) | Medium likelihood (an easy mistake in any DRF codebase), high impact | Write serializers are **explicit field allow-lists**, never `fields = "__all__"`; state-changing fields (`status`, `current_milestone_instance`, anything fee/certificate-related) are **never** writable through a generic serializer — they only change via a service call from a dedicated action endpoint | `apps/applications/serializers.py` (Part 8.2) | `MassAssignmentTests` |

### 2.3 Data integrity & audit

| ID | Scenario | Likelihood / Impact | Mitigation | Enforced where | Proven by |
|---|---|---|---|---|---|
| AC-13 | A future maintainer (or a bulk-fix script) runs `AuditEvent.objects.filter(...).update(...)` or a raw `DELETE FROM auditevent`, bypassing the Python-level guard entirely | Medium likelihood over a multi-decade horizon — this is exactly the "leaves a back door" risk the DRD flagged | **Two independent layers**: (1) `AuditEvent.save()` raises if the PK already exists (no Python-level update path); (2) the app's DB role has `UPDATE`/`DELETE` **revoked** at the Postgres grant level, and a `BEFORE UPDATE OR DELETE` trigger additionally raises — so even a raw-SQL bulk operation from a compromised app process fails at the database | Migration `0xxx_audit_append_only_enforcement.py` (Part 6.2) | `AuditAppendOnlyDbLevelTests` — explicitly issues a raw SQL `UPDATE`/`DELETE` against the audit table using the app's actual restricted connection and asserts it's rejected by Postgres, not just by Django |
| AC-14 | Deleting (or soft-deleting) an `Application` cascades and destroys its `AuditEvent` history via a Django `GenericForeignKey`/`GenericRelation` | Medium likelihood (this is the default behavior if you reach for `contenttypes` GFK without thinking) | `AuditEvent.target_type`/`target_id` are **plain fields**, never a Django `GenericForeignKey` — there is no reverse relation for a cascade to travel across | `apps/audit/models.py::AuditEvent` | `AuditSurvivesTargetDeletionTests` |
| AC-15 | Two `AuditEvent` rows get the same wall-clock `created_at` (sub-millisecond collision, or clock skew across app servers) and an investigator can't establish true order | Medium likelihood, medium impact (matters for RTI/legal reconstruction of "who acted first") | Ordering is by a DB-assigned monotonic `sequence` (`BIGSERIAL`/dedicated sequence), never by `created_at` | `apps/audit/models.py::AuditEvent.sequence` | `AuditOrderingIsMonotonicTests` |
| AC-16 | A `ConfigParameter` rate change (e.g. MbPA finally supplies the real UPDR-2026 scrutiny fee) silently changes the displayed/recorded amount on an already-computed `FeeAssessment` | Medium likelihood (this *will* happen at least once, when real values arrive), critical impact (a citizen could be shown a different amount than they were charged) | `FeeAssessment` snapshots computed `Decimal` amounts plus `config_version`; the row becomes immutable once `Payment.status` moves past `claimed` (Part 6.3) | `apps/fees/models.py::FeeAssessment.save()` override + DB trigger | `FeeSnapshotImmutabilityTests` |
| AC-17 | A `Holiday` row is added/removed *after* a `MilestoneInstance.due_at` was already computed, retroactively making a deadline that was met look breached (or vice versa) | Low likelihood, medium impact | `due_at` is computed and **stored** at transition time, never recomputed on read; a holiday-table change only affects future computations, and any retroactive recompute is an explicit, audited admin action — never automatic | `apps/milestones/services.py::compute_due_at()` | `DueDateIsSnapshotNotRecomputedTests` |
| AC-18 | The Occupancy Certificate milestone (S7) gets auto-advanced by the SLA sweep due to a future code change that "simplifies" the sweep loop and accidentally removes the OC exclusion | Low likelihood, but this is the **single most consequential failure mode in the entire system** — a building occupied without inspection | **Two independent guards**: (1) `StreamMilestone.deemed_clearance_eligible` defaults to and is seeded as `False` for every row where `milestone=OC`; (2) `run_sla_sweep` additionally hardcodes a check that refuses to deem-clear `milestone.code == "S7"` regardless of what the flag says — belt and suspenders, deliberately redundant | `apps/milestones/management/commands/run_sla_sweep.py` | `OccupancyCertificateNeverDeemedTests` — this test must remain in the suite forever and should be called out by name in the PR template whenever the sweep logic is touched |

### 2.4 File handling & document integrity

| ID | Scenario | Likelihood / Impact | Mitigation | Enforced where | Proven by |
|---|---|---|---|---|---|
| AC-19 | An uploaded file is actually an executable/script with a spoofed `.pdf`/`.jpg` extension and forged `Content-Type` header | Medium likelihood, high impact (stored-malware risk, or downstream PDF-parser exploit if `pyHanko`/a viewer later opens it) | Server-side validation re-derives the file type from **magic bytes** (`python-magic` or equivalent), not the client-supplied `Content-Type` or filename extension; rejects any mismatch; size-capped per `DocumentSlot` rules; never executes or `eval`s uploaded content | `apps/documents/services.py::upload_document()` | `MaliciousUploadRejectionTests` |
| AC-20 | An officer's correction-return causes the applicant to re-upload, and the new file **overwrites** the original R2 object — destroying evidence of what was originally filed | Medium likelihood if not deliberately designed against, high impact for a government record | Uploads are **versioned, never overwritten** — each correction creates a new `DocumentUpload` row + a new R2 key; the prior version is soft-deleted (hidden, not destroyed) | `apps/documents/models.py::DocumentUpload.version`, `services.py::upload_document()` | `DocumentVersioningNeverOverwritesTests` |
| AC-21 | A presigned R2 download URL is shared/leaked (forwarded email, browser history) and used by someone who shouldn't have access, after the legitimate viewing window | Medium likelihood, medium impact | Presigned URLs are generated **on demand**, per request, with a short expiry (minutes, not hours); the API never returns a long-lived or permanent URL; every presign call itself is logged as an access event (not necessarily a full `AuditEvent`, but at minimum a structured log line) | `apps/documents/services.py::get_download_url()` | `PresignedUrlExpiryTests` |
| AC-22 | Cloudflare R2 is unreachable mid-upload (network partition, R2 incident) — partial upload leaves a `DocumentUpload` row pointing at a non-existent object | Low likelihood, medium impact | The DB row is created **only after** the R2 `put_object` call succeeds (object-first, metadata-second ordering) inside the service function; a failed R2 call raises before any row is written, so there's no orphaned reference | `apps/documents/services.py::upload_document()` | `R2UploadFailureLeavesNoOrphanRowTests` (mocks a failing R2 client) |

### 2.5 External dependency failure

| ID | Scenario | Likelihood / Impact | Mitigation | Enforced where | Proven by |
|---|---|---|---|---|---|
| AC-23 | Resend's free-tier daily cap is exceeded during a burst (e.g. a mass SLA-sweep notification run) and OTP emails silently fail to send | Medium-to-high likelihood at any real scale (the Handoff explicitly flagged this), high impact (locked-out users) | Email sending goes through a thin wrapper that catches send failures, logs them as a structured warning (not silently swallowed), and — for OTP specifically — surfaces a clear "couldn't send your code, try again shortly" to the user rather than a generic 500; a dashboard/alert (Part 14) tracks daily send volume against the known cap | `apps/notifications/services.py::send_email()` | `EmailSendFailureSurfacesCleanlyTests` |
| AC-24 | Neon's idle scale-to-zero produces a 300–800ms cold start on the first request after inactivity, which a naive health check or load balancer misreads as "down" and triggers a false failover/alert | Medium likelihood (this is documented, expected Neon behavior, not a bug), low impact if anticipated | `/healthz` deliberately performs a trivial DB query and the on-call runbook (Part 14.4) documents the expected cold-start latency explicitly, so it's never mistaken for an incident | `apps/common/views.py::healthz` | Documented in runbook, not a unit test |
| AC-25 | A signed PDF an officer uploads back has a **valid-looking but actually invalid or expired** DSC signature (expired cert, wrong trust root, tampered content after signing) | Medium likelihood (DSC tokens expire annually, officers will upload stale-signed files), critical impact if accepted as final | `receive_signed_certificate()` runs full `pyHanko` validation (`validate_pdf_signature` against a `ValidationContext` built from the CCA trust roots) and **only** sets `signature_verified=True` if `status.bottom_line` is true; an unverified upload is stored but the `Certificate` stays in a `pending_signature` state, never silently treated as final | `apps/certificates/services.py::receive_signed_certificate()` | `InvalidSignatureRejectedTests`, `ExpiredCertRejectedTests` |
| AC-26 | GitHub Actions' free 2,000 minutes/month is exhausted mid-month (e.g. a flaky test causing repeated re-runs), blocking the team from merging anything until next billing cycle | Low likelihood early, rises as the test suite grows, low-to-medium impact (a delivery slowdown, not a production incident) | CI jobs are split and cached aggressively (Part 12.1) specifically to control minute consumption; a usage alert is configured once minutes approach 80% of the monthly allotment | `.github/workflows/ci.yml` | Operational, monitored manually until usage data justifies automation |

### 2.6 Business-logic edge cases

| ID | Scenario | Likelihood / Impact | Mitigation | Enforced where | Proven by |
|---|---|---|---|---|---|
| AC-27 | An Addition/Alteration application crosses the 50%-of-original-BUA threshold mid-flight and converts to the full New Building lifecycle, but the naive implementation just overwrites `Application.stream`, orphaning the `MilestoneInstance` rows that belonged to the old 5-stage sequence | Low likelihood (rare, but a real PRD-described rule), high impact (a corrupted lifecycle state) | Stream conversion is its own service (`convert_stream()`), never a bare field assignment — it audits the conversion, closes obsolete `MilestoneInstance` rows with a `superseded` status (not deletion), and opens the new sequence's rows fresh | `apps/applications/services.py::convert_stream()` | `StreamConversionPreservesHistoryTests` |
| AC-28 | A `Complaint` is system-raised (SLA breach) and something downstream assumes every complaint has a human `raised_by`, throwing a null-reference error | Medium likelihood (an easy oversight in a list/detail serializer), low impact (a 500, not data corruption) | `raised_by` nullability is paired with an enforced business rule (`origin=system_raised` ⇔ `raised_by is None`) checked in the service layer, and every serializer/view that renders a complaint explicitly handles the null case rather than assuming a user object | `apps/complaints/services.py`, `serializers.py` | `SystemRaisedComplaintRenderingTests` |
| AC-29 | A re-erection application reaches S1 before its `DEMO` (demolition & site clearance) milestone is actually cleared, because a naive "create all milestone instances up front" implementation doesn't gate sequencing | Low likelihood if `transition_milestone()` is correctly written, critical impact otherwise (construction permission implying a site that was never certified clear) | `transition_milestone()` validates that **every prior milestone in the stream's ordered sequence** is `approved`/`deemed_approved` before allowing the next one to start — this is a single generic check, not a per-stream special case, so it automatically also covers DEMO→S1 | `apps/milestones/services.py::transition_milestone()` | `StrictMilestoneSequencingTests` (parametrized across all seven streams + DEMO) |
| AC-30 | An applicant edits `proposed_bua_sqm` *after* a `FeeAssessment` already exists for the application, and the UI shows the old fee against the new BUA without anyone noticing the mismatch | Medium likelihood, medium impact (citizen-facing confusion, potential underpayment) | Editing core design metrics after a `FeeAssessment` exists is only possible by explicitly re-triggering assessment (`reassess_fee()`), which creates a **new** `FeeAssessment` row (never mutates the old one, consistent with AC-16) and the API always returns the latest active assessment, never lets a stale one render silently | `apps/fees/services.py::reassess_fee()` | `FeeReassessmentCreatesNewRowTests` |

### 2.7 Compliance & privacy

| ID | Scenario | Likelihood / Impact | Mitigation | Enforced where | Proven by |
|---|---|---|---|---|---|
| AC-31 | A developer, debugging a milestone transition, logs the full request payload (which includes Aadhaar in a nested profile-update call) to application logs or an error tracker | Medium likelihood (a very easy mistake), critical impact (Aadhaar Act exposure) | A logging filter (Part 14.1) redacts known sensitive field names (`aadhaar`, `aadhaar_hash` is fine to log, `aadhaar_raw`/`aadhaar_number` are not) at the logging-config level, not left to developer discipline alone; `AuditEvent.metadata` is schema-reviewed in CI to reject keys matching a sensitive-field denylist | `config/settings/base.py` logging filters, `apps/audit/services.py::record_event()` | `SensitiveFieldRedactionTests` |
| AC-32 | A DPDP erasure request arrives for an applicant whose `Application` is still within the Public Records Act's statutory retention period | Medium likelihood once the system has real usage, legal impact if mishandled either way | The erasure service (`apps/identity/services.py::process_erasure_request()`) nulls only the `ApplicantProfile` identity fields (Aadhaar hash/last4, eventually mobile/name per DPO guidance) and explicitly **does not** touch `Application`/`Certificate`/`AuditEvent` rows — the separation the DRD designed for (§4) is enforced in code, with a clear comment citing DPDP §12 + Public Records Act 1993 | `apps/identity/services.py::process_erasure_request()` | `ErasureDoesNotTouchStatutoryRecordsTests` |
| AC-33 | A security incident occurs and the team needs to scope a breach within the DPDP's 72-hour reporting window, but the audit trail is too sparse (or too verbose with noise) to reconstruct what happened quickly | Low likelihood, severe impact if it happens during a real incident | `AuditEvent` coverage is deliberately broad for *consequential* actions (every milestone decision, every payment verification, every certificate issuance/signature-verification, every officer reassignment, every config change) — this list is treated as a checked requirement in Part 11.4's security tests, not an afterthought | `apps/audit/services.py::record_event()` call sites, audited via a coverage test | `CriticalActionsAreAuditedTests` — asserts every service function in the "consequential" list calls `record_event()` |

This catalog is the spine the rest of this document is built against. Where a Part below introduces a model, service, or test, it will reference the `AC-xx` IDs it satisfies rather than re-explaining the threat.

---

## Part 3 — Repository & Project Layout

**Traces to:** TDD §3.1 (modular monolith), §3.3 (deployment topology); research report §1.

### 3.1 Monorepo top-level layout

One repository, matching the TDD's modular-monolith decision — the backend and frontend are deployed together behind one reverse proxy, so they're versioned together too.

```
mbpa-portal/
├── backend/                  # Django + DRF
├── frontend/                 # React SPA (Vite)
├── infra/                    # reverse-proxy config, deploy scripts, db role/grant SQL
├── docs/
│   ├── adr/                  # Architecture Decision Records (Part 1.5)
│   └── runbooks/             # Part 14.4
├── .github/
│   ├── workflows/             # CI/CD (Part 12)
│   ├── PULL_REQUEST_TEMPLATE.md
│   └── dependabot.yml
├── CODEOWNERS
├── CHANGELOG.md
└── README.md                 # repo-level orientation, links to PRD/TDD/DRD and this plan
```

### 3.2 Backend directory tree

Following the HackSoft Django Styleguide convention researched above: a `config/` package owns Django wiring; everything domain-specific lives in `apps/`.

```
backend/
├── manage.py
├── pyproject.toml             # ruff, mypy, coverage config all live here
├── requirements/
│   ├── base.txt
│   ├── local.txt              # + django-debug-toolbar, ipython
│   ├── staging.txt
│   └── production.txt
├── config/
│   ├── __init__.py
│   ├── asgi.py
│   ├── wsgi.py
│   ├── urls.py                 # root URLconf — includes each app's urls.py under /api/
│   ├── celery.py                # NOT USED — kept absent deliberately, see TDD §3.2
│   └── settings/
│       ├── __init__.py
│       ├── base.py
│       ├── local.py
│       ├── staging.py
│       ├── production.py
│       └── test.py             # CI-specific overrides (e.g. faster password hasher)
└── apps/
    ├── common/                 # shared abstract models, exceptions, pagination, healthz
    ├── identity/                # User, ApplicantProfile, OfficerProfile, OtpToken
    ├── applications/            # Application, ApplicationParty, Holiday
    ├── milestones/               # Stream, Milestone, StreamMilestone, MilestoneInstance
    ├── documents/                # DocumentSlot, DocumentUpload
    ├── fees/                     # Concession, FeeAssessment, Payment
    ├── certificates/             # Certificate
    ├── clearances/               # ConditionalClearance
    ├── complaints/               # Complaint
    ├── audit/                    # AuditEvent (and the DB-level enforcement migration)
    ├── config/                   # ConfigParameter
    └── notifications/            # Resend email wrapper, templates
```

Each app under `apps/` follows the same internal shape (HackSoft layering — Part 1.1 principle 2):

```
apps/<app>/
├── __init__.py
├── apps.py
├── models.py
├── services.py          # all writes; the only place transaction.atomic() lives
├── selectors.py          # all non-trivial reads
├── serializers.py
├── permissions.py
├── apis.py               # DRF views — thin, delegate to services/selectors
├── urls.py
├── admin.py
├── factories.py          # factory_boy factories for this app's models
├── migrations/
└── tests/
    ├── test_models.py
    ├── test_services.py
    ├── test_selectors.py
    └── test_apis.py
```

**Why `apis.py` and not `views.py`:** a small but deliberate HackSoft convention — it keeps "this file contains HTTP-facing code" visually distinct from "this file contains a Django view that might render a template," which matters in a codebase where Django's own admin *does* use templates elsewhere. Consistency reduces the chance a future contributor puts business logic in the wrong layer.

### 3.3 App boundaries (bounded contexts) — one-paragraph README per app

Each `apps/<app>/README.md` starts with this paragraph (filled in per app) so a new contributor never has to guess scope:

- **`common`** — Shared abstract base models (`TimestampedModel`), shared exceptions (`DomainError`), shared DRF pagination/throttle classes, the `/healthz` endpoint. Owns nothing domain-specific; if you're tempted to add a model here, it belongs in another app.
- **`identity`** — Authentication, session lifecycle, OTP, and the two profile types. Owns `User`, `ApplicantProfile`, `OfficerProfile`, `OtpToken`. **Traces to PRD §10.1, §10.2; DRD §3, §4, §5, §16.**
- **`applications`** — The central `Application` record and who's party to it. Owns `Application`, `ApplicationParty`, `Holiday`. **Traces to PRD §8, §9.4; DRD §6, §7.**
- **`milestones`** — The lifecycle engine: streams, milestone definitions, and the live per-application milestone state machine. Owns `Stream`, `Milestone`, `StreamMilestone`, `MilestoneInstance`. **Traces to PRD §9.2–§9.11, Appendix §17; DRD §8, §9; TDD §11.**
- **`documents`** — Uploaded files against document-slot requirements, versioned. Owns `DocumentSlot`, `DocumentUpload`. **Traces to PRD §10.13, §11.5; DRD §10.**
- **`fees`** — Fee computation, concessions, and payment-reference recording. Owns `Concession`, `FeeAssessment`, `Payment`. **Traces to PRD §10.5, §10.10, §11.2; DRD §11, §14.**
- **`certificates`** — Certificate/IOD generation and DSC signature verification. Owns `Certificate`. **Traces to PRD §10.12; DRD §15; TDD §8.**
- **`clearances`** — The conditional NOC wizard (Railway/CRZ/heritage/aviation/pollution). Owns `ConditionalClearance`. **Traces to Handoff §2.3 (discovered-in-code), §6.6; DRD §12.**
- **`complaints`** — Applicant- and system-raised complaints. Owns `Complaint`. **Traces to PRD §10.11; DRD §13.**
- **`audit`** — The append-only `AuditEvent` log and the one function (`record_event()`) everything else calls to write to it. **Traces to DRD §18; TDD §10.**
- **`config`** — `ConfigParameter`, the versioned externalisation of every UPDR-2026-dependent value. **Traces to DRD §19.**
- **`notifications`** — Resend integration, email templates, send-failure handling (AC-23).

### 3.4 Frontend directory tree

```
frontend/
├── index.html
├── vite.config.ts
├── tsconfig.json
├── tailwind.config.ts
├── package.json
└── src/
    ├── main.tsx
    ├── App.tsx                     # route tree root
    ├── api/
    │   ├── client.ts                # fetch wrapper: CSRF header, credentials, 403-retry (Part 9.4)
    │   ├── applications.ts
    │   ├── milestones.ts
    │   └── ...                      # one module per backend app, mirroring apps/
    ├── routes/
    │   ├── applicant/                # protected route tree for applicants
    │   ├── officer/                  # protected route tree for officers (role-gated)
    │   └── public/                   # Stream & Fee Planner, Know Your Status, login/register
    ├── components/
    │   ├── ui/                       # shadcn/ui primitives, generated not hand-written
    │   └── domain/                   # MilestoneTimeline, FeeBreakdown, DocumentSlotChecklist, ...
    ├── hooks/
    ├── lib/
    └── types/                        # generated from the OpenAPI schema (openapi-typescript)
```

**Frontend types are generated, not hand-written:** `openapi-typescript` consumes the `drf-spectacular` schema at build time, so the frontend's request/response types can never silently drift from the backend's actual contract (this is the concrete mitigation for the "API contract drift" risk the TDD §6.3 flagged).

### 3.5 Naming conventions

- Django apps: lowercase, plural where the entity is a collection (`applications`, `milestones`), singular where it's a single concern (`audit`, `config`).
- Service functions: verb-first, business language not CRUD language — `submit_application()` not `update_application()`, `transition_milestone()` not `change_status()`. A reviewer should be able to read a service module's function list and get the PRD's process back.
- Test classes: `<ServiceOrApi>Tests` for the unit under test, `<Scenario>Tests` for adversarial/security tests (matching the `AC-xx` table's "Proven by" column verbatim, so `grep`-ing an `AC-xx` ID finds both the mitigation and its test).

---

## Part 4 — Settings & Configuration

**Traces to:** TDD §15 (secrets management), research report §1/§15.

### 4.1 Settings split

`config/settings/base.py`:

```python
"""
Base settings shared by every environment. Environment-specific settings
files import * from this module and override only what differs.

Traces to: TDD §15 (django-environ, no dedicated secrets manager at this scale).
"""
from pathlib import Path
import environ

BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env(
    DJANGO_DEBUG=(bool, False),
)
environ.Env.read_env(BASE_DIR / ".env")  # no-op in environments where .env doesn't exist

SECRET_KEY = env("DJANGO_SECRET_KEY")
DEBUG = env("DJANGO_DEBUG")
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=[])

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # third-party
    "rest_framework",
    "drf_spectacular",
    "simple_history",
    "storages",
    "django_axes",
    # local apps
    "apps.common",
    "apps.identity",
    "apps.applications",
    "apps.milestones",
    "apps.documents",
    "apps.fees",
    "apps.certificates",
    "apps.clearances",
    "apps.complaints",
    "apps.audit",
    "apps.config",
    "apps.notifications",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "simple_history.middleware.HistoryRequestMiddleware",
    "axes.middleware.AxesMiddleware",                          # must be last — see django-axes docs
    "apps.identity.middleware.IdleTimeoutMiddleware",            # role-based idle timeout, Part 9.2
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

AUTH_USER_MODEL = "identity.User"

AUTHENTICATION_BACKENDS = [
    "axes.backends.AxesBackend",                # must be first — see django-axes docs
    "django.contrib.auth.backends.ModelBackend",
]

DATABASES = {
    "default": env.db("DATABASE_URL"),           # restricted app role — see Part 6.2 / db_routers
    "migrations": env.db("MIGRATIONS_DATABASE_URL"),   # privileged/owner role, migrations only
}
DATABASE_ROUTERS = ["config.db_routers.MigrationsRouter"]

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LANGUAGE_CODE = "en-in"
TIME_ZONE = "Asia/Kolkata"   # business/display timezone; storage is always UTC (USE_TZ=True)
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

STORAGES = {
    "default": {
        "BACKEND": "storages.backends.s3.S3Storage",
        "OPTIONS": {
            "bucket_name": env("R2_BUCKET"),
            "endpoint_url": env("R2_ENDPOINT_URL"),
            "region_name": "auto",
            "signature_version": "s3v4",
            "access_key": env("R2_ACCESS_KEY_ID"),
            "secret_key": env("R2_SECRET_ACCESS_KEY"),
            "default_acl": None,         # R2 buckets are private-only — see Part 6 research
            "querystring_auth": True,    # every URL handed out is presigned, time-limited
            "querystring_expire": 300,   # 5 minutes — AC-21
            "file_overwrite": False,     # belt-and-suspenders alongside AC-20's app-level versioning
        },
    },
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",   # deny-by-default, Part 1.1 principle 5
    ],
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.ScopedRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "otp-request": "5/min",
        "otp-verify": "5/min",
        "login": "10/min",
        "know-your-status": "10/min",
    },
    "DEFAULT_PAGINATION_CLASS": "apps.common.pagination.StandardPagination",
    "PAGE_SIZE": 25,
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],  # no BrowsableAPI in prod
    "EXCEPTION_HANDLER": "apps.common.exceptions.domain_exception_handler",
}

SPECTACULAR_SETTINGS = {
    "TITLE": "MbPA Building Permission Portal API",
    "DESCRIPTION": "Internal API for the MbPA Building Permission Portal. Not a public API product.",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "COMPONENT_SPLIT_REQUEST": True,   # read/write serializer split, research report §4
}

AXES_FAILURE_LIMIT = 5
AXES_COOLOFF_TIME = 1  # hours
AXES_LOCKOUT_PARAMETERS = ["username", "ip_address"]

SESSION_ENGINE = "django.contrib.sessions.backends.db"
# SESSION_COOKIE_AGE is intentionally NOT a fixed global — role-based TTL is set per-login
# via request.session.set_expiry() in apps/identity/services.py::login_issue_session().
# This constant is the *ceiling* fallback if set_expiry is ever skipped.
SESSION_COOKIE_AGE = 60 * 60 * 6   # 6h ceiling = the longer (officer) TTL; applicants get 45 min explicitly

EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST = "smtp.resend.com"
EMAIL_PORT = 587
EMAIL_USE_TLS = True
EMAIL_HOST_USER = "resend"
EMAIL_HOST_PASSWORD = env("RESEND_API_KEY")
DEFAULT_FROM_EMAIL = "MbPA Building Permission Portal <noreply@portal.mbpa.gov.in>"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {
        "redact_sensitive": {"()": "apps.common.logging.SensitiveDataFilter"},  # AC-31
    },
    "formatters": {
        "json": {"()": "apps.common.logging.JsonFormatter"},
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "json",
            "filters": ["redact_sensitive"],
        },
    },
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {
        "django.security": {"handlers": ["console"], "level": "WARNING", "propagate": False},
        "apps.audit": {"handlers": ["console"], "level": "INFO", "propagate": False},
    },
}

# --- Domain-specific, non-secret configuration (NOT UPDR-2026 values — those live in ConfigParameter) ---
AADHAAR_PEPPER_ENV_VAR = "AADHAAR_HMAC_PEPPER"   # the pepper itself is read at use-time, never cached on a settings attribute (Part 7.5)
OTP_TTL_SECONDS = 600
OTP_MAX_ATTEMPTS = 5
APPLICANT_SESSION_TTL_SECONDS = 45 * 60
OFFICER_SESSION_TTL_SECONDS = 6 * 60 * 60
DOCUMENT_MAX_UPLOAD_SIZE_BYTES = 25 * 1024 * 1024  # 25MB; per-slot overrides possible via DocumentSlot later
PRESIGNED_URL_TTL_SECONDS = 300
```

`config/settings/local.py`:

```python
from .base import *  # noqa: F403, F401

DEBUG = True
INSTALLED_APPS += ["django_extensions"]  # shell_plus etc., dev convenience only
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"  # never hit real Resend locally
AXES_ENABLED = False  # don't lock yourself out during local dev
```

`config/settings/staging.py`:

```python
from .base import *  # noqa: F403, F401

DEBUG = False
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
# Staging mirrors production security settings exactly — see Part 13.1 — so a
# certification-style review of staging is representative of production.
```

`config/settings/production.py`:

```python
from .base import *  # noqa: F403, F401
import csp.constants

DEBUG = False

SECURE_SSL_REDIRECT = True
SECURE_HSTS_SECONDS = 31536000          # ramp from a smaller value on first rollout — Part 13.1
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")  # ONLY because the reverse proxy strips client-supplied values — see Part 13.1 caveat
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"

SESSION_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SECURE = True
CSRF_COOKIE_HTTPONLY = False             # must be JS-readable so the SPA can echo it — Part 9.3
CSRF_COOKIE_SAMESITE = "Lax"
CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS")  # explicit allow-list, AC-11

MIDDLEWARE = ["csp.middleware.CSPMiddleware"] + MIDDLEWARE  # django-csp on 5.2; native SECURE_CSP from Django 6.0 — Part 13.2
CSP_DEFAULT_SRC = ["'self'"]
CSP_FRAME_ANCESTORS = ["'none'"]
CSP_OBJECT_SRC = ["'none'"]

ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS")  # never ["*"]
```

`.env.example` (committed; the real `.env` is gitignored):

```
DJANGO_SECRET_KEY=
DJANGO_DEBUG=False
DJANGO_ALLOWED_HOSTS=portal.mbpa.gov.in
DATABASE_URL=postgres://app_restricted:***@***.neon.tech/mbpa?sslmode=require
MIGRATIONS_DATABASE_URL=postgres://app_owner:***@***.neon.tech/mbpa?sslmode=require
R2_BUCKET=
R2_ENDPOINT_URL=https://<account_id>.r2.cloudflarestorage.com
R2_ACCESS_KEY_ID=
R2_SECRET_ACCESS_KEY=
RESEND_API_KEY=
AADHAAR_HMAC_PEPPER=
CSRF_TRUSTED_ORIGINS=https://portal.mbpa.gov.in
```

### 4.2 Database router (privileged migrations role vs restricted app role)

**Traces to:** AC-13; research report §6.

```python
# config/db_routers.py
"""
Routes migration commands to the privileged 'migrations' connection (which owns
the schema and can create roles/triggers/grants), and everything else to the
'default' connection (the restricted app role with INSERT/SELECT only on
audit-protected tables). See Part 6.2 for the matching SQL migration.
"""


class MigrationsRouter:
    def allow_migrate(self, db, app_label, model_name=None, **hints):
        return db == "migrations"

    def db_for_write(self, model, **hints):
        return "default"

    def db_for_read(self, model, **hints):
        return "default"
```

`manage.py migrate --database=migrations` is the **only** way migrations are ever run — this is enforced as a documented operational rule (and checked in the CI deploy job, Part 12.1) rather than left to whoever happens to run the command.

---

## Part 5 — Domain Model

**Traces to:** DRD §1–§21 (every entity below maps 1:1 to a DRD section, cited per model). This part translates the DRD's *shape* into actual Django models — the DRD's adversarial checks become code comments and, where DB-enforceable, actual constraints.

### 5.1 `apps/common` — shared infrastructure, no domain models

```python
# apps/common/models.py
"""
Shared abstract base. Deliberately minimal — per DRD §20.2, a blanket
soft-delete base class is explicitly NOT used here, because delete policy
is a per-model decision (Certificate/AuditEvent: never; OtpToken: hard;
Application: soft). Only the universally-true bits (timestamps) are shared.
"""
from django.db import models


class TimestampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
```

```python
# apps/common/exceptions.py
"""
A single DomainError hierarchy so service-layer business-rule violations
are distinguishable from programming errors and from DRF validation errors.
Services raise these; apis.py never raises raw Exception, and never lets a
service-layer assumption fail silently — see Part 1.1 principle 2.
"""


class DomainError(Exception):
    """Base class for all business-rule violations raised from services.py."""
    code = "domain_error"


class InvalidTransitionError(DomainError):
    code = "invalid_transition"


class SeparationOfDutiesError(DomainError):
    code = "separation_of_duties_violation"


class ConcurrentModificationError(DomainError):
    code = "concurrent_modification"


class ConfigurationMissingError(DomainError):
    """Raised when a required ConfigParameter has no active row — fail loud,
    never silently fall back to an invented number (Part 1.1 principle 1)."""
    code = "configuration_missing"
```

```python
# apps/common/exceptions.py (continued) — DRF exception handler
from rest_framework.views import exception_handler as drf_default_handler
from rest_framework.response import Response
from rest_framework import status as http_status


def domain_exception_handler(exc, context):
    if isinstance(exc, DomainError):
        return Response(
            {"error": {"code": exc.code, "detail": str(exc)}},
            status=http_status.HTTP_409_CONFLICT,
        )
    return drf_default_handler(exc, context)
```

```python
# apps/common/views.py
"""
/healthz — deliberately trivial. See AC-24: a Neon cold start after idle is
EXPECTED here (300-800ms), not an incident. This endpoint exists so an
incident responder can distinguish "Neon is cold" from "Neon is actually down"
by checking response time against the documented cold-start budget (Part 14.4).
"""
import subprocess
from django.db import connection
from django.conf import settings
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response


@api_view(["GET"])
@permission_classes([AllowAny])
@throttle_classes([])
def healthz(request):
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
    return Response({
        "status": "ok",
        "version": settings.RELEASE_VERSION,   # set from CI at build time, Part 1.7 / Part 12
        "git_sha": settings.RELEASE_GIT_SHA,
    })
```

### 5.2 `apps/identity` — `User`, `ApplicantProfile`, `OfficerProfile`, `OtpToken`

**Traces to:** DRD §3, §4, §5, §16–17; PRD §10.1, §16 (glossary).

```python
# apps/identity/models.py
from django.contrib.auth.models import AbstractUser
from django.db import models
from apps.common.models import TimestampedModel


class User(AbstractUser):
    """
    A single user table for both applicants and officers (DRD §3).

    Adversarial check (DRD §3 / this plan's AC-09): an officer can legitimately
    also be an applicant. `user_type` is the account's PRIMARY purpose, not an
    exclusivity flag — both an ApplicantProfile and OfficerProfile MAY exist on
    one User. Separation-of-duties is enforced at the service layer
    (apps/milestones/services.py::transition_milestone), not by a schema
    constraint here, because the schema must be able to REPRESENT the
    dual-role case even though business rules restrict what it may DO.
    """

    class UserType(models.TextChoices):
        APPLICANT = "applicant", "Applicant"
        OFFICER = "officer", "Officer"

    user_type = models.CharField(max_length=16, choices=UserType.choices)
    email = models.EmailField(unique=True)
    # username inherited from AbstractUser, kept unique — retained from the
    # prototype's three-credential login (email + username + password), see
    # DRD §3 note and this plan's Part 9.1.

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["email"], name="uniq_user_email"),
        ]


class ApplicantProfile(TimestampedModel):
    """
    Traces to DRD §4. Holds the system's single most sensitive data:
    aadhaar_hash / aadhaar_last4. See Part 6.3 / Part 7.5 for the hashing
    service — this model NEVER has a field for the raw Aadhaar number, by
    design, and that omission is itself the control (AC-07).
    """

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="applicant_profile")
    full_name = models.CharField(max_length=255)
    mobile = models.CharField(max_length=15)

    # Deliberately NOT unique at the DB level — see DRD §4 adversarial check.
    # Dedup is a checked business rule (apps/identity/services.py::check_aadhaar_dedup),
    # not a hard IntegrityError that would surface as a raw 500 to a citizen.
    aadhaar_hash = models.CharField(max_length=64, db_index=True, null=True, blank=True)
    aadhaar_last4 = models.CharField(max_length=4, null=True, blank=True)
    aadhaar_verified_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["aadhaar_hash"])]


class OfficerProfile(TimestampedModel):
    """
    Traces to DRD §5. `zone` and `stream_specialisation` are PROVISIONAL —
    see Part 18 (carried-forward open items). They are nullable/blank so
    that "one person per role" (the current operating assumption) costs
    nothing, while the shape survives MbPA later confirming role-splitting
    without a migration that touches live application-routing data.
    """

    class Role(models.TextChoices):
        ESTATE_OFFICER = "estate_officer", "Estate Officer"
        JUNIOR_PLANNER = "junior_planner", "Junior Planner"
        DEPUTY_PLANNER = "deputy_planner", "Deputy Planner"
        CHAIRMAN = "chairman", "Chairman"

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="officer_profile")
    role = models.CharField(max_length=32, choices=Role.choices)
    zone = models.CharField(max_length=64, null=True, blank=True)  # PROVISIONAL — Part 18
    stream_specialisation = models.ManyToManyField(
        "milestones.Stream", blank=True
    )  # PROVISIONAL — Part 18
    dsc_serial = models.CharField(max_length=128, null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["role"])]


class OtpToken(TimestampedModel):
    """
    Traces to DRD §16-17. Hard-deleted (no soft-delete) — ephemeral,
    contains a credential, no retention value, real privacy value in
    purging (Part 1.1 principle 4). See AC-06 for the brute-force mitigation
    this model's fields exist to support.
    """

    class Purpose(models.TextChoices):
        LOGIN = "login", "Login"
        SIGNUP = "signup", "Signup email verification"
        STATUS_LOOKUP = "status_lookup", "Know Your Status"

    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)
    email = models.EmailField()  # present even when user is null (pre-account signup flow)
    code_hash = models.CharField(max_length=64)   # SHA-256 of the OTP — never store plaintext
    purpose = models.CharField(max_length=16, choices=Purpose.choices)
    attempt_count = models.PositiveSmallIntegerField(default=0)
    expires_at = models.DateTimeField()
    consumed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["email", "purpose", "consumed_at"])]
```

### 5.3 `apps/applications` — `Application`, `ApplicationParty`, `Holiday`

**Traces to:** DRD §6, §7, §9 (Holiday); PRD §8, §9.2–§9.4.

```python
# apps/applications/models.py
from django.db import models, transaction
from apps.common.models import TimestampedModel


class Application(TimestampedModel):
    """
    The central record (DRD §6). Deliberately permissive-at-rest,
    strict-on-transition (Part 1.1 principle: validation lives where the
    state change happens, not as blanket DB NOT-NULL — see DRD §6 AC2,
    "the draft that never was").
    """

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        SUBMITTED = "submitted", "Submitted"
        UNDER_REVIEW = "under_review", "Under review"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        EXPIRED = "expired", "Expired"
        WITHDRAWN = "withdrawn", "Withdrawn"

    application_number = models.CharField(max_length=32, unique=True, db_index=True, blank=True)
    # blank=True at the field level only because it's empty for the instant between
    # object construction and generate_application_number() assigning it inside the
    # SAME transaction in services.py::create_application — never exposed blank via the API.

    stream = models.ForeignKey("milestones.Stream", on_delete=models.PROTECT, related_name="applications")
    current_milestone_instance = models.ForeignKey(
        "milestones.MilestoneInstance", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT)

    plpn = models.CharField(max_length=64, blank=True)          # Port Land Parcel Number — PRD §8/§11.4
    plot_area_sqm = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    proposed_bua_sqm = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    zonal_rrr = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True
    )  # NEVER system-prefilled — PRD's explicit non-goal (§6); always manually entered

    submitted_at = models.DateTimeField(null=True, blank=True)
    is_deleted = models.BooleanField(default=False)   # soft-delete — statutory retention, DRD §1
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["stream", "status"]),
        ]
        constraints = [
            models.CheckConstraint(
                check=models.Q(plot_area_sqm__isnull=True) | models.Q(plot_area_sqm__gte=0),
                name="application_plot_area_non_negative",
            ),
            models.CheckConstraint(
                check=models.Q(proposed_bua_sqm__isnull=True) | models.Q(proposed_bua_sqm__gte=0),
                name="application_bua_non_negative",
            ),
        ]


class ApplicationNumberCounter(TimestampedModel):
    """
    Supporting model for AC-01 (Part 6.1) — NOT part of the headline DRD
    entity count. A row per (prefix, year); incremented under
    select_for_update() so the human-readable application_number above is
    gapless and gunicorn-multi-worker-safe. See services.py for the locking
    service function — this model has no behaviour of its own.
    """
    prefix = models.CharField(max_length=16)
    year = models.PositiveSmallIntegerField()
    last_value = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["prefix", "year"], name="uniq_counter_prefix_year"),
        ]


class ApplicationParty(TimestampedModel):
    """
    Traces to DRD §7 — the co-applicant model. PROVISIONAL pending MbPA
    confirmation that multi-party filing is permitted (Part 18), but built
    now because a single-party application is just one row with
    party_role=OWNER — the reversible choice (DRD §7).
    """

    class PartyRole(models.TextChoices):
        OWNER = "owner", "Owner"
        ARCHITECT = "architect", "Architect"
        LICENSED_SURVEYOR = "licensed_surveyor", "Licensed Surveyor"
        POA_HOLDER = "poa_holder", "Power-of-Attorney Holder"
        CO_OWNER = "co_owner", "Co-owner"

    application = models.ForeignKey(Application, on_delete=models.CASCADE, related_name="parties")
    user = models.ForeignKey("identity.User", on_delete=models.PROTECT, related_name="application_parties")
    party_role = models.CharField(max_length=32, choices=PartyRole.choices)
    is_account_of_record = models.BooleanField(default=False)
    authorisation_doc = models.ForeignKey(
        "documents.DocumentUpload", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta:
        constraints = [
            # AC-05 — the database, not just the service layer, makes a second
            # TRUE for one application impossible. This is the canonical
            # Postgres "exactly one per group" partial unique index pattern.
            models.UniqueConstraint(
                fields=["application"],
                condition=models.Q(is_account_of_record=True),
                name="one_account_of_record_per_application",
            ),
        ]


class Holiday(TimestampedModel):
    """
    Traces to DRD §9 AC1 — supports working-day SLA computation
    (Part 7.4 / AC-17). A DB-driven, admin-editable table rather than a
    hardcoded calendar, specifically so adding a holiday never requires a
    deploy and never retroactively changes an already-computed due_at
    (due_at is a stored snapshot, computed once at transition time).
    """
    date = models.DateField(unique=True)
    description = models.CharField(max_length=255)
    is_second_or_fourth_saturday = models.BooleanField(
        default=False, help_text="India-specific recurring rule; can be bulk-seeded per year."
    )

    class Meta:
        ordering = ["date"]
```

### 5.4 `apps/milestones` — `Stream`, `Milestone`, `StreamMilestone`, `MilestoneInstance`

**Traces to:** DRD §8, §9; PRD §9.2, Appendix §17; TDD §11.

```python
# apps/milestones/models.py
from django.db import models
from apps.common.models import TimestampedModel


class Stream(TimestampedModel):
    """Reference table — the 7 streams (DRD §8). Natural-key code, not seeded with
    UPDR-2026-dependent values here; see apps/config seed command, Part 15.3."""
    code = models.CharField(max_length=32, primary_key=True)   # e.g. "new_building"
    display_name = models.CharField(max_length=128)
    is_active = models.BooleanField(default=True)


class Milestone(TimestampedModel):
    """Reference table — S1-S7 + DEMO (DRD §8)."""
    code = models.CharField(max_length=8, primary_key=True)    # "S1".."S7", "DEMO"
    display_name = models.CharField(max_length=128)
    default_output_certificate_type = models.CharField(max_length=32, blank=True)


class StreamMilestone(TimestampedModel):
    """
    Ordered through-table encoding which milestones belong to which stream,
    in what order (DRD §8) — TDD §11's "explicit data structure, no
    state-machine library" decision, as a DB table rather than a Python dict,
    specifically so it's seedable/auditable/admin-editable.

    AC-18 lives here: deemed_clearance_eligible defaults to False, and is
    SEEDED explicitly False for every (stream, OC) row — see Part 15.3 seed
    command, which sets this with a comment citing the life-safety reasoning.
    This is guard #1 of 2; guard #2 is the hardcoded check in run_sla_sweep.
    """
    stream = models.ForeignKey(Stream, on_delete=models.CASCADE, related_name="stream_milestones")
    milestone = models.ForeignKey(Milestone, on_delete=models.CASCADE, related_name="+")
    sequence_order = models.PositiveSmallIntegerField()
    sla_working_days = models.PositiveSmallIntegerField(
        null=True, blank=True
    )  # populated from ConfigParameter, never hardcoded — Part 18
    deemed_clearance_eligible = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["stream", "milestone"], name="uniq_stream_milestone"),
            models.UniqueConstraint(fields=["stream", "sequence_order"], name="uniq_stream_sequence"),
        ]
        ordering = ["stream", "sequence_order"]


class MilestoneInstance(TimestampedModel):
    """
    Live per-application milestone state (DRD §9) — the single most
    behaviourally important model in the system; transition_milestone()
    (Part 7.2) is the only code path permitted to change its status.
    """

    class Status(models.TextChoices):
        NOT_STARTED = "not_started", "Not started"
        IN_PROGRESS = "in_progress", "In progress"
        APPROVED = "approved", "Approved"
        RETURNED_FOR_CORRECTION = "returned_for_correction", "Returned for correction"
        DEEMED_APPROVED = "deemed_approved", "Deemed approved (SLA breach)"
        REJECTED = "rejected", "Rejected"
        SUPERSEDED = "superseded", "Superseded (stream conversion, AC-27)"

    application = models.ForeignKey(
        "applications.Application", on_delete=models.CASCADE, related_name="milestone_instances"
    )
    milestone = models.ForeignKey(Milestone, on_delete=models.PROTECT, related_name="+")
    assigned_officer = models.ForeignKey(
        "identity.OfficerProfile", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.NOT_STARTED)

    # AC-02: the clock belongs to the INSTANCE, not the current officer —
    # reassignment (e.g. Estate Officer -> Junior Planner within S1's combined
    # 21-day clock, PRD §9.5) never resets started_at. See services.py.
    started_at = models.DateTimeField(null=True, blank=True)
    due_at = models.DateTimeField(null=True, blank=True)   # snapshot, AC-17 — never recomputed on read
    decided_at = models.DateTimeField(null=True, blank=True)
    is_deemed = models.BooleanField(default=False)

    class Meta:
        indexes = [
            models.Index(fields=["assigned_officer", "status"]),   # the officer-queue selector's main index
            models.Index(fields=["application", "status"]),
        ]
```

### 5.5 `apps/documents` — `DocumentSlot`, `DocumentUpload`

**Traces to:** DRD §10; PRD §10.13, §11.5.

```python
# apps/documents/models.py
from django.db import models
from apps.common.models import TimestampedModel


class DocumentSlot(TimestampedModel):
    """
    Reference matrix (DRD §10): which documents a (stream, milestone) pair
    requires. Rows are exhaustively UPDR-2026/prescribed-forms-dependent —
    see Part 18. The table SHAPE is final now; PRD §11.5 gives a handful of
    concretely named rows (Form 4A/4B at S2, Annexure-10 at S3, Annexure-14
    at S7) that can be seeded immediately as a non-exhaustive starting set.
    """
    stream = models.ForeignKey("milestones.Stream", on_delete=models.CASCADE, related_name="document_slots")
    milestone = models.ForeignKey("milestones.Milestone", on_delete=models.CASCADE, related_name="+")
    document_type = models.CharField(max_length=255)   # e.g. "Form 4A — Project Fact Sheet"
    is_mandatory = models.BooleanField(default=True)
    applies_when = models.CharField(
        max_length=64, blank=True
    )  # links to a ConditionalClearance trigger tag, e.g. "height_gt_70m"

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["stream", "milestone", "document_type"], name="uniq_doc_slot"
            ),
        ]


class DocumentUpload(TimestampedModel):
    """
    AC-19 (malicious upload), AC-20 (versioning, never overwrite),
    AC-21 (presigned URL only) all apply to this model — see
    apps/documents/services.py for the enforcement code; this model only
    stores the validated result, never the raw bytes (R2 holds those).
    """
    application = models.ForeignKey(
        "applications.Application", on_delete=models.CASCADE, related_name="documents"
    )
    document_slot = models.ForeignKey(
        DocumentSlot, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )  # nullable for ad-hoc/extra uploads, DRD §10
    milestone_instance = models.ForeignKey(
        "milestones.MilestoneInstance", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    r2_object_key = models.CharField(max_length=512)   # NEVER the file itself — Part 6 research, §11
    original_filename = models.CharField(max_length=255)
    content_type = models.CharField(max_length=128)    # the VALIDATED type (magic bytes), not client-supplied
    size_bytes = models.BigIntegerField()
    uploaded_by = models.ForeignKey("identity.User", on_delete=models.PROTECT, related_name="+")
    version = models.PositiveSmallIntegerField(default=1)
    is_deleted = models.BooleanField(default=False)   # AC-20: hides superseded versions, never destroys them
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["application", "document_slot", "version"])]
        constraints = [
            models.CheckConstraint(check=models.Q(size_bytes__gt=0), name="document_size_positive"),
        ]
```

### 5.6 `apps/fees` — `Concession`, `FeeAssessment`, `Payment`

**Traces to:** DRD §11, §14; PRD §10.5, §10.10, §11.2.

```python
# apps/fees/models.py
from django.db import models
from django.core.exceptions import ValidationError
from apps.common.models import TimestampedModel


class Concession(TimestampedModel):
    class ConcessionType(models.TextChoices):
        ADDITIONAL_FSI = "additional_fsi", "Additional FSI / built-up area"
        OPEN_SPACE_SHORTFALL = "open_space_shortfall", "Open space shortfall"
        PARKING_WAIVER = "parking_waiver", "Parking waiver"
        HEIGHT_RELAXATION = "height_relaxation", "Height relaxation"
        SETBACK_RELAXATION = "setback_relaxation", "Setback relaxation"

    class Source(models.TextChoices):
        AUTO_DETECTED = "auto_detected", "Auto-detected"
        SELF_DECLARED = "self_declared", "Self-declared"

    application = models.ForeignKey(
        "applications.Application", on_delete=models.CASCADE, related_name="concessions"
    )
    concession_type = models.CharField(max_length=32, choices=ConcessionType.choices)
    detected_value = models.DecimalField(max_digits=12, decimal_places=2)
    benchmark_value = models.DecimalField(
        max_digits=12, decimal_places=2
    )  # sourced from ConfigParameter — currently the prototype's "(demo)" placeholders, Part 18
    premium_amount = models.DecimalField(max_digits=14, decimal_places=2)
    source = models.CharField(max_length=16, choices=Source.choices)


class FeeAssessment(TimestampedModel):
    """
    AC-16 / AC-30: the single most important anti-footgun model in the fees
    subsystem. Snapshots computed Decimal amounts + config_version; becomes
    immutable once a Payment against it leaves the 'claimed' state. See
    Part 6.3 for the save() override and the matching DB trigger.
    """
    application = models.OneToOneField(
        "applications.Application", on_delete=models.CASCADE, related_name="fee_assessment"
    )
    scrutiny_fee = models.DecimalField(max_digits=14, decimal_places=2)
    security_deposit = models.DecimalField(max_digits=14, decimal_places=2)
    debris_deposit = models.DecimalField(max_digits=14, decimal_places=2)
    total_concession_premium = models.DecimalField(max_digits=14, decimal_places=2)
    master_challan_total = models.DecimalField(max_digits=14, decimal_places=2)
    computed_at = models.DateTimeField(auto_now_add=True)
    config_version = models.PositiveIntegerField()   # which ConfigParameter version produced this — AC-16
    is_locked = models.BooleanField(default=False)   # set True the moment a Payment moves past 'claimed'

    def save(self, *args, **kwargs):
        if self.pk:
            existing = FeeAssessment.objects.filter(pk=self.pk, is_locked=True).exists()
            if existing:
                raise ValidationError(
                    "FeeAssessment is locked once payment has progressed past 'claimed' "
                    "(AC-16). Use apps.fees.services.reassess_fee() to create a new "
                    "assessment instead of mutating this one."
                )
        super().save(*args, **kwargs)

    class Meta:
        constraints = [
            models.CheckConstraint(
                check=models.Q(master_challan_total__gte=0), name="fee_total_non_negative"
            ),
        ]


class Payment(TimestampedModel):
    """
    Traces to DRD §14 — "deliberately the trickiest". No live gateway
    (PRD §6 non-goal), so this stores only a reference number and amount,
    never an actual financial instrument — which is precisely what makes
    hard-delete-for-privacy vs retain-for-statute NOT actually conflict here
    (DRD §14 AC2).
    """

    class Status(models.TextChoices):
        CLAIMED = "claimed", "Claimed"
        VERIFIED = "verified", "Verified"
        REJECTED = "rejected", "Rejected"
        MISMATCH = "mismatch", "Mismatch"

    application = models.ForeignKey(
        "applications.Application", on_delete=models.PROTECT, related_name="payments"
    )
    fee_assessment = models.ForeignKey(FeeAssessment, on_delete=models.PROTECT, related_name="payments")
    challan_reference = models.CharField(max_length=64, db_index=True)  # indexed, NOT unique — DRD §14 AC1
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.CLAIMED)
    verified_by = models.ForeignKey(
        "identity.OfficerProfile", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    verified_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["application", "status"])]
```

### 5.7 `apps/certificates` — `Certificate`

**Traces to:** DRD §15; PRD §10.12; TDD §8.

```python
# apps/certificates/models.py
from django.db import models
from django.core.exceptions import ValidationError
from apps.common.models import TimestampedModel


class Certificate(TimestampedModel):
    """
    The legal artifact (DRD §15). NEVER deleted or mutated — a certificate
    that should no longer apply is REVOKED (a new state), never removed.
    See AC-25 for the signature-verification gate this model's
    signature_verified field exists to support.
    """

    class CertificateType(models.TextChoices):
        AIP = "aip", "Approval in Principle"
        DEVELOPMENT_PERMISSION = "development_permission", "Development Permission"
        COMMENCEMENT = "commencement", "Commencement Certificate"
        COMPLETION = "completion", "Building Completion Certificate"
        OCCUPANCY = "occupancy", "Occupancy Certificate"
        IOD = "iod", "Intimation of Disapproval"
        SITE_CLEARANCE = "site_clearance", "Demolition & Site Clearance Certificate"

    application = models.ForeignKey(
        "applications.Application", on_delete=models.PROTECT, related_name="certificates"
    )
    milestone_instance = models.ForeignKey(
        "milestones.MilestoneInstance", on_delete=models.PROTECT, related_name="certificates"
    )
    certificate_type = models.CharField(max_length=32, choices=CertificateType.choices)
    r2_object_key = models.CharField(max_length=512)
    signature_verified = models.BooleanField(default=False)   # AC-25 — set only by receive_signed_certificate()
    signed_by = models.ForeignKey(
        "identity.OfficerProfile", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    dsc_serial_used = models.CharField(max_length=128, blank=True)
    issued_at = models.DateTimeField(null=True, blank=True)
    valid_until = models.DateTimeField(null=True, blank=True)   # AIP=2yr, Dev Permission=5yr — PRD §9.5/§9.6
    revoked_at = models.DateTimeField(null=True, blank=True)

    def save(self, *args, **kwargs):
        if self.pk and Certificate.objects.filter(pk=self.pk).exclude(revoked_at=None).exists():
            # allow setting revoked_at itself, but nothing else may change post-revocation
            pass
        super().save(*args, **kwargs)
        # Full immutability (no field changes once issued_at is set, other than revoked_at)
        # is additionally enforced at the DB level — see Part 6.3's trigger, which covers
        # both Certificate and FeeAssessment with one generic "freeze after issuance" pattern.

    class Meta:
        indexes = [models.Index(fields=["application", "certificate_type"])]
```

### 5.8 `apps/clearances` — `ConditionalClearance`

**Traces to:** DRD §12; Handoff §2.3/§6.6.

```python
# apps/clearances/models.py
from django.db import models
from apps.common.models import TimestampedModel


class ConditionalClearance(TimestampedModel):
    """
    The 7-question NOC wizard discovered in the prototype's code but
    undocumented in the PRD (Handoff §2.3). trigger_metadata is a JSONField
    deliberately — AAI aviation clearance is a coordinate-vs-Colour-Coded-
    Zoning-Map calculation, not a flat height threshold, and CRZ is a
    distance-from-HTL calculation; a plain boolean would throw away the
    inputs that justified the trigger (DRD §12 AC).
    """

    class ClearanceType(models.TextChoices):
        RAILWAY = "railway", "Railway"
        CRZ_MCZMA = "crz_mczma", "CRZ / MCZMA"
        MHCC_HERITAGE = "mhcc_heritage", "MHCC Heritage"
        AAI_AVIATION = "aai_aviation", "AAI / Aviation"
        MPCB = "mpcb", "MPCB Pollution"

    class Status(models.TextChoices):
        NOT_REQUIRED = "not_required", "Not required"
        PENDING_UPLOAD = "pending_upload", "Pending upload"
        UPLOADED = "uploaded", "Uploaded"
        VERIFIED = "verified", "Verified"

    application = models.ForeignKey(
        "applications.Application", on_delete=models.CASCADE, related_name="conditional_clearances"
    )
    clearance_type = models.CharField(max_length=16, choices=ClearanceType.choices)
    is_triggered = models.BooleanField(default=False)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.NOT_REQUIRED)
    clearance_doc = models.ForeignKey(
        "documents.DocumentUpload", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    trigger_metadata = models.JSONField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["application", "clearance_type"], name="uniq_clearance_per_application"
            ),
        ]
```

### 5.9 `apps/complaints` — `Complaint`

**Traces to:** DRD §13; PRD §10.11.

```python
# apps/complaints/models.py
from django.db import models
from django.core.exceptions import ValidationError
from apps.common.models import TimestampedModel


class Complaint(TimestampedModel):
    """AC-28: raised_by nullability is paired with an enforced business
    rule, checked in services.py — origin=SYSTEM_RAISED iff raised_by is None."""

    class Origin(models.TextChoices):
        APPLICANT_RAISED = "applicant_raised", "Applicant-raised"
        SYSTEM_RAISED = "system_raised", "System-raised (SLA breach)"

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        IN_PROGRESS = "in_progress", "In progress"
        RESOLVED = "resolved", "Resolved"
        CLOSED = "closed", "Closed"

    application = models.ForeignKey(
        "applications.Application", on_delete=models.CASCADE, related_name="complaints"
    )
    origin = models.CharField(max_length=20, choices=Origin.choices)
    raised_by = models.ForeignKey(
        "identity.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    subject = models.CharField(max_length=255)
    body = models.TextField()
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.OPEN)
    resolution_note = models.TextField(blank=True)

    def clean(self):
        if self.origin == self.Origin.SYSTEM_RAISED and self.raised_by_id is not None:
            raise ValidationError("System-raised complaints must not have a human raised_by.")
        if self.origin == self.Origin.APPLICANT_RAISED and self.raised_by_id is None:
            raise ValidationError("Applicant-raised complaints must record who raised them.")
```

### 5.10 `apps/audit` — `AuditEvent`

**Traces to:** DRD §18; TDD §10. Full model, the matching SQL migration, and the `record_event()` helper are detailed together in **Part 6.2** since this entity's correctness depends on database-level enforcement, not just the model definition.

### 5.11 `apps/config` — `ConfigParameter`

**Traces to:** DRD §19. Full model and the versioning service are detailed together in **Part 6.3** alongside `FeeAssessment`'s immutability, since the two are two halves of one mechanism (externalised, versioned values feeding an immutable snapshot).

---

## Part 6 — The Three Hard Primitives

These are the pieces the research explicitly flagged as the ones auditors scrutinize and the hardest to retrofit. They're built once, early (Phase 0/1 in Part 16), and everything else depends on them.

### 6.1 Atomic application-number generation

**Traces to:** DRD §6 AC1 (AC-01); research report §5.

```python
# apps/applications/services.py (excerpt)
"""
generate_application_number() — the gapless, concurrency-safe counter.

Why NOT a bare Postgres SEQUENCE: a sequence is concurrency-safe but gappy
(rolled-back transactions consume values) and doesn't cleanly support a
PER-YEAR reset to the documented MBPASPA<year><sequence> format without
extra bookkeeping anyway. Why NOT COUNT(*)+1: two concurrent requests can
read the same count before either commits — AC-01, the exact bug the DRD
flagged as something the prototype's single-threaded Apps Script runtime
never could have hit, but Gunicorn-with-multiple-workers will.

Resolution: a dedicated counter row per (prefix, year), locked with
select_for_update() inside the SAME transaction that creates the
Application row. The lock is held only for the few milliseconds between
SELECT...FOR UPDATE and the increment's COMMIT — short enough that this
does not become a throughput bottleneck at this system's expected volume
(a handful of applications per day, not per second).
"""
from django.db import transaction
from django.utils import timezone
from apps.applications.models import Application, ApplicationNumberCounter

APPLICATION_NUMBER_PREFIX = "MBPASPA"


@transaction.atomic
def generate_application_number() -> str:
    year = timezone.localdate().year   # IST calendar year, per TDD §6.4/DRD §20.5 timezone discipline
    counter, _ = ApplicationNumberCounter.objects.select_for_update().get_or_create(
        prefix=APPLICATION_NUMBER_PREFIX, year=year, defaults={"last_value": 0}
    )
    counter.last_value += 1
    counter.save(update_fields=["last_value", "updated_at"])
    # Format: MBPASPA + 4-digit year + zero-padded sequence (width chosen
    # generously; revisit only if MbPA's real volume ever approaches 99999/yr)
    return f"{APPLICATION_NUMBER_PREFIX}{year}{counter.last_value:05d}"


@transaction.atomic
def create_application(*, stream_code: str, created_by) -> Application:
    """
    Traces to PRD §9.4. The number is generated and the row is created in
    ONE transaction — if anything downstream in this function fails, the
    counter increment rolls back too, so a failed creation never "burns" a
    number into a permanent gap. (We accept the theoretical case where a
    process crashes between the counter commit and a later step in a
    *different* transaction as out of scope — see Part 16 Phase 3 for why
    this function intentionally does all of its writes in one transaction
    rather than spanning several.)
    """
    from apps.milestones.models import Stream

    stream = Stream.objects.get(code=stream_code, is_active=True)
    application = Application.objects.create(
        application_number=generate_application_number(),
        stream=stream,
        status=Application.Status.DRAFT,
    )
    from apps.applications.models import ApplicationParty
    ApplicationParty.objects.create(
        application=application, user=created_by,
        party_role=ApplicationParty.PartyRole.OWNER, is_account_of_record=True,
    )
    return application
```

**Adversarial check (AC-01 proof, summarized — full test in Part 11.2):** a `TransactionTestCase` spins up N threads, each opening its own DB connection and calling `generate_application_number()` concurrently; the assertion is that the resulting set of numbers has **no duplicates and no gaps** across N calls. This must run against real Postgres `select_for_update()` semantics, which is exactly why `TransactionTestCase` (not `TestCase`) is mandatory here — `TestCase` wraps the whole test in one outer transaction and silently defeats the row-locking behavior under test.

### 6.2 Append-only audit enforcement

**Traces to:** DRD §18 (AC-13, AC-14, AC-15, AC-31); research report §6.

This is implemented in **three layers**, deliberately redundant — the DRD was explicit that application-level-only enforcement "leaves a back door."

**Layer 1 — the model:**

```python
# apps/audit/models.py
from django.db import models
from django.core.exceptions import ValidationError


class AuditEvent(models.Model):
    """
    The immutable backbone (DRD §18) — the most safety-critical table in the
    system. Deliberately does NOT inherit TimestampedModel (which has
    auto_now on updated_at — an audit row must never have an "updated_at"
    because it must never be updated).

    target_type / target_id are PLAIN FIELDS, not a Django GenericForeignKey
    (AC-14): a GFK's reverse GenericRelation would let a target's delete
    cascade into deleting its own audit history, which is the exact "back
    door" the DRD's research warned about. Storing a bare (type, id) pair
    means there is no reverse relation for a cascade to travel across, full
    stop — Django literally cannot cascade through a field it doesn't know
    is a relation.
    """

    class EventType(models.TextChoices):
        MILESTONE_APPROVED = "milestone_approved", "Milestone approved"
        MILESTONE_REJECTED = "milestone_rejected", "Milestone rejected"
        MILESTONE_RETURNED = "milestone_returned", "Milestone returned for correction"
        DEEMED_CLEARANCE_FIRED = "deemed_clearance_fired", "Deemed clearance fired"
        IOD_ISSUED = "iod_issued", "IOD issued"
        OFFICER_REASSIGNED = "officer_reassigned", "Officer reassigned"
        PAYMENT_VERIFIED = "payment_verified", "Payment verified"
        STREAM_CONVERTED = "stream_converted", "Stream converted"
        CONFIG_CHANGED = "config_changed", "ConfigParameter changed"
        CERTIFICATE_ISSUED = "certificate_issued", "Certificate issued"
        SIGNATURE_VERIFIED = "signature_verified", "DSC signature verified"
        SIGNATURE_REJECTED = "signature_rejected", "DSC signature rejected"
        ERASURE_PROCESSED = "erasure_processed", "DPDP erasure request processed"
        COMPLAINT_RAISED = "complaint_raised", "Complaint raised"

    sequence = models.BigAutoField(primary_key=True)   # AC-15: monotonic ordering, NOT created_at
    actor = models.ForeignKey(
        "identity.User", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )  # null = system action (e.g. the SLA sweep)
    event_type = models.CharField(max_length=32, choices=EventType.choices)
    target_type = models.CharField(max_length=64)   # e.g. "applications.application" — AC-14
    target_id = models.CharField(max_length=64)
    summary = models.TextField()                    # human-readable "what happened and why"
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)   # for human reading only — AC-15

    class Meta:
        indexes = [
            models.Index(fields=["target_type", "target_id"]),
            models.Index(fields=["event_type"]),
        ]

    def save(self, *args, **kwargs):
        # Layer 1 of 3 — AC-13. Refuses any save() call on a row that
        # already has a PK (i.e. any UPDATE attempt through the ORM).
        if self.pk is not None and AuditEvent.objects.filter(pk=self.pk).exists():
            raise ValidationError(
                "AuditEvent rows are append-only. This is enforced again at the "
                "database level (see the matching migration) — this app-level "
                "guard exists for a fast, friendly error in normal operation, "
                "not as the real security boundary."
            )
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("AuditEvent rows can never be deleted, by anyone, ever.")
```

**Layer 2 — the database-level enforcement migration (the real boundary):**

```python
# apps/audit/migrations/0002_audit_append_only_enforcement.py
"""
Layer 2 of 3 (AC-13) — and the one that actually matters. Runs against the
'migrations' (privileged/owner) connection per config/db_routers.py.

This migration:
  1. Creates a restricted role the Django app actually connects as.
  2. Grants it SELECT, INSERT on audit_auditevent — explicitly NOT
     UPDATE or DELETE.
  3. Installs a trigger that RAISEs on UPDATE/DELETE regardless of which
     role attempts it — a second, independent guard, because role grants
     alone can be undone by someone with the power to grant roles, but a
     trigger on the table itself is a second, separately-reviewed line of
     defense (PostgreSQL wiki's "Audit trigger" pattern, see research §6).

Layer 3 (the actual transactional binding of a state-change + its
AuditEvent into one commit) lives in apps/audit/services.py::record_event(),
shown below — not in this migration.
"""
from django.db import migrations

SQL_FORWARD = """
-- Restricted role the application's DATABASE_URL connects as.
-- (If this role already exists from initial provisioning, this is a no-op
-- guard so the migration is safe to re-run.)
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'app_restricted') THEN
        CREATE ROLE app_restricted LOGIN PASSWORD :'app_restricted_password';
    END IF;
END
$$;

GRANT CONNECT ON DATABASE mbpa TO app_restricted;
GRANT USAGE ON SCHEMA public TO app_restricted;

-- Default posture for the restricted role on every table EXCEPT the audit
-- table: full DML, no DDL. The audit table gets the special treatment below.
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO app_restricted;
REVOKE UPDATE, DELETE ON audit_auditevent FROM app_restricted;

CREATE OR REPLACE FUNCTION audit_protect_append_only()
RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'audit_auditevent is append-only: % is forbidden on this table', TG_OP;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS protect_audit_append_only ON audit_auditevent;
CREATE TRIGGER protect_audit_append_only
    BEFORE UPDATE OR DELETE ON audit_auditevent
    FOR EACH ROW EXECUTE FUNCTION audit_protect_append_only();
"""

SQL_REVERSE = """
DROP TRIGGER IF EXISTS protect_audit_append_only ON audit_auditevent;
DROP FUNCTION IF EXISTS audit_protect_append_only();
GRANT UPDATE, DELETE ON audit_auditevent TO app_restricted;
"""


class Migration(migrations.Migration):
    dependencies = [("audit", "0001_initial")]
    operations = [
        migrations.RunSQL(sql=SQL_FORWARD, reverse_sql=SQL_REVERSE),
    ]
```

**Layer 3 — the transactional binding helper everything else calls:**

```python
# apps/audit/services.py
"""
record_event() is the ONLY way the rest of the codebase writes an
AuditEvent. This exists so AC-31 (sensitive-data leakage into audit
metadata) and "the dual-write problem" (DRD §20.1) are each solved exactly
once, here, rather than re-solved correctly-or-not at every call site.
"""
from django.db import transaction
from apps.audit.models import AuditEvent

# AC-31: keys that must never appear in AuditEvent.metadata. Checked, not
# just documented — see CriticalActionsAreAuditedTests / SensitiveFieldRedactionTests.
_FORBIDDEN_METADATA_KEYS = {
    "aadhaar", "aadhaar_number", "aadhaar_raw", "otp_code", "password",
    "card_number", "cvv",
}


def record_event(*, actor, event_type: str, target, summary: str, metadata: dict | None = None) -> AuditEvent:
    """
    Must always be called from WITHIN the same transaction.atomic() block
    as the state change it documents (Part 1.1 principle 6 / DRD §20.1).
    Callers do not open their own transaction here — this function assumes
    one is already open and will raise (via the assertion) in test/dev if
    called outside one, surfaced through Django's `transaction.get_autocommit()`.
    """
    assert not transaction.get_autocommit(), (
        "record_event() must be called inside an existing transaction.atomic() "
        "block, alongside the state change it documents — see AC-31's sibling "
        "'dual-write problem' (DRD §20.1)."
    )
    metadata = metadata or {}
    leaked = _FORBIDDEN_METADATA_KEYS & metadata.keys()
    if leaked:
        raise ValueError(f"Refusing to write forbidden keys to AuditEvent.metadata: {leaked}")

    return AuditEvent.objects.create(
        actor=actor,
        event_type=event_type,
        target_type=f"{target._meta.app_label}.{target._meta.model_name}",
        target_id=str(target.pk),
        summary=summary,
        metadata=metadata,
    )
```

### 6.3 Fee snapshot immutability & `ConfigParameter`

**Traces to:** DRD §19, §11 AC1 (AC-16, AC-30); research report §8.

```python
# apps/config/models.py
from django.db import models
from apps.common.models import TimestampedModel


class ConfigParameter(TimestampedModel):
    """
    Traces to DRD §19 — the mechanism that keeps every UPDR-2026-dependent
    value out of the *schema* (it lives here, as versioned data) so that
    "real values arrive" is an INSERT, never a migration or a code change.
    See Part 18 for the full list of keys this table must carry before any
    fee/SLA/benchmark figure currently in the codebase can be trusted as
    final.
    """
    key = models.CharField(max_length=128, db_index=True)
    # value stored as Decimal-compatible string in a JSONField rather than a
    # bare DecimalField, because some keys (document-slot lists, benchmark
    # sets) are structured, not scalar — callers that need a Decimal parse
    # it explicitly via get_decimal() below, never via implicit JSON coercion.
    value = models.JSONField()
    effective_from = models.DateField()
    version = models.PositiveIntegerField()
    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["key", "version"], name="uniq_config_key_version"),
        ]
        indexes = [models.Index(fields=["key", "is_active"])]
```

```python
# apps/config/services.py
from decimal import Decimal
from apps.common.exceptions import ConfigurationMissingError
from apps.config.models import ConfigParameter


def get_active_config(key: str) -> ConfigParameter:
    """
    Fail loud (Part 1.1 principle 1) — if a UPDR-2026-dependent key has no
    active row, this raises rather than silently defaulting to an invented
    number. Every caller in apps/fees/services.py and the SLA sweep goes
    through this, never reads ConfigParameter.objects directly.
    """
    row = ConfigParameter.objects.filter(key=key, is_active=True).order_by("-version").first()
    if row is None:
        raise ConfigurationMissingError(
            f"No active ConfigParameter for key={key!r}. This value is "
            f"UPDR-2026-dependent and must be seeded before this code path "
            f"can run — see Part 18 of the build plan."
        )
    return row


def get_decimal_config(key: str) -> Decimal:
    row = get_active_config(key)
    return Decimal(str(row.value))
```

```python
# apps/fees/services.py (excerpt — the snapshot-creating half of AC-16)
from decimal import Decimal
from django.db import transaction
from apps.config.services import get_decimal_config, get_active_config
from apps.fees.models import FeeAssessment, Concession
from apps.audit.services import record_event


@transaction.atomic
def assess_fee(*, application, concessions: list[dict]) -> FeeAssessment:
    """
    Traces to PRD §10.5, §11.2. Computes and SNAPSHOTS the fee — this is
    the write path AC-16's "immutable once payment begins" guarantee
    depends on. concessions is [{"concession_type": ..., "delta_area": Decimal, "source": ...}, ...].
    """
    bua = application.proposed_bua_sqm
    rrr = application.zonal_rrr  # never system-prefilled — PRD's explicit rule
    if bua is None or rrr is None:
        raise ValueError("proposed_bua_sqm and zonal_rrr must both be set before fee assessment.")

    scrutiny_rate = get_decimal_config("scrutiny_fee_per_sqm")
    security_rate = get_decimal_config("security_deposit_per_sqm")
    debris_rate = get_decimal_config("debris_deposit_per_sqm")
    config_row = get_active_config("scrutiny_fee_per_sqm")   # version reference for the snapshot

    scrutiny_fee = (bua * scrutiny_rate).quantize(Decimal("0.01"))
    security_deposit = (bua * security_rate).quantize(Decimal("0.01"))
    debris_deposit = (bua * debris_rate).quantize(Decimal("0.01"))

    total_premium = Decimal("0.00")
    for item in concessions:
        coef = get_decimal_config(f"premium_coefficient.{item['concession_type']}")
        premium = (Decimal(item["delta_area"]) * rrr * coef).quantize(Decimal("0.01"))
        total_premium += premium
        Concession.objects.create(
            application=application,
            concession_type=item["concession_type"],
            detected_value=item["delta_area"],
            benchmark_value=get_decimal_config(f"benchmark.{item['concession_type']}"),
            premium_amount=premium,
            source=item["source"],
        )

    master_challan_total = scrutiny_fee + security_deposit + debris_deposit + total_premium

    assessment = FeeAssessment.objects.create(
        application=application,
        scrutiny_fee=scrutiny_fee,
        security_deposit=security_deposit,
        debris_deposit=debris_deposit,
        total_concession_premium=total_premium,
        master_challan_total=master_challan_total,
        config_version=config_row.version,
    )
    record_event(
        actor=None, event_type="config_changed", target=assessment,
        summary=f"Fee assessed for {application.application_number} using config v{config_row.version}.",
        metadata={"master_challan_total": str(master_challan_total)},
    )
    return assessment


@transaction.atomic
def reassess_fee(*, application, concessions: list[dict]) -> FeeAssessment:
    """
    AC-30: editing BUA/concessions after an assessment exists never mutates
    the old row — it creates a NEW one. The old assessment, if locked,
    stays locked and historically accurate to what was actually paid against;
    callers (selectors.py) always serve the latest by computed_at.
    """
    old = FeeAssessment.objects.filter(application=application).order_by("-computed_at").first()
    if old and old.is_locked:
        # A new OneToOne can't coexist with the locked one on Application directly
        # (FeeAssessment.application is OneToOneField) — this is intentionally a
        # design fork: see Part 18, "fee re-assessment after lock" is flagged as
        # needing a real product decision (supersede vs. amend) before this path
        # is wired to production. Implementing the OneToOne as a ForeignKey with
        # an `is_current` flag is the likely resolution; left as an explicit TODO
        # rather than guessed here.
        raise NotImplementedError(
            "Re-assessment after a locked FeeAssessment requires a product "
            "decision (supersede vs. amend) — see Part 18. Not yet implemented."
        )
    return assess_fee(application=application, concessions=concessions)
```

The `FeeAssessment.save()` override shown in Part 5.6 is layer 1 of this same two-layer pattern; layer 2 (the DB trigger) is created in the same migration style as Part 6.2's audit trigger, applied to both `fees_feeassessment` (guarding all columns once `is_locked=True`) and `certificates_certificate` (guarding all columns once `issued_at` is non-null) — written once as a small reusable `freeze_after()` trigger function parameterised by table name, rather than duplicated per table.

---

## Part 7 — Services & Selectors Layer

### 7.1 `apps/applications/services.py` — stream conversion

**Traces to:** DRD §6 AC3 (AC-27); PRD Stream table ("Addition/Alteration... converts... if work exceeds 50%").

```python
# apps/applications/services.py (continued from Part 6.1)
from django.db import transaction
from apps.applications.models import Application
from apps.audit.services import record_event


@transaction.atomic
def convert_stream(*, application: Application, new_stream_code: str, actor, reason: str) -> Application:
    """
    AC-27: never a bare `application.stream = new_stream; application.save()`.
    Closes obsolete MilestoneInstance rows as SUPERSEDED (not deleted —
    history is preserved per Part 1.1 principle 4) and opens fresh instances
    for the new stream's sequence. The 50%-of-original-BUA THRESHOLD VALUE
    itself is UPDR-2026-dependent (Part 18) — this function takes the
    decision as a given input, it does not decide when conversion should fire.
    """
    from apps.milestones.models import Stream, StreamMilestone, MilestoneInstance

    old_stream = application.stream
    new_stream = Stream.objects.get(code=new_stream_code, is_active=True)

    obsolete = MilestoneInstance.objects.filter(
        application=application
    ).exclude(status__in=[MilestoneInstance.Status.APPROVED, MilestoneInstance.Status.DEEMED_APPROVED])
    obsolete.update(status=MilestoneInstance.Status.SUPERSEDED)

    application.stream = new_stream
    application.save(update_fields=["stream", "updated_at"])

    for sm in StreamMilestone.objects.filter(stream=new_stream).order_by("sequence_order"):
        MilestoneInstance.objects.get_or_create(
            application=application, milestone=sm.milestone,
            defaults={"status": MilestoneInstance.Status.NOT_STARTED},
        )

    record_event(
        actor=actor, event_type="stream_converted", target=application,
        summary=f"{application.application_number} converted from {old_stream.code} to {new_stream.code}: {reason}",
        metadata={"old_stream": old_stream.code, "new_stream": new_stream.code},
    )
    return application
```

### 7.2 `apps/milestones/services.py` — `transition_milestone()`

**Traces to:** TDD §11 ("one `transition_milestone()` service function validates against it"); PRD §9.5–§9.11, §11.3 (strict sequencing); DRD §9 AC1/AC2 (AC-02, AC-17); covers AC-02, AC-08, AC-09, AC-18, AC-29.

This is the single function the rest of the system's correctness depends on most. Every adversarial check in Part 2 that touches milestone state funnels through it.

```python
# apps/milestones/services.py
"""
transition_milestone() — the one and only way a MilestoneInstance's status
changes. No view, serializer, or admin action is permitted to write to
MilestoneInstance.status directly (enforced by code review + the
MassAssignmentTests in Part 11.4, since Python itself can't prevent a
future developer from doing it wrong — this is a discipline the test suite
defends, not a language guarantee).
"""
from datetime import datetime
from django.db import transaction
from django.utils import timezone

from apps.common.exceptions import InvalidTransitionError, SeparationOfDutiesError, ConcurrentModificationError
from apps.milestones.models import MilestoneInstance, StreamMilestone, Milestone
from apps.applications.models import Application, ApplicationParty
from apps.audit.services import record_event


class TransitionAction:
    APPROVE = "approve"
    RETURN_FOR_CORRECTION = "return_for_correction"
    REJECT = "reject"


@transaction.atomic
def transition_milestone(
    *,
    milestone_instance_id: int,
    action: str,
    acting_officer,            # apps.identity.models.OfficerProfile
    decision_note: str = "",
    correction_reason: str = "",
) -> MilestoneInstance:
    """
    Traces to TDD §11, PRD §9.5-§9.11/§11.3.

    Args:
        milestone_instance_id: PK of the MilestoneInstance being decided.
        action: one of TransitionAction.{APPROVE, RETURN_FOR_CORRECTION, REJECT}.
        acting_officer: the OfficerProfile making the decision (NOT the User —
            forces every call site to have already resolved "is this person
            an officer at all", pushing that check out of this function).
        decision_note / correction_reason: human-readable context, stored on
            the AuditEvent.summary — PRD §10.7 requires "a written reason"
            attached to every return-for-correction.

    Returns the updated MilestoneInstance.

    Raises:
        InvalidTransitionError — wrong status for the requested action, or
            an earlier milestone in the stream's sequence isn't cleared yet
            (AC-29 — this is the SAME check for every stream, including the
            re-erection DEMO step; there is no per-stream special case).
        SeparationOfDutiesError — acting_officer is a party to this
            application (AC-09).
        ConcurrentModificationError — the row was already decided by a
            concurrent call between this call's read and its lock (AC-02).
    """
    # select_for_update() — AC-02: the second of two concurrent approve calls
    # blocks here until the first commits, then sees the ALREADY-APPROVED
    # state and raises, rather than silently re-applying the transition.
    instance = MilestoneInstance.objects.select_for_update().select_related(
        "application", "milestone"
    ).get(pk=milestone_instance_id)

    if instance.status not in (MilestoneInstance.Status.IN_PROGRESS, MilestoneInstance.Status.NOT_STARTED):
        raise ConcurrentModificationError(
            f"MilestoneInstance {instance.pk} is already {instance.status}; "
            f"refusing to re-apply '{action}'."
        )

    _assert_no_separation_of_duties_violation(instance.application, acting_officer)
    _assert_prior_milestones_cleared(instance)   # AC-29, generic across all streams

    now = timezone.now()

    if action == TransitionAction.APPROVE:
        instance.status = MilestoneInstance.Status.APPROVED
        instance.decided_at = now
        event_type, summary = "milestone_approved", (
            f"{instance.milestone.code} approved for {instance.application.application_number} "
            f"by {acting_officer.user.get_full_name() or acting_officer.user.username}. {decision_note}"
        )
    elif action == TransitionAction.RETURN_FOR_CORRECTION:
        if not correction_reason:
            raise InvalidTransitionError("A correction_reason is required to return a milestone (PRD §10.7).")
        instance.status = MilestoneInstance.Status.RETURNED_FOR_CORRECTION
        event_type, summary = "milestone_returned", (
            f"{instance.milestone.code} returned for correction on {instance.application.application_number}: "
            f"{correction_reason}"
        )
    elif action == TransitionAction.REJECT:
        instance.status = MilestoneInstance.Status.REJECTED
        instance.decided_at = now
        event_type, summary = "milestone_rejected", (
            f"{instance.milestone.code} rejected for {instance.application.application_number}: {decision_note}"
        )
        # IOD auto-vs-discretionary is an OPEN ITEM (Part 18) — this function
        # deliberately does NOT auto-create a Certificate(type=IOD) here.
        # apps/certificates/services.py exposes issue_iod() as an explicit,
        # separately-called action so either resolution of that open question
        # (auto-coupled or officer-discretionary) is a caller-side decision,
        # not baked into this function — matching DRD §15 AC2's neutrality stance.
    else:
        raise InvalidTransitionError(f"Unknown transition action: {action!r}")

    instance.save(update_fields=["status", "decided_at", "updated_at"])

    record_event(
        actor=acting_officer.user, event_type=event_type, target=instance,
        summary=summary, metadata={"action": action},
    )

    if action == TransitionAction.APPROVE:
        _advance_to_next_milestone_if_any(instance)

    return instance


def _assert_no_separation_of_duties_violation(application: Application, acting_officer) -> None:
    """AC-09. Checked at DECISION time, not just assignment time — an
    officer could become a party to an application AFTER being assigned."""
    is_party = ApplicationParty.objects.filter(
        application=application, user=acting_officer.user
    ).exists()
    if is_party:
        raise SeparationOfDutiesError(
            f"Officer {acting_officer.user.username} is a party to "
            f"{application.application_number} and cannot review it."
        )


def _assert_prior_milestones_cleared(instance: MilestoneInstance) -> None:
    """
    AC-29 — generic across every stream, including the re-erection DEMO
    step and the S1 combined Estate-Officer-then-Junior-Planner clock.
    Uses StreamMilestone.sequence_order, never a hardcoded per-stream if/elif
    chain (which is exactly the kind of special-casing TDD §11 rejected a
    state-machine library in favour of avoiding).
    """
    current_sm = StreamMilestone.objects.get(
        stream=instance.application.stream, milestone=instance.milestone
    )
    earlier = StreamMilestone.objects.filter(
        stream=instance.application.stream, sequence_order__lt=current_sm.sequence_order
    ).order_by("sequence_order")
    for sm in earlier:
        earlier_instance = MilestoneInstance.objects.filter(
            application=instance.application, milestone=sm.milestone
        ).first()
        cleared = earlier_instance and earlier_instance.status in (
            MilestoneInstance.Status.APPROVED, MilestoneInstance.Status.DEEMED_APPROVED,
        )
        if not cleared:
            raise InvalidTransitionError(
                f"Cannot act on {instance.milestone.code}: prior milestone "
                f"{sm.milestone.code} has not been cleared for "
                f"{instance.application.application_number}."
            )


def _advance_to_next_milestone_if_any(approved_instance: MilestoneInstance) -> None:
    """
    Starts the NEXT milestone's clock. This is also where the S1
    Estate-Officer -> Junior-Planner HANDOFF lives conceptually: per PRD
    §9.5/DRD §9 AC2, that handoff is a reassignment WITHIN the same
    MilestoneInstance (same started_at, same combined 21-day clock) — not
    a new instance — so it is handled by assign_officer() below, never by
    this function creating a second S1 instance.
    """
    from apps.milestones.models import StreamMilestone

    application = approved_instance.application
    current_sm = StreamMilestone.objects.get(stream=application.stream, milestone=approved_instance.milestone)
    next_sm = StreamMilestone.objects.filter(
        stream=application.stream, sequence_order=current_sm.sequence_order + 1
    ).first()
    if next_sm is None:
        # This WAS the final milestone (S7, Occupancy Certificate) — application complete.
        application.status = Application.Status.APPROVED
        application.save(update_fields=["status", "updated_at"])
        return

    next_instance, _ = MilestoneInstance.objects.get_or_create(
        application=application, milestone=next_sm.milestone,
        defaults={"status": MilestoneInstance.Status.NOT_STARTED},
    )
    next_instance.status = MilestoneInstance.Status.IN_PROGRESS
    next_instance.started_at = timezone.now()
    next_instance.due_at = compute_due_at(next_instance.started_at, next_sm.sla_working_days)
    next_instance.assigned_officer = _resolve_initial_officer_for(next_sm)
    next_instance.save(update_fields=["status", "started_at", "due_at", "assigned_officer", "updated_at"])

    application.current_milestone_instance = next_instance
    application.status = Application.Status.UNDER_REVIEW
    application.save(update_fields=["current_milestone_instance", "status", "updated_at"])


def assign_officer(*, milestone_instance: MilestoneInstance, officer, actor) -> MilestoneInstance:
    """
    Handles BOTH a fresh assignment and the S1 Estate-Officer -> Junior-
    Planner handoff. Per DRD §9 AC2 / AC-02: never resets started_at or
    due_at — the clock belongs to the MilestoneInstance, not the officer.
    """
    previous = milestone_instance.assigned_officer
    milestone_instance.assigned_officer = officer
    milestone_instance.save(update_fields=["assigned_officer", "updated_at"])
    record_event(
        actor=actor, event_type="officer_reassigned", target=milestone_instance,
        summary=(
            f"{milestone_instance.milestone.code} on "
            f"{milestone_instance.application.application_number} reassigned from "
            f"{previous.user.username if previous else 'unassigned'} to {officer.user.username}."
        ),
    )
    return milestone_instance


def compute_due_at(started_at, sla_working_days):
    """Delegates to the working-day calculator — see Part 7.4."""
    from apps.milestones.workdays import add_working_days
    if sla_working_days is None:
        return None   # SLA value not yet sourced from ConfigParameter — see Part 18; sweep skips instances with due_at=None
    return add_working_days(started_at, sla_working_days)


def _resolve_initial_officer_for(stream_milestone: StreamMilestone):
    """
    PROVISIONAL per DRD §5 — currently assumes one officer per role
    (zone/stream_specialisation ignored). See Part 18. Returns the single
    OfficerProfile for the milestone's first-in-chain role, or None if
    unassigned (a valid, queryable state — DRD §9 AC3).
    """
    from apps.identity.models import OfficerProfile
    role = stream_milestone.milestone.code  # placeholder mapping — real role-per-milestone
    # comes from the MILESTONE_CHAIN-equivalent seed data (Part 15.3), not
    # hardcoded here; this function reads that seeded mapping rather than
    # re-encoding PRD Appendix §17.1's table a second time in Python.
    from apps.milestones.seed_data import MILESTONE_ROLE_MAP
    role_code = MILESTONE_ROLE_MAP.get(role)
    return OfficerProfile.objects.filter(role=role_code).first() if role_code else None
```

**Adversarial checks this single function discharges (cross-referenced to Part 2):** AC-02 (row lock + status guard), AC-08 (callers must resolve `acting_officer` via the permission layer in Part 8.3, which itself is selector-filtered — this function trusts its caller exactly as much as that selector earns), AC-09 (separation-of-duties checked at decision time), AC-18 (the OC exclusion lives in the SLA sweep, Part 7.4, not here — `transition_milestone()` handles *officer-initiated* decisions; deemed clearance is a *separate*, intentionally distinct code path so the two can be reasoned about independently), AC-29 (generic prior-milestone check, parametrized test in Part 11.2).

### 7.3 `apps/milestones/selectors.py` — officer queues (IDOR-proof by construction)

**Traces to:** PRD §10.7 ("only ever sees applications currently sitting at a Milestone their role is responsible for"); covers AC-08.

```python
# apps/milestones/selectors.py
"""
AC-08: list/queue selectors are the ONLY way an officer's queue is ever
fetched. The defining property is that they filter at the QUERY level —
there is no code path where "fetch everything, then filter in Python/the
view" could accidentally leak a row before the filter runs.
"""
from django.db.models import QuerySet
from apps.milestones.models import MilestoneInstance


def officer_queue(*, officer) -> QuerySet[MilestoneInstance]:
    """The officer's 'to verify' inbox — PRD §10.7."""
    return (
        MilestoneInstance.objects.select_related("application", "milestone")
        .filter(assigned_officer=officer, status=MilestoneInstance.Status.IN_PROGRESS)
        .order_by("due_at")
    )


def officer_returned_queue(*, officer) -> QuerySet[MilestoneInstance]:
    return MilestoneInstance.objects.select_related("application", "milestone").filter(
        assigned_officer=officer, status=MilestoneInstance.Status.RETURNED_FOR_CORRECTION
    )


def application_milestone_history(*, application) -> QuerySet[MilestoneInstance]:
    """
    Used by Deputy Planner/Chairman views per PRD §7.4/§7.5 ("full visibility
    of everything submitted and any prior officer's findings on the same
    file"). Deliberately unfiltered by officer — any officer with object-
    level permission on this specific application (Part 8.3) sees its full
    history, by design.
    """
    return MilestoneInstance.objects.select_related("milestone", "assigned_officer__user").filter(
        application=application
    ).order_by("started_at")
```

### 7.4 The SLA sweep — `run_sla_sweep` management command

**Traces to:** PRD §9.11, §10.9; TDD §3.2, §11; DRD §9 AC1; covers AC-03, AC-17, AC-18 (the most safety-critical code path in the system).

```python
# apps/milestones/workdays.py
"""
Working-day calculation — research report §7. Uses `workalendar`'s India
support for fixed/astronomical holidays, LAYERED with the DB-driven
Holiday table (apps.applications.models.Holiday) for India's
second/fourth-Saturday rule and any MbPA-port-specific closures workalendar
doesn't know about. due_at is computed ONCE at transition time and stored
(AC-17) — this module is never called on read, only on write.
"""
from datetime import datetime, timedelta
from django.utils import timezone
from workalendar.asia import India


def _is_working_day(date_, holiday_dates: set, second_fourth_saturdays: set) -> bool:
    cal = India()
    if date_.weekday() == 6:               # Sunday
        return False
    if date_ in second_fourth_saturdays:    # India-specific recurring rule
        return False
    if date_ in holiday_dates:              # MbPA/port-specific + DB-seeded national holidays
        return False
    return cal.is_working_day(date_)


def add_working_days(start_at, n: int):
    """
    Returns a UTC-aware datetime, N working days after start_at, evaluated
    in IST calendar-day terms (TDD §6.4 / DRD §20.5: storage is UTC, but
    "is this still today" is an IST question — converting to IST BEFORE
    taking the date avoids the near-midnight mis-bucketing pitfall the
    research flagged: 23:58 IST is still "today" in IST even though it's
    already tomorrow in UTC).
    """
    from apps.applications.models import Holiday

    holiday_dates = set(Holiday.objects.values_list("date", flat=True))
    second_fourth_saturdays = set(
        Holiday.objects.filter(is_second_or_fourth_saturday=True).values_list("date", flat=True)
    )

    current_date = timezone.localtime(start_at).date()
    remaining = n
    while remaining > 0:
        current_date += timedelta(days=1)
        if _is_working_day(current_date, holiday_dates, second_fourth_saturdays):
            remaining -= 1
    # End-of-business-day IST, converted back to UTC for storage.
    naive_eod_ist = datetime.combine(current_date, datetime.min.time()).replace(hour=18, minute=0)
    return timezone.make_aware(naive_eod_ist, timezone.get_current_timezone())
```

```python
# apps/milestones/management/commands/run_sla_sweep.py
"""
Traces to PRD §9.11/§10.9, TDD §3.2/§11. Triggered by plain Linux cron
(TDD's deliberate "boring infrastructure" decision — no Celery, no
APScheduler). This is the single most safety-critical script in the
codebase: AC-18 (the OC milestone must NEVER be deemed-cleared) lives here,
AC-03 (the sweep must not double-fire) lives here, AC-17 (due_at is never
recomputed) is RESPECTED here (read-only against due_at, never rewritten).
"""
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.milestones.models import MilestoneInstance, StreamMilestone
from apps.audit.services import record_event
from apps.complaints.services import raise_system_complaint


class Command(BaseCommand):
    help = "Daily SLA sweep: deems-clear overdue milestones and flags the responsible officer."

    def handle(self, *args, **options):
        from apps.milestones.models import SlaSweepRun   # see AC-03 idempotency log

        run = SlaSweepRun.objects.create(started_at=timezone.now())
        deemed_count = 0

        overdue = MilestoneInstance.objects.filter(
            status=MilestoneInstance.Status.IN_PROGRESS,
            due_at__lt=timezone.now(),
            due_at__isnull=False,   # AC-17 corollary: an instance with no due_at (SLA not yet
                                     # sourced from ConfigParameter, Part 18) is correctly never swept
        ).select_related("application", "milestone", "assigned_officer__user")

        for instance in overdue:
            with transaction.atomic():
                # AC-02/AC-03: lock before re-checking status — a concurrent
                # officer approval between the queryset above and this lock
                # is exactly the race this guards against.
                locked = MilestoneInstance.objects.select_for_update().get(pk=instance.pk)
                if locked.status != MilestoneInstance.Status.IN_PROGRESS:
                    continue   # already decided by an officer or a prior sweep run — idempotent skip

                # AC-18 — GUARD #2 OF 2. Guard #1 is StreamMilestone.deemed_clearance_eligible
                # (seeded False for S7, Part 15.3). This hardcoded check is
                # DELIBERATELY redundant with that flag — see the AC-18 row in
                # Part 2 for why belt-and-suspenders is the right call here,
                # not over-engineering. NEVER remove this check to "simplify"
                # the loop, even if the flag alone seems sufficient.
                if locked.milestone.code == "S7":
                    self.stdout.write(self.style.WARNING(
                        f"{locked.application.application_number} OC milestone is overdue — "
                        f"NOT deemed-clearing (life-safety exclusion, PRD §9.11/TDD §11). "
                        f"Flagging delay only."
                    ))
                    record_event(
                        actor=None, event_type="deemed_clearance_fired", target=locked,
                        summary=(
                            f"OC milestone overdue for {locked.application.application_number} — "
                            f"delay flagged, NOT auto-cleared (terminal milestone exclusion)."
                        ),
                    )
                    raise_system_complaint(
                        application=locked.application, officer=locked.assigned_officer,
                        subject="SLA breach on Occupancy Certificate milestone",
                    )
                    continue

                sm = StreamMilestone.objects.get(stream=locked.application.stream, milestone=locked.milestone)
                if not sm.deemed_clearance_eligible:
                    continue   # respects the flag for any other milestone explicitly marked ineligible

                locked.status = MilestoneInstance.Status.DEEMED_APPROVED
                locked.is_deemed = True
                locked.decided_at = timezone.now()
                locked.save(update_fields=["status", "is_deemed", "decided_at", "updated_at"])

                record_event(
                    actor=None, event_type="deemed_clearance_fired", target=locked,
                    summary=(
                        f"{locked.milestone.code} on {locked.application.application_number} "
                        f"deemed-cleared: SLA breached by "
                        f"{locked.assigned_officer.user.username if locked.assigned_officer else 'unassigned officer'}."
                    ),
                    metadata={"due_at": locked.due_at.isoformat()},
                )
                raise_system_complaint(
                    application=locked.application, officer=locked.assigned_officer,
                    subject=f"SLA breach: {locked.milestone.code}",
                )

                from apps.milestones.services import _advance_to_next_milestone_if_any
                _advance_to_next_milestone_if_any(locked)
                deemed_count += 1

        run.completed_at = timezone.now()
        run.deemed_count = deemed_count
        run.save(update_fields=["completed_at", "deemed_count"])
        self.stdout.write(self.style.SUCCESS(f"SLA sweep complete: {deemed_count} milestone(s) deemed-cleared."))
```

```python
# apps/milestones/models.py (addition — AC-03's idempotency/observability log)
class SlaSweepRun(TimestampedModel):
    """Not a headline DRD entity — a small operational log so a second,
    overlapping cron invocation (AC-03) is detectable, and so an incident
    responder can see exactly when the sweep last ran and what it did."""
    started_at = models.DateTimeField()
    completed_at = models.DateTimeField(null=True, blank=True)
    deemed_count = models.PositiveIntegerField(default=0)
```

**Cron entry** (`infra/cron/sla-sweep`, installed via the deploy script, not by hand on the box):

```
# Runs daily at 02:00 IST (20:30 UTC the previous day). Logged to a file the
# observability stack tails — see Part 14.4's runbook for what "the sweep
# didn't run" looks like and how to safely re-run it (it's idempotent, AC-03).
30 20 * * * cd /opt/mbpa-portal/backend && /opt/mbpa-portal/venv/bin/python manage.py run_sla_sweep >> /var/log/mbpa/sla_sweep.log 2>&1
```

### 7.5 `apps/identity/services.py` — registration, Aadhaar hashing, OTP, login

**Traces to:** PRD §9.3, §10.1, §10.2; DRD §3, §4, §16-17; TDD §7; covers AC-06, AC-07, AC-10, AC-31.

```python
# apps/identity/services.py
"""
hash_aadhaar() is the single function in the entire codebase permitted to
touch a raw Aadhaar number. It is called, the result is stored, and the
raw value is allowed to fall out of scope — it is never logged, never
placed in a JSONField, never passed to record_event(). AC-07/AC-31 depend
on this function being the only chokepoint.
"""
import hashlib
import hmac
import secrets
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.identity.models import User, ApplicantProfile, OtpToken
from apps.common.exceptions import DomainError


def _get_aadhaar_pepper() -> bytes:
    """
    Read at use-time from secrets management, NEVER cached on a settings
    attribute that might get logged in a startup banner or an error trace
    (AC-07). In production this resolves to a real secret-store read; the
    env-var indirection here is the TDD §15-consistent "no dedicated
    secrets manager at this scale" stance — see Part 13.4 for the rotation
    procedure this design has to support.
    """
    import os
    pepper = os.environ.get(settings.AADHAAR_PEPPER_ENV_VAR)
    if not pepper:
        raise DomainError("AADHAAR_HMAC_PEPPER is not configured — refusing to hash Aadhaar without it.")
    return pepper.encode("utf-8")


def hash_aadhaar(raw_aadhaar: str) -> tuple[str, str]:
    """
    Returns (hash_hex, last4). HMAC-SHA256, NOT plain SHA-256 — a keyed
    hash is what makes the 10^12 input space (AC-07) infeasible to brute-
    force offline without the pepper, while remaining DETERMINISTIC (same
    input -> same output) so dedup still works. A per-row random salt was
    explicitly rejected (DRD §4 AC) precisely because it would break that
    determinism and defeat dedup entirely.
    """
    digits = "".join(c for c in raw_aadhaar if c.isdigit())
    if len(digits) != 12:
        raise DomainError("Aadhaar number must be exactly 12 digits.")
    digest = hmac.new(_get_aadhaar_pepper(), digits.encode("utf-8"), hashlib.sha256).hexdigest()
    return digest, digits[-4:]


def check_aadhaar_dedup(aadhaar_hash: str) -> ApplicantProfile | None:
    """
    DRD §4: deliberately NOT a DB UNIQUE constraint — returns the existing
    profile (if any) so the CALLER can decide how to respond (block +
    notify, per PRD §9.3/§10.1) rather than letting a raw IntegrityError
    surface to a citizen as an ugly 500.
    """
    return ApplicantProfile.objects.filter(aadhaar_hash=aadhaar_hash).select_related("user").first()


@transaction.atomic
def register_applicant(*, email, username, password, full_name, mobile, raw_aadhaar) -> User:
    """Traces to PRD §9.3. AC-07 boundary: raw_aadhaar exists in this
    function's local scope only, for the duration of one hash_aadhaar() call."""
    aadhaar_hash, last4 = hash_aadhaar(raw_aadhaar)

    existing = check_aadhaar_dedup(aadhaar_hash)
    if existing is not None:
        from apps.notifications.services import send_email
        send_email(
            to=existing.user.email,
            template="aadhaar_reuse_alert",   # PRD §9.3's fraud-safeguard email
            context={"existing_username": existing.user.username},
        )
        raise DomainError(
            "An account already exists against this Aadhaar number. "
            "The registered email has been notified."
        )

    user = User.objects.create_user(
        email=email, username=username, password=password, user_type=User.UserType.APPLICANT,
    )
    ApplicantProfile.objects.create(
        user=user, full_name=full_name, mobile=mobile,
        aadhaar_hash=aadhaar_hash, aadhaar_last4=last4,
        aadhaar_verified_at=None,   # set later by the UIDAI offline-KYC verification step, TDD §7 — not this function
    )
    return user
    # NOTE: raw_aadhaar and digits inside hash_aadhaar() are now unreachable —
    # Python's GC will collect them; no explicit del is needed for correctness,
    # but see Part 13.4 for why we additionally avoid ever putting them in a
    # debugger-inspectable long-lived frame (i.e. don't refactor this into a
    # generator or anything that keeps the frame alive across a yield).
```

```python
# apps/identity/services.py (continued) — OTP issuance/verification, AC-06
def _hash_code(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def request_otp(*, email: str, purpose: str, user=None) -> OtpToken:
    code = f"{secrets.randbelow(10**6):06d}"
    token = OtpToken.objects.create(
        user=user, email=email, code_hash=_hash_code(code), purpose=purpose,
        expires_at=timezone.now() + timezone.timedelta(seconds=settings.OTP_TTL_SECONDS),
    )
    from apps.notifications.services import send_email
    send_email(to=email, template=f"otp_{purpose}", context={"code": code})  # AC-23 failure handling lives in send_email
    return token


def verify_otp(*, token_id: int, submitted_code: str) -> OtpToken:
    """AC-06: capped attempts, hashed comparison, hashed storage."""
    token = OtpToken.objects.select_for_update().get(pk=token_id)
    if token.consumed_at is not None:
        raise DomainError("This code has already been used.")
    if timezone.now() > token.expires_at:
        raise DomainError("This code has expired — request a new one.")
    if token.attempt_count >= settings.OTP_MAX_ATTEMPTS:
        raise DomainError("Too many incorrect attempts — request a new code.")

    if not hmac.compare_digest(_hash_code(submitted_code), token.code_hash):
        token.attempt_count += 1
        token.save(update_fields=["attempt_count"])
        raise DomainError("Incorrect code.")

    token.consumed_at = timezone.now()
    token.save(update_fields=["consumed_at"])
    return token
```

```python
# apps/identity/services.py (continued) — role-based session TTL, AC-10
def login_issue_session(request, user) -> None:
    """
    PRD §16/TDD §6.4: 45-min applicant sessions, 6-hour officer sessions.
    set_expiry() is enforced SERVER-SIDE by Django's session framework —
    AC-10's guarantee holds regardless of what a client does with the cookie,
    because Django checks session expiry against its own store on every
    request, not against client-reported time.
    """
    from django.contrib.auth import login
    login(request, user)
    ttl = (
        settings.OFFICER_SESSION_TTL_SECONDS
        if user.user_type == User.UserType.OFFICER
        else settings.APPLICANT_SESSION_TTL_SECONDS
    )
    request.session.set_expiry(ttl)
```

### 7.6 `apps/certificates/services.py` — generation & signature verification

**Traces to:** TDD §8; PRD §10.12; covers AC-25.

```python
# apps/certificates/services.py
"""
Two halves: generate_certificate() produces an UNSIGNED pdf for the
officer to sign locally (TDD §8's decision against server-held private
keys); receive_signed_certificate() verifies the signed PDF on return and
is the ONLY code path that may set Certificate.signature_verified=True.
"""
from django.db import transaction
from django.utils import timezone
from pyhanko.pdf_utils.reader import PdfFileReader
from pyhanko.sign.validation import validate_pdf_signature
from pyhanko_certvalidator import ValidationContext

from apps.certificates.models import Certificate
from apps.audit.services import record_event
from apps.common.exceptions import DomainError


@transaction.atomic
def generate_certificate(*, application, milestone_instance, certificate_type: str) -> Certificate:
    """Builds the unsigned PDF (template rendering -> pdf, e.g. via WeasyPrint
    feeding pyHanko's IncrementalPdfFileWriter) and stores it unsigned in R2.
    PDF-template rendering code omitted here as a presentation-layer detail —
    the contract this function guarantees is: a Certificate row in a
    pending-signature state, with an unsigned PDF object key, is returned."""
    from apps.documents.services import store_object   # thin R2 put wrapper, Part 7.8-adjacent

    unsigned_pdf_bytes = _render_certificate_pdf(application, milestone_instance, certificate_type)
    object_key = store_object(
        prefix=f"certificates/unsigned/{application.application_number}",
        filename=f"{certificate_type}.pdf", content=unsigned_pdf_bytes, content_type="application/pdf",
    )
    certificate = Certificate.objects.create(
        application=application, milestone_instance=milestone_instance,
        certificate_type=certificate_type, r2_object_key=object_key, signature_verified=False,
    )
    record_event(
        actor=None, event_type="certificate_issued", target=certificate,
        summary=f"{certificate_type} generated (unsigned) for {application.application_number}.",
    )
    return certificate


@transaction.atomic
def receive_signed_certificate(*, certificate_id: int, signed_pdf_bytes: bytes, signing_officer) -> Certificate:
    """
    AC-25. validate_pdf_signature() against a ValidationContext built from
    the CCA-licensed trust roots (eMudhra/(n)Code/Capricorn chains, loaded
    from a config-managed file, not hardcoded inline). signature_verified
    is ONLY ever set True here, and ONLY if status.bottom_line is True.
    """
    from apps.common.trust_roots import load_cca_trust_roots   # see Part 13.4

    certificate = Certificate.objects.select_for_update().get(pk=certificate_id)
    if certificate.issued_at is not None:
        raise DomainError("This certificate has already been finalized; cannot re-sign.")

    reader = PdfFileReader(__import__("io").BytesIO(signed_pdf_bytes))
    if not reader.embedded_signatures:
        record_event(
            actor=signing_officer.user, event_type="signature_rejected", target=certificate,
            summary="Uploaded PDF contains no embedded signature.",
        )
        raise DomainError("No signature found in the uploaded PDF.")

    vc = ValidationContext(trust_roots=load_cca_trust_roots())
    status = validate_pdf_signature(reader.embedded_signatures[0], vc)

    if not status.bottom_line:
        record_event(
            actor=signing_officer.user, event_type="signature_rejected", target=certificate,
            summary=f"Signature validation failed: {status.pretty_print_details()}",
        )
        raise DomainError(
            "The uploaded signature could not be verified — it may be expired, "
            "from an untrusted CA, or the document may have been modified after signing."
        )

    from apps.documents.services import store_object
    signed_key = store_object(
        prefix=f"certificates/signed/{certificate.application.application_number}",
        filename=f"{certificate.certificate_type}.pdf", content=signed_pdf_bytes, content_type="application/pdf",
    )
    certificate.r2_object_key = signed_key
    certificate.signature_verified = True
    certificate.signed_by = signing_officer
    certificate.dsc_serial_used = signing_officer.dsc_serial or ""
    certificate.issued_at = timezone.now()
    certificate.save(update_fields=[
        "r2_object_key", "signature_verified", "signed_by", "dsc_serial_used", "issued_at", "updated_at",
    ])

    record_event(
        actor=signing_officer.user, event_type="signature_verified", target=certificate,
        summary=f"DSC signature verified for {certificate.certificate_type} on "
                f"{certificate.application.application_number}.",
    )
    return certificate


def _render_certificate_pdf(application, milestone_instance, certificate_type: str) -> bytes:
    """Presentation-layer detail — template + WeasyPrint/ReportLab. Not
    expanded here; the contract is 'returns unsigned PDF bytes'."""
    raise NotImplementedError("Implement per Part 16 Phase 7 — template rendering, not domain logic.")
```

### 7.7 `apps/documents/services.py` — upload, versioning, presigned download

**Traces to:** DRD §10; covers AC-19, AC-20, AC-21, AC-22.

```python
# apps/documents/services.py
import magic   # python-magic — derives type from content, never trusts the client (AC-19)
from django.conf import settings
from django.db import transaction
from apps.documents.models import DocumentUpload, DocumentSlot
from apps.common.exceptions import DomainError


_ALLOWED_MIME_TYPES = {"application/pdf", "image/jpeg", "image/png"}


def store_object(*, prefix: str, filename: str, content: bytes, content_type: str) -> str:
    """Thin wrapper around the default storage backend (R2 via django-storages,
    Part 4.1's STORAGES config). AC-22: the object is written FIRST; only on
    success does the caller create a DB row referencing it."""
    from django.core.files.storage import default_storage
    from django.core.files.base import ContentFile
    import uuid

    key = f"{prefix}/{uuid.uuid4().hex}-{filename}"
    default_storage.save(key, ContentFile(content))   # raises on R2 failure — AC-22: no row written if this raises
    return key


@transaction.atomic
def upload_document(*, application, document_slot_id, milestone_instance, uploaded_by, filename: str, content: bytes) -> DocumentUpload:
    """AC-19 (magic-byte validation), AC-20 (versioning, never overwrite)."""
    if len(content) > settings.DOCUMENT_MAX_UPLOAD_SIZE_BYTES:
        raise DomainError(f"File exceeds the {settings.DOCUMENT_MAX_UPLOAD_SIZE_BYTES} byte limit.")

    detected_type = magic.from_buffer(content, mime=True)
    if detected_type not in _ALLOWED_MIME_TYPES:
        raise DomainError(
            f"File content does not match an allowed type (detected: {detected_type}). "
            f"The filename/declared Content-Type is never trusted for this check (AC-19)."
        )

    document_slot = DocumentSlot.objects.filter(pk=document_slot_id).first() if document_slot_id else None

    # AC-20: find the current max version for this (application, slot) and
    # increment — never overwrite. Ad-hoc uploads (document_slot=None) are
    # always version 1 of their own lineage, keyed by upload identity instead.
    previous_version = (
        DocumentUpload.objects.filter(application=application, document_slot=document_slot, is_deleted=False)
        .order_by("-version").first()
    )
    next_version = (previous_version.version + 1) if previous_version else 1
    if previous_version:
        previous_version.is_deleted = True
        previous_version.save(update_fields=["is_deleted", "updated_at"])   # hidden, never destroyed

    object_key = store_object(
        prefix=f"documents/{application.application_number}", filename=filename,
        content=content, content_type=detected_type,
    )
    return DocumentUpload.objects.create(
        application=application, document_slot=document_slot, milestone_instance=milestone_instance,
        r2_object_key=object_key, original_filename=filename, content_type=detected_type,
        size_bytes=len(content), uploaded_by=uploaded_by, version=next_version,
    )


def get_download_url(document_upload: DocumentUpload) -> str:
    """AC-21: a fresh presigned URL per request, short TTL (Part 4.1's
    querystring_expire=300), never a stored/long-lived link."""
    from django.core.files.storage import default_storage
    return default_storage.url(document_upload.r2_object_key)
```

### 7.8 `apps/complaints/services.py`

**Traces to:** PRD §10.11; covers AC-28.

```python
# apps/complaints/services.py
from django.db import transaction
from apps.complaints.models import Complaint
from apps.audit.services import record_event


@transaction.atomic
def raise_applicant_complaint(*, application, raised_by, subject: str, body: str) -> Complaint:
    """PRD §10.11: "against whichever officer most recently acted on their file" —
    the most-recent-actor lookup happens in the selector layer at display time,
    not stored redundantly on the Complaint row itself (avoids a second source
    of truth that could drift from the actual MilestoneInstance history)."""
    complaint = Complaint.objects.create(
        application=application, origin=Complaint.Origin.APPLICANT_RAISED,
        raised_by=raised_by, subject=subject, body=body,
    )
    record_event(
        actor=raised_by, event_type="complaint_raised", target=complaint,
        summary=f"Applicant complaint raised on {application.application_number}: {subject}",
    )
    return complaint


@transaction.atomic
def raise_system_complaint(*, application, officer, subject: str) -> Complaint:
    """Called from run_sla_sweep (Part 7.4) on every deemed-clearance —
    AC-28: raised_by is None and origin makes that meaningful, not missing data."""
    complaint = Complaint.objects.create(
        application=application, origin=Complaint.Origin.SYSTEM_RAISED,
        raised_by=None, subject=subject,
        body=f"Automatically raised: SLA breach attributed to "
             f"{officer.user.username if officer else 'an unassigned officer'}.",
    )
    record_event(
        actor=None, event_type="complaint_raised", target=complaint,
        summary=f"System-raised complaint on {application.application_number}: {subject}",
    )
    return complaint
```

---

## Part 8 — API Layer (DRF)

### 8.1 URL routing structure

```python
# config/urls.py
from django.contrib import admin
from django.urls import path, include
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from apps.common.views import healthz

urlpatterns = [
    path("admin/", admin.site.urls),   # IP-allowlisted at the reverse-proxy layer — Part 13.4
    path("healthz", healthz),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema")),  # internal-only, Part 13.4
    path("api/identity/", include("apps.identity.urls")),
    path("api/applications/", include("apps.applications.urls")),
    path("api/milestones/", include("apps.milestones.urls")),
    path("api/documents/", include("apps.documents.urls")),
    path("api/fees/", include("apps.fees.urls")),
    path("api/certificates/", include("apps.certificates.urls")),
    path("api/clearances/", include("apps.clearances.urls")),
    path("api/complaints/", include("apps.complaints.urls")),
    path("api/config/", include("apps.config.urls")),   # Stream & Fee Planner's public read endpoints
]
# Everything NOT matching /api/*, /admin/, or /healthz is served by the
# reverse proxy as the built React SPA (TDD §3.3) — there is no Django
# catch-all route here, by design; Django doesn't know the SPA exists.
```

### 8.2 Serializers — read/write split

**Traces to:** research report §4 (`COMPONENT_SPLIT_REQUEST`); covers AC-12.

```python
# apps/applications/serializers.py
from rest_framework import serializers
from apps.applications.models import Application


class ApplicationReadSerializer(serializers.ModelSerializer):
    stream = serializers.CharField(source="stream.code", read_only=True)
    current_milestone_code = serializers.CharField(
        source="current_milestone_instance.milestone.code", read_only=True, default=None
    )

    class Meta:
        model = Application
        fields = [
            "id", "application_number", "stream", "status",
            "current_milestone_code", "plpn", "plot_area_sqm", "proposed_bua_sqm",
            "zonal_rrr", "submitted_at", "created_at",
        ]
        read_only_fields = fields   # belt-and-suspenders — this serializer is NEVER used for writes


class ApplicationCreateSerializer(serializers.Serializer):
    """
    AC-12: explicit allow-list, intake-shaped, not model-shaped. There is
    NO `status`, NO `current_milestone_instance` field here — those change
    ONLY through transition_milestone()/the milestone apis.py action
    endpoints, never through this serializer. This is the concrete
    enforcement of "state-changing fields are never writable through a
    generic serializer" (Part 2, AC-12).
    """
    stream_code = serializers.ChoiceField(choices=[])  # populated from active Stream rows in __init__

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from apps.milestones.models import Stream
        self.fields["stream_code"].choices = list(
            Stream.objects.filter(is_active=True).values_list("code", "display_name")
        )


class ApplicationIntakeDetailSerializer(serializers.Serializer):
    """The 4-part guided intake (PRD §9.4) — applicant & property details,
    site & environmental details, design metrics & concessions, supporting
    documents. Shown here as the design-metrics part; the other three parts
    follow the identical allow-list pattern in the same module."""
    plpn = serializers.CharField(max_length=64)
    plot_area_sqm = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=0)
    proposed_bua_sqm = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=0)
    zonal_rrr = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=0, required=False)
```

```python
# apps/milestones/serializers.py
from rest_framework import serializers
from apps.milestones.models import MilestoneInstance


class MilestoneInstanceReadSerializer(serializers.ModelSerializer):
    milestone_code = serializers.CharField(source="milestone.code", read_only=True)
    milestone_name = serializers.CharField(source="milestone.display_name", read_only=True)
    assigned_officer_name = serializers.CharField(
        source="assigned_officer.user.get_full_name", read_only=True, default=None
    )

    class Meta:
        model = MilestoneInstance
        fields = [
            "id", "application", "milestone_code", "milestone_name", "status",
            "assigned_officer_name", "started_at", "due_at", "decided_at", "is_deemed",
        ]
        read_only_fields = fields


class MilestoneDecisionSerializer(serializers.Serializer):
    """The ONLY way a milestone decision enters the system via the API —
    delegates entirely to transition_milestone(); this serializer validates
    shape, the service validates business rules."""
    action = serializers.ChoiceField(choices=["approve", "return_for_correction", "reject"])
    decision_note = serializers.CharField(required=False, allow_blank=True, max_length=2000)
    correction_reason = serializers.CharField(required=False, allow_blank=True, max_length=2000)
```

### 8.3 Permissions

**Traces to:** TDD §6.2 (deny-by-default); covers AC-08, AC-09.

```python
# apps/milestones/permissions.py
from rest_framework.permissions import BasePermission
from apps.applications.models import ApplicationParty


class IsAssignedOfficer(BasePermission):
    """AC-08: object-level check — the LIST view is already selector-filtered
    (Part 7.3), so this only needs to guard the DETAIL/decision endpoints
    against a guessed/incremented ID."""
    message = "You are not the officer currently assigned to this milestone."

    def has_object_permission(self, request, view, obj):
        officer_profile = getattr(request.user, "officer_profile", None)
        return officer_profile is not None and obj.assigned_officer_id == officer_profile.id


class IsOfficerRole(BasePermission):
    """Factory-style: IsOfficerRole('chairman') for endpoints restricted to one role."""

    def __init__(self, role: str):
        self.role = role

    def __call__(self):
        return self

    def has_permission(self, request, view):
        officer_profile = getattr(request.user, "officer_profile", None)
        return officer_profile is not None and officer_profile.role == self.role


class IsNotPartyToApplication(BasePermission):
    """
    AC-09 — a PERMISSION-layer mirror of transition_milestone()'s own
    internal check. Deliberately redundant: the service raises
    SeparationOfDutiesError regardless, but failing fast at the permission
    layer means a violation never even reaches the business logic, and
    produces a clean 403 rather than relying solely on the 409 from the
    service-layer exception handler.
    """
    message = "You are a party to this application and cannot act on it."

    def has_object_permission(self, request, view, obj):
        officer_profile = getattr(request.user, "officer_profile", None)
        if officer_profile is None:
            return True   # not an officer at all — a different permission class handles that
        application = obj.application if hasattr(obj, "application") else obj
        return not ApplicationParty.objects.filter(application=application, user=request.user).exists()
```

```python
# apps/applications/permissions.py
from rest_framework.permissions import BasePermission
from apps.applications.models import ApplicationParty


class IsPartyToApplication(BasePermission):
    """Applicant-side equivalent of AC-08 — an applicant may only ever see
    their OWN application's detail, never another's by guessing an ID."""

    def has_object_permission(self, request, view, obj):
        return ApplicationParty.objects.filter(application=obj, user=request.user).exists()
```

### 8.4 Views — representative slice

```python
# apps/milestones/apis.py
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from drf_spectacular.utils import extend_schema

from apps.milestones.selectors import officer_queue, officer_returned_queue
from apps.milestones.serializers import MilestoneInstanceReadSerializer, MilestoneDecisionSerializer
from apps.milestones.services import transition_milestone, TransitionAction
from apps.milestones.permissions import IsAssignedOfficer, IsNotPartyToApplication
from apps.milestones.models import MilestoneInstance
from apps.common.exceptions import DomainError


class OfficerQueueView(APIView):
    """PRD §10.7: 'an inbox of applications to verify'. officer_queue() is
    selector-filtered (AC-08) — there is no unfiltered branch in this view."""
    permission_classes = [IsAuthenticated]

    @extend_schema(responses=MilestoneInstanceReadSerializer(many=True))
    def get(self, request):
        officer = request.user.officer_profile
        queryset = officer_queue(officer=officer)
        return Response(MilestoneInstanceReadSerializer(queryset, many=True).data)


class OfficerReturnedQueueView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        officer = request.user.officer_profile
        queryset = officer_returned_queue(officer=officer)
        return Response(MilestoneInstanceReadSerializer(queryset, many=True).data)


class MilestoneDecisionView(APIView):
    """
    The ONLY HTTP-facing endpoint that can change a MilestoneInstance's
    status — covers AC-12 (no generic PATCH exists for this model at all;
    it is intentionally absent from urls.py, not merely under-permissioned).
    """
    permission_classes = [IsAuthenticated, IsAssignedOfficer, IsNotPartyToApplication]

    def get_object(self):
        from django.shortcuts import get_object_or_404
        obj = get_object_or_404(MilestoneInstance, pk=self.kwargs["pk"])
        self.check_object_permissions(self.request, obj)
        return obj

    @extend_schema(request=MilestoneDecisionSerializer, responses=MilestoneInstanceReadSerializer)
    def post(self, request, pk):
        instance = self.get_object()
        serializer = MilestoneDecisionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            updated = transition_milestone(
                milestone_instance_id=instance.pk,
                action=serializer.validated_data["action"],
                acting_officer=request.user.officer_profile,
                decision_note=serializer.validated_data.get("decision_note", ""),
                correction_reason=serializer.validated_data.get("correction_reason", ""),
            )
        except DomainError:
            raise   # converted to a clean 409 by config.REST_FRAMEWORK["EXCEPTION_HANDLER"], Part 4.1

        return Response(MilestoneInstanceReadSerializer(updated).data)
```

```python
# apps/identity/apis.py — representative auth slice
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from rest_framework.throttling import ScopedRateThrottle

from apps.identity.services import request_otp, verify_otp, login_issue_session
from apps.common.exceptions import DomainError


class OtpRequestView(APIView):
    permission_classes = [AllowAny]   # explicit public exception (TDD §6.2), not an omission
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "otp-request"   # Part 4.1's DEFAULT_THROTTLE_RATES — AC-06

    def post(self, request):
        token = request_otp(email=request.data["email"], purpose="login")
        return Response({"otp_id": token.pk}, status=201)


class OtpVerifyAndLoginView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "otp-verify"

    def post(self, request):
        try:
            token = verify_otp(token_id=request.data["otp_id"], submitted_code=request.data["code"])
        except DomainError as e:
            return Response({"error": str(e)}, status=400)
        login_issue_session(request, token.user)   # AC-10: server-side TTL, role-based
        return Response({"role": token.user.user_type})
```

### 8.5 Throttling configuration

Already shown in `REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]` (Part 4.1) — rates are intentionally conservative (5/min on OTP request/verify) given AC-06's brute-force concern; revisit only with real usage data, never loosen "to make testing easier" without a corresponding test-environment override in `config/settings/test.py`.

### 8.6 `drf-spectacular` annotation pattern

Every non-trivial endpoint uses `@extend_schema` (as shown above) rather than relying on auto-inference alone — particularly for the `MilestoneDecisionView`, where the request/response shape genuinely can't be inferred from a `ModelSerializer` (there isn't one backing this view, by design). The generated schema feeds `openapi-typescript` for the frontend (Part 3.4) — if `manage.py spectacular --validate` ever errors or warns, that's a CI-blocking issue (Part 12.1), not a warning to ignore, because a silently-wrong schema is exactly how the "API contract drift" risk (TDD §6.3) re-enters the system.

---

## Part 9 — Authentication & Session Implementation

### 9.1 The three-credential login, formalized

**Traces to:** the prototype's `loginRequest_()` (email+username+password, three checked fields before OTP) + PRD's "two-factor" framing (password + OTP) — both are accurate at different levels of abstraction, as established in this project's earlier cross-verification pass. The implementation below preserves the prototype's literal three-field check while the PRD's "two-factor" language describes the security *property* (something-you-know + something-you-have).

```python
# apps/identity/apis.py (continued)
from django.contrib.auth import authenticate


class LoginRequestView(APIView):
    """Step 1: email + username + password -> issues an OTP if all three match."""
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "login"

    def post(self, request):
        email = request.data.get("email", "").strip().lower()
        username = request.data.get("username", "").strip()
        password = request.data.get("password", "")

        from apps.identity.models import User
        user = User.objects.filter(email__iexact=email, username__iexact=username).first()
        # Deliberately generic error message regardless of WHICH check failed
        # (email not found vs. username mismatch vs. bad password) — avoids
        # leaking which accounts exist, same posture as django-axes' default.
        generic_error = Response({"error": "Email, username and password do not match an account."}, status=400)
        if user is None:
            return generic_error
        if not authenticate(request, username=user.username, password=password):
            return generic_error

        token = request_otp(email=user.email, purpose="login", user=user)
        return Response({"otp_id": token.pk, "email_masked": _mask_email(user.email)})


def _mask_email(email: str) -> str:
    name, _, domain = email.partition("@")
    return f"{name[:2]}{'*' * max(len(name) - 2, 1)}@{domain}"
```

### 9.2 Role-based idle-timeout middleware

**Traces to:** TDD §6.4; covers AC-10 (the inactivity half — `set_expiry()` in Part 7.5 covers the absolute-age half).

```python
# apps/identity/middleware.py
"""
set_expiry() (Part 7.5) caps the SESSION'S TOTAL AGE. This middleware
additionally enforces IDLE timeout — an officer who is active continuously
for 5 hours should not be silently logged out mid-task at the 6-hour mark
if they were idle for most of that window in a way that matters; conversely
a session idle for 45+ minutes should expire even if its absolute age
hasn't been reached yet. Both checks matter; this is the idle half.
"""
from django.utils import timezone
from django.contrib.auth import logout
from django.conf import settings


class IdleTimeoutMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            last_activity = request.session.get("last_activity")
            ttl = (
                settings.OFFICER_SESSION_TTL_SECONDS
                if getattr(request.user, "user_type", None) == "officer"
                else settings.APPLICANT_SESSION_TTL_SECONDS
            )
            now_ts = timezone.now().timestamp()
            if last_activity is not None and (now_ts - last_activity) > ttl:
                logout(request)
            else:
                request.session["last_activity"] = now_ts
        return self.get_response(request)
```

### 9.3 CSRF bootstrap endpoint

**Traces to:** research report §3; covers AC-11.

```python
# apps/common/apis.py
from django.middleware.csrf import get_token
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response


@api_view(["GET"])
@permission_classes([AllowAny])
def csrf_bootstrap(request):
    """The SPA calls this once on load to ensure the csrftoken cookie is
    set before it ever attempts a mutating request. get_token() forces
    Django to set the cookie on this response if it isn't already present."""
    get_token(request)
    return Response({"detail": "CSRF cookie set."})
```

### 9.4 React API client — CSRF header + 403 retry

```typescript
// frontend/src/api/client.ts
/**
 * Traces to TDD §6.3 ("React must explicitly fetch and attach the CSRF
 * header; nothing does this automatically"). Same-origin (TDD §3.3), so
 * credentials: "include" is technically redundant but kept explicit —
 * AC-11 favors being explicit about a security-relevant default over
 * relying on the browser's same-origin behavior implicitly.
 */
function getCookie(name: string): string | null {
  const match = document.cookie.match(new RegExp(`(^| )${name}=([^;]+)`));
  return match ? decodeURIComponent(match[2]) : null;
}

async function apiFetch(path: string, options: RequestInit = {}): Promise<Response> {
  const isMutating = ["POST", "PUT", "PATCH", "DELETE"].includes((options.method || "GET").toUpperCase());
  const headers = new Headers(options.headers);
  headers.set("Content-Type", "application/json");
  if (isMutating) {
    const csrfToken = getCookie("csrftoken");
    if (csrfToken) headers.set("X-CSRFToken", csrfToken);
  }

  let response = await fetch(`/api${path}`, { ...options, headers, credentials: "include" });

  // CSRF tokens can rotate (e.g. on login) — a single transparent retry
  // after re-bootstrapping covers that case rather than surfacing a
  // confusing 403 to the user for what is really a stale-token issue.
  if (response.status === 403 && isMutating) {
    await fetch("/api/csrf/", { credentials: "include" });
    headers.set("X-CSRFToken", getCookie("csrftoken") ?? "");
    response = await fetch(`/api${path}`, { ...options, headers, credentials: "include" });
  }
  return response;
}

export { apiFetch };
```

---

## Part 10 — Frontend Architecture

**Traces to:** TDD §4.3–§4.5; PRD §7 (two distinct user-facing experiences); research report's frontend-design conventions.

### 10.1 Route tree — applicant vs officer, protected by role

```typescript
// frontend/src/App.tsx
import { createBrowserRouter, RouterProvider } from "react-router-dom";
import { RequireAuth } from "./routes/RequireAuth";
import { RequireRole } from "./routes/RequireRole";

const router = createBrowserRouter([
  // PUBLIC — no login required, matching PRD §10.3's explicit intent
  // (the prototype's accidental login-gating of the Planner is NOT repeated here)
  { path: "/", element: <PublicLanding /> },
  { path: "/planner", element: <StreamFeePlanner /> },
  { path: "/know-your-status", element: <KnowYourStatus /> },
  { path: "/login", element: <Login /> },
  { path: "/register", element: <Register /> },

  // APPLICANT — requires auth, user_type=applicant
  {
    path: "/app",
    element: <RequireAuth><RequireRole role="applicant"><ApplicantLayout /></RequireRole></RequireAuth>,
    children: [
      { path: "applications", element: <MyApplications /> },
      { path: "applications/new", element: <NewApplicationWizard /> },
      { path: "applications/:id", element: <ApplicationDetail /> },
    ],
  },

  // OFFICER — requires auth, user_type=officer; role-specific views further
  // gated client-side for UX (the REAL gate is server-side, Part 8.3 — this
  // is purely "don't show a Chairman a Junior Planner's queue", not security)
  {
    path: "/officer",
    element: <RequireAuth><RequireRole role="officer"><OfficerLayout /></RequireRole></RequireAuth>,
    children: [
      { path: "queue", element: <ReviewQueue /> },
      { path: "applications/:id", element: <OfficerApplicationDetail /> },
      { path: "complaints", element: <ComplaintQueues /> },
    ],
  },
]);

export default function App() {
  return <RouterProvider router={router} />;
}
```

**Reminder this is the UX gate, not the security boundary:** every officer-side data fetch still goes through the server-side selectors/permissions in Parts 7.3/8.3. A client-side route guard prevents a confusing UI, not a real access-control bypass — this distinction should be a comment at the top of `RequireRole.tsx` so nobody mistakes it for the actual control.

### 10.2 State management approach

- **Server state** (applications, milestones, queues): **TanStack Query** (`@tanstack/react-query`) — not Redux. This system has almost no client-only state that isn't a direct reflection of server data; a cache-and-refetch library fits better than a global store, and it gives free request de-duplication, which matters once the officer queue and application-detail views are polled/refetched on every milestone decision.
- **Local UI state** (wizard step, form drafts): plain `useState`/`useReducer`, kept component-local. No global state library needed for this.
- **Forms:** React Hook Form + a schema derived from the same OpenAPI types used elsewhere (Part 3.4) — so a form's validation shape and the backend serializer's shape can never silently diverge for long without a type error surfacing at build time.

### 10.3 Component conventions

- `components/ui/` — shadcn/ui primitives, generated via the shadcn CLI, never hand-edited beyond what the CLI produces (keeps future `shadcn update` runs clean).
- `components/domain/` — composed, business-meaningful components: `MilestoneTimeline` (renders the 7-stage/stream-specific sequence with current position highlighted — PRD §10.6's "precisely which Milestone they are on"), `FeeBreakdown` (renders a `FeeAssessment` with each line item labeled, never a single opaque total — PRD §10.5's "never discovers a hidden cost"), `DocumentSlotChecklist`, `ConditionalClearanceWizard` (the 7-question NOC flow, Handoff §2.3/§6.6).
- Reference `/mnt/skills/public/frontend-design/SKILL.md`'s design-token guidance for visual treatment (color, type, spacing) so the result doesn't read as a templated default — this matters specifically because the TDD's stated visual-quality goal (§4.3, avoiding "ancient government portal" impression) was a deliberate, researched decision, not a throwaway preference.

### 10.4 Accessibility — WCAG 2.1 AA baked into the conventions, not bolted on after

**Traces to:** TDD §13; research report §15 (GIGW 3.0).

- Every `components/ui/` primitive from shadcn/ui already ships with Radix's accessibility primitives (focus management, ARIA roles) — **do not** strip these out for a "simpler" custom implementation.
- Every form field has a programmatically associated `<label>` (not just placeholder text — PRD's intake forms are long, and placeholder-as-label is a common WCAG failure).
- Color is never the *only* signal for status (a returned-for-correction milestone gets an icon + text label, not just a red badge) — relevant given `MilestoneTimeline`'s whole purpose is status-at-a-glance.
- Keyboard navigation and visible focus states are part of the Definition of Done for any new interactive component (Part 1.2) — not a separate "accessibility pass" scheduled for later (Part 16 Phase 11 still includes a dedicated audit pass, but that's a *verification* step, not where accessibility first gets considered).
- Automated checks (`axe-core` via `@axe-core/playwright` or similar) run in CI against key pages (Part 12.1) as a baseline; this catches maybe 30-40% of real WCAG issues and is a floor, not a substitute for the manual NVDA/JAWS/VoiceOver pass the research report recommends before the GIGW audit (Part 16 Phase 12).

---

## Part 11 — Testing Strategy (Concrete)

**Traces to:** TDD §14 ("Django/DRF built-in `TestCase`/`APITestCase` + factory_boy — zero new dependencies"); research report §13.

### 11.1 Test directory structure & factories

Each app's `factories.py` provides a `factory_boy` factory per model, used by every test in that app and freely imported by other apps' tests (e.g. `apps/milestones/tests/` imports `ApplicationFactory` from `apps.applications.factories`).

```python
# apps/applications/factories.py
import factory
from factory.django import DjangoModelFactory
from apps.applications.models import Application, ApplicationParty
from apps.identity.factories import UserFactory
from apps.milestones.factories import StreamFactory


class ApplicationFactory(DjangoModelFactory):
    class Meta:
        model = Application

    stream = factory.SubFactory(StreamFactory)
    status = Application.Status.DRAFT
    plpn = factory.Sequence(lambda n: f"PLPN {n}/{n+100}")
    plot_area_sqm = factory.Faker("pydecimal", left_digits=4, right_digits=2, positive=True)
    proposed_bua_sqm = factory.Faker("pydecimal", left_digits=4, right_digits=2, positive=True)

    @factory.post_generation
    def application_number(self, create, extracted, **kwargs):
        if create and not self.application_number:
            from apps.applications.services import generate_application_number
            self.application_number = generate_application_number()
            self.save(update_fields=["application_number"])


class ApplicationPartyFactory(DjangoModelFactory):
    class Meta:
        model = ApplicationParty

    application = factory.SubFactory(ApplicationFactory)
    user = factory.SubFactory(UserFactory)
    party_role = ApplicationParty.PartyRole.OWNER
    is_account_of_record = True
```

```python
# apps/identity/factories.py
import factory
from factory.django import DjangoModelFactory
from apps.identity.models import User, OfficerProfile, ApplicantProfile


class UserFactory(DjangoModelFactory):
    class Meta:
        model = User

    username = factory.Sequence(lambda n: f"user{n}")
    email = factory.Sequence(lambda n: f"user{n}@example.test")
    user_type = User.UserType.APPLICANT


class OfficerFactory(DjangoModelFactory):
    class Meta:
        model = OfficerProfile

    user = factory.SubFactory(UserFactory, user_type=User.UserType.OFFICER)
    role = OfficerProfile.Role.JUNIOR_PLANNER


class ApplicantProfileFactory(DjangoModelFactory):
    class Meta:
        model = ApplicantProfile

    user = factory.SubFactory(UserFactory)
    full_name = factory.Faker("name")
    mobile = factory.Faker("numerify", text="##########")
    aadhaar_hash = factory.Sequence(lambda n: f"testhash{n:050d}")
    aadhaar_last4 = factory.Sequence(lambda n: f"{n:04d}"[-4:])
```

### 11.2 Unit tests — the domain engine

**(a) Fee calculation — `Decimal` edge cases, AC-16/AC-30**

```python
# apps/fees/tests/test_services.py
from decimal import Decimal
from django.test import TestCase
from apps.applications.factories import ApplicationFactory
from apps.config.factories import ConfigParameterFactory
from apps.fees.services import assess_fee, reassess_fee
from apps.fees.models import FeeAssessment


class FeeAssessmentTests(TestCase):
    def setUp(self):
        ConfigParameterFactory(key="scrutiny_fee_per_sqm", value="50.00", version=1)
        ConfigParameterFactory(key="security_deposit_per_sqm", value="10.00", version=1)
        ConfigParameterFactory(key="debris_deposit_per_sqm", value="20.00", version=1)
        ConfigParameterFactory(key="premium_coefficient.additional_fsi", value="1.10", version=1)
        ConfigParameterFactory(key="benchmark.additional_fsi", value="1.50", version=1)
        self.application = ApplicationFactory(
            proposed_bua_sqm=Decimal("1000.00"), zonal_rrr=Decimal("25000.00")
        )

    def test_base_fees_computed_correctly_against_bua(self):
        assessment = assess_fee(application=self.application, concessions=[])
        self.assertEqual(assessment.scrutiny_fee, Decimal("50000.00"))
        self.assertEqual(assessment.security_deposit, Decimal("10000.00"))
        self.assertEqual(assessment.debris_deposit, Decimal("20000.00"))
        self.assertEqual(assessment.master_challan_total, Decimal("80000.00"))

    def test_concession_premium_uses_configured_coefficient_not_a_hardcoded_one(self):
        assessment = assess_fee(
            application=self.application,
            concessions=[{"concession_type": "additional_fsi", "delta_area": "200", "source": "self_declared"}],
        )
        # 200 * 25000 * 1.10 = 5,500,000.00
        self.assertEqual(assessment.total_concession_premium, Decimal("5500000.00"))

    def test_amounts_are_decimal_never_float(self):
        assessment = assess_fee(application=self.application, concessions=[])
        for field in ("scrutiny_fee", "security_deposit", "debris_deposit", "master_challan_total"):
            self.assertIsInstance(getattr(assessment, field), Decimal)

    def test_config_version_is_snapshotted_on_the_assessment(self):
        assessment = assess_fee(application=self.application, concessions=[])
        self.assertEqual(assessment.config_version, 1)

    def test_rate_change_after_assessment_does_not_alter_the_existing_row(self):
        """AC-16 — the single most important test in this file."""
        assessment = assess_fee(application=self.application, concessions=[])
        original_total = assessment.master_challan_total

        ConfigParameterFactory(key="scrutiny_fee_per_sqm", value="999.00", version=2)  # rate "changes"

        assessment.refresh_from_db()
        self.assertEqual(assessment.master_challan_total, original_total)  # UNCHANGED

    def test_locked_assessment_cannot_be_mutated_directly(self):
        assessment = assess_fee(application=self.application, concessions=[])
        assessment.is_locked = True
        assessment.save(update_fields=["is_locked"])

        assessment.scrutiny_fee = Decimal("1.00")
        with self.assertRaises(Exception):  # ValidationError, raised by FeeAssessment.save()
            assessment.save()

    def test_editing_bua_after_assessment_creates_a_new_row_not_a_mutation(self):
        """AC-30."""
        first = assess_fee(application=self.application, concessions=[])
        self.application.proposed_bua_sqm = Decimal("2000.00")
        self.application.save()

        second = reassess_fee(application=self.application, concessions=[])
        self.assertNotEqual(first.pk, second.pk)
        first.refresh_from_db()
        self.assertEqual(first.scrutiny_fee, Decimal("50000.00"))  # the OLD row is untouched
```

**(b) SLA sweep with `freezegun` — working-day math, AC-17, AC-18**

```python
# apps/milestones/tests/test_sla_sweep.py
from datetime import datetime
from freezegun import freeze_time
from django.test import TestCase
from django.core.management import call_command
from django.utils import timezone

from apps.applications.factories import ApplicationFactory
from apps.milestones.factories import MilestoneInstanceFactory, StreamMilestoneFactory
from apps.milestones.models import MilestoneInstance
from apps.audit.models import AuditEvent


class SlaSweepTests(TestCase):
    def test_overdue_milestone_is_deemed_approved(self):
        application = ApplicationFactory()
        sm = StreamMilestoneFactory(
            stream=application.stream, milestone__code="S3", deemed_clearance_eligible=True
        )
        instance = MilestoneInstanceFactory(
            application=application, milestone=sm.milestone,
            status=MilestoneInstance.Status.IN_PROGRESS,
            due_at=timezone.now() - timezone.timedelta(days=1),   # already overdue
        )
        call_command("run_sla_sweep")
        instance.refresh_from_db()
        self.assertEqual(instance.status, MilestoneInstance.Status.DEEMED_APPROVED)
        self.assertTrue(instance.is_deemed)
        self.assertTrue(
            AuditEvent.objects.filter(event_type="deemed_clearance_fired", target_id=str(instance.pk)).exists()
        )

    def test_not_yet_due_milestone_is_untouched(self):
        instance = MilestoneInstanceFactory(
            status=MilestoneInstance.Status.IN_PROGRESS,
            due_at=timezone.now() + timezone.timedelta(days=1),
        )
        call_command("run_sla_sweep")
        instance.refresh_from_db()
        self.assertEqual(instance.status, MilestoneInstance.Status.IN_PROGRESS)

    def test_occupancy_certificate_milestone_is_NEVER_deemed_approved(self):
        """
        AC-18 — the single most important test in this entire test suite.
        This test must never be deleted, skipped, or weakened, even under
        deadline pressure. If this test is red, do not ship.
        """
        application = ApplicationFactory()
        sm = StreamMilestoneFactory(
            stream=application.stream, milestone__code="S7",
            deemed_clearance_eligible=True,   # deliberately set True to prove guard #2 catches it
                                               # even if guard #1 (the seed data) were ever wrong
        )
        instance = MilestoneInstanceFactory(
            application=application, milestone=sm.milestone,
            status=MilestoneInstance.Status.IN_PROGRESS,
            due_at=timezone.now() - timezone.timedelta(days=30),
        )
        call_command("run_sla_sweep")
        instance.refresh_from_db()
        self.assertEqual(
            instance.status, MilestoneInstance.Status.IN_PROGRESS,
            "An Occupancy Certificate milestone was deemed-approved by the SLA sweep. "
            "This means a building could be occupied without inspection. STOP and "
            "investigate immediately — see Part 2, AC-18.",
        )
        self.assertFalse(instance.is_deemed)

    @freeze_time("2026-08-14")  # the day before an Independence Day + weekend run
    def test_working_day_calculation_skips_sundays_and_holidays(self):
        from apps.applications.models import Holiday
        from apps.milestones.workdays import add_working_days

        Holiday.objects.create(date="2026-08-15", description="Independence Day")
        start = timezone.make_aware(datetime(2026, 8, 14, 10, 0))
        due = add_working_days(start, 1)   # 15th is a holiday, 16th is a Sunday -> should land on the 17th
        self.assertEqual(due.date().isoformat(), "2026-08-17")

    def test_sweep_is_idempotent_under_a_double_run(self):
        """AC-03."""
        instance = MilestoneInstanceFactory(
            status=MilestoneInstance.Status.IN_PROGRESS,
            due_at=timezone.now() - timezone.timedelta(days=1),
        )
        call_command("run_sla_sweep")
        call_command("run_sla_sweep")   # fires again — must not double-process
        self.assertEqual(
            AuditEvent.objects.filter(event_type="deemed_clearance_fired", target_id=str(instance.pk)).count(), 1
        )
```

**(c) Milestone-transition validation, parametrized across streams — AC-29**

```python
# apps/milestones/tests/test_services.py
from django.test import TestCase
from parameterized import parameterized
from apps.applications.factories import ApplicationFactory
from apps.identity.factories import OfficerFactory
from apps.milestones.services import transition_milestone, TransitionAction
from apps.milestones.factories import MilestoneInstanceFactory, StreamMilestoneFactory
from apps.milestones.models import MilestoneInstance
from apps.common.exceptions import InvalidTransitionError, SeparationOfDutiesError


class MilestoneSequencingTests(TestCase):

    @parameterized.expand([
        ("new_building",), ("addition",), ("layout",), ("reerection",),
        ("temporary",), ("special",), ("regularise",),
    ])
    def test_cannot_act_on_a_milestone_before_its_predecessor_clears(self, stream_code):
        """AC-29 — ONE test, parametrized across every stream, because
        _assert_prior_milestones_cleared() is generic, not per-stream."""
        application = ApplicationFactory(stream__code=stream_code)
        officer = OfficerFactory()
        # second-in-sequence instance, predecessor still NOT_STARTED
        sm_first = StreamMilestoneFactory(stream=application.stream, sequence_order=1)
        sm_second = StreamMilestoneFactory(stream=application.stream, sequence_order=2)
        MilestoneInstanceFactory(application=application, milestone=sm_first.milestone, status="not_started")
        second_instance = MilestoneInstanceFactory(
            application=application, milestone=sm_second.milestone, status="in_progress"
        )

        with self.assertRaises(InvalidTransitionError):
            transition_milestone(
                milestone_instance_id=second_instance.pk, action=TransitionAction.APPROVE,
                acting_officer=officer,
            )

    def test_separation_of_duties_blocks_an_officer_who_is_a_party(self):
        """AC-09."""
        from apps.applications.factories import ApplicationPartyFactory
        application = ApplicationFactory()
        officer = OfficerFactory()
        ApplicationPartyFactory(application=application, user=officer.user)  # officer IS a party
        instance = MilestoneInstanceFactory(application=application, status="in_progress")

        with self.assertRaises(SeparationOfDutiesError):
            transition_milestone(
                milestone_instance_id=instance.pk, action=TransitionAction.APPROVE, acting_officer=officer,
            )

    def test_approving_an_already_approved_instance_raises_concurrent_modification(self):
        """AC-02, the single-threaded half of the proof — see
        ApplicationNumberConcurrencyTests for the real multi-thread version."""
        from apps.common.exceptions import ConcurrentModificationError
        officer = OfficerFactory()
        instance = MilestoneInstanceFactory(status="approved")

        with self.assertRaises(ConcurrentModificationError):
            transition_milestone(
                milestone_instance_id=instance.pk, action=TransitionAction.APPROVE, acting_officer=officer,
            )
```

**(d) Application-number concurrency — `TransactionTestCase` + real threads, AC-01**

```python
# apps/applications/tests/test_concurrency.py
"""
TransactionTestCase, NOT TestCase — research report §13: TestCase wraps
each test in an outer transaction that breaks select_for_update()'s real
locking semantics across threads (each thread needs its OWN connection,
which only commits/blocks correctly outside TestCase's transaction wrapper).
"""
import threading
from django.test import TransactionTestCase
from apps.applications.services import generate_application_number


class ApplicationNumberConcurrencyTests(TransactionTestCase):
    def test_concurrent_generation_produces_no_duplicates_and_no_gaps(self):
        n_threads = 20
        results: list[str] = []
        lock = threading.Lock()

        def worker():
            number = generate_application_number()   # each call is its own transaction.atomic()
            with lock:
                results.append(number)

        threads = [threading.Thread(target=worker) for _ in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(results), n_threads)
        self.assertEqual(len(set(results)), n_threads, "Duplicate application number generated under concurrency.")

        sequence_numbers = sorted(int(num[-5:]) for num in results)
        self.assertEqual(
            sequence_numbers, list(range(sequence_numbers[0], sequence_numbers[0] + n_threads)),
            "Gap detected in generated application numbers under concurrency.",
        )
```

### 11.3 Integration tests — officer approve/reject workflow through the API

```python
# apps/milestones/tests/test_apis.py
from rest_framework.test import APITestCase
from rest_framework import status
from apps.applications.factories import ApplicationFactory
from apps.identity.factories import OfficerFactory
from apps.milestones.factories import MilestoneInstanceFactory


class OfficerDecisionApiTests(APITestCase):
    def setUp(self):
        self.officer = OfficerFactory()
        self.client.force_login(self.officer.user)   # session-auth, matches production auth path
        self.application = ApplicationFactory()
        self.instance = MilestoneInstanceFactory(
            application=self.application, assigned_officer=self.officer, status="in_progress"
        )

    def test_officer_can_approve_their_assigned_milestone(self):
        response = self.client.post(
            f"/api/milestones/instances/{self.instance.pk}/decide/", {"action": "approve"}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.instance.refresh_from_db()
        self.assertEqual(self.instance.status, "approved")

    def test_officer_cannot_act_on_a_milestone_assigned_to_someone_else(self):
        """AC-08 — proven at the API layer, not just the service layer."""
        other_officer = OfficerFactory()
        other_instance = MilestoneInstanceFactory(assigned_officer=other_officer, status="in_progress")

        response = self.client.post(
            f"/api/milestones/instances/{other_instance.pk}/decide/", {"action": "approve"}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_return_for_correction_requires_a_reason(self):
        response = self.client.post(
            f"/api/milestones/instances/{self.instance.pk}/decide/",
            {"action": "return_for_correction"}, format="json",   # no correction_reason
        )
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)

    def test_unauthenticated_request_is_rejected(self):
        """Deny-by-default, TDD §6.2."""
        self.client.logout()
        response = self.client.post(
            f"/api/milestones/instances/{self.instance.pk}/decide/", {"action": "approve"}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
```

### 11.4 Security-focused tests

```python
# apps/common/tests/test_security_meta.py
"""
'Meta-tests' — they scan the codebase or settings rather than exercise one
function, and exist specifically to keep the AC-xx catalog's guarantees
true over time, not just true on the day each feature shipped.
"""
import ast
import os
from django.test import TestCase, override_settings
from django.conf import settings


class CsrfExemptionAuditTests(TestCase):
    """AC-11: fails the build if a new @csrf_exempt appears anywhere
    without being in the documented allow-list (currently empty)."""
    ALLOWED_CSRF_EXEMPT_FILES: set[str] = set()  # update deliberately, never silently

    def test_no_undocumented_csrf_exempt_views(self):
        offenders = []
        for root, _, files in os.walk(settings.BASE_DIR / "apps"):
            for f in files:
                if not f.endswith(".py"):
                    continue
                path = os.path.join(root, f)
                with open(path) as fh:
                    if "csrf_exempt" in fh.read() and path not in self.ALLOWED_CSRF_EXEMPT_FILES:
                        offenders.append(path)
        self.assertEqual(offenders, [], f"Undocumented @csrf_exempt usage found: {offenders}")


class DenyByDefaultTests(TestCase):
    def test_default_permission_class_is_isauthenticated(self):
        self.assertIn(
            "rest_framework.permissions.IsAuthenticated",
            settings.REST_FRAMEWORK["DEFAULT_PERMISSION_CLASSES"],
        )


class CriticalActionsAreAuditedTests(TestCase):
    """AC-33: every 'consequential' service function must call record_event()."""
    CONSEQUENTIAL_FUNCTIONS = [
        ("apps.milestones.services", "transition_milestone"),
        ("apps.fees.services", "assess_fee"),
        ("apps.certificates.services", "receive_signed_certificate"),
        ("apps.identity.services", "register_applicant"),
    ]

    def test_consequential_functions_call_record_event(self):
        import inspect
        import importlib
        for module_path, func_name in self.CONSEQUENTIAL_FUNCTIONS:
            module = importlib.import_module(module_path)
            source = inspect.getsource(getattr(module, func_name))
            self.assertIn(
                "record_event(", source,
                f"{module_path}.{func_name} does not call record_event() — AC-33 requires it.",
            )
```

```python
# apps/audit/tests/test_db_enforcement.py
"""
AC-13 — the test that actually proves the database boundary, not just the
Python one. Connects using the app's REAL restricted connection (the
'default' alias, per config/db_routers.py) and issues raw SQL.
"""
from django.test import TestCase
from django.db import connections
from django.db.utils import OperationalError, ProgrammingError
from apps.audit.factories import AuditEventFactory


class AuditAppendOnlyDbLevelTests(TestCase):
    def test_raw_sql_update_is_rejected_by_postgres_not_just_django(self):
        event = AuditEventFactory()
        with self.assertRaises((OperationalError, ProgrammingError)):
            with connections["default"].cursor() as cursor:
                cursor.execute(
                    "UPDATE audit_auditevent SET summary = %s WHERE sequence = %s",
                    ["tampered", event.pk],
                )

    def test_raw_sql_delete_is_rejected_by_postgres_not_just_django(self):
        event = AuditEventFactory()
        with self.assertRaises((OperationalError, ProgrammingError)):
            with connections["default"].cursor() as cursor:
                cursor.execute("DELETE FROM audit_auditevent WHERE sequence = %s", [event.pk])

    def test_app_role_cannot_grant_itself_update_back(self):
        """Confirms the restricted role also lacks the privilege to undo its
        own restriction — a role that could re-grant itself UPDATE would make
        the REVOKE theatre, not enforcement."""
        with self.assertRaises((OperationalError, ProgrammingError)):
            with connections["default"].cursor() as cursor:
                cursor.execute("GRANT UPDATE ON audit_auditevent TO app_restricted")
```

### 11.5 Coverage gate

```toml
# pyproject.toml (excerpt)
[tool.coverage.run]
source = ["apps"]
omit = ["*/migrations/*", "*/tests/*", "*/factories.py"]

[tool.coverage.report]
fail_under = 85
exclude_lines = ["pragma: no cover", "raise NotImplementedError"]
```

The 85% gate is deliberately **not** 100% — chasing the last few percent on Django admin registrations and `__str__` methods buys nothing; the Definition of Done (Part 1.2) already requires explicit tests for every new service function and every new `AC-xx` mitigation, which is where coverage actually matters.

---

## Part 12 — CI/CD Pipeline

**Traces to:** TDD §15; research report §14. Designed against the 2,000 free GitHub Actions minutes/month constraint (TDD §15) — jobs are split so a lint-only failure doesn't burn a full test-matrix run, and dependency caches are aggressive.

### 12.1 GitHub Actions workflow

```yaml
# .github/workflows/ci.yml
name: CI

on:
  pull_request:
  push:
    branches: [main]

concurrency:
  group: ci-${{ github.ref }}
  cancel-in-progress: true   # a new push cancels a stale in-flight run — minutes discipline, TDD §15

jobs:
  lint-and-typecheck:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12", cache: "pip" }
      - run: pip install -r backend/requirements/local.txt
      - run: ruff check backend/
      - run: ruff format --check backend/
      - name: mypy (django-stubs)
        run: cd backend && mypy .
      - name: gitleaks secret scan
        uses: gitleaks/gitleaks-action@v2
      - name: bandit SAST
        run: bandit -r backend/apps -ll

  migrations-check:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:16
        env: { POSTGRES_PASSWORD: postgres, POSTGRES_DB: mbpa_test }
        ports: ["5432:5432"]
        options: >-
          --health-cmd pg_isready --health-interval 10s --health-timeout 5s --health-retries 5
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12", cache: "pip" }
      - run: pip install -r backend/requirements/local.txt
      - name: makemigrations --check (no drift between models and migrations)
        run: |
          cd backend
          python manage.py makemigrations --check --dry-run --settings=config.settings.test
        env:
          DJANGO_SECRET_KEY: ci-only-not-real
          DATABASE_URL: postgres://postgres:postgres@localhost:5432/mbpa_test
          MIGRATIONS_DATABASE_URL: postgres://postgres:postgres@localhost:5432/mbpa_test
          AADHAAR_HMAC_PEPPER: ci-only-test-pepper-not-real

  backend-tests:
    runs-on: ubuntu-latest
    needs: [lint-and-typecheck, migrations-check]
    services:
      postgres:
        image: postgres:16
        env: { POSTGRES_PASSWORD: postgres, POSTGRES_DB: mbpa_test }
        ports: ["5432:5432"]
        options: >-
          --health-cmd pg_isready --health-interval 10s --health-timeout 5s --health-retries 5
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12", cache: "pip" }
      - run: pip install -r backend/requirements/local.txt
      - name: Migrate (privileged role, sets up audit triggers/grants too)
        run: cd backend && python manage.py migrate --database=migrations --settings=config.settings.test
        env:
          DJANGO_SECRET_KEY: ci-only-not-real
          DATABASE_URL: postgres://postgres:postgres@localhost:5432/mbpa_test
          MIGRATIONS_DATABASE_URL: postgres://postgres:postgres@localhost:5432/mbpa_test
          AADHAAR_HMAC_PEPPER: ci-only-test-pepper-not-real
      - name: Run test suite with coverage gate
        run: |
          cd backend
          coverage run manage.py test --settings=config.settings.test
          coverage report --fail-under=85
        env:
          DJANGO_SECRET_KEY: ci-only-not-real
          DATABASE_URL: postgres://postgres:postgres@localhost:5432/mbpa_test
          MIGRATIONS_DATABASE_URL: postgres://postgres:postgres@localhost:5432/mbpa_test
          AADHAAR_HMAC_PEPPER: ci-only-test-pepper-not-real
      - name: pip-audit (dependency vulnerability scan)
        run: pip-audit -r backend/requirements/production.txt

  frontend-build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with: { node-version: "20", cache: "npm", cache-dependency-path: frontend/package-lock.json }
      - run: cd frontend && npm ci
      - run: cd frontend && npm run typecheck
      - run: cd frontend && npm run lint
      - run: cd frontend && npm audit --audit-level=high
      - run: cd frontend && npm run build
      - name: a11y smoke check (axe-core against built pages)
        run: cd frontend && npm run test:a11y

  deploy-gate:
    runs-on: ubuntu-latest
    if: github.ref == 'refs/heads/main'
    needs: [backend-tests, frontend-build]
    steps:
      - uses: actions/checkout@v4
      - name: manage.py check --deploy (zero warnings required)
        run: |
          cd backend && pip install -r requirements/production.txt
          python manage.py check --deploy --settings=config.settings.production --fail-level=WARNING
        env:
          DJANGO_SECRET_KEY: ${{ secrets.DJANGO_SECRET_KEY_CHECK_ONLY }}
          DJANGO_ALLOWED_HOSTS: portal.mbpa.gov.in
      # Actual deploy step intentionally omitted here — depends on the
      # hosting target resolution (TDD §5, still open per Part 18) and
      # should be added as its own job once NIC/NICSI vs. GCC is decided.
```

### 12.2 Branch protection

Configured on `main` (GitHub repo settings, not code, but documented here so it's never "tribal knowledge"):
- Require status checks: `lint-and-typecheck`, `migrations-check`, `backend-tests`, `frontend-build` — all must pass.
- Require at least 1 approving review once the team is >1 person (Part 1.4).
- No force-push, no deletion of `main`.
- `CODEOWNERS` enforcement on for the paths listed in Part 1.4.

### 12.3 PR template

```markdown
<!-- .github/PULL_REQUEST_TEMPLATE.md -->
## What & why
<!-- Traces to which PRD/DRD/TDD section, or which Part 16 phase? -->

## Definition of Done checklist
- [ ] Traces to a named PRD/DRD/TDD section or build-plan phase
- [ ] Business logic lives in services.py/selectors.py, not in a view/serializer
- [ ] No UPDR-2026-dependent value hardcoded — sourced from ConfigParameter (see Part 18)
- [ ] State transitions wrapped in transaction.atomic() with their AuditEvent
- [ ] New DB constraints/triggers have both a migration AND a DB-level test
- [ ] Unit + integration tests added; all pass in CI
- [ ] mypy / ruff / makemigrations --check clean
- [ ] No debug leftovers; structured logging used where warranted
- [ ] New API surface has a working drf-spectacular schema
- [ ] No secret/credential/Aadhaar-shaped literal in this diff
- [ ] If touching Aadhaar/payment/signature code: relevant AC-xx check considered (name it below)

## AC-xx checks considered
<!-- e.g. "AC-09, AC-29 — added a parametrized test across all 7 streams" -->
```

### 12.4 Dependabot

```yaml
# .github/dependabot.yml
version: 2
updates:
  - package-ecosystem: "pip"
    directory: "/backend"
    schedule: { interval: "weekly" }
  - package-ecosystem: "npm"
    directory: "/frontend"
    schedule: { interval: "weekly" }
  - package-ecosystem: "github-actions"
    directory: "/"
    schedule: { interval: "monthly" }
```

---

## Part 13 — Security Hardening Checklist

**Traces to:** TDD §6.3, §9; research report §15.

### 13.1 Production settings checklist (mapped to `manage.py check --deploy`)

| Check | Setting | Status in Part 4.1/production.py |
|---|---|---|
| W004 | `SECURE_HSTS_SECONDS` | Set, 1 year — **ramp-up note:** set to a small value (e.g. 3600) on first production rollout, confirm no HTTPS issues for a few days, then raise to the full year; jumping straight to a year-long HSTS on day one is risky if there's ever a need to roll back to HTTP |
| W006 | `SECURE_CONTENT_TYPE_NOSNIFF` | Set |
| W008 | `SECURE_SSL_REDIRECT` | Set |
| W009 | `SECRET_KEY` | Read from env, never committed, rotated if ever exposed |
| W012/W016 | `SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE` | Set |
| W018 | `DEBUG` | `False` in staging/production |
| W019 | `X_FRAME_OPTIONS` | `DENY` |
| W020 | `ALLOWED_HOSTS` | Explicit list, never `["*"]` |
| — | `SECURE_PROXY_SSL_HEADER` | Set, **with the explicit caveat (research report §15) that the reverse proxy MUST strip any client-supplied `X-Forwarded-Proto` before setting its own** — verify this in the nginx config, not just assume it |

This entire table is asserted by a CI job (`deploy-gate`, Part 12.1) that fails the build on any `check --deploy` warning — it is not a manual pre-launch checklist someone might forget to run.

### 13.2 Content Security Policy — the version trap

**Research finding:** native Django CSP (`SECURE_CSP`) ships only from **Django 6.0**; on the TDD's pinned **5.2 LTS**, CSP requires the **django-csp** package. `production.py` (Part 4.1) already wires `csp.middleware.CSPMiddleware` accordingly. **When the project eventually upgrades to Django 6.x, this is a planned, ADR-documented migration** (Part 1.5) to native `SECURE_CSP` — not a surprise discovered mid-upgrade. Track this as a standing line item in the dependency-upgrade backlog, not something to rediscover later.

### 13.3 `django-axes` brute-force lockout

Already configured in `base.py` (Part 4.1): `AXES_FAILURE_LIMIT=5`, `AXES_COOLOFF_TIME=1` hour, locking on `["username", "ip_address"]`. This sits **alongside**, not instead of, DRF's `ScopedRateThrottle` on the login/OTP endpoints (AC-06) — axes protects the Django auth layer broadly (including admin login), throttling protects the specific high-value API endpoints with tighter, purpose-built rates.

### 13.4 Secrets management procedure

**Traces to:** TDD §15 (no dedicated secrets manager at this scale — `django-environ` + platform env-var injection).

- **Aadhaar pepper rotation:** rotating `AADHAAR_HMAC_PEPPER` invalidates every existing `aadhaar_hash` (since HMAC is keyed). Rotation procedure: (1) add a `pepper_version` column to `ApplicantProfile` (a small additive migration, not yet in the Part 5 model — flagged here as a Phase 11 task, Part 16); (2) on rotation, re-hash every existing profile's Aadhaar — **which requires having the raw Aadhaar number again**, meaning rotation can only happen if you've retained a path to re-verify identity (e.g. requiring affected applicants to re-submit Offline KYC), not by transforming the old hash into a new one. **Document this constraint now, before it's a 2am incident-response surprise.**
- **DSC trust roots** (`load_cca_trust_roots()`, Part 7.6): the CCA root/intermediate certificate chain files live in a config-managed location (e.g. a small private repo or the platform's secret-file mechanism), never hardcoded as inline PEM strings in source — they need periodic updates as the CCA's published root list changes.
- **`/admin/` and `/api/docs/` exposure:** both restricted via the reverse-proxy layer (IP allowlist or VPN-only — TDD §6.3's flagged "now sits next to a public API on shared infrastructure" risk), not by a Django-level check alone. Document the actual allowlist in `infra/`, not in a wiki page that drifts from reality.
- **No secret ever logged:** enforced by the `SensitiveDataFilter` (Part 4.1's `LOGGING` config) plus the `record_event()` denylist (Part 6.2) — two independent layers, matching the project's general "defense in depth, not defense in one place" posture.

### 13.5 GIGW 3.0 / CERT-In / WCAG 2.1 AA mapping

| GIGW 3.0 pillar | This plan's concrete artifact |
|---|---|
| Security (CERT-In-authored chapter) | Parts 6, 13.1–13.4; the full `AC-xx` catalog (Part 2) as the working threat model a VAPT auditor can be handed directly |
| Accessibility (WCAG 2.1 AA) | Part 10.4; automated `axe-core` CI gate (Part 12.1) + manual screen-reader pass (Part 16 Phase 11/12) |
| Quality | The full Definition of Done (Part 1.2), CI gate (Part 12), test coverage gate (Part 11.5) |
| Lifecycle (ongoing conformance, not point-in-time) | ADR process (Part 1.5), Dependabot (Part 12.4), the CalVer release process (Part 1.7) tying every production build to an auditable version |

This table is the direct answer to "is the codebase certification-ready" — every cell points at something that already exists in this plan, not something deferred to a future "compliance phase."

---

## Part 14 — Observability & Operations

### 14.1 Structured logging

```python
# apps/common/logging.py
"""AC-31: this filter is the backstop BEHIND record_event()'s denylist
(Part 6.2) — covers cases where sensitive data might end up in a log line
that never goes through record_event() at all (e.g. an unhandled exception's
traceback capturing local variables)."""
import json
import logging
import re

_SENSITIVE_PATTERNS = [
    re.compile(r'"aadhaar(_number|_raw)?"\s*:\s*"\d{12}"'),
    re.compile(r'"otp_code"\s*:\s*"\d{6}"'),
    re.compile(r'"password"\s*:\s*"[^"]*"'),
]


class SensitiveDataFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        for pattern in _SENSITIVE_PATTERNS:
            message = pattern.sub('"[REDACTED]"', message)
        record.msg = message
        record.args = ()
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "time": self.formatTime(record),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload)
```

### 14.2 Health check (full version, expanding on Part 5.1's stub)

Already shown in Part 5.1 — `RELEASE_VERSION`/`RELEASE_GIT_SHA` are injected as environment variables by the CI deploy job (Part 12.1), reading `git describe` and the commit SHA at build time, so `/healthz`'s response always reflects exactly what's running (Part 1.7).

### 14.3 Error tracking — Sentry-ready interface, not wired yet

```python
# config/settings/base.py (addition)
SENTRY_DSN = env("SENTRY_DSN", default="")
if SENTRY_DSN:
    import sentry_sdk
    from sentry_sdk.integrations.django import DjangoIntegration
    sentry_sdk.init(
        dsn=SENTRY_DSN, integrations=[DjangoIntegration()],
        traces_sample_rate=0.1,
        before_send=lambda event, hint: _scrub_sensitive(event),   # same denylist as SensitiveDataFilter
    )
```

Kept as an **opt-in, env-var-gated** integration rather than a hard dependency — consistent with TDD §15's free-tier-first posture (Sentry's free tier is usable for a system this size; if MbPA's actual incident-response needs justify a paid tier later, this is a config change, not a re-architecture).

### 14.4 Runbooks

`docs/runbooks/` — one short markdown file per scenario, written **before** the scenario happens, not during an incident:

- **`sla-sweep-failure.md`** — how to tell the cron job didn't run (check `SlaSweepRun.objects.latest("started_at")`, Part 7.4) vs. ran but errored (check `/var/log/mbpa/sla_sweep.log`); how to safely re-run it manually (it's idempotent, AC-03 — re-running is always safe).
- **`aadhaar-pepper-rotation.md`** — the procedure and constraint documented in Part 13.4, written out as actual numbered steps, including the "this requires re-verification, it is not a transform" warning in bold at the top.
- **`dsc-token-unavailable.md`** — the V1 fallback (manual sign-print-scan-upload, TDD §8) as an actual step-by-step for an officer whose USB token isn't working, so this isn't reinvented ad hoc by whoever's on duty.
- **`resend-cap-exceeded.md`** — what AC-23's failure mode looks like in the logs, and the escalation path (upgrade tier vs. queue-and-retry) given the system's actual volume at the time.
- **`r2-outage.md`** — what AC-22's "object-first, metadata-second" ordering means for an in-flight upload during an R2 incident (the DB row simply never gets created; nothing to clean up), and how to verify no orphaned references exist after the fact.
- **`neon-cold-start-vs-down.md`** — the AC-24 distinction, with the actual expected cold-start latency number so it's not re-derived under pressure during a real incident.

---

## Part 15 — Migrations & Data Integrity Practices

**Traces to:** research report §16.

### 15.1 Zero-downtime migration checklist (applied as policy, not per-migration improvisation)

1. **Additive first.** New column → nullable or with a `db_default`, deployed and running before any code depends on it being populated.
2. **Backfill as a separate data migration** (`RunPython`), never bundled into the same migration as the schema change for any table with meaningful row counts.
3. **Constraint last.** `NOT NULL`/`CheckConstraint` added only after the backfill migration has run in production and been confirmed complete — never in the same deploy as the column's introduction.
4. **Migrations always run against the `migrations` (privileged) connection** (Part 4.2) — this is what allows the audit-enforcement migration (Part 6.2) to create roles and triggers that the app's own restricted connection couldn't create itself.
5. **Every migration that touches `apps/audit` or `apps/fees`/`apps/certificates`' immutability triggers gets a named second reviewer** (Part 1.4's `CODEOWNERS`), regardless of how small it looks.

### 15.2 Constraint patterns already in this plan

| Pattern | Where used | Why |
|---|---|---|
| Partial unique index (`UniqueConstraint(..., condition=Q(...))`) | `ApplicationParty.is_account_of_record` (Part 5.3, AC-05) | "Exactly one TRUE per group" — the canonical Postgres technique; a non-conditional unique constraint can't express this |
| `CheckConstraint` for non-negative amounts | `Application.plot_area_sqm`/`proposed_bua_sqm` (Part 5.3), `FeeAssessment.master_challan_total` (Part 5.6), `DocumentUpload.size_bytes` (Part 5.5) | Catches a negative value at the database even if every application-layer validator were somehow bypassed |
| `UniqueConstraint` (plain) | `StreamMilestone(stream, milestone)`, `StreamMilestone(stream, sequence_order)`, `DocumentSlot(stream, milestone, document_type)`, `ConditionalClearance(application, clearance_type)` | Ordinary business uniqueness, integrates with Django's `validate_unique()` two-stage validation per the research |
| `BEFORE UPDATE/DELETE` trigger | `audit_auditevent` (Part 6.2), `fees_feeassessment`/`certificates_certificate` (Part 6.3) | Invariants stronger than any constraint language expresses cleanly — "this row may never change after a condition is met" |
| Restricted DB role (`REVOKE`) | The app's connection to `audit_auditevent` (Part 6.2) | The only mechanism that survives even a fully-compromised application process attempting raw SQL |

### 15.3 Seed data — replacing the prototype's `OFFICER_SEED`/`MILESTONE_CHAIN` with a management command

**Traces to:** Handoff §2.3 (hardcoded officer credentials — an identified defect, deliberately not carried forward); TDD §16.

```python
# apps/config/management/commands/seed_reference_data.py
"""
Replaces the prototype's hardcoded OFFICER_SEED/MILESTONE_CHAIN constants
(Code.gs lines 60-87) with idempotent, re-runnable seeding of Stream,
Milestone, StreamMilestone, and the INITIAL (placeholder, clearly-flagged)
ConfigParameter rows. Officer ACCOUNTS are explicitly NOT seeded with
hardcoded plaintext credentials here (that was the prototype's defect,
TDD §16) — officer account creation is a separate, deliberate admin action
(create_officer_account command, invoked interactively, never with a
committed password).
"""
from django.core.management.base import BaseCommand
from django.db import transaction


class Command(BaseCommand):
    help = "Idempotently seeds Stream/Milestone/StreamMilestone reference data and placeholder ConfigParameter rows."

    @transaction.atomic
    def handle(self, *args, **options):
        self._seed_streams_and_milestones()
        self._seed_placeholder_config()
        self.stdout.write(self.style.SUCCESS("Reference data seeded."))

    def _seed_streams_and_milestones(self):
        from apps.milestones.models import Stream, Milestone, StreamMilestone

        STREAMS = [
            ("new_building", "New Building (Full Lifecycle)"),
            ("addition", "Addition / Alteration"),
            ("layout", "Layout / Sub-division / Amalgamation"),
            ("reerection", "Re-erection"),
            ("temporary", "Temporary Permission"),
            ("special", "Special Buildings (High-Rise / Hazardous)"),
            ("regularise", "Regularisation of Unauthorised Construction"),
        ]
        for code, name in STREAMS:
            Stream.objects.update_or_create(code=code, defaults={"display_name": name})

        MILESTONES = [
            ("DEMO", "Demolition & Site Clearance"), ("S1", "Ingestion & Verification"),
            ("S2", "Design Sanction & Foundation Clearance"), ("S3", "Sub-Structure Validation"),
            ("S4", "Superstructure — 80% BUA"), ("S5", "Superstructure — Remaining 20% BUA"),
            ("S6", "Service Infrastructure Integration"), ("S7", "Statutory Finalisation"),
        ]
        for code, name in MILESTONES:
            Milestone.objects.update_or_create(code=code, defaults={"display_name": name})

        # PRD Appendix §17.2's stream-to-milestone-sequence table, as data.
        SEQUENCES = {
            "new_building": ["S1", "S2", "S3", "S4", "S5", "S6", "S7"],
            "addition": ["S1", "S2", "S3", "S6", "S7"],
            "layout": ["S1", "S2", "S3", "S6", "S7"],
            "reerection": ["DEMO", "S1", "S2", "S3", "S4", "S5", "S6", "S7"],
            "temporary": ["S1", "S2", "S6", "S7"],
            "special": ["S1", "S2", "S3", "S4", "S5", "S6", "S7"],
            "regularise": ["S1", "S2", "S3", "S4", "S6", "S7"],
        }
        for stream_code, milestone_codes in SEQUENCES.items():
            stream = Stream.objects.get(code=stream_code)
            for order, m_code in enumerate(milestone_codes, start=1):
                milestone = Milestone.objects.get(code=m_code)
                StreamMilestone.objects.update_or_create(
                    stream=stream, milestone=milestone,
                    defaults={
                        "sequence_order": order,
                        # AC-18 GUARD #1: explicitly False for S7, on EVERY
                        # stream that includes it. This line is the seed-data
                        # half of the belt-and-suspenders pair with
                        # run_sla_sweep's hardcoded check (Part 7.4).
                        "deemed_clearance_eligible": (m_code != "S7"),
                        # sla_working_days is left NULL here deliberately —
                        # see Part 18. It is populated from real UPDR-2026
                        # values via ConfigParameter, never guessed in seed data.
                    },
                )

    def _seed_placeholder_config(self):
        """
        Traces to TDD §16 / Handoff §2.3 — these are the prototype's OWN
        constants (Code.gs FEE_RULES, index.html's "(demo)" benchmarks),
        seeded here with an EXPLICIT, loud is_active=True but a key prefix
        and a stdout warning that makes them impossible to mistake for
        confirmed UPDR-2026 values. See Part 18 for the full list and the
        process for replacing them when real values arrive.
        """
        from apps.config.models import ConfigParameter
        from datetime import date

        PLACEHOLDER_VALUES = {
            "scrutiny_fee_per_sqm": "50.00", "security_deposit_per_sqm": "10.00",
            "debris_deposit_per_sqm": "20.00",
            "premium_coefficient.additional_fsi": "1.10",
            "premium_coefficient.open_space_shortfall": "0.25",
            "premium_coefficient.parking_waiver": "0.40",
            "benchmark.additional_fsi": "1.50",   # prototype's "(demo)" FSI benchmark
            "benchmark.open_space_shortfall": "30.0",  # prototype's "(demo)" open-space %
        }
        for key, value in PLACEHOLDER_VALUES.items():
            ConfigParameter.objects.update_or_create(
                key=key, version=1,
                defaults={"value": value, "effective_from": date.today(), "is_active": True},
            )
        self.stdout.write(self.style.WARNING(
            "Seeded PLACEHOLDER ConfigParameter values inherited from the prototype "
            "(Code.gs FEE_RULES / index.html demo benchmarks). These are NOT confirmed "
            "UPDR-2026 figures — see Part 18 of the build plan before treating any "
            "fee or compliance output as final."
        ))
```

---

## Part 16 — Phased Delivery Roadmap

Each phase has a **Definition of Ready** (what must be true to start) and **Definition of Done** (what must be true to call it complete, beyond the universal PR-level Definition of Done in Part 1.2). Phases are ordered by genuine dependency, not by guesswork — Phase 3 cannot start before Phase 0-2 exist, because `Application` FKs to `Stream` (Phase 2) and needs the audit primitive (Phase 0) to record anything.

### Phase 0 — Repository scaffold, CI gate, settings

**Ready when:** stack decisions (TDD) are final — they already are.
**Build:** Part 3's directory tree, Part 4's settings split, Part 12's CI pipeline (even with zero app code, the lint/typecheck/migrations-check jobs should be green against an empty Django project before any model is written).
**Done when:** an empty `manage.py check` and `manage.py check --deploy` both pass in CI; `/healthz` responds; the database router (Part 4.2) and the two DB connections (privileged/restricted) are provisioned against a real Neon instance, not just configured on paper.
**Retires from Part 2:** none yet — this phase exists to make every later phase's tests runnable.

### Phase 1 — Identity & auth core

**Ready when:** Phase 0 done.
**Build:** `apps/identity` models (Part 5.2), `hash_aadhaar()`/`register_applicant()`/OTP services (Part 7.5), the login flow + role-based session TTL (Part 9), `django-axes` wired (Part 13.3).
**Done when:** a user can register (with the Aadhaar dedup check working against a real DB), request and verify an OTP, log in, and get a session with the correct role-based TTL — all proven by tests for AC-06, AC-07, AC-10, AC-31.
**Retires:** AC-06, AC-07, AC-10, AC-11 (partially — CSRF bootstrap, Part 9.3), AC-31.

### Phase 2 — Reference data & config

**Ready when:** Phase 1 done (officer accounts need `User`).
**Build:** `Stream`/`Milestone`/`StreamMilestone` models (Part 5.4), `ConfigParameter` model + `get_active_config()`/`get_decimal_config()` (Part 6.3), `Holiday` model (Part 5.3), the `seed_reference_data` command (Part 15.3), `create_officer_account` admin command (replacing the prototype's hardcoded `OFFICER_SEED` — TDD §16).
**Done when:** the seed command runs idempotently against a fresh DB and produces the full 7-stream/8-milestone reference set with AC-18's guard #1 verifiably `False` on every S7 row (a test asserts this directly, not just "the seed code looks right").
**Retires:** AC-18 (guard #1 half).

### Phase 3 — Application core, atomic numbering, audit primitive

**Ready when:** Phase 2 done.
**Build:** `Application`/`ApplicationParty`/`ApplicationNumberCounter` (Part 5.3), `generate_application_number()`/`create_application()` (Part 6.1), the full audit migration (Part 6.2) including the DB role/trigger SQL run against a **real** Postgres (Neon) instance — this is the phase where AC-13's DB-level test must pass against the actual restricted connection, not a mock.
**Done when:** `ApplicationNumberConcurrencyTests` (Part 11.2d) passes with real threads against real Postgres; `AuditAppendOnlyDbLevelTests` (Part 11.4) passes against the real restricted role; an application can be created with a guaranteed-unique number and every write is provably audited.
**Retires:** AC-01, AC-05, AC-13, AC-14, AC-15.

### Phase 4 — Milestone engine

**Ready when:** Phase 3 done.
**Build:** `MilestoneInstance`/`SlaSweepRun` (Part 5.4/7.4), `transition_milestone()` and its helpers (Part 7.2), `workdays.py` (Part 7.4), `run_sla_sweep` management command + cron entry (Part 7.4), officer selectors/permissions (Part 7.3/8.3).
**Done when:** `OccupancyCertificateNeverDeemedTests` passes (and is flagged in the team's test-suite documentation as a test that must never be removed); the parametrized cross-stream sequencing test (Part 11.2c) passes for all seven streams + DEMO; the SLA sweep is confirmed idempotent under a double-run against real Postgres.
**Retires:** AC-02, AC-03, AC-08, AC-09, AC-17, AC-18 (guard #2 half, completing AC-18), AC-29.

### Phase 5 — Documents

**Ready when:** Phase 4 done (uploads attach to `MilestoneInstance`).
**Build:** `DocumentSlot`/`DocumentUpload` (Part 5.5), `upload_document()`/`get_download_url()`/`store_object()` (Part 7.7), R2 wiring confirmed against a real bucket (not just `STORAGES` config that's never been exercised).
**Done when:** a malicious-extension upload is provably rejected against real magic-byte detection (not mocked); a correction-triggered re-upload is provably versioned, not overwritten, against a real R2 bucket; a presigned URL is confirmed to actually expire.
**Retires:** AC-19, AC-20, AC-21, AC-22.

### Phase 6 — Fees

**Ready when:** Phase 5 done (concessions can reference uploaded justification docs, though this isn't a hard schema dependency — ordered here because fee assessment is naturally tested after documents exist for a realistic end-to-end flow).
**Build:** `Concession`/`FeeAssessment`/`Payment` (Part 5.6), `assess_fee()`/`reassess_fee()`/`record_payment()` (Part 6.3/7.6), the placeholder `ConfigParameter` rows from Phase 2's seed data now actually exercised end-to-end.
**Done when:** `FeeAssessmentTests` (Part 11.2a) all pass, including the rate-change-after-assessment immutability test against a real DB trigger, not just the Python-level `save()` guard.
**Retires:** AC-04, AC-16, AC-30.

### Phase 7 — Certificates

**Ready when:** Phase 6 done (certificates reference fee-cleared milestones for some types).
**Build:** `Certificate` model (Part 5.7), `generate_certificate()`/`receive_signed_certificate()` (Part 7.6), the `freeze_after()` DB trigger extended to `certificates_certificate` (Part 6.3), `load_cca_trust_roots()` (Part 13.4) wired against real CCA root certificates obtained from MbPA/a CCA.
**Done when:** a deliberately-tampered or expired-cert signed PDF is provably rejected by `pyHanko` validation against real trust roots (not a mocked validator); a genuinely-signed test PDF is provably accepted.
**Retires:** AC-25.

### Phase 8 — Conditional clearances & complaints

**Ready when:** Phase 4 done (both attach to `Application`/`MilestoneInstance`; no hard dependency on Phases 5-7, can run in parallel with them if more than one person is building).
**Build:** `ConditionalClearance` (Part 5.8), `Complaint` (Part 5.9), `raise_applicant_complaint()`/`raise_system_complaint()` (Part 7.8) wired into `run_sla_sweep` (already shown calling it in Part 7.4).
**Done when:** `SystemRaisedComplaintRenderingTests` (AC-28) passes; the SLA sweep's complaint-raising call path is covered by `SlaSweepTests`.
**Retires:** AC-28.

### Phase 9 — Officer console API + frontend

**Ready when:** Phases 4, 6, 7, 8 done.
**Build:** the full `apps/milestones/apis.py` surface (Part 8.4) plus equivalents for fees/certificates/complaints/clearances; `drf-spectacular` schema validated clean; the officer-side React routes (Part 10.1) and domain components.
**Done when:** `OfficerDecisionApiTests` (Part 11.3) passes; an officer can complete a full review cycle (approve, return-for-correction with reason, reject) through the actual UI against the actual API in a manual smoke test, not just isolated unit tests.
**Retires:** confirms AC-08/AC-09/AC-12 hold at the full-stack level, not just service-layer.

### Phase 10 — Applicant frontend

**Ready when:** Phase 9's API surface exists (frontend work can start once the OpenAPI schema is stable, even before officer UI is fully polished).
**Build:** Stream & Fee Planner (public, no-login — confirming the prototype's accidental gating is NOT repeated, TDD §16), the 4-part guided intake wizard, My Applications dashboard, Know Your Status flow.
**Done when:** a full applicant journey — register, plan, apply, track, get a certificate — works end-to-end against the real backend in a staging environment.

### Phase 11 — Security hardening & accessibility pass

**Ready when:** Phases 0-10 functionally complete.
**Build:** the full Part 13 checklist verified against staging (not just unit-tested in isolation); `django-csp` policy tuned against real page behavior (a CSP that's too strict silently breaks the app — this needs a manual pass, not just "the middleware is installed"); manual screen-reader pass (NVDA/JAWS/VoiceOver) against the actual built frontend; the Aadhaar-pepper-rotation and DSC-token-unavailable runbooks (Part 14.4) drilled at least once, not just written.
**Done when:** `manage.py check --deploy` is clean against the real production settings; an informal internal pass against GIGW 3.0's four pillars (Part 13.5's table) finds no open gaps that would block a real CERT-In VAPT engagement.

### Phase 12 — Certification-readiness review

**Ready when:** Phase 11 done.
**Build:** nothing new — this phase is a **review**, consistent with this plan's stated target (Part 0: "certification a review, not a rewrite"). Engage a CERT-In/STQC-empanelled auditor for a gap assessment; walk them through the `AC-xx` catalog (Part 2) directly as the system's working threat model; resolve any findings as normal PRs against the existing architecture, not as a parallel rewrite effort.
**Done when:** the gap assessment comes back with findings that are all addressable as incremental PRs — if it instead surfaces something requiring a structural rework, that's a signal this plan missed something, and worth feeding back into Part 2's catalog for the next system built this way.

---

## Part 17 — Traceability Matrix

A compressed index — full detail lives in each Part's own "Traces to" lines. This table exists so a reviewer (or an MbPA auditor) can start from *either* end: "what does PRD §9.6 become in code?" or "what PRD section justifies this model?"

| PRD / DRD / TDD section | Subject | Build plan location |
|---|---|---|
| PRD §9.3, §10.1 / DRD §3-4 / TDD §7 | Registration, Aadhaar dedup | Parts 5.2, 7.5 |
| PRD §10.2 | Know Your Status | Part 8.4 pattern (OTP-only access — implement as a parallel view to `LoginRequestView` using `purpose=status_lookup`) |
| PRD §10.3 | Stream & Fee Planner (public) | Part 10.1 (public route), `apps/config/apis.py` (read-only `ConfigParameter`/`StreamMilestone` exposure — not separately coded above; follows the same `AllowAny` pattern as Part 8.4's OTP views) |
| PRD §9.4, §10.4 | Guided intake | Part 8.2 (`ApplicationIntakeDetailSerializer`), Part 16 Phase 10 |
| PRD §10.5, §11.2 / DRD §11 | Fee calculation | Part 6.3, Part 7.6... (fees), Part 11.2a |
| PRD §10.6 | My Applications dashboard | Part 16 Phase 10; reads via `apps/applications/selectors.py` (analogous to Part 7.3's pattern, applicant-scoped) |
| PRD §10.7, §9.5-9.11 / DRD §9 / TDD §11 | Officer review, milestone engine | Parts 5.4, 7.2, 7.3, 7.4, 8.3, 8.4 |
| PRD §10.8 | Multi-milestone approval chain | Part 7.2's `_assert_prior_milestones_cleared()` + Part 15.3's seed `SEQUENCES` |
| PRD §10.9 / DRD §9 AC1 | SLA / deemed clearance | Part 7.4 (entire) |
| PRD §10.10 | Progressive payments | Part 5.6 (`Payment`), Part 7.6-adjacent `record_payment()` (pattern shown via `assess_fee()`/`reassess_fee()`; payment-claim recording follows the same service-module convention) |
| PRD §10.11 / DRD §13 | Complaints | Parts 5.9, 7.8 |
| PRD §10.12 / DRD §15 / TDD §8 | Certificates, IOD, Final Dossier | Part 5.7, Part 7.6; **Final Dossier compilation is not yet coded above — flagged as a Phase 7/9 task**: a `compile_final_dossier()` service that zips every `Certificate`/`DocumentUpload` for an application and emails it via `apps/notifications/services.py::send_email()` on the Chairman's S7 approval, called from `transition_milestone()`'s `_advance_to_next_milestone_if_any()` when `next_sm is None` |
| PRD §10.13 | Prescribed document formats download | A static R2-hosted PDF + a simple public view returning its presigned URL — no new model needed, follows Part 7.7's `get_download_url()` pattern |
| PRD §11 (all) / DRD §20 | Business rules & cross-cutting findings | Part 1.1 (governing principles), Part 2 (the `AC-xx` catalog) |
| PRD Appendix §17 | Milestone/stream tables | Part 15.3 seed data (`SEQUENCES` dict) — the PRD's table, as data, exactly per TDD §11's decision |
| DRD §1-21 (every entity) | Data model | Part 5 (entity-by-entity), Part 6 (the three hard primitives) |
| TDD §3 | Architecture, scheduled jobs | Part 3 (layout), Part 7.4 (cron + management command) |
| TDD §4 | Stack decisions | Part 4 (settings reify every decision as actual config) |
| TDD §6 | Auth | Parts 7.5, 9 |
| TDD §9 | DPDP | Part 2 AC-32/AC-33; `process_erasure_request()` referenced in Part 2's AC-32 row but not yet fully coded above — **flagged as a Phase 1 task**, following the same pattern as `register_applicant()` |
| TDD §10 | Audit logging | Part 6.2 (entire) |
| TDD §14 | Testing strategy | Part 11 (entire) |
| TDD §15 | CI/CD, secrets | Parts 12, 13.4 |
| Handoff §2.3 | Prototype defects | Cross-referenced throughout — each defect's "Disposition" column maps to a specific Part (Aadhaar storage → 7.5; fee-rule duplication → 6.3; demo benchmarks → 15.3; hardcoded credentials → 15.3's explicit non-seeding; SLA toast bug → Part 5.4's `StreamMilestone.sla_working_days` single-sourcing) |

---

## Part 18 — Carried-Forward Open Items: What Must Never Be Hardcoded

Every item below was an explicit open question in the DRD/TDD/Handoff. This plan has built an **interface** for each — a `ConfigParameter` key, a nullable/provisional field, an explicit `NotImplementedError`, or a stubbed service — and deliberately stopped short of guessing the value. **If you find yourself typing a literal number or a hardcoded business rule that traces to one of these rows, stop and check this table first.**

| Open item | Source | Where the interface already exists | What's still needed from MbPA |
|---|---|---|---|
| Real UPDR-2026 fee rates, benchmarks, SLA day-counts | TDD §17, DRD §21 | `ConfigParameter` (Part 6.3); seeded in Part 15.3 with the prototype's OWN placeholder values, **loudly flagged**, never silently treated as final | The actual UPDR-2026 text |
| Exhaustive `DocumentSlot` rows per (stream, milestone) | DRD §10, §21 | Table shape exists (Part 5.5); PRD §11.5's handful of named forms can be seeded now as a non-exhaustive start | Real historical application files, prescribed government forms |
| Whether Aadhaar dedup is a hard requirement | DRD §4, §21 | `check_aadhaar_dedup()` (Part 7.5) implements it as specified, but is a single, isolated call site — dropping the requirement means removing one function call and switching `hash_aadhaar()` to a stronger per-row-salted scheme, not a schema change | MbPA's confirmation; see Part 13.4's rotation-cost warning before this gets real production data |
| Multi-party filing confirmation | DRD §7, §21 | `ApplicationParty` (Part 5.3) already supports it; a single-party application is just one row | MbPA confirmation that multi-party filing is permitted under UPDR-2026 |
| Officer zone/stream-specialisation splitting | DRD §5, §21 | `OfficerProfile.zone`/`.stream_specialisation` (Part 5.2) exist, nullable, currently ignored by `_resolve_initial_officer_for()` (Part 7.2) | MbPA confirmation on staffing model |
| Application-number sequence-reset/rollover rule | DRD §6 AC1, §21 | `ApplicationNumberCounter` (Part 5.3) resets per calendar year by construction; confirm this is the intended rule | MbPA confirmation of the actual numbering convention |
| Holiday calendar source/contents | DRD §9 AC1, §21 | `Holiday` model + admin-editable rows (Part 5.3); `workalendar`'s India base calendar covers national holidays | MbPA's port-specific closure calendar, confirmation of the second/fourth-Saturday rule's exact application |
| IOD auto-vs-discretionary | DRD §15 AC2, TDD §16, §21 | `transition_milestone()`'s `REJECT` branch deliberately does NOT auto-create an IOD (Part 7.2); `issue_iod()` is named as a separate, explicit action callers can wire either way | MbPA officer-workflow preference |
| Concession auto-detected vs. self-declared | DRD §11 AC2, §21 | `Concession.source` field (Part 5.6) records which path was used, schema-neutral either way | Product decision on which detection model UPDR-2026 actually intends |
| Certificate lapse consequences (AIP 2yr, Dev Permission 5yr expiry) | DRD §15 AC3, §21 | `Certificate.valid_until` stores the date (Part 5.7); nothing currently consumes it to take an action on lapse | UPDR-2026 / MbPA policy on what happens when a certificate lapses unused |
| Fee re-assessment after a locked `FeeAssessment` (supersede vs. amend) | This plan's Part 6.3 (`reassess_fee()`) | Explicit `NotImplementedError` with a comment pointing here, rather than a guessed behavior | A product decision, not a UPDR-2026 dependency — needs MbPA/product input regardless |
| Final Dossier compilation | PRD §10.12, §9.10 | Flagged in Part 17's traceability matrix as a named Phase 7/9 task with a proposed function signature (`compile_final_dossier()`) | Nothing externally — this is pure implementation work not yet written above, not an open MbPA question |
| DPDP erasure request handling (`process_erasure_request()`) | TDD §9, this plan's Part 2 AC-32 | Named and behaviorally specified (nulls `ApplicantProfile` identity fields only) but not yet fully coded above | The actual DPO/grievance-contact identity (an organisational answer, TDD §9) before the public-facing erasure-request flow can go live |
| Appeal routing (Adjudicatory Board vs. High Court) | TDD §17 | Not a code dependency — affects what a rejection notice should *say*, not how `transition_milestone()` works | Legal confirmation; until resolved, rejection notices should avoid asserting a specific appeal path |
| Hosting target (NIC/NICSI vs. MeitY GCC) | TDD §5, §17 | The architecture (Part 3, Part 4) doesn't lock in either path — Gunicorn behind a reverse proxy, Postgres/R2 both portable | MbPA budget/access decision |

---

## Appendix — Reference Material Index

Grouped by topic, for direct deep-dives during implementation. (Full citations and version numbers are in the standalone research report produced alongside this plan — this index is a quick map back to *which part of that report* covers *which part of this plan*.)

| Topic | Relevant to | 
|---|---|
| Django 5.2 LTS support timeline, `CompositePrimaryKey`, `GeneratedField`, `db_default` | Part 5 (why surrogate PKs + `UniqueConstraint` were chosen over composite PKs) |
| HackSoft Django Styleguide (services/selectors layering) | Parts 1.1, 3.2-3.3, 7 (entire) |
| DRF session auth + CSRF for SPAs | Parts 4.1 (production.py), 8.3, 9 (entire) |
| `drf-spectacular` configuration, `COMPONENT_SPLIT_REQUEST` | Parts 4.1, 8.2, 8.6 |
| Postgres atomic sequence generation (`select_for_update` vs bare `SEQUENCE`) | Part 6.1 |
| Postgres append-only audit pattern (PostgreSQL wiki "Audit trigger") | Part 6.2 |
| `workalendar` India support, IST/UTC day-boundary handling | Part 7.4 |
| `Decimal` currency handling, Django `DecimalField` conventions | Part 6.3, Part 11.2a |
| Aadhaar Act ss.29/37/38/42, UIDAI Offline Paperless KYC | Part 7.5, Part 2 (AC-07) |
| DPDP Act 2023 + DPDP Rules 2025 (erasure, breach notification timelines) | Part 2 (AC-32, AC-33), Part 13.4 |
| `pyHanko` 0.35.x signing/validation API, PKCS#11, CCA Class-3 DSC | Part 7.6 |
| `django-storages` + Cloudflare R2 (`STORAGES` setting, presigned URLs) | Parts 4.1, 7.7 |
| Resend SMTP integration, free-tier daily cap | Parts 4.1, 7.5 (OTP email), 14.4 (`resend-cap-exceeded` runbook) |
| `factory_boy` + Django's built-in `TestCase`/`APITestCase`/`TransactionTestCase` | Part 11 (entire) |
| `freezegun` for time-dependent tests | Part 11.2b |
| GitHub Actions CI for Django+React monorepos, security scanning toolchain | Part 12 (entire) |
| `manage.py check --deploy`, HSTS/CSP/`SECURE_PROXY_SSL_HEADER` | Part 13.1 |
| `django-csp` (5.2) vs native `SECURE_CSP` (6.0+) | Part 13.2 |
| `django-axes` lockout configuration | Part 13.3 |
| GIGW 3.0 / WCAG 2.1 AA / CERT-In VAPT / STQC certification process | Parts 10.4, 13.5, 16 (Phase 11-12) |

---

**End of build plan.** This document and the standalone research report together are the complete handoff for implementation — start at Phase 0 (Part 16), build the three hard primitives (Part 6) as early as the dependency order allows, and keep Part 2's `AC-xx` catalog open in a second window for as long as you're writing code against this plan.
