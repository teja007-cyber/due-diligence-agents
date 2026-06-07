"""Structural guards for the golden Project Atlas example.

Project Atlas (``examples/project-atlas/``) is the single canonical synthetic deal used
across marketing, docs, the public sample report, and the quickstart. These tests are
cheap (no API key, no pipeline run) and exist to stop accidental breakage of the golden
sample: the config must validate, the data room must be complete, and the *hero*
cross-domain mechanic (a change-of-control clause on a material-revenue customer) must
remain present in the source documents so a real run still surfaces it.

They do NOT re-run the pipeline — see ``tests/e2e`` for live runs.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dd_agents.config import load_deal_config

REPO_ROOT = Path(__file__).resolve().parents[2]
ATLAS = REPO_ROOT / "examples" / "project-atlas"
DATA_ROOM = ATLAS / "sample_data_room"
SUBJECT_DIR = DATA_ROOM / "Northwind_Logistics"


def test_atlas_config_loads_and_validates() -> None:
    """The golden deal config must load and parse cleanly."""
    config = load_deal_config(ATLAS / "deal-config.json")
    assert config.target.name == "Northwind Logistics Software"
    assert config.buyer.name == "Summit Industrial Group"
    assert config.forensic_dd.cross_domain.enabled is True


def test_atlas_data_room_is_complete() -> None:
    """All 11 source documents + the buyer reference must be present."""
    assert DATA_ROOM.is_dir(), "Project Atlas data room is missing"
    docs = sorted(p.name for p in SUBJECT_DIR.glob("*.md"))
    expected = {
        "arr_schedule.xlsx.md",
        "board_deck_excerpt.pdf.md",
        "cap_table_summary.pdf.md",
        "contractor_agreement_route_engine.pdf.md",
        "dpa_tidewater.pdf.md",
        "employment_ip_agreement.pdf.md",
        "msa_granite_manufacturing.pdf.md",
        "msa_harbor_foods.pdf.md",
        "msa_meridian_freight.pdf.md",
        "order_form_cobalt_retail.pdf.md",
        "subprocessor_register.pdf.md",
    }
    assert expected.issubset(set(docs)), f"missing Atlas docs: {expected - set(docs)}"
    assert (DATA_ROOM / "_reference" / "buyer_overview.pdf.md").is_file()


def test_atlas_config_path_points_at_data_room() -> None:
    """The config's data_room path must resolve to the committed data room."""
    config = load_deal_config(ATLAS / "deal-config.json")
    data_room = config.data_room
    path = data_room["path"] if isinstance(data_room, dict) else data_room.path
    assert "project-atlas/sample_data_room" in str(path).replace("\\", "/")


def test_hero_change_of_control_clause_present() -> None:
    """The hero cross-domain mechanic must remain extractable.

    The Meridian Freight MSA must contain a change-of-control clause, and the ARR
    schedule must show Meridian as a material (≈30%) customer — together these are what
    let the pipeline connect Legal→Finance into the P0 revenue-cliff finding.
    """
    meridian = (SUBJECT_DIR / "msa_meridian_freight.pdf.md").read_text(encoding="utf-8").lower()
    assert "change of control" in meridian
    assert "terminate" in meridian
    assert "12.3" in meridian, "the cited §12.3 anchor must remain in the Meridian MSA"

    arr = (SUBJECT_DIR / "arr_schedule.xlsx.md").read_text(encoding="utf-8").lower()
    assert "meridian" in arr
    assert "30.1%" in arr, "Meridian's material concentration figure must remain in the ARR schedule"


def test_atlas_data_room_is_synthetic() -> None:
    """Guard the no-real-data policy: the canonical synthetic names must be used."""
    blob = "\n".join(p.read_text(encoding="utf-8") for p in SUBJECT_DIR.glob("*.md")).lower()
    assert "northwind" in blob
    # signatory placeholders, never real names
    assert "signatory a" in blob or "signatory b" in blob


@pytest.mark.parametrize(
    "addr_fragment",
    ["easton commons", "south high street", "civic center drive"],
)
def test_atlas_address_continuity(addr_fragment: str) -> None:
    """All docs must use the one canonical HQ address (no stray variants)."""
    blob = "\n".join(p.read_text(encoding="utf-8") for p in SUBJECT_DIR.glob("*.md")).lower()
    assert addr_fragment not in blob, f"stray HQ address variant '{addr_fragment}' broke continuity"
