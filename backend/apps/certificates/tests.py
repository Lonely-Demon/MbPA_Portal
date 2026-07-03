import io
from unittest.mock import MagicMock, patch

# Pre-import pyHanko modules before any test patches PdfFileReader.
# pyhanko.pdf_utils.incremental_writer binds PdfFileReader at import time via
# "from pyhanko.pdf_utils.reader import PdfFileReader".  If that module is first
# loaded DURING a patch("pyhanko.pdf_utils.reader.PdfFileReader") block, its
# local reference permanently points to the mock.  Importing everything here
# guarantees the real class is captured in each module's namespace.
import pyhanko.pdf_utils.incremental_writer
import pyhanko.sign.signers
import pyhanko.sign.validation  # noqa: F401
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


def _make_officer(username="cert_officer", dsc_serial=""):
    from apps.identity.models import OfficerProfile

    user = User.objects.create_user(username=username, password="pw")
    OfficerProfile.objects.create(
        user=user, role=OfficerProfile.ROLE_DEPUTY_PLANNER, dsc_serial=dsc_serial
    )
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
        patch("asn1crypto.x509.Certificate.load", return_value=MagicMock()),
        patch("apps.certificates.services.store_object", return_value="certificates/signed.pdf"),
        patch("builtins.open", create=True) as mock_open,
    ):
        mock_open.return_value.__enter__ = lambda s: s
        mock_open.return_value.__exit__ = MagicMock(return_value=False)
        mock_open.return_value.read = MagicMock(return_value=b"fake-der")
        mock_reader_cls.return_value.embedded_regular_signatures = [mock_sig]

        updated = receive_signed_certificate(certificate=cert, signed_pdf_bytes=b"fake-pdf")

    assert updated.signature_verified is True
    assert updated.dsc_serial_used == "DEADBEEF"
    assert updated.r2_object_key == "certificates/signed.pdf"


# ── HIGH-3: officer DSC signer allowlist ──────────────────────────────────────


@pytest.mark.django_db
def test_receive_signed_certificate_rejects_signer_not_in_officer_allowlist():
    """A DSC that validates against the trust root but doesn't match the assigned
    officer's registered dsc_serial must be rejected (signer substitution)."""
    from apps.certificates.services import receive_signed_certificate
    from apps.common.exceptions import DomainError

    officer = _make_officer("allowlist_officer", dsc_serial="AAAAAAAA")

    user = _make_user("allowlist_user")
    app = _make_application(user)
    cert = Certificate.objects.create(
        application=app,
        certificate_type=Certificate.TYPE_AIP,
        certificate_number="MBPAAIP20260003",
        r2_object_key="certificates/unsigned3.pdf",
        issued_by=user,
    )

    mock_sig = MagicMock()
    mock_sig.signer_cert.serial_number = 0xDEADBEEF  # does not match "AAAAAAAA"
    mock_status = MagicMock(intact=True, valid=True, trusted=True)

    with (
        patch("pyhanko.pdf_utils.reader.PdfFileReader") as mock_reader_cls,
        patch("pyhanko.sign.validation.validate_pdf_signature", return_value=mock_status),
        patch("pyhanko_certvalidator.ValidationContext"),
        patch("asn1crypto.x509.Certificate.load", return_value=MagicMock()),
        patch("builtins.open", create=True) as mock_open,
    ):
        mock_open.return_value.__enter__ = lambda s: s
        mock_open.return_value.__exit__ = MagicMock(return_value=False)
        mock_open.return_value.read = MagicMock(return_value=b"fake-der")
        mock_reader_cls.return_value.embedded_regular_signatures = [mock_sig]

        with pytest.raises(DomainError, match="does not match"):
            receive_signed_certificate(
                certificate=cert, signed_pdf_bytes=b"fake-pdf", expected_officer=officer
            )

    cert.refresh_from_db()
    assert cert.signature_verified is False


@pytest.mark.django_db
def test_receive_signed_certificate_accepts_signer_matching_officer_allowlist():
    """A DSC serial matching the assigned officer's registered dsc_serial passes."""
    from apps.certificates.services import receive_signed_certificate

    officer = _make_officer("allowlist_officer_ok", dsc_serial="DEADBEEF")

    user = _make_user("allowlist_user_ok")
    app = _make_application(user)
    cert = Certificate.objects.create(
        application=app,
        certificate_type=Certificate.TYPE_AIP,
        certificate_number="MBPAAIP20260004",
        r2_object_key="certificates/unsigned4.pdf",
        issued_by=user,
    )

    mock_sig = MagicMock()
    mock_sig.signer_cert.serial_number = 0xDEADBEEF
    mock_status = MagicMock(intact=True, valid=True, trusted=True)

    with (
        patch("pyhanko.pdf_utils.reader.PdfFileReader") as mock_reader_cls,
        patch("pyhanko.sign.validation.validate_pdf_signature", return_value=mock_status),
        patch("pyhanko_certvalidator.ValidationContext"),
        patch("asn1crypto.x509.Certificate.load", return_value=MagicMock()),
        patch("apps.certificates.services.store_object", return_value="certificates/signed4.pdf"),
        patch("builtins.open", create=True) as mock_open,
    ):
        mock_open.return_value.__enter__ = lambda s: s
        mock_open.return_value.__exit__ = MagicMock(return_value=False)
        mock_open.return_value.read = MagicMock(return_value=b"fake-der")
        mock_reader_cls.return_value.embedded_regular_signatures = [mock_sig]

        updated = receive_signed_certificate(
            certificate=cert, signed_pdf_bytes=b"fake-pdf", expected_officer=officer
        )

    assert updated.signature_verified is True
    assert updated.dsc_serial_used == "DEADBEEF"


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
        patch("asn1crypto.x509.Certificate.load", return_value=MagicMock()),
        patch("builtins.open", create=True) as mock_open,
    ):
        mock_open.return_value.__enter__ = lambda s: s
        mock_open.return_value.__exit__ = MagicMock(return_value=False)
        mock_open.return_value.read = MagicMock(return_value=b"fake-der")
        mock_reader_cls.return_value.embedded_regular_signatures = [mock_sig]

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


