# MbPA Building Permission Portal — TDD Decision Log

**Purpose:** Full audit trail of every architecture/tech-stack decision made so far — what was considered, what was rejected and why, what won and why. This is the raw material the final Technical Design Doc gets written from once everything below is settled. Decisions that were later reversed or revised are kept in full, not deleted, so the reasoning trail stays honest.

**Status legend:** ✅ Final (locked in) · 🔄 Revised/Reversed (see note — both old and new reasoning kept) · ⬜ Open (not yet decided)

---

## Current locked-in state (quick reference)

| Area | Decision | Status |
|---|---|---|
| Engineering approach | Implementation velocity and low onboarding overhead weighted heavily; unconstrained stack | ✅ |
| Backend language | Python | ✅ |
| Backend framework | Django + Django REST Framework (DRF), used as a pure API | ✅ |
| Frontend architecture | Full SPA — React owns the entire UI | ✅ (reversed from original SSR decision) |
| Frontend framework | React | ✅ (revised from original Preact-for-widgets-only decision) |
| Design system for UI polish | Tailwind CSS + shadcn/ui (or Radix) — not React itself | ✅ |
| Next.js | Considered, eliminated | ✅ |
| Auth strategy | Session-cookie + CSRF (Django-native) | ✅ |
| DB | Neon (Postgres) | ✅ |
| File storage | Cloudflare R2 | ✅ |
| System architecture | Modular monolith, synchronous request model, cron-based scheduling (not Celery), same-domain reverse proxy | ✅ |
| Audit logging | django-simple-history + dedicated AuditEvent log for officer decisions | ✅ |
| Testing strategy | Django/DRF built-in TestCase + APITestCase + factory_boy | ✅ |
| CI/CD & Secrets | GitHub Actions + django-environ/.env, no dedicated secrets manager | ✅ |
| Aadhaar handling | UIDAI Offline Paperless KYC / Secure QR verification | ✅ |
| DSC/Certificate issuance | Local DSC-token signing, signature verified on receipt; manual upload fallback for V1 | ✅ |
| DPDP privacy design | Notice not consent; correction not deletion; breach runbook leans on audit log | ✅ |
| Milestone lifecycle (implementation) | Explicit data structure + transition-validation service function, no state-machine library | ✅ |
| Integration points / NOC checklist | Self-attested + document upload for V1, swappable interface | ✅ |
| Email service | Resend | ✅ |
| DRD / Schema | 19 entities + Holiday/ApplicationParty (added via adversarial review); see `MbPA_Data_Requirements_Document.md` | ✅ |

---

## 1. Context & Constraints ✅

- **Engineering approach:** Implementation velocity and minimal onboarding overhead are weighted heavily — technology choices favor low-friction, low-ceremony tooling over deeper but slower-to-adopt alternatives, given a compressed delivery timeline.
- **Mandate (not a constraint, but the governing pressure):** Ship code meeting the named compliance regimes (IT Act 2000, Aadhaar Act 2016, DPDP Act 2023, RTI Act 2005, Public Records Act 1993, GIGW 3.0/STQC/CERT-In hosting expectations) and built for multi-decade maintainability.
- **Stack/vendor/cloud:** Fully unconstrained — no prior infrastructure investment, no mandated tech policy, prototype is being replaced outright, not extended.
- **Open/unconfirmed:** Budget for empanelled hosting/STQC audit/DSC infra unknown. Real-world scale (applications/month, concurrent load) unknown — assumed modest until MbPA data says otherwise.

---

## 2. Backend Language ✅

**Criteria used (referenced throughout this whole log):**
C1 implementation velocity / ecosystem onboarding cost · C2 decades-stability/low churn · C3 security-by-default posture · C4 gov.in/NIC hosting compatibility · C5 future-maintainer availability in Indian govt/PSU IT · C6 ecosystem maturity for this system's specific needs (ORM, scheduled jobs, PDF/DSC signing, file uploads, email) · C7 type safety · C8 licensing cost

**All candidates considered:** Java+Spring Boot, Python+Django, Node.js+Express, Go, .NET/C#, PHP+Laravel, Ruby on Rails

### Round 1 — eliminated on no compensating structural advantage

