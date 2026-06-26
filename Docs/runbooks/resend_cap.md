# Runbook: Resend OTP Email Cap / Delivery Failure

**Scenario:** OTP emails are not being delivered — either Resend has hit a rate limit,
the API key is invalid, the domain is unverified, or Resend is experiencing an outage.

---

## Symptoms

- Users report never receiving OTP emails after `POST /api/identity/login/` or
  `POST /api/identity/signup/`.
- `POST /api/identity/otp/resend/` returns HTTP 200 but no email arrives.
- Django logs show `resend.exceptions.ResendError`, HTTP 429, 401, 403, or 5xx from
  Resend, originating from `apps/identity/services.py` in the OTP send path.

---

## Immediate triage

1. **Check Resend status:** https://resend-status.com — look for delivery delays or API
   incidents.

2. **Check Django logs** for the exact Resend error code:
   - `401 Unauthorized` → API key invalid or revoked.
   - `403 Forbidden` → domain not verified for the From address, or account suspended.
   - `429 Too Many Requests` → rate limit hit (see limits below).
   - `5xx` → Resend-side outage.

3. **Confirm the RESEND_API_KEY** env var is set and begins with `re_`:
   ```bash
   python manage.py shell -c "
   from django.conf import settings
   k = settings.RESEND_API_KEY
   print('set' if k else 'MISSING', k[:5] if k else '')
   "
   ```

4. **Check Resend dashboard** (https://resend.com/overview) for:
   - Bounce/complaint rates (high rates trigger automatic account holds).
   - Remaining daily send quota.
   - Domain verification status for the `From` domain.

---

## Resend free-tier limits

| Metric | Limit |
|--------|-------|
| Emails per day | 100 |
| Emails per month | 3,000 |
| Rate (burst) | ~10/sec |

If the portal is in production and exceeding the free tier, upgrade the Resend plan.

---

## Mitigations by cause

### API key invalid / rotated

1. In the Resend dashboard, create a new API key with Send access.
2. Update `RESEND_API_KEY` in `backend/.env`.
3. Restart the application.
4. Test: trigger a login OTP and confirm email delivery.

### Domain not verified

The `From` address domain must be verified in Resend → Domains. If domain verification
lapses or the DNS records are removed:

1. Re-verify the domain in Resend by re-adding the required DNS records.
2. Confirm DNS propagation (`dig TXT <resend-verify-domain>`).
3. Test OTP delivery.

See `Docs/runbooks/resend_dns.md` for the full DNS setup reference.

### Rate limit (429)

The portal hit the daily or burst send rate. Options:
- **Immediate:** OTP emails will resume after the daily reset (midnight UTC). Users who
  cannot log in should be directed to try again later.
- **Short term:** Upgrade the Resend plan to increase daily quota.
- **Code-level:** If a test or batch process is hammering the OTP endpoint, identify and
  throttle the source. The `OTPDevice` model enforces a `max_attempts` check but does not
  rate-limit sends per email address. Consider adding send-rate throttling in
  `apps/identity/services.py` if needed.

### Resend platform outage

No application-level action. OTP emails will queue and deliver when Resend recovers —
**the OTP token remains valid in the database** for the configured TTL (default: 10 minutes).
If the token expires before delivery, the user must restart the login flow.

Check https://resend-status.com and communicate to affected users that email delivery is
temporarily delayed.

---

## Fallback: OTP delivery without email

There is no SMS fallback configured. If email delivery is down and an officer or admin
urgently needs access:

1. Locate the `OTPDevice` row for the user in the Django admin or via shell:
   ```python
   from apps.identity.models import OTPDevice
   dev = OTPDevice.objects.filter(user__email='user@example.com').latest('created_at')
   print(dev.token, dev.expires_at)
   ```
2. Provide the token out-of-band (secure channel only — phone call or in-person).
3. Log the manual delivery in the incident record.
4. Do not use this for applicant accounts — only internal officers.

---

## Post-incident

- Confirm Resend account is in good standing (no bounces, no complaints).
- Confirm domain DNS records are still present.
- Check daily send quota usage against expected login volume.
- If rate limit was reached, review whether the current plan is sufficient for production load.
