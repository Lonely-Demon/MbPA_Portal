from datetime import timedelta
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.fees.models import ConfigParameter
from apps.fees.services import get_active_config, get_decimal_config

User = get_user_model()


def _make_superuser(username="admin_fee"):
    return User.objects.create_superuser(
        username=username, password="pass", email="admin@example.com"
    )


def _make_config(key, value, days_offset=0, superuser=None):
    if superuser is None:
        superuser = _make_superuser()
    date = timezone.now().date() - timedelta(days=days_offset)
    return ConfigParameter.objects.create(
        key=key,
        value=value,
        effective_from=date,
        created_by=superuser,
    )


# ── get_active_config ─────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_get_active_config_returns_latest_effective():
    su = _make_superuser()
    _make_config("fee_rate", "40.00", days_offset=10, superuser=su)
    _make_config("fee_rate", "50.00", days_offset=2, superuser=su)  # newer
    param = get_active_config("fee_rate")
    assert param.value == "50.00"


@pytest.mark.django_db
def test_get_active_config_ignores_future_rows():
    su = _make_superuser()
    # effective_from in the future should be ignored
    ConfigParameter.objects.create(
        key="future_key",
        value="999.00",
        effective_from=timezone.now().date() + timedelta(days=30),
        created_by=su,
    )
    _make_config("future_key", "10.00", days_offset=1, superuser=su)
    param = get_active_config("future_key")
    assert param.value == "10.00"


@pytest.mark.django_db
def test_get_active_config_raises_key_error_when_missing():
    with pytest.raises(KeyError, match="nonexistent_key"):
        get_active_config("nonexistent_key")


# ── get_decimal_config ────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_get_decimal_config_returns_decimal():
    _make_config("scrutiny_fee_per_sqm", "50.00")
    result = get_decimal_config("scrutiny_fee_per_sqm")
    assert isinstance(result, Decimal)
    assert result == Decimal("50.00")


@pytest.mark.django_db
def test_get_decimal_config_raises_value_error_on_non_numeric():
    _make_config("bad_val", "not_a_number")
    with pytest.raises(ValueError, match="bad_val"):
        get_decimal_config("bad_val")


@pytest.mark.django_db
def test_get_decimal_config_raises_key_error_when_missing():
    with pytest.raises(KeyError):
        get_decimal_config("missing_key")


# ── Fixtures for fee-engine tests ─────────────────────────────────────────────


def _seed_config(su):
    """Seed the seven config keys required by assess_fee()."""
    rows = {
        "scrutiny_fee_per_sqm": "50.00",
        "security_deposit_per_sqm": "10.00",
        "debris_deposit_per_sqm": "20.00",
        "premium_coefficient.additional_fsi": "1.10",
        "premium_coefficient.open_space_shortfall": "0.25",
        "premium_coefficient.parking_waiver": "0.40",
        "benchmark.additional_fsi": "1.50",
    }
    date = timezone.now().date() - timedelta(days=1)
    for key, value in rows.items():
        ConfigParameter.objects.create(key=key, value=value, effective_from=date, created_by=su)


def _make_application(su=None, bua="200.00", rrr="5000.00", plot_area=None):
    from apps.applications.models import Application, Stream
    from apps.applications.services import generate_application_number

    if su is None:
        su = User.objects.create_user(username="app_owner", password="pw")
    stream, _ = Stream.objects.get_or_create(code="NC", defaults={"name": "New Construction"})
    app = Application.objects.create(
        stream=stream,
        submitted_by=su,
        application_number=generate_application_number(),
        status=Application.STATUS_SUBMITTED,
        proposed_bua_sqm=Decimal(bua),
        zonal_rrr=Decimal(rrr),
        plot_area_sqm=Decimal(plot_area) if plot_area else None,
    )
    return app


