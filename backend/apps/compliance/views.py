from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.applications.models import Application, MilestoneInstance
from apps.common.exceptions import DomainError
from apps.compliance.models import AuditEvent, Complaint, ConditionalClearance, ErasureRequest
from apps.compliance.serializers import (
    AuditEventSerializer,
    ComplaintCreateSerializer,
    ComplaintReadSerializer,
    ComplaintResolveSerializer,
    ConditionalClearanceCreateSerializer,
    ConditionalClearanceFulfillSerializer,
    ConditionalClearanceReadSerializer,
    ErasureRequestCreateSerializer,
    ErasureRequestProcessSerializer,
    ErasureRequestReadSerializer,
)
from apps.compliance.services import (
    create_conditional_clearance,
    create_erasure_request,
    fulfill_clearance,
    process_erasure_request,
    raise_applicant_complaint,
    resolve_complaint,
)
from apps.documents.models import DocumentUpload


def _is_admin(user) -> bool:
    return bool(getattr(user, "user_type", None) == "admin" or user.is_staff or user.is_superuser)


class AuditEventListView(APIView):
    """HIGH-1: Restrict audit trail access to admins and parties on the target application."""

    permission_classes = [IsAuthenticated]

    @extend_schema(responses=AuditEventSerializer(many=True))
    def get(self, request, target_type, target_id):
        user = request.user
        if not (_is_admin(user)):
            # For Application targets, verify the requester has access.
            if target_type == "application":
                try:
                    app = Application.objects.get(pk=target_id)
                except Application.DoesNotExist:
                    return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
                if not (
                    app.submitted_by_id == user.pk
                    or app.parties.filter(user=user).exists()
                    or app.milestone_instances.filter(assigned_officer=user).exists()
                ):
                    return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
            else:
                # Non-application audit events are admin-only.
                return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

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
            app = Application.objects.get(
                pk=ser.validated_data["application_id"], deleted_at__isnull=True
            )
        except Application.DoesNotExist:
            return Response({"detail": "Application not found."}, status=status.HTTP_404_NOT_FOUND)

        # An applicant-origin complaint may only be raised by the account of
        # record or a co-party on the application — otherwise any authenticated
        # user could file a complaint against a stranger's application by ID.
        user = request.user
        if not (
            app.submitted_by_id == user.pk
            or app.parties.filter(user=user).exists()
            or user.is_staff
            or getattr(user, "user_type", "") == "admin"
        ):
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

    def _can_access_complaint(self, user, complaint) -> bool:
        """Raiser, assigned officer on the application, or admin."""
        if _is_admin(user):
            return True
        if complaint.raised_by_id == user.pk:
            return True
        if (
            complaint.application
            and MilestoneInstance.objects.filter(
                application=complaint.application, assigned_officer=user
            ).exists()
        ):
            return True
        return False

    @extend_schema(operation_id="complaints_retrieve", responses=ComplaintReadSerializer)
    def get(self, request, pk):
        complaint = self._get_complaint(pk)
        if complaint is None or not self._can_access_complaint(request.user, complaint):
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(ComplaintReadSerializer(complaint).data)

    @extend_schema(request=ComplaintResolveSerializer, responses=ComplaintReadSerializer)
    def patch(self, request, pk):
        complaint = self._get_complaint(pk)
        if complaint is None or not self._can_access_complaint(request.user, complaint):
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


def _can_access_app(user, app) -> bool:
    """Check user has access to an Application (officer, party, admin)."""
    if _is_admin(user):
        return True
    if app.submitted_by_id == user.pk:
        return True
    if app.parties.filter(user=user).exists():
        return True
    if app.milestone_instances.filter(assigned_officer=user).exists():
        return True
    return False


class ConditionalClearanceListView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses=ConditionalClearanceReadSerializer(many=True))
    def get(self, request, application_number):
        try:
            app = Application.objects.get(
                application_number=application_number, deleted_at__isnull=True
            )
        except Application.DoesNotExist:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        if not _can_access_app(request.user, app):
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

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
            app = Application.objects.get(
                application_number=application_number, deleted_at__isnull=True
            )
        except Application.DoesNotExist:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        if not _can_access_app(request.user, app):
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

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


class ErasureRequestListCreateView(APIView):
    """AC-32: DPDP erasure requests. Anyone may request erasure of their own data."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="erasure_requests_list", responses=ErasureRequestReadSerializer(many=True)
    )
    def get(self, request):
        # Admins see all requests; ordinary users see only their own.
        if _is_admin(request.user):
            qs = ErasureRequest.objects.all()
        else:
            qs = ErasureRequest.objects.filter(subject=request.user)
        qs = qs.select_related("subject", "requested_by", "processed_by")
        return Response(ErasureRequestReadSerializer(qs, many=True).data)

    @extend_schema(
        request=ErasureRequestCreateSerializer, responses={201: ErasureRequestReadSerializer}
    )
    def post(self, request):
        ser = ErasureRequestCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)

        subject_id = ser.validated_data.get("subject_id")
        # Filing for another subject is an admin-only action; default is self.
        if subject_id and subject_id != request.user.pk:
            if not _is_admin(request.user):
                return Response(
                    {"detail": "Only an admin may file an erasure request for another user."},
                    status=status.HTTP_403_FORBIDDEN,
                )
            from apps.identity.models import User

            try:
                subject = User.objects.get(pk=subject_id)
            except User.DoesNotExist:
                return Response(
                    {"detail": "Subject user not found."}, status=status.HTTP_404_NOT_FOUND
                )
        else:
            subject = request.user

        req = create_erasure_request(
            subject=subject,
            requested_by=request.user,
            reason=ser.validated_data.get("reason", ""),
        )
        return Response(ErasureRequestReadSerializer(req).data, status=status.HTTP_201_CREATED)


class ErasureRequestProcessView(APIView):
    """AC-32: admin completes or rejects a pending erasure request."""

    permission_classes = [IsAuthenticated]

    @extend_schema(request=ErasureRequestProcessSerializer, responses=ErasureRequestReadSerializer)
    def patch(self, request, pk):
        if not _is_admin(request.user):
            return Response(
                {"detail": "Only an admin may process erasure requests."},
                status=status.HTTP_403_FORBIDDEN,
            )
        try:
            req = ErasureRequest.objects.select_related("subject").get(pk=pk)
        except ErasureRequest.DoesNotExist:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        ser = ErasureRequestProcessSerializer(data=request.data)
        ser.is_valid(raise_exception=True)

        try:
            updated = process_erasure_request(
                erasure_request=req,
                processed_by=request.user,
                approve=ser.validated_data["approve"],
                resolution_notes=ser.validated_data.get("resolution_notes", ""),
            )
        except DomainError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(ErasureRequestReadSerializer(updated).data)


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

        if clearance.application and not _can_access_app(request.user, clearance.application):
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
