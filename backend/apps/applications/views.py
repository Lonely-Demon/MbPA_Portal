from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.applications.models import MilestoneInstance
from apps.applications.permissions import IsAssignedOfficer
from apps.applications.selectors import officer_queue
from apps.applications.serializers import (
    MilestoneActionSerializer,
    MilestoneInstanceSerializer,
    OfficerQueueItemSerializer,
)
from apps.applications.services import transition_milestone


@extend_schema(exclude=True)
class ApplicationListCreateView(APIView):
    pass


@extend_schema(exclude=True)
class ApplicationDetailView(APIView):
    pass


@extend_schema(exclude=True)
class ApplicationSubmitView(APIView):
    pass


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
        return [IsAssignedOfficer()]


@extend_schema(exclude=True)
class StreamListView(APIView):
    pass


@extend_schema(exclude=True)
class StatusLookupView(APIView):
    pass


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