| Candidate | Why eliminated |
|---|---|
| Ruby on Rails | No advantage over Python that justifies the onboarding cost (C1) + very small Indian govt-IT talent pool (C5) |
| PHP + Laravel | No unique edge over Python; fading ecosystem momentum cuts against the decades goal (C2); no onboarding-cost advantage (C1) |
| .NET / C# | Java already wins the "future Indian govt-IT inherits this" argument (C5) more clearly; no onboarding-cost advantage over Python (C1); no edge over Java strong enough to justify a third unfamiliar stack |
| Go | Best-in-class C2/C3, but loses on C6 — DSC/PDF-signing library maturity weaker than Java's/Python's, no Django-style admin scaffolding. Stability win doesn't pay for the velocity loss on a delivery-constrained build |

### Round 2 — Java vs. Python vs. Node

**Node.js + Express — eliminated:**
- C3: Express is deliberately unopinionated — gives nothing for security by default (no CSRF/XSS/SQLi protection out of the box, unlike Django/Spring)
- C2: npm's supply-chain track record is genuinely worse (real incidents: `event-stream`, `ua-parser-js`, the `colors.js`/`faker.js` sabotage)
- The "same language front-to-back" argument is weaker than it looks: unless going fully server-rendered with near-zero frontend JS, a Node backend still pairs with a separate frontend build pipeline anyway — the unification benefit is a convenience, not a security/stability one, and shouldn't outweigh C2/C3

**Final comparison — Java + Spring Boot vs. Python + Django:**

| | Java + Spring Boot | Python + Django |
|---|---|---|
| C1 | Slower — heavier ecosystem onboarding | **Faster — flatter onboarding curve, lower setup ceremony** |
| C2 | Best of all candidates — JVM's backward-compat record unmatched | Very strong — Django's explicit "boring tech" philosophy, stable since 2005 |
| C3 | Mature (Spring Security) | Mature (built-in CSRF/XSS/SQLi protection) — roughly equal |
| C5 | **Strongest** — de facto standard across NIC/PSU systems | Good and growing, not yet as entrenched as Java in this specific context |
| C6 | Excellent (Spring Data JPA, Spring Scheduler, PDFBox/iText) | Excellent (Django ORM + admin scaffolding; pyHanko for PDF/DSC signing) |

**Decision: Python.** C1 is a present, binding constraint — implementation needs to move quickly. Java's C5 edge is a future consideration. Django's batteries-included security/admin defaults serve the decades+security goals without paying Java's onboarding tax.

**Why Java's onboarding tax is real:** JDK/JRE version management, Maven's XML verbosity, and the classpath/packaging conceptual layer all add measurable setup ceremony beyond Python's "install, `pip install`, done" — mitigated but not eliminated by modern tooling (SDKMAN!, Spring Initializr).

**Documented fallback:** if implementation velocity were weighted less heavily, Java + Spring Boot is the named alternative — re-open this decision then, don't pre-optimize for it now.

---

## 3. Python Web Framework — Django vs. Flask vs. FastAPI ✅

*(Decided while the architecture was still assumed server-rendered — re-checked in Section 7 below after the SPA pivot, conclusion held both times.)*

