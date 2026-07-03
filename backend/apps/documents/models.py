from django.conf import settings
from django.db import models

from apps.applications.models import Application, MilestoneInstance, StreamMilestone


class DocumentSlot(models.Model):
    """
    Required/optional document for a specific StreamMilestone.
    Using stream_milestone FK (not separate stream+milestone FKs) ensures only
    valid combinations can be referenced — StreamMilestone already encodes which
    (stream, milestone) pairs exist.
    """

    stream_milestone = models.ForeignKey(
        StreamMilestone, on_delete=models.CASCADE, related_name="document_slots"
    )
    document_type = models.CharField(max_length=255)
    is_mandatory = models.BooleanField(default=True)
    applies_when = models.CharField(max_length=64, blank=True)

    class Meta:
        db_table = "documents_slot"
        constraints = [
            models.UniqueConstraint(
                fields=["stream_milestone", "document_type"],
                name="uniq_doc_slot",
            )
        ]

    def __str__(self):
        return f"{self.stream_milestone} / {self.document_type}"


class DocumentUpload(models.Model):
    """
    AC-19 (magic-byte validation), AC-20 (versioning, never overwrite),
    AC-21 (presigned URL only), AC-22 (object-first ordering) all enforced
    in apps/documents/services.py. This model stores validated results only.

    Ad-hoc uploads (document_slot=None) are always version=1 — versioning only
    applies to named-slot uploads so unrelated ad-hoc uploads on the same
    application never soft-delete each other.
    """

    application = models.ForeignKey(Application, on_delete=models.CASCADE, related_name="documents")
    document_slot = models.ForeignKey(
        DocumentSlot,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    milestone_instance = models.ForeignKey(
        MilestoneInstance,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    r2_object_key = models.CharField(max_length=512)
    original_filename = models.CharField(max_length=255)
    content_type = models.CharField(max_length=128)
    size_bytes = models.BigIntegerField()
    version = models.PositiveSmallIntegerField(default=1)
    is_deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(null=True, blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "documents_upload"
        indexes = [
            models.Index(
                fields=["application", "document_slot", "version"],
                name="documents_u_app_slot_ver_idx",
            ),
        ]
        constraints = [
            # django-stubs 5.0.x's CheckConstraint stub predates Django 5.1's
            # rename of `check` to `condition`; the kwarg is valid at runtime.
            models.CheckConstraint(  # type: ignore[call-arg]
                condition=models.Q(size_bytes__gt=0), name="document_size_positive"
            ),
        ]
