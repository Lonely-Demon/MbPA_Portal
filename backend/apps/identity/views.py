from django.contrib.auth import authenticate, logout
from drf_spectacular.utils import extend_schema, extend_schema_view, inline_serializer
from rest_framework import serializers as drf_serializers
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.identity.models import OtpToken
from apps.identity.serializers import (
    LoginRequestSerializer,
    MeSerializer,
    OtpResendSerializer,
    OtpVerifySerializer,
    SignupSerializer,
)
from apps.identity.services import (
    login_issue_session,
    register_applicant,
    request_otp,
    verify_otp,
)


class SignupView(APIView):
    permission_classes = [AllowAny]
    throttle_scope = "signup"

    @extend_schema(
        request=SignupSerializer,
        responses={
            201: inline_serializer(
                "SignupResponse",
                {
                    "token_ref": drf_serializers.CharField(),
                },
            )
        },
    )
    def post(self, request):
        ser = SignupSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data
        _user, token = register_applicant(
            email=d["email"],
            username=d["username"],
            password=d["password"],
            full_name=d["full_name"],
            aadhaar_raw=d["aadhaar"],
        )
        return Response({"token_ref": token.token_ref}, status=status.HTTP_201_CREATED)


class LoginView(APIView):
    permission_classes = [AllowAny]
    throttle_scope = "login"

    @extend_schema(
        request=LoginRequestSerializer,
        responses={
            200: inline_serializer(
                "LoginResponse",
                {
                    "token_ref": drf_serializers.CharField(),
                    "masked_email": drf_serializers.CharField(),
                },
            )
        },
    )
    def post(self, request):
        ser = LoginRequestSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data

        # Three-credential check: email + username + password (AC-06).
        # Always call authenticate() so django-axes records the attempt.
        authenticated = authenticate(request, username=d["username"], password=d["password"])

        # Generic error regardless of which credential failed (AC-06 — no enumeration).
        generic_err = Response(
            {"detail": "Invalid credentials."},
            status=status.HTTP_401_UNAUTHORIZED,
        )

        if authenticated is None:
            return generic_err

        # Third credential: the email on the account must also match.
        if authenticated.email != d["email"]:
            return generic_err

        token = request_otp(
            email=authenticated.email,
            purpose=OtpToken.PURPOSE_LOGIN,
            user=authenticated,
        )
        local, domain = authenticated.email.split("@", 1)
        masked = f"{local[:3]}***@{domain}"
        return Response({"token_ref": token.token_ref, "masked_email": masked})


class OtpVerifyView(APIView):
    permission_classes = [AllowAny]
    throttle_scope = "otp"

    @extend_schema(
        request=OtpVerifySerializer,
        responses={
            200: inline_serializer(
                "OtpVerifyResponse",
                {
                    "status": drf_serializers.CharField(),
                },
            )
        },
    )
    def post(self, request):
        ser = OtpVerifySerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data

        token = verify_otp(token_ref=d["token_ref"], submitted_code=d["code"])

        if token.user and token.purpose in (
            OtpToken.PURPOSE_LOGIN,
            OtpToken.PURPOSE_SIGNUP,
        ):
            login_issue_session(request, token.user)

        return Response({"status": "ok"})


class OtpResendView(APIView):
    permission_classes = [AllowAny]
    throttle_scope = "otp_resend"

    @extend_schema(
        request=OtpResendSerializer,
        responses={
            200: inline_serializer(
                "OtpResendResponse",
                {
                    "token_ref": drf_serializers.CharField(),
                },
            )
        },
    )
    def post(self, request):
        ser = OtpResendSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        token_ref = ser.validated_data["token_ref"]

        try:
            old = OtpToken.objects.get(token_ref=token_ref, consumed_at__isnull=True)
        except OtpToken.DoesNotExist:
            return Response(
                {"detail": "Token not found or already used."},
                status=status.HTTP_404_NOT_FOUND,
            )

        new_token = request_otp(email=old.email, purpose=old.purpose, user=old.user)
        return Response({"token_ref": new_token.token_ref})


@extend_schema_view(
    post=extend_schema(
        request={},
        responses={
            200: inline_serializer(
                "LogoutResponse",
                {
                    "status": drf_serializers.CharField(),
                },
            )
        },
    )
)
class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        logout(request)
        return Response({"status": "ok"})


class MeView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses=MeSerializer)
    def get(self, request):
        return Response(MeSerializer(request.user).data)
