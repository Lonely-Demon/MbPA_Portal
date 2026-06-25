# MbPA Building Permission Portal — Domain Knowledge Question Log

**Status as of this update:** General/comparative legal research has been done independently (not yet from MbPA). MbPA-confirmed answers via your friend are still expected Monday. I spot-checked the two highest-stakes specific claims in that research against current sources myself — the MPA Act 2021 Adjudicatory Board/Supreme Court appeal route (§1.1 below) and the DPDP Act phased-enforcement dates (§9.3 below) both check out accurately. The rest is internally consistent and properly distinguishes "confirmed law" from "comparative practice only" — I didn't re-verify every citation, but nothing I checked or cross-referenced contradicts it.

**Status legend:**
- ✅ **RESOLVED** — confirmed by general/central law, applies regardless of what UPDR-2026 itself says
- 🔶 **PARTIAL** — comparative principle/practice confirmed, but the UPDR-2026-specific number or clause is still unconfirmed
- ⬜ **OPEN** — research couldn't touch this; still fully needs MbPA / your friend / internal docs

---

## 0. Source Documents Needed

⬜ **0.1.** UPDR-2026 actual text. **Still fully open — confirmed not publicly available anywhere** (mumbaiport.gov.in, shipmin.gov.in, PIB, Gazette all searched, zero hits). What exists publicly instead: the **Indian Ports Act, 2025** (No. 27 of 2025, replaces the 1908 Act, governs ports generally) and the national **Draft Indian Port Rules, 2026** (MoPSW, pre-published 23 Jan 2026). I separately confirmed the Indian Ports Act 2025 does **not** replace the **Major Port Authorities Act, 2021** — MbPA's board/governance structure still runs under the MPA Act 2021, which remains the right anchor statute. UPDR-2026 itself, whatever it is, is still a closed book until MbPA hands it over.

⬜ **0.2.** Paper-based SOP. Still open.

⬜ **0.3.** Real historical application files. Still open.

⬜ **0.4.** Prescribed government forms (Form 4A/4B, Annexure-10/14). Still open.

🔶 **0.5.** Fee notification/circular. MbPA publishes Scale of Rates (SOR) and lease/wharfage gazette notifications publicly (mumbaiport.gov.in) — but the specific building-permission fee circular (₹50/₹10/₹20 per m² etc.) isn't among what's publicly indexed. Still needs the actual circular from MbPA.

⬜ **0.6.** Org chart / role staffing. Still open.

---

## 1. Statutory & Legal Validity

✅ **1.1.** Online submission validity — **RESOLVED.** IT Act 2000 Sections 4–6 give electronic filing, electronic signatures, and government e-services full statutory recognition; Section 6 specifically authorises electronic filing of applications and grant of permits "where the appropriate Government prescribes the manner." A portal is a legally valid filing channel, **but** Section 9 means this isn't automatic — MbPA should affirmatively adopt it via Board resolution + published notification (and may want to keep a documented manual fallback unless something mandates digital-only).

✅ **1.2.** Digital certificate validity — **RESOLVED.** IT Act Sections 5 & 15: a document with a valid electronic signature is legally equivalent to hand-signed. Practical standard is a **Class-3 Digital Signature Certificate (DSC)** for the issuing officer, from a CCA-licensed Certifying Authority. Comparable systems already do this live: Maharashtra MIDC's BPAMS mandates DSC-only issuance; MCGM's AutoDCR digitally signs CC/OC; Telangana's TS-bPASS issues OC online on self-certification. **Action item this confirms:** the rebuild needs real DSC integration for officer-issued certificates, not just a PDF with a logo.

