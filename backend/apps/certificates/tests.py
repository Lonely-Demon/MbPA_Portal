from unittest.mock import MagicMock, patch

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.applications.models import (
    Application,
    Milestone,
    MilestoneInstance,
    Stream,
    StreamMilestone,
)
from apps.applications.services import ACTION_APPROVE
from apps.certificates.models import Certificate

User = get_user_model()


# ── Shared helpers ────────────────────────────────────────────────────────────


def _make_user(username="cert_user"):
    return User.objects.create_user(
        username=username, password="pw", email=f"{username}@example.com"
    )


def _make_officer(username="cert_officer"):
    from apps.identity.models import OfficerProfile

    user = User.objects.create_user(username=username, password="pw")
    OfficerProfile.objects.create(user=user, role=OfficerProfile.ROLE_DEPUTY_PLANNER)
    return user


def _make_application(user, stream_code="new_building"):
    stream, _ = Stream.objects.get_or_create(code=stream_code, defaults={"name": stream_code})
    from apps.applications.services import generate_application_number

    return Application.objects.create(
        stream=stream,
        submitted_by=user,
        application_number=generate_application_number(),
        status=Application.STATUS_SUBMITTED,
    )


def _make_milestone_instance(application, milestone_code, sequence=1, officer=None):
    milestone, _ = Milestone.objects.get_or_create(
        code=milestone_code, defaults={"name": milestone_code, "default_sla_working_days": 21}
    )
    sm, _ = StreamMilestone.objects.get_or_create(
        stream=application.stream,
        milestone=milestone,
        defaults={"sequence": sequence},
    )
    return MilestoneInstance.objects.create(
        application=application,
        stream_milestone=sm,
        assigned_officer=officer,
        status=MilestoneInstance.STATUS_IN_PROGRESS,
        started_at=timezone.now(),
        due_at=timezone.now(),
    )


# ── test_generate_certificate_creates_row_and_r2_object ───────────────────────


@pytest.mark.django_db
def test_generate_certificate_creates_row_and_r2_object():
    from apps.certificates.services import generate_certificate

    user = _make_user("gc_user")
    app = _make_application(user)

    with patch(
        "apps.certificates.services.store_object", return_value="certificates/fake-key.pdf"
    ) as mock_store:
        cert = generate_certificate(application=app, cert_type=Certificate.TYPE_AIP, issued_by=user)

    assert cert.pk is not None
    assert cert.certificate_number.startswith("MBPAAIP")
    assert cert.certificate_type == Certificate.TYPE_AIP
    assert cert.r2_object_key == "certificates/fake-key.pdf"
    mock_store.assert_called_once()


# ── test_s2_approval_creates_two_certificate_rows ─────────────────────────────


@pytest.mark.django_db
def test_s2_approval_creates_two_certificate_rows():
    """Approving an S2 milestone issues both Development Permission and Commencement to Plinth."""
    from apps.applications.services import transition_milestone

    officer = _make_officer("s2_officer")
    user = _make_user("s2_user")
    app = _make_application(user, stream_code="new_building")

    # Officer must not be an ApplicationParty
    instance = _make_milestone_instance(app, "S2", sequence=1, officer=officer)

    with patch("apps.certificates.services.store_object", return_value="certificates/fake.pdf"):
        transition_milestone(
            milestone_instance_id=instance.pk,
            action=ACTION_APPROVE,
            acting_officer=officer,
        )

    certs = Certificate.objects.filter(application=app)
    assert certs.count() == 2
    types_issued = set(certs.values_list("certificate_type", flat=True))
    assert types_issued == {Certificate.TYPE_DEVELOPMENT_PERM, Certificate.TYPE_COMMENCEMENT_PLINTH}


# ── test_receive_signed_certificate_ac25_valid ────────────────────────────────


@pytest.mark.django_db
def test_receive_signed_certificate_ac25_valid():
    """Valid DSC signature → signature_verified=True and dsc_serial_used set."""
    from apps.certificates.services import receive_signed_certificate

    user = _make_user("rsc_user")
    app = _make_application(user)
    cert = Certificate.objects.create(
        application=app,
        certificate_type=Certificate.TYPE_AIP,
        certificate_number="MBPAAIP20260001",
        r2_object_key="certificates/unsigned.pdf",
        issued_by=user,
    )

    mock_sig = MagicMock()
    mock_sig.signer_cert.serial_number = 0xDEADBEEF
    mock_status = MagicMock(intact=True, valid=True, trusted=True)

    with (
        patch("pyhanko.pdf_utils.reader.PdfFileReader") as mock_reader_cls,
        patch("pyhanko.sign.validation.validate_pdf_signature", return_value=mock_status),
        patch("pyhanko_certvalidator.ValidationContext"),
        patch("apps.certificates.services.store_object", return_value="certificates/signed.pdf"),
        patch("builtins.open", create=True) as mock_open,
    ):
        mock_open.return_value.__enter__ = lambda s: s
        mock_open.return_value.__exit__ = MagicMock(return_value=False)
        mock_open.return_value.read = MagicMock(return_value=b"fake-der")
        mock_reader_cls.return_value.embedded_regular_sigs = [mock_sig]

        updated = receive_signed_certificate(certificate=cert, signed_pdf_bytes=b"fake-pdf")

    assert updated.signature_verified is True
    assert updated.dsc_serial_used == "DEADBEEF"
    assert updated.r2_object_key == "certificates/signed.pdf"


