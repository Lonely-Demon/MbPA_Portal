from rest_framework import serializers

from apps.documents.models import DocumentSlot, DocumentUpload
from apps.documents.services import get_download_url


class DocumentSlotReadSerializer(serializers.ModelSerializer):
    stream_code = serializers.SerializerMethodField()
    milestone_code = serializers.SerializerMethodField()

    class Meta:
        model = DocumentSlot
        fields = [
            "id",
            "stream_code",
            "milestone_code",
            "document_type",
            "is_mandatory",
            "applies_when",
        ]

    def get_stream_code(self, obj) -> str:
        return obj.stream_milestone.stream.code

    def get_milestone_code(self, obj) -> str:
        return obj.stream_milestone.milestone.code


class DocumentUploadCreateSerializer(serializers.Serializer):
    file = serializers.FileField()
    document_slot_id = serializers.IntegerField(allow_null=True, required=False)
    milestone_instance_id = serializers.IntegerField(allow_null=True, required=False)


class DocumentUploadReadSerializer(serializers.ModelSerializer):
    presigned_url = serializers.SerializerMethodField()
    application_number = serializers.CharField(
        source="application.application_number", read_only=True
    )

    class Meta:
        model = DocumentUpload
        fields = [
            "id",
            "application_number",
            "version",
            "original_filename",
            "content_type",
            "size_bytes",
            "uploaded_at",
            "presigned_url",
        ]

    def get_presigned_url(self, obj) -> str:
        return get_download_url(obj)
