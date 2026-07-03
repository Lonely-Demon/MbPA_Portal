from unittest.mock import patch

import pytest
from django.test import override_settings

from apps.notifications.services import EmailDeliveryError, send_email


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
def test_send_email_succeeds_with_working_backend():
    send_email("user@test.com", "otp_login", {"code": "123456", "subject": "Code"})


def test_send_email_raises_email_delivery_error_on_failure():
    """
    M-6: send_email must surface delivery failures to the caller instead of
    only logging them — a caller for whom the email IS the outcome (OTP
    delivery) needs to know it didn't go out.
    """
    with patch("apps.notifications.services.send_mail", side_effect=OSError("smtp down")):
        with pytest.raises(EmailDeliveryError):
            send_email("user@test.com", "otp_login", {"code": "123456", "subject": "Code"})
