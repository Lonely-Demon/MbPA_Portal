# MbPA Building Permission Portal
# Data Requirements Document (DRD) — v1.0 (DRAFT for review)

---

## 0. Status, Method & Honest Caveats

**What this is:** the entity/data model for the portal, derived from (a) decisions locked in the TDD, (b) the actual data shapes observed in the prototype's `Code.gs`/`index.html`, and (c) the PRD's described lifecycle. Each entity below was stress-tested with adversarial "how does this break / what state can't this represent" thinking before being locked.

**What this is NOT:** a final, MbPA-validated schema. As flagged when this work was scoped, DRD accuracy depends more heavily than the TDD did on real-world artifacts that nobody has yet — actual historical application files, the prescribed government forms, and the UPDR-2026 text. This draft is a well-reasoned approximation built to be *correct in shape and safe in defaults*, with every domain-dependent value externalised to configuration rather than hardcoded, so that filling in real values later does not require reshaping tables.

**Conventions used throughout:**
- All tables get `id` (Django default BigAutoField PK) unless a natural key is explicitly justified.
- All tables get `created_at` / `updated_at` (auto timestamps) unless explicitly immutable.
- "Soft-delete" = `is_deleted` flag + `deleted_at`, record retained. "Hard-delete" = row physically removed. Which one each entity uses is decided **per-entity** below, not blanket-applied — research confirms sensitive/personal and payment data should generally be hard-deletable for privacy compliance, while statutory records must be retained, and these two pressures genuinely conflict.
- "FK" = ForeignKey. "M2M" = ManyToMany. `PROTECT` / `CASCADE` / `SET_NULL` refer to Django's `on_delete` behaviour and are specified deliberately, never left to default.

---

## 1. Entity Overview