# ── assess_fee ────────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_assess_fee_base_fee_from_bua():
    from apps.fees.services import assess_fee

    su = _make_superuser("af1")
    _seed_config(su)
    app = _make_application(su)

    assessment = assess_fee(application=app, assessed_by=su)

    bua = Decimal("200.00")
    assert assessment.scrutiny_fee == (Decimal("50.00") * bua).quantize(Decimal("0.01"))
    assert assessment.security_deposit == (Decimal("10.00") * bua).quantize(Decimal("0.01"))
    assert assessment.debris_deposit == (Decimal("20.00") * bua).quantize(Decimal("0.01"))


@pytest.mark.django_db
def test_assess_fee_uses_configured_rate_not_hardcoded():
    from apps.fees.services import assess_fee

    su = _make_superuser("af2")
    _seed_config(su)
    # Override scrutiny with a newer, higher rate effective today
    ConfigParameter.objects.create(
        key="scrutiny_fee_per_sqm",
        value="75.00",
        effective_from=timezone.now().date(),
        created_by=su,
    )
    app = _make_application(su)

    assessment = assess_fee(application=app, assessed_by=su)

    bua = Decimal("200.00")
    assert assessment.scrutiny_fee == (Decimal("75.00") * bua).quantize(Decimal("0.01"))


@pytest.mark.django_db
def test_assess_fee_amounts_are_decimal_not_float():
    from apps.fees.services import assess_fee

    su = _make_superuser("af3")
    _seed_config(su)
    app = _make_application(su)

    assessment = assess_fee(application=app, assessed_by=su)

    assert isinstance(assessment.total_amount, Decimal)
    assert isinstance(assessment.scrutiny_fee, Decimal)


@pytest.mark.django_db
def test_assess_fee_snapshots_config_version():
    from apps.fees.services import assess_fee

    su = _make_superuser("af4")
    _seed_config(su)
    app = _make_application(su)

    assessment = assess_fee(application=app, assessed_by=su)

    assert assessment.config_version is not None
    assert assessment.config_version.key == "scrutiny_fee_per_sqm"


# ── AC-16: immutability after rate change ─────────────────────────────────────


@pytest.mark.django_db
def test_rate_change_does_not_alter_existing_assessment():
    from apps.fees.services import assess_fee

    su = _make_superuser("ac16_1")
    _seed_config(su)
    app = _make_application(su)

    assessment = assess_fee(application=app, assessed_by=su)
    original_scrutiny = assessment.scrutiny_fee

    # New config row with a higher rate takes effect today
    ConfigParameter.objects.create(
        key="scrutiny_fee_per_sqm",
        value="999.00",
        effective_from=timezone.now().date(),
        created_by=su,
    )

    assessment.refresh_from_db()
    assert assessment.scrutiny_fee == original_scrutiny


# ── AC-16: lock guard ─────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_locked_assessment_rejects_mutation():
    from apps.common.exceptions import FeeAssessmentLockedError
    from apps.fees.models import FeeAssessment
    from apps.fees.services import assess_fee

    su = _make_superuser("ac16_2")
    _seed_config(su)
    app = _make_application(su)

    assessment = assess_fee(application=app, assessed_by=su)

    # Lock directly via ORM update to bypass save() guard (simulates verify_payment)
    FeeAssessment.objects.filter(pk=assessment.pk).update(is_locked=True, locked_at=timezone.now())

    assessment.refresh_from_db()
    assessment.scrutiny_fee = Decimal("1.00")
    with pytest.raises(FeeAssessmentLockedError):
        assessment.save()


# ── reassess_fee ──────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_reassess_fee_marks_old_is_current_false():
    from apps.fees.models import FeeAssessment
    from apps.fees.services import assess_fee, reassess_fee

    su = _make_superuser("reasf1")
    _seed_config(su)
    app = _make_application(su)

    old = assess_fee(application=app, assessed_by=su)
    old_pk = old.pk

    app.proposed_bua_sqm = Decimal("300.00")
    app.save()

    new = reassess_fee(application=app, assessed_by=su)

    old_refreshed = FeeAssessment.objects.get(pk=old_pk)
    assert old_refreshed.is_current is False
    assert new.is_current is True
    assert new.pk != old_pk
    assert new.scrutiny_fee != old_refreshed.scrutiny_fee