| Criterion | Django | Flask | FastAPI |
|---|---|---|---|
| C1 (implementation velocity) | **Wins** — ORM, admin, auth, forms, templating included | Slower — assemble ORM/auth/admin via extensions | Slower — assemble everything; gives nothing structural |
| C2 (decades-stability) | Strong — stable since 2005, conservative about breaking changes | Also strong — minimal, less to break | Weaker — only since 2018; Pydantic v1->v2 already caused real breaking-change pain across the ecosystem |
| C3 (security by default) | **Wins decisively** — CSRF, auto-escaping, SQLi-safe ORM, all on by default | Opt-in via extensions (Flask-WTF/Flask-Login) — mature, but easy to forget under delivery pressure | Same gap as Flask, **and** the "FastAPI doesn't need CSRF" defense doesn't hold here — this system's actual auth model (carried from the prototype) was session/cookie-based at the time, where CSRF matters |
| C6 (fits this system's needs) | **Wins** — admin panel fits the officer console; Celery/APScheduler for SLA sweep; forms framework fits multi-step intake; templating fit the architecture direction at the time | Workable but fully assembled, not given | Weakest at the time — API-only framework, no templating, conflicted with the then-current server-rendered direction |
| C7 (type safety) | Decent (type hints + django-stubs) | Decent, same as Django | **Genuinely strongest** — Pydantic validation |

**Decision: Django.** Decisive wins on C1/C3/C6; FastAPI's one real edge (C7) wasn't enough to give up built-in security defaults, admin scaffolding, and architecture fit.

---

## 4. Frontend Rendering Architecture — SPA vs. Server-rendered REVERSED

### Original decision: Server-rendered (Django templates) wins

**Reasoning at the time:**
- C1: Django views/forms/templates work together natively — no separate API contract per page
- C2: no JS build pipeline for the bulk of the app, nothing to rot over a decade
- C3: CSRF works the way Django already designed it to — form POST, embedded token
- C6: uses exactly what made Django win Section 3 — admin/forms/templating all assume server-rendering
- UX-need assessment: system is mostly forms/tables/status views/approve-reject actions, not an app-like real-time UI

**Exception carved out even under this decision:** the Fee Planner's live calculation and the multi-step NOC wizard need real client-side interactivity — solvable with light JS, not a full SPA framework.

### Reversal: Full SPA — React owns the entire UI

**Why it was reopened:** the person didn't want the portal to risk looking like "another ancient government portal" — wanted modern/sleek/professional.

**Correction offered before accepting the reversal:** rendering mechanism doesn't determine visual quality — GOV.UK's frontend and Basecamp/HEY are both server-rendered and look excellent. The "ancient government portal" look comes from bad typography/cluttered layout/no design system, not from SSR itself.

**The more accurate version of the reasoning, which justified the reversal:** SPA + a mature component ecosystem (shadcn/ui, Radix, MUI, Ant Design) genuinely lowers the cost of a polished, app-like feel — no full-page-reload flicker, richer micro-interactions, deep pre-built component libraries.

**Decision: Full SPA, React.** Accepted on that basis, even though server-rendered + Tailwind + htmx was later given as the honest recommendation when revisited (see Section 9) — the person chose to keep the SPA and accept the resulting overhead.

**Explicit consequence flagged at the time:** rejecting SSR potentially reopens Section 3's backend framework round too, since Django's win there was partly about template/forms/admin fit. Re-checked in Section 7.

---

## 5. Frontend Framework Choice REVISED

### Original decision (under the server-rendered assumption, for 2 embedded widgets only): Preact

**All candidates considered:** React, Preact, Angular, Vue

| Candidate | Why eliminated/won (at the time) |
|---|---|
| Angular | Eliminated — built for full SPA app-shell complexity, overkill for isolated widgets |
| Vue | Eliminated — no decisive advantage over Preact/React for this narrow use case, smaller talent pool than React in this context |
| React | Eliminated *for this role* — best C5 (talent pool), but heaviest build/dependency footprint of the remaining two; overkill for 1-2 embedded widgets |
| **Preact** | **Won** — ~3kb vs. React's 40kb+, React-compatible API, small enough to drop into a page without a full build pipeline |

**Caveat noted at the time:** even simpler (vanilla JS/Alpine.js/htmx) might be the actual best fit — worth comparing before finalizing.

**Follow-up — person pushed back, asked if React had any drawback besides being overkill:**
Confirmed honestly: no hidden drawback. "Overkill" cashes out concretely as (a) bundle size (~40kb+ vs. ~3kb — matters somewhat for applicants on weaker connections, less for officers on office networks) and (b) needing a build step (Babel/JSX+bundler) for what would otherwise be build-step-free. No security/stability/correctness gap between the two. **Decision at the time: React for the 2 widgets specifically**, scoped via a small Vite build producing just those widget bundles — not a reversal of the server-rendered backbone yet.

### Revision: React for the whole app

Once Section 4 reversed to full SPA, the original reasoning for Preact (small footprint matters for isolated *islands*) no longer applies — there's no longer an "otherwise server-rendered" backbone to stay light against. With React now rendering the entire UI, bundle size matters far less than the depth of the component/design-system ecosystem (exactly what's needed for "modern/sleek/professional").

**Decision: React**, for the entire frontend.

### Next.js — considered separately, eliminated regardless of SPA-vs-SSR framing ✅

| Criterion | Verdict |
|---|---|
| C2 (decades-stability) | Poor — Pages Router → App Router was a major breaking architectural shift; Next.js has had several such disruptions. Worse churn signal than even Pydantic v1→v2 |
| C4 (hosting compatibility) | Full feature set (streaming, ISR, edge functions) assumes a Vercel-tuned Node runtime; mapping that onto NIC/MeitY-empanelled infra is unproven, unlike plain Django |
| Operational footprint | Pairing with Django means running two separate server runtimes (Python+Django *and* Node+Next.js) for one application — doubles patch/monitor/security surface for the team maintaining it |
| Does it solve a real problem here? | No — Next.js's core value (SSR for SEO) doesn't apply; almost everything here is behind auth with zero SEO need |

**Decision: Excluded**, on its own technical merits, independent of which way the SPA-vs-SSR call went.