# ── Medium: Zip-Slip protection in compile_final_dossier ─────────────────────


@pytest.mark.django_db
def test_compile_final_dossier_sanitizes_path_traversal_filenames():
    """A document uploaded with a path-traversal filename must not embed that
    traversal in the zip archive's member names (Zip-Slip)."""
    from apps.certificates.services import compile_final_dossier
    from apps.documents.models import DocumentUpload

    user = _make_user("dossier_user")
    app = _make_application(user)

    evil_doc = DocumentUpload.objects.create(
        application=app,
        uploaded_by=user,
        r2_object_key="documents/evil.pdf",
        original_filename="../../../etc/passwd",
        content_type="application/pdf",
        size_bytes=10,
        version=1,
    )

    with (
        patch("apps.certificates.services.default_storage") as mock_storage,
        patch("apps.certificates.services.store_object", return_value="dossiers/fake.zip"),
        patch("apps.certificates.services.send_email"),
    ):
        mock_storage.open.return_value.read.return_value = b"content"

        with patch("apps.certificates.services.zipfile.ZipFile") as mock_zip_cls:
            mock_zf = mock_zip_cls.return_value.__enter__.return_value
            compile_final_dossier(application=app, triggered_by=user)

    names = [call.args[0] for call in mock_zf.writestr.call_args_list]
    assert len(names) == 1
    assert names[0] == f"documents/{evil_doc.pk}-passwd"
    assert ".." not in names[0]


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


# ── test_receive_signed_certificate_ac25_integration ─────────────────────────


@pytest.mark.django_db
def test_receive_signed_certificate_ac25_integration():
    """
    Real pyHanko round-trip: generate a self-signed cert, sign a PDF, validate end-to-end.
    Nothing in the pyHanko/asn1crypto stack is mocked — this proves the API surface is correct.
    """
    import datetime
    import os
    import tempfile

    from cryptography import x509 as cx509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives.serialization import pkcs12
    from cryptography.x509.oid import NameOID
    from django.test import override_settings
    from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
    from pyhanko.sign import signers
    from pyhanko.sign.fields import SigFieldSpec
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas as rl_canvas

    from apps.certificates.services import receive_signed_certificate

    # Build a self-signed cert; pyHanko requires content_commitment (non-repudiation) key usage.
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = cx509.Name([cx509.NameAttribute(NameOID.COMMON_NAME, "Test DSC Officer")])
    cert = (
        cx509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(cx509.random_serial_number())
        .not_valid_before(datetime.datetime.now(datetime.UTC))
        .not_valid_after(datetime.datetime.now(datetime.UTC) + datetime.timedelta(days=365))
        .add_extension(cx509.BasicConstraints(ca=True, path_length=None), critical=True)
        .add_extension(
            cx509.KeyUsage(
                digital_signature=True,
                content_commitment=True,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=True,
                crl_sign=True,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .sign(key, hashes.SHA256())
    )
    cert_der = cert.public_bytes(serialization.Encoding.DER)
    expected_serial = format(cert.serial_number, "x").upper()

    pfx_data = pkcs12.serialize_key_and_certificates(
        name=b"test-dsc",
        key=key,
        cert=cert,
        cas=None,
        encryption_algorithm=serialization.NoEncryption(),
    )

    pfx_tmp = tempfile.NamedTemporaryFile(suffix=".p12", delete=False)
    pfx_tmp.write(pfx_data)
    pfx_tmp.close()

    der_tmp = tempfile.NamedTemporaryFile(suffix=".der", delete=False)
    der_tmp.write(cert_der)
    der_tmp.close()

    try:
        signer = signers.SimpleSigner.load_pkcs12(pfx_tmp.name)

        buf = io.BytesIO()
        c = rl_canvas.Canvas(buf, pagesize=A4)
        c.drawString(100, 700, "Integration Test Certificate")
        c.showPage()
        c.save()

        writer = IncrementalPdfFileWriter(io.BytesIO(buf.getvalue()))
        out = io.BytesIO()
        signers.sign_pdf(
            writer,
            signers.PdfSignatureMetadata(field_name="Sig1"),
            signer=signer,
            new_field_spec=SigFieldSpec("Sig1", on_page=0, box=(100, 100, 300, 200)),
            output=out,
        )
        signed_pdf_bytes = out.getvalue()

        user = _make_user("ac25_int_user")
        app = _make_application(user)
        db_cert = Certificate.objects.create(
            application=app,
            certificate_type=Certificate.TYPE_AIP,
            certificate_number="MBPAAIP20260099",
            r2_object_key="certificates/unsigned_int.pdf",
            issued_by=user,
        )

        with (
            override_settings(DSC_TRUST_ROOT_PATH=der_tmp.name),
            patch(
                "apps.certificates.services.store_object",
                return_value="certificates/signed_int.pdf",
            ),
        ):
            updated = receive_signed_certificate(
                certificate=db_cert, signed_pdf_bytes=signed_pdf_bytes
            )

        assert updated.signature_verified is True
        assert updated.dsc_serial_used == expected_serial
        assert updated.r2_object_key == "certificates/signed_int.pdf"
    finally:
        os.unlink(pfx_tmp.name)
        os.unlink(der_tmp.name)