| # | Entity | One-line purpose | Delete policy |
|---|---|---|---|
| 1 | `User` | Auth identity for both applicants and officers (extends Django's user) | Soft-delete (officers), see §3 |
| 2 | `ApplicantProfile` | Applicant-specific data incl. Aadhaar token | Hard-deletable on lawful erasure request, see §4 |
| 3 | `OfficerProfile` | Officer role + (provisional) zone/stream specialisation | Soft-delete |
| 4 | `Application` | The central record; one per building-permission request | Soft-delete (statutory retention) |
| 5 | `ApplicationParty` | Links people to an application in named roles (owner/architect/etc.) | Soft-delete with parent |
| 6 | `Stream` | Reference table: the 7 streams + their milestone sequences | Reference data, not deleted |
| 7 | `Milestone` | Reference table: S1–S7 + DEMO definitions | Reference data, not deleted |
| 8 | `MilestoneInstance` | A specific milestone's live state on a specific application | Soft-delete with parent |
| 9 | `DocumentSlot` | Reference: which documents a (stream, milestone) requires | Reference data |
| 10 | `DocumentUpload` | An actual uploaded file against a slot | Soft-delete (audit trail) |
| 11 | `Concession` | A detected/declared concession + its premium | Soft-delete with parent |
| 12 | `FeeAssessment` | The computed fee breakdown for an application | Soft-delete with parent |
| 13 | `Payment` | A recorded payment/challan reference | See §14 — special handling |
| 14 | `Certificate` | An issued, digitally-signed certificate/IOD | NEVER deleted (legal artifact) |
| 15 | `ConditionalClearance` | NOC checklist state (Railway/CRZ/etc.) | Soft-delete with parent |
| 16 | `Complaint` | Applicant-raised or system-raised complaint | Soft-delete with parent |
| 17 | `AuditEvent` | Immutable, append-only record of consequential actions | NEVER deleted/updated (§18) |
| 18 | `OtpToken` | Short-lived OTP for login/verification | Hard-delete (ephemeral) |
| 19 | `ConfigParameter` | Externalised domain values (fee rates, benchmarks, SLAs) | Versioned, not deleted (§19) |

Two reference tables (`Stream`, `Milestone`) plus `ConfigParameter` are the mechanism that keeps every UPDR-2026-dependent value out of the table *structure* — the shape below is final, the values are data.

---

## 2. The Central Relationship Map

```
User ──1:1── ApplicantProfile
User ──1:1── OfficerProfile

Application ──FK──> Stream
Application ──M2M (through ApplicationParty)──> User
Application ──1:N──> MilestoneInstance ──FK──> Milestone
Application ──1:N──> DocumentUpload ──FK──> DocumentSlot
Application ──1:N──> Concession
Application ──1:1──> FeeAssessment
Application ──1:N──> Payment
Application ──1:N──> Certificate ──FK──> MilestoneInstance
Application ──1:N──> ConditionalClearance
Application ──1:N──> Complaint

(Stream, Milestone) ──> DocumentSlot   [reference matrix]

AuditEvent ──> (generic actor + generic target)   [append-only, references everything, owned by nothing]
```

---

## 3. `User`

Extends Django's `AbstractUser`. A single user table for both applicants and officers, distinguished by which profile is attached and by `user_type`.

| Field | Type | Notes |
|---|---|---|
| `user_type` | choice: `applicant` / `officer` | Drives which profile exists, gates the API surface |
| `email` | EmailField, unique | The login identifier (prototype used email+username+password) |
| `username` | CharField, unique | Retained from prototype's 3-factor login |
| `is_active` | bool | Standard Django; doubles as the soft-disable for officers |

**Adversarial check — "what about an officer who is also, personally, an applicant?"** A port employee could plausibly file their own building application. Forcing `user_type` to be exclusive would break this. **Resolution:** `user_type` reflects the *account's primary purpose*; the actual capability gate is which *profile* row(s) exist and the officer's `role`. The design permits both an `ApplicantProfile` and an `OfficerProfile` on one `User` rather than assuming mutual exclusion — but separation-of-duties logic (an officer must never review an application they are a party to) is enforced at the **application/business layer**, recorded here as a hard rule the schema must support, not prevent. This is exactly the kind of real-world case a naïve "applicants and officers are different tables" model silently makes impossible.

---

## 4. `ApplicantProfile`

| Field | Type | Notes |
|---|---|---|
| `user` | 1:1 FK → User (`CASCADE`) | |
| `full_name` | CharField | |
| `mobile` | CharField | |
| `aadhaar_hash` | CharField(64), indexed, nullable | **Salted SHA-256 of the Aadhaar number — for dedup only.** Never the raw number. (TDD §7) |
| `aadhaar_last4` | CharField(4), nullable | Display only |
| `aadhaar_verified_at` | DateTime, nullable | When offline-KYC signature was verified |

**Adversarial check — "the Aadhaar uniqueness trap."** The PRD wants Aadhaar-based deduplication, implying a UNIQUE constraint on the Aadhaar value. **This is a latent bug.** A salted hash makes the same Aadhaar hash to the same value *only if the salt is shared* — but a shared/static salt weakens the hash against a rainbow-table attack on a known-small input space (Aadhaar is a 12-digit number — only 10^12 possibilities, brute-forceable against a static salt). **Resolution and explicit open decision:** use a **single application-wide secret salt (pepper) stored in secrets management, not the DB**, so dedup works (same input → same hash) while the pepper's secrecy defends the small input space. A per-row random salt would defeat dedup entirely. This trade-off (dedup capability vs. ideal hashing hygiene) is a genuine security decision flagged for review — and a reason to ask MbPA whether Aadhaar dedup is even a hard requirement, since dropping it would let us use a far stronger per-row salt. **`aadhaar_hash` is therefore NOT marked UNIQUE at the DB level** — dedup is enforced as a checked business rule, so a hash collision or a legitimate edge case can be handled gracefully rather than throwing a raw IntegrityError at a citizen.

**Privacy/erasure:** these three Aadhaar fields are the system's most sensitive data. On a lawful erasure request (DPDP §12, where no retention obligation overrides), these specific fields can be nulled *without* deleting the `Application` records — separating identity erasure from statutory-record retention. This is why Aadhaar data lives on `ApplicantProfile`, not denormalised onto `Application`.

---

## 5. `OfficerProfile`

| Field | Type | Notes |
|---|---|---|
| `user` | 1:1 FK → User (`CASCADE`) | |
| `role` | choice: `estate_officer` / `junior_planner` / `deputy_planner` / `chairman` | The 4 roles (PRD §7) |
| `zone` | CharField, nullable | **PROVISIONAL** — see check below |
| `stream_specialisation` | M2M → Stream, blank | **PROVISIONAL** — see check below |
| `dsc_serial` | CharField, nullable | Serial of their registered Class-3 DSC, for signature attribution (TDD §8) |

**Adversarial check — "the queue-routing assumption."** The TDD flagged (open item) whether each role is one person or split by geography/stream. The schema must not *bake in* the single-person assumption, because un-baking it later means a migration touching live application-routing. **Resolution:** `zone` and `stream_specialisation` are included now as **nullable/optional** fields. If MbPA confirms one-person-per-role, they stay null and routing ignores them — zero harm. If MbPA confirms splitting, they're already present. Designing for the more flexible shape and leaving it inert is reversible; the opposite is not. Flagged provisional so review knows these are deliberately speculative.

---

## 6. `Application` — the spine

| Field | Type | Notes |
|---|---|---|
| `application_number` | CharField, unique, indexed | e.g. `MBPASPA2026061`. Generation rule in check below |
| `stream` | FK → Stream (`PROTECT`) | Can't delete a stream with live applications |
| `current_milestone_instance` | FK → MilestoneInstance (`SET_NULL`, nullable) | Denormalised pointer to "where it is now" |
| `status` | choice: `draft`/`submitted`/`under_review`/`approved`/`rejected`/`expired`/`withdrawn` | Top-level lifecycle state |
| `plpn` | CharField | Port Land Parcel Number (MbPA term, NOT CTS No.) |
| `plot_area_sqm` | Decimal | |
| `proposed_bua_sqm` | Decimal | Built-Up Area — drives all fee calc |
| `zonal_rrr` | Decimal, nullable | **Never system-prefilled** (PRD rule); manually entered |
| `is_deleted` / `deleted_at` | soft-delete | Statutory retention — never hard-deleted |
| `submitted_at` | DateTime, nullable | Null while draft |

**Adversarial check 1 — "the application-number race condition."** `MBPASPA2026061` looks like prefix + year + sequence. If the sequence is generated by counting existing rows (`COUNT(*) + 1`), two applications submitted in the same instant get the **same number** — a duplicate-key failure, or worse, a silent collision. The prototype (Apps Script, single-threaded) never hit this; Django under Gunicorn with multiple workers **will**. **Resolution:** the numeric sequence must come from a dedicated atomic source — a Postgres `SEQUENCE` or a `select_for_update()` row-lock on a counter table, **never** `COUNT(*)`. Recorded as a hard implementation constraint. Also flagged the year-rollover and sequence-reset rule as an open domain question (TDD §17 already lists this).

**Adversarial check 2 — "the draft that never was."** `status=draft` with `submitted_at=null` must be a valid, first-class state — an applicant starts a form and abandons it. The schema allows almost everything to be null in draft state. **Resolution:** validation is *milestone-gated*, not enforced as DB NOT-NULL — i.e., fields become required when the application *advances*, not at row creation. Enforcing NOT-NULL at the DB level would make saving a half-filled draft impossible, breaking the PRD's save-and-resume intake. This is a deliberate "permissive at rest, strict on transition" stance.

**Adversarial check 3 — "stream conversion."** The PRD's Addition/Alteration stream converts to the full lifecycle if work >50% original BUA. If `stream` is a plain FK, changing it mid-flight orphans the existing `MilestoneInstance` rows that belonged to the old stream's sequence. **Resolution:** stream conversion is modelled as an explicit, audited event — a new `stream` value plus a logged `AuditEvent` plus a reconciliation of `MilestoneInstance` rows (close obsolete ones, open new ones), never a silent FK overwrite. The schema supports it; the business layer orchestrates it. Flagged because the 50% threshold value itself is UPDR-2026-dependent.

---

## 7. `ApplicationParty` — the co-applicant model

The PRD is silent on multiple applicants; the TDD flagged this as provisional pending MbPA. A naïve single `owner` FK on `Application` cannot represent "an architect files on behalf of an owner," which is the *normal* case in Indian building permission practice (confirmed in the DPDP/representation research).

| Field | Type | Notes |
|---|---|---|
| `application` | FK → Application (`CASCADE`) | |
| `user` | FK → User (`PROTECT`) | |
| `party_role` | choice: `owner`/`architect`/`licensed_surveyor`/`poa_holder`/`co_owner` | |
| `is_account_of_record` | bool | Exactly one TRUE per application — who receives official comms |
| `authorisation_doc` | FK → DocumentUpload, nullable | The uploaded POA/authorisation (TDD: POA must be an uploaded scan, can't be e-only) |

**Adversarial check — "who is legally responsible, and who gets the email?"** With multiple parties, "send the applicant an email" becomes ambiguous, and "who is liable for a false declaration" becomes a real legal question. **Resolution:** `is_account_of_record` disambiguates communication (exactly one, enforced as a business rule). Legal responsibility is captured by recording *every* party with their role, so liability questions have a data trail rather than a single guessed "applicant." This is modelled as a through-table (M2M) precisely so the count of parties is open-ended. **Provisional** pending MbPA confirmation that multi-party filing is permitted — but building it in now is the reversible choice (a single-party application just has one `ApplicationParty` row with `party_role=owner`).

---

## 8. `Stream` & `Milestone` (reference tables)

These encode the TDD §11 decision (explicit data structure, no state-machine library) as data.

**`Stream`:** `code` (natural PK, e.g. `new_building`), `display_name`, `is_active`.

**`Milestone`:** `code` (natural PK, e.g. `S1`, `DEMO`), `display_name`, `default_output_certificate_type`.

**`StreamMilestone`** (ordered through-table): `stream` FK, `milestone` FK, `sequence_order` int, `sla_working_days` int (**nullable — populated from `ConfigParameter`/UPDR-2026**), `deemed_clearance_eligible` bool.

**Adversarial check — "the OC deemed-clearance safety rule."** TDD §11 hardcodes `deemed_clearance_eligible=False` for the OC milestone. If this lived only in code, a future well-meaning maintainer "fixing" the SLA sweep could flip it. **Resolution:** it's a column with a safe default of `False`, and the *seeding* of these rows sets OC explicitly to `False` with a code comment citing the life-safety reasoning. Belt and suspenders: the SLA sweep also independently refuses to auto-advance the terminal OC milestone regardless of the flag — two independent guards on the one transition that could let a building be occupied uninspected.

---

## 9. `MilestoneInstance` — live state

| Field | Type | Notes |
|---|---|---|
| `application` | FK → Application (`CASCADE`) | |
| `milestone` | FK → Milestone (`PROTECT`) | |
| `assigned_officer` | FK → OfficerProfile (`SET_NULL`, nullable) | Who owns the review now |
| `status` | choice: `not_started`/`in_progress`/`approved`/`returned_for_correction`/`deemed_approved`/`rejected` | |
| `started_at` | DateTime, nullable | When the SLA clock started |
| `due_at` | DateTime, nullable | Computed from `started_at` + SLA working days |
| `decided_at` | DateTime, nullable | |
| `is_deemed` | bool | TRUE if auto-advanced by SLA breach |

**Adversarial check 1 — "the working-day clock."** `due_at` can't be `started_at + N days` naïvely — SLA is in *working* days (excludes Sundays, second Saturdays, and port-specific holidays per TDD open item). Storing `due_at` as a wall-clock timestamp computed once at start is correct *only* if the holiday calendar is known at that moment and never revised. **Resolution:** `due_at` is computed and stored at transition time from a `Holiday` calendar source (a small reference table, not listed in the headline 19 but required — added below), so the SLA sweep does a cheap timestamp comparison rather than recomputing working-days on every daily run. If the holiday calendar changes retroactively, `due_at` is recomputed by an explicit job, not silently. **Adds a 20th entity: `Holiday` (`date`, `description`).**

**Adversarial check 2 — "the combined-clock milestone."** PRD §17.1: S1 is Estate Officer → JP with a *single combined 21-day clock across two officers*. A model assuming one officer per milestone instance breaks this. **Resolution:** `assigned_officer` is the *current* holder; the handoff from Estate Officer to JP within S1 is a reassignment event (logged in `AuditEvent`) that does **not** reset `started_at`. The clock belongs to the `MilestoneInstance`, not the officer — so reassignment never restarts it. This directly fixes the TDD-flagged officer-handover-SLA concern at the data level.

**Adversarial check 3 — "officer leaves mid-review."** `assigned_officer` uses `SET_NULL`, so deleting/deactivating an officer doesn't cascade-destroy the milestone. An unassigned-but-running milestone is a valid, queryable state (it needs reassignment) rather than a crash or an orphaned row.

---

## 10. `DocumentSlot` & `DocumentUpload`

**`DocumentSlot`** (reference matrix): `stream` FK, `milestone` FK, `document_type` CharField, `is_mandatory` bool, `applies_when` (nullable condition tag, e.g. linked to a conditional-clearance trigger). **The exhaustive contents of this table are UPDR-2026/forms-dependent (TDD open item)** — the table shape is final, the rows come later.

**`DocumentUpload`:**

| Field | Type | Notes |
|---|---|---|
| `application` | FK → Application (`CASCADE`) | |
| `document_slot` | FK → DocumentSlot (`PROTECT`, nullable) | Nullable for ad-hoc/extra uploads |
| `milestone_instance` | FK → MilestoneInstance (`SET_NULL`, nullable) | Which review cycle it was uploaded for |
| `r2_object_key` | CharField | The Cloudflare R2 storage key, NOT the file itself |
| `original_filename` | CharField | |
| `content_type` / `size_bytes` | CharField / BigInt | For the validation rules (TDD: explicit size/type validators) |
| `uploaded_by` | FK → User (`PROTECT`) | |
| `version` | int | See check |
| `is_deleted` / `deleted_at` | soft-delete | |

**Adversarial check — "re-upload after correction."** When an officer returns an application for correction and the applicant re-uploads, does the new file *overwrite* the old one? If yes, the audit trail of "what was originally submitted" is destroyed — unacceptable for a government record where the history of what was filed matters. **Resolution:** uploads are **versioned, never overwritten**. A correction creates a new `DocumentUpload` row with incremented `version` against the same slot; the prior version is soft-deleted (hidden from the active view, retained for audit). The R2 object is likewise not overwritten — a new key. This also defends against the "file path stored but file content not preserved" gap the audit-library research explicitly warned about.

---

## 11. `Concession` & `FeeAssessment`

**`Concession`:**

| Field | Type | Notes |
|---|---|---|
| `application` | FK → Application (`CASCADE`) | |
| `concession_type` | choice: `additional_fsi`/`open_space_shortfall`/`parking_waiver`/`height_relaxation`/`setback_relaxation` | |
| `detected_value` | Decimal | What the applicant's design has |
| `benchmark_value` | Decimal | What the norm is — **sourced from `ConfigParameter`, currently the prototype's "(demo)" placeholders** |
| `premium_amount` | Decimal | Computed premium |
| `source` | choice: `auto_detected`/`self_declared` | See check |

**`FeeAssessment`:**

| Field | Type | Notes |
|---|---|---|
| `application` | 1:1 FK → Application (`CASCADE`) | |
| `scrutiny_fee` / `security_deposit` / `debris_deposit` | Decimal | The base fees |
| `total_concession_premium` | Decimal | Sum of concession premiums |
| `master_challan_total` | Decimal | The grand total due at S2 |
| `computed_at` | DateTime | |
| `config_version` | FK → ConfigParameter version, or int | **Which rate-set produced this** — see check |

**Adversarial check 1 — "the fee that changed after assessment."** Fee rates and benchmarks live in `ConfigParameter` (externalised, revisable). If MbPA updates a rate, every *already-computed* `FeeAssessment` would silently become "wrong" relative to the new rate — and a citizen who already paid could be shown a different number on reload. **Resolution:** `FeeAssessment` stores the **actual computed amounts as a snapshot**, plus a `config_version` reference recording which rate-set was used. The assessment is immutable once payment is initiated. Recomputation only happens on an explicit re-trigger (e.g., the applicant revises their BUA), creating a new assessment, never mutating the paid one. This is the same snapshot principle as `Certificate` and is the single most important anti-footgun decision in the fee subsystem.

**Adversarial check 2 — "auto-detected vs. self-declared concession."** The prototype *auto-detects* concessions from design metrics against (placeholder) benchmarks; the PRD glossary implies the applicant declares them. These produce different liability if the auto-detection is wrong. **Resolution:** `source` records which path set each concession, so a disputed premium can be traced to "the system inferred this" vs. "the applicant declared this." Flagged as a TDD-level open product decision (auto vs. declared) — the schema stays neutral and records the truth either way.

---

## 12. `ConditionalClearance` — the NOC wizard state

Encodes the (undocumented-in-PRD, discovered-in-code) 7-question NOC wizard.

| Field | Type | Notes |
|---|---|---|
| `application` | FK → Application (`CASCADE`) | |
| `clearance_type` | choice: `railway`/`crz_mczma`/`mhcc_heritage`/`aai_aviation`/`mpcb`/`...` | |
| `is_triggered` | bool | Did the applicant's answers trigger this NOC? |
| `status` | choice: `not_required`/`pending_upload`/`uploaded`/`verified` | |
| `clearance_doc` | FK → DocumentUpload, nullable | |
| `trigger_metadata` | JSONField, nullable | e.g. AAI coordinate + AMSL data (research showed AAI is NOT a flat-height yes/no) |

**Adversarial check — "AAI isn't a yes/no."** Research established the AAI aviation clearance trigger is a coordinate-vs-Colour-Coded-Zoning-Map calculation, not a single height threshold, and CRZ is a distance-from-HTL/creek calculation. A plain boolean `is_triggered` throws away the inputs that justified the trigger. **Resolution:** `trigger_metadata` JSONField retains the actual inputs (coordinates, AMSL, computed permissible height) behind the boolean, so a trigger decision is auditable and re-checkable, and the V1 self-attested model can later be replaced by a real NOCAS API lookup without schema change (TDD §12 swappable-interface goal). JSONField is the right call here specifically because the trigger inputs differ in shape per clearance type — forcing them into typed columns would mean 5 different column sets on one table.

---

## 13. `Complaint`

| Field | Type | Notes |
|---|---|---|
| `application` | FK → Application (`CASCADE`) | |
| `origin` | choice: `applicant_raised`/`system_raised` | PRD's two complaint sources |
| `raised_by` | FK → User (`SET_NULL`, nullable) | Null for system-raised |
| `subject` / `body` | CharField / TextField | |
| `status` | choice: `open`/`in_progress`/`resolved`/`closed` | |
| `resolution_note` | TextField, nullable | |

**Adversarial check — "system-raised complaints have no human author."** `raised_by` must be nullable, and a null author must mean "the system," not "missing data." **Resolution:** `origin` carries the real meaning; `raised_by` null is valid *only* when `origin=system_raised`, enforced as a business rule. Avoids the trap of creating a fake "system user" row, while keeping the author trail honest for applicant-raised ones.

---

## 14. `Payment` — deliberately the trickiest

| Field | Type | Notes |
|---|---|---|
| `application` | FK → Application (`PROTECT`) | Can't soft-delete an application out from under a payment |
| `fee_assessment` | FK → FeeAssessment (`PROTECT`) | What this payment is against |
| `challan_reference` | CharField, indexed | The bank/offline challan number the applicant enters |
| `amount` | Decimal | |
| `status` | choice: `claimed`/`verified`/`rejected`/`mismatch` | |
| `verified_by` | FK → OfficerProfile (`SET_NULL`, nullable) | |
| `verified_at` | DateTime, nullable | |

**Adversarial check 1 — "the duplicate/invalid challan."** TDD §10 (integration) and the PRD both lack payment-failure handling. What stops an applicant entering a random or already-used challan number? **Resolution:** `challan_reference` is **indexed but NOT unique-constrained at the DB level** — because a hard UNIQUE throws an IntegrityError that surfaces as a 500 error to a citizen. Instead, duplicate/invalid detection is an explicit `status=mismatch` path: the system records the claim, flags it for officer verification, and shows the applicant a clean "this challan could not be verified" message. The PRD modelled payment as offline-challan-reference-entry (no live gateway, TDD-confirmed), so verification is inherently a human/manual step — the schema makes "claimed but not yet verified" and "claimed but mismatched" first-class states rather than failures.

**Adversarial check 2 — "payment privacy vs. retention conflict."** Research was explicit: payment data should generally be hard-deletable for privacy, yet this is a statutory record that must be retained. **Resolution:** `Payment` records the *challan reference and amount*, NOT card numbers, bank details, or any actual financial instrument data (there's no live gateway — none of that ever enters the system). Because the stored data is a reference number, not a financial instrument, the privacy pressure is far lower, and statutory retention wins cleanly. This is why the no-live-gateway scope decision (inherited from PRD) is quietly a *privacy* win, not just a scope simplification.

---

## 15. `Certificate` — the legal artifact

| Field | Type | Notes |
|---|---|---|
| `application` | FK → Application (`PROTECT`) | |
| `milestone_instance` | FK → MilestoneInstance (`PROTECT`) | Which milestone produced it |
| `certificate_type` | choice: `aip`/`development_permission`/`commencement`/`completion`/`occupancy`/`iod`/`...` | |
| `r2_object_key` | CharField | The signed PDF in R2 |
| `signature_verified` | bool | Was the DSC signature validated on receipt? (TDD §8) |
| `signed_by` | FK → OfficerProfile (`PROTECT`) | |
| `dsc_serial_used` | CharField | Captured from the signature for attribution |
| `issued_at` | DateTime | |
| `valid_until` | DateTime, nullable | AIP=2yr, Dev Permission=5yr (PRD) — null where N/A |
| `revoked_at` | DateTime, nullable | See check |

**Adversarial check 1 — "you cannot delete a government certificate."** `on_delete=PROTECT` on both FKs, and the entity is in the NEVER-deleted set. Even if an application is withdrawn, certificates already issued are historical fact. **Resolution:** certificates are never deleted or mutated. A certificate that should no longer apply is **revoked** (`revoked_at` set) — a new state, not a deletion. The signed PDF in R2 is likewise immutable.

**Adversarial check 2 — "the IOD coupling."** The prototype auto-issues an IOD on *every* rejection; TDD flagged whether IOD should be discretionary (open item). Modelling IOD as just another `certificate_type` keeps the schema neutral: whether one is auto-created on rejection or created by an explicit officer action is a *business-layer* decision, not baked into the data model. Either resolution of the open question works without a schema change.

**Adversarial check 3 — "certificate validity lapse."** `valid_until` enables the PRD's 2yr/5yr validity. The SLA sweep (or a sibling job) can find lapsed certificates. But "what happens on lapse" (auto-expire the application? require renewal?) is a UPDR-2026 open item — so the schema stores the date and the question of consequence is left to the business layer, not guessed.

---

## 16–17. `OtpToken` & `AuditEvent`

**`OtpToken`** (ephemeral, hard-deleted): `user` FK or `email` CharField, `code_hash` (the OTP is hashed, never stored plain), `purpose` choice (`login`/`status_lookup`/`signup`), `expires_at`, `consumed_at`. TTL is 10 minutes (prototype value). Hard-deleted because it's transient and contains a credential — no retention value, real privacy value in purging.

**Adversarial check — "OTP brute force."** A short numeric OTP with unlimited attempts is crackable. **Resolution:** schema includes `attempt_count`; the business layer locks after N failures. Storing `code_hash` not the raw code means a DB leak doesn't expose live OTPs.

---

## 18. `AuditEvent` — the immutable backbone (most safety-critical table)

| Field | Type | Notes |
|---|---|---|
| `actor` | FK → User (`PROTECT`, nullable) | Null = system action |
| `event_type` | choice: `milestone_approved`/`milestone_rejected`/`iod_issued`/`officer_reassigned`/`payment_verified`/`stream_converted`/`config_changed`/`deemed_clearance_fired`/`...` | |
| `target_type` / `target_id` | generic reference | What was acted on (application, milestone, etc.) |
| `summary` | TextField | Human-readable "what happened and why" |
| `metadata` | JSONField | Structured details |
| `created_at` | DateTime, indexed | Server-assigned |
| `sequence` | BigAutoField / Postgres sequence | Monotonic ordering — see check |

**Adversarial check 1 — "append-only must be enforced at the DB, not just in code."** Research was explicit: blocking updates/deletes only in the application "leaves a back door." **Resolution, layered:**
1. The model overrides `save()` to forbid updates (only inserts) and has no delete path in the app.
2. **At the database level**, the deployment grants the application's DB role INSERT-only (no UPDATE/DELETE) on this table, and/or a Postgres trigger raises on UPDATE/DELETE. This is the real enforcement; the app-level guard is convenience.
3. This is recorded as a **deployment requirement**, not just an ORM detail — the DB user the app connects as must be configured with restricted grants on `auditevent`.

**Adversarial check 2 — "cascade-delete eats the audit trail."** Research surfaced exactly this: generic-relation audit fields cascade-delete history when the target is deleted. **Resolution:** `AuditEvent` is **owned by nothing** — it uses a *non-cascading* generic reference (`target_type`/`target_id` as plain fields, not a Django `GenericForeignKey` with a `GenericRelation` back-reference). Deleting (or soft-deleting) any target leaves its audit events fully intact. The audit log references the world; the world does not own the audit log.

**Adversarial check 3 — "clock skew breaks ordering."** Research warned against wall-clock ordering across hosts. **Resolution:** ordering relies on the monotonic `sequence` (a DB sequence), not `created_at`, so even if a server's clock is wrong, the *order* of events is authoritative. `created_at` is for human reading; `sequence` is for truth.

**Adversarial check 4 — "the audit log vs. erasure conflict."** If an applicant exercises Aadhaar erasure (§4), but an `AuditEvent` metadata blob captured their Aadhaar... that's a leak surviving erasure. **Resolution:** `AuditEvent.metadata` must **never** store raw Aadhaar, full payment instruments, or OTP codes — only references/IDs and non-identifying facts. Recorded as a hard rule on what may be written to audit metadata. This is the audit-vs-privacy reconciliation the research flagged (encrypt/reference sensitive payloads, retain only non-identifying metadata).

---

## 19. `ConfigParameter` — how every UPDR-2026 value stays out of the schema

| Field | Type | Notes |
|---|---|---|
| `key` | CharField, indexed | e.g. `scrutiny_fee_per_sqm`, `benchmark_fsi`, `sla_days.S2`, `additional_fsi_premium_multiplier` |
| `value` | Decimal or CharField/JSON | |
| `effective_from` | DateField | |
| `version` | int | |
| `is_active` | bool | |

**Adversarial check — "the whole reason this table exists."** Every value the TDD flagged as UPDR-2026-dependent (fee rates ₹50/₹10/₹20, the demo benchmarks FSI 1.5 / open space 30% / etc., SLA working-day counts, concession multipliers 1.10/0.25/0.40) lives here as data, **versioned**. This is what lets the schema be "final in shape, pending in values." When real UPDR-2026 numbers arrive, they're inserted as a new version — no migration, no code change, and `FeeAssessment.config_version` records which version any given assessment used (the §11 snapshot principle). The prototype's fatal flaw (rates duplicated across backend and frontend, hardcoded) is structurally impossible here: one versioned source, referenced everywhere.

---

## 20. Cross-Cutting Adversarial Findings (system-level, not per-entity)

1. **The dual-write problem.** Research warned: writing to an entity table and separately to the audit table risks divergence if one fails. **Resolution:** any state transition + its `AuditEvent` must occur in the **same database transaction** (`transaction.atomic()`), so either both commit or neither does. Recorded as a hard implementation rule.

2. **Soft-delete is not uniform — and that's deliberate.** A blanket soft-delete base model (the common Django pattern) would be *wrong* here: `Certificate` and `AuditEvent` must never be deletable at all; `OtpToken` and erased Aadhaar fields must be *hard*-deletable for privacy; statutory records (`Application`) must be soft-deleted/retained. Applying one base class everywhere would violate at least one of these. **Resolution:** delete policy is assigned per-entity per the §1 table, justified by whether the data is statutory (retain), sensitive (purge), or a legal artifact (immutable).

3. **Separation of duties** (an officer must not review an application they're a party to) spans `User`, `ApplicationParty`, and `MilestoneInstance.assigned_officer`. The schema *supports representing* this; enforcement is a business-layer rule checked at assignment and decision time. Recorded so it isn't lost.

4. **The "draft" lifecycle** means most FKs and fields on `Application` and children are nullable-at-rest and validated-on-transition. This is a coherent global stance (permissive at rest, strict on advance), not field-by-field laxity.

5. **Timezone.** All timestamps stored UTC (Django `USE_TZ=True`); IST is a display concern. SLA "working day" cutoffs (TDD open item: does 11:58 PM count as that day?) resolve against IST business hours at the business layer, but storage stays UTC to avoid DST-free India's only real risk: mixed-offset comparisons.

---

## 21. What Still Needs MbPA Before This Is Final

The schema *shape* is locked and stress-tested. These items fill *values/rows*, not structure — none require reshaping the tables above:

- Exhaustive `DocumentSlot` rows per (stream, milestone) — needs the prescribed forms + real application files
- Real `ConfigParameter` values (all fee rates, benchmarks, SLA day counts) — needs UPDR-2026
- Confirmation of the **multi-party filing** model (§7) — currently provisional
- Confirmation of **officer zone/stream splitting** (§5) — currently provisional/inert
- Whether **Aadhaar dedup** is a hard requirement (§4) — affects the salt/pepper security trade-off
- Resolution of **IOD auto-vs-discretionary** (§15) and **concession auto-vs-declared** (§11) — schema is neutral, business rule pending
- **Application-number** sequence-reset/rollover rule (§6)
- **Holiday calendar** source/contents for the `Holiday` table (§9)
- Certificate **lapse consequences** (§15) — schema stores the date, behaviour is TBD

**Net:** every open item is a value or a business rule, not a structural unknown. That was the goal — a schema that absorbs the pending domain answers as *data* rather than demanding a redesign when they arrive.
