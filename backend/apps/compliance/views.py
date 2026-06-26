from drf_spectacular.utils import extend_schema
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
    permission_classes = [IsAuthenticated]

    @extend_schema(responses=AuditEventSerializer(many=True))
    def get(self, request, target_type, target_id):
        events = (
            AuditEvent.objects.filter(target_type=target_type, target_id=target_id)
            .select_related("actor")
            .order_by("-created_at")
        )
        return Response(AuditEventSerializer(events, many=True).data)


class ComplaintListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(operation_id="complaints_list", responses=ComplaintReadSerializer(many=True))
    def get(self, request):
        from apps.applications.models import ApplicationParty

        user = request.user
        if ApplicationParty.objects.filter(user=user).exists():
            qs = Complaint.objects.filter(raised_by=user)
        else:
            app_ids = MilestoneInstance.objects.filter(assigned_officer=user).values_list(
                "application_id", flat=True
            )
            qs = Complaint.objects.filter(application_id__in=app_ids)

        qs = qs.select_related("application", "raised_by").order_by("-created_at")
        return Response(ComplaintReadSerializer(qs, many=True).data)

    @extend_schema(request=ComplaintCreateSerializer, responses={201: ComplaintReadSerializer})
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
    permission_classes = [IsAuthenticated]

    def _get_complaint(self, pk):
        try:
            return Complaint.objects.select_related("application", "raised_by").get(pk=pk)
        except Complaint.DoesNotExist:
            return None

    @extend_schema(operation_id="complaints_retrieve", responses=ComplaintReadSerializer)
    def get(self, request, pk):
        complaint = self._get_complaint(pk)
        if complaint is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(ComplaintReadSerializer(complaint).data)

    @extend_schema(request=ComplaintResolveSerializer, responses=ComplaintReadSerializer)
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
    permission_classes = [IsAuthenticated]

    @extend_schema(responses=ConditionalClearanceReadSerializer(many=True))
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
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=ConditionalClearanceCreateSerializer,
        responses={201: ConditionalClearanceReadSerializer},
    )
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
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=ConditionalClearanceFulfillSerializer,
        responses=ConditionalClearanceReadSerializer,
    )
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
