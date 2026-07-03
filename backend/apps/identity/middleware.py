from __future__ import annotations

from datetime import datetime

from django.conf import settings
from django.contrib.auth import logout
from django.utils import timezone


class IdleTimeoutMiddleware:
    """
    Server-side idle-timeout enforcement (Part 9.2, AC-10).

    On every authenticated request: compare now() to the _last_activity
    timestamp stored in the session. If the gap exceeds the role-based TTL,
    invalidate the session. On every response, refresh the timestamp.
    """

    _KEY = "_last_activity"

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            self._check_idle(request)

        response = self.get_response(request)

        if request.user.is_authenticated:
            request.session[self._KEY] = timezone.now().isoformat()

        return response

    def _check_idle(self, request) -> None:
        last_str = request.session.get(self._KEY)
        if not last_str:
            return

        last = datetime.fromisoformat(last_str)
        if timezone.is_naive(last):
            last = timezone.make_aware(last)

        user = request.user
        ttl = (
            settings.OFFICER_SESSION_TTL_SECONDS
            if hasattr(user, "officer_profile")
            else settings.APPLICANT_SESSION_TTL_SECONDS
        )

        if (timezone.now() - last).total_seconds() > ttl:
            logout(request)
