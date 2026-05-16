"""search_in_file MCP tool.

Searches within extracted text for a given query, returning matches with
page numbers, character offsets, and surrounding context.  Enables agents
to locate specific clauses without reading entire documents.
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import Any

from dd_agents.search.chunker import PAGE_MARKER_RE

# Maximum matches to return per call (prevents context flooding).
_MAX_RESULTS = 20

# Characters of surrounding context per match.
_CONTEXT_CHARS = 120


def _normalize(text: str) -> str:
    """Normalize whitespace and Unicode for comparison."""
    text = unicodedata.normalize("NFKC", text)
    return re.sub(r"\s+", " ", text).strip()


def _find_page_number(text: str, char_offset: int) -> int | None:
    """Determine page number for *char_offset* using ``--- Page N ---`` markers."""
    page_num: int | None = None
    for m in PAGE_MARKER_RE.finditer(text):
        if m.start() > char_offset:
            break
        page_num = int(m.group(1))
    return page_num


def search_in_file(
    source_path: str,
    query: str,
    text_dir: str | Path,
    *,
    case_sensitive: bool = False,
    max_results: int = _MAX_RESULTS,
    allowed_dir: str | Path | None = None,
    data_room_path: str | Path | None = None,
) -> dict[str, Any]:
    """Search within extracted text of *source_path* for *query*.

    Args:
        source_path: Original file path from inventory.
        query: Search string (plain text or regex pattern).
        text_dir: Path to directory containing extracted text files.
        case_sensitive: Whether to match case-sensitively.
        max_results: Maximum number of matches to return.
        allowed_dir: If set, restrict reads to this directory tree.

    Returns:
        ``{"matches": [...], "total_matches": int, "truncated": bool}`` or
        ``{"error": str, "reason": str}``.
    """
    if not source_path:
        return {"error": "invalid_input", "reason": "Empty source_path"}
    if not query:
        return {"error": "invalid_input", "reason": "Empty query"}

    # Path containment pre-check — block traversal attempts before lookup.
    if allowed_dir and ".." in source_path:
        try:
            from dd_agents.extraction.pipeline import ExtractionPipeline

            naive = (Path(text_dir) / ExtractionPipeline._safe_text_name(source_path)).resolve()
            if not naive.is_relative_to(Path(allowed_dir).resolve()):
                return {"error": "blocked", "reason": "Path traversal blocked"}
        except (OSError, ValueError):
            return {"error": "blocked", "reason": "Invalid text path"}

    from dd_agents.tools._text_lookup import resolve_text_path

    text_path = resolve_text_path(source_path, text_dir, data_room_path=data_room_path)

    if text_path is None:
        return {
            "error": "not_found",
            "reason": f"No extracted text for '{source_path}'",
        }

    # Path containment check on resolved file.
    if allowed_dir:
        try:
            resolved = text_path.resolve()
            allowed_resolved = Path(allowed_dir).resolve()
            if not resolved.is_relative_to(allowed_resolved):
                return {"error": "blocked", "reason": "Path traversal blocked"}
        except (OSError, ValueError):
            return {"error": "blocked", "reason": "Invalid text path"}

    text = text_path.read_text(encoding="utf-8")

    # Build regex pattern from the query.
    flags = 0 if case_sensitive else re.IGNORECASE
    try:
        pattern = re.compile(re.escape(query), flags)
    except re.error:
        return {"error": "invalid_input", "reason": f"Invalid query pattern: {query}"}

    matches: list[dict[str, Any]] = []
    total = 0

    for m in pattern.finditer(text):
        total += 1
        if len(matches) >= max_results:
            continue  # Keep counting but stop collecting.

        start = m.start()
        length = m.end() - m.start()
        page = _find_page_number(text, start)

        ctx_before_start = max(0, start - _CONTEXT_CHARS)
        ctx_after_end = min(len(text), start + length + _CONTEXT_CHARS)

        matches.append(
            {
                "page_number": page,
                "char_offset": start,
                "matched_text": text[start : start + length],
                "context_before": text[ctx_before_start:start].strip(),
                "context_after": text[start + length : ctx_after_end].strip(),
            }
        )

    return {
        "source_path": source_path,
        "query": query,
        "matches": matches,
        "total_matches": total,
        "truncated": total > max_results,
    }