🔶 **1.3.** Appeal mechanism above Chairman — **RESOLVED at the statute level, with a real open question underneath.** I verified this one myself: under the MPA Act 2021, the **Adjudicatory Board** (Section 54, civil-court powers, Presiding Officer = retired SC/HC judge) hears grievances per **Section 32**, with appeal from the Adjudicatory Board going **directly to the Supreme Court within 60 days** (Section 58/independently confirmed). The genuinely open part: Section 32 is explicitly scoped to the Board's actions "under sections 22 to 31" — land, assets, tariff — and it's untested whether a building-permission refusal falls within that scope. If it doesn't, the backstop is ordinary High Court writ jurisdiction (Article 226), not the Adjudicatory Board. **This needs an explicit answer from MbPA/legal counsel: does a rejected building-permission application route through the Adjudicatory Board, or straight to writ?** The Ministry (MoPSW) is confirmed *not* a general appellate body over individual permissions either way.

✅ **1.4.** RTI applicability — **RESOLVED.** MbPA is a statutory body established by Parliament, substantially Centrally funded — squarely a "public authority" under RTI Act Section 2(h). Must designate a CPIO, comply with Section 4 proactive disclosure, answer within 30 days. Retention is governed by the **Public Records Act, 1993** (applies to Central statutory bodies) — needs a nominated Records Officer; unauthorised destruction is itself penalised (up to 5 years). DPDP retention rules (below) have to be reconciled with this, not override it.

🔶 **1.5.** `.gov.in`/NIC hosting mandate — **RESOLVED as expectation, not hard statute.** GIGW 3.0 (MeitY/NIC/STQC/CERT-In jointly) expects `gov.in`/`nic.in` hosting, NIC/NICSI or MeitY-empanelled Government Community Cloud, plus a CERT-In safe-to-host certificate and STQC "Certified Quality Website" sign-off before go-live. It's administrative guidance rather than a standalone law, but for a statutory port authority's permission portal, deviating from it is a real compliance flag, not just a style choice. MbPA's existing site is already NIC-hosted on `gov.in`, which is the strong signal this portal should follow the same path.

---

## 2. Roles, Actors & Organization

⬜ **2.1.** Fire Officer / undefined conditional-clearance roles — still open as a **design decision** (confirm self-attested checklist vs. real reviewer role), but general Fire-NOC trigger thresholds are now known (see §4 below) to inform the conversation.

⬜ **2.2.** Officer handover/leave reassignment. Still open — internal HR/process question.

⬜ **2.3.** Role splitting by geography/stream/plot size. Still open.

---

## 3. Fees, Concessions & the FSI/Setback Benchmark Engine

⬜ **3.1.** Real UPDR-2026 benchmark values (FSI/open-space/height/setback/parking). **Confirmed not publicly derivable — still fully open**, needs UPDR-2026 text directly.

⬜ **3.2.** Whether benchmarks vary by zone/use/plot size. Still open — same blocker.

🔶 **3.3.** Zonal RRR sourcing — **partially resolved, with a real distinction surfaced.** Maharashtra's Ready Reckoner Rate (Annual Statement of Rates) is published by IGR Maharashtra and looked up at `easr.igrmaharashtra.gov.in`, revised annually (effective 1 April, per district/taluka/CTS number). **But** whether MbPA's fee formula actually uses *that* RRR, or its own internal Scale-of-Rates-equivalent for port land, is unconfirmed — these are legally distinct instruments. **Ask specifically: does the Zonal RRR field in this portal mean the IGR e-ASR rate, or an MbPA-internal land-value schedule?**

⬜ **3.4.** Whether the ₹50/₹10/₹20 rates and 110%/25%/40% coefficients vary by stream. Still open.

⬜ **3.5.** Refund timing/forfeiture conditions for security/debris deposits. Still open.

🔶 **3.6.** BUA definition — **comparative answer only, not confirmed for UPDR-2026.** Under UDCPR/NBC practice generally: lift wells, lift machine rooms, stairwells, basements/stilts/podiums used solely for parking, service floors, and plant rooms are typically *excluded* from FSI-counted BUA; open balconies are typically *included*. This is genuinely just "how comparable regulations usually do it" — UPDR-2026 could differ, and given port land's industrial/dock-operational character, it plausibly does.