---

## 6. Design System for UI Polish ✅

The actual lever for "modern/sleek/professional" is **not React itself** — React with no styling discipline looks exactly as dated as bad Django templates would have. **Decision: Tailwind CSS + shadcn/ui (or Radix)** as the concrete tool for achieving the visual quality goal, layered on top of the React decision above.

---

## 7. Backend Re-check After the SPA Pivot ✅ (reaffirmed)

Once Django became a pure API (DRF) instead of a template-rendering app, its win over FastAPI in Section 3 needed re-examination, since the templating/forms advantage was now irrelevant.

**Re-evaluation:**
- FastAPI's old weaknesses that no longer apply: "doesn't do templating" — moot now, nothing is templated anywhere.
- FastAPI's old weaknesses that still apply: C2 (Pydantic v1→v2 churn already happened), no built-in admin equivalent.
- Django's advantage that **survives the pivot intact**: the **admin panel doesn't disappear** — it remains valuable as a separate internal MbPA ops/data-inspection tool regardless of the citizen/officer-facing UI being React. This is an orthogonal benefit, not tied to whatever renders the public-facing pages.
- Django ORM maturity and C2 stability edge over FastAPI also still stand.

**Decision: Django + DRF reaffirmed**, even as a pure API. FastAPI's real edges (Pydantic validation, auto-generated docs) are real but not decisive enough to give up the admin panel and the stability edge.

---

## 8. Security & Management Overhead Inventory (consequence of Section 4's reversal, not a separate elimination)

Once the architecture became Django-API + React-SPA, several things Django gave "for free" under SSR became explicit responsibilities. Logged here because it directly feeds the eventual NFRD/security section of the TDD:

**Now explicit work (previously automatic):**
- Auth mechanism (Token/JWT vs. Session+manual-CSRF) — nothing is automatic anymore (see Section 10, still open)
- Token storage trade-off if JWT: `localStorage` (XSS-exploitable) vs. `httpOnly` cookie (reintroduces CSRF)
- Token revocation/logout — stateless JWTs need a blocklist or short-lived+refresh pattern
- The prototype's OTP+session-TTL model needs explicit re-implementation, doesn't carry over automatically
- CSRF for session auth — React must explicitly fetch and attach the CSRF header; nothing does this for you
- **CORS — entirely new**, didn't exist under same-origin SSR. Misconfigured CORS (wildcard + credentials) is a common real vulnerability. **Recommendation: serve React and the API from the same domain via reverse proxy** to sidestep this and cross-subdomain cookie issues entirely
- `permission_classes` must be set deliberately on every DRF viewset — **recommendation: global default `IsAuthenticated` (deny-by-default)**, explicitly whitelist what's public
- API contract/versioning — frontend and backend can now drift apart; use `drf-spectacular` for an OpenAPI schema
- Rate limiting on auth/OTP endpoints specifically — now bare, scriptable API endpoints
- Dependency surface doubles — Python backend deps *and* npm frontend deps; the npm supply-chain risk that helped eliminate Node as backend in Section 2 comes back in through the React frontend regardless. Mitigate with lockfiles, `npm audit`/Dependabot, minimal dependency count
- Admin panel exposure — now sits next to a public API on shared infra; needs its own access restriction (IP allowlist/VPN), not just a login page

**Confirmed NOT lost / unaffected by the split:**
- Input validation — DRF serializers are a close equivalent to Django Forms
- File upload validation — same diligence as before, just a different API surface
- XSS auto-escaping — React escapes by default like Django templates; real risk is `dangerouslySetInnerHTML` without sanitization (DOMPurify); the API must still validate server-side regardless, since it's a directly callable surface independent of what the "trusted" frontend does
- Clickjacking protection (`X-Frame-Options`), HSTS/SSL-redirect settings, `manage.py check --deploy` — all response-header-level, unaffected by SSR-vs-API

---

## 9. "Is the UI polish worth it?" Reconsideration ✅ (final answer: keep SPA, informed)

When asked for an honest assessment, the recommendation given was to **revert to server-rendered Django + Tailwind (+htmx for the 2 interactive bits)**, reasoning:
- The hassle list in Section 8 is a permanent complexity increase, not a one-time tax, and pulls against the project's stated top priority (decades-maintainability, minimal moving parts)
- "Modern and professional" is achievable without React (GOV.UK, Basecamp/HEY as evidence)
- The SSR path is also the lower-onboarding-cost option — it engages *all* of Django (templates/forms/admin/ORM together, the way its own docs teach it) vs. the API+SPA path, which engages Django+DRF as two stacked layers while skipping the most approachable parts (templates/forms)

