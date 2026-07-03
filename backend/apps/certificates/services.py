from __future__ import annotations

import io
import logging
import os
import zipfile
from datetime import date

from django.conf import settings
from django.core.files.storage import default_storage
from django.db import transaction
from django.utils import timezone
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.pdfgen import canvas

from apps.applications.services import generate_application_number
from apps.certificates.models import Certificate
from apps.common.exceptions import DomainError
from apps.compliance.services import record_audit_event
from apps.documents.services import store_object
from apps.notifications.services import send_email

logger = logging.getLogger("apps")

_CERT_PREFIX_MAP: dict[str, str] = {
    Certificate.TYPE_AIP: "MBPAAIP",
    Certificate.TYPE_DEVELOPMENT_PERM: "MBPADP",
    Certificate.TYPE_COMMENCEMENT_PLINTH: "MBPACP",
    Certificate.TYPE_FURTHER_COMMENCEMENT: "MBPAFC",
    Certificate.TYPE_COMMENCEMENT_80PCT: "MBPAC8",
    Certificate.TYPE_COMMENCEMENT_REM20: "MBPACR",
    Certificate.TYPE_BUILDING_COMPLETION: "MBPABC",
    Certificate.TYPE_OC: "MBPAOC",
    Certificate.TYPE_DEMOLITION_CLEARANCE: "MBPADC",
}

_CERT_DISPLAY_NAME: dict[str, str] = dict(Certificate.TYPE_CHOICES)


def generate_certificate_number(cert_type: str) -> str:
    prefix = _CERT_PREFIX_MAP[cert_type]
    return generate_application_number(prefix=prefix)


def _render_certificate_pdf(
    application,
    cert_type: str,
    cert_number: str,
    issued_by,
    issued_at: date,
) -> bytes:
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4

    # Header
    c.setFont("Helvetica-Bold", 18)
    c.drawCentredString(width / 2, height - 3 * cm, "Mumbai Port Authority")
    c.setFont("Helvetica-Bold", 14)
    c.drawCentredString(width / 2, height - 4.2 * cm, "Building Permission Portal")

    # Certificate title
    cert_title = _CERT_DISPLAY_NAME.get(cert_type, cert_type)
    c.setFont("Helvetica-Bold", 16)
    c.drawCentredString(width / 2, height - 6 * cm, cert_title.upper())

    # Border
    c.setLineWidth(2)
    c.rect(2 * cm, 2 * cm, width - 4 * cm, height - 4 * cm)

    # Fields
    c.setFont("Helvetica", 11)
    y = height - 8 * cm
    line_height = 0.8 * cm
    fields = [
        ("Certificate Number", cert_number),
        ("Application Number", application.application_number or "—"),
        (
            "Applicant",
            application.submitted_by.get_full_name() or application.submitted_by.username,
        ),
        ("Plot Reference", application.plpn or "—"),
        ("Issue Date", issued_at.strftime("%d %B %Y")),
        ("Issued By", issued_by.get_full_name() or issued_by.username),
    ]
    for label, value in fields:
        c.setFont("Helvetica-Bold", 11)
        c.drawString(3 * cm, y, f"{label}:")
        c.setFont("Helvetica", 11)
        c.drawString(9 * cm, y, str(value))
        y -= line_height

    # Watermark — unsigned
    c.setFont("Helvetica-Bold", 36)
    c.setFillColorRGB(0.85, 0.85, 0.85)
    c.saveState()
    c.translate(width / 2, height / 2)
    c.rotate(45)
    c.drawCentredString(0, 0, "UNSIGNED — PENDING DSC")
    c.restoreState()

    c.setFont("Helvetica", 9)
    c.setFillColorRGB(0, 0, 0)
    footer = "This document is valid only when digitally signed by the issuing officer."
    c.drawCentredString(width / 2, 2.5 * cm, footer)

    c.showPage()
    c.save()
    return buffer.getvalue()


@transaction.atomic
def generate_certificate(*, application, cert_type: str, issued_by) -> Certificate:
    cert_number = generate_certificate_number(cert_type)
    issued_at = timezone.now().date()
    pdf_bytes = _render_certificate_pdf(application, cert_type, cert_number, issued_by, issued_at)
    r2_key = store_object(
        prefix="certificates",
        filename=f"{cert_number}.pdf",
        content=pdf_bytes,
        content_type="application/pdf",
    )
    cert = Certificate.objects.create(
        application=application,
        certificate_type=cert_type,
        certificate_number=cert_number,
        r2_object_key=r2_key,
        issued_by=issued_by,
    )
    record_audit_event(
        verb="certificate.generated",
        target_type="Certificate",
        target_id=cert.pk,
        actor=issued_by,
        payload={
            "certificate_number": cert_number,
            "certificate_type": cert_type,
            "application": application.application_number,
        },
    )
    return cert


