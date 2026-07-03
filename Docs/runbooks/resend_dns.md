# Resend Email Setup Runbook

Resend's free tier allows **100 emails/day** — a hard production blocker for
high-volume OTP flows. Review AC-23 in the build plan before going live.

## 1. Create a Resend account and verify your domain

1. Sign up at [resend.com](https://resend.com).
2. Go to **Domains** → **Add Domain** → enter `mbpa.example.gov` (replace with
   your actual domain).
3. Resend will display DNS records to add. Add all of them to your DNS provider:

| Type | Name | Value |
|------|------|-------|
| MX | `send.mbpa.example.gov` | `feedback-smtp.us-east-1.amazonses.com` (Resend provides exact value) |
| TXT | `send.mbpa.example.gov` | SPF record (Resend provides exact value) |
| CNAME | `resend._domainkey.mbpa.example.gov` | DKIM record (Resend provides exact value) |
| TXT | `_dmarc.mbpa.example.gov` | `v=DMARC1; p=quarantine; rua=mailto:dmarc@mbpa.example.gov` |

Wait for all records to verify (green checkmarks) before sending live email.

## 2. Create an API key

1. Go to **API Keys** → **Create API Key**.
2. Name it `mbpa-portal-prod`, permission: **Sending access**.
3. Copy the key — shown once.

## 3. Wire environment variables

```
RESEND_API_KEY=re_xxxxxxxxxxxxxxxxxxxx
DEFAULT_FROM_EMAIL=Mumbai Port Authority <noreply@mbpa.example.gov>
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
```

`settings/base.py` already configures SMTP with `smtp.resend.com:587` using the
API key as the password and `resend` as the username.

## 4. Test email delivery

```bash
python manage.py shell -c "
from django.core.mail import send_mail
send_mail(
    'MbPA Portal — Test',
    'Email delivery confirmed.',
    None,  # uses DEFAULT_FROM_EMAIL
    ['your-test-inbox@example.com'],
)
print('Sent.')
"
```

## 5. Production capacity warning (AC-23)

**100 emails/day on the free tier will be exhausted by ~50 OTP logins + signups.**

Before going live:
- Upgrade to Resend's Starter plan ($20/month, 50 k emails/month); or
- Implement OTP rate-limiting at the applicant level (not just IP) to reduce volume; or
- Cache OTP tokens so the same token is reused for a short window rather than
  issuing a new one on every page reload.

The daily cap is tracked as AC-23 in the build plan. It is the highest-priority
cost/availability risk before production launch.