**Final decision, after hearing the recommendation: Keep React SPA, accept the security/management overhead.** Explicit, informed, final — not to be revisited again without new information.

---

## 10. Auth Strategy — JWT vs. Session-cookie+CSRF ✅

| Criterion | JWT | Session-cookie + CSRF |
|---|---|---|
| C1 (ecosystem onboarding cost) | Adds new concepts on top of an already-adopted framework (signing, claim validation, refresh rotation) | **Wins** — literally "the Django way," what Django's own docs default to |
| C2 (decades-stability/dependency count) | Needs a third-party package (`djangorestframework-simplejwt`) | **Wins** — relies on Django core's own session framework |
| C3 (security) | Real, unsolved storage problem (see below) | **Wins** — `httpOnly` cookie is immune to XSS-based token theft by construction |
| Revocation | Stateless by design — can't kill an active token before expiry without bolting on a server-side blocklist (at which point you've rebuilt session storage anyway) | **Wins** — delete the session row, access is dead immediately. Matters for officer termination/compromised-credential scenarios |
| Where JWT would actually win | Third-party API consumers, mobile apps, genuine horizontal-scaling-without-shared-session-store needs | None of these apply — this is a first-party SPA, same operator, same domain |

**The deciding point:** "JWT avoids CSRF" only holds if the token is stored somewhere CSRF can't reach (`localStorage`/memory) — but that's XSS-exploitable, a worse trade for a government system. Store it in an `httpOnly` cookie instead to fix that, and CSRF protection is needed anyway — at which point JWT's complexity cost bought nothing over just using sessions.

**Decision: Session-cookie + CSRF.** Django gives this natively; the standard React pattern (fetch the CSRF cookie, attach as a header on mutating requests) is well-documented; instant server-controlled revocation is a real operational win for this system.

---

## 11. Database Hosting — Supabase vs. Neon vs. Render ✅

**Context that triggered this round:** budget is a real, present constraint — needs a genuinely free Postgres host, not just an abstractly "cheap" one. Person initially assumed Supabase was the only free Postgres-based option; that assumption was checked and corrected.

| Candidate | Free tier reality (verified via current search, not stale knowledge) | Verdict |
|---|---|---|
| Render (free Postgres) | Deleted permanently after 30 days, no backups, no HA, 256MB RAM | ❌ Eliminated — not viable for anything meant to persist |
| Supabase | 500MB DB, 1GB file storage, 50K MAU, 5GB bandwidth — but free projects **pause after 7 days of inactivity and stay down until someone manually unpauses them from the dashboard.** No automated backups on free tier either | Real contender, lost on the point below |
| **Neon** | 100 CU-hours/month free, built-in pgBouncer connection pooling (up to 10,000 connections) on all plans, backed by Databricks (~$1B acquisition, May 2025) — not a startup that might disappear | ✅ **Winner** |

**Decisive factor:** not price (both are free) — it's idle behavior. Supabase requires manual dashboard intervention to come back from a pause; Neon scales to zero and **resumes automatically on the next query** with a ~300-800ms cold start. For a government system that needs to at least look reliably available, "down until someone notices and logs in" is a real liability that "brief delay on first request" isn't.

Also relevant: Supabase is a full BaaS platform (bundled auth, storage, instant APIs) — features that would sit unused since Django+DRF already owns auth and the API layer. Neon is just Postgres, which is all that's actually needed now.

**Decision: Neon.**

---

## 12. Object/File Storage — AWS S3 vs. Cloudflare R2 ✅

| Candidate | Free tier reality (verified current) | Verdict |
|---|---|---|
| AWS S3 | 5GB storage, 20K GET/2K PUT requests — **free only for the first 12 months of a new account.** $0.09/GB egress after that, on every download | ❌ Eliminated — not a real long-term-free option, and this system is download-heavy (certificates, NOC documents, repeated retrieval by applicants/officers) |
| **Cloudflare R2** | 10GB storage, 1M write ops/month, 10M read ops/month — **permanent, resets monthly, not a 12-month countdown.** Zero egress fees, always, regardless of volume. S3-compatible API (`boto3` etc. work unchanged) | ✅ **Winner** |

**Decision: Cloudflare R2.** S3's free tier is a trial, not a feature; its egress pricing is specifically bad for a document-retrieval-heavy government portal. R2's free tier is genuinely permanent, and zero egress means every certificate/document download costs nothing instead of metering against a budget that doesn't exist yet.

