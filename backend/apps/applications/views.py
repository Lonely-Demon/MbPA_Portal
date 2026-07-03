from django.db.models import Q
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers as drf_serializers
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.applications.models import Application, MilestoneInstance, Stream, StreamMilestone
from apps.applications.permissions import IsAssignedOfficer
from apps.applications.selectors import officer_queue
from apps.applications.serializers import (
    ApplicationCreateSerializer,
    ApplicationReadSerializer,
    MilestoneActionSerializer,
    MilestoneInstanceSerializer,
    OfficerQueueItemSerializer,
)
from apps.applications.services import create_application, submit_application, transition_milestone


class StreamListView(APIView):
    permission_classes = []
    authentication_classes = []

    @extend_schema(
        responses={
            200: inline_serializer(
                "StreamListItem",
                {
                    "id": drf_serializers.IntegerField(),
                    "code": drf_serializers.CharField(),
                    "name": drf_serializers.CharField(),
                    "description": drf_serializers.CharField(),
                    "milestones": inline_serializer(
                        "StreamMilestoneItem",
                        {
                            "code": drf_serializers.CharField(),
                            "name": drf_serializers.CharField(),
                            "sequence": drf_serializers.IntegerField(),
                            "sla_working_days": drf_serializers.IntegerField(),
                            "deemed_clearance_eligible": drf_serializers.BooleanField(),
                        },
                        many=True,
                    ),
                },
                many=True,
            )
        }
    )
    def get(self, request):
        from django.db.models import Prefetch

        streams = Stream.objects.filter(is_active=True).prefetch_related(
            Prefetch(
                "stream_milestones",
                queryset=StreamMilestone.objects.select_related("milestone").order_by("sequence"),
            )
        )
        return Response(
            [
                {
                    "id": s.id,
                    "code": s.code,
                    "name": s.name,
                    "description": s.description,
                    "milestones": [
                        {
                            "code": sm.milestone.code,
                            "name": sm.milestone.name,
                            "sequence": sm.sequence,
                            "sla_working_days": sm.milestone.default_sla_working_days,
                            "deemed_clearance_eligible": sm.deemed_clearance_eligible,
                        }
                        for sm in s.stream_milestones.all()
                    ],
                }
                for s in streams
            ]
        )


class StatusLookupView(APIView):
    permission_classes = []
    authentication_classes = []

    @extend_schema(
        responses={
            200: inline_serializer(
                "StatusLookupResponse",
                {
                    "application_number": drf_serializers.CharField(),
                    "stream": drf_serializers.CharField(),
                    "stream_code": drf_serializers.CharField(),
                    "status": drf_serializers.CharField(),
                    "submitted_at": drf_serializers.DateTimeField(allow_null=True),
                    "milestones": inline_serializer(
                        "StatusMilestoneItem",
                        {
                            "id": drf_serializers.IntegerField(),
                            "code": drf_serializers.CharField(),
                            "name": drf_serializers.CharField(),
                            "sequence": drf_serializers.IntegerField(),
                            "status": drf_serializers.CharField(),
                            "started_at": drf_serializers.DateTimeField(allow_null=True),
                            "completed_at": drf_serializers.DateTimeField(allow_null=True),
                            "is_deemed": drf_serializers.BooleanField(),
                        },
                        many=True,
                    ),
                },
            )
        }
    )
    def get(self, request):
        from django.db.models import Prefetch

        app_number = request.query_params.get("application_number", "").strip()
        if not app_number:
            return Response(
                {"detail": "application_number is required."}, status=status.HTTP_400_BAD_REQUEST
            )
        try:
            app = (
                Application.objects.select_related("stream")
                .prefetch_related(
                    Prefetch(
                        "milestone_instances",
                        queryset=MilestoneInstance.objects.select_related(
                            "stream_milestone__milestone"
                        ).order_by("stream_milestone__sequence"),
                    )
                )
                .get(application_number=app_number, deleted_at__isnull=True)
            )
        except Application.DoesNotExist:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        return Response(
            {
                "application_number": app.application_number,
                "stream": app.stream.name,
                "stream_code": app.stream.code,
                "status": app.status,
                "submitted_at": app.submitted_at,
                "milestones": [
                    {
                        # A MilestoneInstance id grants no capability by itself
                        # (DocumentUploadView/etc. still enforce ownership on
                        # the application, not secrecy of this id) — exposing
                        # it here is what lets the applicant's own dashboard
                        # reuse this same public endpoint to know which
                        # instance to attach an upload to.
                        "id": mi.id,
                        "code": mi.stream_milestone.milestone.code,
                        "name": mi.stream_milestone.milestone.name,
                        "sequence": mi.stream_milestone.sequence,
                        "status": mi.status,
                        "started_at": mi.started_at,
                        "completed_at": mi.completed_at,
                        "is_deemed": mi.is_deemed,
                    }
                    for mi in app.milestone_instances.all()
                ],
            }
        )


class ApplicationListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses=ApplicationReadSerializer(many=True))
    def get(self, request):
        qs = (
            Application.objects.filter(
                Q(submitted_by=request.user) | Q(parties__user=request.user),
                deleted_at__isnull=True,
            )
            .distinct()
            .select_related("stream")
            .order_by("-created_at")
        )
        return Response(ApplicationReadSerializer(qs, many=True).data)

    @extend_schema(
        request=ApplicationCreateSerializer,
        responses={201: ApplicationReadSerializer},
    )
    def post(self, request):
        ser = ApplicationCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data
        try:
            app = create_application(
                stream_id=d["stream_id"],
                submitted_by=request.user,
                plpn=d.get("plpn", ""),
                plot_area_sqm=d["plot_area_sqm"],
                proposed_bua_sqm=d["proposed_bua_sqm"],
                existing_bua_sqm=d["existing_bua_sqm"],
                zonal_rrr=d["zonal_rrr"],
            )
        except Exception as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        app.refresh_from_db()
        return Response(ApplicationReadSerializer(app).data, status=status.HTTP_201_CREATED)


class ApplicationDetailView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses=ApplicationReadSerializer)
    def get(self, request, pk):
        try:
            app = Application.objects.select_related("stream").get(pk=pk, deleted_at__isnull=True)
        except Application.DoesNotExist:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        if not (app.submitted_by == request.user or app.parties.filter(user=request.user).exists()):
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(ApplicationReadSerializer(app).data)


class ApplicationSubmitView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request={},
        responses={200: ApplicationReadSerializer},
    )
    def post(self, request, pk):
        from apps.common.exceptions import DomainError

        # CRIT-3: Verify the requesting user owns this draft before submitting.
        try:
            app_obj = Application.objects.get(pk=pk, deleted_at__isnull=True)
        except Application.DoesNotExist:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        if app_obj.submitted_by_id != request.user.pk:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        try:
            app = submit_application(application_id=pk, submitted_by=request.user)
        except DomainError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(ApplicationReadSerializer(app).data)


@extend_schema(exclude=True)
class ApplicationWithdrawView(APIView):
    pass


class MilestoneListView(APIView):
    @extend_schema(responses=MilestoneInstanceSerializer(many=True))
    def get(self, request, application_number):
        qs = officer_queue(request.user).filter(application__application_number=application_number)
        ser = MilestoneInstanceSerializer(qs, many=True)
        return Response(ser.data)


class MilestoneActionView(APIView):
    @extend_schema(
        request=MilestoneActionSerializer,
        responses=MilestoneInstanceSerializer,
    )
    def post(self, request, application_number, pk):
        try:
            instance = MilestoneInstance.objects.select_related("application").get(
                pk=pk, application__application_number=application_number
            )
        except MilestoneInstance.DoesNotExist:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        self.check_object_permissions(request, instance)

        ser = MilestoneActionSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data

        updated = transition_milestone(
            milestone_instance_id=instance.pk,
            action=d["action"],
            acting_officer=request.user,
            decision_note=d["decision_note"],
            correction_reason=d["correction_reason"],
        )
        return Response(MilestoneInstanceSerializer(updated).data)

    def get_permissions(self):
        return [IsAuthenticated(), IsAssignedOfficer()]


class OfficerQueueView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses=OfficerQueueItemSerializer(many=True))
    def get(self, request):
        from django.db.models import Count, Q

        qs = officer_queue(request.user).annotate(
            document_count=Count(
                "application__documents",
                filter=Q(application__documents__is_deleted=False),
            )
        )
        return Response(OfficerQueueItemSerializer(qs, many=True).data)
