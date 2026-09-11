"""
Mobile numbers: normalising, validating and masking.

Staff type a number the way they say it out loud — ``0300 123 4821``,
``+92-300-123-4821``, ``0092 300 1234821`` — and all three have to end up as
the one string an SMS gateway will accept and the database can hold a UNIQUE
index over. Everything is stored in E.164::

    +<country code><subscriber number>      e.g. +923001234821

with no spaces, dashes or brackets, so that two spellings of the same number
cannot register as two accounts — the UNIQUE index on the column is what
enforces that, and it can only compare exact strings.

A national number with no country code is assumed to belong to
``SMS_DEFAULT_COUNTRY_CODE`` (see ``.env``). That is the right guess for a shop
whose staff are all local, and anyone who is not can type the ``+`` themselves.

This is deliberately not a full libphonenumber: it does not know which prefixes
a given country has actually allocated. It checks shape and length, which is
enough to catch a typo at the keyboard. Nothing is ever sent to these numbers —
they are contact details for an approver to ring.
"""

from __future__ import annotations

import re

from app.core.exceptions import ValidationError

#: Characters people use as separators, all of which we simply drop.
_PUNCTUATION = re.compile(r"[\s\-().\u2013\u2014/]")

#: E.164 allows at most 15 digits including the country code, and the first
#: digit of a country code is never zero.
E164_PATTERN = re.compile(r"^\+[1-9]\d{7,14}$")

#: Shortest and longest total digit count we will accept.
MIN_DIGITS = 8
MAX_DIGITS = 15


def normalise_phone(value: str | None, *, default_country_code: str = "") -> str:
    """Return ``value`` in E.164, or ``""`` when there is nothing to work with.

    Accepts ``+`` and ``00`` international prefixes, and a national number with
    a single leading ``0`` (the trunk prefix), which is replaced by
    ``default_country_code``. Never raises — use :func:`is_phone` or
    :func:`require_phone` to judge the result.
    """
    if not value:
        return ""

    cleaned = _PUNCTUATION.sub("", str(value).strip())
    if not cleaned:
        return ""

    # "00" is the international access code in most of the world; "011" in
    # North America is left alone, as those callers type "+1" anyway.
    if cleaned.startswith("00"):
        cleaned = "+" + cleaned[2:]

    if cleaned.startswith("+"):
        digits = cleaned[1:]
        return f"+{digits}" if digits.isdigit() else ""

    if not cleaned.isdigit():
        return ""

    country = _clean_country_code(default_country_code)
    if not country:
        # Nothing to prepend, so the number can only be taken at face value.
        return f"+{cleaned}"

    # A single leading zero is a trunk prefix, dropped when the country code
    # goes on: 0300 1234821 -> +92 300 1234821.
    national = cleaned.lstrip("0") if cleaned.startswith("0") else cleaned

    return f"+{country}{national}"


def is_phone(value: str | None) -> bool:
    """True when ``value`` is already a well-formed E.164 number."""
    if not value:
        return False

    candidate = str(value).strip()
    if not E164_PATTERN.match(candidate):
        return False

    return MIN_DIGITS <= len(candidate) - 1 <= MAX_DIGITS


def require_phone(value: str | None, *, default_country_code: str = "") -> str:
    """Normalise ``value`` or raise a :class:`ValidationError` a person can act on."""
    raw = (value or "").strip()

    if not raw:
        raise ValidationError("Please enter a mobile number.")

    normalised = normalise_phone(raw, default_country_code=default_country_code)

    if not normalised:
        raise ValidationError(
            "That does not look like a mobile number. Use digits only, "
            "for example 0300 1234821 or +92 300 1234821."
        )

    digits = len(normalised) - 1

    if digits < MIN_DIGITS:
        raise ValidationError("That mobile number is too short. Check the digits and try again.")

    if digits > MAX_DIGITS:
        raise ValidationError("That mobile number is too long. Check the digits and try again.")

    if not is_phone(normalised):
        raise ValidationError("That does not look like a mobile number. Check it and try again.")

    return normalised


def mask_phone(value: str | None) -> str:
    """``+923001234821`` -> ``+92 ••• ••• 4821``.

    Shown while a passcode is in flight so the person can confirm it went to a
    handset they are holding, without printing a full number on a shop-floor
    screen where anyone can read it.
    """
    if not value:
        return "your mobile number"

    candidate = str(value).strip()

    if not candidate.startswith("+"):
        candidate = normalise_phone(candidate)

    digits = candidate.lstrip("+")

    if len(digits) < 6:
        return "your mobile number"

    # Two digits of country code is right for most of the world and wrong
    # harmlessly for the rest — it only ever reveals less than it should.
    country, last = digits[:2], digits[-4:]

    return f"+{country} ••• ••• {last}"


def _clean_country_code(value: str | None) -> str:
    """``"+92"``, ``"92"`` and ``" 0092 "`` all become ``"92"``."""
    if not value:
        return ""

    digits = _PUNCTUATION.sub("", str(value).strip()).lstrip("+")

    if digits.startswith("00"):
        digits = digits[2:]

    return digits if digits.isdigit() else ""