---

## 13. System Architecture — Pattern & Processing Model ✅

**Pattern: Modular monolith, not microservices.** Implied since early in this log (decades-maintainability, "boring tech" philosophy) — made explicit here rather than left as an unstated assumption. One Django+DRF deployable unit; React build served as static files alongside it.

**Background/scheduled job execution — the one genuine decision in this section:**

| Candidate | Verdict |
|---|---|
| Celery + Redis | ❌ Eliminated — adds a whole separate stateful service (Redis) to run/secure/patch for decades, plus worker-process monitoring, for a system with exactly one recurring job and an occasional slow task. Disproportionate to actual need |
| APScheduler (in-process) | ❌ Eliminated — risks the same scheduled job firing multiple times across multiple worker processes without added coordination logic |
| django-q2 | Viable middle ground, can use Postgres itself as the broker instead of adding Redis — named as the upgrade path if needed later |
| **OS cron + Django management command** | ✅ **Winner** — `manage.py run_sla_sweep` via plain Linux cron for the daily SLA sweep. Zero new dependencies or services |

**Certificate generation + DSC signing:** done synchronously, inline within the request — at this system's actual volume (a handful of certificates/day for one port authority), there's no real case yet for decoupling it. `django-q2` is the named fallback if that assumption proves wrong once real usage data exists.

**Deployment topology:** same-domain reverse proxy (e.g., Nginx) — `/api/*` → Django/Gunicorn, everything else → built React static files. Locks in the CORS-avoidance approach already recommended when the auth/security overhead was discussed (Section 9).

**Synthesized diagram:**

```
Applicant / Officer browser
        │
        ▼
   Reverse proxy (same domain)
   ├─ /api/*  → Django + DRF (Gunicorn)
   │              ├─ Session auth + CSRF
   │              ├─ Neon (Postgres) — application/milestone/audit data
   │              ├─ Cloudflare R2 — uploaded documents, generated certificates
   │              ├─ [OPEN] DSC signing — sync, inline
   │              └─ [OPEN] Email service — sync, inline
   └─ /*      → React build (static)

   Linux cron → `manage.py run_sla_sweep` (daily)
   Django admin (/admin) → internal MbPA ops tool, separate access control
```

**Explicitly still open (visible on purpose, not silently assumed):** email service provider, DSC signing integration. Both slot into this architecture once decided — next up in this log.

---

DB and file storage are now resolved (Sections 11–12) via the full elimination protocol, closing out the gap flagged earlier in this log about quiet, untested defaults.

---

## 14. Audit Logging ✅

| Candidate | Verdict |
|---|---|
| django-easy-audit | ❌ Eliminated — lightly maintained, last release was v0.0.5 (2024); real users report migration issues |
| django-pghistory | ❌ Eliminated — DB-trigger-based, catches even bulk/raw-SQL changes, technically the strongest option, but trigger-level complexity is a higher onboarding cost than this project's timeline favors |
| django-auditlog | Solid, Jazzband-maintained, JSON field-diffs | Close second |
| **django-simple-history** | Actively maintained, full per-model history table, integrates directly with Django admin (already the locked-in internal MbPA ops tool) — history becomes browsable there for free | ✅ **Winner** |

**Decision:** django-simple-history for generic model-change tracking, **plus a deliberate, purpose-built `AuditEvent` log specifically for officer decisions** (approve/reject/IOD-issue — who, when, what, why). The library answers "what changed on this row"; the legally significant moments for RTI/audit purposes get an explicit semantic record on top of that.

---

## 15. Testing Strategy ✅

| Candidate | Verdict |
|---|---|
| pytest-django + factory_boy | Less boilerplate via fixtures, but two more dependencies, and its implicit fixture-injection model is a second new testing paradigm stacked on top of someone already learning Django from zero |
| **Django/DRF built-in `TestCase`/`APITestCase` + factory_boy** | Zero new dependencies — already have Django+DRF. `APITestCase` is what DRF's own docs teach as the default way to test a DRF API. factory_boy still works fine here, it isn't pytest-exclusive | ✅ **Winner** — consistent with the same onboarding-cost reasoning that already favored Python over Java and sessions over JWT |

**Test allocation:** heavy unit coverage on the domain engine (fee calc, SLA sweep, milestone transitions), integration tests on the officer approve/reject workflow end-to-end through the API, a thin E2E layer for only the highest-stakes journeys (intake submission, OC issuance). `coverage.py` for measurement — no real competing option, no elimination needed.

