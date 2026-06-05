"""Shared finding predicates for the validation gates (single source of truth).

Keeping these here avoids drift between the numerical-audit and qa-audit gates,
which must agree on what to exclude (e.g. deterministic tamper findings).
"""

from __future__ import annotations

from typing import Any

__all__ = ["is_tamper_finding"]


def is_tamper_finding(finding: dict[str, Any]) -> bool:
    """True for deterministic tamper / ``document_integrity`` findings.

    These are injected by :meth:`dd_agents.reporting.merge.FindingMerger.inject_tamper_findings`
    and carry attacker-controlled injection prose as their ``exact_quote`` (by
    design — the injection is the evidence), optionally with a synthetic source
    path. The source-citation validation layers (Layer 6 financial citation,
    Layer 7 quote fidelity) and the qa-audit citation gates must exclude them
    rather than self-fail on them.
    """
    if finding.get("category") == "document_integrity":
        return True
    meta = finding.get("metadata")
    return bool(isinstance(meta, dict) and meta.get("tamper"))
