import uuid

import magic
from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db import transaction
from django.utils import timezone

from apps.common.exceptions import DomainError
from apps.documents.models import DocumentSlot, DocumentUpload

_ALLOWED_MIME_TYPES = {"application/pdf", "image/jpeg", "image/png"}


def store_object(*, prefix: str, filename: str, content: bytes, content_type: str) -> str:
    """AC-22: write the R2 object FIRST. Raises on storage failure so the caller
    never creates a DB row pointing at a non-existent object."""
    key = f"{prefix}/{uuid.uuid4().hex}-{filename}"
    default_storage.save(key, ContentFile(content))
    return key


@transaction.atomic
def upload_document(
    *,
    application,
    document_slot_id,
    milestone_instance,
    uploaded_by,
    filename: str,
    content: bytes,
) -> DocumentUpload:
    """
    AC-19: reject files whose magic bytes don't match an allowed MIME type.
    AC-20: version named-slot uploads; soft-delete the superseded version.
          Ad-hoc uploads (document_slot_id=None) are always version=1 —
          each is independent and never soft-deletes another.
    AC-22: R2 write happens before any DB row is created.
    """
    max_bytes = getattr(settings, "DOCUMENT_MAX_UPLOAD_SIZE_BYTES", 25 * 1024 * 1024)
    if len(content) > max_bytes:
        raise DomainError(f"File exceeds the {max_bytes // (1024 * 1024)} MB upload limit.")

    detected_type = magic.from_buffer(content, mime=True)
    if detected_type not in _ALLOWED_MIME_TYPES:
        raise DomainError(
            f"File content does not match an allowed type (detected: {detected_type}). "
            "The filename and Content-Type header are never trusted for this check (AC-19)."
        )

    document_slot = None
    next_version = 1

    if document_slot_id is not None:
        document_slot = DocumentSlot.objects.filter(pk=document_slot_id).first()

        previous = (
            DocumentUpload.objects.filter(
                application=application,
                document_slot=document_slot,
                is_deleted=False,
            )
            .order_by("-version")
            .first()
        )
        if previous:
            next_version = previous.version + 1
            previous.is_deleted = True
            previous.deleted_at = timezone.now()
            previous.save(update_fields=["is_deleted", "deleted_at", "updated_at"])

    object_key = store_object(
        prefix=f"documents/{application.application_number}",
        filename=filename,
        content=content,
        content_type=detected_type,
    )

    return DocumentUpload.objects.create(
        application=application,
        document_slot=document_slot,
        milestone_instance=milestone_instance,
        uploaded_by=uploaded_by,
        r2_object_key=object_key,
        original_filename=filename,
        content_type=detected_type,
        size_bytes=len(content),
        version=next_version,
    )


def get_download_url(document_upload: DocumentUpload) -> str:
    """AC-21: fresh presigned URL per request, TTL from settings (5 min).
    Never store or cache this URL."""
    return default_storage.url(document_upload.r2_object_key)