---

## 16. CI/CD & Secrets ✅

**CI/CD:** GitHub Actions — GitHub is the assumed code host throughout. Private repos get 2,000 free Linux CI minutes/month on the Free plan, comfortably enough for a lint/test/build pipeline at this scale. No elimination round against GitLab CI/CircleCI — no reason to introduce a second platform.

**Secrets:** `django-environ` for parsing config from environment variables; `.env` for local dev (gitignored, with a committed `.env.example` for documentation); the hosting platform's own environment-variable injection for production; GitHub Actions' built-in repo/environment secrets for CI. No dedicated secrets manager (Vault, AWS Secrets Manager) — real infrastructure to run/secure for a problem this system doesn't have yet, and it costs money, conflicting with the free-tier constraint already set for DB/storage.

---

## 17. Aadhaar Handling & Identity Verification ✅

| Option | What it requires | Verdict |
|---|---|---|
| Build own Aadhaar Data Vault | HSM-backed encrypted vault meeting UIDAI's technical bar, own security audit — effectively becoming a fully compliant AUA/KUA-equivalent entity | ❌ Eliminated — institutional undertaking disproportionate to this project's scope |
| Route through an existing licensed AUA/KUA | Sub-AUA onboarding — contractual, usually a paid commercial relationship | ❌ Eliminated — paperwork/cost/timeline doesn't fit the project's scope |
| **UIDAI Offline Paperless KYC / Secure QR verification** | Verify UIDAI's own digital signature on the applicant's offline e-KYC data or Secure QR code, using UIDAI's public certificate — no live API call to UIDAI's database, no AUA/KUA license needed | ✅ **Winner** |

**Decision:** Offline Paperless KYC / Secure QR verification. No AUA/KUA relationship. Only a salted hash of the Aadhaar number (for deduplication) + last 4 digits (for display) are ever stored — never the full number, consistent with the compliance finding from the original domain research (Aadhaar Act §§37/38/42 carry personal criminal liability for mishandling).

---

## 18. DSC / Certificate Issuance ✅

**Cost reality, stated plainly:** a Class-3 DSC token costs roughly ₹1,500–3,000/year per officer from a CCA-licensed CA. This is a regulatory requirement and MbPA's institutional cost — not something engineering can eliminate via free-tier substitution.

