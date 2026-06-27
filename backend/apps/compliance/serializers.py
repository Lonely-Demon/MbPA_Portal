from rest_framework import serializers

from apps.compliance.models import AuditEvent, Complaint, ConditionalClearance, ErasureRequest


class AuditEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = AuditEvent
        fields = [
            "id",
            "sequence",
            "verb",
            "target_type",
            "target_id",
            "actor",
            "payload",
            "ip_address",
            "created_at",
        ]


class ComplaintReadSerializer(serializers.ModelSerializer):
    class Meta:
        model = Complaint
        fields = [
            "id",
            "application",
            "origin",
            "raised_by",
            "subject",
            "body",
            "status",
            "resolution_notes",
            "created_at",
            "updated_at",
            "resolved_at",
        ]


class ComplaintCreateSerializer(serializers.Serializer):
    application_id = serializers.IntegerField()
    subject = serializers.CharField(max_length=255)
    body = serializers.CharField()


class ComplaintResolveSerializer(serializers.Serializer):
    resolution_notes = serializers.CharField()


class ConditionalClearanceReadSerializer(serializers.ModelSerializer):
    class Meta:
        model = ConditionalClearance
        fields = [
            "id",
            "application",
            "milestone_instance",
            "clearance_type",
            "description",
            "trigger_metadata",
            "clearance_doc",
            "is_fulfilled",
            "fulfilled_at",
            "fulfilled_by",
            "created_at",
        ]


class ConditionalClearanceCreateSerializer(serializers.Serializer):
    milestone_instance_id = serializers.IntegerField(required=False, allow_null=True)
    clearance_type = serializers.ChoiceField(choices=ConditionalClearance.TYPE_CHOICES)
    description = serializers.CharField()
    trigger_metadata = serializers.JSONField(default=dict)


class ConditionalClearanceFulfillSerializer(serializers.Serializer):
    clearance_doc_id = serializers.IntegerField()


class ErasureRequestReadSerializer(serializers.ModelSerializer):
    is_overdue = serializers.BooleanField(read_only=True)

    class Meta:
        model = ErasureRequest
        fields = [
            "id",
            "subject",
            "requested_by",
            "reason",
            "status",
            "requested_at",
            "due_at",
            "processed_at",
            "processed_by",
            "resolution_notes",
            "is_overdue",
        ]


class ErasureRequestCreateSerializer(serializers.Serializer):
    # Optional: an admin may file on another user's behalf. Omitted ⇒ self-request.
    subject_id = serializers.IntegerField(required=False, allow_null=True)
    reason = serializers.CharField(required=False, allow_blank=True, default="")


class ErasureRequestProcessSerializer(serializers.Serializer):
    approve = serializers.BooleanField()
    resolution_notes = serializers.CharField(required=False, allow_blank=True, default="")
