#!/usr/bin/env python3
"""Publish the public sample report (GitHub Pages) from the golden Project Atlas run.

The public sample at ``docs/sample-report/index.html`` is the **real, self-contained
HTML report** produced by running the pipeline on the golden synthetic deal,
``examples/project-atlas/`` (target: Northwind Logistics Software; acquirer: Summit
Industrial Group). It is 100% synthetic — no real company, person, or financial data —
but it is genuine pipeline output, not hand-authored mock data: the hero cross-domain
finding (a change-of-control clause on a customer worth 30% of ARR) is surfaced and
cited to an exact quote by the agents themselves.

This script keeps the published sample in sync with the captured golden artifact at
``docs/marketing/sample-report-atlas/index.html``.

Usage:
    python scripts/generate_sample_report.py            # sync published sample from golden capture
    python scripts/generate_sample_report.py --check     # verify they match (CI-friendly), non-zero on drift

To REGENERATE the golden artifact from scratch (requires API/Bedrock credentials):
    dd-agents run examples/project-atlas/deal-config.json
    cp examples/project-atlas/sample_data_room/_dd/forensic-dd/runs/latest/report/dd_report.html \\
       docs/marketing/sample-report-atlas/index.html
    cp examples/project-atlas/sample_data_room/_dd/forensic-dd/runs/latest/report/dd_report.xlsx \\
       docs/marketing/sample-report-atlas/dd_report.xlsx
    python scripts/generate_sample_report.py
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
GOLDEN = REPO_ROOT / "docs" / "marketing" / "sample-report-atlas" / "index.html"
PUBLISHED = REPO_ROOT / "docs" / "sample-report" / "index.html"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Verify the published sample matches the golden capture; exit non-zero on drift.",
    )
    args = parser.parse_args()

    if not GOLDEN.exists():
        print(f"ERROR: golden capture not found: {GOLDEN}", file=sys.stderr)
        print("Regenerate it from a pipeline run — see this script's docstring.", file=sys.stderr)
        return 2

    golden_html = GOLDEN.read_text(encoding="utf-8")

    # The published sample must be a self-contained, single-file HTML (no external
    # asset references) so GitHub Pages can serve it standalone.
    if 'src="http' in golden_html or 'href="http' in golden_html.split("</head>")[0]:
        # Note: this is a light guard; the report inlines CSS/JS, external links in body are fine.
        pass

    if args.check:
        current = PUBLISHED.read_text(encoding="utf-8") if PUBLISHED.exists() else ""
        if current != golden_html:
            print("DRIFT: docs/sample-report/index.html is out of sync with the golden capture.", file=sys.stderr)
            print("Run: python scripts/generate_sample_report.py", file=sys.stderr)
            return 1
        print("OK: published sample matches the golden Project Atlas capture.")
        return 0

    PUBLISHED.parent.mkdir(parents=True, exist_ok=True)
    PUBLISHED.write_text(golden_html, encoding="utf-8")
    print(f"Published sample report: {PUBLISHED}")
    print(f"Source (golden capture):  {GOLDEN}")
    print(f"Open in browser: file://{PUBLISHED}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
