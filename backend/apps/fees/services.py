from __future__ import annotations

from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone

from apps.compliance.services import record_audit_event
from apps.fees.models import Concession, ConfigParameter, FeeAssessment, Payment


def _compute_fee_breakdown(
    *,
    proposed_bua_sqm: Decimal,
    plot_area_sqm: Decimal | None,
    zonal_rrr: Decimal,
    open_space_shortfall_sqm: Decimal | None = None,
    parking_waiver_sqm: Decimal | None = None,
) -> dict:
    """
    Pure arithmetic — no DB writes. Returns a breakdown dict with keys:
      scrutiny_fee, security_deposit, debris_deposit,
      premiums (list of concession dicts), premium_total, total_amount,
      config_snapshot (the scrutiny_fee_per_sqm ConfigParameter row).

    Each concession dict carries the fields needed to create a Concession row:
      concession_type, detected_value, benchmark_value, premium_amount,
      source, detection_method.
    """
    bua = proposed_bua_sqm
    rrr = zonal_rrr

    scrutiny_rate = get_decimal_config("scrutiny_fee_per_sqm")
    security_rate = get_decimal_config("security_deposit_per_sqm")
    debris_rate = get_decimal_config("debris_deposit_per_sqm")
    coeff_fsi = get_decimal_config("premium_coefficient.additional_fsi")
    coeff_open = get_decimal_config("premium_coefficient.open_space_shortfall")
    coeff_park = get_decimal_config("premium_coefficient.parking_waiver")
    benchmark_fsi = get_decimal_config("benchmark.additional_fsi")
    config_snapshot = get_active_config("scrutiny_fee_per_sqm")

    q = Decimal("0.01")
    scrutiny = (scrutiny_rate * bua).quantize(q)
    security = (security_rate * bua).quantize(q)
    debris = (debris_rate * bua).quantize(q)

    premiums = []

    if plot_area_sqm and plot_area_sqm > 0 and (bua / plot_area_sqm) > benchmark_fsi:
        excess = bua - plot_area_sqm * benchmark_fsi
        premiums.append(
            {
                "concession_type": Concession.TYPE_FSI,
                "detected_value": (bua / plot_area_sqm).quantize(Decimal("0.0001")),
                "benchmark_value": benchmark_fsi.quantize(Decimal("0.0001")),
                "premium_amount": (excess * rrr * coeff_fsi).quantize(q),
                "source": "UPDR-2026 Table 4",
                "detection_method": Concession.DETECTION_AUTO,
            }
        )

    if open_space_shortfall_sqm is not None:
        premiums.append(
            {
                "concession_type": Concession.TYPE_OPEN_SPACE,
                "detected_value": open_space_shortfall_sqm.quantize(Decimal("0.0001")),
                "benchmark_value": Decimal("0"),
                "premium_amount": (open_space_shortfall_sqm * rrr * coeff_open).quantize(q),
                "source": "Officer-declared",
                "detection_method": Concession.DETECTION_DECLARED,
            }
        )

    if parking_waiver_sqm is not None:
        premiums.append(
            {
                "concession_type": Concession.TYPE_PARKING,
                "detected_value": parking_waiver_sqm.quantize(Decimal("0.0001")),
                "benchmark_value": Decimal("0"),
                "premium_amount": (parking_waiver_sqm * rrr * coeff_park).quantize(q),
                "source": "Officer-declared",
                "detection_method": Concession.DETECTION_DECLARED,
            }
        )

    premium_total = sum((p["premium_amount"] for p in premiums), Decimal("0"))
    total = (scrutiny + security + debris + premium_total).quantize(q)

    return {
        "scrutiny_fee": scrutiny,
        "security_deposit": security,
        "debris_deposit": debris,
        "premiums": premiums,
        "premium_total": premium_total,
        "total_amount": total,
        "config_snapshot": config_snapshot,
    }


def get_active_config(key: str) -> ConfigParameter:
    """
    Return the ConfigParameter with the latest effective_from <= today for key.

    Raises KeyError if no matching row exists. Callers that need a fallback
    default must handle the KeyError explicitly — silent fallbacks hide
    misconfigured environments.
    """
    today = timezone.now().date()
    try:
        return ConfigParameter.objects.filter(key=key, effective_from__lte=today).latest(
            "effective_from"
        )
    except ConfigParameter.DoesNotExist:
        raise KeyError(f"No active ConfigParameter found for key {key!r}") from None


def get_decimal_config(key: str) -> Decimal:
    """Return the active config value for key as a Decimal."""
    param = get_active_config(key)
    try:
        return Decimal(param.value)
    except InvalidOperation:
        raise ValueError(
            f"ConfigParameter {key!r} has value {param.value!r} which cannot be "
            "parsed as a Decimal. Fix the stored value."
        ) from None


def _get_current_assessment(application) -> FeeAssessment | None:
    return FeeAssessment.objects.filter(application=application, is_current=True).first()


