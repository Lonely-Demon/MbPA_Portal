# MbPA Building Permission Portal
# Technical Design Document (TDD) — v1.0

---

## 1. Purpose & Scope

This document specifies **how** the MbPA Building Permission Portal is built — architecture, technology stack, security posture, and engineering practices. It does not redefine **what** the system does; that is the PRD's job. Where this document and the PRD describe the same feature differently, the PRD's intent governs, and this document should be corrected — not the reverse.

This TDD covers the rebuild of an existing HTML + Google Apps Script prototype into a production-oriented system for the Mumbai Port Authority (MbPA), a Special Planning Authority under the Major Port Authorities Act, 2021.

---

## 2. Context & Constraints

- **Engineering approach:** Implementation velocity and minimal onboarding overhead are weighted heavily — technology choices favor low-friction, low-ceremony tooling over deeper but slower-to-adopt alternatives, given a compressed delivery timeline.
- **Mandate:** Ship code that meets the specific compliance regimes identified for this system — IT Act 2000, Aadhaar Act 2016, DPDP Act 2023, RTI Act 2005, Public Records Act 1993, and GIGW 3.0/STQC/CERT-In hosting expectations — and that remains maintainable on a multi-decade horizon, since government systems routinely outlive the people who built them.
- **Stack, vendor, cloud:** Fully unconstrained. No prior infrastructure investment, no mandated technology policy, and the existing prototype is being replaced outright, not extended.
- **Budget:** No confirmed institutional budget — every infrastructure decision in this document was deliberately evaluated against genuinely free options, not merely "cheap" ones.
- **Open and unconfirmed:** Real-world scale (applications/month, concurrent officer load) is not yet known and is assumed modest until MbPA data says otherwise.

---

## 3. System Architecture

### 3.1 Pattern: Modular Monolith

Microservices were never seriously considered. A project building for decades-scale maintainability, with a compressed delivery timeline, should build one well-structured deployable unit — not a distributed system that requires its own orchestration discipline to operate safely. The system is a single Django + Django REST Framework (DRF) application, with the React frontend built and served as static files alongside it.

### 3.2 Background & Scheduled Job Execution

The system has two recurring needs: a **daily SLA sweep** (checking every active application for deadline breaches) and **certificate generation + digital signature handling** (potentially slow enough to consider decoupling from the request cycle).

| Candidate | Verdict | Reasoning |
|---|---|---|
| Celery + Redis | ❌ Eliminated | Adds a whole separate stateful service (Redis) to run, secure, and patch for decades, plus worker-process monitoring — disproportionate to a system with exactly one recurring job and an occasional slow task |
| APScheduler (in-process) | ❌ Eliminated | Risks the same scheduled job firing multiple times across multiple worker processes without added coordination logic — fragile for something as consequential as the SLA sweep |
| django-q2 | Named fallback | Lighter than Celery — can use the existing Postgres database itself as the broker instead of adding Redis. Reserved as the upgrade path if real async-processing needs emerge later |
| **OS cron + Django management command** | ✅ **Decision** | `python manage.py run_sla_sweep`, triggered by plain Linux cron. Zero new dependencies, zero new services — as close to "boring infrastructure" as this gets |

Certificate generation and digital-signature verification are handled **synchronously, inline, within the request** — at this system's actual volume (a handful of certificates per day for one port authority), there is no performance case yet for decoupling it.

### 3.3 Deployment Topology

A same-domain reverse proxy (e.g., Nginx) splits traffic: `/api/*` routes to Django/Gunicorn, everything else serves the built React static files. This single decision avoids CORS configuration and cross-subdomain cookie handling entirely, rather than managing two origins.

### 3.4 System Diagram

```
Applicant / Officer browser
        |
        v
   Reverse proxy (same domain)
   +- /api/*  -> Django + DRF (Gunicorn)
   |              +- Session auth + CSRF
   |              +- Neon (Postgres) - application/milestone/audit data
   |              +- Backblaze B2 - uploaded documents, generated certificates
   |              +- DSC signing - sync, inline (local token / Aadhaar eSign)
   |              +- Resend - email, sync, inline
   +- /*      -> React build (static)

   Linux cron -> `manage.py run_sla_sweep` (daily)
   Django admin (/admin) -> internal MbPA ops tool, separate access control
```

---

## 4. Technology Stack

### 4.1 Backend Language — Python