---

## 4. Conditional NOCs / Clearance Wizard

🔶 **4.1.** Completeness of the 7-trigger list — **still open on completeness**, but the listed 5 (Railway, CRZ/MCZMA, MHCC heritage, AAI/aviation, MPCB) are all real, correctly-named clearance regimes. Coast Guard, Customs, and Tree Authority involvement for port land specifically is **not confirmed either way** — worth asking directly.

✅ **4.2.** Trigger conditions — **RESOLVED in detail for two of the five, genuinely valuable findings:**
  - **AAI/aviation:** Height NOC needed up to **20 km from a VFR aerodrome, 56 km from an IFR aerodrome**, via NOCAS (`nocas2.aai.aero`). It is **not a flat height number** — permissible height is the Permissible Top Elevation for that specific grid cell on the airport's Colour Coded Zoning Map (CCZM), in WGS-84 coordinates, computed as CCZM elevation minus site elevation (AMSL). Local approval without AAI referral is possible only if requested height is below the CCZM limit for that grid (capped at 150m via CCZM; above that, NOCAS application is mandatory regardless). NOC validity: 8 years (12 years for masts/chimneys/transmission lines). Mumbai Port sits within Mumbai/Navi Mumbai aerodrome safeguarding radii, so this genuinely applies — **the current single "yes/no + flat height" question in the prototype is the wrong model; it needs a coordinate + AMSL lookup against the CCZM, not a single number.**
  - **CRZ/MCZMA:** Triggered within **500m of the High Tide Line** on the seafront, **50m along tidal creeks** (100m until the relevant Coastal Zone Management Plan is approved). MCZMA issues the NOC for CRZ-II/III; MoEFCC for CRZ-I/IV. Port-master-plan alignment under the MPA Act 2021 also applies.
  - Railway, MHCC heritage, and MPCB trigger-distance specifics: still open, not resolved by general research.

⬜ **4.3.** Self-attested checklist vs. real reviewer gate. Still a design decision, open.

---

## 5. Document Slots & Prescribed Formats

⬜ **5.1–5.3.** All still fully open — these are internal-document questions, exactly as expected; general legal research has nothing to add here.

---

## 6. Stream-Specific Rules