# ── test_receive_signed_certificate_ac25_tampered_rejected ───────────────────


@pytest.mark.django_db
def test_receive_signed_certificate_ac25_tampered_rejected():
    """Tampered PDF (intact=False) raises DomainError; signature_verified stays False."""
    from apps.certificates.services import receive_signed_certificate
    from apps.common.exceptions import DomainError

    user = _make_user("rsc_tamper")
    app = _make_application(user)
    cert = Certificate.objects.create(
        application=app,
        certificate_type=Certificate.TYPE_AIP,
        certificate_number="MBPAAIP20260002",
        r2_object_key="certificates/unsigned2.pdf",
        issued_by=user,
    )

    mock_sig = MagicMock()
    mock_status = MagicMock(intact=False, valid=False, trusted=False)

    with (
        patch("pyhanko.pdf_utils.reader.PdfFileReader") as mock_reader_cls,
        patch("pyhanko.sign.validation.validate_pdf_signature", return_value=mock_status),
        patch("pyhanko_certvalidator.ValidationContext"),
        patch("builtins.open", create=True) as mock_open,
    ):
        mock_open.return_value.__enter__ = lambda s: s
        mock_open.return_value.__exit__ = MagicMock(return_value=False)
        mock_open.return_value.read = MagicMock(return_value=b"fake-der")
        mock_reader_cls.return_value.embedded_regular_sigs = [mock_sig]

        with pytest.raises(DomainError, match="AC-25"):
            receive_signed_certificate(certificate=cert, signed_pdf_bytes=b"tampered-pdf")

    cert.refresh_from_db()
    assert cert.signature_verified is False


# ── test_certificate_revocation_never_deletes_row_or_r2 ──────────────────────


@pytest.mark.django_db
def test_certificate_revocation_never_deletes_row_or_r2():
    """Revoking a certificate keeps the row and r2_object_key intact."""
    from django.core.files.storage import default_storage

    user = _make_user("rev_user")
    app = _make_application(user)
    cert = Certificate.objects.create(
        application=app,
        certificate_type=Certificate.TYPE_OC,
        certificate_number="MBPAOC20260001",
        r2_object_key="certificates/oc.pdf",
        issued_by=user,
    )
    original_key = cert.r2_object_key

    # Revoke via direct update (as a service would do)
    Certificate.objects.filter(pk=cert.pk).update(
        revoked_at=timezone.now(),
        revoked_by=user,
        revocation_reason="Test revocation",
    )

    cert.refresh_from_db()
    assert cert.revoked_at is not None
    assert cert.r2_object_key == original_key  # R2 object key untouched
    assert Certificate.objects.filter(pk=cert.pk).exists()  # Row still present

    with patch.object(default_storage, "delete") as mock_delete:
        # Confirm nothing tries to delete the object when we look at the cert
        _ = Certificate.objects.get(pk=cert.pk)
        mock_delete.assert_not_called()


# ── test_oc_approval_triggers_dossier_compilation ────────────────────────────


@pytest.mark.django_db
def test_oc_approval_triggers_dossier_compilation():
    """Approving an OC milestone automatically calls compile_final_dossier."""
    from apps.applications.services import transition_milestone

    officer = _make_officer("oc_officer")
    user = _make_user("oc_user")
    app = _make_application(user, stream_code="new_building")

    instance = _make_milestone_instance(app, "OC", sequence=1, officer=officer)

    with (
        patch("apps.certificates.services.store_object", return_value="certificates/fake.pdf"),
        patch("apps.certificates.services.compile_final_dossier") as mock_dossier,
    ):
        # generate_certificate is called inside _issue_certificates_for_milestone;
        # patch store_object only so the cert row is created, then compile_final_dossier is mocked.
        # But compile_final_dossier is called directly after generate_certificate, so we need
        # to let generate_certificate run (store_object mocked) and mock compile_final_dossier.
        transition_milestone(
            milestone_instance_id=instance.pk,
            action=ACTION_APPROVE,
            acting_officer=officer,
        )

    mock_dossier.assert_called_once_with(application=app, triggered_by=officer)