**Criteria:** C1 implementation velocity / ecosystem onboarding cost · C2 decades-stability/low churn · C3 security-by-default posture · C4 gov.in/NIC hosting compatibility · C5 future-maintainer availability in Indian govt/PSU IT · C6 ecosystem maturity for this system's needs · C7 type safety · C8 licensing cost

**Candidates considered:** Java+Spring Boot, Python+Django, Node.js+Express, Go, .NET/C#, PHP+Laravel, Ruby on Rails

**Round 1 — eliminated on no compensating structural advantage:**

| Candidate | Reasoning |
|---|---|
| Ruby on Rails | No advantage over Python that justifies the onboarding cost (C1) plus a very small Indian govt-IT talent pool (C5) |
| PHP + Laravel | No unique edge over Python; fading ecosystem momentum cuts against the decades goal (C2); no onboarding-cost advantage (C1) |
| .NET / C# | Java already wins the "future Indian govt-IT inherits this" argument (C5) more clearly; no onboarding-cost advantage over Python (C1) |
| Go | Best-in-class C2/C3, but loses on C6 — DSC/PDF-signing library maturity is weaker than Java's or Python's, and there is no Django-style admin scaffolding. The stability advantage doesn't pay for the velocity loss on a delivery-constrained build |

**Round 2 — Java vs. Python vs. Node:**

Node.js + Express was eliminated: Express is deliberately unopinionated, providing no CSRF/XSS/SQLi protection by default (C3); npm's supply-chain track record is genuinely worse than PyPI's or Maven's, with real documented incidents (`event-stream`, `ua-parser-js`, the `colors.js`/`faker.js` sabotage) (C2); and the "same language front-to-back" appeal is weaker than it looks, since a Node backend still pairs with a separate frontend build pipeline unless the app is fully server-rendered.

| | Java + Spring Boot | Python + Django |
|---|---|---|
| C1 | Slower — heavier ecosystem onboarding | **Faster — flatter onboarding curve, lower setup ceremony** |
| C2 | Best of all candidates — JVM's backward-compat record is unmatched | Very strong — Django's "boring tech" philosophy, stable since 2005 |
| C3 | Mature (Spring Security) | Mature (built-in CSRF/XSS/SQLi protection) — roughly equal |
| C5 | **Strongest** — de facto standard across NIC/PSU systems | Good and growing, not yet as entrenched as Java in this context |
| C6 | Excellent (Spring Data JPA, Spring Scheduler, PDFBox/iText) | Excellent (Django ORM + admin scaffolding; pyHanko for PDF/DSC signing) |

**Decision: Python.** C1 is a present, binding constraint — implementation needs to move quickly. Java's C5 advantage is a future consideration. Django's batteries-included security and admin defaults serve the decades-maintainability and security goals without paying Java's onboarding tax.

**Why Java's onboarding tax is real, not a vague impression:** Java's tooling reputation has concrete, well-documented basis. JDK/JRE version management (`JAVA_HOME`, PATH, choosing between Oracle JDK/OpenJDK/Temurin/Corretto distributions) involves materially more moving parts than Python's "install Python, `pip install`, done." Maven's `pom.xml` is XML — verbose by design, and anything beyond a basic dependency list means hand-editing XML noticeably less pleasant than `pyproject.toml`. Modern tooling (SDKMAN! for JDK version switching, Spring Initializr for project scaffolding, IDE-managed builds) mitigates this significantly compared to a decade ago, but doesn't eliminate it — the gap is real and measurable, not just reputation. This is the concrete, generalizable substance behind C1's weighting in the decision above, independent of any particular team's makeup.

**Documented alternative path:** if implementation velocity were weighted less heavily relative to the other criteria, Java + Spring Boot would be the preferred backend, on C2 and C5 alone — Python's only decisive advantage over Java was C1. This is recorded here in case priorities shift (e.g., MbPA's IT function takes over development with existing Java staff, where the onboarding cost no longer applies).

### 4.2 Backend Web Framework — Django