@transaction.atomic
def assess_fee(
    *,
    application,
    assessed_by,
    open_space_shortfall_sqm: Decimal | None = None,
    parking_waiver_sqm: Decimal | None = None,
) -> FeeAssessment:
    from apps.common.exceptions import DomainError

    bua = application.proposed_bua_sqm
    rrr = application.zonal_rrr
    if bua is None or rrr is None:
        raise DomainError(
            "Cannot assess fee: application.proposed_bua_sqm and zonal_rrr must both be set."
        )

    bd = _compute_fee_breakdown(
        proposed_bua_sqm=bua,
        plot_area_sqm=application.plot_area_sqm,
        zonal_rrr=rrr,
        open_space_shortfall_sqm=open_space_shortfall_sqm,
        parking_waiver_sqm=parking_waiver_sqm,
    )

    for p in bd["premiums"]:
        Concession.objects.create(application=application, **p)

    assessment = FeeAssessment.objects.create(
        application=application,
        config_version=bd["config_snapshot"],
        scrutiny_fee=bd["scrutiny_fee"],
        security_deposit=bd["security_deposit"],
        debris_deposit=bd["debris_deposit"],
        premium_total=bd["premium_total"],
        total_amount=bd["total_amount"],
        assessed_by=assessed_by,
        bua_sqm_snapshot=bua,
        zonal_rrr_snapshot=rrr,
        is_current=True,
        is_locked=False,
    )

    record_audit_event(
        verb="fee.assessed",
        target_type="FeeAssessment",
        target_id=assessment.pk,
        actor=assessed_by,
        payload={"total": str(bd["total_amount"])},
    )
    return assessment


@transaction.atomic
def reassess_fee(
    *,
    application,
    assessed_by,
    open_space_shortfall_sqm: Decimal | None = None,
    parking_waiver_sqm: Decimal | None = None,
) -> FeeAssessment:
    from apps.common.exceptions import DomainError, FeeAssessmentLockedError

    old = _get_current_assessment(application)
    if old is None:
        raise DomainError("No current FeeAssessment exists for this application.")

    if old.is_locked:
        raise FeeAssessmentLockedError(
            "AC-16: Cannot reassess — the current assessment is locked after payment verification."
        )

    if old.payments.exclude(status=Payment.STATUS_REJECTED).exists():
        raise DomainError(
            "Cannot reassess while non-rejected payments exist. "
            "All pending payments must be rejected before reassessment."
        )

    old_total = old.total_amount
    old.is_current = False
    old.save()

    application.concessions.all().delete()

    new_assessment = assess_fee(
        application=application,
        assessed_by=assessed_by,
        open_space_shortfall_sqm=open_space_shortfall_sqm,
        parking_waiver_sqm=parking_waiver_sqm,
    )

    record_audit_event(
        verb="fee.reassessed",
        target_type="FeeAssessment",
        target_id=new_assessment.pk,
        actor=assessed_by,
        payload={"old_total": str(old_total), "new_total": str(new_assessment.total_amount)},
    )
    return new_assessment


def record_payment(
    *,
    application,
    challan_reference: str,
    claimed_amount: Decimal,
    payment_date,
    recorded_by,
) -> Payment:
    from apps.common.exceptions import DomainError

    if (
        Payment.objects.filter(challan_reference=challan_reference)
        .exclude(status=Payment.STATUS_REJECTED)
        .exists()
    ):
        raise DomainError(
            f"Challan reference {challan_reference!r} already has an active payment record. "
            "A mismatch requires officer resolution; a new challan is needed for any shortfall."
        )

    assessment = _get_current_assessment(application)
    if assessment is None:
        raise DomainError("No fee assessment exists for this application.")

    payment = Payment.objects.create(
        application=application,
        assessment=assessment,
        challan_reference=challan_reference,
        claimed_amount=claimed_amount,
        payment_date=payment_date,
        recorded_by=recorded_by,
        status=Payment.STATUS_CLAIMED,
    )

    record_audit_event(
        verb="payment.claimed",
        target_type="Payment",
        target_id=payment.pk,
        actor=recorded_by,
        payload={"challan_reference": challan_reference, "claimed_amount": str(claimed_amount)},
    )
    return payment


@transaction.atomic
def verify_payment(
    *,
    payment: Payment,
    decision: str,
    verified_amount: Decimal,
    verified_by,
    remarks: str = "",
) -> Payment:
    from apps.common.exceptions import DomainError

    if payment.status != Payment.STATUS_CLAIMED:
        raise DomainError(
            f"Payment {payment.pk} has status {payment.status!r}; "
            "only 'claimed' payments can be verified."
        )

    payment.status = decision
    payment.verified_amount = verified_amount
    payment.verified_by = verified_by
    payment.verified_at = timezone.now()
    payment.remarks = remarks
    payment.save()

    if decision == Payment.STATUS_VERIFIED:
        assessment = payment.assessment
        assessment.is_locked = True
        assessment.locked_at = timezone.now()
        assessment.save()

    record_audit_event(
        verb=f"payment.{decision}",
        target_type="Payment",
        target_id=payment.pk,
        actor=verified_by,
        payload={"decision": decision, "verified_amount": str(verified_amount)},
    )
    return payment
