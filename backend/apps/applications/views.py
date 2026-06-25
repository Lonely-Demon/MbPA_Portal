from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.applications.models import MilestoneInstance
from apps.applications.permissions import IsAssignedOfficer
from apps.applications.selectors import officer_queue
from apps.applications.serializers import MilestoneActionSerializer, MilestoneInstanceSerializer
from apps.applications.services import transition_milestone


class ApplicationListCreateView(APIView):
    pass


class ApplicationDetailView(APIView):
    pass


class ApplicationSubmitView(APIView):
    pass


class ApplicationWithdrawView(APIView):
    pass


class MilestoneListView(APIView):
    def get(self, request, application_number):
        qs = officer_queue(request.user).filter(application__application_number=application_number)
        ser = MilestoneInstanceSerializer(qs, many=True)
        return Response(ser.data)


class MilestoneActionView(APIView):
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


class StreamListView(APIView):
    pass


class StatusLookupView(APIView):
    pass
