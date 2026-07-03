# Runbook: DSC Unavailable

**Scenario:** The Digital Signature Certificate (DSC) service is unavailable, the trust root file
is missing or corrupt, or `receive_signed_certificate()` raises `OSError` / `ValueError` during
verification of an uploaded signed PDF.

---

## Symptoms

- `POST /api/certificates/<number>/<pk>/receive-signed/` returns HTTP 500 or 400.
- Django logs show `OSError: [Errno 2] No such file or directory: 'cca_trust_root.der'`
  or `SignatureVerificationError: ...` from the `apps/certificates/services.py` path.
- Officers see "Upload failed" in the Certificates panel of the Officer Console.

---

## Immediate triage

1. **Check the trust root file exists:**
   ```bash
   ls -lh $DSC_TRUST_ROOT_PATH      # default: cca_trust_root.der
   ```
   If missing → proceed to "Trust root missing" below.

2. **Check the error detail** in Django logs (Sentry / stdout):
   - `OSError` → file missing or wrong path (see `DSC_TRUST_ROOT_PATH` env var).
   - `ValueError: signature invalid` → certificate was modified after signing, or wrong root.
   - `ValueError: certificate expired` → signer's DSC has expired; escalate to applicant.

3. **Confirm the DSC_TRUST_ROOT_PATH env var** points to the correct `.der` file:
   ```bash
   echo $DSC_TRUST_ROOT_PATH
   ```

---

## Mitigations by cause

### Trust root file missing

The CCA root bundle is a deployment prerequisite — it is not bundled in the repo (binary,
and subject to CCA rotation). Obtain the current CCA India root bundle from
https://cca.gov.in/root-certifying-authority.html, save as `cca_trust_root.der`, and
restart the application.

No code change needed. `apps/certificates/checks.py` (`certificates.E001`) fails
`manage.py check` whenever `DSC_TRUST_ROOT_PATH` doesn't parse as a real DER X.509
certificate and `DEBUG=False` — this is exactly that check firing, catching the shipped
`cca_trust_root.der` placeholder (or a missing/corrupt real one) before it can silently
reach production, the same way `identity.E001` does for `AADHAAR_PEPPER`.

### Signer DSC expired

The applicant's DSC has expired. This is not an application error. Return the certificate
upload via `return_for_correction` action on the milestone so the applicant can re-sign with
a valid DSC.

### CCA root rotated

CCA periodically rotates root certificates. If existing `.der` is present but verification
fails for all new uploads (while old ones passed), the CCA root may have been superseded.
Download the new bundle, swap the file, and restart. Verify against a known-good test PDF.

---

## Recovery without DSC (degraded mode)

There is no bypass path in the verification code itself — `receive_signed_certificate()`
always calls the verifier when `DSC_TRUST_ROOT_PATH` is set. If the trust root cannot be
supplied immediately:

1. Set `DSC_TRUST_ROOT_PATH=""` in the environment to disable verification.
2. Restart the application **without running `manage.py check`/`manage.py migrate`
   first** — `certificates.E001` (see above) will now correctly refuse to pass a
   deploy-time check with an empty/invalid trust root when `DEBUG=False`. That check
   exists specifically so this exact "quietly leave it unset" state doesn't linger
   unnoticed; if your deploy/restart pipeline runs `manage.py check` as a gate (this
   project's CI does — see `.github/workflows/ci.yml`), that gate will now fail here,
   which is intentional. A raw `gunicorn`/`runserver` process restart does not itself
   invoke Django's check framework, so the application will still boot — but treat the
   check failure as a loud, correct reminder that degraded mode is active, not a bug to
   route around.
3. Officers can then accept signed PDFs without cryptographic verification (manual
   visual inspection required instead).
4. **Re-enable DSC_TRUST_ROOT_PATH as soon as the root bundle is available**, and confirm
   `manage.py check` passes again before the next normal deploy. Log the window during
   which verification was disabled in the incident record.

---

## Post-incident

- Confirm the root bundle was updated (not just restarted with the same broken file).
- Run a test upload with a signed PDF whose signature you control to verify end-to-end.
- Document the outage window in the incident log.
- If degraded mode was used, audit all certificates accepted during that window.
