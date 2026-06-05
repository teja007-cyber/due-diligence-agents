"""Deterministic quote-salience guard (finding #2).

The guard answers a narrower, higher-integrity question than fuzzy citation
matching: *does the quote's material content — numbers, dates, durations,
currency, and negations — actually appear in the cited source?* A high
``partial_ratio`` can mask a flipped negation or a swapped figure ("90 days" →
"30 days" scores ~0.95); this guard catches exactly those adversarial edits,
using only the standard library (no new dependencies).
"""

from __future__ import annotations

from dd_agents.validation.quote_guard import (
    extract_salient_tokens,
    quote_salience_mismatches,
)

# ---------------------------------------------------------------------------
# extract_salient_tokens — what counts as "material"
# ---------------------------------------------------------------------------


def test_extracts_currency_durations_percentages_negations() -> None:
    tokens = extract_salient_tokens("Vendor shall not pay $1,200,000 within 90 days; the cap is 15% of fees.")
    assert "$1200000" in tokens["currency"]
    assert "90 days" in tokens["duration"]
    assert "15%" in tokens["percent"]
    assert tokens["negation"] is True


def test_currency_normalizes_magnitude_suffix() -> None:
    tokens = extract_salient_tokens("ARR of $1.2M and a $904K floor")
    assert "$1200000" in tokens["currency"]
    assert "$904000" in tokens["currency"]


def test_clean_text_has_no_negation() -> None:
    tokens = extract_salient_tokens("The Agreement renews for 12 months at $50,000.")
    assert tokens["negation"] is False


# ---------------------------------------------------------------------------
# quote_salience_mismatches — quote tokens must be supported by source
# ---------------------------------------------------------------------------


def test_exact_support_no_mismatch() -> None:
    quote = "Customer may terminate within 90 days for a fee of $50,000."
    source = "Section 7. Customer may terminate within 90 days for a fee of $50,000 upon notice."
    assert quote_salience_mismatches(quote, source) == []


def test_swapped_number_is_caught() -> None:
    # The classic partial_ratio blind spot: 90 -> 30 days.
    quote = "Customer may terminate within 30 days."
    source = "Customer may terminate within 90 days."
    mismatches = quote_salience_mismatches(quote, source)
    assert any("30 days" in m for m in mismatches)


def test_swapped_dollar_amount_is_caught() -> None:
    quote = "The liability cap is $5,000,000."
    source = "The liability cap is $2,000,000."
    mismatches = quote_salience_mismatches(quote, source)
    assert any("5000000" in m.replace(",", "") for m in mismatches)


def test_negation_flip_is_caught() -> None:
    quote = "The Provider shall not indemnify the Customer."
    source = "The Provider shall indemnify the Customer."
    mismatches = quote_salience_mismatches(quote, source)
    assert any("negation" in m.lower() for m in mismatches)


def test_added_negation_when_source_has_none() -> None:
    quote = "Customer is never entitled to a refund."
    source = "Customer is entitled to a refund within 30 days."
    mismatches = quote_salience_mismatches(quote, source)
    assert any("negation" in m.lower() for m in mismatches)


def test_currency_within_tolerance_not_flagged() -> None:
    # Rounding ($1.2M vs $1,200,500) is within 5% — not a fabrication.
    quote = "ARR is $1.2M."
    source = "Total ARR is $1,200,500 for the period."
    assert quote_salience_mismatches(quote, source) == []


def test_percentage_swap_is_caught() -> None:
    quote = "A discount of 50% applies."
    source = "A discount of 15% applies."
    mismatches = quote_salience_mismatches(quote, source)
    assert any("50%" in m for m in mismatches)


def test_empty_quote_or_source_is_no_mismatch() -> None:
    # The guard only flags positive contradictions; absence of source text is
    # handled upstream (non-blocking), not here.
    assert quote_salience_mismatches("", "anything") == []
    assert quote_salience_mismatches("$5,000,000", "") == []


def test_negation_elsewhere_in_long_source_is_not_a_false_positive() -> None:
    """A faithful quote must NOT fail just because the long source document has a
    negation in an UNRELATED passage (the blocking-gate false positive)."""
    source = (
        "Section 1. The Agreement renews annually. " * 20
        + "Section 9. The Provider shall not be liable for indirect damages. "
        + "Section 12. No refunds except as required by law. " * 10
    )
    assert quote_salience_mismatches("The Agreement renews annually.", source) == []


def test_currency_suffix_does_not_swallow_following_word() -> None:
    """'$50,000 monthly' must not parse the 'm' of 'monthly' as a $-million suffix."""
    assert quote_salience_mismatches("a fee of $50,000 monthly", "the fee of $50,000 every month") == []


def test_duration_cross_unit_within_tolerance() -> None:
    """4 weeks (28d) vs 1 month (~30d) is approximate-equal, not a fabrication."""
    assert quote_salience_mismatches("terminate within 4 weeks", "terminate within 1 month") == []


def test_comparison_phrases_with_no_are_not_negations() -> None:
    """'no later than' must NOT trip the negation guard."""
    assert quote_salience_mismatches("payment is due no later than 30 days", "payment is due within 30 days") == []


def test_contraction_negation_flip_is_caught() -> None:
    mismatches = quote_salience_mismatches("the vendor won't be liable", "the vendor will be liable for all losses")
    assert any("negation" in m.lower() for m in mismatches)


def test_curly_apostrophe_contraction_is_caught() -> None:
    # U+2019 curly apostrophe must fold to ASCII so "won't" still matches.
    mismatches = quote_salience_mismatches("the vendor won’t be liable", "the vendor will be liable")
    assert any("negation" in m.lower() for m in mismatches)


def test_negation_directional_source_negates_quote_does_not() -> None:
    """Directional: source negating while the quote does not is NOT flagged."""
    assert quote_salience_mismatches("the vendor is liable", "the vendor is not liable") == []


def test_unicode_and_whitespace_normalization() -> None:
    # Smart quotes / non-breaking spaces / newlines must not cause false mismatch.
    quote = "fee of $50,000 within 90\ndays"
    source = "the fee of $50,000 within 90 days"
    assert quote_salience_mismatches(quote, source) == []