⬜ **6.1–6.7.** All confirmed still fully open — every one of these (50% conversion threshold, 90% infra rule's milestone gate, regularisation CRZ-block automation logic, DEMO-step SLA days, Temporary Permission renewal, Special Building height/hazard classification) requires UPDR-2026 text directly. No general law substitutes for these. Nothing lost — this was always going to need MbPA, not research.

---

## 7. Milestone Mechanics, SLA & Deemed Clearance

✅ **7.1.** Deemed-clearance scope re: Occupancy Certificate — **this is the most important finding in the whole research pass.** Across Indian Ease-of-Doing-Business building law, **final occupancy/safety sign-off is consistently excluded from silent time-lapse deemed-approval.** Telangana's TS-bPASS Act, 2020 is the explicit model: building permission itself deems-approves on a 21-day time lapse, but the Occupancy Certificate is issued only via affirmative self-certification by the owner *and* a Licensed Technical Personnel, who are personally and statutorily liable for false declarations — never by silent deeming. Smallest plots are simply exempted from needing an OC at all; none are auto-granted one by default. **Recommendation: design the rebuild to exclude S7/OC from deemed-clearance by default, and treat any UPDR-2026 confirmation otherwise as the exception that needs explicit, written sign-off from MbPA — not the default assumption.** This is a life-safety question, not a style preference, and the comparative law is unusually consistent on it.

✅ **7.2.** "Working day" definition — **RESOLVED at the general level.** Statutory anchor is the explanation to Section 25 of the Negotiable Instruments Act, 1881: Sundays + any day gazette-notified as a public holiday by Central/State Government. Second Saturdays are holidays for government offices by separate notification, not the NI Act text itself. MbPA, as a Central statutory body, almost certainly publishes its own annual holiday list — **the SLA clock should reference that specific MbPA-published calendar, not a generic state list** — but the actual MbPA list itself is still needed from your friend.

⬜ **7.3.** SLA day-counting cutoff time. Still open — internal operational question.

⬜ **7.4.** Certificate lapse/renewal mechanics under UPDR-2026. Still open.

⬜ **7.5.** Milestone reopening after approval. Still open.

---

## 8. Applicants, Representation & Identity

🔶 **8.1.** Co-applicants / representation — **comparative practice confirmed, not UPDR-2026-specific.** Under typical Maharashtra DCR/UDCPR and MCGM AutoDCR practice, a registered Architect or Licensed Surveyor files on the owner's behalf with the owner's authorisation + ownership documents attached; both the owner and the licensed professional carry accountability, and licensing authorities can warn or terminate a professional's license for false representations (MCGM does this routinely via AutoDCR). General practice, not a confirmed UPDR-2026 rule, but a reasonable default to design toward pending MbPA confirmation.

✅ **8.2.** Is a POA/authorisation letter required and verified — **RESOLVED on formality, even though "is it required" stays comparative.** The IT Act's First Schedule specifically *excludes* a Power of Attorney (under the Powers of Attorney Act, 1882) from pure electronic execution. **The portal should accept an uploaded scan of a traditionally executed/notarised POA — it cannot just be an e-form filled out on-screen.** That's a real implementation constraint regardless of what UPDR-2026 itself says about whether a POA is required at all.

⬜ **8.3.** Mid-application ownership transfer. Still open.

---

## 9. Aadhaar, Privacy & DPDP Act 2023

✅ **9.1.** Full Aadhaar storage — **RESOLVED, and this is now a confirmed compliance defect in the prototype, not just a best-practice suggestion.** UIDAI mandates that any full Aadhaar number held in structured electronic form must sit in an encrypted **Aadhaar Data Vault (ADV)** behind a reference token, with masked (last-4) display as the UI standard — never the full number in an ordinary application database. The governing instruments: UIDAI Circular K-11020/205/2017, tightened by Circular No. 8 of 2025 (18 Jul 2025) and FAQs (3 Nov 2025), which restrict ADV hosting to the entity's secure premises, a MeitY-empanelled Government Community Cloud, or ADV-as-a-service, with HSM-based AES-256 encryption.

✅ **9.2.** AUA/KUA licensing requirement — **RESOLVED.** To authenticate or verify Aadhaar directly, an entity must operate as (or through) an Authentication User Agency / e-KYC User Agency under the Aadhaar Authentication Regulations 2021. **The realistic path for MbPA is almost certainly *not* becoming its own AUA/KUA** — it's routing through an existing AUA/KUA, or using offline/QR-based Aadhaar verification, which avoids holding the full number at all. This should shape how identity verification gets rebuilt, not just where Aadhaar gets stored. Worth knowing the actual penalties for getting this wrong, not just "it's bad": Aadhaar Act Section 37 (unauthorised disclosure) — up to 3 years imprisonment + fine up to ₹10,000 (₹1 lakh for a company); Section 38 (unauthorised access/tampering of CIDR data) — up to 3 years + fine **not less than ₹10 lakh**; Section 42 residuary offence — up to 1 year + fine up to ₹25,000 (₹1 lakh for a company). This is personal criminal liability for whoever in the organization is responsible, not just an institutional fine.

✅ **9.3.** DPDP obligations specifics — **RESOLVED in detail, and one finding actually *simplifies* the design:**
  - **Section 7(b)** makes government processing for "provision of any subsidy, benefit, service, certificate, licence or permit" a **legitimate use not requiring consent.** A building-permission/certificate-issuance portal squarely qualifies — **you likely don't need a full consent-capture flow for the core statutory function**, though the DPDP Rules' Second Schedule still requires notice, data minimisation, purpose limitation, retention limits, and reasonable security regardless.
  - **Section 12**: Data Principal has the right to correction, completion, and erasure (erasure only where retention isn't required by law — which, per §1.4 above, it usually will be for statutory records).
  - **Section 8(6) + Rule 7**: breach notification — intimate the Data Protection Board and affected Data Principals "without delay," with a **detailed report to the Board within 72 hours** of becoming aware.
  - **Section 8(7)/(8)**: erase data once consent is withdrawn or purpose served, unless legally required to retain — reconcile this against Public Records Act/RTI retention, don't let it silently override statutory retention.
  - **Phasing (I independently verified this):** DPDP Rules notified 14 Nov 2025 (Data Protection Board operational immediately); Consent Manager provisions from 13–14 Nov 2026; **full substantive compliance obligations — notice, consent, breach reporting, retention/erasure, data-principal rights — from 13–14 May 2027.** Designing for this now, ahead of the hard deadline, is the right call rather than waiting.

⬜ **9.4.** Internal correction-path workflow for wrong applicant details post-submission. Still open as an implementation detail, though DPDP §12 confirms the legal *right* to correction exists — the portal's actual UX for it still needs designing.

---

## 10. Payments

⬜ **10.1–10.3.** All still fully open. This entire section is internal MbPA process — general legal research correctly had nothing to contribute here.

---

## 11. Inspections

⬜ **11.1.** Who conducts inspections / separate field-inspector role. Still open.

🔶 **11.2.** Fire NOC / high-rise trigger thresholds — **comparative answer only.** Under the Maharashtra Fire Prevention and Life Safety Measures Act, 2006 + NBC 2016 Part 4: "high-rise" generally triggers at **15m (residential) / 24m (other)**; "special building" status can also trigger on occupancy/floor area (e.g., ≥500 sqm on any floor for certain occupancies) regardless of height. Fire NOC is required before OC and needs **annual renewal** in Maharashtra (non-compliance: fine up to ₹50,000 + up to 1 year imprisonment). A recent state amendment raised permissible heights for some uses (educational to 45m, automated parking to 100m). **None of this is confirmed as UPDR-2026's actual threshold** — it's the comparative baseline to check against once UPDR-2026 is in hand.

---

## 12. Portal-Specific Decisions (code vs. PRD conflicts — still need an actual decision)

⬜ **12.1.** Stream & Fee Planner public vs. login-gated. Still a pure product decision — not something legal research resolves.

🔶 **12.2.** IOD auto-generation on every rejection vs. officer discretion. Not directly resolved, but the §7.1 finding above (favor affirmative, accountable human decisions over silent automation wherever the outcome is consequential) is a relevant steering principle here too — leans toward keeping IOD as a deliberate, visible officer action rather than something that happens invisibly on every rejection. Still ultimately MbPA's call.

⬜ **12.3.** Fee-rule single-sourcing. Pure engineering decision, unaffected by this research, unchanged from before.

---

## 13. Terminology Sanity Check

⬜ **13.1–13.2.** Still fully open — internal terminology/numbering scheme, as expected.

---

## Updated Summary

| Status | Count |
|---|---|
| ✅ Resolved (general law, holds regardless of UPDR-2026) | 10 |
| 🔶 Partial (comparative only, still needs UPDR-2026 confirmation) | 9 |
| ⬜ Open (needs MbPA / internal docs — research couldn't touch) | 36 |
| **Total tracked items** | **55** |

**What this changes for Monday:** the legal/regulatory background is now mostly settled — what's left for your friend to chase at MbPA is almost entirely **the UPDR-2026 text itself, internal SOPs/org structure, and the handful of pure product decisions in §12.** That's a much shorter, much more concrete list to walk in with than "55 open questions." I'd suggest leading with **§0.1 (UPDR-2026 text)** and **§1.3 (which appeal route applies)** — almost everything else either resolves itself once UPDR-2026 is in hand, or is now answered well enough to build against.
