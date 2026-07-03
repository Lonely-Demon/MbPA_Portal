from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model

from apps.applications.models import (
    Application,
    MilestoneInstance,
    Stream,
    StreamMilestone,
)
from apps.applications.services import generate_application_number
from apps.common.exceptions import DomainError
from apps.documents.models import DocumentSlot, DocumentUpload
from apps.documents.services import get_download_url, upload_document

User = get_user_model()

# ── Minimal bytes for each allowed type ──────────────────────────────────────
_PDF_BYTES = b"%PDF-1.4 %" + b"\x00" * 20
_JPEG_BYTES = b"\xff\xd8\xff\xe0" + b"\x00" * 20
# Minimal valid PNG with IHDR chunk — libmagic needs the IHDR to detect image/png
_PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde"
)
_ELF_BYTES = b"\x7fELF" + b"\x00" * 20


# ── Fixtures ──────────────────────────────────────────────────────────────────


def _make_user(username="u", role="applicant"):
    u = User.objects.create_user(username=username, password="pw")
    u.role = role
    u.save()
    return u


def _make_application(stream_code="test_stream", submitted_by=None):
    stream, _ = Stream.objects.get_or_create(code=stream_code, defaults={"name": stream_code})
    if submitted_by is None:
        submitted_by = User.objects.get_or_create(
            username=f"_app_owner_{stream_code}",
            defaults={"password": "x"},
        )[0]
    app = Application.objects.create(
        stream=stream,
        submitted_by=submitted_by,
        application_number=generate_application_number(),
        status=Application.STATUS_SUBMITTED,
    )
    return app


def _make_stream_milestone(stream_code="ts", milestone_code="M1"):
    from apps.applications.models import Milestone

    stream, _ = Stream.objects.get_or_create(code=stream_code, defaults={"name": stream_code})
    milestone, _ = Milestone.objects.get_or_create(
        code=milestone_code, defaults={"name": milestone_code}
    )
    sm, _ = StreamMilestone.objects.get_or_create(
        stream=stream,
        milestone=milestone,
        defaults={"sequence": 1, "required_officer_role": "RDO"},
    )
    return sm


def _make_slot(sm, document_type="Form 1A"):
    return DocumentSlot.objects.create(
        stream_milestone=sm,
        document_type=document_type,
    )


# ── AC-19: magic-byte rejection ───────────────────────────────────────────────


@pytest.mark.django_db
def test_malicious_upload_elf_bytes_rejected():
    user = _make_user("u1")
    app = _make_application("s1")

    with patch("apps.documents.services.default_storage") as mock_storage:
        with pytest.raises(DomainError) as exc_info:
            upload_document(
                application=app,
                document_slot_id=None,
                milestone_instance=None,
                uploaded_by=user,
                filename="legitimate.pdf",
                content=_ELF_BYTES,
            )

    assert "AC-19" in str(exc_info.value) or "detected" in str(exc_info.value)
    mock_storage.save.assert_not_called()
    assert DocumentUpload.objects.count() == 0


@pytest.mark.django_db
def test_malicious_upload_no_db_row_on_rejection():
    user = _make_user("u2")
    app = _make_application("s2")

    with patch("apps.documents.services.default_storage"):
        with pytest.raises(DomainError):
            upload_document(
                application=app,
                document_slot_id=None,
                milestone_instance=None,
                uploaded_by=user,
                filename="evil.pdf",
                content=_ELF_BYTES,
            )
    assert DocumentUpload.objects.filter(application=app).count() == 0


# ── AC-19: size cap ───────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_upload_exceeding_size_cap_raises_domain_error(settings):
    settings.DOCUMENT_MAX_UPLOAD_SIZE_BYTES = 100
    user = _make_user("u3")
    app = _make_application("s3")

    with patch("apps.documents.services.default_storage"):
        with pytest.raises(DomainError) as exc_info:
            upload_document(
                application=app,
                document_slot_id=None,
                milestone_instance=None,
                uploaded_by=user,
                filename="big.pdf",
                content=b"x" * 101,
            )
    assert "limit" in str(exc_info.value).lower()
    assert DocumentUpload.objects.filter(application=app).count() == 0


# ── AC-20: versioning — named-slot uploads ────────────────────────────────────


@pytest.mark.django_db
def test_second_slot_upload_creates_new_version_and_soft_deletes_prior():
    user = _make_user("u4")
    app = _make_application("s4")
    sm = _make_stream_milestone("s4", "M1")
    slot = _make_slot(sm, "Form 4A")

    fake_key_1 = "documents/APP0001/aaa-form.pdf"
    fake_key_2 = "documents/APP0001/bbb-form.pdf"

    with patch("apps.documents.services.default_storage") as mock_s:
        mock_s.save.side_effect = [fake_key_1, fake_key_2]
        doc1 = upload_document(
            application=app,
            document_slot_id=slot.pk,
            milestone_instance=None,
            uploaded_by=user,
            filename="form.pdf",
            content=_PDF_BYTES,
        )
        doc2 = upload_document(
            application=app,
            document_slot_id=slot.pk,
            milestone_instance=None,
            uploaded_by=user,
            filename="form_v2.pdf",
            content=_PDF_BYTES,
        )

    doc1.refresh_from_db()
    assert doc1.is_deleted is True
    assert doc1.deleted_at is not None
    assert doc2.is_deleted is False
    assert doc2.version == 2
    assert doc1.r2_object_key != doc2.r2_object_key
    assert DocumentUpload.objects.filter(application=app, document_slot=slot).count() == 2