# ── record_payment ────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_record_payment_rejects_duplicate_active_claim():
    from apps.common.exceptions import DomainError
    from apps.fees.services import assess_fee, record_payment

    su = _make_superuser("rp1")
    _seed_config(su)
    app = _make_application(su)
    assess_fee(application=app, assessed_by=su)

    record_payment(
        application=app,
        challan_reference="CHALLAN-001",
        claimed_amount=Decimal("16000.00"),
        payment_date=timezone.now().date(),
        recorded_by=su,
    )
    with pytest.raises(DomainError):
        record_payment(
            application=app,
            challan_reference="CHALLAN-001",
            claimed_amount=Decimal("16000.00"),
            payment_date=timezone.now().date(),
            recorded_by=su,
        )


@pytest.mark.django_db
def test_record_payment_blocks_resubmission_after_mismatch():
    """STATUS_MISMATCH blocks resubmission — officer must resolve; new challan required."""
    from apps.common.exceptions import DomainError
    from apps.fees.models import Payment
    from apps.fees.services import assess_fee, record_payment, verify_payment

    su = _make_superuser("rp_mismatch")
    _seed_config(su)
    app = _make_application(su)
    assess_fee(application=app, assessed_by=su)

    payment = record_payment(
        application=app,
        challan_reference="CHALLAN-MM",
        claimed_amount=Decimal("16000.00"),
        payment_date=timezone.now().date(),
        recorded_by=su,
    )
    verify_payment(
        payment=payment,
        decision=Payment.STATUS_MISMATCH,
        verified_amount=Decimal("15000.00"),
        verified_by=su,
    )

    with pytest.raises(DomainError):
        record_payment(
            application=app,
            challan_reference="CHALLAN-MM",
            claimed_amount=Decimal("16000.00"),
            payment_date=timezone.now().date(),
            recorded_by=su,
        )


@pytest.mark.django_db
def test_record_payment_allows_resubmission_after_rejection():
    from apps.fees.models import Payment
    from apps.fees.services import assess_fee, record_payment, verify_payment

    su = _make_superuser("rp2")
    _seed_config(su)
    app = _make_application(su)
    assess_fee(application=app, assessed_by=su)

    payment = record_payment(
        application=app,
        challan_reference="CHALLAN-002",
        claimed_amount=Decimal("16000.00"),
        payment_date=timezone.now().date(),
        recorded_by=su,
    )
    verify_payment(
        payment=payment,
        decision=Payment.STATUS_REJECTED,
        verified_amount=Decimal("0.00"),
        verified_by=su,
        remarks="Fraudulent challan",
    )

    payment2 = record_payment(
        application=app,
        challan_reference="CHALLAN-002",
        claimed_amount=Decimal("16000.00"),
        payment_date=timezone.now().date(),
        recorded_by=su,
    )
    assert payment2.pk != payment.pk
    assert payment2.status == Payment.STATUS_CLAIMED


# ── verify_payment ────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_verify_payment_locks_assessment():
    from apps.fees.models import Payment
    from apps.fees.services import assess_fee, record_payment, verify_payment

    su = _make_superuser("vp1")
    _seed_config(su)
    app = _make_application(su)
    assess_fee(application=app, assessed_by=su)

    payment = record_payment(
        application=app,
        challan_reference="CHALLAN-VFY",
        claimed_amount=Decimal("16000.00"),
        payment_date=timezone.now().date(),
        recorded_by=su,
    )
    verify_payment(
        payment=payment,
        decision=Payment.STATUS_VERIFIED,
        verified_amount=Decimal("16000.00"),
        verified_by=su,
    )

    payment.assessment.refresh_from_db()
    assert payment.assessment.is_locked is True
    assert payment.assessment.locked_at is not None
