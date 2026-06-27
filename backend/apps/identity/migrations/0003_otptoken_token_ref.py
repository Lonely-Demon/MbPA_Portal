"""
CRIT-5/6: Add token_ref (opaque public identifier) and prior_attempt_count
(cumulative brute-force cap across OTP resends) to OtpToken.

token_ref replaces the integer PK as the client-facing reference so that
sequential enumeration of token IDs is no longer possible.

prior_attempt_count is carried forward when request_otp() supersedes an
existing token, preventing the brute-force cap from being reset via resend.

This migration uses the standard Django two-step pattern for adding a unique
field to an existing table with rows:
  1. Add the column as nullable (no unique constraint yet).
  2. Populate unique values for every existing row.
  3. Alter to NOT NULL + UNIQUE.
"""

from __future__ import annotations

import secrets

from django.db import migrations, models


def _populate_token_ref(apps, schema_editor):
    OtpToken = apps.get_model("identity", "OtpToken")
    for token in OtpToken.objects.filter(token_ref__isnull=True):
        token.token_ref = secrets.token_urlsafe(32)
        token.save(update_fields=["token_ref"])


class Migration(migrations.Migration):
    dependencies = [
        ("identity", "0002_otptoken_signup_fields"),
    ]

    operations = [
        # Step 1: add nullable (no unique constraint yet)
        migrations.AddField(
            model_name="otptoken",
            name="token_ref",
            field=models.CharField(max_length=43, null=True, blank=True),
        ),
        # Step 2: populate unique values for all existing rows
        migrations.RunPython(_populate_token_ref, migrations.RunPython.noop),
        # Step 3: apply NOT NULL + UNIQUE
        migrations.AlterField(
            model_name="otptoken",
            name="token_ref",
            field=models.CharField(
                max_length=43,
                unique=True,
                default=lambda: secrets.token_urlsafe(32),
            ),
        ),
        # prior_attempt_count is new with a safe default — single step is fine
        migrations.AddField(
            model_name="otptoken",
            name="prior_attempt_count",
            field=models.PositiveSmallIntegerField(default=0),
        ),
    ]
