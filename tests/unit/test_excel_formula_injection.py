"""Excel/CSV formula-injection sanitizer (audit MF6).

Document-derived strings (citation quotes, titles, descriptions) are
attacker-influenceable. A cell value beginning with ``= + - @`` would be
evaluated as a live formula by Excel/Sheets on open; the sanitizer defuses it.
"""

from __future__ import annotations

from dd_agents.reporting.excel import _sanitize_cell


def test_equals_prefixed_string_is_neutralized() -> None:
    assert _sanitize_cell("=1+1") == "'=1+1"
    assert _sanitize_cell('=HYPERLINK("http://evil")') == '\'=HYPERLINK("http://evil")'


def test_other_formula_triggers_are_neutralized() -> None:
    for trigger in ("+", "-", "@"):
        assert _sanitize_cell(f"{trigger}cmd").startswith("'" + trigger)


def test_leading_control_chars_then_formula_are_neutralized() -> None:
    # Leading tab/CR is a known bypass; strip it, then defuse the trigger.
    assert _sanitize_cell("\t=1+1") == "'=1+1"
    assert _sanitize_cell("\r\n@x") == "'@x"


def test_plain_text_is_unchanged() -> None:
    assert _sanitize_cell("Customer may terminate within 90 days.") == "Customer may terminate within 90 days."
    assert _sanitize_cell("") == ""


def test_non_string_values_pass_through_unchanged() -> None:
    # Numbers/None must stay their native type so numeric cells stay numeric.
    assert _sanitize_cell(42) == 42
    assert _sanitize_cell(3.14) == 3.14
    assert _sanitize_cell(None) is None


def test_idempotent() -> None:
    once = _sanitize_cell("=danger")
    assert _sanitize_cell(once) == once  # already prefixed with ' → unchanged
