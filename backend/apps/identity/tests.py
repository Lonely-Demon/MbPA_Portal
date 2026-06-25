import pytest
from django.test import override_settings

from apps.identity.services import _normalize_aadhaar, aadhaar_matches, hash_aadhaar

VALID_AADHAAR = "123456789012"
VALID_AADHAAR_SPACED = "1234 5678 9012"
VALID_AADHAAR_HYPHEN = "1234-5678-9012"
PEPPER_A = "pepper-aaaa-test-value-64-chars-long-placeholder-xxxxxxxxxxxxxxxxx"
PEPPER_B = "pepper-bbbb-test-value-64-chars-long-placeholder-xxxxxxxxxxxxxxxxx"


# ── _normalize_aadhaar ────────────────────────────────────────────────────────

def test_normalize_strips_spaces():
    assert _normalize_aadhaar(VALID_AADHAAR_SPACED) == VALID_AADHAAR


def test_normalize_strips_hyphens():
    assert _normalize_aadhaar(VALID_AADHAAR_HYPHEN) == VALID_AADHAAR


def test_normalize_accepts_plain_digits():
    assert _normalize_aadhaar(VALID_AADHAAR) == VALID_AADHAAR


def test_normalize_rejects_too_short():
    with pytest.raises(ValueError, match="12 digits"):
        _normalize_aadhaar("12345")


def test_normalize_rejects_too_long():
    with pytest.raises(ValueError, match="12 digits"):
        _normalize_aadhaar("1234567890123")  # 13 digits


def test_normalize_rejects_letters():
    with pytest.raises(ValueError, match="12 digits"):
        _normalize_aadhaar("ABCDEFGHIJKL")


def test_normalize_rejects_empty():
    with pytest.raises(ValueError, match="12 digits"):
        _normalize_aadhaar("")


# ── hash_aadhaar ──────────────────────────────────────────────────────────────

@override_settings(AADHAAR_PEPPER=PEPPER_A)
def test_hash_aadhaar_returns_64_char_hex():
    result = hash_aadhaar(VALID_AADHAAR)
    assert len(result) == 64
    assert all(c in "0123456789abcdef" for c in result)


@override_settings(AADHAAR_PEPPER=PEPPER_A)
def test_hash_aadhaar_is_deterministic():
    """Same input + same pepper must always produce the same hash."""
    assert hash_aadhaar(VALID_AADHAAR) == hash_aadhaar(VALID_AADHAAR)


@override_settings(AADHAAR_PEPPER=PEPPER_A)
def test_hash_aadhaar_normalises_spacing():
    """Spaced and unspaced forms of the same number must produce identical hashes."""
    assert hash_aadhaar(VALID_AADHAAR_SPACED) == hash_aadhaar(VALID_AADHAAR)
    assert hash_aadhaar(VALID_AADHAAR_HYPHEN) == hash_aadhaar(VALID_AADHAAR)


@override_settings(AADHAAR_PEPPER=PEPPER_A)
def test_hash_aadhaar_different_number_gives_different_hash():
    other = "999999999999"
    assert hash_aadhaar(VALID_AADHAAR) != hash_aadhaar(other)


def test_hash_aadhaar_pepper_changes_output():
    """Different peppers must produce different hashes — pepper is not ignored."""
    with override_settings(AADHAAR_PEPPER=PEPPER_A):
        hash_a = hash_aadhaar(VALID_AADHAAR)
    with override_settings(AADHAAR_PEPPER=PEPPER_B):
        hash_b = hash_aadhaar(VALID_AADHAAR)
    assert hash_a != hash_b


@override_settings(AADHAAR_PEPPER="")
def test_hash_aadhaar_raises_without_pepper():
    """Hashing without a pepper must raise ValueError loudly."""
    with pytest.raises(ValueError, match="AADHAAR_PEPPER"):
        hash_aadhaar(VALID_AADHAAR)


@override_settings(AADHAAR_PEPPER=None)
def test_hash_aadhaar_raises_when_pepper_is_none():
    with pytest.raises(ValueError, match="AADHAAR_PEPPER"):
        hash_aadhaar(VALID_AADHAAR)


# ── aadhaar_matches ───────────────────────────────────────────────────────────

@override_settings(AADHAAR_PEPPER=PEPPER_A)
def test_aadhaar_matches_true_for_same_input():
    stored = hash_aadhaar(VALID_AADHAAR)
    assert aadhaar_matches(VALID_AADHAAR, stored) is True


@override_settings(AADHAAR_PEPPER=PEPPER_A)
def test_aadhaar_matches_true_normalised_vs_plain():
    """Verifying a spaced entry against a hash of the plain digits must succeed."""
    stored = hash_aadhaar(VALID_AADHAAR)
    assert aadhaar_matches(VALID_AADHAAR_SPACED, stored) is True


@override_settings(AADHAAR_PEPPER=PEPPER_A)
def test_aadhaar_matches_false_for_different_number():
    stored = hash_aadhaar(VALID_AADHAAR)
    assert aadhaar_matches("999999999999", stored) is False


@override_settings(AADHAAR_PEPPER=PEPPER_A)
def test_aadhaar_matches_false_for_tampered_hash():
    stored = hash_aadhaar(VALID_AADHAAR)
    tampered = stored[:-1] + ("0" if stored[-1] != "0" else "1")
    assert aadhaar_matches(VALID_AADHAAR, tampered) is False
