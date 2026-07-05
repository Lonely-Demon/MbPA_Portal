import ssl
from django.core.mail.backends.smtp import EmailBackend

class UnsafeEmailBackend(EmailBackend):
    """
    SMTP Email Backend that disables SSL certificate verification.
    Useful when running in environments with simulated system clocks (e.g. 2026)
    where public CA certificates appear expired.
    """
    @property
    def ssl_context(self):
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        return context
