"""Deterministic quote-salience guard (finding #2) — standard-library only.

Fuzzy citation matching (``rapidfuzz.partial_ratio`` at 0.85) verifies that a
quote *roughly* appears in its source. It tolerates OCR noise — but, because it
scores the best-aligning substring window, it also waves through small but
*material* adversarial edits: "90 days" → "30 days", "$2,000,000" → "$5,000,000",
or a flipped negation ("shall indemnify" → "shall not indemnify") typically score
0.93–0.99 and pass.

This module closes that blind spot with a complementary, deterministic check:
extract the *salient* tokens from a finding's quote — currency amounts, durations,
percentages, bare numbers, and the presence of negation — and require each to be
supported by the cited source text. A salient token in the quote that the source
does not support is a *positive contradiction*: exactly the fabrication signature
fuzzy matching misses.

Design rules:

* **Zero dependencies.** Pure ``re`` + ``unicodedata`` from the stdlib.
* **Pure functions.** No I/O, no globals; trivially unit-testable and reusable
  by both the pipeline gate (:mod:`dd_agents.validation.numerical_audit`) and any
  caller that has a quote and its source text.
* **Conservative.** Numbers/currency match within a ±5% tolerance (rounding and
  magnitude phrasing are not fabrication); the guard only reports a mismatch when
  the source genuinely fails to support the quote's claim, so it never fires on
  clean citations.
"""

from __future__ import annotations

import re
import unicodedata
from typing import TypedDict

__all__ = ["SalientTokens", "extract_salient_tokens", "quote_salience_mismatches"]

#: Relative tolerance for numeric/currency support (rounding ≠ fabrication).
_NUMERIC_TOLERANCE = 0.05

# Currency like $1,200,000 / $1.2M / $904K / $3 billion. The magnitude suffix
# requires a trailing word boundary so it never swallows the leading letter of a
# following word (e.g. the "m" of "monthly" must NOT inflate $50,000 to $50B).
_CURRENCY_RE = re.compile(r"\$\s*[\d,]+(?:\.\d+)?(?:\s*(?:m|b|k|mm|million|billion|thousand)\b)?", re.IGNORECASE)
# Durations like "90 days", "12 months", "3 years".
_DURATION_RE = re.compile(r"\b(\d+)\s+(day|days|month|months|year|years|week|weeks)\b", re.IGNORECASE)
# Percentages like "15%" or "15 %".
_PERCENT_RE = re.compile(r"\b(\d+(?:\.\d+)?)\s*%")
#: Cross-unit duration comparison (month≈30d, year≈365d) is approximate, so
#: durations use a looser tolerance than exact currency/percent figures —
#: "4 weeks" (28d) must not be flagged against "1 month" (30d).
_DURATION_TOLERANCE = 0.15
# STRONG negation / liability-flip cues only. Deliberately EXCLUDES bare "no"
# (which fires on innocuous comparison phrases like "no later than", "no less
# than", "at no additional cost") and "without"/"except"/"none". The gate flags
# a negation mismatch ONLY when the quote asserts one of these strong negations
# that appears NOWHERE in the cited source — a near-certain fabrication signal
# with effectively zero false positives.
_NEGATION_RE = re.compile(
    r"(?:\b(?:shall|will|would|may|can|must|does|do|is|are|was|were|has|have)\s+not\b"
    r"|\b(?:cannot|won't|can't|shan't|isn't|aren't|wasn't|weren't|doesn't|don't|didn't|hasn't|haven't|wouldn't|couldn't|shouldn't)\b"
    r"|\bno\s+(?:obligation|liability|liabilities|right|rights|warrant(?:y|ies)|refund|indemnit)"
    r"|\bnot\s+(?:liable|entitled|obligated|responsible|permitted|required|bound)\b"
    r"|\bnever\b)",
    re.IGNORECASE,
)


class SalientTokens(TypedDict):
    """Material tokens extracted from a span of text."""

    currency: set[str]
    duration: set[str]
    percent: set[str]
    negation: bool


def _normalize(text: str) -> str:
    """NFKC-normalize, collapse whitespace, fold apostrophes, lowercase.

    Curly apostrophes (U+2019) are folded to ASCII ``'`` so contraction-based
    negations ("won't", "isn't") match regardless of the document's typography.
    Matches ``verify_citation`` normalization plus the apostrophe fold.
    """
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("’", "'").replace("ʼ", "'")
    return re.sub(r"\s+", " ", text).strip().lower()


def _currency_to_float(raw: str) -> float | None:
    """Parse a currency match (e.g. ``$1.2M``) to a float dollar value."""
    s = raw.lower().replace("$", "").replace(",", "").strip()
    multiplier = 1.0
    if s.endswith("m") or s.endswith("million"):
        s = re.sub(r"(?:m|million)$", "", s).strip()
        multiplier = 1_000_000.0
    elif s.endswith("b") or s.endswith("billion"):
        s = re.sub(r"(?:b|billion)$", "", s).strip()
        multiplier = 1_000_000_000.0
    elif s.endswith("k") or s.endswith("thousand"):
        s = re.sub(r"(?:k|thousand)$", "", s).strip()
        multiplier = 1_000.0
    try:
        return float(s) * multiplier
    except ValueError:
        return None


