from django.core.files.storage import default_storage
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.applications.models import Application
from apps.certificates.models import Certificate
from apps.certificates.services import receive_signed_certificate
from apps.common.exceptions import DomainError


def _get_application(application_number: str):
    try:
        return Application.objects.get(application_number=application_number)
    except Application.DoesNotExist:
        return None


class _CertificateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Certificate
        fields = [
            "id",
            "certificate_type",
            "certificate_number",
            "signature_verified",
            "dsc_serial_used",
            "issued_at",
            "valid_until",
            "revoked_at",
        ]


class CertificateListView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses=_CertificateSerializer(many=True))
    def get(self, request, application_number):
        app = _get_application(application_number)
        if app is None:
            return Response({"detail": "Application not found."}, status=status.HTTP_404_NOT_FOUND)
        certs = app.certificates.filter(revoked_at__isnull=True).order_by("issued_at")
        return Response(_CertificateSerializer(certs, many=True).data)


class CertificateDownloadView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        responses={200: inline_serializer("DownloadUrlResponse", {"url": serializers.URLField()})}
    )
    def get(self, request, application_number, pk):
        app = _get_application(application_number)
        if app is None:
            return Response({"detail": "Application not found."}, status=status.HTTP_404_NOT_FOUND)
        try:
            cert = app.certificates.get(pk=pk)
        except Certificate.DoesNotExist:
            return Response({"detail": "Certificate not found."}, status=status.HTTP_404_NOT_FOUND)
        url = default_storage.url(cert.r2_object_key)
        return Response({"url": url})


class CertificateReceiveSignedView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request={
            "multipart/form-data": inline_serializer(
                "SignedPdfUpload", {"signed_pdf": serializers.FileField()}
            )
        },
        responses={200: _CertificateSerializer, 422: None},
    )
    def post(self, request, application_number, pk):
        app = _get_application(application_number)
        if app is None:
            return Response({"detail": "Application not found."}, status=status.HTTP_404_NOT_FOUND)
        try:
            cert = app.certificates.get(pk=pk)
        except Certificate.DoesNotExist:
            return Response({"detail": "Certificate not found."}, status=status.HTTP_404_NOT_FOUND)

        signed_pdf = request.FILES.get("signed_pdf")
        if signed_pdf is None:
            return Response(
                {"detail": "Field 'signed_pdf' is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            updated = receive_signed_certificate(
                certificate=cert,
                signed_pdf_bytes=signed_pdf.read(),
            )
        except DomainError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)

        return Response(_CertificateSerializer(updated).data)
