"""Unit tests for the built-in prompt Markdown loader."""

from __future__ import annotations

import pytest

from dd_agents.agents import severity_thresholds as thr
from dd_agents.agents.prompts import loader


def test_resolve_thresholds_substitutes_known_placeholders() -> None:
    out = loader.resolve_thresholds("TfC over {TFC_REVENUE_PCT}% with {TFC_NOTICE_DAYS}d notice")
    assert out == f"TfC over {thr.TFC_REVENUE_PCT}% with {thr.TFC_NOTICE_DAYS}d notice"


def test_resolve_thresholds_leaves_json_braces_untouched() -> None:
    # The prompts are full of literal JSON braces — these must survive verbatim.
    text = 'Return {"severity": "P1", "nested": {"a": 1}} as JSON'
    assert loader.resolve_thresholds(text) == text


def test_resolve_thresholds_fails_closed_on_typo_placeholder() -> None:
    with pytest.raises(loader.PromptLoadError, match="unresolved severity-threshold placeholder"):
        loader.resolve_thresholds("bad {TFC_REVENU_PCT} typo")


def test_split_sections_parses_headings() -> None:
    body = "## Role\nrole text\n\n## Specialist Focus\nfocus text\n## Domain Guidance\nguide"
    sections = loader._split_sections(body)
    assert sections["Role"] == "role text"
    assert sections["Specialist Focus"] == "focus text"
    assert sections["Domain Guidance"] == "guide"


def test_split_front_matter_optional() -> None:
    meta, body = loader._split_front_matter("## Role\nhi")
    assert meta == {}
    assert "## Role" in body
    meta2, body2 = loader._split_front_matter("---\nid: x\n---\n## Role\nhi")
    assert meta2 == {"id": "x"}
    assert body2.strip().startswith("## Role")


def test_load_missing_specialist_fails_closed() -> None:
    loader.load_builtin_specialist.cache_clear()
    with pytest.raises(loader.PromptLoadError, match="not found"):
        loader.load_builtin_specialist("__no_such_agent__")
