from django.middleware.csrf import get_token
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import ensure_csrf_cookie
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers as drf_serializers
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView


@method_decorator(ensure_csrf_cookie, name="dispatch")
class CsrfView(APIView):
    """Return a CSRF cookie. React calls this once on mount."""

    permission_classes = [AllowAny]

    @extend_schema(
        responses={
            200: inline_serializer("CsrfResponse", {"csrfToken": drf_serializers.CharField()})
        }
    )
    def get(self, request):
        return Response({"csrfToken": get_token(request)})


class HealthzView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(
        responses={
            200: inline_serializer("HealthzResponse", {"status": drf_serializers.CharField()})
        }
    )
    def get(self, request):
        return Response({"status": "ok"})
