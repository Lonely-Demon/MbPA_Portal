from rest_framework import serializers

from apps.applications.models import Application
from apps.applications.services import VALID_ACTIONS


class ApplicationCreateSerializer(serializers.Serializer):
    stream_id = serializers.IntegerField()
    plpn = serializers.CharField(max_length=50, allow_blank=True, default="")
    plot_area_sqm = serializers.DecimalField(max_digits=12, decimal_places=2)
    proposed_bua_sqm = serializers.DecimalField(max_digits=12, decimal_places=2)
    existing_bua_sqm = serializers.DecimalField(max_digits=12, decimal_places=2)
    zonal_rrr = serializers.DecimalField(max_digits=12, decimal_places=2)


class ApplicationReadSerializer(serializers.ModelSerializer):
    stream_code = serializers.CharField(source="stream.code", read_only=True)
    stream_name = serializers.CharField(source="stream.name", read_only=True)

    class Meta:
        model = Application
        fields = [
            "id",
            "application_number",
            "stream_code",
            "stream_name",
            "status",
            "plpn",
            "plot_area_sqm",
            "proposed_bua_sqm",
            "existing_bua_sqm",
            "zonal_rrr",
            "submitted_at",
            "created_at",
        ]
        read_only_fields = fields


class MilestoneActionSerializer(serializers.Serializer):
    action = serializers.ChoiceField(choices=sorted(VALID_ACTIONS))
    decision_note = serializers.CharField(required=False, default="", allow_blank=True)
    correction_reason = serializers.CharField(required=False, default="", allow_blank=True)


class MilestoneInstanceSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    application_number = serializers.CharField(
        source="application.application_number", read_only=True
    )
    stream_code = serializers.CharField(source="stream_milestone.stream.code", read_only=True)
    milestone_code = serializers.CharField(source="stream_milestone.milestone.code", read_only=True)
    sequence = serializers.IntegerField(source="stream_milestone.sequence", read_only=True)
    status = serializers.CharField(read_only=True)
    started_at = serializers.DateTimeField(read_only=True)
    due_at = serializers.DateTimeField(read_only=True)
    completed_at = serializers.DateTimeField(read_only=True)
    officer_remarks = serializers.CharField(read_only=True)


class OfficerQueueItemSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    application_number = serializers.CharField(source="application.application_number")
    stream_code = serializers.CharField(source="stream_milestone.stream.code")
    stream_name = serializers.CharField(source="stream_milestone.stream.name")
    milestone_code = serializers.CharField(source="stream_milestone.milestone.code")
    milestone_name = serializers.CharField(source="stream_milestone.milestone.name")
    sequence = serializers.IntegerField(source="stream_milestone.sequence")
    sla_working_days = serializers.IntegerField(
        source="stream_milestone.milestone.default_sla_working_days"
    )
    status = serializers.CharField()
    started_at = serializers.DateTimeField()
    due_at = serializers.DateTimeField()
    document_count = serializers.IntegerField()
