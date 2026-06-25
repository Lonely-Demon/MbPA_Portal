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
