from django.conf import settings
from django.db import models

from apps.applications.models import Application, MilestoneInstance, Stream, StreamMilestone


class DocumentSlot(models.Model):
    """Definition of a required or optional document for a stream/milestone combination."""
    stream = models.ForeignKey(Stream, on_delete=models.CASCADE, related_name="document_slots")
    stream_milestone = models.ForeignKey(
        StreamMilestone, on_delete=models.CASCADE, related_name="document_slots",
        null=True, blank=True,  # null = required at submission regardless of milestone
    )
    code = models.CharField(max_length=50)
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    accepted_mime_types = models.JSONField(default=list)  # e.g. ["application/pdf", "image/jpeg"]
    max_size_mb = models.PositiveSmallIntegerField(default=10)
    is_mandatory = models.BooleanField(default=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "documents_slot"
        unique_together = [("stream", "stream_milestone", "code")]

    def __str__(self):
        return f"{self.stream.code} / {self.code}"


class DocumentUpload(models.Model):
    """A single uploaded file attached to an application slot."""
    STATUS_PENDING = "pending"
    STATUS_ACCEPTED = "accepted"
    STATUS_REJECTED = "rejected"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_ACCEPTED, "Accepted"),
        (STATUS_REJECTED, "Rejected"),
    ]

    application = models.ForeignKey(Application, on_delete=models.CASCADE, related_name="document_uploads")
    slot = models.ForeignKey(DocumentSlot, on_delete=models.PROTECT, related_name="uploads")
    milestone_instance = models.ForeignKey(
        MilestoneInstance, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="document_uploads",
    )
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="uploaded_documents"
    )

    # R2 object key — presigned URLs generated on demand; never stored here
    r2_object_key = models.CharField(max_length=512)
    original_filename = models.CharField(max_length=255)
    mime_type = models.CharField(max_length=100)
    size_bytes = models.PositiveIntegerField()

    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=STATUS_PENDING)
    version = models.PositiveSmallIntegerField(default=1)
    # Soft-delete so statutory retention is preserved
    deleted_at = models.DateTimeField(null=True, blank=True)

    reviewer_remarks = models.TextField(blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "documents_upload"
        indexes = [
            models.Index(fields=["application", "slot", "version"]),
            models.Index(fields=["status"]),
        ]
