"""Canonicalization helpers for Forward identity strings.

Forward location keys arrive as raw concatenated strings such as
``8ng5+500 W 30TH ST+NEW YORK+NY+10001``. The same physical site shows up under
formatting variants (``ST`` vs ``STREET``, mixed case, doubled spaces), and the
device rows reference those same raw keys. Left untouched, every variant becomes
a distinct Nautobot Location and devices scatter across the duplicates.

``normalize_location_key`` produces a conservative canonical form used only as a
dedup/lookup key — the original first-seen name is still what gets written. It
case-folds, collapses whitespace, and standardizes common US street-suffix
abbreviations so true formatting variants collapse, while genuinely different
addresses (e.g. ``30TH`` vs ``33rd``) stay distinct.
"""

from __future__ import annotations

import re

# Common USPS street-suffix abbreviations -> a single canonical token. Both the
# abbreviation and the full word map to the same value so either spelling
# collapses to one key. Deliberately small and well-known to avoid merging
# distinct sites by accident.
_STREET_SUFFIXES: dict[str, str] = {
    "st": "street",
    "street": "street",
    "ave": "avenue",
    "av": "avenue",
    "avenue": "avenue",
    "rd": "road",
    "road": "road",
    "blvd": "boulevard",
    "boulevard": "boulevard",
    "dr": "drive",
    "drive": "drive",
    "ln": "lane",
    "lane": "lane",
    "ct": "court",
    "court": "court",
    "pkwy": "parkway",
    "parkway": "parkway",
    "hwy": "highway",
    "highway": "highway",
    "sq": "square",
    "square": "square",
    "pl": "place",
    "place": "place",
    "ter": "terrace",
    "terrace": "terrace",
    "cir": "circle",
    "circle": "circle",
    "ste": "suite",
    "suite": "suite",
}

_WORD_RE = re.compile(r"[a-z0-9]+")


def normalize_location_key(value: str) -> str:
    """Return a conservative canonical key for a location string.

    Case-folds, collapses runs of non-alphanumeric characters to single spaces,
    and expands known street-suffix abbreviations. Returns "" for blank input.
    """
    text = str(value or "").strip().lower()
    if not text:
        return ""
    tokens = _WORD_RE.findall(text)
    canonical = [_STREET_SUFFIXES.get(tok, tok) for tok in tokens]
    return " ".join(canonical)