| Criterion | Django | Flask | FastAPI |
|---|---|---|---|
| C1 | **Wins** — ORM, admin, auth, forms, templating included | Slower — assemble ORM/auth/admin via extensions | Slower — assemble everything; no structural scaffolding |
| C2 | Strong — stable since 2005, conservative about breaking changes | Also strong — minimal, less to break | Weaker — only since 2018; the Pydantic v1→v2 migration already caused real breaking-change pain |
| C3 | **Wins decisively** — CSRF, auto-escaping, SQLi-safe ORM, on by default | Opt-in via extensions (Flask-WTF/Flask-Login) | Same gap as Flask |
| C6 | **Wins** — admin panel fits the officer console; scheduled-job integration for the SLA sweep; ORM and PDF/signing libraries fit directly | Workable but fully assembled, not given | API-only framework, no templating |
| C7 | Decent (type hints + django-stubs) | Decent, same as Django | Genuinely strongest — Pydantic validation |

**Decision: Django + Django REST Framework**, used as a pure API backend. **Re-checked after the frontend architecture pivot to a full SPA** (Section 4.3), since Django's templating advantage became irrelevant once nothing is server-rendered: the admin panel survives as a separate internal MbPA ops/data-inspection tool regardless of what renders the citizen/officer-facing UI — an orthogonal benefit unaffected by the pivot. Django's ORM maturity and C2 stability edge over FastAPI also still stand. FastAPI's real advantages (Pydantic validation, auto-generated docs) were not decisive enough to give those up.

### 4.3 Frontend Rendering Architecture — Full SPA

**Initial recommendation:** server-rendered Django templates, reasoned as follows — Django views/forms/templates integrate natively without a separate API contract per page (C1); no JS build pipeline for the bulk of the app means nothing to rot over a decade (C2); CSRF works the way Django already designed it to (C3); and the system is mostly forms, tables, and status views rather than an app-like, real-time UI.

**Reconsideration:** the explicit goal of avoiding a dated, "ancient government portal" visual impression led to reopening this decision. The correction offered at the time still stands as a documented fact: rendering mechanism does not determine visual quality — GOV.UK's frontend and Basecamp/HEY are both server-rendered and look excellent. The more accurate justification for moving to a SPA is that a mature component ecosystem (shadcn/ui, Radix, MUI) genuinely lowers the *cost* of achieving a polished, app-like feel — no full-page-reload flicker, richer micro-interactions, deep pre-built component libraries.

**Decision: Full SPA — React owns the entire UI, Django operates purely as an API.** This was an informed choice, made after the full security/management overhead of the API+SPA split (Section 6.3) was explicitly laid out and accepted.

### 4.4 Frontend Framework — React

**Candidates considered:** React, Preact, Angular, Vue, Next.js