| Option | Verdict |
|---|---|
| Server holds officers' private keys, signs on their behalf | ❌ Eliminated — defeats the legal point of an individually-attributable signature; a server compromise would mean forged government certificates |
| **Local signing (officer's own DSC token + browser-side signer) → signed PDF uploaded back, signature verified on receipt** | ✅ **Winner** — the proven pattern already used for GST/MCA/Income Tax e-filing in India |
| Aadhaar eSign (cloud-hosted key, OTP-authenticated per signature) | Named as a real alternative worth flagging to MbPA — no physical token, pay-per-signature — but not architected around exclusively |

**Decision:** Django generates the unsigned PDF via `pyHanko` (already the named Python tool for this from the backend-language round), hands it off for local signing, verifies the PKCS#7/CAdES signature on receipt before treating it as final — this verification step makes the architecture agnostic to which DSC mechanism produced the signature.

**V1 fallback, given the timeline:** manual sign-print-scan-upload, same receive-and-verify code path. Real one-click token signing is a fast-follow, not a blocker to shipping.

---

## 19. DPDP Privacy Design ✅

Mostly a synthesis of legal groundwork already established (domain question log §9.3), turned into concrete engineering choices:

- **Notice, not consent**, for the core function — §7(b) exemption already established. A plain privacy notice page, no consent-checkbox gating the application form
- **Retention beats erasure for application records** — DPDP's erasure right doesn't override the Public Records Act's retention mandate for statutory government records. **Correction** (name/contact typos, DPDP §12) is supported; self-service **deletion** of application records is not — documented explicitly so this isn't ambiguous later
- **Breach notification runbook** is a process document, not code — but the audit-logging system (Section 14) is what makes "scope a breach within 72 hours" actually achievable
- **Open, needs MbPA:** who's the actual DPO/grievance contact to list on the portal — organizational answer, not engineering, already sitting in the domain question log

---

## 20. Milestone Lifecycle — Implementation Pattern ✅

*(The states/SLA values themselves still need UPDR-2026 — this section is about how the engine is built, not what the rules say.)*

| Option | Verdict |
|---|---|
| State-machine library (django-fsm or similar) | Real branching complexity exists (7 streams × different milestone subsets × conditional branches like the DEMO step or the >50%-BUA conversion rule) — but a new dependency with its own decorator-based mental model adds onboarding cost this project's timeline doesn't favor |
| **Explicit data structure + a single transition-validation service function** | ✅ **Winner** — consistent with the same "less magic, more explicit" principle that already favored Django's built-in test tools over pytest-django |

**Decision:** each stream's milestone sequence as a plain Python data structure (`{stream: [ordered milestone list]}`), one `transition_milestone()` service function validating against it, plus the already-decided `deemed_clearance_eligible` flag (hardcoded `False` for OC/S7). Each milestone instance carries `started_at`/`due_at`/`status`, tied into the AuditEvent log for every decision made on it.

---

## 21. Integration Points ✅

**NOC checklist (Railway/CRZ/MHCC/AAI/MPCB):** self-attested checklist + document upload for V1, stored behind the same interface a real API check (e.g., AAI's NOCAS) could fill in later without restructuring the surrounding application flow.

**Email service:**

| Candidate | Current reality | Verdict |
|---|---|---|
| SendGrid | Permanent free tier discontinued (2025) — now a 60-day trial only, then $19.95/month minimum | ❌ Eliminated |
| AWS SES | Cheapest at scale, but starts in sandbox mode requiring manual production-access approval (24-48h), and needs hand-built bounce/complaint/monitoring infrastructure on SNS/CloudWatch — real ops burden, same reasoning that eliminated Celery+Redis | ❌ Eliminated |
| **Resend** | 3,000 emails/month free, permanently, no credit card required, ~15-minute setup | ✅ **Winner** |

**Decision:** Resend. Comfortably covers this system's actual volume (OTPs, milestone notifications, SLA flags for one port authority) with no AWS-style approval gate or DIY infrastructure to maintain.

---

## 22. Data Requirements Document (DRD) — Schema ✅

Drafted as a standalone document (`MbPA_Data_Requirements_Document.md`), built by applying every TDD decision to a concrete entity model and stress-testing each entity with adversarial "how does this break" thinking before locking it. Summarized here for consistency between the two documents.

**19 core entities, plus 2 the adversarial pass forced in:** `User`, `ApplicantProfile`, `OfficerProfile`, `Application`, `ApplicationParty` (added — multi-party filing), `Stream`, `Milestone`, `MilestoneInstance`, `DocumentSlot`, `DocumentUpload`, `Concession`, `FeeAssessment`, `Payment`, `Certificate`, `ConditionalClearance`, `Complaint`, `AuditEvent`, `OtpToken`, `ConfigParameter`, plus `Holiday` (added — working-day SLA calculation).

**Key cross-cutting decisions:**
- **Delete policy is per-entity, not blanket-applied.** `Certificate`/`AuditEvent` are never deletable (legal artifacts); `OtpToken` and erased Aadhaar fields are hard-deletable (privacy); `Application` and most children are soft-deleted (statutory retention). A single shared soft-delete base class — the common Django pattern — was rejected because it would violate at least one of these three pressures.
- **`AuditEvent` enforcement happens at the database level, not just the ORM** — restricted INSERT-only grants/triggers on the application's DB role — because app-level-only immutability "leaves a back door" (confirmed via research). The table also uses a non-cascading generic reference so deleting its target never deletes its history, and orders by a monotonic DB sequence rather than wall-clock time to survive clock skew.
- **Every UPDR-2026-dependent value lives in a versioned `ConfigParameter` table, never hardcoded** — the schema's shape is final; only the values are pending. `FeeAssessment` snapshots its computed amounts plus a config-version reference specifically so a future rate change can never retroactively alter an already-paid fee.
- **`ApplicationParty` and `OfficerProfile.zone`/`stream_specialisation` are provisional** — built flexible and left inert pending MbPA confirmation on multi-party filing and officer staffing, since designing-in-and-dormant is reversible and the opposite isn't.
- **Application-number generation must use an atomic DB sequence, never `COUNT(*)`** — the prototype's single-threaded Apps Script model never exposed this race condition; Django under multiple Gunicorn workers would hit it immediately.

**Open items remaining (values/business rules only, no structural redesign needed):** exhaustive DocumentSlot rows, real ConfigParameter values, multi-party filing confirmation, officer staffing confirmation, whether Aadhaar dedup is a hard requirement (affects the hash/salt security trade-off), IOD auto-vs-discretionary, concession auto-vs-declared, application-number rollover rule, holiday calendar contents, certificate-lapse consequences.

---