@pytest.mark.django_db
def test_versioning_never_destroys_prior_r2_object():
    """The prior DocumentUpload row is soft-deleted (is_deleted=True), not removed.
    The R2 object itself is never deleted — only the DB visibility flag changes."""
    user = _make_user("u5")
    app = _make_application("s5")
    sm = _make_stream_milestone("s5", "M2")
    slot = _make_slot(sm, "Form 4B")

    with patch("apps.documents.services.default_storage") as mock_s:
        mock_s.save.return_value = "documents/app/key.pdf"
        upload_document(
            application=app,
            document_slot_id=slot.pk,
            milestone_instance=None,
            uploaded_by=user,
            filename="x.pdf",
            content=_PDF_BYTES,
        )
        upload_document(
            application=app,
            document_slot_id=slot.pk,
            milestone_instance=None,
            uploaded_by=user,
            filename="x2.pdf",
            content=_PDF_BYTES,
        )

    # R2 delete was never called — soft-delete only
    mock_s.delete.assert_not_called()


# ── AC-20: ad-hoc uploads are independent (no cross-versioning) ──────────────


@pytest.mark.django_db
def test_ad_hoc_uploads_do_not_supersede_each_other():
    """Two unrelated ad-hoc uploads (document_slot=None) on the same application
    must each be version=1 and must not soft-delete each other."""
    user = _make_user("u6")
    app = _make_application("s6")

    with patch("apps.documents.services.default_storage") as mock_s:
        mock_s.save.return_value = "documents/app/x.pdf"
        doc_a = upload_document(
            application=app,
            document_slot_id=None,
            milestone_instance=None,
            uploaded_by=user,
            filename="letter.pdf",
            content=_PDF_BYTES,
        )
        doc_b = upload_document(
            application=app,
            document_slot_id=None,
            milestone_instance=None,
            uploaded_by=user,
            filename="photo.jpg",
            content=_JPEG_BYTES,
        )

    assert doc_a.version == 1
    assert doc_b.version == 1
    doc_a.refresh_from_db()
    assert doc_a.is_deleted is False


# ── AC-21: presigned URL is a fresh call per request ─────────────────────────


@pytest.mark.django_db
def test_get_download_url_calls_storage_url_each_time():
    user = _make_user("u7")
    app = _make_application("s7")

    with patch("apps.documents.services.default_storage") as mock_s:
        mock_s.save.return_value = "documents/app/x.pdf"
        doc = upload_document(
            application=app,
            document_slot_id=None,
            milestone_instance=None,
            uploaded_by=user,
            filename="doc.pdf",
            content=_PDF_BYTES,
        )
        mock_s.url.return_value = "https://r2.example.com/signed?X-Amz-Expires=300"

    with patch("apps.documents.services.default_storage") as mock_u:
        mock_u.url.side_effect = [
            "https://r2.example.com/call1",
            "https://r2.example.com/call2",
        ]
        url1 = get_download_url(doc)
        url2 = get_download_url(doc)

    assert url1 != url2
    assert mock_u.url.call_count == 2


# ── AC-22: R2 failure leaves no orphan DB row ─────────────────────────────────


@pytest.mark.django_db
def test_r2_failure_leaves_no_orphan_row():
    user = _make_user("u8")
    app = _make_application("s8")

    with patch("apps.documents.services.default_storage") as mock_s:
        mock_s.save.side_effect = OSError("R2 unreachable")
        with pytest.raises(OSError):
            upload_document(
                application=app,
                document_slot_id=None,
                milestone_instance=None,
                uploaded_by=user,
                filename="doc.pdf",
                content=_PDF_BYTES,
            )

    assert DocumentUpload.objects.filter(application=app).count() == 0


# ── DocumentSlotListView ──────────────────────────────────────────────────────


@pytest.mark.django_db
def test_document_slot_list_returns_slots_for_milestone_instance(client):
    user = _make_user("officer", role="officer")
    client.force_login(user)

    sm = _make_stream_milestone("sv", "Mv")
    _make_slot(sm, "Annexure 10")
    app = _make_application("sv")
    mi = MilestoneInstance.objects.create(
        application=app,
        stream_milestone=sm,
        status=MilestoneInstance.STATUS_IN_PROGRESS,
        assigned_officer=user,
    )

    resp = client.get(f"/api/documents/slots/{mi.pk}/")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["document_type"] == "Annexure 10"
    assert data[0]["stream_code"] == "sv"
    assert data[0]["milestone_code"] == "Mv"


@pytest.mark.django_db
def test_document_slot_list_requires_auth(client):
    resp = client.get("/api/documents/slots/999/")
    assert resp.status_code in (401, 403)


# ── Allowed MIME types accepted ───────────────────────────────────────────────


@pytest.mark.django_db
@pytest.mark.parametrize(
    "content,filename",
    [
        (_PDF_BYTES, "doc.pdf"),
        (_JPEG_BYTES, "photo.jpg"),
        (_PNG_BYTES, "plan.png"),
    ],
)
def test_allowed_mime_types_accepted(content, filename):
    user = _make_user(f"u_{filename}")
    app = _make_application(f"sa_{filename}")

    with patch("apps.documents.services.default_storage") as mock_s:
        mock_s.save.return_value = f"documents/app/{filename}"
        doc = upload_document(
            application=app,
            document_slot_id=None,
            milestone_instance=None,
            uploaded_by=user,
            filename=filename,
            content=content,
        )

    assert doc.pk is not None
    assert doc.is_deleted is False