Under an earlier, narrower framing (server-rendered backbone, React/Preact considered only for two embedded interactive widgets), Preact won on bundle size (~3kb vs. React's ~40kb+) and not requiring a full build pipeline. Once the architecture moved to a full SPA, that framing no longer applied — there is no longer a lightweight backbone to stay small against, and bundle size matters far less than the depth of the component/design-system ecosystem needed for a polished, professional look.

| Candidate | Verdict |
|---|---|
| Angular | Built for full SPA app-shell complexity with enforced structure — a genuine asset for *multi-developer* long-term maintenance, but the deciding criterion here (component/design-system ecosystem depth for visual polish) doesn't favor it over React regardless of team size |
| Vue | No decisive advantage over React for this context; smaller talent pool in the Indian context specifically |
| Next.js | See 4.4.1 below — eliminated independently of the SPA-vs-SSR question |
| **React** | **Decision** — deepest component/design-system ecosystem (shadcn/ui, Radix, MUI, Ant Design) of any candidate, directly serving the stated visual-quality goal |

**4.4.1 Next.js — eliminated on independent merits:**

| Criterion | Verdict |
|---|---|
| C2 (decades-stability) | Poor — the Pages Router → App Router transition was a major breaking architectural shift; Next.js has had several such disruptions, a worse churn signal than even Pydantic v1→v2 |
| C4 (hosting compatibility) | Full feature set (streaming, ISR, edge functions) assumes a Vercel-tuned Node runtime; mapping that onto NIC/MeitY-empanelled infrastructure is unproven |
| Operational footprint | Pairing with Django means running two separate server runtimes (Python+Django and Node+Next.js) for one application — doubling the patch/monitor/security surface for the team maintaining it |
| Does it solve a real problem here? | No — Next.js's core value (SSR for SEO) doesn't apply to a system that's almost entirely behind authentication |

### 4.5 Design System

The actual lever for "modern, sleek, professional" is **not React itself** — React with no styling discipline looks exactly as dated as a poorly designed server-rendered page would. **Decision: Tailwind CSS + shadcn/ui (or Radix)** as the concrete tool for the visual-quality goal, layered on top of the React decision above.

### 4.6 Database — Neon (PostgreSQL)

The initial assumption was that Supabase was the only viable free Postgres option; this was checked and corrected.

| Candidate | Free tier (verified) | Verdict |
|---|---|---|
| Render | Deleted permanently after 30 days, no backups, no HA | ❌ Eliminated |
| Supabase | 500MB DB, but free projects pause after 7 days of inactivity and require **manual dashboard intervention** to resume; no automated backups on the free tier | Real contender, lost on the point below |
| **Neon** | 100 CU-hours/month free, built-in pgBouncer connection pooling (up to 10,000 connections), backed by Databricks (~$1B acquisition, May 2025) | ✅ **Decision** |

**Deciding factor:** idle behavior, not price. Supabase requires someone to notice and manually unpause a stalled project; Neon **scales to zero and resumes automatically** on the next query (~300–800ms cold start). For a government system that needs to look reliably available even in pilot phase, the difference matters. Supabase's bundled BaaS features (auth, storage, instant APIs) would also sit unused, since Django+DRF already owns those layers — Neon is just Postgres, which is all that's actually needed.

### 4.7 File/Object Storage — Backblaze B2

> **Post-decision revision (as of this document's sync against the built portal):** this section originally selected Cloudflare R2, on the strength of R2's unconditional zero-egress-fee policy. The team switched the actual deployment to **Backblaze B2** during implementation; the table and rationale below reflect what is actually running (`config/settings/base.py`'s `B2_KEY_ID`/`B2_APPLICATION_KEY`/`B2_BUCKET_NAME`/`B2_REGION`, `backblazeb2.com` endpoint), not the original R2 pick. The `r2_object_key` field name on `DocumentUpload`/`Certificate` is a naming artifact of the original R2-based design — renaming it now would require a live-data migration for no functional benefit, so it stays as-is and simply stores a B2 object key.

| Candidate | Free tier (verified) | Verdict |
|---|---|---|
| AWS S3 | 5GB, free only for the first 12 months of a new account; $0.09/GB egress after | ❌ Eliminated — not a real long-term-free option, and this system is download-heavy |
| Cloudflare R2 | 10GB storage, permanent (not time-limited), zero egress fees forever, S3-compatible API | Originally selected here; superseded — see note above |
| **Backblaze B2** | 10GB storage, permanent (not time-limited); free egress up to 3× the average monthly stored volume via the B2 Native/S3-compatible API (beyond that, $0.01/GB); S3-compatible API (`django-storages` + `boto3` work unchanged, pointed at the `backblazeb2.com` S3-compatible endpoint) | ✅ **Actually deployed** |

S3's free tier is a 12-month trial dressed as a feature — both R2 and B2 avoid that specific trap, which is why either was a reasonable pick. B2's free-egress allowance (3× stored volume/month) is a cap rather than R2's unconditional zero, but comfortably covers this system's actual document-retrieval volume; see `Docs/runbooks/b2_outage.md` for the operational side of this choice.

---

## 5. Deployment & Hosting

The same-domain reverse-proxy topology is locked (Section 3.3). The choice between **NIC/NICSI hosting** and a **MeitY-empanelled Government Community Cloud** is explicitly **not resolved by this document** — it depends on budget and access that only MbPA controls. The architecture itself (Gunicorn behind a reverse proxy, Postgres via Neon — portable to any Postgres instance, B2 via the S3-compatible API — portable to any S3-compatible target) does not lock in either path, so this remains open without blocking development.

---

## 6. Authentication & Authorization

### 6.1 Strategy — Session-cookie + CSRF

| Criterion | JWT | Session-cookie + CSRF |
|---|---|---|
| C1 (ecosystem onboarding cost) | Adds new concepts (signing, claim validation, refresh rotation) on top of an already-adopted framework | **Wins** — the default Django approach |
| C2 (dependency count) | Needs a third-party package (`djangorestframework-simplejwt`) | **Wins** — relies on Django's own session framework |
| C3 (security) | Real, unsolved storage problem — `localStorage` is XSS-exploitable; an `httpOnly` cookie avoids that but reintroduces CSRF, defeating JWT's main argued advantage | **Wins** — `httpOnly` cookie is immune to XSS-based theft by construction |
| Revocation | Stateless by design — can't kill an active token before expiry without a server-side blocklist | **Wins** — deleting the session row kills access immediately |

**Decision: Session-cookie + CSRF.** "JWT avoids CSRF" only holds if the token is stored somewhere CSRF can't reach, which means accepting XSS exposure instead — a worse trade for this system. The standard React pattern (fetch the CSRF cookie, attach it as a header on mutating requests) is well-documented, and instant, server-controlled revocation is operationally valuable for officer-termination or compromised-credential scenarios.

### 6.2 Authorization

DRF's global default permission is set to `IsAuthenticated` (deny-by-default); public endpoints (the Stream & Fee Planner, status lookup) are explicitly whitelisted rather than left open by omission.

### 6.3 Security Implications of the API+SPA Split

Moving from a server-rendered Django app to a Django-API + React-SPA split made several things Django previously handled automatically into explicit engineering responsibilities:

**Now explicit work:**
- CORS — did not exist under same-origin SSR. Mitigated by the same-domain reverse-proxy topology (Section 3.3), avoiding cross-origin configuration and the risk of a misconfigured wildcard-plus-credentials setup
- CSRF for session auth — React must explicitly fetch and attach the CSRF header; nothing does this automatically
- API contract drift — frontend and backend can now diverge; `drf-spectacular` generates an OpenAPI schema as the documented contract
- Rate limiting on auth/OTP endpoints — now bare, scriptable API endpoints, mitigated with DRF throttling classes
- Dependency surface doubles — Python backend dependencies and npm frontend dependencies both need tracking; the npm supply-chain risk that helped eliminate Node as a backend (Section 4.1) returns through the React frontend regardless, mitigated with lockfiles and `npm audit`/Dependabot
- Django admin exposure — now sits next to a public API on shared infrastructure and needs its own access restriction (IP allowlist/VPN), not just a login page

**Confirmed unaffected by the split:**
- Input validation — DRF serializers are a close equivalent to Django Forms
- XSS auto-escaping — React escapes by default like Django templates; the real risk is `dangerouslySetInnerHTML` without sanitization (DOMPurify); the API must still validate server-side regardless, since it is a directly callable surface independent of what the "trusted" frontend sends
- Clickjacking protection, HSTS/SSL-redirect settings, `manage.py check --deploy` — all response-header-level, unaffected by SSR-vs-API

### 6.4 Session Timeouts

Carried from the existing prototype's values: 45-minute applicant sessions, 6-hour officer sessions, refreshed on activity.

---

## 7. Aadhaar Handling & Identity Verification

| Option | Requirement | Verdict |
|---|---|---|
| Build an own Aadhaar Data Vault | HSM-backed encrypted vault meeting UIDAI's technical bar, plus a dedicated security audit — effectively becoming a fully compliant AUA/KUA-equivalent entity | ❌ Eliminated — an institutional undertaking disproportionate to this project's scope |
| Route through an existing licensed AUA/KUA | Sub-AUA onboarding — contractual, usually a paid commercial relationship | ❌ Eliminated — doesn't fit the project's timeline or budget |
| **UIDAI Offline Paperless KYC / Secure QR verification** | Verify UIDAI's own digital signature on the applicant's offline e-KYC data or Secure QR code, using UIDAI's public certificate — no live API call to UIDAI's database, no AUA/KUA license needed | ✅ **Decision** |

**Storage rule:** only a salted hash of the Aadhaar number (for deduplication) and the last 4 digits (for display) are ever stored — never the full number, anywhere persistent. This is not a best-practice suggestion; the Aadhaar Act (Sections 37, 38, 42) carries personal criminal liability for mishandling, with fines and imprisonment terms confirmed against current sources.

---

## 8. Digital Signature / Certificate Issuance

**Cost reality, stated plainly:** a Class-3 DSC token costs roughly ₹1,500–3,000/year per officer from a CCA-licensed Certifying Authority. This is a regulatory requirement and an institutional cost for MbPA to bear — not something engineering can eliminate through a free-tier substitution.

| Option | Verdict |
|---|---|
| Server holds officers' private keys and signs on their behalf | ❌ Eliminated — defeats the legal purpose of an individually attributable signature; a server compromise would mean forged government certificates |
| **Local signing** (officer's own DSC token + browser-side signer utility) → signed PDF uploaded back, signature verified on receipt | ✅ **Decision** — the proven pattern already used for GST/MCA/Income Tax e-filing in India |
| Aadhaar eSign (cloud-hosted key, OTP-authenticated per signature) | Named as a legitimate alternative worth raising with MbPA — no physical token required, pay-per-signature instead of an annual cost — but not architected around exclusively |

**Architecture:** Django generates the unsigned PDF certificate via `pyHanko`. The officer signs it locally (USB DSC token or Aadhaar eSign), and the signed PDF is uploaded back. The system **verifies the PKCS#7/CAdES signature on receipt** before treating the certificate as final — this verification step is what makes the architecture agnostic to which signing mechanism produced the signature.

**V1 fallback, given the timeline:** manual sign-print-scan-upload, using the same receive-and-verify code path. One-click DSC-token signing integration is a fast-follow, not a blocker to shipping.

---

## 9. DPDP / Privacy Design

- **Notice, not consent**, for the core function. DPDP Act Section 7(b) treats government processing for "provision of any subsidy, benefit, service, certificate, licence or permit" as a legitimate use not requiring consent — a building-permission/certificate-issuance portal qualifies. A plain privacy notice page is used instead of a consent-gated application form, though notice, purpose-limitation, and security obligations still apply under the DPDP Rules' Second Schedule.
- **Retention beats erasure for application records.** DPDP Section 12 grants correction, completion, and erasure rights, but erasure applies only where retention isn't otherwise legally required — and the Public Records Act, 1993 mandates retention for statutory government records. **Correction** of applicant details (name/contact typos) is supported; self-service **deletion** of application records is not — this distinction is documented explicitly so it isn't ambiguous later.
- **Breach notification:** Section 8(6) and Rule 7 require notifying the Data Protection Board and affected Data Principals "without delay," with a detailed report to the Board within 72 hours. This is a process runbook, not code — but the audit-logging system (Section 10) is what makes "scope a breach within 72 hours" operationally achievable.
- **Phasing:** DPDP Rules were notified 14 Nov 2025; Consent Manager provisions phase in from 13–14 Nov 2026; full substantive compliance obligations apply from 13–14 May 2027. Designing for this now, ahead of the deadline, is the deliberate choice.
- **Open, pending MbPA:** the identity of the actual Data Protection Officer/grievance contact to list on the portal — an organizational answer, not an engineering one.

---

## 10. Audit Logging & Records Compliance

| Candidate | Verdict |
|---|---|
| django-easy-audit | ❌ Eliminated — lightly maintained, last release v0.0.5 (2024); reported migration issues |
| django-pghistory | ❌ Eliminated — database-trigger-based, technically the strongest option (catches even bulk/raw-SQL changes), but trigger-level complexity is a higher onboarding cost than this project's timeline favors |
| django-auditlog | Solid, actively maintained, JSON field-diffs | Close second |
| **django-simple-history** | Actively maintained, full per-model history table, integrates directly with Django admin — already the locked-in internal MbPA ops tool, so history becomes browsable there for free | ✅ **Decision** |

**Decision:** django-simple-history for generic model-change tracking, **plus a deliberate, purpose-built `AuditEvent` log specifically for officer decisions** (approve/reject/IOD-issue — who, when, what, why). The library answers "what changed on this row"; the legally significant moments for RTI and audit purposes get an explicit semantic record on top of that, satisfying the Public Records Act's integrity expectations and RTI's transparency requirements.

---

## 11. Milestone Lifecycle — Implementation Pattern

*(This section covers how the engine is built, not what the rules say — the SLA day values, zone-specific thresholds, and stream-specific conditions themselves still depend on UPDR-2026, which has not yet been obtained.)*

| Option | Verdict |
|---|---|
| State-machine library (django-fsm or similar) | Real branching complexity exists (seven streams, each with a different milestone subset, plus conditional branches like the demolition step for re-erection or the >50%-BUA conversion rule for additions/alterations) — but this means a new dependency with its own decorator-based mental model, adding onboarding cost this project's timeline doesn't favor |
| **Explicit data structure + a single transition-validation service function** | ✅ **Decision** |

**Reasoning:** consistent with the same "less magic, more explicit" principle that favored Django's built-in test tools over pytest-django (Section 14) — the actual rules here are data (which streams have which milestones, in which order), not complex branching behavior, and don't need a library to express. Each stream's milestone sequence is a plain Python data structure; one `transition_milestone()` service function validates against it. Each milestone instance carries `started_at`/`due_at`/`status` fields and a `deemed_clearance_eligible` flag, hardcoded `False` for the Occupancy Certificate milestone — comparative Indian Ease-of-Doing-Business law is unusually consistent in excluding final occupancy/safety sign-off from automatic, silent deeming, even where intermediate building-permission stages do auto-clear on SLA breach. Every transition is tied into the AuditEvent log (Section 10).

---

## 12. Integration Points

**NOC checklist (Railway, CRZ/MCZMA, MHCC heritage, AAI/aviation, MPCB pollution):** self-attested checklist plus document upload for V1, stored behind an interface that a real API check (for example, AAI's NOCAS coordinate-based lookup) could fill in later without restructuring the surrounding application flow. This is a deliberately deferred integration, not a forgotten one.

**Email service:**

| Candidate | Current reality (verified) | Verdict |
|---|---|---|
| SendGrid | Permanent free tier discontinued in 2025; now a 60-day trial only, then $19.95/month minimum | ❌ Eliminated |
| AWS SES | Cheapest at scale, but starts in sandbox mode requiring manual production-access approval (24–48 hours), and needs hand-built bounce/complaint/monitoring infrastructure on SNS/CloudWatch | ❌ Eliminated — same reasoning that eliminated Celery+Redis (Section 3.2): real ongoing ops burden for a problem this system's modest volume doesn't justify |
| **Resend** | 3,000 emails/month free, permanently, no credit card required, roughly 15-minute setup — **capped at 100/day**, the binding constraint given bursty OTP traffic, not the monthly figure | ✅ **Decision** |

**The 100/day cap is a real go-live blocker, not a comfortable margin** (tracked as AC-23; see `Docs/runbooks/resend_dns.md`) — move to the Pro tier before production traffic and monitor daily send count.

**Live payment gateway and GIS/mapping integration remain explicitly out of scope**, per the PRD.

---

## 13. Non-Functional Requirements

| NFR | Target |
|---|---|
| API response time | Under 500ms, typical |
| Page load | Under 2 seconds on average broadband |
| Availability | Best-effort, target above 99% once live — no formal SLA at pilot stage, consistent with the fact that the underlying free-tier infrastructure (Neon) itself carries no SLA |
| Accessibility | GIGW 3.0 / WCAG 2.1 AA |
| Browser support | Last 2 versions of evergreen browsers (Chrome, Firefox, Edge, Safari) — no Internet Explorer 11 support |
| Session timeouts | 45 minutes (applicant) / 6 hours (officer), carried from the existing prototype |
| Email capacity | Resend's 3,000/month free tier is ample on average, but its 100/day cap is a real go-live blocker for bursty OTP traffic (AC-23) — upgrade to Pro before production, don't wait to be exceeded |

---

## 14. Testing Strategy

| Candidate | Verdict |
|---|---|
| pytest-django + factory_boy | Reduces boilerplate via fixtures, but adds two dependencies, and its implicit fixture-injection model is a second testing paradigm layered on top of the Django/DRF stack itself — additional onboarding surface for marginal gain |
| **Django/DRF built-in `TestCase` / `APITestCase` + factory_boy** | ✅ **Decision** — zero new dependencies beyond what's already chosen; `APITestCase` is what DRF's own documentation teaches as the default way to test a DRF API. factory_boy still works fine here, as it isn't pytest-exclusive |

**Test allocation:** heavy unit-test coverage on the domain engine (fee calculation, the SLA sweep, milestone transitions); integration tests covering the officer approve/reject workflow end-to-end through the API; a thin end-to-end layer reserved for only the highest-stakes journeys (intake submission, Occupancy Certificate issuance). `coverage.py` for measurement.

---

## 15. CI/CD & Secrets Management

**CI/CD:** GitHub Actions, since GitHub is the assumed code host throughout this build. Private repositories receive 2,000 free Linux CI minutes per month on the Free plan — comfortably enough for a lint/test/build pipeline at this project's scale. No second CI platform is introduced.

**Secrets:** `django-environ` for parsing configuration from environment variables; a gitignored `.env` for local development with a committed `.env.example` for documentation; the hosting platform's own environment-variable injection for production secrets; GitHub Actions' built-in repository/environment secrets for CI. No dedicated secrets manager (HashiCorp Vault, AWS Secrets Manager) — real infrastructure to run and secure for a problem this system's scale does not yet have, and one that costs money, conflicting with the free-tier constraint set elsewhere in this document.

---

## 16. Migration Plan from Prototype

**Carried over in concept, rebuilt properly underneath — not copy-pasted:**
- The milestone-chain structure (stream-to-milestone mapping), reimplemented as the data structure in Section 11; SLA day *values* are carried only as placeholders pending UPDR-2026
- The four-officer-role model, the document-slot concept, and the OTP-plus-session login flow — all unchanged in concept, rebuilt on the Section 6 authentication architecture

**Deliberately rebuilt, not carried over, because they were identified defects in the prototype:**
- Fee-rule duplication (the prototype maintained separate copies in the backend and the frontend) — single-sourced in this rebuild
- Hardcoded "demo" benchmark placeholder values (e.g., FSI 1.5, open space 30%) — flagged as requiring real UPDR-2026 sourcing, never silently reused
- Full Aadhaar number storage — replaced with the hash-plus-last-4 approach in Section 7
- Hardcoded officer credentials in source code — replaced with the secrets management approach in Section 15
- A cosmetic bug where the rejection toast displayed a hardcoded "7 days" regardless of the milestone's actual SLA — values are now single-sourced from the milestone definitions and cannot drift

**Resolved in this rebuild, where the prototype's behavior conflicted with the PRD's stated intent:** the **Stream & Fee Planner** is public, requiring no login, matching the PRD's original intent over the prototype's accidental login-gating. No compliance research identified any reason to gate it — it involves no personal data, only plot and building parameters — and gating it works against the PRD's stated Ease-of-Doing-Business purpose.

**Explicitly not resolved here, carried forward as an open decision:** whether an IOD (Intimation of Disapproval) should continue to be auto-generated on every officer rejection, as the prototype does, or whether officers should have discretion to issue a simple correction-return instead. This depends on actual officer workflow preference that cannot be invented here — it requires MbPA's input.

---

## 17. Open Risks & Pending Decisions

- **UPDR-2026 text itself** — not publicly available; blocks fee rates, zone-specific FSI/setback/parking benchmarks, document-slot checklists, the 50%/90% stream-conversion thresholds, the demolition-step SLA duration, Temporary Permission renewal terms, and Special Building height/hazard classification criteria
- **Hosting target** — NIC/NICSI vs. MeitY-empanelled Government Community Cloud (Section 5)
- **DPO/grievance contact identity** (Section 9)
- **Appeal routing** — whether a rejected application's appeal goes through the MPA Act's Adjudicatory Board or directly to High Court writ jurisdiction; the Adjudicatory Board's statutory scope (Sections 22–31) may not squarely cover building-permission refusals
- **IOD auto-generation vs. officer discretion** (Section 16)
- **Organizational staffing** — whether each of the four officer roles is held by a single person or split by geography/stream type
- **Zonal Ready Reckoner Rate source** — the Maharashtra IGR e-ASR rate vs. a possible MbPA-internal Scale of Rates equivalent for port land
- **Real historical application files, the existing paper SOP, and the prescribed government forms** — needed before a Data Requirements Document and Functional Requirements Document can be fully detailed
- **Exact NOC trigger distances for Railway, MHCC heritage, and MPCB pollution clearances** — only the AAI/aviation and CRZ triggers were resolved with concrete, sourced figures; the others remain comparative assumptions

---

## 18. Traceability to PRD

| TDD Section | Traces to |
|---|---|
| Aadhaar handling | PRD glossary references; domain question log items on Aadhaar/AUA-KUA |
| DSC / Certificate issuance | PRD certificate-issuance flow; domain question log on digital signature validity |
| DPDP design | Domain question log on DPDP obligations |
| Milestone lifecycle | PRD's milestone/officer/SLA appendix tables |
| Integration points (NOC) | PRD's conditional-clearance references; domain question log on NOC triggers |
| Deemed-clearance / OC exclusion | Domain question log finding on comparative Ease-of-Doing-Business law |
| Audit logging | PRD's complaint-system description; RTI and Public Records Act findings |

---

## 19. Production-Readiness (Forward Pointer)

A separate Production-Readiness / Handover document — explicitly **not** part of this TDD — covers STQC certification, CERT-In empanelled VAPT, the GIGW accessibility audit, and empanelled-hosting approval. These are MbPA's institutional gates to clear before real go-live, not engineering deliverables, and are deliberately kept out of this document so it stays scoped to *how the system is built*.
