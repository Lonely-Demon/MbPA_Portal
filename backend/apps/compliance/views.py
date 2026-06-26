from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.applications.models import Application, MilestoneInstance
from apps.common.exceptions import DomainError
from apps.compliance.models import AuditEvent, Complaint, ConditionalClearance
from apps.compliance.serializers import (
    AuditEventSerializer,
    ComplaintCreateSerializer,
    ComplaintReadSerializer,
    ComplaintResolveSerializer,
    ConditionalClearanceCreateSerializer,
    ConditionalClearanceFulfillSerializer,
    ConditionalClearanceReadSerializer,
)
from apps.compliance.services import (
    create_conditional_clearance,
    fulfill_clearance,
    raise_applicant_complaint,
    resolve_complaint,
)
from apps.documents.models import DocumentUpload


class AuditEventListView(APIView):
    """
    GET /audit/<target_type>/<target_id>/
    Returns all audit events for the given target, newest first.
    Permission: officer or admin (any authenticated user — access is by target scope).
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, target_type, target_id):
        events = (
            AuditEvent.objects.filter(target_type=target_type, target_id=target_id)
            .select_related("actor")
            .order_by("-created_at")
        )
        return Response(AuditEventSerializer(events, many=True).data)


class ComplaintListCreateView(APIView):
    """
    GET  /complaints/ — list complaints visible to the requesting user.
    POST /complaints/ — applicant raises a complaint against their own application.

    Visibility: applicant sees complaints they raised; officers see all complaints
    on applications where they are an assigned milestone officer.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        from apps.applications.models import ApplicationParty

        user = request.user
        # Applicant: complaints they personally raised.
        # Officer: complaints on applications where they're assigned to any milestone.
        if ApplicationParty.objects.filter(user=user).exists():
            qs = Complaint.objects.filter(raised_by=user)
        else:
            app_ids = MilestoneInstance.objects.filter(assigned_officer=user).values_list(
                "application_id", flat=True
            )
            qs = Complaint.objects.filter(application_id__in=app_ids)

        qs = qs.select_related("application", "raised_by").order_by("-created_at")
        return Response(ComplaintReadSerializer(qs, many=True).data)

    def post(self, request):
        ser = ComplaintCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)

        try:
            app = Application.objects.get(pk=ser.validated_data["application_id"])
        except Application.DoesNotExist:
            return Response({"detail": "Application not found."}, status=status.HTTP_404_NOT_FOUND)

        try:
            complaint = raise_applicant_complaint(
                application=app,
                raised_by=request.user,
                subject=ser.validated_data["subject"],
                body=ser.validated_data["body"],
            )
        except DomainError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(ComplaintReadSerializer(complaint).data, status=status.HTTP_201_CREATED)


class ComplaintDetailView(APIView):
    """
    GET   /complaints/<pk>/ — retrieve one complaint.
    PATCH /complaints/<pk>/ — officer resolves the complaint (sets STATUS_RESOLVED).
    """

    permission_classes = [IsAuthenticated]

    def _get_complaint(self, pk):
        try:
            return Complaint.objects.select_related("application", "raised_by").get(pk=pk)
        except Complaint.DoesNotExist:
            return None

    def get(self, request, pk):
        complaint = self._get_complaint(pk)
        if complaint is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(ComplaintReadSerializer(complaint).data)

    def patch(self, request, pk):
        complaint = self._get_complaint(pk)
        if complaint is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        ser = ComplaintResolveSerializer(data=request.data)
        ser.is_valid(raise_exception=True)

        try:
            updated = resolve_complaint(
                complaint=complaint,
                resolved_by=request.user,
                resolution_notes=ser.validated_data["resolution_notes"],
            )
        except DomainError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(ComplaintReadSerializer(updated).data)


class ConditionalClearanceListView(APIView):
    """
    GET /clearances/<application_number>/
    Lists all conditional clearances for an application.
    Permission: authenticated applicant party or assigned officer.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, application_number):
        try:
            app = Application.objects.get(application_number=application_number)
        except Application.DoesNotExist:
            return Response({"detail": "Application not found."}, status=status.HTTP_404_NOT_FOUND)

        clearances = (
            ConditionalClearance.objects.filter(application=app)
            .select_related("milestone_instance", "fulfilled_by", "clearance_doc")
            .order_by("created_at")
        )
        return Response(ConditionalClearanceReadSerializer(clearances, many=True).data)


class ConditionalClearanceCreateView(APIView):
    """
    POST /clearances/<application_number>/create/
    Officer attaches a conditional clearance requirement to an application.
    Permission: authenticated assigned officer.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request, application_number):
        try:
            app = Application.objects.get(application_number=application_number)
        except Application.DoesNotExist:
            return Response({"detail": "Application not found."}, status=status.HTTP_404_NOT_FOUND)

        ser = ConditionalClearanceCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)

        milestone_instance = None
        mi_id = ser.validated_data.get("milestone_instance_id")
        if mi_id:
            try:
                milestone_instance = MilestoneInstance.objects.get(pk=mi_id, application=app)
            except MilestoneInstance.DoesNotExist:
                return Response(
                    {"detail": "MilestoneInstance not found for this application."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        clearance = create_conditional_clearance(
            application=app,
            milestone_instance=milestone_instance,
            clearance_type=ser.validated_data["clearance_type"],
            description=ser.validated_data["description"],
            trigger_metadata=ser.validated_data.get("trigger_metadata", {}),
            created_by=request.user,
        )
        return Response(
            ConditionalClearanceReadSerializer(clearance).data, status=status.HTTP_201_CREATED
        )


class ConditionalClearanceFulfillView(APIView):
    """
    PATCH /clearances/<pk>/fulfill/
    Officer marks a clearance as fulfilled, attaching the evidence document.
    Permission: authenticated assigned officer.
    """

    permission_classes = [IsAuthenticated]

    def patch(self, request, pk):
        try:
            clearance = ConditionalClearance.objects.select_related("application").get(pk=pk)
        except ConditionalClearance.DoesNotExist:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        ser = ConditionalClearanceFulfillSerializer(data=request.data)
        ser.is_valid(raise_exception=True)

        try:
            doc = DocumentUpload.objects.get(
                pk=ser.validated_data["clearance_doc_id"],
                application=clearance.application,
                is_deleted=False,
            )
        except DocumentUpload.DoesNotExist:
            return Response(
                {"detail": "Document not found or does not belong to this application."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            updated = fulfill_clearance(
                clearance=clearance,
                clearance_doc=doc,
                fulfilled_by=request.user,
            )
        except DomainError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(ConditionalClearanceReadSerializer(updated).data)