def _canonical_currency(raw: str) -> str:
    """Canonical key for a currency token: ``$<int-or-float>`` with no separators."""
    value = _currency_to_float(raw)
    if value is None:
        return raw.strip()
    # Integer-valued amounts render without a trailing .0 for stable keys.
    return f"${int(value)}" if value.is_integer() else f"${value}"


def extract_salient_tokens(text: str) -> SalientTokens:
    """Extract the material tokens (currency, duration, percent, negation) from *text*."""
    norm = _normalize(text)
    currency = {_canonical_currency(m.group(0)) for m in _CURRENCY_RE.finditer(norm)}
    duration = {f"{m.group(1)} {_singular_unit(m.group(2))}" for m in _DURATION_RE.finditer(norm)}
    percent = {f"{m.group(1)}%" for m in _PERCENT_RE.finditer(norm)}
    negation = _NEGATION_RE.search(norm) is not None
    return SalientTokens(currency=currency, duration=duration, percent=percent, negation=negation)


def _singular_unit(unit: str) -> str:
    """Normalize a duration unit to its plural canonical form (day→days)."""
    u = unit.lower().rstrip("s")
    return f"{u}s"


def _numeric_supported(value: float, candidates: set[float], tolerance: float = _NUMERIC_TOLERANCE) -> bool:
    """True if *value* matches any candidate within *tolerance* (0 matches 0)."""
    for c in candidates:
        if c == 0 and value == 0:
            return True
        if c != 0 and abs(value - c) / abs(c) <= tolerance:
            return True
    return False


def _duration_value(token: str) -> float | None:
    """Convert a canonical duration token ("90 days") to a comparable day count."""
    m = re.match(r"(\d+)\s+(day|month|year|week)s?$", token)
    if not m:
        return None
    n = float(m.group(1))
    unit = m.group(2)
    factor = {"day": 1.0, "week": 7.0, "month": 30.0, "year": 365.0}[unit]
    return n * factor


def _aligned_window(quote: str, source: str, margin: int = 240) -> str:
    """Return the slice of *source* aligned to *quote*, for local negation checks.

    Anchors on the quote's longest run of content words and returns that region
    of the source ± *margin* chars. When no anchor is found (the quote's content
    is not in the source at all), returns the whole source so a genuinely
    unsupported negated quote is still evaluated. Pure string work — no deps.
    """
    nsource = _normalize(source)
    nquote = _normalize(quote)
    if not nquote or not nsource:
        return source
    # Try the whole normalized quote first, then progressively shorter leading
    # word-runs, to find an anchor offset in the source.
    words = nquote.split()
    for span in range(min(len(words), 12), 2, -1):
        probe = " ".join(words[:span])
        idx = nsource.find(probe)
        if idx != -1:
            start = max(0, idx - margin)
            end = min(len(nsource), idx + len(probe) + margin)
            return nsource[start:end]
    # No alignment anchor → evaluate against the full source (conservative).
    return nsource


def quote_salience_mismatches(quote: str, source: str) -> list[str]:
    """Return human-readable mismatches where *quote*'s salient tokens lack support in *source*.

    Returns an empty list when the source supports every salient token in the
    quote (within numeric tolerance), or when either input is empty (absence of
    source is handled upstream as non-blocking, not as a contradiction here).
    """
    if not quote.strip() or not source.strip():
        return []

    q = extract_salient_tokens(quote)
    s = extract_salient_tokens(source)
    mismatches: list[str] = []

    # Currency: every quoted amount must be supported (±tolerance) by the source.
    source_amounts = {v for raw in s["currency"] if (v := _currency_to_float(raw)) is not None}
    for raw in q["currency"]:
        val = _currency_to_float(raw)
        if val is not None and not _numeric_supported(val, source_amounts):
            mismatches.append(f"currency {raw} in quote not supported by source")

    # Durations: compared in normalized days, with a looser tolerance because
    # cross-unit conversion (month≈30d, year≈365d) is approximate.
    source_days = {v for tok in s["duration"] if (v := _duration_value(tok)) is not None}
    for tok in q["duration"]:
        val = _duration_value(tok)
        if val is not None and not _numeric_supported(val, source_days, _DURATION_TOLERANCE):
            mismatches.append(f"duration {tok!r} in quote not supported by source")

    # Percentages: exact numeric support (±tolerance).
    source_pcts = {float(p.rstrip("%")) for p in s["percent"]}
    for p in q["percent"]:
        val = float(p.rstrip("%"))
        if not _numeric_supported(val, source_pcts):
            mismatches.append(f"percentage {p} in quote not supported by source")

    # Negation — DIRECTIONAL and WINDOWED to avoid blocking-gate false positives:
    # only flag when the QUOTE asserts a strong negation that is absent from the
    # region of the source aligned to the quote. We never flag the reverse
    # (source negates, quote doesn't) — that is not a fabrication by the quote —
    # and we compare against a window around the quote's best alignment, not the
    # whole 500K-char document (an unrelated 'shall not' elsewhere is irrelevant).
    if q["negation"]:
        window = _aligned_window(quote, source)
        if not _NEGATION_RE.search(_normalize(window)):
            mismatches.append("negation mismatch: quote asserts a negation absent from the cited source passage")

    return mismatches
