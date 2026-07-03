from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers as drf_serializers
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.applications.models import MilestoneInstance
from apps.documents.models import DocumentSlot, DocumentUpload
from apps.documents.permissions import CanAccessDocument
from apps.documents.serializers import (
    DocumentSlotReadSerializer,
    DocumentUploadCreateSerializer,
    DocumentUploadReadSerializer,
)
from apps.documents.services import get_download_url, upload_document


class DocumentSlotListView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses=DocumentSlotReadSerializer(many=True))
    def get(self, request, milestone_instance_id):
        try:
            mi = MilestoneInstance.objects.select_related("stream_milestone", "application").get(
                pk=milestone_instance_id
            )
        except MilestoneInstance.DoesNotExist:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        # CRIT-4: Confirm the requesting user has access to the underlying application.
        app = mi.application
        user = request.user
        if not (
            app.submitted_by_id == user.pk
            or app.parties.filter(user=user).exists()
            or app.milestone_instances.filter(assigned_officer=user).exists()
            or user.is_staff
            or getattr(user, "user_type", "") == "admin"
        ):
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        slots = DocumentSlot.objects.filter(stream_milestone=mi.stream_milestone).select_related(
            "stream_milestone__stream", "stream_milestone__milestone"
        )
        return Response(DocumentSlotReadSerializer(slots, many=True).data)


class DocumentUploadView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request={"multipart/form-data": DocumentUploadCreateSerializer},
        responses={201: DocumentUploadReadSerializer},
    )
    def post(self, request):
        ser = DocumentUploadCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)

        uploaded_file = ser.validated_data["file"]
        content = uploaded_file.read()
        filename = uploaded_file.name

        slot_id = ser.validated_data.get("document_slot_id")
        mi_id = ser.validated_data.get("milestone_instance_id")

        # H-2: DocumentSlot only references a StreamMilestone template (shared
        # across every application on that stream), not a specific Application —
        # there is no way to resolve which application a slot-only upload
        # belongs to. milestone_instance_id is required to determine both the
        # application and (below) that the slot actually belongs to it.
        if slot_id and not mi_id:
            return Response(
                {"detail": "milestone_instance_id is required when document_slot_id is set."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        milestone_instance = None
        if mi_id:
            milestone_instance = (
                MilestoneInstance.objects.select_related("application").filter(pk=mi_id).first()
            )
            if milestone_instance is None:
                return Response(
                    {"detail": "milestone_instance_id not found."},
                    status=status.HTTP_404_NOT_FOUND,
                )

        if slot_id:
            slot_matches = DocumentSlot.objects.filter(
                pk=slot_id, stream_milestone_id=milestone_instance.stream_milestone_id
            ).exists()
            if not slot_matches:
                return Response(
                    {"detail": "document_slot_id does not belong to this milestone."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        if milestone_instance is None:
            return Response(
                {"detail": "Cannot determine application: provide milestone_instance_id."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        application = milestone_instance.application

        # CRIT-4: Verify the uploading user has access to this application.
        user = request.user
        if not (
            application.submitted_by_id == user.pk
            or application.parties.filter(user=user).exists()
            or application.milestone_instances.filter(assigned_officer=user).exists()
            or user.is_staff
            or getattr(user, "user_type", "") == "admin"
        ):
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        doc = upload_document(
            application=application,
            document_slot_id=slot_id,
            milestone_instance=milestone_instance,
            uploaded_by=request.user,
            filename=filename,
            content=content,
        )
        return Response(
            DocumentUploadReadSerializer(doc).data,
            status=status.HTTP_201_CREATED,
        )


class DocumentDetailView(APIView):
    permission_classes = [IsAuthenticated, CanAccessDocument]

    @extend_schema(responses=DocumentUploadReadSerializer)
    def get(self, request, pk):
        try:
            doc = DocumentUpload.objects.select_related("application").get(pk=pk, is_deleted=False)
        except DocumentUpload.DoesNotExist:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        self.check_object_permissions(request, doc)
        return Response(DocumentUploadReadSerializer(doc).data)


class PresignedUrlView(APIView):
    permission_classes = [IsAuthenticated, CanAccessDocument]

    @extend_schema(
        responses={
            200: inline_serializer("PresignedUrlResponse", {"url": drf_serializers.URLField()})
        }
    )
    def get(self, request, pk):
        try:
            doc = DocumentUpload.objects.select_related("application").get(pk=pk, is_deleted=False)
        except DocumentUpload.DoesNotExist:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        self.check_object_permissions(request, doc)
        return Response({"url": get_download_url(doc)})
