from __future__ import annotations

from decimal import Decimal, InvalidOperation

from django.utils import timezone

from apps.fees.models import ConfigParameter


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
