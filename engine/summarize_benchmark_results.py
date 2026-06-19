#!/usr/bin/env python3
"""
Summarize benchmark result JSON files produced by evaluate_benchmark.py.

Usage:
    python3 pipeline/summarize_benchmark_results.py
    python3 pipeline/summarize_benchmark_results.py --latest 5
    python3 pipeline/summarize_benchmark_results.py --best C2
    python3 pipeline/summarize_benchmark_results.py --json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).parent.parent
DEFAULT_RESULTS_DIR = REPO_ROOT / "benchmark" / "results"
COMPONENTS = ("C1", "C2", "C3")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Summarize benchmark result files")
    parser.add_argument(
        "--results-dir",
        type=Path,
        default=DEFAULT_RESULTS_DIR,
        help=f"Directory containing benchmark result JSON files (default: {DEFAULT_RESULTS_DIR})",
    )
    parser.add_argument(
        "--latest",
        type=int,
        default=0,
        help="Show only the latest N runs by filename timestamp",
    )
    parser.add_argument(
        "--best",
        choices=("overall", "C1", "C2", "C3"),
        default="overall",
        help="Sort key for best runs (default: overall)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON instead of a table",
    )
    return parser.parse_args()


def _extract_report(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text())
    except Exception:
        return None

    report = payload.get("report")
    if not isinstance(report, dict):
        return None
    if "overall_mean" not in report or "components" not in report:
        return None
    return report


def _component_mean(report: dict[str, Any], component: str) -> float:
    comp = report.get("components", {}).get(component, {})
    return float(comp.get("mean", 0.0))


def collect_rows(results_dir: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(results_dir.glob("*.json")):
        # Skip comparison reports; we want per-run scorecards.
        if path.name.startswith("comparison_"):
            continue

        report = _extract_report(path)
        if report is None:
            continue

        rows.append(
            {
                "file": path.name,
                "label": str(report.get("label", "")),
                "overall": float(report.get("overall_mean", 0.0)),
                "C1": _component_mean(report, "C1"),
                "C2": _component_mean(report, "C2"),
                "C3": _component_mean(report, "C3"),
                "all_pass": bool(report.get("all_pass", False)),
            }
        )

    return rows


def print_table(rows: list[dict[str, Any]]) -> None:
    if not rows:
        print("No benchmark report files found.")
        return

    header = (
        f"{'file':<42} {'overall':>7} {'C1':>5} {'C2':>5} {'C3':>5} {'pass':>6}"
    )
    print(header)
    print("-" * len(header))

    for r in rows:
        print(
            f"{r['file']:<42} "
            f"{r['overall']:>7.3f} {r['C1']:>5.3f} {r['C2']:>5.3f} {r['C3']:>5.3f} "
            f"{('yes' if r['all_pass'] else 'no'):>6}"
        )


def main() -> None:
    args = parse_args()

    rows = collect_rows(args.results_dir)
    if not rows:
        if args.json:
            print("[]")
        else:
            print("No benchmark report files found.")
        return

    sort_key = args.best
    rows.sort(key=lambda r: r[sort_key], reverse=True)

    if args.latest and args.latest > 0:
        # Keep latest by filename timestamp while preserving best-first ranking
        latest = sorted(rows, key=lambda r: r["file"], reverse=True)[: args.latest]
        latest_names = {r["file"] for r in latest}
        rows = [r for r in rows if r["file"] in latest_names]

    if args.json:
        print(json.dumps(rows, indent=2))
        return

    print(f"Runs: {len(rows)} | Ranked by: {sort_key}")
    print_table(rows)

    best = rows[0]
    print()
    print(
        "Best run: "
        f"{best['file']} | overall={best['overall']:.3f} "
        f"C1={best['C1']:.3f} C2={best['C2']:.3f} C3={best['C3']:.3f} "
        f"all_pass={'yes' if best['all_pass'] else 'no'}"
    )


if __name__ == "__main__":
    main()