def receive_signed_certificate(
    *, certificate: Certificate, signed_pdf_bytes: bytes, expected_officer=None
) -> Certificate:
    """
    AC-25: validate the DSC signature on a returned PDF against the CCA trust root.
    Sets signature_verified=True and records dsc_serial_used only on a genuine pass.

    HIGH-3: if `expected_officer` is given, the signing certificate's serial must
    match that officer's registered DSC serial. Without this, any CCA-trusted DSC
    (e.g. a different officer's, or an unrelated citizen's) would be accepted as
    long as it chains to the trust root — allowing signer substitution even when
    the uploading officer is correctly assigned to the application.
    """
    from asn1crypto import x509 as asn1_x509
    from pyhanko.pdf_utils.reader import PdfFileReader
    from pyhanko.sign.validation import validate_pdf_signature
    from pyhanko_certvalidator import ValidationContext

    reader = PdfFileReader(io.BytesIO(signed_pdf_bytes))
    sigs = reader.embedded_regular_signatures
    if not sigs:
        raise DomainError("No embedded DSC signature found in the submitted PDF (AC-25).")

    trust_root_path = settings.DSC_TRUST_ROOT_PATH
    try:
        with open(trust_root_path, "rb") as fh:
            root_der = fh.read()
    except OSError as exc:
        raise DomainError(f"DSC trust root not found at {trust_root_path}: {exc}") from exc

    root_cert = asn1_x509.Certificate.load(root_der)
    vc = ValidationContext(
        trust_roots=[root_cert],
        revocation_mode=settings.DSC_REVOCATION_MODE,
        allow_fetching=settings.DSC_ALLOW_REVOCATION_FETCHING,
    )
    sig = sigs[0]
    status = validate_pdf_signature(sig, vc)

    if not (status.intact and status.valid and status.trusted):
        raise DomainError(
            "DSC signature validation failed (AC-25): "
            f"intact={status.intact}, valid={status.valid}, trusted={status.trusted}."
        )

    dsc_serial = format(sig.signer_cert.serial_number, "x").upper()

    if expected_officer is not None:
        officer_profile = getattr(expected_officer, "officer_profile", None)
        registered_serial = (getattr(officer_profile, "dsc_serial", "") or "").strip().upper()
        if not registered_serial or registered_serial != dsc_serial:
            raise DomainError(
                "DSC signer does not match the assigned officer's registered "
                "certificate serial (AC-25)."
            )

    new_key = store_object(
        prefix="certificates",
        filename=f"{certificate.certificate_number}_signed.pdf",
        content=signed_pdf_bytes,
        content_type="application/pdf",
    )
    certificate.r2_object_key = new_key
    certificate.signature_verified = True
    certificate.dsc_serial_used = dsc_serial
    certificate.save(update_fields=["r2_object_key", "signature_verified", "dsc_serial_used"])

    record_audit_event(
        verb="certificate.signed",
        target_type="Certificate",
        target_id=certificate.pk,
        payload={
            "certificate_number": certificate.certificate_number,
            "dsc_serial": dsc_serial,
        },
    )
    return certificate


def _safe_zip_member_name(directory: str, discriminator, filename: str) -> str:
    """Sanitize a filename before writing it into the dossier zip.

    `original_filename` is client-supplied and never validated as a bare name
    (AC-19 only checks content bytes). A name like "../../evil.pdf" would embed
    a path-traversal entry in the archive that a downstream consumer could
    later write outside the target directory on extraction (Zip-Slip). Keep
    only the basename and prefix the row's PK so same-named uploads can't
    collide with — and silently overwrite — each other inside the archive.
    """
    safe_name = os.path.basename(filename.replace("\\", "/")) or "file"
    return f"{directory}/{discriminator}-{safe_name}"


def compile_final_dossier(*, application, triggered_by) -> str:
    """
    Zip all active documents and issued certificates; store the bundle in R2;
    email the applicant. Triggered automatically on OC milestone approval.

    No zip-bomb guard is needed on the write side: every member's content
    comes from either an already size-capped upload (DOCUMENT_MAX_UPLOAD_SIZE_BYTES,
    AC-19) or a locally rendered certificate PDF, so the archive's total size is
    inherently bounded by the application's document/certificate count.
    """
    documents = application.documents.filter(is_deleted=False)
    certificates = application.certificates.filter(revoked_at__isnull=True)

    expected_count = documents.count() + certificates.count()
    items_added = 0

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for doc in documents:
            try:
                content = default_storage.open(doc.r2_object_key).read()
                zf.writestr(
                    _safe_zip_member_name("documents", doc.pk, doc.original_filename), content
                )
                items_added += 1
            except Exception:
                logger.warning("Dossier: skipping missing document object %s", doc.r2_object_key)
        for cert in certificates:
            try:
                content = default_storage.open(cert.r2_object_key).read()
                zf.writestr(f"certificates/{cert.certificate_number}.pdf", content)
                items_added += 1
            except Exception:
                logger.warning("Dossier: skipping missing cert object %s", cert.r2_object_key)

    if expected_count > 0 and items_added == 0:
        raise DomainError(
            f"Dossier compilation aborted: 0 of {expected_count} expected items could be read "
            "from storage. Check bucket credentials and configuration."
        )

    zip_key = store_object(
        prefix="dossiers",
        filename=f"{application.application_number}_dossier.zip",
        content=zip_buffer.getvalue(),
        content_type="application/zip",
    )

    send_email(
        to=application.submitted_by.email,
        template="dossier_ready",
        context={
            "subject": f"Your MbPA Portal Dossier is Ready — {application.application_number}",
            "application_number": application.application_number,
            "applicant_name": (
                application.submitted_by.get_full_name() or application.submitted_by.username
            ),
        },
    )

    record_audit_event(
        verb="dossier.compiled",
        target_type="Application",
        target_id=application.pk,
        actor=triggered_by,
        payload={
            "application": application.application_number,
            "zip_key": zip_key,
        },
    )
    return zip_key
